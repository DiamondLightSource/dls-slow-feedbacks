import os, cothread, numpy, scipy, scipy.io
from cothread.catools import caput, caget, FORMAT_TIME
from softioc import builder


# Errors
NO_ERROR = 'No Errors'
MAGNET_CURRENT_ERROR = 'Magnet current exceeds tolerance'
TUNE_RANGE_ERROR = 'Tunes are outside allowable range'
TUNE_DELTA_ERROR = 'Tunes are varying too rapidly'
TUNE_VALIDITY_ERROR = 'Tune measurement is invalid'
LOW_CURRENT_ERROR = 'Current is too low'


# PV names
TUNE_PVS = ['SR21C-DI-TMBF-01:TUNE:TUNE',
            'SR21C-DI-TMBF-02:TUNE:TUNE']
CURRENT_PV = 'SR-CS-TCFB-01:CURRENT'
INJECTION_PV = 'SR-CS-FILL-01:COUNTDOWN'


def load_magnet_pvs(file):
    '''
    Load corrector magnet PVs from the specific format
    in the file.
    '''
    raw_pvs = scipy.io.loadmat(file)
    mag_pvs = []
    for pvset in raw_pvs['ans'][0]:
        mag_pvs.extend([str(pv) for pv in pvset])
    return mag_pvs


def load_tune_rm(file):
    '''
    Load response matrix from the specific format found
    in the specified file.
    '''
    raw_rms = scipy.io.loadmat(file)
    # Construct complete response matrix.
    rmx = []
    rmy = []
    for raw_rm in raw_rms['Rmat'][0]:
        raw_rmx = raw_rm[0][0][0][0]
        raw_rmy = raw_rm[0][0][0][1]
        rmx.extend(raw_rmx)
        rmy.extend(raw_rmy)
    return numpy.array([rmx, rmy])


class TunefbException(Exception):
    pass


