import sys
import os
import numpy
import inspect
import pytest
import mock
import collections
import pytac
from pytac import epics
from cothread import catools

try:
    import pytest
except ImportError:
    print('Usage: py.test {}'.format(sys.argv[0]))
    sys.exit()

import sofb
import sofb_server
import mode


NCOR = 172
NBPM = 173
PSC_ON = 2


@pytest.fixture
def mock_caget():
    mock_caget = mock.MagicMock()
    catools.caget = mock_caget
    sofb.caget = mock_caget
    epics.caget = mock_caget
    return mock_caget


@pytest.fixture
def mock_caput():
    mock_caput = mock.MagicMock()
    catools.caput = mock.MagicMock()
    sofb.caput = mock_caput
    epics.caput = mock_caput
    return mock_caput


@pytest.fixture
def lattice():
    return pytac.load_csv.load('DIAD')


@pytest.fixture
def test_sofb(lattice):
    s = sofb.Sofb(lattice)
    # Assume square matrix
    s.set_rm(numpy.eye(NBPM, NCOR), numpy.eye(NBPM, NCOR))
    s.step_limit = 1e6  # Avoid hitting the limit by default
    s.mu = 0  # Do not use regularisation by default
    return s

@pytest.fixture
def test_mode():
    return mode.RingMode()

@pytest.fixture
def test_sofb_server(test_mode):
    s = sofb_server.SofbServer(test_mode)
    s.sofb.set_rm(numpy.eye(NBPM, NCOR), numpy.eye(NBPM, NCOR))
    s.sofb.step_limit = 1e6  # Avoid hitting the limit by default
    s.sofb.mu = 0  # Do not use regularisation by default
    return s


@pytest.fixture
def caget_responses():
    caget_responses = collections.OrderedDict()
    caget_responses['afrac'] = 1
    caget_responses['bpmen'] = numpy.ones(NBPM)
    caget_responses['hbpmen'] = numpy.zeros(NBPM)
    caget_responses['vbpmen'] = numpy.zeros(NBPM)
    caget_responses['hen'] = numpy.zeros(NCOR)
    caget_responses['ven'] = numpy.zeros(NCOR)
    caget_responses['psc_errors'] = numpy.zeros(NCOR * 2)
    caget_responses['psc_states'] = numpy.full(NCOR * 2, PSC_ON)
    caget_responses['bpmx'] = numpy.zeros(NBPM)
    caget_responses['h_current'] = numpy.zeros(NCOR)
    caget_responses['bpmy'] = numpy.zeros(NBPM)
    caget_responses['v_current'] = numpy.zeros(NCOR)
    return caget_responses


def test_zero_correction(test_sofb, lattice, mock_caput, mock_caget, caget_responses):
    mock_caget.side_effect = caget_responses.values()
    test_sofb.correction()
    h_expected = numpy.zeros(NCOR)
    v_expected = numpy.zeros(NCOR)
    print(mock_caput.call_args_list)
    hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

    numpy.testing.assert_equal(
            lattice.get_pv_names('HSTR', 'b0', pytac.SP),
            hcm_call[0][0]
    )
    numpy.testing.assert_equal(h_expected, hcm_call[0][1])
    numpy.testing.assert_equal(
            lattice.get_pv_names('HSTR', 'a0', pytac.SP),
            vcm_call[0][0]
    )
    numpy.testing.assert_equal(v_expected, vcm_call[0][1])
    assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


@pytest.mark.xfail  # do we want to catch this?
def test_correction_fails_if_wrong_dimensions(test_sofb, mock_caget, mock_caput, caget_responses):
    caget_responses['bpmx'] = numpy.zeros(NBPM + 1)
    mock_caget.side_effect = caget_responses.values()
    with pytest.raises(Exception):
        test_sofb.correction()


def test_random_correction(test_sofb, lattice, mock_caput, mock_caget, caget_responses):
    caget_responses['bpmx'] = numpy.random.rand(NBPM)
    caget_responses['bpmy'] = numpy.random.rand(NBPM)
    mock_caget.side_effect = caget_responses.values()
    test_sofb.correction()
    # Identity matrix RM means output = input
    h_expected = caget_responses['bpmx'][:NCOR]
    v_expected = caget_responses['bpmy'][:NCOR]
    hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

    numpy.testing.assert_equal(
            lattice.get_pv_names('HSTR', 'b0', pytac.SP),
            hcm_call[0][0]
    )
    numpy.testing.assert_equal(h_expected, -hcm_call[0][1])
    numpy.testing.assert_equal(
            lattice.get_pv_names('VSTR', 'a0', pytac.SP),
            vcm_call[0][0]
    )
    numpy.testing.assert_equal(v_expected, -vcm_call[0][1])
    assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)

