

from cothread.catools import *
from scipy.io import *
from numpy import *
import time
import traceback
import os
from softioc import builder
from math import sqrt

class coupling_fb_constants:
    COUPLING_TARGET_INITIAL = 0.3
    MAX_TS_AGE = 0.3
    MAX_PS_TS_AGE = 2
    PS_DELTA_MAX_INITIAL = 0.1
    PS_DELTA_RMS_MAX_INITIAL = 10
    COUPLING_MAX_INITIAL = 0.5
    COUPLING_MIN_INITIAL = 0.1
    COUPLING_MAX_CHANGE_INITIAL = 0.1
    VEMIT_MAX_INITIAL = 100
    VEMIT_MIN_INITIAL = 1
    VEMIT_MAX_CHANGE_INITIAL = 1
    SIGMAY_MAX_INITIAL = [100.0, 100.0 ]
    SIGMAY_MIN_INITIAL = [ 0.0, 0.0 ]
    SIGMAY_MAX_CHANGE_INITIAL = [ 10.0, 10.0]

class calc_exception(Exception):
    pass

class status:
    OK = 0
    BAD_CALC_INPUT_TS = 1
    BAD_CALC_INPUT = 2
    BAD_PS_VAL = 3
    BAD_PS_OUT = 4        


################################# SKEW QUADS ####################################################

class skew_quadrupoles(object):
    def monitor_wf(self, pvs):
        wf = zeros(len(pvs))
        ts = zeros(len(pvs))
        def on_update(value, index):
            wf[index] = value
            ts[index] = value.timestamp
        camonitor(pvs, on_update, format = FORMAT_TIME)
        return wf, ts

    def __init__(self):
        self.debug = False #True
        self.threshold_debug = False #True

        self.squad_pvs= ['SR%02dA-PC-SQUAD-%02d:SETI' % (n,m)  for n in range(1,25) for m in range (1,5)]

        self.squad_vals, self.squad_vals_ts = \
            self.monitor_wf(['SR%02dA-PC-SQUAD-%02d:I' % (n,m)  for n in range(1,25) for m in range (1,5)])

        self.drvhs = caget(['SR%02dA-PC-SQUAD-%02d:SETI.DRVH' % (n,m)  for n in range(1,25) for m in range (1,5)])
        self.drvls = caget(['SR%02dA-PC-SQUAD-%02d:SETI.DRVL' % (n,m)  for n in range(1,25) for m in range (1,5)])

        self.record()

    def current_values_ok(self):
        return True

    def delta_ok(self, delta):
        sqvals = self.squad_vals
        new_sqvals = array([ val + delta[0] for val in sqvals])

        if self.debug: print 'new_sqvals', new_sqvals

        if self.debug: print 'drvhs', self.drvhs
        for i in range(len(self.drvhs)):
            if new_sqvals[i] > self.drvhs[i]:
                print i, "too high", new_sqvals[i], self.drvhs[i]
                return False

        if self.debug: print 'drvls', self.drvls
        for i in range(len(self.drvls)):
            if new_sqvals[i] < self.drvls[i]:
                print i, "too low", new_sqvals[i], self.drvls[i]
                return False

        max_delta = max([abs(d) for d in delta])
        if self.threshold_debug or self.debug:  print 'max delta', max_delta
        if max_delta > self.ps_delta_max_pv.get():
            print 'max delta too big', max_delta, '>', self.ps_delta_max_pv.get()
            return False

        rms = sqrt(sum([i*i for i in delta]))
        if self.threshold_debug or self.debug: print 'delta rms', rms 
        if sum([i*i for i in delta]) > self.ps_delta_rms_max_pv.get():
            print 'max delta too big', max_delta, '>', self.ps_delta_max_pv.get()
            return False

        return True


    def put_delta(self, delta):
        new_sqvals = array([ val + delta[0] for val in self.squad_vals])
        caput(self.squad_pvs, new_sqvals)


    def record(self):
        builder.SetDeviceName("SR-CS-CPLFB-01")

        self.ps_delta_max_pv = self.coupling_max_pv = self.period_pv = builder.aOut("PS_DELTA_MAX",
                initial_value = coupling_fb_constants.PS_DELTA_MAX_INITIAL,
                PREC = 4, EGU = "A")

        self.ps_delta_rms_max_pv = self.coupling_max_pv = self.period_pv = builder.aOut("PS_DELTA_RMS_MAX",
                initial_value = coupling_fb_constants.PS_DELTA_RMS_MAX_INITIAL,
                PREC = 4, EGU = "A")         

################################# COUPLING FB ####################################################


