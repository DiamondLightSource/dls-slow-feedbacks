"IOC for RF Feedback"

import os, sys
from pkg_resources import require
require('cothread==1.16')
require('scipy==0.8.0b1')
require('iocbuilder==3.3')

import cothread
from cothread import catools
import traceback
import builder
from softioc import *
from scipy.io import loadmat
import numpy

import rffb_calc
import correctors
import mml
import iochelper

ring_modes = ["SR", "SRI13", "SRLE3ps", "SRLEm3ps"]

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

        # use MML database
        self.rad_over_A = mml.ao["hcm"].hw2physics
        self.correctors = mml.ao["hcm"].readback

        iochelper.on_init.append(self.start)
        
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
                    self.set_message("CALC FAILED")

    def set_message(self, s):
        self.message_pv.set(s)
    
    def feedback(self):

        # copy state to local thread
        bpmresp = self.bpmresp.copy()
        disp = self.disp.copy()
        rfstep = self.rfstep

        # channel access read
        fbstat = catools.caget("CS-CS-MSTAT-01:FBSTAT")
        enabled_cor = catools.caget("SR-PC-HSTR-01:ENABLED") == 0
        enabled_bpm = catools.caget("SR-DI-EBPM-01:ENABLED") == 0
        hcm = numpy.array(catools.caget(self.correctors[enabled_cor]))
        rf = catools.caget("LI-RF-MOSC-01:FREQ_SET")
        
        if fbstat == 0:
            self.set_message("ORBIT FB")
            self.power_pv.set(0)
            return
        
        drf = rffb_calc.calc_rffb(self.bpmresp, self.disp,
                                  enabled_bpm, enabled_cor,
                                  hcm, self.rad_over_A)
        self.delta_pv.set(drf)
        
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
        self.set_message("NO ERRORS")

    def set_mode(self, mode):
        self.set_datadir(ring_modes[mode])
        
    def set_power(self, power):
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

    def set_target(self, target):
        self.target = target
        self.target_pv.set(target)

    def set_datadir(self, datadir):
        self.power_pv.set(0)
        self.datadir = datadir
        path = os.path.join(self.dataroot, self.datadir)
        self.set_valid(0)
        rffb_calc.cache.clear()
        try:
            self.bpmresp = loadmat(os.path.join(path, "GoldenBPMResp"))
            self.disp = loadmat(os.path.join(path, "GoldenDisp"))
            assert(self.bpmresp["Rmat"][0,0]["Units"] == "Hardware")
            assert(self.disp["BPMxDisp"]["Units"] == "Hardware")
            self.set_valid(1)
            self.set_message("MATRIX OK")
        except:
            traceback.print_exc()
            self.set_message("MATRIX BAD")
            
    # PV connection
    def set_target_pv(self, target_pv):
        self.target_pv = target_pv

    def set_power_pv(self, power_pv):
        self.power_pv = power_pv

    def set_delta_pv(self, delta_pv):
        self.delta_pv = delta_pv

    def set_message_pv(self, message_pv):
        self.message_pv = message_pv

class rffb_database(object):
    
    def __init__(self):

        rffb = rffb_service()

        iochelper.SetDevice('CS-DI-IOC-09')
        
        builder.stringIn('WHOAMI', VAL = 'RF Feedback Server')
        builder.stringIn('HOSTNAME', VAL = os.uname()[1])

        iochelper.SetDevice('SR-CS-RFFB-01')
        
        power_pv = builder.mbbOut('ONOFF', ("OFF", 0), ("ON", 1),
                                  initial_value = rffb.power,
                                  on_update = rffb.set_power)
        
        builder.aOut("RFSTEP", initial_value = rffb.rfstep,
                     on_update = rffb.set_rfstep,
                     DRVH = 100, DRVL = 0.1, PREC = 1, EGU = "Hz")
        
        builder.aOut("PERIOD", initial_value = rffb.period,
                     on_update = rffb.set_period,
                     DRVH = 100, DRVL = 0.1, PREC = 1, EGU = "s")

        delta_pv = builder.aIn("DELTARF")

        message_pv = builder.stringIn("MESSAGE")
                
        target_pv = builder.aIn("TARGET", initial_value = rffb.target, PREC = 1, EGU = "Hz")
        
        rffb.set_target_pv(target_pv)
        rffb.set_power_pv(power_pv)
        rffb.set_delta_pv(delta_pv)
        rffb.set_message_pv(message_pv)
        
        iochelper.SetDevice('SR-CS-RING-01')

        mode = builder.mbbOut("MODE", on_update = rffb.set_mode,
                              *(zip(ring_modes, range(len(ring_modes)))))

        cor = correctors.correctors()

        iochelper.on_init.append(lambda : mode.set(0))
        iochelper.start_ioc()
        
mydb = rffb_database()

