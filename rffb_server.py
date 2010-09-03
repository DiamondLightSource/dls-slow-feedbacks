"IOC for RF Feedback"

import os, sys
from pkg_resources import require
require('cothread==1.16')
require('scipy==0.8.0b1')
require('iocbuilder==3.0')

import cothread
from cothread import catools
import traceback
import builder
from softioc import *
from scipy.io import loadmat
import numpy

import rffb_calc

class rffb_service(object):
    
    def __init__(self):
        self.event = cothread.Event()

        self.valid = 0
        self.power = 0
        self.rfstep = 0.1
        self.period = 1
        self.target = 0
        self.datadir = "SR"
        self.dataroot = "/home/diamond/common/matlab/middlelayer/2-0/machine/diamondopsdata"
        
        # [rad A^-1] values from middlelayer
        rad_over_A = [
            0.219088331921733,
            0.219088331921733,
            0.163286961340012,
            0.219088331921733,
            0.161008538618683,
            0.219088331921733,
            0.219088331921733] * 24

        # add 13S correctors
        self.rad_over_A = numpy.array(rad_over_A[:12*7] + [1, 1] + rad_over_A[12*7:]) * 1e-3

        correctors = ["SR%02dA-PC-HSTR-%02d:I" % (c + 1, i + 1)
                           for c in range(24) for i in range(7)]

        cell13 = ["SR13S-PC-HSTR-01:I", "SR13S-PC-HSTR-02:I"]
        self.correctors = numpy.array(correctors[:7*12] + cell13 + correctors[7*12:])
        
    def start(self):
        cothread.Spawn(self.timer)
        
    def timer(self):
        while True:
            # event is signalled if the period is changed
            # so we don't have to wait for the next cycle
            try:
                self.event.Wait(timeout = self.period)
                continue
            except cothread.Timedout:
                pass

            if self.power and self.valid:
                try:
                    self.feedback()
                except:
                    traceback.print_exc()
                    self.set_message("ERROR IN CALCULATION")

    def set_message(self, s):
        self.message_pv.set(s)
    
    def feedback(self):

        # copy state to local thread
        bpmresp = self.bpmresp.copy()
        disp = self.disp.copy()
        rfstep = self.rfstep

        # for testing ignore 13S
        enabled_cor = range(170)
        enabled_cor.remove(7*12+0)
        enabled_cor.remove(7*12+1)

        # channel access read
        fbstat = catools.caget("CS-CS-MSTAT-01:FBSTAT")
        enabled_bpm = numpy.nonzero(catools.caget("SR-DI-EBPM-01:ENABLED") == 0)[0]
        hcm = numpy.array(catools.caget(self.correctors[enabled_cor]))
        rf = catools.caget("LI-RF-MOSC-01:FREQ_SET")

        if fbstat == 0:
            self.set_message("NO ORBIT FEEDBACK")
            self.power_pv.set(0)
            return
        
        drf = rffb_calc.calc_rffb(self.bpmresp, self.disp,
                                  enabled_bpm, enabled_cor,
                                  hcm, self.rad_over_A)
        print "delta RF", drf
        def round10(x):
            return round(x * 10.0) / 10.0
        
        target = round10(rf + drf)
        if abs(drf) > rfstep:
            drf = numpy.sign(drf) * rfstep
        target_limit = round10(rf + drf)

        # channel access write
        catools.caput("LI-RF-MOSC-01:FREQ_SET", target_limit)
        
        # update status
        self.set_target(target)
        self.set_message("RUNNING")
        
    def set_power(self, power):
        print "set power", power, self.valid
        self.power = power
        self.event.Signal()
        if power and not self.valid:
            self.power_pv.set(0)

    def set_rfstep(self, rfstep):
        self.rfstep = rfstep
        self.power_pv.set(0)

    def set_period(self, period):
        self.period = period
        self.power_pv.set(0)
    
    def set_valid(self, valid):
        self.valid = valid
        self.valid_pv.set(valid)

    def set_target(self, target):
        self.target = target
        self.target_pv.set(target)

    def set_datadir(self, datadir):
        self.power_pv.set(0)
        self.datadir = datadir
        path = os.path.join(self.dataroot, self.datadir)
        print "path", path
        self.set_valid(0)
        rffb_calc.cache.clear()
        try:
            self.bpmresp = loadmat(os.path.join(path, "GoldenBPMResp"))
            self.disp = loadmat(os.path.join(path, "GoldenDisp"))
            assert(self.bpmresp["Rmat"][0,0]["Units"] == "Hardware")
            assert(self.disp["BPMxDisp"]["Units"] == "Hardware")
            self.set_valid(1)
            self.set_message("LOADED RESPONSE MATRIX")
        except:
            traceback.print_exc()
            self.set_message("BAD RESPONSE MATRIX")
            
    # PV connection
    def set_target_pv(self, target_pv):
        self.target_pv = target_pv

    def set_power_pv(self, power_pv):
        self.power_pv = power_pv

    def set_valid_pv(self, valid_pv):
        self.valid_pv = valid_pv

    def set_message_pv(self, message_pv):
        self.message_pv = message_pv

        
class rffb_database(object):
    
    def __init__(self):

        rffb = rffb_service()

        builder.SetDeviceName('CS-DI-IOC-09')
        
        builder.stringIn('WHOAMI', VAL = 'RF Feedback Server')
        builder.stringIn('HOSTNAME', VAL = os.uname()[1])

        builder.SetDeviceName('SR-CS-RFFB-01')
        
        power_pv = builder.mbbOut('ONOFF', ("OFF", 0), ("ON", 1),
                                  RVAL = rffb.power,
                                  on_update = rffb.set_power)
        
        builder.aOut("RFSTEP", VAL = rffb.rfstep,
                     on_update = rffb.set_rfstep,
                     DRVH = 100, DRVL = 0.1, PREC = 1, EGU = "Hz")
        
        builder.aOut("PERIOD", VAL = rffb.period,
                     on_update = rffb.set_period,
                     DRVH = 100, DRVL = 0.1, PREC = 1, EGU = "s")

        valid_pv = builder.mbbIn("MATRIX", ("INVALID", 0), ("VALID", 1),
                                 RVAL = rffb.valid)

        builder.stringOut("DATADIR", VAL = rffb.datadir, on_update = rffb.set_datadir)
        message_pv = builder.stringIn("MESSAGE")
                
        target_pv = builder.aIn("TARGET", VAL = rffb.target, PREC = 1, EGU = "Hz")
        
        rffb.set_target_pv(target_pv)
        rffb.set_power_pv(power_pv)
        rffb.set_valid_pv(valid_pv)
        rffb.set_message_pv(message_pv)
        
        builder.SetDeviceName('SR-CS-RING-01')
        builder.mbbIn("MODE", ("SR", 0), ("MINIBETA", 1), ("LOWALPHA", 2), RVAL = 0)
        
        builder.LoadDatabase()
        
        iocInit()
        rffb.start()
        
        interactive_ioc(globals())
        
mydb = rffb_database()

# now add new BPMs (what are the locations and names? check mml)

# SR13S-DI-EBPM-01
# SR13S-DI-EBPM-02

# so the HCM have nice names too? fine.

