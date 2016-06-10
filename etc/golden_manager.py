#!/bin/env dls-python
import dls_packages
import numpy as np
import mml
import sys
import cothread
from cothread.catools import *


device_names = mml.ao['bpmy'].devices 
suffix = ':CF:GOLDEN_Y_S'
golden_names = np.core.defchararray.add(device_names, suffix)

DELAY = 0.1
STEPS = 100


# Argument Handling
def print_usage():
    print 'Usage:', sys.argv[0],
    print 'get filepath|put filepath|remove]'
    sys.exit(-1)

if not sys.argv[1:]:
    print_usage()

if sys.argv[1] not in ['get', 'put', 'remove']:
    print_usage()

if sys.argv[1] in ['get', 'put']:
    if not sys.argv[2:]:
        print_usage()


# Functionality
if sys.argv[1] == 'get':
    with open(sys.argv[2], 'w') as file:
        golden_values = caget(golden_names)
        for value in golden_values:
            file.write(str(value) + '\n')
        print 'Downloaded values to', sys.argv[2], ':', golden_values

elif sys.argv[1] == 'put':
    golden_values = [float(x.strip()) for x in open(sys.argv[2])]
    caput(golden_names, golden_values)

elif sys.argv[1] == 'remove':
    caput(golden_names, [0.0]*len(golden_names))

    # Slow removal
    #golden_values = caget(golden_names)
    #steps = int(sys.argv[2])
    #delta = np.multiply(golden_values, -1.0/float(sys.argv[2]))
    #for step in range(steps + 1):
        #print golden_values + step*delta
        #caput(golden_names, golden_values + step*delta)
        #cothread.Sleep(0.1)

