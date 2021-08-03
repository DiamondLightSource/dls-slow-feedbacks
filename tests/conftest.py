"""Test fixtures."""
import os

import pytest


def pytest_sessionstart():
    """Set EPICS environment variables for Python code.

    Note that any soft IOCs use these variables at launch - see
    ioc_manager.py.

    """
    os.environ["EPICS_CA_SERVER_PORT"] = "7064"
    os.environ["EPICS_CA_REPEATER_PORT"] = "7065"
    os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
    os.environ["EPICS_CA_ADDR_LIST"] = "localhost"
