"common startup routines for python ioc"

from softioc import builder
from softioc import softioc

def SetDevice(d):
    builder.SetDeviceName(d)

on_init = []

def start_ioc():
    builder.LoadDatabase()
    softioc.iocInit()
    for o in on_init:
        o()
    del on_init[:]
    softioc.interactive_ioc(globals())