class cplfb_coupling(object):
#    def monitor_pv(self, pv, name, initial_value=0, **kargs):
#        def on_update(value):
#            setattr(self, name, value)
#        setattr(self, name, initial_value)
#        camonitor(pv, on_update, **kargs)

    def monitor_wf(self, pvs):
        wf = zeros(len(pvs))
        ts = zeros(len(pvs))
        def on_update(value, index):
            wf[index] = value
            ts[index] = value.timestamp
        camonitor(pvs, on_update, format = FORMAT_TIME)
        return wf, ts

    def __init__(self, skew_quads):
        print 'emitfb: __init__'
        self.RM = None
        self.use_mean = False

        self.debug = False #True
        self.threshold_debug = False #True
        self.fraction = 0.5
        self.target = 0.3
        self.last = None

        self.skew_quads = skew_quads

        self.emit_coupling_mean, self.emit_coupling_mean_ts = \
            self.monitor_wf(['SR-DI-EMIT-01:COUPLING_MEAN'])

        self.emit_coupling, self.emit_coupling_ts = \
            self.monitor_wf(['SR-DI-EMIT-01:COUPLING'])

        self.record()

    def on_ringmode_change(self, ringmode):
        try:
            self.IRM = self.RM = None
            print 'emitfb: loadMatrix', ringmode
            matDir = '/dls_sw/work/common/matlab/mml/machine/diamondopsdata/' + ringmode
            rm_file = os.path.join(matDir, 'GoldenCoupling.mat')
            RM_load=loadmat(rm_file)
            self.RM=RM_load['RM']
            if self.debug: print 'RM', self.RM
            self.IRM = linalg.pinv(self.RM)
            if self.debug: print 'IRM', self.IRM

        except:
            print 'emitfb ringmode_change raised unexpected exception'
            traceback.print_exc()


    def on_mode_change(self, on):
        pass


    def correct(self):
        rv = self.do_calc(True)
        if self.debug: print 'emitfb correct() done'
        return rv

    def calc(self):
        rv = self.do_calc(False)
        if self.debug: print 'emitfb calc() done'
        return rv


    def isMatrixOk(self):
        return not (self.RM == None)


    def do_calc(self, apply_calc):
        if self.debug: print 'emitfb calc() %%', self.fraction

        self.use_mean = self.use_mean_pv.get()

        if not self.isMatrixOk():
            print 'No matrix'
            raise calc_exception

        target = self.target
        if self.debug: print 'target', target

        current = self.emit_coupling_mean if self.use_mean else self.emit_coupling_mean

        ts = self.emit_coupling_mean_ts if self.use_mean else self.emit_coupling_mean_ts
        current_time = time.time()
        if self.debug: print 'current monitored + ts + time:'
        if self.debug: print current, ts, current_time

        age = current_time - ts.min()
        if self.threshold_debug or self.debug:
             print 'age', age, 'MAX', coupling_fb_constants.MAX_TS_AGE 
        
        # Timestamps ok?
        if age > coupling_fb_constants.MAX_TS_AGE:
            print 'coupling ts too old - bail out'
            return status.BAD_CALC_INPUT_TS
        
        if self.debug:
            if self.use_mean:
                print 'using mean'
                print caget(['SR-DI-EMIT-01:COUPLING_MEAN'])
                print current
            else:
                print 'using latest'
                caget(['SR-DI-EMIT-01:COUPLING'])
                print current            


        # vals ok
        if self.threshold_debug or self.debug:
             print 'coupling ', current, '  MAX ', self.coupling_max_pv.get()
        if current > self.coupling_max_pv.get():
            print 'coupling too high - bail out'
            return status.BAD_CALC_INPUT            

        if self.threshold_debug or self.debug:
             print 'coupling ', current, '  MIN ', self.coupling_min_pv.get()
        if current < self.coupling_min_pv.get():
            print 'coupling too low - bail out'
            return status.BAD_CALC_INPUT

        if self.last != None:
            last = self.last
            change = current[0] - last[0]
            if self.threshold_debug or self.debug:
                print 'current', current[0], 'last', last[0], 'change ', change
                print 'change ', change, '  MAX_CHANGE ', self.coupling_max_change_pv.get()

            if abs(change) > self.coupling_max_change_pv.get():
                print 'coupling change too big - bail out'
                return status.BAD_CALC_INPUT
                
        self.last = +current


        diff = current-target

        if self.debug: print 'IRM', self.IRM
        if self.debug: print 'diff', diff

        delta = -self.fraction*dot(self.IRM, diff)
        if self.debug: print 'delta', delta
        
        sqvals = self.skew_quads.squad_vals
        #if self.debug: print 'sqvals', sqvals             

        sq_delta = [ delta[0] for val in sqvals]

        if not self.skew_quads.current_values_ok():
            return status.BAD_PS_VAL
        
        if not self.skew_quads.delta_ok(sq_delta):
            return status.BAD_PS_OUT

        if apply_calc:
            self.skew_quads.put_delta(sq_delta)

        return status.OK

    """
    def input_ts_ok(self):

        target = self.target
        print 'target', target

        ts = self.emit_coupling_mean_ts
        current_time = time.time()
        if self.debug: print 'current monitored + ts + time:'
        if self.debug: print current, ts, current_time

        age = current_time - ts.min()
        if self.debug: print 'age', age
        
        return age <= coupling_fb_constants.MAX_TS_AGE:
    """    


    def record(self):
        builder.SetDeviceName("SR-CS-CPLFB-01")

        self.use_mean_pv = builder.mbbOut('WHICH_COUPLING', ("CURRENT", 0), ("MEAN", 1),
                                       initial_value = 1 if self.use_mean else 0 )

        self.coupling_max_pv = builder.aOut("COUPLING_MAX",
                initial_value = coupling_fb_constants.COUPLING_MAX_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "%")        

        self.coupling_min_pv = builder.aOut("COUPLING_MIN",
                initial_value = coupling_fb_constants.COUPLING_MIN_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "%")

        self.coupling_max_change_pv = builder.aOut("COUPLING_MAX_CHANGE",
                initial_value = coupling_fb_constants.COUPLING_MAX_CHANGE_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "%")



