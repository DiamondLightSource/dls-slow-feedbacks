import logging

# Slow feedback IOC startup.
import os
import sys
from typing import Tuple

import cothread.catools
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

TESTING_MODE = bool(sys.argv[1:])


def mock_caput(pvs, values, **kargs) -> None:
    """Log instead of executing caput when in testing mode."""
    print("caput", pvs, values, kargs)


def configure_logging() -> None:
    """Set up logging"""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def create_servers(ring_mode: mode.RingMode) -> Tuple:
    """Instantiate the appropriate servers:

    wavs - Monitors magnet settings and creates aggregated waveforms.
    rffb - Adjusts RF frequency to minimise horizontal dispersion.
    sofb - Slow orbit feedback. Ensures the beam is centred in the ring.
    vefb - Vertical emittance feedback. Minimises vertical beam size.
    tunefb - Tune feedback. Minimises tune spread.

    Return their instances in a tuple.
    """
    wavs = waveforms.WaveformsServer(ring_mode)
    rffb = rffb_server.RffbServer(ring_mode)
    sofb = sofb_server.SofbServer(ring_mode)
    vefb = vefb_server.VefbServer(ring_mode)
    tunefb = tunefb_server.TunefbServer(ring_mode)
    return wavs, rffb, sofb, vefb, tunefb


def create_pvs() -> None:
    """Create FOFB Mirror and Identification PV's for the IOC."""
    # Mirror PV for FOFB status to reduce overall load on vxWorks IOCs.
    builder.SetDeviceName("SR-CS-FOFB-01")
    run = records.ai("RUN", PINI="YES", VAL=0, INP="SR01A-CS-FOFB-01:RUN CP MS")

    # Identification PV's
    builder.SetDeviceName("CS-DI-IOC-09")
    builder.stringIn("WHOAMI", VAL="Machine Feedback Services")
    builder.stringIn("HOSTNAME", VAL=os.uname()[1])


def initialise_servers(servers: Tuple) -> None:
    """Spawn the cothread routines for each server."""
    for server in servers:
        server.init()


def main() -> None:
    configure_logging()

    if TESTING_MODE:
        cothread.catools.caput = mock_caput

    # Used externally to select the operating ring mode, used to define appropriate
    # feedback parameters internally.
    ring_mode = mode.RingMode()
    servers = create_servers(ring_mode)

    create_pvs()
    builder.LoadDatabase()

    # All records created, can now fire up the IOC.
    softioc.iocInit()

    # Perform post iocInit initialisation
    initialise_servers(servers)

    softioc.interactive_ioc(globals())
