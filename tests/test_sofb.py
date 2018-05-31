import sys
import os
import pkg_resources
pkg_resources.require('cothread')
pkg_resources.require('mock')
import numpy
import inspect
import mock
import collections

try:
    import pytest
except ImportError:
    print('Usage: py.test {}'.format(sys.argv[0]))
    sys.exit()

sys.path.append('../python')

import sofb
import mml


NCOR = 172
NBPM = 173
PSC_ON = 2


# Patch caget
sofb.caget = mock.MagicMock()


@pytest.fixture
def test_sofb():
    s = sofb.Sofb()
    # Assume square matrix
    s.rmx = numpy.eye(NBPM, NCOR)
    s.rmy = numpy.eye(NBPM, NCOR)
    s.step_limit = 1e6  # Avoid hitting the limit by default
    s.mu = 0  # Do not use regularisation by default
    return s


@pytest.fixture
def caget_responses():
    caget_responses = collections.OrderedDict()
    caget_responses['afrac'] = 1
    caget_responses['hen'] = numpy.zeros(NCOR)
    caget_responses['ven'] = numpy.zeros(NCOR)
    caget_responses['bpmen'] = numpy.zeros(NBPM)
    caget_responses['hbpmen'] = numpy.zeros(NBPM)
    caget_responses['vbpmen'] = numpy.zeros(NBPM)
    caget_responses['psc_errors'] = numpy.zeros(NCOR * 2)
    caget_responses['psc_states'] = numpy.full(NCOR * 2, PSC_ON)
    caget_responses['bpmx'] = numpy.zeros(NBPM)
    caget_responses['h_current'] = numpy.zeros(NCOR)
    caget_responses['bpmy'] = numpy.zeros(NBPM)
    caget_responses['v_current'] = numpy.zeros(NCOR)
    return caget_responses


def test_zero_correction(test_sofb, caget_responses):
    sofb.caget.side_effect = caget_responses.values()
    with mock.patch('sofb.caput') as mock_caput:
        test_sofb.correction()
        h_expected = numpy.zeros(NCOR)
        v_expected = numpy.zeros(NCOR)
        hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

        numpy.testing.assert_equal(mml.ao['hcm'].setpoint, hcm_call[0][0])
        numpy.testing.assert_equal(h_expected, hcm_call[0][1])
        numpy.testing.assert_equal(mml.ao['vcm'].setpoint, vcm_call[0][0])
        numpy.testing.assert_equal(v_expected, vcm_call[0][1])
        assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


@pytest.mark.xfail  # do we want to catch this?
def test_correction_fails_if_wrong_dimensions(test_sofb, caget_responses):
    caget_responses['bpmx'] = numpy.zeros(NBPM + 1)
    sofb.caget.side_effect = caget_responses.values()
    with mock.patch('sofb.caput'):
        with pytest.raises(Exception):
            test_sofb.correction()


def test_random_correction(test_sofb, caget_responses):
    caget_responses['bpmx'] = numpy.random.rand(NBPM)
    caget_responses['bpmy'] = numpy.random.rand(NBPM)
    sofb.caget.side_effect = caget_responses.values()
    with mock.patch('sofb.caput') as mock_caput:
        test_sofb.correction()
        # Identity matrix RM means output = input
        h_expected = caget_responses['bpmx'][:NCOR]
        v_expected = caget_responses['bpmy'][:NCOR]
        hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

        numpy.testing.assert_equal(mml.ao['hcm'].setpoint, hcm_call[0][0])
        numpy.testing.assert_equal(h_expected, -hcm_call[0][1])
        numpy.testing.assert_equal(mml.ao['vcm'].setpoint, vcm_call[0][0])
        numpy.testing.assert_equal(v_expected, -vcm_call[0][1])
        assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


def test_afrac_correction(test_sofb, caget_responses):
    caget_responses['bpmx'] = numpy.random.rand(NBPM)
    caget_responses['bpmy'] = numpy.random.rand(NBPM)
    caget_responses['afrac'] = 0.5
    sofb.caget.side_effect = caget_responses.values()
    with mock.patch('sofb.caput') as mock_caput:
        test_sofb.correction()
        # Identity matrix RM means output = input (this time scaled by afrac)
        h_expected = caget_responses['bpmx'][:NCOR] / 2
        v_expected = caget_responses['bpmy'][:NCOR] / 2
        hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

        numpy.testing.assert_equal(mml.ao['hcm'].setpoint, hcm_call[0][0])
        numpy.testing.assert_equal(h_expected, -hcm_call[0][1])
        numpy.testing.assert_equal(mml.ao['vcm'].setpoint, vcm_call[0][0])
        numpy.testing.assert_equal(v_expected, -vcm_call[0][1])
        assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


def test_scaled_correction(test_sofb, caget_responses):
    caget_responses['bpmx'] = numpy.random.rand(NBPM)
    caget_responses['bpmy'] = numpy.random.rand(NBPM)
    # One value is twice the limit.
    test_sofb.step_limit = 10
    caget_responses['bpmx'][10] = 20
    sofb.caget.side_effect = caget_responses.values()
    with mock.patch('sofb.caput') as mock_caput:
        test_sofb.correction()
        # Identity matrix RM means output = input (this time scaled by limit)
        h_expected = caget_responses['bpmx'][:NCOR] / 2
        v_expected = caget_responses['bpmy'][:NCOR]
        hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

        numpy.testing.assert_equal(mml.ao['hcm'].setpoint, hcm_call[0][0])
        numpy.testing.assert_equal(h_expected, -hcm_call[0][1])
        numpy.testing.assert_equal(mml.ao['vcm'].setpoint, vcm_call[0][0])
        numpy.testing.assert_equal(v_expected, -vcm_call[0][1])
        assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


def test_psc_error_non_zero(test_sofb, caget_responses):
    caget_responses['psc_errors'][112] = 8
    sofb.caget.side_effect = caget_responses.values()
    with mock.patch('sofb.caput') as mock_caput:
        with pytest.raises(sofb.CalculationException):
            test_sofb.correction()


def test_psc_state_not_on(test_sofb, caget_responses):
    caget_responses['psc_states'][23] = 0
    sofb.caget.side_effect = caget_responses.values()
    with mock.patch('sofb.caput') as mock_caput:
        with pytest.raises(sofb.CalculationException):
            test_sofb.correction()
