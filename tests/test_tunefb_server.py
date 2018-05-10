#!/dls_sw/work/R3.14.12.3/support/pythonSoftIoc/pythonIoc
# Need all the packages available for imports.

# Note that these unit tests are using caget to fetch data from
# EPICS.  If IOCs are not responding, the tests may fail.

from pkg_resources import require
require('cothread')
require('iocbuilder')
require('mock')
require('pytac')


from mock import MagicMock, patch
import unittest
import os
import time
import tunefb_server
from tunefb_server import TunefbServer, TunefbError, TunefbInvalid
import numpy
import pytac


RING_MODE = 'DIAD'
LATTICE = pytac.load_csv.load(RING_MODE)


TFB_FAMILIES = ('Q1D', 'Q2D', 'Q3D', 'Q3B', 'Q2B', 'Q1B')
DATADIR = '/dls_sw/work/common/matlab/mml/machine/diamondopsdata'
RESPONSE_MATRIX = os.path.join(DATADIR, RING_MODE, 'GoldenTuneResp.mat')


def load_pytac_tfb_pvs():
    tfb_elements = []
    for family in TFB_FAMILIES:
        tfb_elements.extend(LATTICE.get_elements(family))
    tfb_pvs = [element.get_device('b1').name for element in tfb_elements]
    return tfb_pvs


class TestTunefb(unittest.TestCase):

    def __init__(self, caller):
        unittest.TestCase.__init__(self, caller)

    @patch('tunefb_server.caget')
    @patch('tunefb_server.TunefbServer.records')
    def setUp(self, mock_records, mock_caget):
        mode = MagicMock(listeners=[])
        self.pytac_tfb_pvs = load_pytac_tfb_pvs()
        self.nquads = len(self.pytac_tfb_pvs)
        self.tfb = TunefbServer(mode)
        self.tfb.max_i_pv = MagicMock()
        self.tfb.rm = numpy.zeros((2, self.nquads))
        self.tfb.tune_int_h_pv = MagicMock()
        self.tfb.tune_int_v_pv = MagicMock()
        self.tfb.integrated_current = numpy.zeros(self.nquads)

    def test_load_tune_rm_dimensions(self):
        rm = tunefb_server.load_tune_rm(RESPONSE_MATRIX)
        self.assertEqual(rm.shape, (2, self.nquads))

    def test_magnet_pvs_match_pytac(self):
        self.assertListEqual(self.tfb.mag_pvs, self.pytac_tfb_pvs)

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

    def test_refresh_tune_deltas_completes_when_tune_severity_minor(self):
        with patch('tunefb_server.caget') as mock_caget:
            val1 = ca_float(1.0)
            val1.timestamp = time.time()
            val1.severity = 1
            val2 = ca_float(1.0)
            val2.timestamp = time.time()
            mock_caget.return_value = (val1, val2)
            try:
                self.tfb.refresh_tune_deltas()
            except TunefbInvalid:
                self.fail('Should not thrown an exception')

    def test_loop_correction_throws_error_on_mutiple_invalids(self):
        self.tfb.update_fwd_ok_pv = MagicMock()
        self.tfb.checked_correction = MagicMock(side_effect=TunefbInvalid(7))
        self.tfb.power_pv = MagicMock()
        self.tfb.status_pv = MagicMock()
        # If we keep getting Invalids we should trip
        for _ in range(10):
            self.tfb.loop_correction()
        try:
            self.assertFalse(self.tfb.power_pv.set.call_args[0][0])
        except TypeError:
            self.fail('self.tfb.power_pv.set object never called')

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

    def test_apply_correction_does_not_apply_nans_from_deltas(self):
        deltas = numpy.zeros(self.nquads)
        deltas[56] = numpy.nan
        # Awkward patch to control value of fetched_current
        with patch('numpy.array') as na:
            z = numpy.zeros(self.nquads)
            na.return_value = z
            self.assertRaises(TunefbError, self.tfb.apply_correction, deltas)

    def test_apply_correction_does_not_apply_nans_from_pv(self):
        deltas = numpy.zeros(self.nquads)
        # Awkward patch to control value of fetched_current
        with patch('numpy.array') as na:
            z = numpy.zeros(self.nquads)
            z[33] = numpy.nan
            na.return_value = z
            self.assertRaises(TunefbError, self.tfb.apply_correction, deltas)

    def test_check_tune_alarms_raises_exception_with_minor_severity(self):
        self.tfb.tunes = [MagicMock(), MagicMock()]
        for tune in self.tfb.tunes:
            tune.severity = 1
        self.assertRaises(TunefbInvalid, self.tfb.check_tune_alarms)

    def test_check_tune_alarms_completes_with_no_alarm_severity(self):
        self.tfb.tunes = [MagicMock(), MagicMock()]
        for tune in self.tfb.tunes:
            tune.severity = 0
        try:
            self.tfb.check_tune_alarms()
        except TunefbInvalid:
            self.fail('Should not throw an exception.')

    @patch('tunefb_server.caput')
    @patch('tunefb_server.caget')
    def test_aggregate_setpoints_moves_values_to_setpoints(self, mock_caget, mock_caput):
        self.tfb.aggregate_pv = MagicMock()
        self.tfb.reset_integrated_current_pv = MagicMock()
        self.tfb.integrated_tunes = numpy.array([1,2])
        rnd_integrated = numpy.random.rand(self.nquads)
        rnd_setpoint = numpy.random.rand(self.nquads)
        self.tfb.integrated_current = numpy.copy(rnd_integrated)
        [self.tfb.mirror_pvs.append(MagicMock()) for q in range(self.nquads)]

        mock_caget.side_effect = rnd_setpoint
        # Actually call the function
        self.tfb.aggregate_setpoints(1)

        numpy.testing.assert_array_equal(self.tfb.integrated_current,
                                       numpy.zeros(self.nquads))
        calls = numpy.array([call[0][1] for call in mock_caput.call_args_list])
        numpy.testing.assert_array_equal(rnd_integrated + rnd_setpoint, calls)
        numpy.testing.assert_array_equal(self.tfb.integrated_tunes, numpy.zeros(2))

    def test_reset_integrated_current_sets_everything_to_zero(self):
        self.tfb.aggregate_pv = MagicMock()
        self.tfb.reset_integrated_current_pv = MagicMock()
        self.tfb.integrated_tunes = numpy.array([1,2])
        rnd_integrated = numpy.random.rand(self.nquads)
        self.tfb.integrated_current = numpy.copy(rnd_integrated)
        (self.tfb.mirror_pvs.append(MagicMock()) for q in range(self.nquads))

        # Actually call the function
        self.tfb.reset_integrated_current(1)

        numpy.testing.assert_array_equal(self.tfb.integrated_current,
                                       numpy.zeros(self.nquads))
        numpy.testing.assert_array_equal(self.tfb.integrated_tunes, numpy.zeros(2))


class ca_float(float):
    severity = 0
    timestamp = None


if __name__ == "__main__":
    unittest.main()
