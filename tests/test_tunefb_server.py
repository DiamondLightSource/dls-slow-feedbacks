#!/dls_sw/work/R3.14.12.3/support/pythonSoftIoc/pythonIoc
# Need all the packages available for imports.

# Note that these unit tests are using caget to fetch data from
# EPICS.  If IOCs are not responding, the tests may fail.

from pkg_resources import require
require('cothread')
require('numpy')
require('scipy')
require('iocbuilder')

from mock import MagicMock, patch
import unittest
import time
from tunefb_server import TunefbServer, TunefbError, TunefbInvalid
import numpy


class TestTunefb(unittest.TestCase):

    def __init__(self, caller):
        unittest.TestCase.__init__(self, caller)

    def setUp(self):
        mode = MagicMock(listeners=[])
        with patch('tunefb_server.TunefbServer.records'):
            self.tfb = TunefbServer(mode)
            self.tfb.max_i_pv = MagicMock()

    def test_check_current_does_nothing_if_current_valid(self):
        with patch('tunefb_server.caget') as mock_caget:
            mock_caget.return_value = 2
            try:
                self.tfb.check_current()
            except TunefbError:
                self.fail('Should not throw an exception.')

    def test_check_current_throws_exception_if_current_invalid(self):
        with patch('tunefb_server.caget') as mock_caget:
            mock_caget.return_value = 0.5
            self.assertRaises(TunefbError, self.tfb.check_current)

    def test_refresh_tune_deltas_throws_exception_if_severity_minor(self):
        with patch('tunefb_server.caget') as mock_caget:
            val1 = ca_float(1.0)
            val1.severity = 1
            val2 = ca_float(numpy.nan)
            mock_caget.return_value = (val1, val2)
            self.assertRaises(TunefbInvalid, self.tfb.refresh_tune_deltas)

    def test_refresh_tune_deltas_throws_exception_if_nan_received(self):
        with patch('tunefb_server.caget') as mock_caget:
            val1 = ca_float(1.0)
            val1.timestamp = time.time()
            val2 = ca_float(numpy.nan)
            val2.timestamp = time.time()
            mock_caget.return_value = (val1, val2)
            self.assertRaises(TunefbInvalid, self.tfb.refresh_tune_deltas)

    def test_refresh_tune_deltas_throws_exception_if_timestamp_old(self):
        with patch('tunefb_server.caget') as mock_caget:
            val1 = ca_float(1.0)
            val1.timestamp = time.time() - 2  # Allowed lag 1.0s.
            val2 = ca_float(numpy.nan)
            val2.timestamp = time.time()
            mock_caget.return_value = (val1, val2)
            self.assertRaises(TunefbInvalid, self.tfb.refresh_tune_deltas)

    def test_scale_deltas_returns_deltas_if_none_smaller_than_max(self):
        self.tfb.mag_delta_max = 10
        deltas = numpy.array([1, 2, 3, 4], dtype=numpy.float64)
        scaled_deltas = self.tfb.scale_deltas(deltas)
        if not all(deltas == scaled_deltas):
            self.fail('Deltas should not be scaled.')

    def test_scale_deltas_scales_deltas_if_larger_than_max(self):
        self.tfb.mag_delta_max = 1
        deltas = numpy.array([1, 2, 3, 4], dtype=numpy.float64)
        correctly_scaled = numpy.array([0.25, 0.5, 0.75, 1.0])
        scaled_deltas = self.tfb.scale_deltas(deltas)
        print('The scaled deltas are {}'.format(scaled_deltas))
        if not all(correctly_scaled == scaled_deltas):
            self.fail('Deltas should have been scaled.')

    def test_check_mag_limits_raises_exception_if_i_too_large(self):
        self.tfb.max_current_range = 1.0
        currents = numpy.zeros((100,))
        currents[45] = 0.5
        self.tfb.check_mag_limits(currents)
        currents[55] = 2
        self.assertRaises(TunefbError, self.tfb.check_mag_limits, currents)


class ca_float(float):
    severity = 0
    timestamp = None


if __name__ == "__main__":
    unittest.main()
