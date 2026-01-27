import time
from unittest import mock

import pytac
import pytest

from dls_slow_feedbacks import vefb_server
from dls_slow_feedbacks.vefb_server import VefbServer, VefbStatus


def setup_module():
    vefb_server.SkewQuadrupoles = mock.MagicMock
    vefb_server.PVMonitor = mock.MagicMock
    time.original_time = time.time
    time.time = mock.MagicMock(return_value=1000.1)


def teardown_module():
    time.time = time.original_time


@pytest.fixture
def ring():
    return pytac.load_csv.load("DIAD")


@pytest.fixture
def nsquads(ring):
    return len(ring.get_elements("SQUAD"))


@pytest.fixture
def ring_mode(ring):
    ring_mode = mock.MagicMock(lattice=ring)
    ring_mode.DATAROOT = "/dls_sw/work/common/matlab/mml/machine-new/diamondopsdata"
    return ring_mode


def soft_ioc_pv(return_value):
    """Used for mocking PVs created by pythonSoftIoc."""
    get = mock.MagicMock(return_value=return_value)
    return mock.MagicMock(get=get)


@pytest.fixture
def vefb(ring_mode, nsquads):
    """Mock all the necessary attributes of VefbServer."""
    with mock.patch.object(VefbServer, "records"):
        v = vefb_server.VefbServer(ring_mode)
        v.error_check = mock.MagicMock(return_value=VefbStatus.OK)
        v.vemit = mock.MagicMock(value=1.5, timestamp=1000)
        v.vemit_target_pv = soft_ioc_pv(1)
        v.vemit_err_max_pv = soft_ioc_pv(1)
        v.vemit_extra_err_max_pv = soft_ioc_pv(1)
        v.afrac_pv = soft_ioc_pv(1)
        v.iir_frac_pv = soft_ioc_pv(1)
        # method_pv is 1 for the new method of calculation
        v.method_pv = soft_ioc_pv(1)
        v.status_pv = soft_ioc_pv(1)
        v.squad_delta_max_pv = soft_ioc_pv(1)
        v.calc_parameters_ok = soft_ioc_pv(True)
        v.skew_quads.set_pv_names = mock.MagicMock()
        v.skew_quads.put_delta = mock.MagicMock()
        v.skew_quads.num = nsquads
        v.on_ringmode_change(ring_mode.lattice)
        return v


def test_vefb_server_do_calc_fails_if_calc_parameters_ok_returns_false(vefb):
    vefb.calc_parameters_ok = mock.MagicMock(return_value=False)
    assert vefb.do_calc(False) == VefbStatus.MISSING_CALC_PARAMETERS


def test_vefb_server_do_calc_fails_if_vemit_timestamp_older_than_1_sec(vefb):
    # More than one second older than the mocked value of 1000.1
    vefb.vemit.timestamp = 999
    assert vefb.do_calc(False) == VefbStatus.NO_EMITTANCE_VALUE


@pytest.mark.parametrize("apply", (True, False))
@pytest.mark.parametrize("check_limits", (True, False))
def test_vefb_server_do_calc_succeeds_if_calc_parameters_ok_returns_true(
    vefb, apply, check_limits
):
    # Set up variables for the calculation
    vefb.afrac_pv = soft_ioc_pv(0.5)
    vefb.IRM = 2
    vefb.vemit.value = 3
    vefb.vemit_target_pv = soft_ioc_pv(4)
    # Expect -0.5 * 2 * (4 - 3) = 1
    expected_delta = 1
    with mock.patch.object(vefb, "apply_delta") as mock_apply:
        mock_apply.return_value = "dummy"
        # Check that the return value of apply_delta is returned
        assert vefb.do_calc(apply, check_limits=check_limits) == "dummy"
        # Check the calculated delta
        assert mock_apply.call_args[0][0] == expected_delta
        # Check that apply_calc and check_limits were passed through
        assert mock_apply.call_args[0][1] == apply
        assert mock_apply.call_args[0][2] == check_limits


def test_apply_delta_returns_magnet_delta_error_if_delta_gt_delta_max_and_check_limits(
    vefb,
):
    vefb.squad_delta_max_pv = soft_ioc_pv(2)
    assert vefb.apply_delta(3, check_limits=True) == VefbStatus.MAGNET_DELTA_ERROR


def test_apply_delta_returns_magnet_error_if_put_delta_not_ok(vefb):
    vefb.skew_quads.put_delta.return_value = False
    assert vefb.apply_delta(1) == VefbStatus.MAGNET_ERROR


def test_apply_delta_applies_correct_dimensions(vefb, nsquads):
    vefb.apply_delta(2)
    assert vefb.skew_quads.put_delta.call_args[0][0].size == nsquads
