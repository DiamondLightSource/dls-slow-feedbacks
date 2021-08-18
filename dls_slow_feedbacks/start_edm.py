import os
import subprocess
import sys
from pathlib import Path


def run_edm_gui(edl_file):
    script_dir = Path(os.path.dirname(os.path.realpath(__file__)))
    os.chdir(script_dir / "opi")

    if len(sys.argv) > 1:
        os.environ["EPICS_CA_SERVER_PORT"] = 6064

    subprocess.run(["edm", "-x", "-eolc", edl_file])


def sofb_gui():
    run_edm_gui("rffb.edl")


def vefb_gui():
    run_edm_gui("vefb.edl")
