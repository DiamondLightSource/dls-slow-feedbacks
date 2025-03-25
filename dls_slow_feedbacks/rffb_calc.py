import numpy as np
from numpy.linalg import pinv

cache: dict = {}


def get_disp_corr(
    enabled_bpm: np.ndarray,
    enabled_cor: np.ndarray,
    bpm_resp: np.ndarray,
    disp: np.ndarray,
) -> np.ndarray:
    "get the dispersion corrector vector and cache"

    key = (tuple(enabled_bpm), tuple(enabled_cor))
    if key in cache:
        return cache[key]

    # disable bpms
    dispx = disp[enabled_bpm]
    rmx = bpm_resp[np.ix_(enabled_bpm, enabled_cor)]

    dispcor = np.dot(pinv(rmx), dispx)

    cache.clear()
    cache[key] = dispcor

    return dispcor


def calc_rffb(
    bpm_resp: np.ndarray,
    disp: np.ndarray,
    enabled_bpm: np.ndarray,
    enabled_cor: np.ndarray,
    hcm: np.ndarray,
) -> float:
    "calculate the RF change"
    # the "inverse" of a vector v is: v / |v|^2
    # same as you get from the svd pinv:
    # pinv([v])[0] = v / sum(v**2)
    dispcor = get_disp_corr(enabled_bpm, enabled_cor, bpm_resp, disp)
    drf = np.dot(hcm, dispcor / sum(dispcor ** 2))
    return drf