################################# VEMIT FB ####################################################


class cplfb_emit(object):
#    def monitor_pv(self, pv, name, initial_value=0, **kargs):
#        def on_update(value):
#            setattr(self, name, value)
#        setattr(self, name, initial_value)
#        camonitor(pv, on_update, **kargs)

    def monitor_wf(self, pvs):
        wf = zeros(len(pvs))
        ts = zeros(len(pvs))
        def on_update(value, index):
            wf[index] = value
            ts[index] = value.timestamp
        camonitor(pvs, on_update, format = FORMAT_TIME)
        return wf, ts

    def __init__(self, skew_quads):
        print 'emitfb: __init__'
        self.RM = None
        self.use_mean = False

        self.debug = False #True
        self.threshold_debug = False #True

        self.fraction = 0.5
        
        self.last = None

        self.skew_quads = skew_quads

        self.vemit_mean, self.vemit_mean_ts = \
            self.monitor_wf(['SR-DI-EMIT-01:VEMIT_MEAN'])

        self.vemit, self.vemit_ts = \
            self.monitor_wf(['SR-DI-EMIT-01:VEMIT'])

        self.get_target()

        self.record()

    def on_ringmode_change(self, ringmode):
        try:
            self.IRM = self.RM = None
            print 'emitfb: loadMatrix', ringmode
            matDir = '/dls_sw/work/common/matlab/mml/machine/diamondopsdata/' + ringmode
            rm_file = os.path.join(matDir, 'GoldenCouplingEmittance.mat')
            RM_load=loadmat(rm_file)
            self.RM=RM_load['RM']
            if self.debug: print 'RM', self.RM
            self.IRM = linalg.pinv(self.RM)
            if self.debug: print 'IRM', self.IRM

        except:
            print 'emitfb ringmode_change raised unexpected exception'
            traceback.print_exc()


    def on_mode_change(self, on):
        if on:
            self.get_target()

    def get_target(self):
        self.target = copy(self.vemit_mean)
        if self.debug: print self.target


    def correct(self):
        rv = self.do_calc(True)
        if self.debug: print 'emitfb correct() done'
        return rv

    def calc(self):
        rv = self.do_calc(False)
        if self.debug: print 'emitfb calc() done'
        return rv


    def isMatrixOk(self):
        return not (self.RM == None)


    def do_calc(self, apply_calc):
        if self.debug: print 'emitfb calc() %%', self.fraction

        self.use_mean = self.use_mean_pv.get()

        if not self.isMatrixOk():
            print 'No matrix'
            raise calc_exception

        target = self.target
        if self.debug: print 'target', target

        current = self.vemit_mean if self.use_mean else self.vemit_mean

        ts = self.vemit_mean_ts if self.use_mean else self.vemit_mean_ts
        current_time = time.time()
        if self.debug: print 'current monitored + ts + time:'
        if self.debug: print current, ts, current_time

        age = current_time - ts.min()
        if self.threshold_debug or self.debug:
             print 'age', age, 'MAX', coupling_fb_constants.MAX_TS_AGE 
        
        # Timestamps ok?
        if age > coupling_fb_constants.MAX_TS_AGE:
            print 'vemit ts too old - bail out'
            return status.BAD_CALC_INPUT_TS
        
        if self.debug:
            if self.use_mean:
                print 'using mean'
                print caget(['SR-DI-EMIT-01:VEMIT_MEAN'])
                print current
            else:
                print 'using latest'
                caget(['SR-DI-EMIT-01:VEMIT'])
                print current            


        # vals ok
        if self.threshold_debug or self.debug:
             print 'vemit ', current, '  MAX ', self.vemit_max_pv.get()
        if current > self.vemit_max_pv.get():
            print 'vemit too high - bail out'
            return status.BAD_CALC_INPUT            

        if self.threshold_debug or self.debug:
             print 'vemit ', current, '  MIN ', self.vemit_min_pv.get()
        if current < self.vemit_min_pv.get():
            print 'vemit too low - bail out'
            return status.BAD_CALC_INPUT

        if self.last != None:
            last = self.last
            change = current[0] - last[0]
            if self.threshold_debug or self.debug:
                print 'current', current[0], 'last', last[0], 'change ', change
                print 'change ', change, '  MAX_CHANGE ', self.vemit_max_change_pv.get()

            if abs(change) > self.vemit_max_change_pv.get():
                print 'vemit change too big - bail out'
                return status.BAD_CALC_INPUT
                
        self.last = +current


        diff = current-target

        if self.debug: print 'IRM', self.IRM
        if self.debug: print 'diff', diff

        delta = -self.fraction*dot(self.IRM, diff)
        if self.debug: print 'delta', delta
        
        sqvals = self.skew_quads.squad_vals
        #if self.debug: print 'sqvals', sqvals             

        sq_delta = [ delta[0] for val in sqvals]

        if not self.skew_quads.current_values_ok():
            return status.BAD_PS_VAL
        
        if not self.skew_quads.delta_ok(sq_delta):
            return status.BAD_PS_OUT

        if apply_calc:
            self.skew_quads.put_delta(sq_delta)

        return status.OK

    """
    def input_ts_ok(self):

        target = self.target
        print 'target', target

        ts = self.vemit_mean_ts
        current_time = time.time()
        if self.debug: print 'current monitored + ts + time:'
        if self.debug: print current, ts, current_time

        age = current_time - ts.min()
        if self.debug: print 'age', age
        
        return age <= coupling_fb_constants.MAX_TS_AGE:
    """    


    def record(self):
        builder.SetDeviceName("SR-CS-CPLFB-01")

        self.use_mean_pv = builder.mbbOut('WHICH_VEMIT', ("CURRENT", 0), ("MEAN", 1),
                                       initial_value = 1 if self.use_mean else 0 )

        self.vemit_max_pv = builder.aOut("VEMIT_MAX",
                initial_value = coupling_fb_constants.VEMIT_MAX_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "%")        

        self.vemit_min_pv = builder.aOut("VEMIT_MIN",
                initial_value = coupling_fb_constants.VEMIT_MIN_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "%")

        self.vemit_max_change_pv = builder.aOut("VEMIT_MAX_CHANGE",
                initial_value = coupling_fb_constants.VEMIT_MAX_CHANGE_INITIAL,
                DRVH = 100.0, DRVL = 0.0, PREC = 4, EGU = "%")

        self.vemit_target_pv = builder.aOut("VEMIT_TARGET",
                initial_value = self.target[0],
                DRVH = 100.0, DRVL = 0.0, PREC = "1")


