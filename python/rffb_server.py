"IOC for RF Feedback"

import os, sys
from pkg_resources import require
require('cothread==1.17')
require('scipy==0.8.0b1')
require('iocbuilder==3.3')

import cothread
from cothread import catools
import traceback
import builder
from softioc import *
from scipy.io import loadmat
import numpy

import mml
import iochelper
import rffb_calc
import magnets
import sofb_server

class ringmode(object):

    ring_modes = ["SR", "SRI13", "SRI0913", "SRLE3ps", "SRLEm3ps"]

    def __init__(self):
        self.records()
        self.listeners = []
        iochelper.on_init.append(self.init)
        
    def records(self):
        iochelper.SetDevice('SR-CS-RING-01')
        self.mode = builder.mbbOut("MODE", on_update = self.set_mode,
                                   *(zip(self.ring_modes, range(len(self.ring_modes)))))
        self.mode = builder.mbbOut("DISABLE_16_6", ("OFF", 0), ("ON", 1))

    def init(self):
        self.mode.set(0)
        
    def set_mode(self, mode):
        for l in self.listeners:
            l(self.ring_modes[mode])

class rffb_server(object):
    
    def __init__(self):
        self.tick = 0
        self.power = 0
        self.rfstep = 0.1
        self.period = 10
        self.datadir = "SR"
        self.dataroot = "/home/diamond/common/matlab/middlelayer/2-0/machine/diamondopsdata"

        # use MML database
        self.rad_over_A = mml.ao["hcm"].hw2physics
        self.correctors = mml.ao["hcm"].readback

        self.records()

        iochelper.on_init.append(self.start)
        
    def start(self):
        cothread.Spawn(self.timer)
        
    def timer(self):
        
        while True:

            cothread.Sleep(1.0)
            self.tick = (self.tick + 1) % 10

            if self.period == 10 and self.tick != 0:
                continue
            
            try:
                self.feedback()
            except catools.ca_nothing, e:
                self.pv_error.set(e.name)
                self.calc_error.set(1)
                self.power_pv.set(0)
            except:
                traceback.print_exc()
                self.calc_error.set(1)
                self.power_pv.set(0)
                

    def feedback(self):

        # channel access read
        fbstat = catools.caget("CS-CS-MSTAT-01:FBSTAT")
        enabled_cor = catools.caget("SR-PC-HSTR-01:ENABLED") == 0
        enabled_bpm = catools.caget("SR-DI-EBPM-01:ENABLED") == 0
        current = catools.caget("SR-DI-DCCT-01:SIGNAL")

        # always turn off 16-6
        if catools.caget("SR-CS-RING-01:DISABLE_16_6") == 1:
            enabled_bpm[mml.BPM_16_6] = False
        
        hcm = numpy.array(catools.caget(self.correctors[enabled_cor]))
        rf = catools.caget("LI-RF-MOSC-01:FREQ_SET")
        
        drf = rffb_calc.calc_rffb(self.bpmresp, self.disp,
                                  enabled_bpm, enabled_cor,
                                  hcm, self.rad_over_A)
        self.delta_pv.set(drf)
        
        def round10(x):
            return round(x * 10.0) / 10.0
        
        target = round10(rf + drf)
        if abs(drf) > self.rfstep:
            drf = numpy.sign(drf) * self.rfstep
        target_limit = round10(rf + drf)

        # update status
        self.target_pv.set(target)

        # turn off feedback loop with no orbit loop
        if fbstat == 0:
            self.power_pv.set(0)
            return
        
        # turn off feedback loop below 2mA
        if current <= 2:
            self.power_pv.set(0)
            return
        
        # channel access write
        if self.power:
            catools.caput("LI-RF-MOSC-01:FREQ_SET", target_limit)
        
        self.calc_error.set(0)
        self.pv_error.set("OK")

    def set_power(self, power):
        self.power = power

    def set_rfstep(self, rfstep):
        self.rfstep = rfstep

    def set_period(self, period):
        self.period = period
    
    def set_valid(self, valid):
        self.valid = valid

    def set_datadir(self, datadir):
        rffb_calc.cache.clear()
        path = os.path.join(self.dataroot, datadir)
        try:
            self.bpmresp = loadmat(os.path.join(path, "GoldenBPMResp"))
            self.disp = loadmat(os.path.join(path, "GoldenDisp"))
            assert(self.bpmresp["Rmat"][0,0]["Units"] == "Hardware")
            assert(self.disp["BPMxDisp"]["Units"] == "Hardware")
            self.matrix_error.set(0)
            print "RFFB loaded matrix %s" % datadir
        except:
            traceback.print_exc()
            self.bpmresp = None
            self.disp = None
            self.matrix_error.set(1)
            
    def records(self):

        iochelper.SetDevice("SR-CS-RFFB-01")

        self.matrix_error = builder.boolIn(
            "EMATRIX", DESC = "Matrix Error",
            initial_value = 1, ZNAM = "OK",
            ONAM = "RFFB MATRIX")
        
        self.calc_error = builder.boolIn(
            "ECALC", DESC = "Calculation Error",
            initial_value = 0, ZNAM = "OK",
            ONAM = "RFFB CALC")

        self.pv_error = builder.stringIn(
            "EPV", DESC = "PV Error", initial_value = "OK")

        self.power_pv = builder.mbbOut('ONOFF', ("OFF", 0), ("ON", 1),
                                  initial_value = self.power,
                                  on_update = self.set_power)
        
        self.delta_pv = builder.aIn("DELTARF", initial_value = 0,
                                    PREC = 1, EGU = "Hz")
        
        self.target_pv = builder.aIn("TARGET", initial_value = 0,
                                PREC = 1, EGU = "Hz")
        
        builder.aOut("RFSTEP", initial_value = self.rfstep,
                     on_update = self.set_rfstep,
                     DRVH = 100, DRVL = 0.1, PREC = 1, EGU = "Hz")
        
        builder.mbbOut('PERIOD', ("1 second", 1), ("10 seconds", 10),
                       initial_value = self.period,
                       on_update = self.set_period)
        
class status_server(object):
    def __init__(self):
        iochelper.SetDevice('CS-DI-IOC-09')
        builder.stringIn('WHOAMI', VAL = 'RF Feedback Server')
        builder.stringIn('HOSTNAME', VAL = os.uname()[1])

def startup():

    "spawn the various servers on this IOC"
    
    status = status_server()
    rffb = rffb_server()
        
    mags = magnets.magnets_server()
    sofb = sofb_server.sofb_server()
        
    mode = ringmode()
    mode.listeners.append(rffb.set_datadir)
    mode.listeners.append(sofb.set_datadir)
    
    iochelper.start_ioc()

startup()

