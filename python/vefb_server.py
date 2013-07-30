import os
import traceback
from softioc import builder
import cothread
from cothread.catools import *
from numpy import *
from scipy.io import loadmat
import time


class VEFBConstants:
    VEMIT_TARGET_INITIAL = 8.0
    AFRAC_INITIAL = 0.15
    IIRF_PARAM_INITIAL = 0.25
    MAX_TS_AGE = 0.35
    PS_DELTA_MAX_INITIAL = 0.01
    VEMIT_TARGET_ERR_MAX_INITIAL = 1.0


class EmittanceStatus:
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


class VEFBStatus:
    OK = 0
    INJECTING = 1
    EMITTANCE_WARNING = 2
    UNKNOWN_ERROR = 3
    NO_STORED_BEAM = 4    
    EMITTANCE_ERROR = 5
    RING_MODE_CHANGE = 6
    MAGNET_DELTA_ERROR = 7
    BAD_EMITTANCE_VALUE = 8
    MISSING_CALC_PARAMETERS = 9
    MAGNET_ERROR = 10
    RECOVERING_CAMERAS = 11
    NO_EMITTANCE_VALUE = 12
    PERSISTENT_EMITTANCE_ERRORS = 13

#################################  DEBUG WIDGET  ##############################################

class DebugWriter:
    NONE           =  0
    ERROR          =  1
    WARNING        =  2
    INFO           =  3
    THRESHOLD      =  4
    DEBUG          =  5
    VERBOSE_DEBUG  =  6
    ALL            =  7

    def __init__(self):
        self.lines = set()
        self.lines_last = set()
        self.tagged_lines = {}
        self.tagged_lines_last = {}
        self.dbg_level = self.INFO

    def dbg(self, dbg_level, *args):
        line = ' '.join(map(str, args))
        if dbg_level <= self.dbg_level:
            print line
      
    def dbg_unique(self, dbg_level, *args):
        line = ' '.join(map(str, args))
        if line not in self.lines_last and line not in self.lines:
            if dbg_level <= self.dbg_level:
                print line
                self.lines.add(line)

    def dbg_tag_unique(self, dbg_level, tag, *args):
        line = ' '.join(map(str, args))
        if tag not in self.tagged_lines_last and tag not in self.tagged_lines:
            if dbg_level <= self.dbg_level:
                print line
            self.tagged_lines[tag] = line

    def flush(self):
        self.lines_last = self.lines
        self.lines = set()
        self.tagged_lines_last = self.tagged_lines
        self.tagged_lines = {}


debug = DebugWriter()

#################################  Monitors  ##############################################

class PVMonitor:
    def __init__(self, name):
        self.name = name
        self.ok = False
        self.value = None
        self.timestamp = 0
        camonitor(name, self.on_update, format = FORMAT_TIME, notify_disconnect = True)

    def on_update(self, value):
        self.ok = value.ok
        if value.ok:
            self.value = +value
            self.timestamp = value.timestamp
        else:
            self.value = None
            self.timestamp = time.time()


class WFMonitor:
    def __init__(self, names, dtype=double):
        self.names = names
        self.ok = False
        self.oks = array([False for i in names], dtype = bool)
        self.values = zeros(len(names), dtype=dtype)
        self.timestamps = zeros(len(names))
        camonitor(names, self.on_update, format = FORMAT_TIME, notify_disconnect = True)

    def on_update(self, value, index):
        self.oks[index] = value.ok
        if value.ok:
            self.values[index] = +value
            self.timestamps[index] = value.timestamp
        else:
            self.values[index] = 0
            self.timestamps[index] = time.time()
        self.ok = all(self.oks)


################################# SKEW QUADS ####################################################

