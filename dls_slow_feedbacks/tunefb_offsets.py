"""
Simple script to set OFFSET1.INP for each magnet used in tune feedback.

Each .INP is set to the local PV mirrored in our IOC.
"""
import sys

import cothread
from pytac import cothread_cs, load_csv
from cothread.catools import DBR_STRING, caget, caput  # noqa
import logging as log

# Constants
BEAM_DAMP_TIME = 0.001
IOC = "SR-CS-TFB-01"
CURRENT_LINK = ":I CPP MS"
OFFSET_INPUT = ":OFFSET1.INP"
LOCAL_LINK = ":LOFFSET1 CPP MS"


TUNE_QUAD_FAMILIES = ("Q1D", "Q2D", "Q3D", "Q3B", "Q2B", "Q1B")


def load_magnet_pvs(lattice):
    """
    Load corrector magnet PVs from the specific format
    in the file.
    """
    quad_names = []
    for family in TUNE_QUAD_FAMILIES:
        device_names = lattice.get_element_device_names(family, "b1")
        quad_names.extend(device_names)
    return quad_names


def rename_pvs(pvs):
    """Rename quadrople pv names for use as local pvs."""
    new_pvs = []
    for pv in pvs:
        parts = pv.split("-")
        cell = parts[0][2:4]
        new_pv = IOC + ":" + cell + parts[2] + parts[3]
        new_pvs.append(new_pv)
    return new_pvs


def all_forwarded(local_pvs, mag_pvs):
    inps = caget([pv + OFFSET_INPUT for pv in mag_pvs], timeout=1.0)
    expected = [pv + CURRENT_LINK for pv in local_pvs]
    return inps == expected


def main():
    mode = caget("SR-CS-RING-01:MODE", datatype=DBR_STRING)

    # Increase CA timeouts to improve reliability
    cs = cothread_cs.CothreadControlSystem(timeout=5.0)

    lattice = load_csv.load(mode, control_system=cs)
    mag_pvs = load_magnet_pvs(lattice)
    local_pvs = rename_pvs(mag_pvs)

    caput_function = caput

    if "test" in sys.argv:

        def test_caput(pv, value):
            log.debug(f"(TFB) Testing caput: {pv}   {value}")

        caput_function = test_caput

    if "redirect" in sys.argv:
        # set INP to our PVs
        links = [pv + CURRENT_LINK for pv in local_pvs]
    elif "reset" in sys.argv:
        # set INP to the remote PVs
        links = [pv + LOCAL_LINK for pv in mag_pvs]
    elif "forwarded" in sys.argv:
        log.info("(TFB) mags forwarded = " + all_forwarded(local_pvs, mag_pvs))
        sys.exit()
    else:
        log.info("(TFB) usage: ")
        log.info(f"(TFB) {sys.argv[0]} redirect|reset [test]")
        sys.exit()

    inps = [pv + ":OFFSET1.INP" for pv in mag_pvs]
    for inp, link in zip(inps, links):
        caput_function(inp, link)
        cothread.Sleep(BEAM_DAMP_TIME * 10.0)
