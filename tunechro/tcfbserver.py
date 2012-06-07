#!/usr/bin/env dls-python2.6

import os, sys, mml2

if __name__ == "__main__":

    from pkg_resources import require
    require('cothread==2.8')
    require('scipy==0.8.0b1')
    require('iocbuilder==3.23')

from cothread import catools
from softioc import builder, softioc

def fakecaput(xs, ys):
    for (x, y) in zip(xs, ys):
        print "%s %.6f" % (x, y)

class TuneChroServer(object):
    def __init__(self):
        
        builder.SetDomain("SR")
        builder.SetTechnicalArea("CS")
        builder.SetDevice("TCFB", 1)

        mml = mml2.Middlelayer()

        tunefb = mml2.Correction(mml, "GoldenTuneResp.mat")
        chrofb = mml2.Correction(mml, "GoldenChroResp.mat")

        PREC = 4

        goalh = builder.aOut("GOALH", initial_value = 0,
                             on_update = tunefb.SetGoalH, always_update = True, PREC = PREC)

        goalv = builder.aOut("GOALV", initial_value = 0,
                             on_update = tunefb.SetGoalV, always_update = True, PREC = PREC)

        tunelimit = builder.aIn("TUNELIMIT", PREC = PREC, HIGH = 0.999, HSV = "MINOR", PINI = "YES", EGU = "A")
        tuneh = builder.aIn("TUNEH", PREC = PREC)
        tunev = builder.aIn("TUNEV", PREC = PREC)

        tunestep = builder.aOut("TUNESTEP", initial_value = 0.001, PREC = PREC,
                                on_update = tunefb.SetDelta, always_update = True, PINI = "YES")
        tunehup   = builder.aOut("TUNEHUP",   on_update = tunefb.StepHUp,   always_update = True)
        tunehdown = builder.aOut("TUNEHDOWN", on_update = tunefb.StepHDown, always_update = True)
        tunevup   = builder.aOut("TUNEVUP",   on_update = tunefb.StepVUp,   always_update = True)
        tunevdown = builder.aOut("TUNEVDOWN", on_update = tunefb.StepVDown, always_update = True)
        settune   = builder.aOut("SETTUNE",   on_update = tunefb.Correct,   always_update = True)
        
        # Chromaticity Control
        
        chrolimit = builder.aIn("CHROLIMIT", PREC = PREC, HIGH = 0.999, HSV = "MINOR", PINI = "YES", EGU = "A")
        chrostep  = builder.aOut("CHROSTEP", initial_value = 0.1, PREC = PREC, 
                                 on_update = chrofb.SetDelta, always_update = True, PINI = "YES")
        chrohup   = builder.aOut("CHROHUP",   on_update = chrofb.StepHUp,   always_update = True)
        chrohdown = builder.aOut("CHROHDOWN", on_update = chrofb.StepHDown, always_update = True)
        chrovup   = builder.aOut("CHROVUP",   on_update = chrofb.StepVUp,   always_update = True)
        chrovdown = builder.aOut("CHROVDOWN", on_update = chrofb.StepVDown, always_update = True)
        
        fanout = mml2.Signal()
        
        source = builder.mbbOut("TUNESOURCE", ("CUMSUM", 0), ("TUNE", 1),
                                on_update = fanout.fire, always_update = True)
        
        mh = mml2.Mux(2)
        mv = mml2.Mux(2)
        
        # -- WIRING --
        
        fanout.connect(mh.SetSelector)
        fanout.connect(mv.SetSelector)
        
        tunefb.LimitedChanged.connect(tunelimit.set)
        tunefb.GoalHChanged.connect(goalh.set)
        tunefb.GoalVChanged.connect(goalv.set)
        tunefb.Output.connect(catools.caput)
        
        ModeFanout = mml2.Signal()
        ModeFanout.connect(tunefb.SetMode)
        
        ModeFanout.connect(chrofb.SetMode)
        chrofb.Output.connect(catools.caput)
        chrofb.LimitedChanged.connect(chrolimit.set)
        
        catools.camonitor("SR-CS-RING-01:MODE", ModeFanout.fire, datatype = catools.DBR_STRING)
        catools.camonitor("SR21C-DI-TMBF-01:TUNE", lambda x: mh.SetInput(0, x))
        catools.camonitor("SR21C-DI-TMBF-02:TUNE", lambda x: mv.SetInput(0, x))
        catools.camonitor("SR21C-DI-TMBF-01:CUMSUMTUNE", lambda x: mh.SetInput(1, x))
        catools.camonitor("SR21C-DI-TMBF-02:CUMSUMTUNE", lambda x: mv.SetInput(1, x))
        
        mh.Output.connect(tunefb.SetTuneH)
        mv.Output.connect(tunefb.SetTuneV)
        
        mh.Output.connect(tuneh.set)
        mv.Output.connect(tunev.set)

if __name__ == "__main__":

    server = TuneChroServer()
    

    builder.LoadDatabase()
    softioc.iocInit()
    softioc.interactive_ioc(globals())