def test_afrac_correction(test_sofb, lattice, mock_caget, mock_caput, caget_responses):
    caget_responses['bpmx'] = numpy.random.rand(NBPM)
    caget_responses['bpmy'] = numpy.random.rand(NBPM)
    caget_responses['afrac'] = 0.5
    mock_caget.side_effect = caget_responses.values()
    test_sofb.correction()
    # Identity matrix RM means output = input (this time scaled by afrac)
    h_expected = caget_responses['bpmx'][:NCOR] / 2
    v_expected = caget_responses['bpmy'][:NCOR] / 2
    hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

    numpy.testing.assert_equal(
            lattice.get_pv_names('HSTR', 'b0', pytac.SP),
            hcm_call[0][0]
    )
    numpy.testing.assert_equal(h_expected, -hcm_call[0][1])
    numpy.testing.assert_equal(
            lattice.get_pv_names('VSTR', 'a0', pytac.SP),
            vcm_call[0][0]
    )
    numpy.testing.assert_equal(v_expected, -vcm_call[0][1])
    assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


def test_scaled_correction(test_sofb, lattice, mock_caget, mock_caput, caget_responses):
    caget_responses['bpmx'] = numpy.random.rand(NBPM)
    caget_responses['bpmy'] = numpy.random.rand(NBPM)
    # One value is twice the limit.
    test_sofb.step_limit = 10
    caget_responses['bpmx'][10] = 20
    mock_caget.side_effect = caget_responses.values()
    test_sofb.correction()
    # Identity matrix RM means output = input (this time scaled by limit)
    h_expected = caget_responses['bpmx'][:NCOR] / 2
    v_expected = caget_responses['bpmy'][:NCOR]
    hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

    numpy.testing.assert_equal(
            lattice.get_pv_names('HSTR', 'b0', pytac.SP),
            hcm_call[0][0]
    )
    numpy.testing.assert_equal(h_expected, -hcm_call[0][1])
    numpy.testing.assert_equal(
            lattice.get_pv_names('HSTR', 'a0', pytac.SP),
            vcm_call[0][0]
    )
    numpy.testing.assert_equal(v_expected, -vcm_call[0][1])
    assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


def test_psc_error_non_zero_multiple(test_sofb, mock_caget, mock_caput, caget_responses):
    caget_responses['psc_errors'][112] = 8
    caget_responses['psc_errors'][8] = 8
    mock_caget.side_effect = caget_responses.values()
    with pytest.raises(sofb.CalculationException):
        test_sofb.correction()

def test_psc_error_non_zero(test_sofb, mock_caget, mock_caput, caget_responses):
    caget_responses['psc_errors'][112] = 8
    mock_caget.side_effect = caget_responses.values()
    with pytest.raises(sofb.CalculationException):
        test_sofb.correction()

def test_psc_state_not_on_multiple(test_sofb, mock_caget, caget_responses):
    caget_responses['psc_states'][112] = 0
    caget_responses['psc_states'][8] = 8
    mock_caget.side_effect = caget_responses.values()
    with pytest.raises(sofb.CalculationException):
        test_sofb.correction()

def test_psc_state_not_on(test_sofb, mock_caget, mock_caput, caget_responses):
    caget_responses['psc_states'][23] = 0
    mock_caget.side_effect = caget_responses.values()
    with pytest.raises(sofb.CalculationException):
        test_sofb.correction()

def test_calc_error_reset_after_single(test_sofb_server, mock_caget, mock_caput, caget_responses):
    # Previous error state
    test_sofb_server.calc_error.set(1)
    test_sofb_server.pv_error.set("Some error")

    # Single correction
    MEANINGLESS_VALUE = 0
    test_sofb_server.single(MEANINGLESS_VALUE)

    # Errors should have been cleared
    assert test_sofb_server.calc_error.get() == 0
    assert test_sofb_server.pv_error.get() == "OK"
