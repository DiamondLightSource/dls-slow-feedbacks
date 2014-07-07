import os
import time
import traceback
import numpy, scipy, scipy.io
import cothread
from cothread.catools import caget, caput, FORMAT_TIME
from softioc import builder, alarm


# Set up logging
import logging as log
LOG_FORMAT = 'TFB: %(levelname)s %(message)s'
LOG_LEVEL = log.WARNING
log.basicConfig(format=LOG_FORMAT, level=LOG_LEVEL)
numpy.set_printoptions(precision=4)


OFFSET_CURRENT_CHANGED = 'Offset changed outside of TFB',


class Status(object):
    ''' Enum for tune feedback errors.  I can't find a simpler
        way of retaining the same information.
    '''
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
    UNEXPECTED_ERROR = 10

    STRINGS = {FEEDBACK_OFF:  'Feedback off',
               FEEDBACK_ON: 'Feedback running',
               FEEDBACK_SCALING: 'Feedback running: scaled',
               SINGLE_CORR: 'Single correction applied',
               SINGLE_SCALED: 'Single correction: scaled',
               MAGNET_CURRENT: 'Magnet current error',
               TUNE_RANGE: 'Tunes outside valid range',
               TUNE_VALIDITY: 'Tune measurement invalid',
               TUNE_UPDATE: 'Tune PV not updated',
               LOW_CURRENT: 'Beam current is too low',
               UNEXPECTED_ERROR: 'Unexpected error'}


# PV names
TUNE_PVS = ['SR23C-DI-TMBF-01:TUNE:TUNE',
            'SR23C-DI-TMBF-02:TUNE:TUNE']
CURRENT_PV = 'SR-DI-DCCT-01:SIGNAL'


# Configuration directory
DATADIR = '/dls_sw/work/common/matlab/mml/machine/diamondopsdata'
GOLDEN_TUNE_CONFIG = '/home/ops/diagnostics/config/TMBF_tune.config'


# Our IOC name
IOC = 'SR-CS-TFB-01'


# Constant
BEAM_DAMP_TIME = 0.001
# Default values
DELTA_TUNE_TOLERANCE = 0.02
MAX_CURRENT_OFFSET = 0.15


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
    def __init__(self, code):
        Exception.__init__(self, Status.STRINGS[code])
        self.code = code

class TunefbError(Exception):
    '''
    Exception used to stop tune feedback.
    '''
    def __init__(self, code):
        Exception.__init__(self, Status.STRINGS[code])
        self.code = code

