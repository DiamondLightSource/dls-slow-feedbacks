import sys, os

from scipy.io.matlab import *
from numpy import *
from numpy.linalg import svd, pinv
from cothread.catools import *

cache = {}

def get_dispcor(enabled_bpm, enabled_cor, bpmresp, disp, rad_over_A):
    "get the dispersion corrector vector and cache"

    key = (tuple(enabled_bpm), tuple(enabled_cor))
    if key in cache:
        return cache[key]

    dispx = disp["BPMxDisp"]["Data"][0,0]
    rmx = bpmresp["Rmat"][0,0]["Data"]

    # disable bpms
    dispx = dispx[enabled_bpm]
    rmx = rmx[ix_(enabled_bpm, enabled_cor)] / rad_over_A[enabled_cor]

    dispcor = dot(pinv(rmx), dispx)

    cache.clear()
    cache[key] = dispcor

    return dispcor

def calc_rffb(bpmresp, disp, enabled_bpm, enabled_cor, hcm, rad_over_A):
    "calculate the RF change"
    dispcor = get_dispcor(enabled_bpm, enabled_cor, bpmresp, disp, rad_over_A)
    # the "inverse" of a vector v is: v / |v|^2
    # same as you get from the svd pinv:
    # pinv([v])[0] = v / sum(v**2)
    drf = dot(hcm * rad_over_A[enabled_cor], dispcor / sum(dispcor**2))
    return drf
