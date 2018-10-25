#!/bin/env dls-python
from pkg_resources import require
require("mock")
from mock import MagicMock, patch
require("cothread")
import cothread
import unittest

import rffb_server
import constants

class MockPV:
    def __init__(self, pv_name, value, severity=constants.SEVR_NO_ALARM, ok=True):
        self.pv_name = pv_name
        self.value = cothread.dbr.ca_float(value)
        self.value.severity = severity
        self.value.ok = ok

    def get(self):
        self.value.timestamp = 0
        return self.value

    def put(self, value):
        self.value = value
        return

# Default dummy values for cagets
caget_value_list = [MockPV("LI-RF-MOSC-01:FREQ_SET", 499681023),
              MockPV("LI-RF-MOSC-01:FREQ", 499682023),
              MockPV("MOCK-PV-03", 5.432, severity=constants.SEVR_MAJOR),
                MockPV("MOCK-PV-04", 5.432, severity=constants.SEVR_INVALID)]

# Put these in a dict for ease of access
caget_value_dict = {}
for caget_value in caget_value_list:
    caget_value_dict[caget_value.pv_name] = caget_value

def lookup_caget_value(pv_name, *args, **kwargs):
    """Mock a caget by returning a value from a dict;
    To use, add :
    @patch("cothread.catools.caget", side_effect = lookup_caget_value)"""
    try:
        return_value = caget_value_dict[pv_name].get()
    except:
        return_value = -1

    return return_value

class TestMockPv(unittest.TestCase):
    def test_creating(self):
        name = "MOCK-PV-01"
        value = 1.234
        pv = MockPV(name, value)

        got = pv.get()

        self.assertEqual(got, value)
        self.assertEqual(got.severity, constants.SEVR_NO_ALARM)
        self.assertEqual(got.ok, True)

    def test_creating_with_severity(self):
        name = "MOCK-PV-02"
        value = 2.345
        pv = MockPV(name, value, severity=constants.SEVR_INVALID)

        got = pv.get()

        self.assertEqual(got, value)
        self.assertEqual(got.severity, constants.SEVR_INVALID)
        self.assertEqual(got.ok, True)

class PVWithValidityTests(unittest.TestCase):
    @patch("cothread.catools.caget", side_effect=lookup_caget_value)
    def test_creating(self, mock_caget):
        pv = rffb_server.PVWithValidity("MOCK-PV-03")
        value_should_be = caget_value_dict["MOCK-PV-03"].get()
        self.assertEqual(pv.get(), value_should_be)
        self.assertEqual(pv.severity, value_should_be.severity)

    @patch("cothread.catools.caget", side_effect=lookup_caget_value)
    def test_threshold(self, mock_caget):
        pv = rffb_server.PVWithValidity("MOCK-PV-04")
        value_should_be = caget_value_dict["MOCK-PV-04"].get()


        for i in xrange(pv.ALLOWED_INVALID_CAGETS+1):
            print i
            self.assertEqual(pv.get(), value_should_be)
            self.assertEqual(pv.severity, value_should_be.severity)

            if i < pv.ALLOWED_INVALID_CAGETS:
                self.assertTrue(pv.healthy())
            else:
                self.assertFalse(pv.healthy())

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
