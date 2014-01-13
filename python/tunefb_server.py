import os
import time
import traceback
import numpy, scipy, scipy.io
import cothread
from cothread.catools import caput, caget, FORMAT_TIME
from softioc import builder

# set up logging
import logging as log
LOG_FORMAT = '%(asctime)s %(levelname)s %(message)s'
LOG_LEVEL = log.DEBUG
log.basicConfig(format=LOG_FORMAT, level=LOG_LEVEL)
numpy.set_printoptions(precision=3)


# Errors
NO_ERROR = 'No Errors'
MAGNET_CURRENT_ERROR = 'Magnet current above tolerances'
TUNE_RANGE_ERROR = 'Tunes are outside allowable range'
TUNE_VALIDITY_ERROR = 'Tune measurement is invalid'
TUNE_UPDATE_ERROR = 'Tune PV not updated'
LOW_CURRENT_ERROR = 'Current is too low'
UNEXPECTED_ERROR = 'Unexpected error'


# Status
FEEDBACK_OFF = 'Feedback off'
FEEDBACK_ON = 'Feedback running'
CLIPPING_STATUS = 'Correction scaled down by factor'


# PV names
TUNE_PVS = ['SR21C-DI-TMBF-01:TUNE:TUNE',
            'SR21C-DI-TMBF-02:TUNE:TUNE']
CURRENT_PV = 'SR-DI-DCCT-01:SIGNAL'


# Configuration directory
DATADIR = '/home/uxj42447/software/fastfeedback.data'


# Our IOC name
IOC = 'SR-CS-TCFB-01'


# Amount we allow tune feedback to change the current by
MAX_CURRENT_RANGE = 10


def load_magnet_pvs(txt_file):
    '''
    Load corrector magnet PVs from the specific format
    in the file.
    '''
    mag_pvs = []
    with open(txt_file) as f:
        for line in f:
            mag_pvs.append(line.strip())
    return mag_pvs


def rename_pvs(pvs):
    '''Rename quadrople pv names for use as local pvs.'''
    new_pvs = []
    for pv in pvs:
        parts = pv.split('-')
        cell = parts[0][2:4]
        new_pv = IOC + ':' + cell + parts[2] + parts[3]
        new_pvs.append(new_pv)

    return new_pvs


def load_tune_rm(mat_file):
    '''
    Load response matrix from the specific format found
    in the specified file.
    '''
    raw_rms = scipy.io.loadmat(mat_file)
    # Construct complete response matrix.
    rmx = []
    rmy = []
    for raw_rm in raw_rms['Rmat'][0]:
        raw_rmx = raw_rm[0][0][0][0]
        raw_rmy = raw_rm[0][0][0][1]
        rmx.extend(raw_rmx)
        rmy.extend(raw_rmy)
    return numpy.array([rmx, rmy])


class TunefbInvalid(Exception):
    '''
    Exception used to pause tune feedback.
    '''
    pass

class TunefbError(Exception):
    '''
    Exception used to stop tune feedback.
    '''
    pass

