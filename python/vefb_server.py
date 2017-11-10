import os
import traceback
from softioc import builder
import cothread
from cothread.catools import camonitor, caput, FORMAT_TIME
import numpy as np
from scipy.io import loadmat
import time

import mode


class VefbConstants(object):
    VEMIT_TARGET_INITIAL = 8.0
    AFRAC_INITIAL = 0.25
    IIRF_PARAM_INITIAL = 0.25
    MAX_TS_AGE = 0.35
    SQUAD_DELTA_MAX_INITIAL = 0.1
    VEMIT_TARGET_ERR_MAX_INITIAL = 1.0
    VEMIT_FB_START_ERR_MAX_INITIAL = 1.0
    VEMIT_EXTRA_TARGET_ERR_MAX_INITIAL = 0.2
    VEMIT_SINGLE_DELTA_INITIAL = 0.005
    NO_VALUE_TIMEOUT_INITIAL = 2.0
    MAX_ERROR_TIME_INITIAL = 24.0
    MAX_RECOVERY_TIME_INITIAL = 120.0
    MIN_CAM_RECOVERY_TIME_INITIAL = 35.0
    MAX_CAM_RECOVERY_TIME_INITIAL = 50.0
    NO_EFFECT_FACTOR_DELTA_MAX_INITIAL = 3.0
    VEMIT_ACCEPTABLE_ERR_INITIAL = 0.5


class EmittanceStatus(object):
    # Successful emittance calculation.
    OK              = 0
    # Successful emittance calculation on invalid beam (no beam or injecting).
    FORCED          = 1
    # All emittance processing switched off.
    DISABLED        = 2

    # Injecting beam, calculation postponed.
    INJECTING       = 3
    # No beam present in machine, nothing to calculate.
    NO_BEAM         = 4
    # Image too bright, pixels saturated.
    SATURATED       = 5
    # Image too faint for reliable fit.
    TOO_DIM         = 6

    # Error in emittance calculation, probable bad beam image.
    FIT_ERROR       = 7

    # No triggers because triggering is currently disabled.
    NO_TRIGGER      = 8
    # Cameras not in sticky state, manual intervention needed.
    CAMERA_OFF      = 9
    # Cameras stalled, recovery not in progress, recovery needed.
    STALLED         = 10

    # Attempting to automatically recovery cameras.
    RECOVERING      = 11
    # Camera recovery failed.
    RECOVER_FAILED  = 12


class VefbStatus(object):
    # Feedback operation successful.
    OK = 0

    # Feedback suspended during injection.
    INJECTING = 1

    # Emittance calc reports error status. Feedback suspended.
    EMITTANCE_WARNING = 2

    # Error of unknown type (e.g. uncaught exception). Feedback stops.
    UNKNOWN_ERROR = 3

    # No stored beam. Feedback stops.
    NO_STORED_BEAM = 4

    # Ring mode change with feedback running. Feedback stops.
    RING_MODE_CHANGE = 5

    # Magnet change exceeds threshold. Feedback stops if running.
    MAGNET_DELTA_ERROR = 6

    # Emittance value outside tolerable values. Feedback suspended.
    BAD_EMITTANCE_VALUE = 7

    # A parameter required for feedback to run. Feedback stopped/won't start.
    MISSING_CALC_PARAMETERS = 8

    # Error reading from/writing to magnet or with magnet drive levels.
    # Feedback stops if running.
    MAGNET_ERROR = 9

    # Cameras are in recovery. Feedback suspended.
    RECOVERING_CAMERAS = 10

    # No value from emittance IOC. Feedback suspended.
    NO_EMITTANCE_VALUE = 11

    # Time feedback is suspended due to errors exceeds theshold.
    # Feedback stops.
    PERSISTENT_EMITTANCE_ERRORS = 12

    # Applying corrections is having no effect.
    # Feedback stops before skew quads driven to bad position.
    HAVING_NO_EFFECT  = 13

    # VEMIT is too far away from target to start.
    # Feedback stops.
    AWAY_FROM_TARGET = 14

    # Calculation method changed while running feedback.
    # Feedback stops.
    METHOD_CHANGE = 15

#################################  Monitors  ###################################


