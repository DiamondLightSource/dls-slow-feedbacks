import numpy as np
from numpy.linalg import pinv

cache: dict = {}


def get_disp_corr(
    enabled_bpm: np.ndarray,
    enabled_cor: np.ndarray,
    bpm_response_matrix: np.ndarray,
    dispersion_matrix: np.ndarray,
) -> np.ndarray:
    "Get the dispersion corrector vector and cache"

    key = (tuple(enabled_bpm), tuple(enabled_cor))
    if key in cache:
        return cache[key]

    # remove data for disabled bpms
    dispersion_matrix = dispersion_matrix[enabled_bpm]
    # rearrange numpy arrays to required format
    rmx = bpm_response_matrix[np.ix_(enabled_bpm, enabled_cor)]
    # calculate correction
    dispersion_correction = np.dot(pinv(rmx), dispersion_matrix)

    cache.clear()
    cache[key] = dispersion_correction

    return dispersion_correction


def calc_rffb(
    bpm_response_matrix: np.ndarray,
    dispersion_matrix: np.ndarray,
    enabled_bpms: np.ndarray,
    enabled_correctors: np.ndarray,
    hcm: np.ndarray,
) -> float:
    "Calculate the RF change"

    dispersion_correction = get_disp_corr(
        enabled_bpms, enabled_correctors, bpm_response_matrix, dispersion_matrix
    )
    delta_rf = np.dot(hcm, dispersion_correction / sum(dispersion_correction**2))
    # TODO: delta_rf should always be a float, but is sometimes a float in a numpy array
    # which we have to get it out of, investigate the root cause of this
    return delta_rf.item()