################################# SIGMAY FB ####################################################



class cplfb_sigmay(object):

    def monitor_wf(self, pvs):
        wf = zeros(len(pvs))
        ts = zeros(len(pvs))
        def on_update(value, index):
            wf[index] = value
            ts[index] = value.timestamp
        camonitor(pvs, on_update, format = FORMAT_TIME)
        return wf, ts

    def __init__(self, skew_quads):
        print 'sigmay_fb __init__'
        self.RM = None
        self.use_mean = False
        self.last = None

        self.fraction = 0.5

        self.debug = False #True
        self.threshold_debug = False #True

        self.skew_quads = skew_quads

        self.sigmay_mean, self.sigmay_mean_ts = \
            self.monitor_wf(['SR-DI-EMIT-01:P%d:SIGMAY_MEAN' % (n+1) for n in range(2)])

        self.get_target()

        self.sigmay, self.sigmay_ts = \
            self.monitor_wf(['SR-DI-EMIT-01:P%d:SIGMAY' % (n+1) for n in range(2)])

        self.record()


    def on_ringmode_change(self, ringmode):
        try:
            self.IRM = self.RM = None

            if self.debug:print 'sigmay_fb loadMatrix', ringmode
            matDir = '/dls_sw/work/common/matlab/mml/machine/diamondopsdata/' + ringmode
            rm_file = os.path.join(matDir, 'GoldenCouplingBeamsize.mat')
            RM_load=loadmat(rm_file)

            self.RM=RM_load['RM']
            if self.debug: print 'RM', self.RM

            self.IRM = linalg.pinv(self.RM)
            if self.debug: print 'IRM', self.IRM

        except:
            print 'sigmay_fb ringmode_change raised unexpected exception'
            traceback.print_exc()


    def on_mode_change(self, on):
        if on:
            self.get_target()


    def get_target(self):
        self.target = copy(self.sigmay_mean)
        if self.debug: print self.target


    def correct(self):
        rv = self.do_calc(True)        
        if self.debug: print 'sigmay_fb correct() done'
        return rv


    def calc(self):
        rv = self.do_calc(False)
        if self.debug: print 'sigmay_fb calc() done'
        return rv


    def isMatrixOk(self):
        return not (self.RM == None)


    def do_calc(self, apply_calc):
        if self.debug: print 'sigmay_fb correct() %% ', self.fraction

        self.use_mean = self.use_mean_pv.get()

        if not self.isMatrixOk():
            print 'No matrix'
            raise calc_exception

        target = self.target
        if self.debug: print 'target', target


        current = self.sigmay_mean
        ts = self.sigmay_mean_ts

        current_time = time.time()
        if self.debug: print 'current monitored + ts + time:'
        if self.debug: print current, ts, current_time

        # Timestamps ok?
        age = current_time - ts.min()
        if self.debug: print 'age', age
                
        if age > coupling_fb_constants.MAX_TS_AGE:
            print 'sigmay_mean ts too old - bail out'
            return status.BAD_CALC_INPUT_TS            


        # vals ok      
        for i in range(len(current)):
            if self.threshold_debug or self.debug:
                print 'sigmay%d ' % i , current[i], '  MAX ', self.sigmay_max_pvs[i].get()
            if current[i] > self.sigmay_max_pvs[i].get():
                print 'sigmay too high - bail out'
                return status.BAD_CALC_INPUT            

            if self.threshold_debug or self.debug:
                print 'sigmay%d ' % i , current[i], '  MIN ',self.sigmay_min_pvs[i].get()
            if current[i] < self.sigmay_min_pvs[i].get():
                print 'sigmay too low - bail out'
                return status.BAD_CALC_INPUT
        
            if self.threshold_debug or self.debug:
                print 'change %d ' %i, current[i], '  MAX_CHANGE ', self.sigmay_max_change_pvs[i].get()
            
            if self.last != None:
                last = self.last[i]
                change = +current[i] - last
                if self.threshold_debug or self.debug: print 'current', current[i], 'last', last, 'change ', change
                if abs(change) > max([smcp.get() for smcp in self.sigmay_max_change_pvs]) :
                    print 'sigmay  change too big - bail out'
                    return status.BAD_CALC_INPUT
            
                
        
        self.last = +current

        diff = current-target


        diff = current-target
        delta = -self.fraction*dot(self.IRM, diff)
    

        if not self.skew_quads.current_values_ok():
            return status.BAD_PS_VAL
        
        if not self.skew_quads.delta_ok(delta):
            return status.BAD_PS_OUT

        if apply_calc:
            self.skew_quads.put_delta(delta)

        
        return status.OK


    def record(self):
        builder.SetDeviceName("SR-CS-CPLFB-01")

        self.use_mean_pv = builder.mbbOut('WHICH_SIGMAY', ("CURRENT", 0), ("MEAN", 1),
                                       initial_value = 1 if self.use_mean else 0 )
        
        self.sigmay_max_pvs = [ builder.aOut("SIGMAY_MAX%d" % (i+1),
                initial_value = coupling_fb_constants.SIGMAY_MAX_INITIAL[i],
                DRVL = 0.0, PREC = 1, EGU = "um") for i in range(2)]

        self.sigmay_min_pvs = [ builder.aOut("SIGMAY_MIN%d" % (i+1),
                initial_value = coupling_fb_constants.SIGMAY_MIN_INITIAL[i],
                DRVL = 0.0, PREC = 1, EGU = "um") for i in range(2)]

        self.sigmay_max_change_pvs = [ builder.aOut("SIGMAY_MAX_CHANGE%d" % (i+1),
                initial_value = coupling_fb_constants.SIGMAY_MAX_CHANGE_INITIAL[i],
                DRVL = 0.0, PREC = 1, EGU = "um") for i in range(2)]
        