class SkewQuadrupoles:
    def __init__(self):
        self.monitors()
        self.sp = None
        self.sum_delta = zeros(self.num)
        self._use_setpoint = False

    
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
        for a,b, c in zip(self.seti_drvls.values,
                       self.seti_drvhs.values,
                       self.squad_pvs):
            if a >= b:
                debug.dbg_tag_unique(debug.ERROR, "drive check", "DRVH >= DRVL", c)
                return False
        return True


    def make_setpoint(self):
        if self.seti.ok:
            self.sp = +self.seti.values
            self.sum_delta = zeros(self.num)
            debug.dbg(debug.INFO, 'new set point')
            debug.dbg(debug.INFO, self.sp)


    def use_setpoint(self, use):
        if use and (self.sp is None or not self._use_setpoint):
            self.make_setpoint()
        self._use_setpoint = use


    def values_within_levels(self, values):
        drvhs = self.seti_drvhs.values
        drvls = self.seti_drvls.values

        debug.dbg(debug.VERBOSE_DEBUG, 'drvls', self.drvls)
        for i in range(len(self.drvls)):
            if values[i] < self.drvls[i]:
                debug.dbg_tag_unique(debug.ERROR, "DRVL check", self.squad_pvs[i],
                    ": New SQUAD value", values[i], "< DRVL", drvls[i])
                return False

        debug.dbg(debug.VERBOSE_DEBUG, 'drvhs', drvhs)
        for i in range(len(self.drvhs)):
            if values[i] > self.drvhs[i]:
                debug.dbg_tag_unique(debug.ERROR, "DRVH check", self.squad_pvs[i],
                    ": New SQUAD value", values[i], "> DRVH", self.drvhs[i])
                return False

        return True


    def put_delta(self, delta):
        if self._use_setpoint:
            if self.sp == None:
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
        ok = all(map(bool, results))
        if not ok:
            for s in [str(r) for r in results if not bool(r)]:
                print s
        return ok


    def monitors(self):
        squad_pv_names = ['SR%02dA-PC-SQUAD-%02d' % (n,m)\
            for n in range(1,25) for m in range (1,5)]

        squad_pvs = ['%s:SETI' % name for name in squad_pv_names ]
        self.squad_pvs = squad_pvs

        self.seti = WFMonitor(squad_pvs)

        squad_pv_drvhs = ['%s:SETI.DRVH' % name for name in squad_pv_names ]
        squad_pv_drvls = ['%s:SETI.DRVL' % name for name in squad_pv_names ]

        self.seti_drvhs = WFMonitor(squad_pv_drvhs)
        self.seti_drvls = WFMonitor(squad_pv_drvls)

        self.drvhs = self.seti_drvhs.values
        self.drvls = self.seti_drvls.values


################################# VEMIT FB ####################################################


