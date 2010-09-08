#!/usr/bin/env dls-python2.6

"Test Database for SOFB"

import os
from pkg_resources import require
require('cothread==1.16')
require('iocbuilder==3.0')
require('scipy')
import builder
from softioc import *
from numpy import *
from cothread.catools import *
from cothread import Spawn, Sleep
from mml import ao, getrb
from scipy.io import loadmat

dirname = "/home/diamond/common/matlab/middlelayer/2-0/machine/diamondopsdata/SR"
bpmresp = loadmat(os.path.join(dirname, "GoldenBPMResp"))
rmx = bpmresp["Rmat"][0,0]["Data"]
rmy = bpmresp["Rmat"][1,1]["Data"]

def SetDevice(d):
    builder.SetAddressPrefix(d)
    builder.SetDeviceName(d)

SetDevice("SR-DI-EBPM-01")
enabled = builder.WaveformIn("ENABLED", length = 170)
sax = builder.WaveformIn("SA:X", length = 170)
say = builder.WaveformIn("SA:Y", length = 170)
builder.Waveform("IL:ENABLE", length = 170)
builder.Waveform("CF:ATTEN", length = 170)
builder.Waveform("CF:AUTOSW", length = 170)

to_set = []

for c in ao["hcm"].devices:
    SetDevice(c)
    to_set.append(builder.aIn("I"))
    builder.aOut("SETI")
    builder.mbbOut('ENABLED', ("Disabled", 0), ("Enabled", 1), RVAL = 1, PINI = "YES")

for c in ao["vcm"].devices:
    SetDevice(c)
    to_set.append(builder.aIn("I"))
    builder.aOut("SETI")
    builder.mbbOut('ENABLED', ("Disabled", 0), ("Enabled", 1), RVAL = 1, PINI = "YES")

SetDevice("LI-RF-MOSC-01")
builder.aOut("FREQ_SET")
SetDevice("SR21C-DI-DCCT-01")
builder.aOut("SIGNAL")
SetDevice("CS-CS-MSTAT-01")
builder.aOut("FBHEART")
builder.aOut("FBSTAT")

class server(object):
    
    def __init__(self):
        Spawn(self.tick)
        
    def tick(self):
        while True:
            Sleep(1.0)
            caput("CS-CS-MSTAT-01:FBHEART", 0)

            hcm = caget(ao["hcm"].setpoint)
            vcm = caget(ao["vcm"].setpoint)

            caput(ao["hcm"].readback, hcm)
            caput(ao["vcm"].setpoint, vcm)
            
            # little error to correct here...
            hcm[5*7+0] += 1e-4
            hcm[1*7+3] -= 2e-4
            ox = dot(rmx, hcm)
            oy = dot(rmy, vcm)
            sax.set(ox)
            say.set(oy)
            # print ox

s = server()

builder.LoadDatabase()
iocInit()
enabled.set([0] * 170)
caput(ao["hcm"].setpoint, 0)
caput(ao["vcm"].setpoint, 0)

for t in to_set:
    t.set(0)

interactive_ioc(globals())
