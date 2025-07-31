import logging
import os
import traceback

import cothread
import numpy
import pytac
from cothread import catools
from scipy.io import loadmat
from softioc import builder

from dls_slow_feedbacks import constants, mode, rffb_calc

"IOC for RF Feedback"

logger = logging.getLogger(name="dls_slow_feedbacks")

# Constants
MAX_DIFFERENCE_Hz = 100  # Allowable difference between RF setpoint and rbv


class RffbServer(object):
    def __init__(self, ring_mode):
        self.tick = 0
        self.power = 0
        self.rfstep = 0.1
        self.period = 10
        self.correctors = numpy.array(
            ring_mode.lattice.get_element_pv_names("HSTR", "x_kick", pytac.RB)
        )

        self.records()

        self.rf_freq_set_pv = PVWithValidity("LI-RF-MOSC-01:FREQ_SET")
        self.rf_freq_rbv_pv = PVWithValidity("LI-RF-MOSC-01:FREQ")

        ring_mode.add_listener(self.set_datadir)

    def init(self):
        cothread.Spawn(self.timer)

    def timer(self):

        while True:

            cothread.Sleep(1.0)
            self.tick = (self.tick + 1) % 10

            if self.period == 10 and self.tick != 0:
                continue

            try:
                self.feedback()
            except catools.ca_nothing as e:
                # A caget or caput failed
                logger.exception(f"Channel access exception. RFFB will be stopped.")
                self.pv_error.set(e.name)
                self.calc_error.set(1)
                self.power_pv.set(0)
            except BaseException:
                logger.exception("Feedback error occurred.")
                self.calc_error.set(1)
                self.power_pv.set(0)

    def feedback(self):

        # Check if either SOFB or FOFB is running
        fbstat = catools.caget("CS-CS-MSTAT-01:FBSTAT")
        # Use all correctors, enabled or not, in RFFB.
        ncor = len(self.correctors)
        enabled_cor = numpy.ones(ncor, dtype=numpy.bool)
        enabled_bpm = catools.caget("SR-DI-EBPM-01:ENABLED") == 0
        current = catools.caget("SR-DI-DCCT-01:SIGNAL")

        hcm = numpy.array(catools.caget(self.correctors[enabled_cor]))
        present_rf_demand = self.rf_freq_set_pv.get()
        present_rf_freq = self.rf_freq_rbv_pv.get()

        delta_rf_demand = rffb_calc.calc_rffb(
            self.bpmresp, self.disp, enabled_bpm, enabled_cor, hcm
        )
        self.delta_pv.set(delta_rf_demand)

        def round10(x):
            return numpy.around(x * 10.0) / 10.0

        target = round10(present_rf_demand + delta_rf_demand)
        if abs(delta_rf_demand) > self.rfstep:
            delta_rf_demand = numpy.sign(delta_rf_demand) * self.rfstep
        target_limit = round10(present_rf_demand + delta_rf_demand)

        # update status
        self.target_pv.set(target)

        # Only do checks and caput if feedback loop is on
        if self.power:

            # turn off feedback loop with no orbit loop
            if fbstat == 0:
                logger.fatal("No orbit feedback is running. RFFB will be stopped.")
                self.power_pv.set(0)
                self.pv_error.set("No orbit feedback")
                return

            # turn off feedback loop below 2mA
            if current <= 2:
                logger.fatal("Beam current <= 2mA. RFFB will be stopped.")
                self.power_pv.set(0)
                self.pv_error.set("Current too low")
                return

            # HLA-349: Check for discrepancy between present RF frequency and
            # setpoint; indicates problem with master oscillator
            if not self.rf_near_setpoint(present_rf_freq, present_rf_demand):
                logger.fatal(
                    "Discrepancy between RF frequency and setpoint. RFFB will be stopped."
                )
                self.power_pv.set(0)
                self.pv_error.set(self.rf_freq_set_pv.get_name())
                return

            if not self.rf_pvs_valid():
                logger.fatal(
                    f"RF PV was invalid > {PVWithValidity.ALLOWED_INVALID_CAGETS} times. RFFB will be stopped."
                )
                self.power_pv.set(0)
                return

            # channel access write
            catools.caput("LI-RF-MOSC-01:FREQ_SET", target_limit)

            self.calc_error.set(0)
            self.pv_error.set("OK")

    @staticmethod
    def rf_near_setpoint(present_rf_freq, rf_setpoint):
        """Returns True if RF frequency and setpoint differ by
        less than a threshold
        """
        frequency_difference_Hz = abs(present_rf_freq - rf_setpoint)
        return frequency_difference_Hz <= MAX_DIFFERENCE_Hz

    def rf_pvs_valid(self):
        """RF FREQ and FREQ_SET PVs have both not been invalid too many times"""

        rf_pvs = [self.rf_freq_set_pv, self.rf_freq_rbv_pv]

        # Check each PV
        ok = True
        for rf_pv in rf_pvs:
            if not rf_pv.healthy():
                ok = False
                # Easiest to set the "Bad PV" from here
                self.pv_error.set(rf_pv.get_name())
                break

        return ok

    def set_power(self, power):
        self.power = power

    def set_rfstep(self, rfstep):
        self.rfstep = rfstep

    def set_period(self, period):
        self.period = period

    def set_valid(self, valid):
        self.valid = valid

    def set_datadir(self, lattice):
        rffb_calc.cache.clear()
        path = os.path.join(mode.DATAROOT, lattice.name)
        self.correctors = numpy.array(
            lattice.get_element_pv_names("HSTR", "x_kick", pytac.RB)
        )
        try:
            raw_bpmresp = loadmat(os.path.join(path, "GoldenBPMResp"))
            raw_disp = loadmat(os.path.join(path, "GoldenDisp"))
            self.bpmresp = raw_bpmresp["Rmat"][0, 0]["Data"]
            self.disp = raw_disp["BPMxDisp"]["Data"][0, 0]
            assert raw_bpmresp["Rmat"][0, 0]["Units"] == "Hardware"
            assert raw_disp["BPMxDisp"]["Units"] == "Hardware"
            self.matrix_error.set(0)
            logger.info(f"Loaded matrix {lattice.name}")
        except BaseException:
            logger.exception(f"Failed to load matrix data {lattice.name}")
            self.bpmresp = None
            self.disp = None
            self.matrix_error.set(1)

    def records(self):

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
            initial_value=self.rfstep,
            on_update=self.set_rfstep,
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


