import numpy as np
from numpy.linalg import pinv

cache: dict = {}


def get_dispcor(enabled_bpm, enabled_cor, bpmresp, disp):
    "get the dispersion corrector vector and cache"

    key = (tuple(enabled_bpm), tuple(enabled_cor))
    if key in cache:
        return cache[key]

    dispx = disp
    rmx = bpmresp

    # disable bpms
    dispx = dispx[enabled_bpm]
    rmx = rmx[np.ix_(enabled_bpm, enabled_cor)]

    dispcor = np.dot(pinv(rmx), dispx)

    cache.clear()
    cache[key] = dispcor

    return dispcor


def calc_rffb(bpmresp, disp, enabled_bpm, enabled_cor, hcm):
    "calculate the RF change"
    dispcor = get_dispcor(enabled_bpm, enabled_cor, bpmresp, disp)
    # the "inverse" of a vector v is: v / |v|^2
    # same as you get from the svd pinv:
    # pinv([v])[0] = v / sum(v**2)
    drf = np.dot(hcm, dispcor / sum(dispcor ** 2))
    return drf
