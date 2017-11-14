# Slow feedback IOC startup.

import os, sys
from pkg_resources import require
require('cothread==2.10')
require('scipy==0.19.1')
require('pytac==0.1')
require('epicsdbbuilder==1.0')


if sys.argv[1:]:
    # If running in testing mode log instead of executing caput.  We do this by
    # "monkey patching" catools!
    import cothread.catools
    def caput(pvs, values, **kargs):
        print 'caput', pvs, values, kargs
    cothread.catools.caput = caput


from softioc import builder, softioc
from epicsdbbuilder import records

import mode
import rffb_server
import waveforms
import sofb_server
import vefb_server
import tunefb_server


# This import enables caput logging
from softioc import pvlog


# Create the appropriate servers.

# Used externally to select the operating ring mode, used to define appropriate
# feedback parameters internally.
ring_mode = mode.RingMode()

# Monitors magnet settings and creates aggregated waveforms.
wavs = waveforms.WaveformsServer(ring_mode)

# Adjusts RF frequency to minimise horizontal dispersion.
rffb = rffb_server.RffbServer(ring_mode)

# Slow orbit feedback.
sofb = sofb_server.SofbServer(ring_mode)

# Vertical emittance feedback.
vefb = vefb_server.VefbServer(ring_mode)

# Tune feedback.
tunefb = tunefb_server.TunefbServer(ring_mode)


# Create mirror PV for FOFB status to reduce overall load on vxWorks IOCs.
builder.SetDeviceName('SR-CS-FOFB-01')
run = records.ai('RUN', PINI = 'YES', VAL = 0,
    INP = 'SR01A-CS-FOFB-01:RUN CP MS')


# Create the identification PVs
builder.SetDeviceName('CS-DI-IOC-09')
builder.stringIn('WHOAMI', VAL = 'Machine Feedback Services')
builder.stringIn('HOSTNAME', VAL = os.uname()[1])


# All records created, can now fire up the IOC.
builder.LoadDatabase()
softioc.iocInit()


# Perform post ioc init initialisation for the various components
ring_mode.init()
wavs.init()
rffb.init()
sofb.init()
vefb.init()
tunefb.init()

softioc.interactive_ioc(globals())