class PVWithValidity(object):
    """For a PV, maintain a history of cagets
    in order to decide if current value is valid
    """

    ALLOWED_INVALID_CAGETS = 10

    def __init__(self, pv_name):
        self.pv_name = pv_name
        self.consecutive_times_invalid = 0
        self.ok = False
        self.last_caget_time = None
        self.severity = None

    def get(self):
        """Do a caget, store the value and severity
        Returns the result of the caget.
        Does not store it to prevent stale data"""

        # Do caget and store attributes
        value = catools.caget(self.pv_name, format=catools.FORMAT_TIME)
        self.severity = value.severity
        self.ok = value.ok
        self.last_caget_time = value.timestamp

        # Check alarm severity not OK and increment counter
        if self.severity != constants.SEVR_NO_ALARM or not self.ok:
            self.consecutive_times_invalid += 1
        else:
            self.consecutive_times_invalid = 0

        return value

    def healthy(self):
        """Return False if too many cagets have returned alarm"""
        if self.consecutive_times_invalid <= self.ALLOWED_INVALID_CAGETS:
            return True
        else:
            logger.warning(
                f"{self.pv_name} raised an alarm more than {self.ALLOWED_INVALID_CAGETS} times"
            )
            return False

    def get_name(self):
        """Return PV name"""
        return self.pv_name
