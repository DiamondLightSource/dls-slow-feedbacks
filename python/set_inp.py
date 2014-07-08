#!/dls_sw/work/R3.14.12.3/support/pythonSoftIoc/pythonIoc
'''
Simple script to set OFFSET1.INP for each magnet used in tune feedback.

Each .INP is set to the local PV mirrored in our IOC.
'''

# unfortunately, need these imports so that we can load a function from
# tunefb_server
from pkg_resources import require
require('cothread')
require('scipy')
require('numpy')
require('iocbuilder')

import cothread
from cothread.catools import caput
from tunefb_server import load_magnet_pvs, rename_pvs, BEAM_DAMP_TIME
import sys, os

# load file from same directory as the script
PYDIR = os.path.dirname(os.path.realpath(__file__))
PVS_FILE = os.path.join(PYDIR, 'TunePvs.txt')

mag_pvs = load_magnet_pvs(PVS_FILE)
local_pvs = rename_pvs(mag_pvs)

if 'test' in sys.argv:
    def caput(pv, value):
        print '%s   %s' % (pv, value)
if 'redirect' in sys.argv:
    # set INP to our PVs
    links = [pv + ':I CPP MS' for pv in local_pvs]
elif 'reset' in sys.argv:
    # set INP to the remote PVs
    links = [pv + ':LOFFSET1 CPP MS' for pv in mag_pvs]
else:
    print 'usage: '
    print '    %s redirect|reset [test]' % sys.argv[0]
    sys.exit()

inps = [pv + ':OFFSET1.INP' for pv in mag_pvs]

for inp, link in zip(inps, links):
    caput(inp, link)
    cothread.Sleep(BEAM_DAMP_TIME * 10.)
