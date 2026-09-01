import logging
import time
from pathlib import Path

import cothread
import numpy as np
import scipy
import scipy.io
from cothread.catools import FORMAT_TIME, ca_nothing, caget, caput
from pytac.lattice import EpicsLattice
from softioc import alarm, builder

from dls_slow_feedbacks.mode import D2_RING_MODES
from dls_slow_feedbacks.tunefb_offsets import (
    D2_TUNE_QUAD_FAMILIES,
    TUNE_QUAD_FAMILIES,
    all_forwarded,
    load_magnet_pvs,
    rename_pvs,
)

logger = logging.getLogger(name="dls_slow_feedbacks")
np.set_printoptions(precision=4)


# Configuration file
GOLDEN_TUNE_CONFIG = "/home/ops/diagnostics/config/MBF_tune.config"

# Our IOC name
IOC = "SR-CS-TFB-01"

# PV names
TUNE_PVS = ["SR23C-DI-TMBF-01:TUNE:TUNE", "SR23C-DI-TMBF-02:TUNE:TUNE"]
CURRENT_PV = "SR-DI-DCCT-01:SIGNAL"

# Constants
BEAM_DAMP_TIME = 0.01  # seconds
OFFSET_CURRENT_CHANGED = "Offset changed outside of TFB"

# Default values
MAX_CURRENT_OFFSET = 0.2  # Amps
MAX_CONSECUTIVE_INVALIDS = 5


class Status:
    """Enum for tune feedback errors."""

    FEEDBACK_OFF = 0
    FEEDBACK_ON = 1
    FEEDBACK_SCALING = 2
    SINGLE_CORR = 3
    SINGLE_SCALED = 4
    MAGNET_CURRENT = 5
    TUNE_RANGE = 6
    TUNE_VALIDITY = 7
    TUNE_UPDATE = 8
    LOW_CURRENT = 9
    TUNE_STEP = 10
    UNEXPECTED_ERROR = 11

    STRINGS = {
        FEEDBACK_OFF: ("Feedback off", "NO_ALARM"),
        FEEDBACK_ON: ("Feedback running", "NO_ALARM"),
        FEEDBACK_SCALING: ("Feedback running: scaled", "NO_ALARM"),
        SINGLE_CORR: ("Single correction applied", "NO_ALARM"),
        SINGLE_SCALED: ("Single correction: scaled", "NO_ALARM"),
        MAGNET_CURRENT: ("Magnet current error", "MAJOR"),
        TUNE_RANGE: ("Tunes outside valid range", "MINOR"),
        TUNE_VALIDITY: ("Tune measurement invalid", "MINOR"),
        TUNE_UPDATE: ("Tune PV not updated", "MINOR"),
        LOW_CURRENT: ("Beam current is too low", "MAJOR"),
        TUNE_STEP: ("Tune step applied", "NO_ALARM"),
        UNEXPECTED_ERROR: ("Unexpected error", "MAJOR"),
    }


class TunefbInvalidError(Exception):
    """Exception used to pause tune feedback."""

    def __init__(self, code):
        Exception.__init__(self, Status.STRINGS[code])
        self.code = code


class TunefbError(Exception):
    """Exception used to stop tune feedback."""

    def __init__(self, code):
        Exception.__init__(self, Status.STRINGS[code])
        self.code = code


