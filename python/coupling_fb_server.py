import os
import traceback
#import mml
from softioc import builder
import cothread
from cothread.catools import *
from numpy import *
from scipy.io import loadmat
import time

import coupling_fb


class emittance_status:
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


class coupling_fb_status:
    OK = 0
    INJECTING = 1
    EMITTANCE_WARNING = 2
    UNKNOWN_ERROR = 3
    NO_STORED_BEAM = 4    
    EMITTANCE_ERROR = 5
    RING_MODE_CHANGE = 6
    CALC_ERROR = 7
    BAD_EMITTANCE_VALUE = 8
    MISSING_CALC_PARAMETERS = 9

class coupling_fb_server(object):
    def monitor_wf(self, pvs):
        wf = zeros(len(pvs))
        ts = zeros(len(pvs))
        def on_update(value, index):
            wf[index] = value
            ts[index] = value.timestamp
        camonitor(pvs, on_update, format = FORMAT_TIME)
        return wf, ts

    def __init__(self, mode):
        print 'coupling_fb_srvr __init__'
        skew_quads = coupling_fb.skew_quadrupoles()
        self.skew_quads = skew_quads

        self.enabled = 0
        self.cpl_mode = 1
        self.debug = False #True
        self.threshold_debug = False #True

        self.time_step = 0.2
        current_time = time.time()
        self.last_good = current_time 
        self.last_apply = current_time

        cpl_fb = coupling_fb.cplfb_coupling(skew_quads)
        emit_fb = coupling_fb.cplfb_emit(skew_quads)
        sigmay_fb = coupling_fb.cplfb_sigmay(skew_quads)
        self.coupling_fbs = [ cpl_fb, emit_fb, sigmay_fb]

        self.set_target(coupling_fb.coupling_fb_constants.COUPLING_TARGET_INITIAL)
        self.setFraction(coupling_fb.coupling_fb_constants.AFRAC_INITIAL)

        self.beam_current, self.beam_current_ts = \
            self.monitor_wf(['SR21C-DI-DCCT-01:SIGNAL'])

        self.emit_status, self.emit_status_ts = \
            self.monitor_wf(['SR-DI-EMIT-01:STATUS'])

        self.records()
        mode.add_listener(self.on_ringmode_change)

    def init(self):
        cothread.Spawn(self.run)
        print 'coupling_fb_srvr starting'

    def run(self):
        while True:
            try:
                cothread.Sleep(self.time_step)
                do_correction = False
                current_time = time.time()
                do_correction = (self.enabled == 1)
                self.run_once(do_correction)

            except:
                print 'Coupling control raised unexpected exception'
                traceback.print_exc()
                self.handle_status(coupling_fb_status.UNKNOWN_ERROR, do_correction)  
                

    def run_once(self, do_correction, single = False):
        if self.debug: print 'run once', 'do_corection', do_correction
        if self.debug: 'EMIT STATUS', emit_status

        status = coupling_fb_status.UNKNOWN_ERROR

        if not self.have_stored_beam():
            print 'no stored beam'
            self.handle_status(coupling_fb_status.NO_STORED_BEAM, do_correction)
            return

        elif self.is_injecting():
            print 'injecting'
            self.last_good = time.time()
            self.handle_status(coupling_fb_status.INJECTING, do_correction)
            return

        elif not self.is_emittance_ok():
            print 'emittance status bad'
            self.handle_status(coupling_fb_status.EMITTANCE_ERROR, do_correction)
            return

        elif self.skip():
            print 'emittance status not ok, but not fatal yet - skip'
            status = coupling_fb_status.EMITTANCE_WARNING

        elif not self.coupling_fb().isMatrixOk():
            print 'no matrix'
            self.handle_status(coupling_fb_status.MISSING_CALC_PARAMETERS, do_correction)
            return
        else:
            if single:
                self.last_apply = time.time()
                calc_status = self.coupling_fb().single()            
            elif do_correction:
                self.last_apply = time.time()
                calc_status = self.coupling_fb().correct()
            else:
                calc_status = self.coupling_fb().calc()
            if calc_status == coupling_fb.status.OK:
                if self.debug: print 'correct OK' if do_correction else 'calc OK'
                self.last_good = time.time()
                status = coupling_fb_status.OK
            elif calc_status == coupling_fb.status.BAD_CALC_INPUT_TS:
                if self.debug: print 'correct OK' if do_correction else 'calc OK'
                status = coupling_fb_status.EMITTANCE_WARNING
            elif calc_status == coupling_fb.status.BAD_CALC_INPUT:
                if self.debug: print 'bad calc input - skip', 'correct' if do_correction else 'calc'
                status = coupling_fb_status.BAD_EMITTANCE_VALUE
            else:
                status = coupling_fb_status.CALC_ERROR
                print 'correct ERROR' if do_correction else 'calc ERROR'

        time_since_last_good = time.time() - self.last_good
        if self.debug: print 'tslg: ', time_since_last_good
        if time_since_last_good > self.time_since_last_good_threshold_pv.get():
            print 'tslg threshold exceeded', time_since_last_good
            status = coupling_fb_status.EMITTANCE_ERROR

        self.handle_status(status, do_correction)                
        if self.threshold_debug or self.debug: print

    def single(self, value):
        print 'single'
        self.run_once(True, True)


    def on_ringmode_change(self, ringmode):
        for fb in self.coupling_fbs:
            fb.on_ringmode_change(ringmode)
        self.on_mode_change()
        if self.enabled:
           self.handle_status(coupling_fb_status.RING_MODE_CHANGE, True)
        else:
            self.handle_status(coupling_fb_status.OK, True)
        self.skew_quads.make_setpoint()


    def on_mode_change(self):
        for fb in self.coupling_fbs:
            fb.on_mode_change(False)
        self.coupling_fb().on_mode_change(True)
        self.skew_quads.make_setpoint()
            
    def coupling_fb(self):
        return self.coupling_fbs[self.cpl_mode]


    def handle_status(self, status, do_correction):
        if self.debug: print 'handle status', status, do_correction
        self.calc_status_pv.set(status)
        if status in [ coupling_fb_status.OK, \
                       coupling_fb_status.INJECTING, \
                       coupling_fb_status.EMITTANCE_WARNING, \
                       coupling_fb_status.BAD_EMITTANCE_VALUE ]:
            self.calc_error.set(0)
            if do_correction or (self.enabled == 1):
                self.status_pv.set(status)
        else:
            self.calc_error.set(1)
            if do_correction or (self.enabled == 1):
                self.status_pv.set(status)
                self.on_error()

        self.matrix_error.set(0 if self.coupling_fb().isMatrixOk() else 1)
        cothread.Sleep(0.01)

    def have_stored_beam(self):
        beam_current = self.beam_current
        if self.debug: print beam_current
        return beam_current > self.dcct_threshold_pv.get()   


    def is_injecting(self):
        #return False

        """        
        try:
            self.inject_ctr = self.inject_ctr+1
            print 'INJ CTR', self.inject_ctr
        except:
            self.inject_ctr = 0
        if self.inject_ctr > 5:
            self.inject_ctr = 0
            return True
        return False
        """

        emit_status = self.emit_status
        return emit_status == emittance_status.INJECTING


    def skip(self):
        #return False       
        emit_status = self.emit_status
        return emit_status in [ emittance_status.SATURATED, \
                                emittance_status.TOO_DIM, \
                                emittance_status.FIT_ERROR, \
                                emittance_status.NO_TRIGGER, \
                                emittance_status.INJECTING, \
                                emittance_status.STALLED, ]


    def is_emittance_ok(self):
        #return True         
        emit_status = self.emit_status
        return emit_status in [ emittance_status.OK, \
                                emittance_status.FORCED, \
                                emittance_status.INJECTING, \
                                emittance_status.SATURATED, \
                                emittance_status.TOO_DIM, \
                                emittance_status.FIT_ERROR, \
                                emittance_status.NO_TRIGGER, \
                                emittance_status.INJECTING, \
                                emittance_status.STALLED ]


    def set_enabled(self, enabled):
        print 'ENABLE:', enabled
        self.enabled = enabled
        self.coupling_fb().enable(enabled)
        if enabled:
            self.skew_quads.make_setpoint()


    def set_cpl_mode(self, mode):
        print 'CPL MODE:', mode
        if mode != self.mode:
            self.cpl_mode = mode
            self.on_mode_change()


    def on_error(self):
        print 'error'
        self.enable_pv.set(0)


    def setFraction(self, value):
        for fb in self.coupling_fbs:
            fb.fraction = value


    def set_target(self, value):
        print 'TARGET:', value
        self.coupling_fbs[0].target = value


    def records(self):
        builder.SetDeviceName("SR-CS-CPLFB-01")

        self.target_pv = builder.aOut("TARGET", initial_value = self.coupling_fbs[0].target,
                     on_update = self.set_target, DRVL = 0.0, PREC = 4)

        self.enable_pv = builder.mbbOut('ONOFF', ("OFF", 0), ("ON", 1, "MINOR"),
                                       initial_value = self.enabled,
                                       on_update = self.set_enabled)


        builder.aOut("AFRAC", initial_value = self.coupling_fb().fraction, on_update = self.setFraction,
                     DRVH = 1, DRVL = 0, PREC = 2, EGU = "1")


        #builder.aOut("SVDT", initial_value = self.cpl.threshold,
        #             on_update = self.cpl.set_threshold,
        #             DRVH = 1, DRVL = 0, PREC = 4, EGU = "Hz")


        #self.period_pv = builder.aOut("PERIOD", initial_value = 5.0,
        #             DRVH = 10.0, DRVL = 0.1, PREC = 1, EGU = "s")

        self.matrix_error = builder.boolIn(
            "EMATRIX", DESC = "Matrix Error",
            initial_value = 0, ZNAM = "OK",
            ONAM = "coupling_fb MATRIX")

        self.calc_error = builder.boolIn(
            "ECALC", DESC = "Calculation Error",
            initial_value = 0, ZNAM = "OK",
            ONAM = "coupling_fb CALC")

        builder.aOut("CORRECT", initial_value = 0,
            on_update = self.single, always_update = True)

        self.cpl_mode_pv = builder.mbbOut('MODE', ("COUPLING", 0), ("VEMIT", 1), ("SIGMAY", 2),
                 initial_value = self.cpl_mode,
                 on_update = self.set_cpl_mode)


        self.dcct_threshold_pv = builder.aOut("DCCT_THRESHOLD", initial_value = 5,
                     DRVH = 1000, DRVL = 0, PREC = 4, EGU = "mA")


        self.status_pv = builder.mbbIn('STATUS',\
                 ("Ok", coupling_fb_status.OK),
                 ("Injecting", coupling_fb_status.INJECTING),
                 ("Transient emittance error", coupling_fb_status.EMITTANCE_WARNING, "MINOR"),
                 ("Unknown error", coupling_fb_status.UNKNOWN_ERROR, "MAJOR"),
                 ("No stored beam", coupling_fb_status.NO_STORED_BEAM, "MAJOR"),
                 ("Emitance calc error", coupling_fb_status.EMITTANCE_ERROR, "MAJOR"),
                 ("Ring mode change", coupling_fb_status.RING_MODE_CHANGE, "MAJOR"),
                 ("Calculation error", coupling_fb_status.CALC_ERROR, "MAJOR"),
                 ("Bad emittance value", coupling_fb_status.BAD_EMITTANCE_VALUE, "MINOR"),
                 ("Missing calc parameters", coupling_fb_status.MISSING_CALC_PARAMETERS, "MAJOR"),
                 initial_value = coupling_fb_status.OK)

        self.calc_status_pv = builder.mbbIn('CALC_STATUS',\
                 ("Ok", coupling_fb_status.OK),
                 ("Injecting", coupling_fb_status.INJECTING),
                 ("Transient emittance error", coupling_fb_status.EMITTANCE_WARNING, "MINOR"),
                 ("Unknown error", coupling_fb_status.UNKNOWN_ERROR, "MINOR"),
                 ("No stored beam", coupling_fb_status.NO_STORED_BEAM, "MINOR"),
                 ("Emitance calc error", coupling_fb_status.EMITTANCE_ERROR, "MINOR"),
                 ("Ring mode change", coupling_fb_status.RING_MODE_CHANGE, "MINOR"),
                 ("Calculation error", coupling_fb_status.CALC_ERROR, "MINOR"),
                 ("Bad emittance value", coupling_fb_status.BAD_EMITTANCE_VALUE, "MINOR"),
                 ("Missing calc parameters", coupling_fb_status.MISSING_CALC_PARAMETERS, "MINOR"),
                 initial_value = coupling_fb_status.OK)

        self.time_since_last_good_threshold_pv = builder.aOut("TSLG_THRESHOLD", initial_value = 10.0,
                     DRVL = 0.0, PREC = 1, EGU = "s")