class TunefbServer(object):

    '''
    Server for tune feedback. Creates PVs, and monitors and then
    corrects tune towards a setpoint.
    '''

    PERIOD = 1.0

    def __init__(self, mode):
        '''Fetch data from files and set up soft IOC.'''

        # Initial values for PVs
        self.afrac = 0.2
        self.last_error = NO_ERROR

        # Tune data
        self.golden_tunes = numpy.array([0.201, 0.371]) # CHANGE TO NULL
        self.tunes_delta_max = numpy.array([0.005, 0.005])
        self.tunes_max = numpy.array([0.25, 0.42])
        self.tunes_min = numpy.array([0.15, 0.32])

        # Current checking values
        self.min_current = 0.1

        # Load data from files (and on ringmode change)
        self.mag_pvs = None
        self.mag_limits = None
        self.rm = None
        self.irm = None
        self.dataroot = '/home/uxj42447/software/fastfeedback.data'
        if self.set_datadir not in mode.listeners:
            mode.add_listener(self.set_datadir)

        # Initalise EPICS records
        self.records()

    def set_datadir(self, datadir):
        '''Load required data from files in datadir.'''
        print "set_datadir"
        dir = os.path.join(self.dataroot, datadir)

        self.mag_pvs = load_magnet_pvs(os.path.join(dir, 'TunePvs.mat'))
        self.rm = load_tune_rm(os.path.join(dir, 'GoldenTuneResp.mat'))

        # Magnet current limits
        self.mag_limits = [
            numpy.array(caget([pv + 'MIN' for pv in self.mag_pvs])),
            numpy.array(caget([pv + 'MAX' for pv in self.mag_pvs]))]

        # Invert response matrix
        self.irm = numpy.linalg.pinv(self.rm)

    def init(self):
        '''Spawn a new thread to run the main ioc loop.'''
        cothread.Spawn(self.tick)

    def tick(self):
        '''
        Top level loop in the ioc, if it terminates then
        a restart of the ioc is required. Therefore, it is appropriate
        to catch all exceptions.
        '''
        while True:
            cothread.Sleep(self.PERIOD)
            try:
                if self.power_pv.get():
                    self.checked_correction()
            except TunefbException, e:
                self.power_pv.set(False)
                self.error_pv.set(str(e))
                print 'Error:', e
            except Exception, e:
                print "Unexpected exception:", e
                self.power_pv.set(False)
                self.error_pv.set('Unexpected error')

    def check_current(self):
        '''Check if current is greater than a mininum current.'''
        if caget(CURRENT_PV) < self.min_current:
            raise TunefbException(LOW_CURRENT_ERROR)

    def injecting(self):
        '''Check if topup injection is occurring.'''
        return (caget(INJECTION_PV) == 0)

    def get_delta_tunes(self):
        '''Update values for delta_tunes.'''
        tunes = caget(TUNE_PVS, format=FORMAT_TIME)
        if any([tune.severity != 0 for tune in tunes]):
            raise TunefbException(TUNE_VALIDITY_ERROR)
        # Move tunes to numpyarray after severity check
        tunes = numpy.array(tunes)
        if any(tunes > self.tunes_max):
            raise TunefbException(TUNE_RANGE_ERROR)
        if any(tunes < self.tunes_min):
            raise TunefbException(TUNE_RANGE_ERROR)

        delta_tunes = self.golden_tunes - tunes
        if any(abs(delta_tunes) > self.tunes_delta_max):
            raise TunefbException(TUNE_DELTA_ERROR)
        print "determined tune delta", delta_tunes
        return delta_tunes

    def apply_correction(self, deltas):
        '''Put delta correction to magnets.'''
        mag_vals = numpy.array(caget(self.mag_pvs))
        mag_vals += deltas
        if any(mag_vals < self.mag_limits[0]):
            raise TunefbException(MAGNET_CURRENT_ERROR)
        if any(mag_vals > self.mag_limits[1]):
            raise TunefbException(MAGNET_CURRENT_ERROR)

        print "retrieved tune delta", numpy.dot(self.rm, deltas)
        # actually should caput mag_vals
        caput(self.mag_pvs, deltas)

    def correct(self):
        tunes_delta = self.get_delta_tunes()
        deltas = self.afrac * numpy.dot(self.irm, tunes_delta)
        self.apply_correction(deltas)

    def checked_correction(self):
        '''Calculate and then apply a correction, subject to checks.'''
        self.check_current()
        if not self.injecting():
            self.correct()

    def unchecked_correction(self, dummy):
        self.correct()
        print 'completed single correction'

    def reset(self, dummy):
        '''Reset the error pv.'''
        self.error_pv.set(NO_ERROR)
        self.reset_pv.set(0)
        print 'reset called', dummy

    def set_afrac(self, value):
        self.afrac = value

    def set_tune_h(self, value):
        self.golden_tunes[0] = value

    def set_tune_v(self, value):
        self.golden_tunes[1] = value

    def set_max_h_tune(self, value):
        self.tunes_max[0] = value

    def set_max_v_tune(self, value):
        self.tunes_max[1] = value

    def set_min_h_tune(self, value):
        self.tunes_min[0] = value

    def set_min_v_tune(self, value):
        self.tunes_min[1] = value

    def set_delta_h_tune(self, value):
        self.tunes_delta_max[0] = value

    def set_delta_v_tune(self, value):
        self.tunes_delta_max[1] = value

    def records(self):
        '''Setup iocbuilder to create required records.'''
        builder.SetDeviceName("SR-CS-TCFB-01")
        self.afrac_pv = builder.aOut(
                'AFRAC', initial_value=0.2, on_update=self.set_afrac,PREC=4)
        self.power_pv = builder.boolOut(
                'ONOFF', "OFF", "ON", initial_value=False)
        self.error_pv = builder.stringOut(
                'ERROR', initial_value=NO_ERROR)
        self.unchecked_correction_pv= builder.aOut(
                'CORR', initial_value=0,
                on_update=self.unchecked_correction, always_update=True)
        self.reset_pv = builder.aOut(
                'RESET', initial_value=0, on_update=self.reset)
        builder.aOut(
                'TUNE:H', initial_value=self.golden_tunes[0],
                on_update=self.set_tune_h, PREC=4)
        builder.aOut(
                'TUNE:V', initial_value=self.golden_tunes[1],
                on_update=self.set_tune_v, PREC=4)
        builder.aOut(
                'TUNE:HMAX', initial_value=self.tunes_max[0],
                on_update=self.set_max_h_tune, PREC=4)
        builder.aOut(
                'TUNE:VMAX', initial_value=self.tunes_max[1],
                on_update=self.set_min_v_tune, PREC=4)
        builder.aOut(
                'TUNE:HMIN', initial_value=self.tunes_min[0],
                on_update=self.set_min_v_tune, PREC=4)
        builder.aOut(
                'TUNE:VMIN', initial_value=self.tunes_min[1],
                on_update=self.set_min_v_tune, PREC=4)
        builder.aOut(
                'TUNE:HDELTA', initial_value=self.tunes_delta_max[0],
                on_update=self.set_delta_h_tune, PREC=4)
        builder.aOut(
                'TUNE:VDELTA', initial_value=self.tunes_delta_max[1],
                on_update=self.set_delta_v_tune, PREC=4)
        # testing
        builder.aOut(
                'CURRENT', initial_value=1,
                PREC=4)