class TunefbServer(object):

    '''
    Server for tune feedback. Creates PVs, and monitors and then
    corrects tune towards a setpoint.
    '''

    PERIOD = 1.0
    MIN_CURRENT = 1.0

    def __init__(self, mode):
        '''Fetch data from files and set up soft IOC.'''
        # Initial values for PVs
        self.afrac = 0.2
        self.last_error = NO_ERROR

        # Tune data
        # TODO: should not provide default values.
        self.golden_tunes = numpy.array([0.201, 0.371])
        self.mag_delta_max = numpy.array([0.01])
        self.tunes_max = numpy.array([0.25, 0.42])
        self.tunes_min = numpy.array([0.15, 0.32])
        self.tunes = numpy.zeros(2)
        self.tune_deltas = numpy.zeros(2)

        # Load magnet PVs from file in this directory.
        pydir = os.path.dirname(os.path.realpath(__file__))
        pvs_file = os.path.join(pydir, 'TunePvs.txt')
        self.mag_pvs = load_magnet_pvs(pvs_file)
        self.local_pvs = rename_pvs(self.mag_pvs)

        # Load data from files (and on ringmode change)
        self.rm = None
        self.irm = None
        self.dataroot = DATADIR
        if self.set_datadir not in mode.listeners:
            mode.add_listener(self.set_datadir)

        # Magnet setpoint PVs
        self.mag_ctrl_pvs = [pv + ':I' for pv in self.local_pvs]

        # fetch values from the PVs we will be mirroring, before
        # starting up.
        self.startup_currents = caget([pv + ':OFFSET1' for pv in self.mag_pvs])
        self.integrated_current = self.startup_currents
        self.integrated_tunes = numpy.zeros(2)

        # Magnet current limits
        self.mag_limits = [
            numpy.array([-MAX_CURRENT_RANGE for pv in self.local_pvs]),
            numpy.array([ MAX_CURRENT_RANGE for pv in self.local_pvs])]
        # Initalise EPICS records
        self.records()

    def set_datadir(self, datadir):
        '''Load required data from files in datadir.'''
        # Load data from file
        mode_dir = os.path.join(self.dataroot, datadir)
        self.rm = load_tune_rm(os.path.join(mode_dir, 'GoldenTuneResp.mat'))

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
                    self.status_pv.set(FEEDBACK_ON)
                else:
                    self.status_pv.set(FEEDBACK_OFF)
            except TunefbInvalid, e:
                # skip one correction
                if self.status_pv.get() != str(e):
                    self.status_pv.set(str(e))
                    log.warn('Tune feedback paused: %s' % str(e))
            except TunefbError, e:
                # stop feedback
                self.power_pv.set(False)
                self.error_pv.set(str(e))
                log.warn('Error: %s' % str(e))
            except Exception, e:
                # stop feedback and print stack trace
                log.warn('Unexpected exception: %s' %str(e))
                traceback.print_exc()
                self.power_pv.set(False)
                self.error_pv.set(UNEXPECTED_ERROR)

    def check_current(self):
        '''Check if current is greater than a mininum current.'''
        if caget(CURRENT_PV) < self.MIN_CURRENT:
            raise TunefbError(LOW_CURRENT_ERROR)

    def check_tune_range(self):
        '''Check if the measured tunes are within the allowed range.'''
        if any(self.tunes > self.tunes_max):
            raise TunefbError(TUNE_RANGE_ERROR)
        if any(self.tunes < self.tunes_min):
            raise TunefbError(TUNE_RANGE_ERROR)

    def refresh_tune_deltas(self):
        '''
        Update values for tune deltas, checking if the values are
        reliable.
        '''
        tunes = caget(TUNE_PVS, format=FORMAT_TIME)
        if any([tune.severity == 3 for tune in tunes]):
            raise TunefbInvalid(TUNE_VALIDITY_ERROR)
        # this will work as long as the TMBF updates the tune PVs
        # more often than self.PERIOD
        last_check = time.time() - self.PERIOD
        if any([tune.timestamp < last_check for tune in tunes]):
            raise TunefbInvalid(TUNE_UPDATE_ERROR)
        # Move tunes to numpyarray after severity check
        tunes = numpy.array(tunes)
        log.debug('Tune delta before last correction %s' % self.tune_deltas)
        log.debug('Tune change since last correction %s' % str(tunes - self.tunes))
        self.tunes = tunes
        self.tune_deltas = self.golden_tunes - self.tunes
        log.debug('Actual tune deltas %s' % self.tune_deltas)

    def apply_correction(self, deltas):
        '''Put delta correction to magnets, clipping if neccassary.'''
        # Scale values over the step current limit
        if any(abs(deltas) > self.mag_delta_max):
            factor = self.mag_delta_max / abs(deltas).max()
            deltas *= factor
            self.status_pv.set(CLIPPING_STATUS + ': ' + str(factor))
            log.debug('Using clipping factor: %s' % factor)

        # Add correction to total values
        self.integrated_current += deltas
        if any(self.integrated_current < self.mag_limits[0]):
            raise TunefbError(MAGNET_CURRENT_ERROR)
        if any(self.integrated_current > self.mag_limits[1]):
            raise TunefbError(MAGNET_CURRENT_ERROR)

        calc_tune_corr = numpy.dot(self.rm, deltas)
        log.debug('Theoretical tune correction %s' % str(calc_tune_corr))
        self.integrated_tunes += calc_tune_corr
        # TODO: useful for testing
        #log.debug('Calculated current deltas:\n', deltas)
        caput(self.mag_ctrl_pvs, self.integrated_current)
        log.debug('Total tune change from feedback %s' % str(self.integrated_tunes))

    def correct(self):
        '''
        Calculate the current deltas and then apply them
        to the magnet power supplies.
        '''
        mag_deltas = self.afrac * numpy.dot(self.irm, self.tune_deltas)
        self.apply_correction(mag_deltas)

    def checked_correction(self):
        '''
        Calculate and then apply a correction, will throw an execption
        in the event of an invalid or error state.
        '''
        self.check_current()
        self.refresh_tune_deltas()
        self.check_tune_range()
        self.correct()

    def unchecked_correction(self, dummy):
        '''
        Calculate and apply correction without checking beam current.
        Catches all invalid and error states.
        '''
        try:
            self.refresh_tune_deltas()
            self.correct()
            log.debug('Completed single correction')
        except (TunefbInvalid, TunefbError), e:
            log.warn('Error: %s' % str(e))
            self.error_pv.set(str(e))
        except Exception, e:
            log.warn('Unexpected exception: %s' % str(e))
            self.error_pv.set(UNEXPECTED_ERROR)

    def reset(self, dummy):
        '''Reset the error pv.'''
        self.error_pv.set(NO_ERROR)
        self.reset_pv.set(0)

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

    def set_mag_delta_max(self, value):
        self.mag_delta_max = value

    def records(self):
        '''Setup iocbuilder to create required records.'''
        builder.SetDeviceName(IOC)
        self.afrac_pv = builder.aOut(
                'AFRAC', initial_value=self.afrac,
                on_update=self.set_afrac, PREC=4)
        self.power_pv = builder.boolOut(
                'ONOFF', 'OFF', 'ON', initial_value=False)
        self.status_pv = builder.stringOut(
                'STATUS', initial_value=FEEDBACK_OFF)
        self.error_pv = builder.stringOut(
                'ERROR', initial_value=NO_ERROR)
        self.unchecked_correction_pv = builder.aOut(
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
                on_update=self.set_min_h_tune, PREC=4)
        builder.aOut(
                'TUNE:VMIN', initial_value=self.tunes_min[1],
                on_update=self.set_min_v_tune, PREC=4)
        builder.aOut(
                'IMAX', initial_value=self.mag_delta_max,
                on_update=self.set_mag_delta_max, PREC=4)

        # initialise each current PV to the value from the remote
        # PV that it will be starting from
        for pv, value in zip(self.local_pvs, self.startup_currents):
            builder.aOut(pv.split(':')[1] + ':I', initial_value=value)
