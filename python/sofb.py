#!/bin/env dls-python2.6

import sys, os, traceback

if __name__ == "__main__":
    from pkg_resources import require
    require('cothread==1.16')
    require('scipy')
    
from numpy import *
from numpy.linalg import *
from cothread.catools import *
from cothread import Spawn, Sleep, WaitForQuit
from mml import ao

class sofb(object):
    
    def __init__(self):
        self.step_limit = 0.05
        self.threshold = 0
        self.cache = {}

    def set_step_limit(self, step_limit):
        self.step_limit = step_limit
    
    def set_threshold(self, threshold):
        self.threshold = threshold
    
    def get_irm(self, hen, ven, bpmen, threshold):
        key = (tuple(hen), tuple(ven), tuple(bpmen), threshold)
        if key in self.cache:
            return self.cache[key]
        print "new response matrix"
        irm = [None, None]
        rmx = self.rmx[ix_(bpmen, hen)]
        rmy = self.rmy[ix_(bpmen, ven)]
        irm = [pinv(rmx, threshold),
               pinv(rmy, threshold)]
        self.cache.clear()
        self.cache[key] = irm
        return irm
        
    def tick(self):
        while True:
            Sleep(1.0)
            try:
                self.correction()
            except:
                traceback.print_exc()
    
    def correction(self):

        # calculate inverse response matrix on demand

        hen = caget("SR-PC-HSTR-01:ENABLED") == 0
        ven = caget("SR-PC-VSTR-01:ENABLED") == 0
        bpmen = caget("SR-DI-EBPM-01:ENABLED") == 0

        irm = self.get_irm(hen, ven, bpmen, self.threshold)
        
        bpmx = caget(ao["bpmx"].readback)[bpmen]
        hcm = caget(ao["hcm"].readback[hen])
        
        bpmy = caget(ao["bpmy"].readback)[bpmen]
        vcm = caget(ao["vcm"].readback[ven])

        hdelta = dot(irm[0], bpmx)
        hdelta = hdelta * self.scale(hdelta)

        vdelta = dot(irm[1], bpmy)
        vdelta = vdelta * self.scale(vdelta)
        
        caput(ao["hcm"].setpoint[hen], hcm - hdelta)
        caput(ao["vcm"].setpoint[ven], vcm - vdelta)
        caput("CS-CS-MSTAT-01:FBHEART", 10)
        
    def scale(self, xs):
        "greatest scale factor <= 1.0 such that max(abs(sf * xs)) < step_limit"
        EPS = 1e-9
        max_step = max(abs(xs))
        if max_step > EPS:
            sf = min(1.0, self.step_limit / max_step)
        else:
            sf = 1.0
        return sf

if __name__ == "__main__":

    # need some PVs for activities:
    
    # 1) threshold
    # 2) limit
    # 3) power
    # 4) single correction
    
    feedback = sofb()
    feedback.set_datadir("SR")
    feedback.correction()
    Spawn(feedback.tick)
    WaitForQuit()