class PVMonitor(object):
    def __init__(self, name):
        self.name = name
        self.ok = False
        self.value = None
        self.timestamp = 0
        camonitor(name, self.on_update,
            format = FORMAT_TIME, notify_disconnect = True)

    def on_update(self, value):
        self.ok = value.ok
        if value.ok:
            self.value = +value
            self.timestamp = value.timestamp
        else:
            self.value = None
            self.timestamp = time.time()


class WFMonitor(object):
    def __init__(self, names, dtype=np.double):
        self.names = names
        self.ok = False
        self.oks = np.zeros(len(names), dtype=np.bool)
        self.values = np.zeros(len(names), dtype=dtype)
        self.timestamps = np.zeros(len(names))
        camonitor(names, self.on_update,
            format = FORMAT_TIME, notify_disconnect = True)

    def on_update(self, value, index):
        self.oks[index] = value.ok
        if value.ok:
            self.values[index] = +value
            self.timestamps[index] = value.timestamp
        else:
            self.values[index] = np.nan
            self.timestamps[index] = time.time()
        self.ok = all(self.oks)


################################# SKEW QUADS ###################################


class SkewQuadrupoles(object):
    def __init__(self, mask=[]):
        self.monitors(mask)
        self.sp = None
        self.sum_delta = np.zeros(self.num)
        self._use_setpoint = False

        self.last_levels_ok_fail = None
        self.last_drvl_fail = None
        self.last_drvh_fail = None

    @property
    def num(self):
        return len(self.squad_pvs)


    def check_state(self):
        return self.ok and self.drive_levels_ok()


    @property
    def ok(self):
        pvs = [self.seti, self.seti_drvls, self.seti_drvls]
        return all([s.ok for s in pvs])


    def drive_levels_ok(self):
        for a,b,c in zip(self.seti_drvls.values,
                       self.seti_drvhs.values,
                       self.squad_pvs):
            if a >= b:
                if self.last_levels_ok_fail != c:
                    print "vefb: drive check", "DRVH <= DRVL", c
                    self.last_levels_ok_fail = c
                return False
        self.last_levels_ok_fail = None
        return True


    def make_setpoint(self):
        if self.seti.ok:
            self.sp = +self.seti.values
            self.sum_delta = np.zeros(self.num)


    def use_setpoint(self, use):
        if use and (self.sp is None or not self._use_setpoint):
            self.make_setpoint()
        self._use_setpoint = use


    def values_within_levels(self, values):
        drvhs = self.seti_drvhs.values
        drvls = self.seti_drvls.values

        for i in range(self.num):
            if values[i] < self.drvls[i]:
                if self.last_drvl_fail != i:
                    print "vefb: DRVL check", self.squad_pvs[i], \
                        ": New SQUAD value", values[i], "< DRVL", drvls[i]
                    self.last_drvl_fail = i
                    self.last_drvh_fail = None
                return False

        for i in range(self.num):
            if values[i] > self.drvhs[i]:
                if self.last_drvh_fail != i:
                    print "vefb: DRVH check", self.squad_pvs[i], \
                        ": New SQUAD value", values[i], "> DRVH", self.drvhs[i]
                    self.last_drvh_fail = i
                    self.last_drvl_fail = None
                return False

        self.last_drvl_fail = None
        self.last_drvh_fail = None

        return True


    def put_delta(self, delta):
        if self._use_setpoint:
            if self.sp is None:
                return False
            self.sum_delta += delta
            new_sqvals = self.sp + self.sum_delta
        elif self.seti.ok:
            new_sqvals = self.seti.values + delta
        else:
            return False

        if not self.ok:
            return False

        if not self.values_within_levels(new_sqvals):
            return False

        results = caput(self.squad_pvs, new_sqvals, throw=False)
        ok = np.all(map(bool, results))
        if not ok:
            print 'vefb: caput error'
            for s in [str(r) for r in results if not bool(r)]:
                print s
        return ok


    def monitors(self, mask):
        squad_pv_names = ['SR%02dA-PC-SQUAD-%02d' % (n,m)\
            for n in range(1,25) for m in range (1,5)]
        # Suitable only for post-DDBA configurations.
        squad_pv_names.insert(8, 'SR02A-PC-SQUAD-05')
        squad_pv_names.insert(9, 'SR02A-PC-SQUAD-06')

        # Remove masked values
        for m in mask:
            del squad_pv_names[m]

        squad_pvs = ['%s:SETI' % name for name in squad_pv_names ]
        self.squad_pvs = squad_pvs

        self.seti = WFMonitor(squad_pvs)

        squad_pv_drvhs = ['%s:SETI.DRVH' % name for name in squad_pv_names ]
        squad_pv_drvls = ['%s:SETI.DRVL' % name for name in squad_pv_names ]

        self.seti_drvhs = WFMonitor(squad_pv_drvhs)
        self.seti_drvls = WFMonitor(squad_pv_drvls)

        self.drvhs = self.seti_drvhs.values
        self.drvls = self.seti_drvls.values


