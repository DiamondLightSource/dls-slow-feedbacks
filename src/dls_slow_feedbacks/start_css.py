import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from dls_slow_feedbacks._version_git import __version__


def get_opi_dir():
    script_dir = Path(os.path.dirname(os.path.realpath(__file__)))
    return script_dir / "opi"


def get_bin_dir():
    bin_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    return bin_dir


def get_version():
    # If the module has not been released, the version will be similar to:
    # 2.9+27.g4c7d2fd.dirty
    # The following regex is designed to identify the hash plus optional '.dirty'
    pattern = re.compile(r"\.g[0-9a-f]{7}(.dirty)?$")
    if pattern.search(__version__) is not None:
        return "dev"
    else:
        return __version__


def get_css():
    output = subprocess.run(
        ["configure-ioc", "s", "-p", "CSS-gui"], capture_output=True
    )
    return output.stdout.strip()


def generate_css_args(launch_opi, links, macros, extra_args):
    args = ["-o", launch_opi, "-s", "-l", links]
    if macros:
        args += ["-m", macros]
    args += extra_args

    return args


def run_css_gui(launch_opi, links, macros, extra_args):
    css_prog = get_css()

    command = [css_prog]
    command += generate_css_args(launch_opi, links, macros, extra_args)
    subprocess.run(command)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Run CSS OPI files. Additional arguments are passed to css.sh.",
        # Need ellipsis at end of standard usage message to indicate args that get
        # passed to css.sh
        usage="start-css [-h] [-m MACROS] opi_file ...",
    )

    parser.add_argument(
        "opi_file",
        help="opi_file path should be relative to opi/ directory",
    )

    # Specify macros (even though all extra args are forwarded) to improve help message
    parser.add_argument(
        "-m", dest="macros", help="CSS macros in format: macro1=value1,macro2=value2"
    )

    return parser.parse_known_args()


def validate_opi_file(opi_path):
    opi_valid = opi_path.is_file() and opi_path.suffix == ".opi"
    if not opi_valid:
        raise OSError(f"The opi path does not link to an opi file:\n{opi_path}")


def main():
    parsed_args, unparsed_args = parse_arguments()

    opi_file = parsed_args.opi_file

    module = "dls_slow_feedbacks"
    version = get_version()

    project = f"{module}_{version}"
    launch_opi = f"/{project}/{module}/{opi_file}"

    opi_dir = get_opi_dir()
    links = f"{opi_dir}={project}/{module}"

    validate_opi_file(opi_dir / opi_file)

    bin_dir = get_bin_dir()
    macros = ",".join(filter(None, [parsed_args.macros, f"bin_dir={bin_dir}"]))

    os.chdir(opi_dir)
    run_css_gui(launch_opi, links, macros, unparsed_args)
