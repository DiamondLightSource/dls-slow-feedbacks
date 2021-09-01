import os
import sys

from setuptools import setup

# Place the directory containing _version_git on the path
TOP = os.path.dirname(os.path.abspath(__file__))
for d in os.listdir(TOP):
    if os.path.exists(os.path.join(TOP, d, "_version_git.py")):
        sys.path.append(os.path.join(TOP, d))

from _version_git import __version__, get_cmdclass  # noqa

# Setup information is stored in setup.cfg but this function call
# is still necessary.
setup(cmdclass=get_cmdclass(), version=__version__)
