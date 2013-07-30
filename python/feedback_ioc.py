# Slow feedback IOC startup.

import os, sys
from pkg_resources import require
require('cothread==2.6')
require('scipy==0.8.0b1')
require('iocbuilder==3.23')


if sys.argv[1:]:
    # If running in testing mode log instead of executing caput.  We do this by
    # "monkey patching" catools!
    import cothread.catools
    def caput(pvs, values, **kargs):
        print 'caput', pvs, values, kargs
    cothread.catools.caput = caput


from softioc import builder, softioc
from iocbuilder import records


import rffb_server
import magnets
import sofb_server
import vefb_server

sys.path.append(os.path.join(sys.path[0], "../tunechro"))
import tcfbserver


# This import enables caput logging
from softioc import pvlog


# Create the appropriate servers.

# Used externally to select the operating ring mode, used to define appropriate
# feedback parameters internally.
mode = rffb_server.ringmode()

# Monitors magnet settings and creates aggregated waveforms.
mags = magnets.magnets_server()

# Chromaticity control server.  No idea what this does and whether it actually
# does anything at all yet.  Seems that none of the generated PVs is used.
tcfb = tcfbserver.TuneChroServer()

# Adjusts RF frequency to minimise horizontal dispersion.
rffb = rffb_server.rffb_server(mode)

# Slow orbit feedback.
sofb = sofb_server.sofb_server(mode)

# Coupling control.
cplfb = vefb_server.coupling_fb_server(mode)


# Create mirror PV for FOFB status to reduce overall load on vxWorks IOCs.
builder.SetDeviceName('SR-CS-FOFB-01')
run = records.ai('RUN', PINI = 'YES', VAL = 0,
    INP = 'SR01A-CS-FOFB-01:RUN CP MS')


# Create the identification PVs
builder.SetDeviceName('CS-DI-IOC-09')
builder.stringIn('WHOAMI', VAL = 'RF Feedback Server')
builder.stringIn('HOSTNAME', VAL = os.uname()[1])


# All records created, can now fire up the IOC.
builder.LoadDatabase()
softioc.iocInit()


# Perform post ioc init initialisation for the various components
mode.init()
mags.init()
rffb.init()
sofb.init()
cplfb.init()


softioc.interactive_ioc(globals())
