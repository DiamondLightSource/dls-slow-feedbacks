"corrector disable PVs for EDM panel and :ENABLED vector"

import builder
from numpy import *
import mml

def SetDevice(d):
    builder.SetAddressPrefix(d)
    builder.SetDeviceName(d)

def bind1st(x, f):
    def g(*args, **kw):
        f(x, *args, **kw)
    return g

class correctors(object):

    def __init__(self):
        self.create()

    def update(self, key, value):
        (k, i) = key
        r = self.cenabled[k]
        wf = r.get()
        wf[i] = value
        r.set(wf)

    def create(self):
        
        self.cenabled = [None, None]
        fams = ["hcm", "vcm"]
        records = [[], []]

        for p in range(2):
            f = fams[p]

            # build concentrator vector
            NC = len(mml.ao[f].devices)
            envec = zeros(NC)
            envec[12*7+0:12*7+2] = 1
            SetDevice("SR-PC-%sSTR-01" % "HV"[p])
            self.cenabled[p] = builder.WaveformIn("ENABLED", 
                                                  initial_value = envec)
            # build individual controls
            for n, c in enumerate(mml.ao[f].devices):
                SetDevice(c)
                r = builder.mbbOut('DISABLED', ("Enabled", 0), ("Disabled", 1),
                                   on_update = bind1st((p, n), self.update))
                records[p].append(r)
        self.records = records

    def init(self):
        # set initial control values
        for p in range(2):
            for n, r in enumerate(self.records[p]):
                r.set(self.cenabled[p].get()[n])
                
