#!/usr/bin/env dls-python2.6

"magnet position PVs"

if __name__ == "__main__":
    from pkg_resources import require
    require('iocbuilder==3.3')
    require('cothread==1.16')

import traceback
import mml
import builder
import iochelper
import cothread
from cothread.catools import caget
from numpy import *

class s_server(object):
    
    def __init__(self):

        self.wf = [None, None]
        
        iochelper.SetDevice("SR-DI-EBPM-01")
        builder.WaveformOut("S", initial_value = mml.ao["bpmx"].s)
        
        nm = (("hcm", 'SR-PC-HSTR-01'),
              ("vcm", 'SR-PC-VSTR-01'))
        
        for i, (k, v) in enumerate(nm):
            iochelper.SetDevice(v)
            w = builder.WaveformOut("I", initial_value = zeros(len(mml.ao[k].s)))
            builder.WaveformOut("S", initial_value = mml.ao[k].s)
            self.wf[i] = w
        
        iochelper.on_init.append(self.init)

    def init(self):
        cothread.Spawn(self.timer)

    def timer(self):
        while True:
            try:
                cothread.Sleep(1.0)
                self.calc()
            except:
                traceback.print_exc()
            
    def calc(self):
        
        en = array([True] * 170)
        
        hv = [None, None]
        fam = ["hcm", "vcm"]

        # get readbacks
        for p in range(2):
            hv[p] = caget(mml.ao[fam[p]].readback[en])

        # write to waveforms
        for p in range(2):
            w = self.wf[p].get()
            w[en] = hv[p]
            w[en == False] = 0
            self.wf[p].set(w)
            
if __name__ == "__main__":
    # standalone test
    s = s_server()
    iochelper.start_ioc()


