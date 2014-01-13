#!/dls_sw/work/R3.14.11/support/pythonSoftIoc/pythonIoc
'''
Simple script to set OFFSET1.INP for each magnet used in tune feedback.

Each .INP is set to the local PV mirrored in our IOC.
'''

from pkg_resources import require
require('cothread')
require('scipy')
require('numpy')
require('iocbuilder')

from cothread.catools import caput
from tunefb_server import load_magnet_pvs, rename_pvs
import sys, os


PYDIR = os.path.dirname(os.path.realpath(__file__))
PVS_FILE = os.path.join(PYDIR, 'TunePvs.txt')

# provide an argument to enter test mode
if len(sys.argv) > 1:
    def caput(pvs, values):
        for pv, val in zip(pvs, values):
            print '%s   %s' % (pv, val)


mag_pvs = load_magnet_pvs(PVS_FILE)
local_pvs = rename_pvs(mag_pvs)

inps = [pv + ':OFFSET1.INP' for pv in mag_pvs]
links = [pv + ':I CPP MS' for pv in local_pvs]

caput(inps, links)
