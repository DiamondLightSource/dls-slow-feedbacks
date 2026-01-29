"""Slow feedback IOC startup interface for ``python -m dls_slow_feedbacks``."""

import logging
import os
from typing import Annotated

import cothread.catools
import typer
from softioc import builder, softioc

from dls_slow_feedbacks import (
    logconfig,
    mode,
    rffb_server,
    sofb_server,
    tunefb_server,
    vefb_server,
    waveforms,
)

from . import __version__

__all__ = ["main"]

# Configure logging
logconfig.setup_logging(application="dls_slow_feedbacks")
logger = logging.getLogger(name="dls_slow_feedbacks")
app = typer.Typer()


# If running in testing mode log instead of executing caput.  We do this by
# "monkey patching" catools!
def mock_caput(pvs, values, **kargs):
    logger.debug("caput", pvs, values, kargs)


def print_version(value: bool):
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def configure_logging() -> None:
    """Set up logging"""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def create_servers(ring_mode: mode.RingMode) -> tuple:
    """Instantiate the appropriate servers:

    wavs - Monitors magnet settings and creates aggregated waveforms.
    rffb - Adjusts RF frequency to minimise horizontal dispersion.
    sofb - Slow orbit feedback. Ensures the beam is centred in the ring.
    vefb - Vertical emittance feedback. Maintains VE at a constant value for beamline
           use.
    tunefb - Tune feedback. Minimises tune spread and allows setting of tune target.

    Return their instances in a tuple.
    """
    wavs = waveforms.WaveformsServer(ring_mode)
    rffb = rffb_server.RffbServer(ring_mode)
    sofb = sofb_server.SofbServer(ring_mode)
    vefb = vefb_server.VefbServer(ring_mode)
    tunefb = tunefb_server.TunefbServer(ring_mode)
    return wavs, rffb, sofb, vefb, tunefb


def create_records() -> None:
    """Create FOFB Mirror and Identification PV's for the IOC."""
    # Mirror PV for FOFB status to reduce overall load on vxWorks IOCs.
    builder.SetDeviceName("SR-CS-FOFB-01")
    builder.aIn("RUN", PINI="YES", VAL=0, INP="SR01A-CS-FOFB-01:RUN CP MS")

    # Identification PV's
    builder.SetDeviceName("CS-DI-IOC-09")
    builder.stringIn("WHOAMI", VAL="Machine Feedback Services")
    builder.stringIn("HOSTNAME", VAL=os.uname()[1])


def start_servers(servers: tuple) -> None:
    """Spawn the cothread routines for each server."""
    for server in servers:
        server.start()


@app.callback(invoke_without_command=True)
def main(
    test: Annotated[
        bool, typer.Option(help="Write to log instead of executing Caput")
    ] = False,
    version: bool = typer.Option(None, "--version", callback=print_version),
) -> None:
    configure_logging()

    if test:
        cothread.catools.caput = mock_caput

    # Used externally to select the operating ring mode, used to define appropriate
    # feedback parameters internally.
    ring_mode = mode.RingMode()
    servers = create_servers(ring_mode)

    create_records()
    builder.LoadDatabase()

    # Fire up the IOC.
    softioc.iocInit()

    ring_mode.init()
    start_servers(servers)

    softioc.interactive_ioc(globals())


if __name__ == "__main__":
    typer.run(main)
