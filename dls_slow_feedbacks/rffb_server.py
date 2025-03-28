import logging
import os
import traceback
from typing import Optional

import cothread
import numpy as np
import pytac
from cothread.catools import FORMAT_TIME, ca_nothing, caget, caput
from pytac.lattice import EpicsLattice
from scipy.io import loadmat
from softioc import builder

from dls_slow_feedbacks import constants, mode, rffb_calc

MAX_FREQ_DIFFERENCE = 100  # Allowable difference between RF setpoint and rbv, Hz


class PVWithValidity:
    """For a PV, maintain a history of cagets
    in order to decide if current value is valid.
    """

    ALLOWED_INVALID_CAGETS: int = 10

    def __init__(self, pv_name) -> None:
        self.pv_name: str = pv_name
        self.consecutive_times_invalid: int = 0
        self.ok: bool = False
        self.last_caget_time = None
        self.severity = None

    def get(self):
        """Do a caget, store the value and severity.

        Return the result of the caget. Does not store it to prevent stale data."""

        # Do caget and store attributes
        value = caget(self.pv_name, format=FORMAT_TIME)
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
        """Return False if too many cagets have returned alarm."""
        if self.consecutive_times_invalid <= self.ALLOWED_INVALID_CAGETS:
            return True
        else:
            logging.warning(
                "{pv_name} had alarm more than {count} times".format(
                    pv_name=self.pv_name, count=self.ALLOWED_INVALID_CAGETS
                )
            )
            return False

    def get_name(self) -> str:
        """Return PV name."""
        return self.pv_name


class RffbServer:
    def __init__(self, ring_mode: mode.RingMode) -> None:
        self.tick: int = 0
        self.power: int = 0  # ON/OFF
        self.rf_step: float = 0.1
        self.period: int = 10
        self.bpm_resp: Optional[np.ndarray] = None
        self.disp: Optional[np.ndarray] = None
        self.correctors = np.array(
            ring_mode.lattice.get_element_pv_names("HSTR", "x_kick", pytac.RB)
        )

        self.create_records()
        self.set_data_dir(ring_mode.lattice)

        self.rf_freq_set_pv = PVWithValidity("LI-RF-MOSC-01:FREQ_SET")
        self.rf_freq_rbv_pv = PVWithValidity("LI-RF-MOSC-01:FREQ")

        ring_mode.add_listener(self.set_data_dir)

    def start(self) -> None:
        """Start the feedback loop."""
        cothread.Spawn(self.run)

    def run(self) -> None:
        """Main feedback loop."""
        while True:
            cothread.Sleep(1.0)
            self.tick = (self.tick + 1) % 10

            if self.period == 10 and self.tick != 0:
                continue

            try:
                self.run_feedback()

            except ca_nothing as e:
                print("Channel access exception: RFFB will be stopped.")
                print(e)
                self.pv_error.set(e.name)
                self.calc_error.set(1)
                self.power_pv.set(0)

            except BaseException:
                traceback.print_exc()
                self.calc_error.set(1)
                self.power_pv.set(0)

    def run_feedback(self) -> None:
        """Adjust the RF frequency to relieve orbit feeback correction"""
        fbstat = caget("CS-CS-MSTAT-01:FBSTAT")
        current = caget("SR-DI-DCCT-01:SIGNAL")
        enabled_bpm = caget("SR-DI-EBPM-01:ENABLED") == 0

        # Use all correctors, enabled or not, in RFFB.
        ncor = len(self.correctors)
        enabled_cor = np.ones(ncor, dtype=bool)
        hcm = np.array(caget(self.correctors[enabled_cor]))

        present_rf_demand = self.rf_freq_set_pv.get()
        present_rf_freq = self.rf_freq_rbv_pv.get()

        if self.bpm_resp is not None and self.disp is not None:
            delta_rf_demand = rffb_calc.calc_rffb(
                self.bpm_resp, self.disp, enabled_bpm, enabled_cor, hcm
            )
        else:
            raise ValueError("BPM response and/or dispersion matrices not loaded")

        target, target_limit = self._calculate_targets(
            present_rf_demand, delta_rf_demand
        )

        self.delta_pv.set(delta_rf_demand)
        self.target_pv.set(target)

        # Only caput if feedback loop is on and there are no errors
        if self.power and not self.check_for_errors(
            fbstat, current, present_rf_freq, present_rf_demand
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

        if abs(delta_rf_demand) > self.rf_step:
            delta_rf_demand = np.sign(delta_rf_demand) * self.rf_step

        target_limit = round10(present_rf_demand + delta_rf_demand)

        return target, target_limit

    def check_for_errors(
        self, fbstat, current: float, present_rf_freq: float, present_rf_demand: float
    ) -> bool:
        """Check for conditions that would prevent RFFB from running."""
        if fbstat == 0:
            logging.fatal("No orbit feedback is running. " "RFFB will be stopped.")
            self.power_pv.set(0)
            self.pv_error.set("No orbit feedback")
            return True

        if current <= 2:
            logging.fatal("Beam current <= 2mA. RFFB will be stopped.")
            self.power_pv.set(0)
            self.pv_error.set("Current too low")
            return True

        # HLA-349
        if not self.rf_near_setpoint(present_rf_freq, present_rf_demand):
            logging.fatal(
                "Discrepancy between RF frequency and setpoint. "
                "RFFB will be stopped."
            )
            self.power_pv.set(0)
            self.pv_error.set(self.rf_freq_set_pv.get_name())
            return True

        if not self.rf_pvs_valid():
            logging.fatal(
                "RF PV was invalid > {count} times. "
                "RFFB will be stopped.".format(
                    count=PVWithValidity.ALLOWED_INVALID_CAGETS
                )
            )
            self.power_pv.set(0)
            return True

        return False

    @staticmethod
    def rf_near_setpoint(present_rf_freq: float, rf_setpoint: float) -> bool:
        """Return True if RF frequency and setpoint differ by
        less than a threshold.
        """
        frequency_difference = abs(present_rf_freq - rf_setpoint)
        return frequency_difference <= MAX_FREQ_DIFFERENCE

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
        self.period = period

    def set_data_dir(self, lattice: EpicsLattice) -> None:
        """Load the BPM response and dispersion matrices."""
        rffb_calc.cache.clear()
        path = os.path.join(mode.DATAROOT, lattice.name)
        self.correctors = np.array(
            lattice.get_element_pv_names("HSTR", "x_kick", pytac.RB)
        )
        try:
            raw_bpm_resp = loadmat(os.path.join(path, "GoldenBPMResp"))
            raw_disp = loadmat(os.path.join(path, "GoldenDisp"))
            self.bpm_resp = raw_bpm_resp["Rmat"][0, 0]["Data"]
            self.disp = raw_disp["BPMxDisp"]["Data"][0, 0]

            self._validate_matrices(raw_bpm_resp, raw_disp)

            self.matrix_error.set(0)
            print(f"RFFB loaded matrix {lattice.name}")

        except BaseException:
            traceback.print_exc()
            self.bpm_resp = None
            self.disp = None
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
            initial_value=self.period,
            on_update=self.set_period,
        )