class TunefbServer:
    """Server for tune feedback. Creates PVs, and monitors and then
    corrects tune towards a setpoint.
    """

    def __init__(self, ring_mode):
        """Fetch data from files and set up soft IOC."""
        # Initial values for PVs
        self.afrac = 0.2
        self.max_current_range = MAX_CURRENT_OFFSET
        self.min_beam_current = 1.0
        self.period = 1.0
        self.last_error = None

        # Whether the last correction was scaled
        self.scaling = False
        # Tune data - Golden tunes are set from ringmode
        self.golden_tunes = np.array([0.0, 0.0])
        self.mag_delta_max = 0.01
        self.tunes = np.zeros(2)
        self.tune_deltas = np.zeros(2)
        # Count consecutive invalid exceptions to eventually trip
        self.invalid_counter = 0

        # Load magnet PVs from Pytac
        self.mag_pvs = load_magnet_pvs(ring_mode.lattice)
        self.local_pvs = rename_pvs(self.mag_pvs)

        # List of references to locally hosted mirror PVs, created
        # in self.records()
        self.mirror_pvs = []

        # Load data from files (and on ringmode change)
        self.rm = None
        self.irm = None
        if self.set_data_dir not in ring_mode.listeners:
            ring_mode.add_listener(self.set_data_dir)

        self.startup_currents = self.setup_startup_currents()
        self.integrated_current = np.array(self.startup_currents)
        self.integrated_tunes = np.zeros(2)

        # Initalise EPICS records
        self.records()

    def setup_startup_currents(self):
        # fetch values from the PVs we will be mirroring, before
        # starting up.
        startup_currents = caget([pv + ":OFFSET1" for pv in self.mag_pvs], throw=False)
        for i in range(len(startup_currents)):
            if not startup_currents[i].ok:
                logger.warning(f"Unable to read {startup_currents[i].name}")
                startup_currents[i] = 0
        return startup_currents

    def set_data_dir(self, lattice: EpicsLattice, dataroot: Path) -> None:
        """Load required data from files in datadir."""
        # Load magnet PVs from Pytac
        self.mag_pvs = load_magnet_pvs(lattice)
        self.local_pvs = rename_pvs(self.mag_pvs)
        self.startup_currents = self.setup_startup_currents()
        self.integrated_current = np.array(self.startup_currents)
        self.integrated_tunes = np.zeros(2)

        # Load data from file
        mode_dir = dataroot / lattice.name
        self.rm = self.load_tune_rm(lattice.name, mode_dir / "GoldenTuneResp.mat")
        logger.info(f"Tunefb loading {lattice.name}")
        # Invert response matrix
        self.irm = np.linalg.pinv(self.rm)

        # Load tune config file into environment
        env = {}
        logger.debug(f"Reading tune setpoints from: {GOLDEN_TUNE_CONFIG}")
        with open(GOLDEN_TUNE_CONFIG) as f:
            exec(f.read(), env)

        # Select correct tune based on ringmode
        # tune_h = env["X_tune_" + lattice.name]
        # tune_v = env["Y_tune_" + lattice.name]
        tune_h = 0.14
        tune_v = 0.2402

        # Invert response matrix
        self.irm = np.linalg.pinv(self.rm)

        # Update PV values.
        self.tune_h_pv.set(tune_h)
        self.tune_v_pv.set(tune_v)
        logger.info(f"Tune targets set to: x={tune_h} y={tune_v}")
        self.update_max_i_pv()

        self.integrated_tunes = np.dot(self.rm, self.integrated_current)
        self.tune_int_h_pv.set(self.integrated_tunes[0])
        self.tune_int_v_pv.set(self.integrated_tunes[1])

    def load_tune_rm(self, ringmode: str, mat_file: Path):
        """Load response matrix from the specific format found
        in the specified file.
        """
        if ringmode in D2_RING_MODES:
            families = D2_TUNE_QUAD_FAMILIES
        else:
            families = TUNE_QUAD_FAMILIES

        raw_rms = scipy.io.loadmat(mat_file)

        # Construct complete response matrix.
        rmx = []
        rmy = []
        rmats = []

        # We build the response matrix out of the tune quad families, making sure
        # that they are ordered in the same order as defined elsewhere.
        for family in families:
            for rmat in raw_rms["Rmat"][0]:
                rmat_family = str(rmat["Actuator"][0][0][0][0][1][0])
                if rmat_family == family:
                    print(f"Adding family {family}")
                    rmats.append(rmat)
                    break

        for raw_rm in rmats:
            raw_rmx = raw_rm[0][0][0][0]
            raw_rmy = raw_rm[0][0][0][1]
            rmx.extend(raw_rmx)
            rmy.extend(raw_rmy)

        return np.array([rmx, rmy])

    def start(self) -> None:
        """Spawn a new thread to run the main ioc loop."""
        cothread.Spawn(self.run)

    def run(self) -> None:
        """Top level loop in the ioc, if it terminates then
        a restart of the ioc is required. Therefore, it is appropriate
        to catch all exceptions.
        """
        logger.info("Tunefb started")
        while True:
            cothread.Sleep(self.period)
            try:
                self.loop_correction()
            except Exception as e:
                # stop feedback and print stack trace
                logger.exception(f"Unexpected exception: {str(e)}")
                self.power_pv.set(False)
                self.status_pv.set(Status.UNEXPECTED_ERROR)

    def loop_correction(self) -> None:
        """If key parameters are within expected ranges and power is true, attempts to
        do a correction. This is run periodically"""
        self.update_max_i_pv()
        self.update_fwd_ok_pv()
        try:
            if self.power_pv.get():
                self.checked_correction()
                if self.scaling:
                    self.status_pv.set(Status.FEEDBACK_SCALING)
                else:
                    self.status_pv.set(Status.FEEDBACK_ON)
                self.invalid_counter = 0
            else:
                if self.status_pv.get() in (
                    Status.FEEDBACK_ON,
                    Status.FEEDBACK_SCALING,
                ):
                    self.status_pv.set(Status.FEEDBACK_OFF)
        except TunefbInvalidError as e:
            # skip corrections for a while before tripping off
            self.invalid_counter += 1
            if self.invalid_counter >= MAX_CONSECUTIVE_INVALIDS:
                self.trip_feedback(e)
            if self.status_pv.get() != e.code:
                self.status_pv.set(e.code)
                logger.warning(f"Tune feedback paused: {str(e)}")
        except TunefbError as e:
            self.trip_feedback(e)

    def trip_feedback(self, exception) -> None:
        """Take the appropriate action when a trip occurs."""
        self.power_pv.set(False)
        self.status_pv.set(exception.code)
        logger.error(f"Feedback tripped: {str(exception)}")

    def check_current(self) -> None:
        """Check if current is greater than a mininum current."""
        if caget(CURRENT_PV) < self.min_beam_current:
            raise TunefbError(Status.LOW_CURRENT)

    def refresh_tune_deltas(self) -> None:
        """Update values for tune deltas, checking if the values are
        reliable.
        """
        tunes = caget(TUNE_PVS, format=FORMAT_TIME)
        # Store tunes in cothread wrapper to allow severity checking
        self.tunes = tunes
        tune_array = np.array(tunes)
        # This will succeed as long as the TMBF updates the tune PVs
        # more often than self.period
        last_check = time.time() - self.period
        if any([tune.timestamp < last_check for tune in tunes]):  # noqa: C419
            raise TunefbInvalidError(Status.TUNE_UPDATE)
        if np.isnan(tune_array).any():
            logger.warning("Tune value NaN but PV not invalid.")
            raise TunefbInvalidError(Status.TUNE_VALIDITY)
        logger.debug(f"Tune delta before last correction {self.tune_deltas}")
        logger.debug(
            f"Tune change since last correction {str(tune_array - self.tunes)}"
        )
        self.tune_deltas = self.golden_tunes - tune_array
        logger.debug(f"Actual tune deltas {self.tune_deltas}")

    def check_tune_alarms(self, max_alarm=alarm.MINOR_ALARM) -> None:
        if any(tune.severity >= max_alarm for tune in self.tunes):
            raise TunefbInvalidError(Status.TUNE_VALIDITY)

    def scale_deltas(self, deltas) -> None:
        """Put delta correction to magnets, clipping if neccassary."""
        # Scale values over the step current limit
        if any(abs(deltas) > self.mag_delta_max):
            factor = self.mag_delta_max / abs(deltas).max()
            deltas *= factor
            self.scaling = True
            logger.debug(f"Using clipping factor: {factor}")
        else:
            self.scaling = False
        return deltas

    def check_mag_limits(self, currents) -> None:
        max_i = max(abs(i) for i in currents)
        if max_i > self.max_current_range:
            logger.debug(f"Max current offset: {max_i}")
            logger.debug(f"Current offset limit: {self.max_current_range}")
            raise TunefbError(Status.MAGNET_CURRENT)

    def apply_correction(self, deltas) -> None:
        """Do final calculations and apply corrections to PVs."""
        calc_tune_corr = np.dot(self.rm, deltas)
        logger.debug(f"Theoretical tune correction {str(calc_tune_corr)}")
        self.integrated_tunes += calc_tune_corr
        self.tune_int_h_pv.set(self.integrated_tunes[0])
        self.tune_int_v_pv.set(self.integrated_tunes[1])
        logger.debug(f"Calculated current deltas:\n{str(deltas)}")
        # Refresh integrated currents so they match their PVs.
        fetched_current = np.array([pv.get() for pv in self.mirror_pvs])
        if any(fetched_current - self.integrated_current):
            logger.warning(f"{OFFSET_CURRENT_CHANGED}")

        self.integrated_current = fetched_current + deltas
        if np.isnan(self.integrated_current).any():
            logger.warning("Unexpected NaN in calculated current correction.")
            raise TunefbError(Status.UNEXPECTED_ERROR)
        for pv, current in zip(self.mirror_pvs, self.integrated_current, strict=True):
            pv.set(current)
        logger.debug(f"Total tune change from feedback {str(self.integrated_tunes)}")

    def checked_correction(self) -> None:
        """Calculate and then apply a correction, will throw an execption
        in the event of an invalid or error state.
        """
        self.check_current()
        self.refresh_tune_deltas()
        self.check_tune_alarms(max_alarm=alarm.MINOR_ALARM)
        mag_deltas = self.afrac * np.dot(self.irm, self.tune_deltas)
        scaled_deltas = self.scale_deltas(mag_deltas)
        # Check if offset currents have been exceeded
        self.check_mag_limits(self.integrated_current)
        self.apply_correction(scaled_deltas)

    def unchecked_correction(self, dummy) -> None:
        """Calculate and apply correction without checking beam current.
        Catches all invalid and error states.
        """
        try:
            logger.info("Single correction pressed")
            # This is here only to give visual feedback when pressing the
            # single correction button
            self.status_pv.set(Status.FEEDBACK_OFF)
            cothread.Sleep(0.3)
            self.refresh_tune_deltas()
            self.check_tune_alarms(max_alarm=alarm.INVALID_ALARM)
            mag_deltas = self.afrac * np.dot(self.irm, self.tune_deltas)
            scaled_deltas = self.scale_deltas(mag_deltas)
            self.apply_correction(scaled_deltas)
            self.corr_toggle_pv.set(1 - self.corr_toggle_pv.get())
            # This sleep is also necessary to see the above status change
            # in the GUI
            cothread.Sleep(0.2)
            if self.scaling:
                self.status_pv.set(Status.SINGLE_SCALED)
            else:
                self.status_pv.set(Status.SINGLE_CORR)
        except TunefbInvalidError as e:
            logger.warning("" + str(e))
            self.status_pv.set(e.code)
        except TunefbError as e:
            logger.error("" + str(e))
            self.status_pv.set(e.code)
        except Exception as e:
            logger.error(f"Unexpected exception: {str(e)}")
            self.status_pv.set(Status.UNEXPECTED_ERROR)

    def step_tune(self, dummy) -> None:
        """Apply raw correction without checking beam current.
        Catches all invalid and error states.
        """
        try:
            # This is here only to give visual feedback when pressing the
            # single correction button
            self.status_pv.set(Status.FEEDBACK_OFF)
            cothread.Sleep(0.3)
            # Apply tune change according to step PVs.
            deltas = (self.hstep_pv.get(), self.vstep_pv.get())
            mag_deltas = np.dot(self.irm, deltas)
            self.apply_correction(mag_deltas)
            logger.info("Completed tune step")
            self.step_toggle_pv.set(1 - self.step_toggle_pv.get())

            # This sleep is also necessary to see the above status change
            # in the GUI
            cothread.Sleep(0.2)
            self.status_pv.set(Status.TUNE_STEP)
        except TunefbInvalidError as e:
            logger.warning(f"{str(e)}")
            self.status_pv.set(e.code)
        except TunefbError as e:
            logger.error(f"{str(e)}")
            self.status_pv.set(e.code)
        except Exception as e:
            logger.error(f"Unexpected exception: {str(e)}")
            self.status_pv.set(Status.UNEXPECTED_ERROR)

    def reset_error(self, dummy) -> None:
        """Reset the error pv."""
        self.status_pv.set(Status.FEEDBACK_OFF)
        self.reset_pv.set(0)
        self.invalid_counter = 0

    def _reset_state(self) -> None:
        """Set internal current and tune state to zero."""
        self.tune_int_h_pv.set(0)
        self.tune_int_v_pv.set(0)
        self.integrated_tunes = np.zeros(2)
        self.integrated_current = np.zeros(self.integrated_current.shape)

    def reset_integrated_current(self, value) -> None:
        """Set all integrated currents to zero."""
        if value:
            self.reset_integrated_current_pv.set(0)
            # Set our local PVs and currents to zero
            for pv in self.mirror_pvs:
                pv.set(0)
                cothread.Sleep(BEAM_DAMP_TIME)
            logger.warning("All integrated currents were reset to zero")
            self._reset_state()

    def aggregate_setpoints(self, value) -> None:
        """Move offsets from this ioc to the quadrupole setpoints."""
        if value:
            self.aggregate_pv.set(0)
            # Forward setpoint values one at a time to prevent beam dump
            for i, pv in enumerate(self.mag_pvs):
                pv = pv + ":SETI"
                caput(pv, caget(pv) + self.integrated_current[i])
                self.mirror_pvs[i].set(0)
                cothread.Sleep(BEAM_DAMP_TIME)
            logger.warning("Aggregated offsets into setpoints")
            self._reset_state()

    def update_max_i_pv(self) -> None:
        """Update value and severity of IMAX PV."""
        value = max(abs(i) for i in self.integrated_current)
        if value > self.max_current_range:
            sev = alarm.MAJOR_ALARM
        elif value > 0.8 * self.max_current_range:
            sev = alarm.MINOR_ALARM
        else:
            sev = alarm.NO_ALARM
        self.max_i_pv.set(value, severity=sev)

    def update_fwd_ok_pv(self) -> None:
        """Update value and severity of FWDOK PV."""
        try:
            if not all_forwarded(self.local_pvs, self.mag_pvs):
                self.fwd_ok_pv.set(1)
            else:
                self.fwd_ok_pv.set(0)
        except ca_nothing:
            self.fwd_ok_pv.set(2)

    def set_afrac(self, value) -> None:
        self.afrac = value

    def set_max_current_range(self, value) -> None:
        self.max_current_range = value

    def set_min_beam_current(self, value) -> None:
        self.min_beam_current = value

    def set_period(self, value) -> None:
        self.period = value

    def set_tune_h(self, value) -> None:
        self.golden_tunes[0] = value

    def set_tune_v(self, value) -> None:
        self.golden_tunes[1] = value

    def set_mag_delta_max(self, value) -> None:
        self.mag_delta_max = value

    def records(self) -> None:
        """Setup iocbuilder to create required records."""
        builder.SetDeviceName(IOC)
        self.power_pv = builder.boolOut("ONOFF", "OFF", "ON", initial_value=False)
        self.reset_pv = builder.aOut(
            "RESET", initial_value=0, on_update=self.reset_error
        )
        self.aggregate_pv = builder.aOut(
            "AGGREGATE", initial_value=0, on_update=self.aggregate_setpoints
        )
        self.reset_integrated_current_pv = builder.aOut(
            "RESETCORR", initial_value=0, on_update=self.reset_integrated_current
        )
        self.tune_h_pv = builder.aOut(
            "TUNE:H",
            initial_value=self.golden_tunes[0],
            on_update=self.set_tune_h,
            PREC=4,
        )
        self.tune_v_pv = builder.aOut(
            "TUNE:V",
            initial_value=self.golden_tunes[1],
            on_update=self.set_tune_v,
            PREC=4,
        )
        self.tune_int_h_pv = builder.aOut(
            "TUNE:HINT", initial_value=self.integrated_tunes[0], PREC=4
        )
        self.tune_int_v_pv = builder.aOut(
            "TUNE:VINT", initial_value=self.integrated_tunes[1], PREC=4
        )
        self.hstep_pv = builder.aOut("TUNE:HSTEP", initial_value=0, PREC=4)
        self.vstep_pv = builder.aOut("TUNE:VSTEP", initial_value=0, PREC=4)
        self.corr_toggle_pv = builder.aIn("CORR:TOGGLE", initial_value=0, PREC=4)
        builder.aOut(
            "CORR",
            initial_value=0,
            on_update=self.unchecked_correction,
            always_update=True,
        )
        builder.aOut(
            "STEPTUNE", initial_value=0, on_update=self.step_tune, always_update=True
        )
        self.step_toggle_pv = builder.aIn("STEP:TOGGLE", initial_value=0, PREC=4)
        builder.aOut(
            "AFRAC", initial_value=self.afrac, on_update=self.set_afrac, PREC=4
        )
        builder.aOut(
            "PERIOD", initial_value=self.period, on_update=self.set_period, PREC=4
        )
        builder.aOut(
            "OFFSETLIM",
            initial_value=self.max_current_range,
            on_update=self.set_max_current_range,
            PREC=4,
        )
        self.max_i_pv = builder.aIn("OFFSETMAX", initial_value=0.0, PREC=4)
        self.fwd_ok_pv = builder.mbbOut(
            "FWDOK",
            ("OK", "NO_ALARM"),
            ("NOT FORWARDED", "MINOR"),
            ("IOC DOWN", "MAJOR"),
            initial_value=0,
        )
        builder.aOut(
            "BEAMMIN",
            initial_value=self.min_beam_current,
            on_update=self.set_min_beam_current,
            PREC=4,
        )
        builder.aOut(
            "IDELTA",
            initial_value=self.mag_delta_max,
            on_update=self.set_mag_delta_max,
            PREC=4,
        )

        # initialise each current PV to the value from the remote
        # PV from which it will be starting
        for pv, value in zip(self.local_pvs, self.startup_currents, strict=True):
            self.mirror_pvs.append(
                builder.aOut(pv.split(":")[1] + ":I", initial_value=value)
            )

        # Pass all values from the enum into the status PV
        num_statuses = len(Status.STRINGS)
        status_args = ["STATUS"] + [
            Status.STRINGS[code] for code in range(num_statuses)
        ]
        self.status_pv = builder.mbbOut(*status_args, initial_value=Status.FEEDBACK_OFF)
