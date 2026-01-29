"""
Simple script to set OFFSET1.INP for each magnet used in tune feedback.

Each .INP is set to the local PV mirrored in our IOC.
"""

import logging
import sys
from typing import Annotated

import cothread
import typer
from cothread.catools import DBR_STRING, caget, caput  # noqa
from pytac import cothread_cs, load_csv

logger = logging.getLogger(name="dls_slow_Feedbacks")
tunefb_app = typer.Typer()

# Constants
BEAM_DAMP_TIME = 0.001
IOC = "SR-CS-TFB-01"
CURRENT_LINK = ":I CPP MS"
OFFSET_INPUT = ":OFFSET1.INP"
LOCAL_LINK = ":LOFFSET1 CPP MS"

TUNE_QUAD_FAMILIES = ("Q1D", "Q2D", "Q3D", "Q3B", "Q2B", "Q1B")


# If running in testing mode log instead of executing caput.
def mock_caput(pvs, values, **kargs):
    logger.debug("caput", pvs, values, kargs)


def load_magnet_pvs(lattice) -> list[str]:
    """
    Load corrector magnet PVs from the specific format
    in the file.
    """
    quad_names = []
    for family in TUNE_QUAD_FAMILIES:
        device_names = lattice.get_element_device_names(family, "b1")
        quad_names.extend(device_names)
    return quad_names


def rename_pvs(pvs) -> list[str]:
    """Rename quadrupole pv names for use as local pvs."""
    new_pvs = []
    for pv in pvs:
        parts = pv.split("-")
        cell = parts[0][2:4]
        new_pv = IOC + ":" + cell + parts[2] + parts[3]
        new_pvs.append(new_pv)
    return new_pvs


def all_forwarded(local_pvs, mag_pvs) -> bool:
    """Check if PV names have been correctly forwarded."""
    inps = caget([pv + OFFSET_INPUT for pv in mag_pvs], timeout=1.0)
    expected = [pv + CURRENT_LINK for pv in local_pvs]
    return inps == expected


@tunefb_app.callback(invoke_without_command=True)
def main(
    test: Annotated[
        bool, typer.Option(help="Write to log instead of executing Caput.")
    ] = False,
    redirect: Annotated[
        bool,
        typer.Option(
            help="Configure OFFSET PVs to mirror the value of the TFB current PVs."
        ),
    ] = False,
    reset: Annotated[
        bool,
        typer.Option(
            help="Configure OFFSET PVs to mirror the value of the LOFFSET PVs."
        ),
    ] = False,
    forwarded: Annotated[
        bool,
        typer.Option(help="Returns true if PVs have been forwarded"),
    ] = False,
):
    mode = caget("SR-CS-RING-01:MODE", datatype=DBR_STRING)

    # Increase CA timeouts to improve reliability
    cs = cothread_cs.CothreadControlSystem(timeout=5.0)

    lattice = load_csv.load(mode, control_system=cs)
    mag_pvs = load_magnet_pvs(lattice)
    local_pvs = rename_pvs(mag_pvs)
    caput_function = caput
    if test:
        caput_function = mock_caput

    if redirect:
        # The offset PVs, such as SR01A-PC-Q1D-01:OFFSET1 should get their value from
        # the tunefeedback current PVs, such as SR-CS-TFB-01:01Q1D01:I. To do this,
        # we must write name of the tunefb PV into the .INP field of the OFFSET PV.
        # This is done by calling tunefb_offsets.main() with the "redirect" arg.
        links = [pv + CURRENT_LINK for pv in local_pvs]
    elif reset:
        # set INP to the remote PVs
        links = [pv + LOCAL_LINK for pv in mag_pvs]
    elif forwarded:
        logger.info(f"mags forwarded = {all_forwarded(local_pvs, mag_pvs)}")
        sys.exit()
    else:
        print(
            "Please provide one of the following options: --redirect | --reset | "
            "--forwarded."
        )
        sys.exit()

    inps = [pv + ":OFFSET1.INP" for pv in mag_pvs]
    for inp, link in zip(inps, links, strict=True):
        caput_function(inp, link)
        cothread.Sleep(BEAM_DAMP_TIME * 10.0)
