from pkg_resources import require
require('cothread')
require('numpy')
require('scipy')

import os, cothread, scipy, numpy, scipy.io
from cothread.catools import caput, caget, FORMAT_TIME
from softioc import builder


# Errors
NO_ERROR = 'No Errors'
MAGNET_CURRENT_ERROR = 'Magnet current exceeds tolerance'
TUNE_RANGE_ERROR = 'Tunes are outside allowable range'
TUNE_DELTA_ERROR = 'Tunes are varying to rapidly'
TUNE_VALIDITY_ERROR = 'Tune measurement is invalid'
LOW_CURRENT_ERROR = 'Current is to low'


class tunefb_server(object):

    """
    Server for tune feedback. Creates PVs, and monitors and then
    corrects tune towards a setpoint.
    """

    def __init__(self, mode):
        """Initalise values."""

        # Initial values for PVs
        self.power = 1
        self.afrac = 0.2
        self.last_error = NO_ERROR

        # Tune data
        self.tune_pvs = [
                'SR21C-DI-TMBF-01:TUNE:TUNE',
                'SR21C-DI-TMBF-02:TUNE:TUNE']
        self.golden_tunes = numpy.array([0.201, 0.371])
        self.max_delta_tunes = numpy.array([0.1, 0.1])
        self.max_tunes = self.golden_tunes + 0.1
        self.min_tunes = self.golden_tunes - 0.1
        self.delta_tunes = (self.golden_tunes -
                numpy.array(caget(self.tune_pvs)))

        # Current checking values
        self.current_pv = 'SR-DI-DCCT-01:SIGNAL'
        self.min_current = 0.1

        # Injection checking values
        self.injection_pv = 'SR-CS-FILL-01:COUNTDOWN'

        # Load data from files (and on ringmode change)
        self.rmx = []
        self.rmy = []
        self.irm = []
        self.dataroot = '/home/uxj42447/software/fastfeedback.data'
        self.set_datadir('SRI0913')
        if self.set_datadir not in mode.listeners:
            mode.add_listener(self.set_datadir)

        # Initalise EPICS records
        self.afrac_pv = None
        self.power_pv = None
        self.error_pv = None
        self.reset_pv = None
        self.records()

    def set_datadir(self, datadir):
        """Load required data from files in datadir."""
        print "set_datadir"
        dir = os.path.join(self.dataroot, datadir)

        # Magnet pv names
        raw_pvs = scipy.io.loadmat(os.path.join(dir, 'TunePvs.mat'))
        self.mag_pvs = [
                [pv.encode() for pv in pvs] for pvs in raw_pvs['ans'][0]]

        # Magnet current limits
        self.mag_limits = [[
            numpy.array(caget([pv + 'MIN' for pv in pvs])),
            numpy.array(caget([pv + 'MAX' for pv in pvs]))]
            for pvs in self.mag_pvs]

        # Inverse response matricies
        raw_rms = scipy.io.loadmat(os.path.join(dir, 'GoldenTuneResp.mat'))
        self.irm = []
        self.rmx = []
        self.rmy = []
        for raw_rm in raw_rms['Rmat'][0]:
            rmx = raw_rm[0][0][0][0]
            rmy = raw_rm[0][0][0][1]
            self.rmx.extend(rmx)
            self.rmy.extend(rmy)
        self.rm = numpy.array([self.rmx, self.rmy])
        print "rm", self.rm.shape
        self.irm = numpy.linalg.pinv(self.rm)
        print "irm", self.irm.shape

    def init(self):
        """Spawn a new thread to run the main ioc loop."""
        cothread.Spawn(self.tick)

    def tick(self):
        """Top level loop in the ioc, if it terminates then
        a restart of the ioc is required. Therefore, it is appropraite
        to catch all exceptions.
        """
        while True:
            try:
                if self.power:
                    self.do_correction()
                cothread.Sleep(1.0)
            except Exception, e:
                print 'Error:', e

    def check_current(self):
        """Check if current is greater than a minium current."""
        if caget(self.current_pv) < self.min_current:
            raise Exception(LOW_CURRENT_ERROR)

    def is_injection_occurring(self):
        """Check if topup injection is occurring."""
        if caget(self.injection_pv) == 0:
            return True
        return False

    def refresh_delta_tunes(self):
        """Update values for self.delta_tunes."""
        tunes = caget(self.tune_pvs, format=FORMAT_TIME)
        if all([tune.severity != 0 for tune in tunes]):
            #raise Exception(TUNE_VALIDITY_ERROR)
            pass
        self.delta_tunes = self.golden_tunes - numpy.array(tunes)
        if (tunes > self.max_tunes).any():
            raise Exception(TUNE_RANGE_ERROR)
        if (tunes < self.min_tunes).any():
            raise Exception(TUNE_RANGE_ERROR)
        if (abs(self.delta_tunes) > self.max_delta_tunes).any():
            raise Exception(TUNE_DELTA_ERROR)
        self.delta_tunes = (1,1)

    def apply_correction(self, deltas):
        """Put delta correction to magnets."""
        mag_vals = [numpy.array(caget(pvs)) for pvs in self.mag_pvs]
