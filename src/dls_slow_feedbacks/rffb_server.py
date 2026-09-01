import logging
from pathlib import Path
from typing import TypeAlias

import cothread
import numpy as np
import pytac
from cothread.catools import FORMAT_TIME, ca_nothing, caget, caput
from pytac.lattice import EpicsLattice
from scipy.io import loadmat
from softioc import builder

from dls_slow_feedbacks import constants, mode, rffb_calc

logger = logging.getLogger(name="dls_slow_feedbacks")

PVValueType: TypeAlias = int | float | np.ndarray | str

# Allowable difference between RF (master oscillator) setpoint and rbv
MAX_FREQ_DIFFERENCE_HZ = 100


class RffbServer:
    """IOC for RF Feedback

    Monitor BPMs and adjust the RF frequency to account for orbit feeback corrections.
    """

    def __init__(self, ring_mode: mode.RingMode) -> None:
        self.tick: int = 0
        self.power: int = 0  # ON=1/OFF=0
        self.rf_step: float = 0.1
        self.correction_period: int = 10
        self.bpm_response_matrix: np.ndarray | None = None
        self.dispersion_matrix: np.ndarray | None = None
        self.correctors = np.array(
            ring_mode.lattice.get_element_pv_names("HSTR", "x_kick", pytac.RB)
        )

        self.create_records()

        self.rf_freq_set_pv = PVWithValidity("LI-RF-MOSC-01:FREQ_SET")
        self.rf_freq_rbv_pv = PVWithValidity("LI-RF-MOSC-01:FREQ")

        ring_mode.add_listener(self.set_data_dir)

    def start(self) -> None:
        """Start the feedback loop."""
        cothread.Spawn(self.run)

    def run(self) -> None:
        """Main feedback loop."""
        logger.info("Rffb started")
        while True:
            cothread.Sleep(1.0)
            self.tick = (self.tick + 1) % 10

            if self.correction_period == 10 and self.tick != 0:
                continue

            if self.power:
                try:
                    self.apply_correction()

                except ca_nothing as e:
                    # A caget or caput failed
                    logger.exception("Channel access exception. RFFB will be stopped.")
                    self.pv_error.set(e.name)
                    self.calc_error.set(1)
                    self.power_pv.set(0)

                except BaseException:
                    logger.exception("Feedback error occurred.")
                    self.calc_error.set(1)
                    self.power_pv.set(0)

    def apply_correction(self) -> None:
        """Do final calculation and apply correction to PVs"""

        fbstat = caget("CS-CS-MSTAT-01:FBSTAT")
        ring_current = caget("SR-DI-DCCT-01:SIGNAL")
        enabled_bpms = caget("SR-DI-EBPM-01:ENABLED") == 0

        # Use all correctors, enabled or not, in RFFB.
        ncor = len(self.correctors)
        enabled_correctors = np.ones(ncor, dtype=bool)
        hcm = np.array(caget(self.correctors[enabled_correctors]))

        present_rf_demand = self.rf_freq_set_pv.get()
        present_rf_freq = self.rf_freq_rbv_pv.get()

        if self.bpm_response_matrix is not None and self.dispersion_matrix is not None:
            delta_rf_demand = rffb_calc.calc_rffb(
                self.bpm_response_matrix,
                self.dispersion_matrix,
                enabled_bpms,
                enabled_correctors,
                hcm,
            )
        else:
            raise ValueError("BPM response and/or dispersion matrices not loaded")

        target, target_limit = self._calculate_targets(
            present_rf_demand, delta_rf_demand
        )

        self.delta_pv.set(delta_rf_demand)
        self.target_pv.set(target)

        # Only caput if there are no errors
        if not self.check_for_errors(
            fbstat, ring_current, present_rf_freq, present_rf_demand
        ):
            caput("LI-RF-MOSC-01:FREQ_SET", target_limit)
            self.calc_error.set(0)
            self.pv_error.set("OK")

    def _calculate_targets(
        self, present_rf_demand: float, delta_rf_demand: float
    ) -> tuple:
        """Calculate the target RF frequency and limit."""

        def round10(x):
            return np.around(x * 10.0) / 10.0

        target = round10(present_rf_demand + delta_rf_demand)
        target_limit = target

        # If our demand is larger than our maximum step (self.rfstep) then we change the
        # target rf by either +/- 0.1
        if abs(delta_rf_demand) > self.rf_step:
            delta_rf_demand = np.sign(delta_rf_demand) * self.rf_step

        target_limit = round10(present_rf_demand + delta_rf_demand)
        # TODO: target should always be a float, but is sometimes a float in a numpy
        # array which we have to get it out of, investigate the root cause of this
        return target.item(), target_limit

    def check_for_errors(
        self, fbstat, current: float, present_rf_freq: float, present_rf_demand: float
    ) -> bool:
        """Check for conditions that would prevent RFFB from running."""
        if fbstat == 0:
            logger.critical("No orbit feedback is running. RFFB will be stopped.")
            self.power_pv.set(0)
            self.pv_error.set("No orbit feedback")
            return True

        if current <= 2:
            logger.critical("Beam current <= 2mA. RFFB will be stopped.")
            self.power_pv.set(0)
            self.pv_error.set("Current too low")
            return True

        # HLA-349: Discrepancy may indicate problem with master oscillator
        if not self.rf_near_setpoint(present_rf_freq, present_rf_demand):
            logger.critical(
                "Discrepancy between RF frequency and setpoint. RFFB will be stopped."
            )
            self.power_pv.set(0)
            self.pv_error.set(self.rf_freq_set_pv.get_name())
            return True

        if not self.rf_pvs_valid():
            logger.critical(
                f"RF PV was invalid > {PVWithValidity.ALLOWED_INVALID_CAGETS} times. "
                "RFFB will be stopped."
            )
            self.power_pv.set(0)
            return True

        return False

    @staticmethod
    def rf_near_setpoint(present_rf_freq: float, rf_setpoint: float) -> bool:
        """Return True if RF frequency and setpoint differ by
        less than a threshold.
        """
        frequency_difference_hz = abs(present_rf_freq - rf_setpoint)
        return frequency_difference_hz <= MAX_FREQ_DIFFERENCE_HZ

    def rf_pvs_valid(self) -> bool:
        """Check that RF FREQ and FREQ_SET PVs have both
        not been invalid too many times.
        """
        rf_pvs = [self.rf_freq_set_pv, self.rf_freq_rbv_pv]

        for rf_pv in rf_pvs:
            if not rf_pv.healthy():
                self.pv_error.set(rf_pv.get_name())
                return False

        return True

    def set_power(self, power: int) -> None:
        self.power = power

    def set_rf_step(self, rf_step: float) -> None:
        self.rf_step = rf_step

    def set_period(self, period: int) -> None:
        self.correction_period = period

    def set_data_dir(self, lattice: EpicsLattice, dataroot: Path) -> None:
        """Load the BPM response and dispersion matrices."""
        rffb_calc.cache.clear()
        path = dataroot / lattice.name
        self.correctors = np.array(
            lattice.get_element_pv_names("HSTR", "x_kick", pytac.RB)
        )
        try:
            raw_bpm_resp = loadmat(path / "GoldenBPMResp.mat")
            raw_disp = loadmat(path / "GoldenDisp.mat")
            self.bpm_response_matrix = raw_bpm_resp["Rmat"][0, 0]["Data"]
            self.dispersion_matrix = raw_disp["BPMxDisp"]["Data"][0, 0]

            self._validate_matrices(raw_bpm_resp, raw_disp)

            self.matrix_error.set(0)
            logger.info(f"Rffb loading {lattice.name}")
        except BaseException:
            logger.exception(f"Failed to load matrix data {lattice.name}")
            self.bpm_response_matrix = None
            self.dispersion_matrix = None
            self.matrix_error.set(1)

    def _validate_matrices(self, raw_bpm_resp: dict, raw_disp: dict) -> None:
        """Validate the BPM response and dispersion matrices."""
        if raw_bpm_resp["Rmat"][0, 0]["Units"] != "Hardware":
            raise ValueError("BPM response matrix is not set to hardware units")

        if raw_disp["BPMxDisp"]["Units"] != "Hardware":
            raise ValueError("Dispersion matrix is not set to hardware units")

    def create_records(self) -> None:
        """Define PV's for RF Feedback."""
        builder.SetDeviceName("SR-CS-RFFB-01")

        self.matrix_error = builder.boolIn(
            "EMATRIX",
            DESC="Matrix Error",
            initial_value=1,
            ZNAM="OK",
            ONAM="RFFB MATRIX",
        )

        self.calc_error = builder.boolIn(
            "ECALC",
            DESC="Calculation Error",
            initial_value=0,
            ZNAM="OK",
            ONAM="RFFB CALC",
        )

        self.pv_error = builder.stringIn("EPV", DESC="PV Error", initial_value="OK")

        self.power_pv = builder.mbbOut(
            "ONOFF", "OFF", "ON", initial_value=self.power, on_update=self.set_power
        )

        self.delta_pv = builder.aIn("DELTARF", initial_value=0, PREC=1, EGU="Hz")

        self.target_pv = builder.aIn("TARGET", initial_value=0, PREC=1, EGU="Hz")

        builder.aOut(
            "RFSTEP",
            initial_value=self.rf_step,
            on_update=self.set_rf_step,
            DRVH=100,
            DRVL=0.1,
            PREC=1,
            EGU="Hz",
        )

        builder.mbbOut(
            "PERIOD",
            "1 second",
            "10 seconds",
            initial_value=self.correction_period,
            on_update=self.set_period,
        )


