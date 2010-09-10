#!/usr/bin/env dls-python2.6

"Test Database for SOFB"

import os, sys
sys.path.append("..")
from pkg_resources import require
require('cothread==1.16')
require('iocbuilder==3.0')
require('scipy')
import builder
from softioc import *
from numpy import *
from cothread.catools import *
from cothread import Spawn, Sleep
from mml import ao
from scipy.io import loadmat

dirname = "/home/diamond/common/matlab/middlelayer/2-0/machine/diamondopsdata/SR"
bpmresp = loadmat(os.path.join(dirname, "GoldenBPMResp"))
rmx = bpmresp["Rmat"][0,0]["Data"]
rmy = bpmresp["Rmat"][1,1]["Data"]

def SetDevice(d):
    builder.SetAddressPrefix(d)
    builder.SetDeviceName(d)

SetDevice("SR-DI-EBPM-01")
NB = 170
# disable I13
bpmen = zeros(NB)
bpmen[12*7+0:12*7+2] = 1
zv = zeros(NB)
enabled = builder.WaveformIn("ENABLED", initial_value = bpmen)
sax = builder.WaveformIn("SA:X", initial_value = zeros(NB))
say = builder.WaveformIn("SA:Y", initial_value = zeros(NB))
builder.Waveform("IL:ENABLE", initial_value = zeros(NB))
builder.Waveform("CF:ATTEN", initial_value = zeros(NB))
builder.Waveform("CF:AUTOSW", initial_value = zeros(NB))

SetDevice("LI-RF-MOSC-01")
builder.aOut("FREQ_SET", initial_value = 4.99654e8)
builder.aOut("FREQ", initial_value = 4.99654e8)

SetDevice("SR21C-DI-DCCT-01")
builder.aOut("SIGNAL", initial_value = 150)
SetDevice("SR-DI-DCCT-01")
builder.aOut("SIGNAL", initial_value = 150)

SetDevice("CS-CS-MSTAT-01")
builder.aOut("FBHEART", initial_value = 0)
builder.aOut("FBSTAT", initial_value = 1)

for p in range(2):
    f = ["hcm", "vcm"][p]
    for c in ao[f].devices:
        SetDevice(c)
        builder.aIn("I", initial_value = 0)
        builder.aOut("SETI", initial_value = 0)

class server(object):
    
    def __init__(self):
        pass

    def init(self):
        Spawn(self.tick)
        
    def tick(self):
        print "starting timer"
        while True:
            Sleep(1.0)
            caput("CS-CS-MSTAT-01:FBHEART", 0)

            hcm = caget(ao["hcm"].setpoint)
            vcm = caget(ao["vcm"].setpoint)

            caput(ao["hcm"].readback, hcm)
            caput(ao["vcm"].readback, vcm)
            
            # little error to correct here...
            hcm[5*7+0] += 0.5
            hcm[1*7+3] -= 1
            hcm[22*7+4] -= 1.5
            ox = dot(rmx, hcm)
            oy = dot(rmy, vcm)
            sax.set(ox)
            say.set(oy)
            # print ox

s = server()
builder.LoadDatabase()
iocInit()
s.init()

def reset():
    cm = random.rand(170)
    caput(ao["hcm"].setpoint, cm)
    caput(ao["vcm"].setpoint, cm)

interactive_ioc(globals())