#        for i, delta in enumerate(deltas):
#            mag_vals[i] += delta
#        if any([
#                (x[0] > x[1][1]).any() or (x[0] < x[1][0]).any()
#                for x in zip(mag_vals, self.mag_limits)]):
#            raise Exception(MAGNET_CURRENT_ERROR)
        mag_pvs= []
        for pvset in self.mag_pvs:
            mag_pvs.extend(pvset)

        print "retrieved", numpy.dot(self.rm, deltas)
        [caput(x[0], x[1]) for x in zip(mag_pvs, deltas)]

    def do_correction(self):
        """Calculate and then apply a correction, subject to checks."""
        try:
            self.check_current()
            if not self.is_injection_occurring():
                self.refresh_delta_tunes()
                deltas = numpy.dot(self.irm, self.delta_tunes)
                print "deltaed"
                #deltas = [delta*self.afrac for delta in deltas]
                self.apply_correction(deltas)
        except Exception, e:
            self.power_pv.set(0)
            self.error_pv.set(e.__str__())
            print 'Error', e

    def reset(self, dummy):
        """Reset the error pv."""
        self.error_pv.set(NO_ERROR)
        self.reset_pv.set(0)
        print 'reset called', dummy

    def set_power(self, value):
        self.power = value

    def set_afrac(self, value):
        self.afrac = value

    def set_tune_h(self, value):
        self.golden_tunes[0] = value

    def set_tune_v(self, value):
        self.golden_tunes[1] = value

    def set_max_h_tune(self, value):
        self.max_tunes[0] = value

    def set_max_v_tune(self, value):
        self.max_tunes[1] = value

    def set_min_h_tune(self, value):
        self.min_tunes[0] = value

    def set_min_v_tune(self, value):
        self.min_tunes[1] = value

    def set_min_v_tune(self, value):
        self.min_tunes[1] = value

    def set_delta_h_tune(self, value):
        self.max_delta_tunes[0] = value

    def set_delta_v_tune(self, value):
        self.max_delta_tunes[1] = value

    def records(self):
        """Setup iocbuilder to create required records."""
        builder.SetDeviceName("SR-CS-TCFB-01")
        self.afrac_pv = builder.aOut(
                'AFRAC', initial_value=0.2, on_update=self.set_afrac,PREC=4)
        self.power_pv = builder.mbbOut(
                'ONOFF', ("OFF", 0), ("ON", 1),
                initial_value=self.power, on_update=self.set_power)
        self.error_pv = builder.stringOut(
                'ERROR', initial_value=NO_ERROR)
        self.reset_pv = builder.aOut(
                'RESET', initial_value=0, on_update=self.reset)
        builder.aOut(
                'TUNE:H', initial_value=self.golden_tunes[0],
                on_update=self.set_tune_h, PREC=4)
        builder.aOut(
                'TUNE:V', initial_value=self.golden_tunes[1],
                on_update=self.set_tune_v, PREC=4)
        builder.aOut(
                'TUNE:HMAX', initial_value=self.max_tunes[0],
                on_update=self.set_max_h_tune, PREC=4)
        builder.aOut(
                'TUNE:VMAX', initial_value=self.max_tunes[1],
                on_update=self.set_min_v_tune, PREC=4)
        builder.aOut(
                'TUNE:HMIN', initial_value=self.min_tunes[0],
                on_update=self.set_min_v_tune, PREC=4)
        builder.aOut(
                'TUNE:VMIN', initial_value=self.min_tunes[1],
                on_update=self.set_min_v_tune, PREC=4)
        builder.aOut(
                'TUNE:HDELTA', initial_value=self.max_delta_tunes[0],
                on_update=self.set_delta_h_tune, PREC=4)
        builder.aOut(
                'TUNE:VDELTA', initial_value=self.max_delta_tunes[1],
                on_update=self.set_delta_v_tune, PREC=4)