################################# VEMIT FB #####################################


class VefbServer(object):

    def __init__(self, mode):
        self.skew_quads = SkewQuadrupoles()

        self.enabled = False
        self.enabled_first_time = False
        self.time_step = 0.2

        self.IRM        = None
        self.skewhw     = None
        self.IRM_old    = None
        self.skewhw_old = None
        self.IRM_new    = None
        self.skewhw_new = None

        self.last = None
        self.vemit_filtered = VefbConstants.VEMIT_TARGET_INITIAL
        self.last_calc_status = VefbStatus.OK
        self.delta = 0

        self.recovering_cameras = False

        self.error_or_recover_time = 0
        self.error_time = 0
        self.current_time = time.time()
        self.recovery_start_time = self.current_time
        self.sum_delta_oor = 0
        self.no_value_start_time = self.current_time

        self.monitors()
        self.records()

        mode.add_listener(self.on_ringmode_change)


    def init(self):
        cothread.Spawn(self.run)


    def init_wait(self, wait_time):
        print 'vefb: init wait'
        end_time = time.time() + wait_time

        while True:
            monitors = [ self.skew_quads,
                         self.vemit,
                         self.beam_current,
                         self.emit_status ]

            if np.all([pv.ok for pv in monitors]):
                print 'vefb: initialised ok'
                return
            if time.time() > end_time:
                print 'vefb: init timeout'
                return
            cothread.Sleep(self.time_step)


    def run(self):
        self.init_wait(3.0)
        while True:
            try:
                cothread.Sleep(self.time_step)
                current_time = time.time()
                self.run_once(self.enabled)

            except:
                print 'Vemit FB raised unexpected exception'
                traceback.print_exc()
                self.handle_status(VefbStatus.UNKNOWN_ERROR, False)


    def run_single(self, value):
        if not self.enabled:
            try:
                self.run_once(True, True)
            except:
                print 'Vemit FB raised unexpected exception'
                traceback.print_exc()
                self.handle_status(VefbStatus.UNKNOWN_ERROR, True)
        else:
             print 'vefb: single correct disabled in loopback mode'


    def add_single(self, value):
        if not self.enabled:
            try:
                self.run_add_delta(self.vemit_single_delta.get())
            except:
                print 'Vemit FB raised unexpected exception'
                traceback.print_exc()
                self.handle_status(VefbStatus.UNKNOWN_ERROR, True)
        else:
             print 'vefb: add delta single disabled in loopback mode'

    def sub_single(self, value):
        if not self.enabled:
            try:
                self.run_add_delta(-self.vemit_single_delta.get())
            except:
                print 'Vemit FB raised unexpected exception'
                traceback.print_exc()
                self.handle_status(VefbStatus.UNKNOWN_ERROR, True)
        else:
             print 'vefb: subtract delta single disabled in loopback mode'


    def error_check(self):

        status = VefbStatus.OK

        self.check_camera_state()

        if not self.calc_parameters_ok():
            return VefbStatus.MISSING_CALC_PARAMETERS

        if not self.have_stored_beam():
            status = VefbStatus.NO_STORED_BEAM

        elif not self.skew_quads.check_state():
            status = VefbStatus.MAGNET_ERROR

        elif self.recovering_cameras:
            status = VefbStatus.RECOVERING_CAMERAS

        elif self.away_from_target():
            status = VefbStatus.AWAY_FROM_TARGET

        elif self.is_injecting():
            status = VefbStatus.INJECTING

        elif self.emittance_status_bad():
            status = VefbStatus.EMITTANCE_WARNING

        return status

    def run_once(self, do_correction, single = False):

        status = self.error_check()

        if single and status == VefbStatus.AWAY_FROM_TARGET:
            status = VefbStatus.OK

        if status == VefbStatus.OK:
            if single:
                status = self.single_correct()
            elif do_correction:
                status = self.loop_correct()
            else:
                status = self.calc_only()

        self.vemit_filtered_pv.set(self.vemit_filtered)

        self.handle_status(status, single)

        self.enabled_first_time = False

    def on_ringmode_change(self, ringmode):
        self.last = None
        self.IRM = None
        self.IRM_old = None
        self.skewhw_old = None
        self.IRM_new = None
        self.skewhw_new = None

        # Remove skew quad 11-3 when we're using DIAD
        if ringmode in mode.DIAD_MODES:
            self.skew_quads = SkewQuadrupoles([44])
        else:
            self.skew_quads = SkewQuadrupoles()

        try:
            self.skewhw_old = np.ones(self.skew_quads.num)
            print 'skewhw_old', self.skewhw_old

            matDir = '/dls_sw/work/common/matlab/mml/machine/diamondopsdata/'
            rm_file = os.path.join(
                matDir, ringmode, 'GoldenCouplingEmittance.mat')
            print 'vefb: loadMatrix', ringmode, rm_file

            RM_load=loadmat(rm_file)
            RM=RM_load['RM']
            print 'RM_old=', RM
            self.IRM_old = 1/RM[0][0]
            print 'IRM_old', self.IRM_old

        except:
            print 'vefb ringmode_change raised unexpected exception'
            traceback.print_exc()

        try:
            rm_file = os.path.join(
                matDir, ringmode, 'GoldenSkewVector.mat')
            print 'vefb: loadSkewVector', ringmode, rm_file

            RM_load=loadmat(rm_file)
            RM=RM_load['RM']
            print 'RM_new=', RM
            skew=RM_load['skewhw'][0]
            print 'skew', skew
            self.IRM_new = 1/RM[0][0]
            self.skewhw_new = skew
            print 'IRM_new', self.IRM_new
            print 'skewhw_new', self.skewhw_new

        except:
            print 'vefb ringmode_change raised unexpected exception'
            traceback.print_exc()

        self.update_calc_parameters()

        if self.enabled:
           self.handle_status(VefbStatus.RING_MODE_CHANGE, True)
        else:
            self.handle_status(VefbStatus.OK, True)

    def on_method_change(self, value):
        if self.enabled:
           self.handle_status(VefbStatus.METHOD_CHANGE, True)
        self.update_calc_parameters()

    def update_calc_parameters(self):
        if self.method_pv.get() == 0:
            self.IRM = self.IRM_old
            self.skewhw = self.skewhw_old
        else:
            self.IRM = self.IRM_new
            self.skewhw = self.skewhw_new
        print 'IRM', self.IRM
        print 'skewhw', self.skewhw

    def handle_status(self, status, single):
        do_correction = single or self.enabled

        status = self.persistent_error_check(status)
        status = self.no_effect_check(status)

        status = self.filter_errors(status, do_correction)
        calc_status = status

        if not single:
            self.last_calc_status = calc_status
            self.calc_status_pv.set(calc_status)

        if do_correction:
            old_status = self.status_pv.get()
            if status != old_status:
                okStates = [ VefbStatus.OK,
                        VefbStatus.INJECTING]
                if status not in okStates or old_status not in okStates:
                    print 'vefb: status change', old_status, '->', status

            self.status_pv.set(status)
            if status not in [ VefbStatus.OK,
                       VefbStatus.INJECTING,
                       VefbStatus.EMITTANCE_WARNING,
                       VefbStatus.NO_EMITTANCE_VALUE,
                       VefbStatus.BAD_EMITTANCE_VALUE,
                       VefbStatus.RECOVERING_CAMERAS ]:
                self.enable_pv.set(0)

    def persistent_error_check(self, status):

        current_time = time.time()
        diff = current_time - self.current_time

        if status in [ VefbStatus.OK ]:
            self.error_or_recover_time = 0
            self.error_time = 0
        elif status in [ VefbStatus.INJECTING ]:
            pass
        elif status in [ VefbStatus.RECOVERING_CAMERAS ]:
            self.error_or_recover_time += diff
        else:
            self.error_or_recover_time += diff
            self.error_time += diff

        if self.enabled and \
                self.error_or_recover_time > self.max_recovery_time_pv.get():
            print 'vefb: time in error/recovery exceeds timeout', \
                      self.max_recovery_time_pv
            status = VefbStatus.PERSISTENT_EMITTANCE_ERRORS

        elif self.enabled and \
                (self.error_time > self.max_error_time_pv.get()):
            print 'vefb: time in error exceeds timeout', \
                    self.max_error_time_pv
            status = VefbStatus.PERSISTENT_EMITTANCE_ERRORS

        self.current_time = current_time

        return status


    def no_effect_check(self, status):
        if not self.enabled or status not in [ VefbStatus.OK ]:
            return status

        err = abs(self.vemit_filtered - self.vemit_target_pv.get())

        if err > self.vemit_acceptable_error_pv.get():
            self.sum_delta_oor += self.delta

            sum_delta_oor_threshold = self.oor_factor_max_pv.get() * self.IRM

            if self.no_effect_error_enable_pv.get() == 1 and \
                     abs(self.sum_delta_oor) > sum_delta_oor_threshold:
                print 'vefb: oor v:%.2f t:%.2f me:%.2f' % (self.vemit_filtered,
                         self.vemit_target_pv.get(),
                         self.vemit_acceptable_error_pv.get() )
                print 'sum_delta_oor %.6f exceeds threshold %.6f' \
                         % ( self.sum_delta_oor, sum_delta_oor_threshold
)
                status = VefbStatus.HAVING_NO_EFFECT

        else:
            self.sum_delta_oor = 0

        return status


    def filter_errors(self, status, do_correction):
        if status in [ VefbStatus.NO_EMITTANCE_VALUE ]:
             if self.last_calc_status not in [ VefbStatus.NO_EMITTANCE_VALUE ]:
                 self.no_value_start_time = self.current_time - VefbConstants.MAX_TS_AGE
                 status = VefbStatus.OK
             else:
                 no_value_time = (self.current_time - self.no_value_start_time)
                 if no_value_time < self.no_value_timeout.get():
                     status = VefbStatus.OK
                 elif do_correction:
                     print 'vefb: No value for %.2f. Exceeds threshold (%.2f)' \
                             % ( no_value_time, self.no_value_timeout.get() )

        else:
            self.no_value_start_time = self.current_time

        return status


    def check_camera_state(self):
        if self.recovering_cameras:
            current_time = time.time()
            min_recovery_timeout = self.min_camera_recovery_time_pv.get()
            max_recovery_timeout = self.max_camera_recovery_time_pv.get()
            recovery_time = current_time - self.recovery_start_time

            if recovery_time > min_recovery_timeout and \
                    self.camera_recovery_complete():
                print 'vefb: camera recovery successful after %g seconds' \
                        % recovery_time
                self.recovering_cameras = False

            elif recovery_time > max_recovery_timeout:
                print 'vefb: camera recovery timeout %g seconds exceeded' \
                        % max_recovery_timeout
                self.recovering_cameras = False

        elif self.cam_recovery_enable_pv.get() == 1:
            self.recovering_cameras = self.camera_recovery_started()
            if self.recovering_cameras:
                 current_time = time.time()
                 self.recovery_start_time = current_time
                 print 'vefb: camera recovery started'


    def camera_recovery_started(self):
        emit_status = self.emit_status.value
        return emit_status == EmittanceStatus.RECOVERING


    def camera_recovery_complete(self):
        emit_status = self.emit_status.value
        return emit_status == EmittanceStatus.OK


    def have_stored_beam(self):
        return self.beam_current.ok and \
            self.beam_current.value > self.dcct_threshold_pv.get()


    def is_injecting(self):
        return self.emit_status.value == EmittanceStatus.INJECTING


    def emittance_status_bad(self):
        if not self.emit_status.ok:
            return False
        return self.emit_status.value not in \
            [ EmittanceStatus.OK,
              EmittanceStatus.FORCED,
              EmittanceStatus.INJECTING ]


    def away_from_target(self):
        if (not self.enabled and not self.is_injecting()) \
                 or self.enabled_first_time:
            target = self.vemit_target_pv.get()
            threshold = self.vemit_fb_start_err_max_pv.get()
            err= min(abs(self.vemit.value - target), \
                abs(self.vemit_mean.value - target))
            if err > threshold:
                return True
        return False


    def set_enabled(self, value):
        print 'vefb: LOOP ENABLE:', value
        enabled = (value == 1)
        self.enabled = enabled
        self.enabled_first_time = True
        self.error_or_recover_time = 0
        self.error_time = 0
        if enabled:
            self.vemit_filtered = self.vemit_target_pv.get()
            self.sum_delta_oor = 0
        self.skew_quads.use_setpoint(enabled)


    def loop_correct(self):
        return self.do_calc(True)


    def single_correct(self):
        return self.do_calc(True, False, False)


    def calc_only(self):
        return self.do_calc(False)


    def calc_parameters_ok(self):
        return self.IRM is not None and \
                self.skewhw is not None and \
                len(self.skewhw) == self.skew_quads.num


    def do_calc(self, apply_calc, use_filter=True, check_limits=True):

        if not self.calc_parameters_ok():
            return VefbStatus.MISSING_CALC_PARAMETERS

        target = self.vemit_target_pv.get()
        vemit = self.vemit.value
        ts = self.vemit.timestamp

        current_time = time.time()
        age = current_time - ts

        # Timestamps ok?
        if age > VefbConstants.MAX_TS_AGE:
            return VefbStatus.NO_EMITTANCE_VALUE

        truncated = False
        vemit_raw = vemit

        # values ok?
        if check_limits:

            vmax = target + self.vemit_err_max_pv.get() + \
                self.vemit_extra_err_max_pv.get()
            if vemit > vmax:
                if apply_calc:
                    vemit = vmax
                    truncated = True

            vmin = target - self.vemit_err_max_pv.get() - \
                self.vemit_extra_err_max_pv.get()
            if vemit < vmin:
                if apply_calc:
                    vemit = vmin
                    truncated = True


        # apply filter (IIR) if required
        if use_filter:
            filter_frac = self.iir_frac_pv.get()
            filtered = filter_frac * vemit + \
                (1-filter_frac) * self.vemit_filtered
            vemit_used = filtered
            self.vemit_filtered = filtered
        else:
            vemit_used = vemit

        if check_limits:
            if truncated:
                print 'vemit truncated', vemit_raw, vemit, vemit_used

            vwrite_max = target + self.vemit_err_max_pv.get()
            if vemit_used > vwrite_max:
                if apply_calc:
                     print 'vemit too high - skip', vemit_used, 'MAX ', vwrite_max
                return VefbStatus.BAD_EMITTANCE_VALUE
            vwrite_min = target - self.vemit_err_max_pv.get()
            if vemit_used < vwrite_min:
                if apply_calc:
                    print 'vemit too low - skip', vemit_used, 'MIN ', vwrite_min
                return VefbStatus.BAD_EMITTANCE_VALUE


        # calc skew quad delta
        fraction = self.afrac_pv.get()
        delta = -fraction * self.IRM * (vemit_used-target)

        return self.apply_delta(delta, apply_calc, check_limits)


    def run_add_delta(self, delta):

        if (self.check_status_on_delta_pv.get() == 0):
            status = VefbStatus.OK
        else:
            status = self.error_check()

        if status == VefbStatus.OK or status == VefbStatus.AWAY_FROM_TARGET:
            status = self.apply_delta(delta)

        self.handle_status(status, True)


    def apply_delta(self, delta, apply_calc = True, check_limits = False):
        # check delta within limits and raise error or scale
        delta_max = self.squad_delta_max_pv.get()
        if check_limits:
            if np.abs(delta) > delta_max:
                return VefbStatus.MAGNET_DELTA_ERROR
        else:
            if delta_max <= 0:
                if apply_calc: print 'vefb: max delta non positive'
                return VefbStatus.MAGNET_DELTA_ERROR

            if delta > delta_max:
                if apply_calc: print 'vefb: delta scaled ', delta, '->', delta_max
                delta = delta_max
            elif delta < -delta_max:
                if apply_calc: print 'vefb: scaled ', delta, '->', -delta_max
                delta = -delta_max

        self.delta = delta

        # same correction applied to all skew quads
        sq_delta = delta * self.skewhw

        if apply_calc:
            # apply correction to skew quads
            ok = self.skew_quads.put_delta(sq_delta)
            if not ok:
                return VefbStatus.MAGNET_ERROR

        return VefbStatus.OK

    def monitors(self):
        self.vemit = PVMonitor('SR-DI-EMIT-01:VEMIT')
        self.vemit_mean = PVMonitor('SR-DI-EMIT-01:VEMIT_MEAN')
        self.beam_current = PVMonitor('SR21C-DI-DCCT-01:SIGNAL')
        self.emit_status =  PVMonitor('SR-DI-EMIT-01:STATUS')


    def records(self):
        builder.SetDeviceName("SR-CS-VEFB-01")

        self.enable_pv = builder.mbbOut(
                "LOOP", ("OFF", 0, "MINOR"), ("ON", 1),
                initial_value = 0, on_update = self.set_enabled)

        self.single_pv = builder.aOut("SINGLE", initial_value = 0,
                     on_update = self.run_single, always_update = True)

        self.add_delta_pv = builder.aOut("ADD_DELTA", initial_value = 0,
                     on_update = self.add_single, always_update = True)

        self.sub_delta_pv = builder.aOut("SUB_DELTA", initial_value = 0,
                     on_update = self.sub_single, always_update = True)

        self.method_pv = builder.mbbOut(
                "METHOD", ("OLD", 0), ("NEW", 1),
                on_update = self.on_method_change,
                initial_value = 1)

        self.afrac_pv = builder.aOut(
                "AFRAC", initial_value = VefbConstants.AFRAC_INITIAL,
                DRVH = 1, DRVL = 0, PREC = 2, EGU = "1")

        self.iir_frac_pv = builder.aOut(
                "IIRF_PARAM",
                initial_value = VefbConstants.IIRF_PARAM_INITIAL,
                DRVH = 1, DRVL = 0, PREC = 2, EGU = "1")


        self.dcct_threshold_pv = builder.aOut(
                "DCCT_THRESHOLD", initial_value = 5,
                DRVH = 1000, DRVL = 0, PREC = 4, EGU = "mA")

        self.vemit_single_delta = builder.aOut(
                "VEMIT_SINGLE_DELTA",
                initial_value = VefbConstants.VEMIT_SINGLE_DELTA_INITIAL,
                DRVH = VefbConstants.SQUAD_DELTA_MAX_INITIAL,
                DRVL = 0.0, PREC = 4, EGU = "A")

        self.check_status_on_delta_pv = builder.mbbOut(
                "CHECK_STATUS_ON_DELTA", ("DISABLED", 0), ("ENABLED", 1),
                 initial_value = 1)

        self.vemit_err_max_pv = builder.aOut(
                "VEMIT_TARGET_ERR_MAX",
                initial_value = VefbConstants.VEMIT_TARGET_ERR_MAX_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "pm rad")

        self.vemit_fb_start_err_max_pv = builder.aOut(
                "VEMIT_FB_START_ERR_MAX",
                initial_value = VefbConstants.VEMIT_FB_START_ERR_MAX_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "pm rad")

        self.vemit_extra_err_max_pv = builder.aOut(
                "VEMIT_EXTRA_TARGET_ERR_MAX",
                initial_value = VefbConstants.VEMIT_EXTRA_TARGET_ERR_MAX_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "pm rad")

        self.vemit_acceptable_error_pv = builder.aOut(
                "VEMIT_ACCEPTABLE_ERR",
                initial_value = VefbConstants.VEMIT_ACCEPTABLE_ERR_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "pm rad")

        self.oor_factor_max_pv = builder.aOut(
                "NO_EFFECT_FACTOR_DELTA_MAX",
                initial_value =
                    VefbConstants.NO_EFFECT_FACTOR_DELTA_MAX_INITIAL,
                PREC = 4, EGU = "A")

        self.vemit_target_pv = builder.aOut(
                "VEMIT_TARGET",
                initial_value = VefbConstants.VEMIT_TARGET_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = "1", EGU = "pm rad")

        self.vemit_filtered_pv = builder.aOut(
                "VEMIT_FILTERED",
                initial_value = VefbConstants.VEMIT_TARGET_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = "2", EGU = "pm rad")

        self.no_effect_error_enable_pv = builder.mbbOut(
                "NO_EFFECT_ERRORS", ("DISABLED", 0), ("ENABLED", 1),
                 initial_value = 1)

        self.no_value_timeout = builder.aOut(
                "NO_VALUE_TIMEOUT",
                initial_value = VefbConstants.NO_VALUE_TIMEOUT_INITIAL,
                DRVL = 0.0, PREC = 1, EGU = "s")

        self.max_error_time_pv = builder.aOut(
                "MAX_ERROR_TIME",
                initial_value = VefbConstants.MAX_ERROR_TIME_INITIAL,
                DRVL = 0.0, PREC = 1, EGU = "s")

        self.max_recovery_time_pv = builder.aOut(
                "MAX_RECOVERY_TIME",
                initial_value = VefbConstants.MAX_RECOVERY_TIME_INITIAL,
                DRVL = 0.0, PREC = 1, EGU = "s")

        self.min_camera_recovery_time_pv = builder.aOut(
                "MIN_CAM_RECOVERY_TIME",
                initial_value = VefbConstants.MIN_CAM_RECOVERY_TIME_INITIAL,
                DRVL = 0.0, PREC = 1, EGU = "s")

        self.max_camera_recovery_time_pv = builder.aOut(
                "MAX_CAM_RECOVERY_TIME",
                initial_value = VefbConstants.MAX_CAM_RECOVERY_TIME_INITIAL,
                DRVL = 0.0, PREC = 1, EGU = "s")

        self.cam_recovery_enable_pv = builder.mbbOut(
                "CAM_RECOVERY", ("DISABLED", 0), ("ENABLED", 1),
                 initial_value = 1)

        self.squad_delta_max_pv = builder.aOut(
                "SQUAD_DELTA_MAX",
                initial_value = VefbConstants.SQUAD_DELTA_MAX_INITIAL,
                PREC = 4, EGU = "A")

        self.status_pv = builder.mbbIn("STATUS",
             ("Ok", VefbStatus.OK),
             ("Injecting", VefbStatus.INJECTING),
             ("Bad emittance status", VefbStatus.EMITTANCE_WARNING, "MINOR"),
             ("Unknown error", VefbStatus.UNKNOWN_ERROR, "MAJOR"),
             ("No stored beam", VefbStatus.NO_STORED_BEAM, "MAJOR"),
             ("Ring mode change", VefbStatus.RING_MODE_CHANGE, "MAJOR"),
             ("Magnet delta error", VefbStatus.MAGNET_DELTA_ERROR, "MAJOR"),
             ("Bad emittance value", VefbStatus.BAD_EMITTANCE_VALUE, "MINOR"),
             ("Missing calc parameters",
                 VefbStatus.MISSING_CALC_PARAMETERS, "MAJOR"),
             ("Magnet Error", VefbStatus.MAGNET_ERROR, "MAJOR"),
             ("Recovering cameras", VefbStatus.RECOVERING_CAMERAS, "MINOR"),
             ("No emittance value", VefbStatus.NO_EMITTANCE_VALUE, "MINOR"),
             ("Persistent emittance err",
                 VefbStatus.PERSISTENT_EMITTANCE_ERRORS, "MAJOR"),
             ("Having no effect", VefbStatus.HAVING_NO_EFFECT, "MAJOR"),
             ("Away from target", VefbStatus.AWAY_FROM_TARGET, "MAJOR"),
             ("Method change", VefbStatus.METHOD_CHANGE, "MAJOR"),
             initial_value = VefbStatus.OK)


        self.calc_status_pv = builder.mbbIn("CALC_STATUS",
             ("Ok", VefbStatus.OK),
             ("Injecting", VefbStatus.INJECTING),
             ("Bad emittance status", VefbStatus.EMITTANCE_WARNING, "MINOR"),
             ("Unknown error", VefbStatus.UNKNOWN_ERROR, "MINOR"),
             ("No stored beam", VefbStatus.NO_STORED_BEAM, "MINOR"),
             ("Ring mode change", VefbStatus.RING_MODE_CHANGE, "MINOR"),
             ("Magnet delta error", VefbStatus.MAGNET_DELTA_ERROR, "MINOR"),
             ("Bad emittance value", VefbStatus.BAD_EMITTANCE_VALUE, "MINOR"),
             ("Missing calc parameters",
                  VefbStatus.MISSING_CALC_PARAMETERS, "MINOR"),
             ("Magnet Error", VefbStatus.MAGNET_ERROR, "MINOR"),
             ("Recovering cameras", VefbStatus.RECOVERING_CAMERAS, "MINOR"),
             ("No emittance value", VefbStatus.NO_EMITTANCE_VALUE, "MINOR"),
             ("Persistent emittance err",
                 VefbStatus.PERSISTENT_EMITTANCE_ERRORS, "MINOR"),
             ("Away from target", VefbStatus.AWAY_FROM_TARGET, "MINOR"),
             ("Method change", VefbStatus.METHOD_CHANGE, "MINOR"),
             initial_value = VefbStatus.OK)

