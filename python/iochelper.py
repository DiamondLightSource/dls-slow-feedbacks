"common startup routines for python ioc"

import builder
from softioc import *

def SetDevice(d):
    builder.SetAddressPrefix(d)
    builder.SetDeviceName(d)

on_init = []

def start_ioc():
    builder.LoadDatabase()
    iocInit()
    for o in on_init:
        o()
    del on_init[:]
    interactive_ioc(globals())

BPM_16_6 = 112
