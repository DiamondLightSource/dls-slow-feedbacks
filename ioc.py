"""fofb postmortem decimator"""

import sys
sys.path.append("/dls_sw/tools/python2.4/lib/python2.4"
                "/site-packages/dls.ca2-2.16-py2.4.egg")
from dls.ca2.catools import *
import time, threading, re
from numpy import *
from epics import *

device      = "TS-CS-PC-01"
recordnames = ["SETI_C", "I_C", "MIN_C", "MAX_C", "I_R", "SETI_R"]
wavenames   = ["SETI", "I", "SETI.LOPR", "SETI.HOPR"]

def update(target, args):
    if args.status != ECA_NORMAL:
        return
    target[0] = args.dbr.value[0]
    
def curry(f, arg0):
    def g(arg1):
        return f(arg0, arg1)
    return g

def entry():
    
    supplies = open("names.txt").readlines()
    supplies = [n.strip() for n in supplies if re.search("-PC-", n)]
    
    records = {}
    for r in recordnames:
        records[r] = Record("%s:%s" % (device, r))
        records[r].waveform = zeros(len(supplies))
    
    for (i, s) in enumerate(supplies):
        for (r, w) in zip(recordnames, wavenames):
            # get slice into waveform
            target = records[r].waveform[i:i+1]
            pv = "%s:%s" % (s, w)
            camonitor(pv, curry(update, target))

    # for convenience put record arrays in globals
    for r in recordnames:
        globals()[r] = records[r].waveform
    
    while True:
        # write to the CONTENTS, not the name
        I_R[:] = (I_C - MIN_C) / (MAX_C - MIN_C)
        SETI_R[:] = (SETI_C - MIN_C) / (MAX_C - MIN_C)
        for r in records.values():
            dbPutField(r.paddr, DBF_DOUBLE,
                       r.waveform.ctypes.data, len(r.waveform))
        ca_pend_event(0.2)
        
i_c = Record("%s:%s" % (device, "I_C"))
threading.Thread(target = entry).start()
