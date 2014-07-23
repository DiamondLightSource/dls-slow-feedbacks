#!/dls_sw/work/R3.14.12.3/support/pythonSoftIoc/pythonIoc
'''
Simple script to set OFFSET1.INP for each magnet used in tune feedback.

Each .INP is set to the local PV mirrored in our IOC.
'''

from pkg_resources import require
require('cothread')
import cothread
from cothread.catools import caget, caput
import sys
import os

# Constants
BEAM_DAMP_TIME = 0.001
IOC = 'SR-CS-TFB-01'
CURRENT_LINK = ':I CPP MS'
OFFSET_INPUT = ':OFFSET1.INP'
LOCAL_LINK =':LOFFSET1 CPP MS'


def load_magnet_pvs(txt_file):
    '''
    Load corrector magnet PVs from the specific format
    in the file.
    '''
    mag_pvs = []
    with open(txt_file) as f:
        for line in f:
            mag_pvs.append(line.strip())
    return mag_pvs


def rename_pvs(pvs):
    '''Rename quadrople pv names for use as local pvs.'''
    new_pvs = []
    for pv in pvs:
        parts = pv.split('-')
        cell = parts[0][2:4]
        new_pv = IOC + ':' + cell + parts[2] + parts[3]
        new_pvs.append(new_pv)
    return new_pvs

def all_forwarded(local_pvs, mag_pvs):
    inps = caget([pv + OFFSET_INPUT for pv in mag_pvs], timeout=1.)
    expected = [pv + CURRENT_LINK for pv in local_pvs]
    return inps == expected


if __name__ == "__main__":
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
        links = [pv + CURRENT_LINK for pv in local_pvs]
    elif 'reset' in sys.argv:
        # set INP to the remote PVs
        links = [pv + LOCAL_LINK for pv in mag_pvs]
    elif 'forwarded' in sys.argv:
        print all_forwarded(local_pvs, mag_pvs)
        sys.exit()
    else:
        print 'usage: '
        print '    %s redirect|reset [test]' % sys.argv[0]
        sys.exit()

    inps = [pv + ':OFFSET1.INP' for pv in mag_pvs]
    for inp, link in zip(inps, links):
        caput(inp, link)
        cothread.Sleep(BEAM_DAMP_TIME * 10.)
