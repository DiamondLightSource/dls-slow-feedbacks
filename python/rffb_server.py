"IOC for RF Feedback"

import os, sys

import cothread
from cothread import catools
import traceback
from softioc import builder
from iocbuilder import records
from scipy.io import loadmat
import numpy

import mml
import rffb_calc


class ringmode(object):
    ring_modes = [
        "SR", "SRI13", "SRI0913", "SRLE3ps", "SRLEm3ps",
        "SRLETHz", "SRI0913_MOGA", "SRI21"]

    def __init__(self):
        self.records()
        self.listeners = []

    def records(self):
        builder.SetDeviceName('SR-CS-RING-01')
        self.mode = builder.mbbOut("MODE", on_update = self.set_mode,
            *zip(self.ring_modes, range(len(self.ring_modes))))

    def init(self):
        self.mode.set(self.ring_modes.index("SRI0913"))

    def set_mode(self, mode):
        for l in self.listeners:
            l(self.ring_modes[mode])

    def add_listener(self, listener):
        self.listeners.append(listener)


class rffb_server(object):

    def __init__(self, mode):
        self.tick = 0
        self.power = 0
        self.rfstep = 0.1
        self.period = 10
        self.datadir = "SR"
        self.dataroot = \
            "/dls_sw/work/common/matlab/mml/machine/diamondopsdata"

        # use MML database
        self.rad_over_A = mml.ao["hcm"].hw2physics
        self.correctors = mml.ao["hcm"].readback

        self.records()

        mode.add_listener(self.set_datadir)

    def init(self):
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

        builder.SetDeviceName("SR-CS-RFFB-01")

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
