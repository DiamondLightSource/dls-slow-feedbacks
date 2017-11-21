import sys, os, traceback

import numpy as np
from numpy import linalg
from cothread.catools import caput, caget
import pytac


# PSC Enum constants
PSC_STATE_ON = 2


def tkv_reg(m, mu, singular_values):
    # Tikhonov regularization
    u, s, vt = linalg.svd(m, full_matrices = False)
    # We use nan_to_num here to catch the case of singular m and zero mu.
    si = np.nan_to_num(s / (mu + s**2))

    if singular_values is not None:
        singular_values.s.set(s)
        singular_values.s_inv.set(np.nan_to_num(1 / s))
        singular_values.s_inv_cut.set(si)
        singular_values.length.set(np.count_nonzero(s))
    return np.dot(vt.T * si, u.T)


class SingularValuePVs(object):
    """
    Stores references to PV objects that can be set to provide
    waveforms representing SVD Data.
    """
    def __init__(self):
        # Requires injecting of fields from instantiating class
        self.s = None
        self.s_inv = None
        self.s_inv_cut = None
        self.length = None


class CalculationException(Exception):
    pass


class Sofb(object):

    def __init__(self, lattice):
        self.lattice = lattice
        self.step_limit = 0.1
        self.mu = 0.01
        self.svd = {'X':None, 'Y':None}
        self.cache = {}
        device_names = np.concatenate(
                (lattice.get_device_names('HSTR', 'b0'),
                 lattice.get_device_names('VSTR', 'a0')))
        self.psc_error_names = np.array([d + ':ERCSUM' for d in device_names])
        self.psc_state_names = np.array([d + ':STATE' for d in device_names])

    def set_step_limit(self, step_limit):
        self.step_limit = step_limit

    def set_mu(self, mu):
        self.mu = mu

    def get_irm(self, hen, ven, hbpmen, vbpmen, mu):
        key = (tuple(hen), tuple(ven), tuple(hbpmen), tuple(vbpmen), mu)
        if key in self.cache:
            return self.cache[key]
        print "new response matrix"
        irm = [None, None]
        rmx = self.rmx[np.ix_(hbpmen, hen)]
        rmy = self.rmy[np.ix_(vbpmen, ven)]
        irm = [
            tkv_reg(rmx, mu, self.svd['X']) if rmx.size else np.array([]),
            tkv_reg(rmy, mu, self.svd['Y']) if rmy.size else np.array([])]
        self.cache.clear()
        self.cache[key] = irm
        return irm

    def correction(self):
        afrac = caget("SR-CS-SOFB-01:AFRAC")

        bpmen = np.array(caget(self.lattice.get_pv_names('BPM', 'enabled', pytac.RB)))
        hbpmen = np.logical_and(bpmen, np.array(caget(self.lattice.get_pv_names('BPM', 'x_slow_disabled', pytac.RB))) == 0)
        vbpmen = np.logical_and(bpmen, np.array(caget(self.lattice.get_pv_names('BPM', 'y_slow_disabled', pytac.RB))) == 0)

        hen = np.array(caget(self.lattice.get_pv_names('HSTR', 'h_slow_disabled', pytac.RB))) == 0
        ven = np.array(caget(self.lattice.get_pv_names('VSTR', 'v_slow_disabled', pytac.RB))) == 0

        psc_errors = np.array(
                caget(self.psc_error_names[np.concatenate((hen, ven))]))
        if psc_errors.any():
            error_index = np.nonzero(psc_errors)[0] + 1
            print 'Correctors with ERCSUM nonzero:', error_index
            raise CalculationException(
                    'Corrector {} in error'.format(error_index[0]))

        psc_states = np.array(
                caget(self.psc_state_names[np.concatenate((hen, ven))]))
        if not (psc_states == PSC_STATE_ON).all():
            error_index = np.nonzero(psc_states != PSC_STATE_ON)[0] + 1
            print 'Correctors with state not on:', error_index
            raise CalculationException(
                    'Corrector {} in bad state'.format(error_index[0]))

        # calculate inverse response matrix on demand
        irm = self.get_irm(hen, ven, hbpmen, vbpmen, self.mu)

        bpmx = np.array(caget(self.lattice.get_pv_names('BPM', 'x', pytac.RB)))[hbpmen]
        hcm = np.array(caget(self.lattice.get_pv_names('HSTR', 'b0', pytac.RB)))[hen]

        bpmy = np.array(caget(self.lattice.get_pv_names('BPM', 'y', pytac.RB)))[vbpmen]
        vcm = np.array(caget(self.lattice.get_pv_names('VSTR', 'a0', pytac.RB)))[ven]

        if not irm[0].size == 0:
            hdelta = np.dot(irm[0], bpmx)
            hdelta = hdelta * self.scale(hdelta)
            hstr_pvs = self.lattice.get_pv_names('HSTR', 'b0', pytac.SP)
            caput(hstr_pvs, hcm - hdelta * afrac)

        if not irm[1].size == 0:
            vdelta = np.dot(irm[1], bpmy)
            vdelta = vdelta * self.scale(vdelta)
            vstr_pvs = self.lattice.get_pv_names('VSTR', 'b0', pytac.SP)
            caput(vstr_pvs, vcm - vdelta * afrac)

        caput("CS-CS-MSTAT-01:FBHEART", 10)

    def scale(self, xs):
        "greatest scale factor <= 1.0 such that max(abs(sf * xs)) < step_limit"
        EPS = 1e-9
        max_step = max(abs(xs))
        if max_step > EPS:
            sf = min(1.0, self.step_limit / max_step)
        else:
            sf = 1.0
        return sf
