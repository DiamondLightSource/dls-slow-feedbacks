#!/bin/env dls-python
from pkg_resources import require

require("mock")
from mock import MagicMock, patch
import copy

require("cothread")
import cothread
import unittest

import rffb_server
import constants
import mode


class MockPV(object):
    """Dummy class with the same interface as
    rffb_server.PvWithValidity but without channel access
    """

    def __init__(self, pv_name, value, severity=constants.SEVR_NO_ALARM,
                 ok=True):
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


class MockRecord(object):
    """Mock an iocbuilder record"""
    def __init__(self, name, ):
        pass


# Default dummy values for cagets
caget_value_list = [MockPV("LI-RF-MOSC-01:FREQ_SET", 123456.7),
                    MockPV("LI-RF-MOSC-01:FREQ", 123455.6),
                    MockPV("MOCK-PV-03", 5.432, severity=constants.SEVR_MAJOR),
                    MockPV("MOCK-PV-04", 5.432,
                           severity=constants.SEVR_INVALID),
                    MockPV("MOCK-PV-05", 6.54, severity=constants.SEVR_INVALID)]

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
        # Create a mock PV
        pv = rffb_server.PVWithValidity("MOCK-PV-04")
        value_should_be = caget_value_dict["MOCK-PV-04"].get()

        # Check that we tolerate the right number of invalid gets and then
        # complain
        for i in xrange(pv.ALLOWED_INVALID_CAGETS + 1):

            self.assertEqual(pv.get(), value_should_be)
            self.assertEqual(pv.severity, value_should_be.severity)

            print("%d: healthy = %s, consecutive_times_invalid = %d" % (
            i, pv.healthy(), pv.consecutive_times_invalid))

            if i < pv.ALLOWED_INVALID_CAGETS:
                self.assertTrue(pv.healthy())
            else:
                self.assertFalse(pv.healthy())

    @patch("cothread.catools.caget", side_effect=lookup_caget_value)
    def test_almost_threshold(self, mock_caget):
        # Create a mock PV
        pv = rffb_server.PVWithValidity("MOCK-PV-05")
        value_should_be = caget_value_dict["MOCK-PV-05"].get()

        # Do cagets up to the threshold and it should not fail
        for i in xrange(pv.ALLOWED_INVALID_CAGETS):
            print i
            self.assertEqual(pv.get(), value_should_be)
            self.assertEqual(pv.severity, value_should_be.severity)

            self.assertTrue(pv.healthy())

        # Reset the severity
        caget_value_dict["MOCK-PV-05"].value.severity = \
            constants.SEVR_NO_ALARM

        # Now go up to the threshold and past it
        # and healthy() should stay True
        for i in xrange(pv.ALLOWED_INVALID_CAGETS + 5):
            print i
            self.assertEqual(pv.get(), value_should_be)
            self.assertEqual(pv.severity, value_should_be.severity)

            if i < pv.ALLOWED_INVALID_CAGETS:
                self.assertTrue(pv.healthy())


class RffbTests(unittest.TestCase):

    def test_rf_near_setpoint_bad(self):
        """Frequency difference > 100 Hz"""
        present_rf_freq = 499682023
        rf_setpoint = 499681023
        self.assertFalse(
            rffb_server.RffbServer.rf_near_setpoint(
                present_rf_freq,
                rf_setpoint))

    def test_rf_near_setpoint_good(self):
        """Frequencey difference < 100 Hz"""
        present_rf_freq = 499682023
        rf_setpoint = 499682023
        self.assertTrue(rffb_server.RffbServer.rf_near_setpoint(
            present_rf_freq,
            rf_setpoint))


class RffbServerFactory(object):
    """Class to hand out fresh copies of the RffbServer object
    In an attempt to get around iocbuilder's restriction on
    defining record names only once

    Edit: not as clever as I thought, the copy contains references
    """
    def __init__(self):
        ring_mode = mode.RingMode()
        self.rffb = rffb_server.RffbServer(ring_mode)

    def get_object(self):
        return copy.copy(self.rffb)

# Done at module level so is only instantiated once
rffb_server_factory = RffbServerFactory()

class TestRffbServerFactory(unittest.TestCase):
    @patch("cothread.catools.caget", side_effect=lookup_caget_value)
    def test_modifying_one_copy_doesnt_modify_other(self, mock_caget):
        rffb1 = rffb_server_factory.get_object()
        rffb2 = rffb_server_factory.get_object()

        rffb1.power_pv.set(1)
        rffb2.power_pv.set(0)
        self.assertNotEquals(rffb2.power_pv.get(), rffb1.power_pv.get())

class IntegrationTests(unittest.TestCase):

    @patch("cothread.catools.caget", side_effect=lookup_caget_value)
    def setUp(self, mock_caget):
        self.rffb = rffb_server_factory.get_object()

    def tearDown(self):
        self.rffb = None

    def test_records_created(self):
        self.assertIsInstance(self.rffb.rf_freq_set_pv, rffb_server.PVWithValidity)
        self.assertIsNotNone(self.rffb.power_pv)

    def test_caget_of_nonexistent_pv_raises_exception(self):
        #caget_value_dict["MOCK-PV-05"] = MockPV()
        with self.assertRaises(cothread.catools.ca_nothing):
            self.rffb.feedback()

    def test_caget_of_nonexistent_pv_raises_exception_again(self):
        # caget_value_dict["MOCK-PV-05"] = MockPV()
        with self.assertRaises(cothread.catools.ca_nothing):
            self.rffb.feedback()

"""
    def test_rf_frequency_and_setpoint_differ(self):
        present_rf_freq = 499682023
        rf_setpoint = 499681023
        caget_value_dict["MOCK-PV-05"] = MockPV()

"""

if __name__ == "__main__":
    unittest.main()
