import os
import subprocess
import sys
from pathlib import Path


def run_edm_gui(edl_file, macros=None):
    script_dir = Path(os.path.dirname(os.path.realpath(__file__)))
    os.chdir(script_dir / "opi")

    if len(sys.argv) > 1:
        os.environ["EPICS_CA_SERVER_PORT"] = 6064

    if macros:
        subprocess.run(["edm", "-x", "-m", macros, "-eolc", edl_file])
    else:
        subprocess.run(["edm", "-x", "-eolc", edl_file])


def sofb_gui():
    run_edm_gui("rffb.edl")


def vefb_gui():
    run_edm_gui("vefb.edl")


def tunefb_gui():
    bin_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    macros = f'bin_dir={bin_dir}'
    run_edm_gui("tfb.edl", macros)
