"common startup routines for python ioc"

from softioc import builder
from softioc.softioc import *

def SetDevice(d):
    builder.SetDeviceName(d)

on_init = []

def start_ioc():
    builder.LoadDatabase()
    iocInit()
    for o in on_init:
        o()
    del on_init[:]
    interactive_ioc(globals())