class TunefbServer(object):

    '''
    Server for tune feedback. Creates PVs, and monitors and then
    corrects tune towards a setpoint.
    '''

    def __init__(self, mode):
        '''Fetch data from files and set up soft IOC.'''
        # Initial values for PVs
        self.afrac = 0.2
        self.max_current_range = MAX_CURRENT_OFFSET
        self.min_beam_current = 1.0
        self.period = 1.0
        self.last_error = None

        # Whether the last correction was scaled
        self.scaling = False
        # Tune data - Golden tunes are set from ringmode
        self.golden_tunes = numpy.array([0.0, 0.0])
        self.mag_delta_max = numpy.array([0.01])
        self.tunes_max_delta = numpy.array([DELTA_TUNE_TOLERANCE] * 2)
        self.tunes = numpy.zeros(2)
        self.tune_deltas = numpy.zeros(2)
        # Allow one tune measument out of range before tripping
        self.one_tune_error = False

        # Load magnet PVs from file in this directory.
        pydir = os.path.dirname(os.path.realpath(__file__))
        pvs_file = os.path.join(pydir, 'TunePvs.txt')
        self.mag_pvs = load_magnet_pvs(pvs_file)
        self.local_pvs = rename_pvs(self.mag_pvs)

        # List of references to locally hosted mirror PVs, created
        # in self.records()
        self.mirror_pvs = []

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
        self.startup_currents = \
            caget([pv + ':OFFSET1' for pv in self.mag_pvs], throw = False)
        for i in range(len(self.startup_currents)):
            if not self.startup_currents[i].ok:
                print 'Unable to read', self.startup_currents[i].name
                self.startup_currents[i] = 0

        self.integrated_current = self.startup_currents
        self.integrated_tunes = numpy.zeros(2)

        # Magnet current limits
        self.set_max_current_range(self.max_current_range)

        # Initalise EPICS records
        self.records()
        self.max_i_pv.set(max(abs(i) for i in self.startup_currents))

    def set_datadir(self, datadir):
        '''Load required data from files in datadir.'''
        # Load tune config file into environment
        env = {}
        execfile(GOLDEN_TUNE_CONFIG, env)

        # Select correct tune based on ringmode
        tune_h = env['X_tune_' + datadir] * 0.0001
        tune_v = env['Y_tune_' + datadir] * 0.0001
        self.tune_h_pv.set(tune_h)
        self.tune_v_pv.set(tune_v)

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
            cothread.Sleep(self.period)
            try:
                if self.power_pv.get():
                    self.checked_correction()
                    if self.scaling:
                        self.status_pv.set(Status.FEEDBACK_SCALING)
                    else:
                        self.status_pv.set(Status.FEEDBACK_ON)
                else:
                    if self.status_pv.get() in (Status.FEEDBACK_ON, Status.FEEDBACK_SCALING):
                        self.status_pv.set(Status.FEEDBACK_OFF)
            except TunefbInvalid, e:
                # skip one correction
                if self.status_pv.get() != e.code:
                    self.status_pv.set(e.code, severity=alarm.MINOR_ALARM)
                    log.info('Tune feedback paused: %s' % str(e))
            except TunefbError, e:
                # stop feedback
                self.power_pv.set(False)
                self.status_pv.set(e.code, severity=alarm.MAJOR_ALARM)
                log.error('%s' % str(e))
            except Exception, e:
                # stop feedback and print stack trace
                log.warn('Unexpected exception: %s' %str(e))
                traceback.print_exc()
                self.power_pv.set(False)
                self.status_pv.set(Status.UNEXPECTED_ERROR, severity=alarm.MAJOR_ALARM)

    def check_current(self):
        '''Check if current is greater than a mininum current.'''
        if caget(CURRENT_PV) < self.min_beam_current:
            raise TunefbError(Status.LOW_CURRENT)

    def check_tune_range(self):
        '''Check if the measured tunes are within the allowed range.'''
        if any(abs(self.tunes - self.golden_tunes) > self.tunes_max_delta):
            if self.one_tune_error:
                self.one_tune_error = False
                raise TunefbError(Status.TUNE_RANGE)
            else:
                self.one_tune_error = True
                raise TunefbInvalid(Status.TUNE_RANGE)
        else:
            self.one_tune_error = False

    def refresh_tune_deltas(self):
        '''
        Update values for tune deltas, checking if the values are
        reliable.
        '''
        tunes = caget(TUNE_PVS, format=FORMAT_TIME)
        if any([tune.severity == alarm.INVALID_ALARM for tune in tunes]):
            raise TunefbInvalid(Status.TUNE_VALIDITY)
        # This will succeed as long as the TMBF updates the tune PVs
        # more often than self.period
        last_check = time.time() - self.period
        if any([tune.timestamp < last_check for tune in tunes]):
            raise TunefbInvalid(Status.TUNE_UPDATE)
        # Move tunes to numpyarray after severity check
        tunes = numpy.array(tunes)
        log.info('Tune delta before last correction %s' % self.tune_deltas)
        log.info(
            'Tune change since last correction %s' % str(tunes - self.tunes))
        self.tunes = tunes
        self.tune_deltas = self.golden_tunes - self.tunes
        log.info('Actual tune deltas %s' % self.tune_deltas)

    def scale_deltas(self, deltas):
        '''Put delta correction to magnets, clipping if neccassary.'''
        # Scale values over the step current limit
        if any(abs(deltas) > self.mag_delta_max):
            factor = self.mag_delta_max / abs(deltas).max()
            deltas *= factor
            self.scaling = True
            log.info('Using clipping factor: %s' % factor)
        else:
            self.scaling = False
        return deltas

    def check_mag_limits(self, currents):
        max_i = max(abs(currents))
        if max_i > self.max_current_range:
            log.debug('Max current offset: ' +  str(max_i))
            log.debug('Current offset limit:' + str(self.max_current_range))
            raise TunefbError(Status.MAGNET_CURRENT)

    def apply_correction(self, deltas):
        # Calculate and publish tune correction
        calc_tune_corr = numpy.dot(self.rm, deltas)
        log.info('Theoretical tune correction %s' % str(calc_tune_corr))
        self.integrated_tunes += calc_tune_corr
        self.tune_int_h_pv.set(self.integrated_tunes[0])
        self.tune_int_v_pv.set(self.integrated_tunes[1])
        log.debug('Calculated current deltas:\n%s' % str(deltas))
        # Refresh integrated currents so they match their PVs.
        fetched_current = numpy.array([pv.get() for pv in self.mirror_pvs])
        if any(fetched_current - self.integrated_current):
            log.warn(OFFSET_CURRENT_CHANGED)

        self.integrated_current = fetched_current + deltas
        self.max_i_pv.set(max(abs(self.integrated_current)))
        for pv, current in zip(self.mirror_pvs, self.integrated_current):
            pv.set(current)
        log.info(
            'Total tune change from feedback %s' % str(self.integrated_tunes))

    def checked_correction(self):
        '''
        Calculate and then apply a correction, will throw an execption
        in the event of an invalid or error state.
        '''
        self.check_current()
        self.refresh_tune_deltas()
        self.check_tune_range()
        mag_deltas = self.afrac * numpy.dot(self.irm, self.tune_deltas)
        scaled_deltas = self.scale_deltas(mag_deltas)
        self.check_mag_limits(self.integrated_current + scaled_deltas)
        self.apply_correction(scaled_deltas)

    def unchecked_correction(self, dummy):
        '''
        Calculate and apply correction without checking beam current.
        Catches all invalid and error states.
        '''
        try:
            # This is here only to give visual feedback when pressing the
            # single correction button
            self.status_pv.set(Status.FEEDBACK_OFF)
            cothread.Sleep(0.3)
            self.refresh_tune_deltas()
            mag_deltas = self.afrac * numpy.dot(self.irm, self.tune_deltas)
            scaled_deltas = self.scale_deltas(mag_deltas)
            self.apply_correction(scaled_deltas)
            log.info('Completed single correction')
            self.corr_toggle_pv.set(1 - self.corr_toggle_pv.get())
            # This sleep is also necessary to see the above status change
            # in the GUI
            cothread.Sleep(0.2)
            if self.scaling:
                self.status_pv.set(Status.SINGLE_SCALED)
            else:
                self.status_pv.set(Status.SINGLE_CORR)
        except TunefbInvalid, e:
            log.warn('%s' % str(e))
            self.status_pv.set(e.code, severity=alarm.MINOR_ALARM)
        except TunefbError, e:
            log.error('%s' % str(e))
            self.status_pv.set(e.code, severity=alarm.MAJOR_ALARM)
        except Exception, e:
            log.warn('Unexpected exception: %s' % str(e))
            self.status_pv.set(Status.UNEXPECTED_ERROR, severity=alarm.MAJOR_ALARM)

    def reset(self, dummy):
        '''Reset the error pv.'''
        self.status_pv.set(Status.FEEDBACK_OFF)
        self.reset_pv.set(0)

    def reset_integrated_current(self, value):
        '''Set all integrated currents to zero.'''
        if value:
            self.reset_integrated_current_pv.set(0)
            # Set our local PVs and currents to zero
            self.integrated_current = [0 for _ in self.integrated_current]
            for pv in self.mirror_pvs:
                pv.set(0)
                cothread.Sleep(BEAM_DAMP_TIME * 10.)
            log.warn('Reset all integrated currents to zero')

    def aggregate_setpoints(self, value):
        '''Move offsets from this ioc to the quadrupole setpoints.'''
        if value:
            self.aggregate_pv.set(0)
            # Forward setpoint values one at a time to prevent beam dump
            for i, pv in enumerate(self.mag_pvs):
                pv = pv + ':SETI'
                caput(pv, caget(pv) + self.integrated_current[i])
                self.mirror_pvs[i].set(0)
                self.integrated_current[i] = 0
                cothread.Sleep(BEAM_DAMP_TIME * 10.)
            log.warn('Aggregated offsets into setpoints')

    def set_afrac(self, value):
        self.afrac = value

    def set_max_current_range(self, value):
        self.max_current_range = value

    def set_min_beam_current(self, value):
        self.min_beam_current = value

    def set_period(self, value):
        self.period = value

    def set_tune_h(self, value):
        self.golden_tunes[0] = value

    def set_tune_v(self, value):
        self.golden_tunes[1] = value

    def set_max_h_tune_delta(self, value):
        self.tunes_max_delta[0] = value

    def set_max_v_tune_delta(self, value):
        self.tunes_max_delta[1] = value

    def set_mag_delta_max(self, value):
        self.mag_delta_max = value

    def records(self):
        '''Setup iocbuilder to create required records.'''
        builder.SetDeviceName(IOC)
        self.power_pv = builder.boolOut(
                'ONOFF', 'OFF', 'ON', initial_value=False)
        self.reset_pv = builder.aOut(
                'RESET', initial_value=0, on_update=self.reset)
        self.aggregate_pv = builder.aOut(
                'AGGREGATE', initial_value=0,
                on_update=self.aggregate_setpoints)
        self.reset_integrated_current_pv = builder.aOut(
                'RESETCORR', initial_value=0,
                on_update=self.reset_integrated_current)
        self.tune_h_pv = builder.aOut(
                'TUNE:H', initial_value=self.golden_tunes[0],
                on_update=self.set_tune_h, PREC=4)
        self.tune_v_pv = builder.aOut(
                'TUNE:V', initial_value=self.golden_tunes[1],
                on_update=self.set_tune_v, PREC=4)
        self.tune_int_h_pv = builder.aOut(
                'TUNE:HINT', initial_value=self.integrated_tunes[0],
                PREC=4)
        self.tune_int_v_pv = builder.aOut(
                'TUNE:VINT', initial_value=self.integrated_tunes[1],
                PREC=4)
        self.max_h_tune_delta_pv = builder.aOut(
                'TUNE:HDELTA', initial_value=self.tunes_max_delta[0],
                on_update=self.set_max_h_tune_delta, PREC=4)
        self.max_v_tune_delta_pv = builder.aOut(
                'TUNE:VDELTA', initial_value=self.tunes_max_delta[1],
                on_update=self.set_max_v_tune_delta, PREC=4)
        self.corr_toggle_pv = builder.aOut(
                'CORR:TOGGLE', initial_value=0, PREC=4)
        builder.aOut(
                'CORR', initial_value=0,
                on_update=self.unchecked_correction, always_update=True)
        builder.aOut(
                'AFRAC', initial_value=self.afrac,
                on_update=self.set_afrac, PREC=4)
        builder.aOut(
                'PERIOD', initial_value=self.period,
                on_update=self.set_period, PREC=4)
        builder.aOut(
                'ILIM', initial_value=self.max_current_range,
                on_update=self.set_max_current_range, PREC=4)
        self.max_i_pv = builder.aOut(
                'IMAX', initial_value=0.0, PREC=4)
        builder.aOut(
                'BEAMMIN', initial_value=self.min_beam_current,
                on_update=self.set_min_beam_current, PREC=4)
        builder.aOut(
                'IDELTA', initial_value=self.mag_delta_max,
                on_update=self.set_mag_delta_max, PREC=4)

        # initialise each current PV to the value from the remote
        # PV from which it will be starting
        for pv, value in zip(self.local_pvs, self.startup_currents):
            self.mirror_pvs.append(
                    builder.aOut(pv.split(':')[1] + ':I', initial_value=value))

        # Pass all values from the enum into the status PV
        num_statuses = len(Status.STRINGS)
        status_args = ['STATUS'] + [(Status.STRINGS[code], code) for code in range(num_statuses)]
        self.status_pv = builder.mbbIn(*status_args, initial_value=Status.FEEDBACK_OFF)
