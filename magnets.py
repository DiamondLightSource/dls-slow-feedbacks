#!/usr/bin/env dls-python2.6

"magnet position PVs"

if __name__ == "__main__":
    from pkg_resources import require
    require('iocbuilder==3.3')
    require('cothread==1.16')

import mml
import builder
import iochelper

class s_server(object):
    
    def __init__(self):
        nm = {"hcm": 'SR-PC-STR-01',
              "bpmx": 'SR-DI-EBPM-01'}
        for(k, v) in nm.items():
            iochelper.SetDevice(v)
            builder.WaveformOut("S", initial_value = mml.ao[k].s)
            
if __name__ == "__main__":
    # standalone test
    s = s_server()
    iochelper.start_ioc()
    


    

