#!/dls_sw/work/R3.14.11/support/pythonSoftIoc/pythonIoc
# Slow feedback IOC startup.

import os, sys
from pkg_resources import require
require('cothread==2.6')
require('scipy==0.8.0b1')
require('iocbuilder==3.23')


if sys.argv[1:]:
    # If running in testing mode log instead of executing caput.  We do this by
    # "monkey patching" catools!
    print "Running in test mode."
    import cothread.catools
    def caput(pvs, values, **kargs):
        print 'caput', pvs, values, kargs
    cothread.catools.caput = caput


from softioc import builder, softioc
from iocbuilder import records


import rffb_server
import tunefb_server
# import magnets
# import sofb_server
# import vefb_server

# This import enables caput logging
from softioc import pvlog

# Create the appropriate servers.

# Used externally to select the operating ring mode, used to define appropriate
# feedback parameters internally.
mode = rffb_server.ringmode()

# Monitors magnet settings and creates aggregated waveforms.
# mags = magnets.magnets_server()

# Chromaticity control server.  No idea what this does and whether it actually
# does anything at all yet.  Seems that none of the generated PVs is used.
# tcfb = tcfbserver.TuneChroServer()

# Adjusts RF frequency to minimise horizontal dispersion.
# rffb = rffb_server.rffb_server(mode)

# Slow orbit feedback.
# sofb = sofb_server.sofb_server(mode)

# Vertical emittance feedback.
# vefb = vefb_server.vefb_server(mode)

tunefb = tunefb_server.tunefb_server(mode)

# Create mirror PV for FOFB status to reduce overall load on vxWorks IOCs.
# builder.SetDeviceName('SR-CS-FOFB-01')
# run = records.ai('RUN', PINI = 'YES', VAL = 0,
    # INP = 'SR01A-CS-FOFB-01:RUN CP MS')


# Create the identification PVs
# builder.SetDeviceName('CS-DI-IOC-09')
# builder.stringIn('WHOAMI', VAL = 'RF Feedback Server')
# builder.stringIn('HOSTNAME', VAL = os.uname()[1])


# All records created, can now fire up the IOC.
builder.LoadDatabase()
softioc.iocInit()


# Perform post ioc init initialisation for the various components
mode.init()
# mags.init()
# rffb.init()
# sofb.init()
# vefb.init()
tunefb.init()

softioc.interactive_ioc(globals())
