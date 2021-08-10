import logging

# Slow feedback IOC startup.
import os
import sys

from epicsdbbuilder import records
from softioc import builder, softioc

from dls_slow_feedbacks import (
    mode,
    rffb_server,
    sofb_server,
    tunefb_server,
    vefb_server,
    waveforms,
)

if sys.argv[1:]:
    # If running in testing mode log instead of executing caput.  We do this by
    # "monkey patching" catools!
    import cothread.catools

    def caput(pvs, values, **kargs):
        print("caput", pvs, values, kargs)

    cothread.catools.caput = caput

# Configure logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

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
builder.SetDeviceName("SR-CS-FOFB-01")
run = records.ai("RUN", PINI="YES", VAL=0, INP="SR01A-CS-FOFB-01:RUN CP MS")


# Create the identification PVs
builder.SetDeviceName("CS-DI-IOC-09")
builder.stringIn("WHOAMI", VAL="Machine Feedback Services")
builder.stringIn("HOSTNAME", VAL=os.uname()[1])


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
