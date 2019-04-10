#!/dls_sw/prod/R3.14.12.3/support/pythonSoftIoc/2-11/pythonIoc
"""Run all the tests using pythonSoftIoc."""
import os
import sys
import pkg_resources
pkg_resources.require('pytest')
pkg_resources.require('mock')
pkg_resources.require('pytac==0.2.0')
pkg_resources.require('iocbuilder')
pkg_resources.require('epicsdbbuilder')
pkg_resources.require('cothread')
import pytest

# Put the python directory on the path.
PYTHON_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'python')
sys.path.append(PYTHON_DIR)


if __name__ == '__main__':
    pytest.main()
