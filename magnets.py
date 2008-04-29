"""
psu concentrator IOC

"""

import time, threading, epics, re
from numpy import *
from ctypes import byref

waveforms = ["SETI_C", "I_C", "MIN_C", "MAX_C"]

class Record(object):
    def __init__(self, name, length):
        addr = epics.dbAddr()
        assert(epics.dbNameToAddr(name, byref(addr)) == 0)
        self.name = name
        self.addr = addr
        self.data = zeros(length)
    
class Supply(object):
    def __init__(self, name, index):
        self.name = name
        self.fields = {}
        self.index = index
        for f in waveforms:
            record = Record("%s:%s" % (name, f), 1)
            self.fields[f] = record
        
def entry():
    
    names = open("names.txt").readlines()
    names = [n.strip() for n in names if re.search("-PC-", n)]
    
    supplies = []
    for i, n in enumerate(names):
        supplies.append(Supply(n, i))

    device = "SR-CS-PC-01"
    records = {}
    for n in waveforms + ["I_R", "SETI_R"]:
        records[n] = Record("%s:%s" % (device, n), len(supplies))
    
    # optimization
    DBF_DOUBLE = epics.DBF_DOUBLE
    dbGetField = epics.dbGetField
    
    gets = []
    for s in supplies:
        for k, v in s.fields.items():
            dp = records[k].data[s.index:s.index+1].ctypes.data
            gets.append((byref(v.addr), dp))
    
    minc = records["MIN_C"].data
    maxc = records["MAX_C"].data
    seti = records["SETI_C"].data
    ic = records["I_C"].data
    
    while True:
        
        for (record, buf) in gets:
            dbGetField(record, DBF_DOUBLE, buf, 0, 0, 0)
            
        records["I_R"].data = (ic - minc) / (maxc - minc)
        records["SETI_R"].data = (seti - minc) / (maxc - minc)
        
        for r in records.values():
            epics.dbPutField(byref(r.addr), DBF_DOUBLE,
                             r.data.ctypes.data, len(r.data))
        time.sleep(0.2)
        
threading.Thread(target = entry).start()
