#!/usr/bin/env dls-python2.6

import os, sys, mml2

from pkg_resources import require
require('cothread==2.8')
require('scipy==0.8.0b1')
require('iocbuilder==3.23')

from cothread import catools
from softioc import builder, softioc

def fakecaput(xs, ys):
    for (x, y) in zip(xs, ys):
        print "%s %.6f" % (x, y)

builder.SetDomain("CS")
builder.SetTechnicalArea("DI")
builder.SetDevice("HELLO", 1)

mml = mml2.Middlelayer()

c = mml2.Correction(mml, "GoldenTuneResp.mat")

builder.aOut("CORRECT", initial_value = 0,
             on_update = c.Correct, always_update = True)

builder.aOut("DELTAH", initial_value = 1e-3,
             on_update = c.SetDeltaH, always_update = True)

builder.aOut("DELTAV", initial_value = 1e-3,
             on_update = c.SetDeltaV, always_update = True)

goalh = builder.aOut("GOALH", initial_value = 0,
                     on_update = c.SetGoalH, always_update = True)

goalv = builder.aOut("GOALV", initial_value = 0,
                     on_update = c.SetGoalV, always_update = True)

# -- WIRING --

c.GoalHChanged.connect(goalh.set)
c.GoalVChanged.connect(goalv.set)
c.Output.connect(fakecaput)

# catools.camonitor(c.matrix.actuators, c.SetActuators)

catools.camonitor("SR-CS-RING-01:MODE", c.SetMode, datatype = catools.DBR_STRING)
catools.camonitor("SR21C-DI-TMBF-01:CUMSUMTUNE", c.SetTuneH)
catools.camonitor("SR21C-DI-TMBF-02:CUMSUMTUNE", c.SetTuneV)

# -- END WIRING --

builder.LoadDatabase()
softioc.iocInit()
softioc.interactive_ioc(globals())
