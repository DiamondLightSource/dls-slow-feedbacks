#!/bin/env dls-python2.6

import sys, os
from pkg_resources import require

require('cothread==1.16')
require('scipy')
from numpy import *
from numpy.linalg import *
from cothread.catools import *
from cothread import Spawn, Sleep, WaitForQuit
from mml import ao
from scipy.io import loadmat

class sofb(object):
    
    def __init__(self):
        self.step_limit = 5e-6
        self.threshold = 0
        self.datadir = None
        self.irm = None

    def set_enabled(self, enabled):
        if self.enabled != enabled:
            self.enabled = enabled
            self.calc_irm()
        
    def set_threshold(self, threshold):
        if self.threshold != threshold:
            self.threshold = threshold
            self.calc_irm()
    
    def set_datadir(self, datadir):
        if self.datadir != datadir:
            dirname = "/home/diamond/common/matlab/middlelayer/2-0/machine/diamondopsdata/%s" % datadir
            bpmresp = loadmat(os.path.join(dirname, "GoldenBPMResp"))
            self.rmx = bpmresp["Rmat"][0,0]["Data"]
            self.rmy = bpmresp["Rmat"][1,1]["Data"]
            self.datadir = datadir
            self.calc_irm()

    def calc_irm(self):
        if self.rmx is None:
            return
        self.irm = [None, None]
        rmx = self.rmx[ix_(ao["bpmx"].enabled, ao["hcm"].enabled)]
        rmy = self.rmy[ix_(ao["bpmy"].enabled, ao["vcm"].enabled)]
        self.irm = [pinv(rmx, self.threshold), pinv(rmy, self.threshold)]
        print self.irm[0][ix_(range(4), range(4))]

    def tick(self):
        while True:
            Sleep(1.0)
            self.correction()
    
    def correction(self):

        bpmx = caget(ao["bpmx"].readback)[ao["bpmx"].enabled]
        hcm = caget(ao["hcm"].readback[ao["hcm"].enabled])
        hdelta = dot(feedback.irm[0], bpmx)
        hdelta = hdelta * self.scale(hdelta)

        print hdelta

        bpmy = caget(ao["bpmy"].readback)[ao["bpmy"].enabled]
        vcm = caget(ao["vcm"].readback[ao["vcm"].enabled])
        vdelta = dot(feedback.irm[1], bpmy)
        vdelta = vdelta * self.scale(vdelta)

        caput(ao["hcm"].setpoint[ao["hcm"].enabled], hcm - hdelta)
        caput(ao["vcm"].setpoint[ao["vcm"].enabled], vcm - vdelta)
        
    def scale(self, xs):
        "greatest scale factor <= 1.0 such that max(abs(sf * xs)) < step_limit"
        EPS = 1e-9
        max_step = max(abs(xs))
        if max_step > EPS:
            sf = min(1.0, self.step_limit / max_step)
        else:
            sf = 1.0
        return sf
        
feedback = sofb()
feedback.set_datadir("SR")
feedback.set_threshold(0)
feedback.correction()
Spawn(feedback.tick)
WaitForQuit()

# ok very nice, just needs to be wrapped in a nice server
# need a vector for disabled corrector magnets...
# One control for each magnet? Yes really...
# need a GUI for the enabled / disabled vector
# used for sofb and fofb activation.
# put FOFB parameters in PVs...

# 1 make GUIs

