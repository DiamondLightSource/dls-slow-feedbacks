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


NCOR = 173
NBPM = 173


@pytest.fixture
def setup_sofb():
    s = sofb.sofb()
    # Assume square matrix
    s.rmx = numpy.eye(NBPM, NCOR)
    s.rmy = numpy.eye(NBPM, NCOR)
    s.step_limit = 1e6  # Avoid hitting the limit by default
    s.mu = 0  # Do not use regularisation by default
    sofb.caget = mock.MagicMock()
    default_params = collections.OrderedDict()
    default_params['afrac'] = 1
    default_params['hen'] = numpy.zeros(NCOR)
    default_params['ven'] = numpy.zeros(NCOR)
    default_params['bpmen'] = numpy.zeros(NBPM)
    default_params['hbpmen'] = numpy.zeros(NBPM)
    default_params['vbpmen'] = numpy.zeros(NBPM)
    default_params['bpmx'] = numpy.zeros(NBPM)
    default_params['h_current'] = numpy.zeros(NCOR)
    default_params['bpmy'] = numpy.zeros(NBPM)
    default_params['v_current'] = numpy.zeros(NCOR)
    return s, default_params


def test_zero_correction(setup_sofb):
    s, params = setup_sofb
    sofb.caget.side_effect = params.values()
    with mock.patch('sofb.caput') as mock_caput:
        s.correction()
        h_expected = numpy.zeros(NCOR)
        v_expected = numpy.zeros(NCOR)
        hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

        numpy.testing.assert_equal(mml.ao['hcm'].setpoint, hcm_call[0][0])
        numpy.testing.assert_equal(h_expected, hcm_call[0][1])
        numpy.testing.assert_equal(mml.ao['vcm'].setpoint, vcm_call[0][0])
        numpy.testing.assert_equal(v_expected, vcm_call[0][1])
        assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


@pytest.mark.xfail  # do we want to catch this?
def test_correction_fails_if_wrong_dimensions(setup_sofb):
    s, params = setup_sofb
    params['bpmx'] = numpy.zeros(NBPM + 1)
    sofb.caget.side_effect = params.values()
    with mock.patch('sofb.caput'):
        with pytest.raises(Exception):
            s.correction()


def test_random_correction(setup_sofb):
    s, params = setup_sofb
    params['bpmx'] = numpy.random.rand(NBPM)
    params['bpmy'] = numpy.random.rand(NBPM)
    sofb.caget.side_effect = params.values()
    with mock.patch('sofb.caput') as mock_caput:
        s.correction()
        # Identity matrix RM means output = input
        h_expected = params['bpmx'][:NCOR]
        v_expected = params['bpmy'][:NCOR]
        hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

        numpy.testing.assert_equal(mml.ao['hcm'].setpoint, hcm_call[0][0])
        numpy.testing.assert_equal(h_expected, -hcm_call[0][1])
        numpy.testing.assert_equal(mml.ao['vcm'].setpoint, vcm_call[0][0])
        numpy.testing.assert_equal(v_expected, -vcm_call[0][1])
        assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


def test_afrac_correction(setup_sofb):
    s, params = setup_sofb
    params['bpmx'] = numpy.random.rand(NBPM)
    params['bpmy'] = numpy.random.rand(NBPM)
    params['afrac'] = 0.5
    sofb.caget.side_effect = params.values()
    with mock.patch('sofb.caput') as mock_caput:
        s.correction()
        # Identity matrix RM means output = input (this time scaled by afrac)
        h_expected = params['bpmx'][:NCOR] / 2
        v_expected = params['bpmy'][:NCOR] / 2
        hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

        numpy.testing.assert_equal(mml.ao['hcm'].setpoint, hcm_call[0][0])
        numpy.testing.assert_equal(h_expected, -hcm_call[0][1])
        numpy.testing.assert_equal(mml.ao['vcm'].setpoint, vcm_call[0][0])
        numpy.testing.assert_equal(v_expected, -vcm_call[0][1])
        assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)


def test_scaled_correction(setup_sofb):
    s, params = setup_sofb
    params['bpmx'] = numpy.random.rand(NBPM)
    params['bpmy'] = numpy.random.rand(NBPM)
    # One value is twice the limit.
    s.step_limit = 10
    params['bpmx'][10] = 20
    sofb.caget.side_effect = params.values()
    with mock.patch('sofb.caput') as mock_caput:
        s.correction()
        # Identity matrix RM means output = input (this time scaled by limit)
        h_expected = params['bpmx'][:NCOR] / 2
        v_expected = params['bpmy'][:NCOR]
        hcm_call, vcm_call, heartbeat_call = mock_caput.call_args_list

        numpy.testing.assert_equal(mml.ao['hcm'].setpoint, hcm_call[0][0])
        numpy.testing.assert_equal(h_expected, -hcm_call[0][1])
        numpy.testing.assert_equal(mml.ao['vcm'].setpoint, vcm_call[0][0])
        numpy.testing.assert_equal(v_expected, -vcm_call[0][1])
        assert heartbeat_call == mock.call('CS-CS-MSTAT-01:FBHEART', 10)