class PVWithValidity:
    """For a PV, maintain a history of cagets in order to decide if current value is
    valid.
    """

    ALLOWED_INVALID_CAGETS: int = 10

    def __init__(self, pv_name: str) -> None:
        self.pv_name: str = pv_name
        self.consecutive_times_invalid: int = 0
        self.ok: bool = False
        self.last_caget_time = None
        self.severity = None

    def get(self) -> PVValueType:
        """Do a caget, store the severity and ok status and return the result.
        Do not store the caget value to prevent stale data."""

        # Do caget and store attributes
        value = cothread.catools.caget(self.pv_name, format=FORMAT_TIME)
        self.severity = value.severity
        self.ok = value.ok
        self.last_caget_time = value.timestamp

        # Check alarm severity not OK and increment counter
        if self.severity != constants.SEVR_NO_ALARM or not self.ok:
            self.consecutive_times_invalid += 1
        else:
            self.consecutive_times_invalid = 0

        return value

    def healthy(self) -> bool:
        """Return False if too many cagets have returned a PV alarm status."""
        if self.consecutive_times_invalid <= self.ALLOWED_INVALID_CAGETS:
            return True
        else:
            logger.warning(
                f"{self.pv_name} raised an alarm more than "
                "{self.ALLOWED_INVALID_CAGETS} times."
            )
            return False

    def get_name(self) -> str:
        """Return PV name."""
        return self.pv_name
