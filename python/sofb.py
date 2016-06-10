import sys, os, traceback

from numpy import *
from numpy.linalg import *
from cothread.catools import *
from cothread import Spawn, Sleep, WaitForQuit
import mml


def tkv_reg(m, mu, singular_values):
    # Tikhonov regularization
    u, s, vt = svd(m, full_matrices = False)
    # We use nan_to_num here to catch the case of singular m and zero mu.
    si = nan_to_num(s / (mu + s**2))

    singular_values.s.set(s)
    singular_values.s_inv.set(nan_to_num(1 / s))
    singular_values.s_inv_cut.set(si)
    singular_values.length.set(count_nonzero(s))
    return dot(vt.T * si, u.T)


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


class sofb(object):

    def __init__(self):
        self.step_limit = 0.1
        self.mu = 0.01
        self.svd = {'X':SingularValuePVs(), 'Y':SingularValuePVs()}
        self.cache = {}

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
        rmx = self.rmx[ix_(hbpmen, hen)]
        rmy = self.rmy[ix_(vbpmen, ven)]
        irm = [
            tkv_reg(rmx, mu, self.svd['X']),
            tkv_reg(rmy, mu, self.svd['Y'])]
        self.cache.clear()
        self.cache[key] = irm
        return irm

    def tick(self):
        while True:
            Sleep(1.0)
            try:
                self.correction()
            except:
                traceback.print_exc()

    def correction(self):

        # calculate inverse response matrix on demand

        afrac = caget("SR-CS-SOFB-01:AFRAC")
        hen = caget("SR-PC-HSTR-01:SLOW:ENABLED") == 0
        ven = caget("SR-PC-VSTR-01:SLOW:ENABLED") == 0

        bpmen = caget("SR-DI-EBPM-01:ENABLED") == 0
        hbpmen = logical_and(bpmen, caget("SR-PC-HBPM-01:SLOW:ENABLED") == 0)
        vbpmen = logical_and(bpmen, caget("SR-PC-VBPM-01:SLOW:ENABLED") == 0)

        irm = self.get_irm(hen, ven, hbpmen, vbpmen, self.mu)

        bpmx = caget(mml.ao["bpmx"].readback)[bpmen]
        hcm = caget(mml.ao["hcm"].setpoint[hen])

        bpmy = caget(mml.ao["bpmy"].readback)[bpmen]
        vcm = caget(mml.ao["vcm"].setpoint[ven])

        hdelta = dot(irm[0], bpmx)
        hdelta = hdelta * self.scale(hdelta)

        vdelta = dot(irm[1], bpmy)
        vdelta = vdelta * self.scale(vdelta)

        caput(mml.ao["hcm"].setpoint[hen], hcm - hdelta * afrac)
        caput(mml.ao["vcm"].setpoint[ven], vcm - vdelta * afrac)
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
