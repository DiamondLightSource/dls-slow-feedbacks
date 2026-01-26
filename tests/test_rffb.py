import unittest

from cothread.dbr import ca_float
from mock import patch

from dls_slow_feedbacks import constants, rffb_server


class MockPV(object):
    """Dummy class with the same interface as
    rffb_server.PvWithValidity but without channel access
    """

    def __init__(self, pv_name, value, severity=constants.SEVR_NO_ALARM, ok=True):
        self.pv_name = pv_name
        self.value = ca_float(value)
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

    def __init__(
        self,
        name,
    ):
        pass


# Default dummy values for cagets
caget_value_list = [
    MockPV("LI-RF-MOSC-01:FREQ_SET", 123456.7),
    MockPV("LI-RF-MOSC-01:FREQ", 123455.6),
    MockPV("MOCK-PV-03", 5.432, severity=constants.SEVR_MAJOR),
    MockPV("MOCK-PV-INVALID", 5.432, severity=constants.SEVR_INVALID),
    MockPV("MOCK-PV-05", 6.54, severity=constants.SEVR_INVALID),
    MockPV("MOCK-PV-MAJOR", 7.864, severity=constants.SEVR_MAJOR),
    MockPV("MOCK-PV-MINOR", 7.864, severity=constants.SEVR_MINOR),
]

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
    except BaseException:
        return_value = -1

    return return_value


class TestMockPv(unittest.TestCase):
    def test_creating_MockPV(self):
        name = "MOCK-PV-01"
        value = 1.234
        pv = MockPV(name, value)

        got = pv.get()

        self.assertEqual(got, value)
        self.assertEqual(got.severity, constants.SEVR_NO_ALARM)
        self.assertEqual(got.ok, True)

    def test_creating_MockPV_with_severity(self):
        name = "MOCK-PV-02"
        value = 2.345
        pv = MockPV(name, value, severity=constants.SEVR_INVALID)

        got = pv.get()

        self.assertEqual(got, value)
        self.assertEqual(got.severity, constants.SEVR_INVALID)
        self.assertEqual(got.ok, True)


class PVWithValidityTests(unittest.TestCase):
    def test_get_name(self):
        pv_name_set = "ANY-PV-NAME-01"
        pv = rffb_server.PVWithValidity(pv_name_set)
        self.assertEqual(pv.get_name(), pv_name_set)

    @patch("cothread.catools.caget", side_effect=lookup_caget_value)
    def test_creating_PVWithValidity(self, mock_caget):
        pv = rffb_server.PVWithValidity("MOCK-PV-03")
        value_should_be = caget_value_dict["MOCK-PV-03"].get()
        self.assertEqual(pv.get(), value_should_be)
        self.assertEqual(pv.severity, value_should_be.severity)

    @patch("cothread.catools.caget", side_effect=lookup_caget_value)
    def test_invalid_cagets_over_threshold_return_not_healthy(self, mock_caget):

        for pv_name in ["MOCK-PV-INVALID", "MOCK-PV-MAJOR", "MOCK-PV-MINOR"]:
            # Create a mock PV
            pv = rffb_server.PVWithValidity(pv_name)
            value_should_be = caget_value_dict[pv_name].get()

            # Check that we tolerate the right number of invalid gets and then
            # complain
            for i in range(pv.ALLOWED_INVALID_CAGETS + 1):

                self.assertEqual(pv.get(), value_should_be)
                self.assertEqual(pv.severity, value_should_be.severity)
                self.assertEqual(pv.consecutive_times_invalid, i + 1)

                print(
                    f"{i}: healthy = {pv.healthy()},"
                    f"consecutive_times_invalid = {pv.consecutive_times_invalid}"
                )

                if i < pv.ALLOWED_INVALID_CAGETS:
                    self.assertTrue(pv.healthy())
                else:
                    self.assertFalse(pv.healthy())

    @patch("cothread.catools.caget", side_effect=lookup_caget_value)
    def test_resetting_severity_makes_PV_healthy(self, mock_caget):
        # Create a mock PV
        pv = rffb_server.PVWithValidity("MOCK-PV-05")
        value_should_be = caget_value_dict["MOCK-PV-05"].get()

        # Do cagets up to the threshold and it should not fail
        for i in range(pv.ALLOWED_INVALID_CAGETS):
            print(i)
            self.assertEqual(pv.get(), value_should_be)
            self.assertEqual(pv.severity, value_should_be.severity)
            self.assertEqual(pv.consecutive_times_invalid, i + 1)

            self.assertTrue(pv.healthy())

        # Reset the severity
        caget_value_dict["MOCK-PV-05"].value.severity = constants.SEVR_NO_ALARM

        # Now go up to the threshold and past it
        # and healthy() should stay True
        for i in range(pv.ALLOWED_INVALID_CAGETS + 5):
            print(i)
            self.assertEqual(pv.get(), value_should_be)
            self.assertEqual(pv.severity, value_should_be.severity)
            self.assertEqual(pv.consecutive_times_invalid, 0)

            self.assertTrue(pv.healthy())


class RffbTests(unittest.TestCase):
    def test_rf_near_setpoint_with_bad_values_returns_false(self):
        """Frequency difference > 100 Hz"""
        present_rf_freq = 499682023
        rf_setpoint = 499681023
        self.assertFalse(
            rffb_server.RffbServer.rf_near_setpoint(present_rf_freq, rf_setpoint)
        )

    def test_rf_near_setpoint_with_good_values_returns_true(self):
        """Frequencey difference < 100 Hz"""
        present_rf_freq = 499682023
        rf_setpoint = 499682023
        self.assertTrue(
            rffb_server.RffbServer.rf_near_setpoint(present_rf_freq, rf_setpoint)
        )