class vefb_server:

    def __init__(self, mode):
        self.skew_quads = SkewQuadrupoles()

        self.enabled = False
        self.time_step = 0.2

        self.IRM = None
        self.last = None
        self.vemit_filtered = VEFBConstants.VEMIT_TARGET_INITIAL
        self.last_status = VEFBStatus.OK

        self.recovering_cameras = False
        
        self.error_or_recover_time = 0
        self.error_time = 0
        self.current_time = time.time()
        self.recovery_start_time = self.current_time

        self.monitors()
        self.records()

        mode.add_listener(self.on_ringmode_change)


    def init(self):
        cothread.Spawn(self.run)


    def init_wait(self, wait_time):
        print 'init wait'
        end_time = time.time() + wait_time
        
        while True:
            monitors = [ self.skew_quads,
                         self.vemit,
                         self.beam_current,
                         self.emit_status ]

            if all([pv.ok for pv in monitors]):
                print 'initialised ok'
                return
            if time.time() > end_time:
                print 'init timeout'
                return
            cothread.Sleep(self.time_step)
            

    def run(self):
        self.init_wait(3.0)
        while True:
            try:
                cothread.Sleep(self.time_step)
                current_time = time.time()
                do_correction = self.enabled
                self.run_once(do_correction)
                debug.flush()

            except:
                debug.dbg(debug.ERROR, 'Vemit control raised unexpected exception')
                traceback.print_exc()
                self.handle_status(VEFBStatus.UNKNOWN_ERROR, do_correction)         
                

    def run_once(self, do_correction, single = False):
        status = VEFBStatus.UNKNOWN_ERROR

        self.check_camera_state()

        if not self.have_stored_beam():
            debug.dbg_unique(debug.ERROR, 'no stored beam')
            status = VEFBStatus.NO_STORED_BEAM

        elif not self.skew_quads.check_state():
            debug.dbg_unique(debug.ERROR, 'skew quad error')
            status = VEFBStatus.MAGNET_ERROR

        elif self.recovering_cameras:
            status = VEFBStatus.RECOVERING_CAMERAS

        elif self.is_injecting():
            debug.dbg_unique(debug.INFO, 'injecting')
            status = VEFBStatus.INJECTING

        elif self.emittance_status_bad():
            debug.dbg_unique(debug.WARNING,
                'emittance status %d not ok, but not fatal yet - skip' % self.emit_status.value)
            status = VEFBStatus.EMITTANCE_WARNING

        else:
            if single:
                status = self.single_correct()
            elif do_correction:
                status = self.loop_correct()
            else:
                status = self.calc_only()

        self.handle_status(status, do_correction)


    def single(self, value):
        debug.dbg(debug.INFO, 'single')
        self.run_once(True, True)


    def on_ringmode_change(self, ringmode):
        try:
            self.last = None
            self.IRM = None

            matDir = '/dls_sw/work/common/matlab/mml/machine/diamondopsdata/'
            rm_file = os.path.join(matDir, ringmode, 'GoldenCouplingEmittance.mat')
            debug.dbg(debug.INFO, 'emitfb: loadMatrix', ringmode, rm_file)

            RM_load=loadmat(rm_file)
            RM=RM_load['RM']
            debug.dbg(debug.INFO, 'RM=', RM)
            self.IRM_ = linalg.pinv(RM)
            self.IRM = 1/RM[0][0]
            debug.dbg(debug.INFO,'IRM', self.IRM)

        except:
            debug.dbg(debug.ERROR, 'emitfb ringmode_change raised unexpected exception')
            traceback.print_exc()

        if self.enabled:
           self.handle_status(VEFBStatus.RING_MODE_CHANGE, True)
        else:
            self.handle_status(VEFBStatus.OK, True)


    def handle_status(self, status, do_correction):
        debug.dbg(debug.DEBUG, 'handle status', status, do_correction)

        status = self.persistent_error_check(status)

        if self.last_status != status:
            debug.dbg(debug.INFO, 'vefb status change', self.last_status, '->', status)
            if status == VEFBStatus.OK:
                debug.dbg(debug.INFO, 'OK again')
        self.last_status = status

        self.calc_status_pv.set(status)
        if status in [ VEFBStatus.OK,
                       VEFBStatus.INJECTING,
                       VEFBStatus.EMITTANCE_WARNING,
                       VEFBStatus.NO_EMITTANCE_VALUE,
                       VEFBStatus.BAD_EMITTANCE_VALUE,
                       VEFBStatus.RECOVERING_CAMERAS ]:
            if do_correction or self.enabled:
                self.status_pv.set(status)

        elif do_correction or self.enabled:
                self.status_pv.set(status)
                self.enable_pv.set(0)


    def persistent_error_check(self, status):

        current_time = time.time()
        diff = current_time - self.current_time

        if status in [ VEFBStatus.OK ]:
            self.error_or_recover_time = 0
            self.error_time = 0
        elif status in [ VEFBStatus.INJECTING ]:
            pass
        elif status in [ VEFBStatus.RECOVERING_CAMERAS ]:
            self.error_or_recover_time += diff
        else:
            self.error_or_recover_time += diff
            self.error_time += diff

        if self.enabled and \
                self.error_or_recover_time > self.max_recovery_time_pv.get():
            debug.dbg(debug.ERROR, 'time in error/recovery exceeds timeout',
                      self.max_recovery_time_pv)
            status = VEFBStatus.PERSISTENT_EMITTANCE_ERRORS

        elif self.enabled and \
                (self.error_time > self.max_error_time_pv.get()):
            debug.dbg(debug.ERROR, 'time in error exceeds timeout',
                    self.max_error_time_pv)
            status = VEFBStatus.PERSISTENT_EMITTANCE_ERRORS

        self.current_time = current_time

        return status


    def check_camera_state(self):
        if self.recovering_cameras:
            current_time = time.time()
            min_recovery_timeout = self.min_camera_recovery_time_pv.get()
            max_recovery_timeout = self.max_camera_recovery_time_pv.get()
            recovery_time = current_time - self.recovery_start_time

            if recovery_time > min_recovery_timeout and \
                    self.camera_recovery_complete():
                message = 'camera recovery successful after %g seconds' % recovery_time
                debug.dbg(debug.INFO, message)
                self.recovering_cameras = False
            else:
                if recovery_time > max_recovery_timeout:
                    debug.dbg(debug.INFO,
                        'camera recovery timeout %g seconds exceeded' % max_recovery_timeout)
                    self.recovering_cameras = False

        elif self.cam_recovery_enable_pv.get() == 1:
            self.recovering_cameras = self.camera_recovery_started()
            if self.recovering_cameras:
                 current_time = time.time()
                 self.recovery_start_time = current_time
                 debug.dbg(debug.INFO, 'camera recovery started')


    def camera_recovery_started(self):
        emit_status = self.emit_status.value
        return emit_status == EmittanceStatus.RECOVERING


    def camera_recovery_complete(self):
        emit_status = self.emit_status.value
        return emit_status == EmittanceStatus.OK


    def have_stored_beam(self):
        ok = self.beam_current.ok
        beam_current = self.beam_current.value
        debug.dbg(debug.DEBUG, ok, beam_current)
        return ok and beam_current > self.dcct_threshold_pv.get()


    def is_injecting(self):
        return self.emit_status.value == EmittanceStatus.INJECTING


    def emittance_status_bad(self):
        if not self.emit_status.ok:
            print 'Emit Status PV not ok'
            return False
        return self.emit_status.value not in \
            [ EmittanceStatus.OK,
              EmittanceStatus.FORCED,
              EmittanceStatus.INJECTING ]


    def set_enabled(self, enabled):
        debug.dbg(debug.INFO, 'ENABLE:', enabled)
        self.enabled = (enabled == 1)
        self.error_or_recover_time = 0
        self.error_time = 0
        if enabled:
            self.vemit_filtered = self.vemit_target_pv.get()
        self.skew_quads.use_setpoint(enabled)


    def loop_correct(self):
        return self.do_calc(True)


    def single_correct(self):
        return self.do_calc(True, False, False)


    def calc_only(self):
        return self.do_calc(False)


    def calc_parameters_ok(self):
        return self.IRM is not None


    def do_calc(self, apply_calc, use_filter=True, check_limits=True):
        
        if not self.calc_parameters_ok():
            debug.dbg(debug.ERROR, 'No matrix')
            return VEFBStatus.MISSING_CALC_PARAMETERS

        target = self.vemit_target_pv.get()
        vemit = self.vemit.value
        ts = self.vemit.timestamp

        current_time = time.time()
        age = current_time - ts

        # Timestamps ok?
        if age > VEFBConstants.MAX_TS_AGE:
            debug.dbg_unique(debug.WARNING, 'vemit ts too old - bail out')
            return VEFBStatus.NO_EMITTANCE_VALUE
            
        # values ok?
        if check_limits:
            vmax = target + self.vemit_err_max_pv.get()
            if vemit > vmax:
                debug.dbg_tag_unique(debug.WARNING, 'VEMIT BIG',
                    'vemit too high - bail out', vemit, 'MAX ', vmax)
                return VEFBStatus.BAD_EMITTANCE_VALUE
                
            vmin = target - self.vemit_err_max_pv.get()
            if vemit < vmin:
                debug.dbg_tag_unique(debug.WARNING, 'VEMIT SMALL',
                    'vemit too low - bail out', 'vemit ', vemit, 'MIN ', vmin)
                return VEFBStatus.BAD_EMITTANCE_VALUE

        # apply filter (IIR) if required
        if use_filter:
            filter_frac = self.iir_frac_pv.get()
            filtered = filter_frac * vemit + (1-filter_frac) * self.vemit_filtered
            vemit_used = filtered if use_filter else vemit
            self.vemit_filtered = filtered
        else:
            vemit_used = vemit

        # calc skew quad delta
        fraction = self.afrac_pv.get()
        delta = -fraction * self.IRM * (vemit_used-target)

        # check delta within limits and raise error or scale
        delta_max = self.squad_delta_max_pv.get()
        if check_limits:
            if abs(delta) > delta_max:
                return VEFBStatus.MAGNET_DELTA_ERROR
        else:
            if delta_max <= 0:
                debug.dbg(debug.ERROR, 'max delta non positive')
                return VEFBStatus.MAGNET_DELTA_ERROR

            if delta > delta_max:
                print 'scaled ', delta, '->', delta_max
                delta = delta_max
            elif delta < -delta_max:
                print 'scaled ', delta, '->', -delta_max
                delta = -delta_max

        # same correction applied to all skew quads
        num_squads = self.skew_quads.num
        sq_delta = array([ delta ] * num_squads)

        if apply_calc:
            # apply correction to skew quads
            ok = self.skew_quads.put_delta(sq_delta)
            if not ok:
                return VEFBStatus.MAGNET_ERROR

        return VEFBStatus.OK


    def monitors(self):
        self.vemit = PVMonitor('SR-DI-EMIT-01:VEMIT')
        self.beam_current = PVMonitor('SR21C-DI-DCCT-01:SIGNAL')
        self.emit_status =  PVMonitor('SR-DI-EMIT-01:STATUS')


    def records(self):
        builder.SetDeviceName("SR-CS-VEFB-01")

        self.enable_pv = builder.mbbOut(
                'LOOP', ("OFF", 0, "MINOR"), ("ON", 1),
                initial_value = 0, on_update = self.set_enabled)

        builder.aOut("SINGLE", initial_value = 0,
                     on_update = self.single, always_update = True)

        self.afrac_pv = builder.aOut(
                "AFRAC", initial_value = VEFBConstants.AFRAC_INITIAL,
                DRVH = 1, DRVL = 0, PREC = 2, EGU = "1")
    
        self.iir_frac_pv = builder.aOut(
                "IIRF_PARAM",
                initial_value = VEFBConstants.IIRF_PARAM_INITIAL,
                DRVH = 1, DRVL = 0, PREC = 2, EGU = "1")


        self.dcct_threshold_pv = builder.aOut(
                "DCCT_THRESHOLD", initial_value = 5,
                DRVH = 1000, DRVL = 0, PREC = 4, EGU = "mA")

        self.vemit_err_max_pv = builder.aOut(
                "VEMIT_TARGET_ERR_MAX",
                initial_value = VEFBConstants.VEMIT_TARGET_ERR_MAX_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "pm rad")

        self.vemit_target_pv = builder.aOut(
                "VEMIT_TARGET",
                initial_value = VEFBConstants.VEMIT_TARGET_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = "1", EGU = "pm rad")

        self.max_error_time_pv = builder.aOut(
                 "MAX_ERROR_TIME", initial_value = 24.0,
                 DRVL = 0.0, PREC = 1, EGU = "s")

        self.max_recovery_time_pv = builder.aOut(
                 "MAX_RECOVERY_TIME", initial_value = 120,
                 DRVL = 0.0, PREC = 1, EGU = "s")

        self.min_camera_recovery_time_pv = builder.aOut(
                     "MIN_CAM_RECOVERY_TIME",
                     initial_value = 35, DRVL = 0.0, PREC = 1, EGU = "s")

        self.max_camera_recovery_time_pv = builder.aOut("MAX_CAM_RECOVERY_TIME",
                     initial_value = 50, DRVL = 0.0, PREC = 1, EGU = "s")

        self.cam_recovery_enable_pv = builder.mbbOut(
                'CAM_RECOVERY', ("DISABLED", 0), ("ENABLED", 1),
                 initial_value = 1)

        self.squad_delta_max_pv = builder.aOut(
                "SQUAD_DELTA_MAX",
                initial_value = VEFBConstants.PS_DELTA_MAX_INITIAL,
                PREC = 4, EGU = "A")


        self.status_pv = builder.mbbIn('STATUS',
             ("Ok", VEFBStatus.OK),
             ("Injecting", VEFBStatus.INJECTING),
             ("Bad emittance status", VEFBStatus.EMITTANCE_WARNING, "MINOR"),
             ("Unknown error", VEFBStatus.UNKNOWN_ERROR, "MAJOR"),
             ("No stored beam", VEFBStatus.NO_STORED_BEAM, "MAJOR"),
             ("Emittance calc error", VEFBStatus.EMITTANCE_ERROR, "MAJOR"),
             ("Ring mode change", VEFBStatus.RING_MODE_CHANGE, "MAJOR"),
             ("Magnet delta error", VEFBStatus.MAGNET_DELTA_ERROR, "MAJOR"),
             ("Bad emittance value", VEFBStatus.BAD_EMITTANCE_VALUE, "MINOR"),
             ("Missing calc parameters", VEFBStatus.MISSING_CALC_PARAMETERS, "MAJOR"),
             ("Magnet Error", VEFBStatus.MAGNET_ERROR, "MAJOR"),
             ("Recovering cameras", VEFBStatus.RECOVERING_CAMERAS, "MINOR"),
             ("No emittance value", VEFBStatus.NO_EMITTANCE_VALUE, "MINOR"),
             ("Persistent emittance err", VEFBStatus.PERSISTENT_EMITTANCE_ERRORS, "MAJOR"),
             initial_value = VEFBStatus.OK)


        self.calc_status_pv = builder.mbbIn('CALC_STATUS',
             ("Ok", VEFBStatus.OK),
             ("Injecting", VEFBStatus.INJECTING),
             ("Bad emittance status", VEFBStatus.EMITTANCE_WARNING, "MINOR"),
             ("Unknown error", VEFBStatus.UNKNOWN_ERROR, "MINOR"),
             ("No stored beam", VEFBStatus.NO_STORED_BEAM, "MINOR"),
             ("Emittance calc error", VEFBStatus.EMITTANCE_ERROR, "MINOR"),
             ("Ring mode change", VEFBStatus.RING_MODE_CHANGE, "MINOR"),
             ("Magnet delta error", VEFBStatus.MAGNET_DELTA_ERROR, "MINOR"),
             ("Bad emittance value", VEFBStatus.BAD_EMITTANCE_VALUE, "MINOR"),
             ("Missing calc parameters", VEFBStatus.MISSING_CALC_PARAMETERS, "MINOR"),
             ("Magnet Error", VEFBStatus.MAGNET_ERROR, "MINOR"),
             ("Recovering cameras", VEFBStatus.RECOVERING_CAMERAS, "MINOR"),
             ("No emittance value", VEFBStatus.NO_EMITTANCE_VALUE, "MINOR"),
             ("Persistent emittance err", VEFBStatus.PERSISTENT_EMITTANCE_ERRORS, "MINOR"),
             initial_value = VEFBStatus.OK)

