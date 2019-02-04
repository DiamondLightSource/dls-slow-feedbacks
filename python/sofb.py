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
        self.set_lattice(lattice)
        self.step_limit = 0.1
        self.mu = 0.01
        self.svd = {'X':None, 'Y':None}
        self.cache = {}

    def set_lattice(self, lattice):
        self.lattice = lattice
        device_names = np.concatenate(
                (lattice.get_device_names('HSTR', 'b0'),
                 lattice.get_device_names('VSTR', 'a0')))
        self.psc_error_names = np.array([d + ':ERCSUM' for d in device_names])
        self.psc_state_names = np.array([d + ':STATE' for d in device_names])

    def set_rm(self, rmx, rmy):
        self.rmx = rmx
        self.rmy = rmy

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

    def report_corrector_error(self,
                               array_of_pv_names,
                               error_indices,
                               error_description):
        error_pvs = array_of_pv_names[error_indices]
        # Message to be printed to the console can contain the whole
        # list and reason because no limited on space
        print ('Correctors {}: {}'.format(error_description,
                                          error_pvs))

        # This message goes into the error PV so we keep it short
        more_to_show=""
        if len(error_pvs) > 1:
            more_to_show=", ..."

        exception_message = "{}{}".format(error_pvs[0], more_to_show)
        raise CalculationException(exception_message)

    def correction(self):
        # Correction is scaled by this fraction <= 1
        afrac = caget("SR-CS-SOFB-01:AFRAC")

        bpmen = self.lattice.get_values('BPM',
                                        'enabled',
                                        pytac.RB,
                                        dtype=np.bool_)
        hbpmen = np.logical_and(bpmen,
                                self.lattice.get_values('BPM',
                                                        'x_sofb_disabled',
                                                        pytac.RB,
                                                        dtype=np.bool_) == 0)
        vbpmen = np.logical_and(bpmen,
                                self.lattice.get_values('BPM',
                                                        'y_sofb_disabled',
                                                        pytac.RB,
                                                        dtype=np.bool_) == 0)

        hen = self.lattice.get_values('HSTR',
                                      'h_sofb_disabled',
                                      pytac.RB,
                                      dtype=np.bool_) == 0
        ven = self.lattice.get_values('VSTR',
                                      'v_sofb_disabled',
                                      pytac.RB,
                                      dtype=np.bool_) == 0

        array_of_error_pv_names = self.psc_error_names[np.concatenate((hen, ven))]
        psc_errors = np.array(
                caget(array_of_error_pv_names))
        if psc_errors.any():
            error_indices = np.nonzero(psc_errors)[0]
            self.report_corrector_error(array_of_error_pv_names,
                                        error_indices,
                                        "with ERCSUM nonzero")

        array_of_psc_state_pv_names = self.psc_state_names[np.concatenate((hen, ven))]
        psc_states = np.array(
                caget(array_of_psc_state_pv_names))
        if not (psc_states == PSC_STATE_ON).all():
            error_indices = np.nonzero(psc_states != PSC_STATE_ON)[0]
            self.report_corrector_error(array_of_psc_state_pv_names,
                                        error_indices,
                                        "not ON")

        # calculate inverse response matrix on demand
        irm = self.get_irm(hen, ven, hbpmen, vbpmen, self.mu)

        bpmx = self.lattice.get_values('BPM', 'x', pytac.RB, dtype=np.float64)[hbpmen]
        hcm = self.lattice.get_values('HSTR', 'b0', pytac.RB, dtype=np.float64)[hen]

        bpmy = self.lattice.get_values('BPM', 'y', pytac.RB, dtype=np.float64)[vbpmen]
        vcm = self.lattice.get_values('VSTR', 'a0', pytac.RB, dtype=np.float64)[ven]

        if not irm[0].size == 0:
            hdelta = np.dot(irm[0], bpmx)
            hdelta = hdelta * self.scale(hdelta)
            hstr_pvs = np.array(self.lattice.get_pv_names('HSTR', 'b0', pytac.SP))[hen]
            caput(hstr_pvs, hcm - hdelta * afrac)

        if not irm[1].size == 0:
            vdelta = np.dot(irm[1], bpmy)
            vdelta = vdelta * self.scale(vdelta)
            vstr_pvs = np.array(self.lattice.get_pv_names('VSTR', 'a0', pytac.SP))[ven]
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
