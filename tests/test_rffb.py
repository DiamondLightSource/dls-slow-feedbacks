#!/bin/env dls-python
from pkg_resources import require
require("mock")
from mock import MagicMock, patch
import unittest

import rffb_server

# Default dummy values for cagets
caget_values = {"LI-RF-MOSC-01:FREQ_SET": 499681023,
              "LI-RF-MOSC-01:FREQ": 499682023 }

def lookup_caget_value(pv_name):
    """Mock a caget by returning a value from a dict;
    To use, add :
    @patch("cothread.catools.caget", side_effect = lookup_caget_value)"""
    try:
        return_value = caget_values[pv_name]
    except:
        return_value = -1

    return return_value

class RffbTests(unittest.TestCase):

    def test_rf_near_setpoint_bad(self):
        """Frequency difference > 100 Hz"""
        present_rf_freq = 499682023
        rf_setpoint = 499681023
        self.assertFalse(rffb_server.RffbServer.rf_near_setpoint(present_rf_freq, rf_setpoint))

    def test_rf_near_setpoint_good(self):
        """Frequencey difference < 100 Hz"""
        present_rf_freq = 499682023
        rf_setpoint = 499682023
        self.assertTrue(rffb_server.RffbServer.rf_near_setpoint(present_rf_freq, rf_setpoint))


if __name__ == "__main__":
    unittest.main()
