import logging

import numpy as np
import pytac
from cothread.catools import caget, caput
from numpy import linalg

# PSC Enum constants
PSC_STATE_ON = 2

logger = logging.getLogger(name="dls_slow_feedbacks")

def tkv_reg(m, mu, singular_values):
    # Tikhonov regularization
    u, s, vt = linalg.svd(m, full_matrices=False)
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
        self.svd = {"X": None, "Y": None}
        self.cache = {}

    def set_lattice(self, lattice):
        self.lattice = lattice
        device_names = np.concatenate(
            (
                lattice.get_element_device_names("HSTR", "x_kick"),
                lattice.get_element_device_names("VSTR", "y_kick"),
            )
        )
        self.psc_error_names = np.array([d + ":ERCSUM" for d in device_names])
        self.psc_state_names = np.array([d + ":STATE" for d in device_names])

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
        logger.info("(SOFB) New response matrix")
        irm = [None, None]
        rmx = self.rmx[np.ix_(hbpmen, hen)]
        rmy = self.rmy[np.ix_(vbpmen, ven)]
        irm = [
            tkv_reg(rmx, mu, self.svd["X"]) if rmx.size else np.array([]),
            tkv_reg(rmy, mu, self.svd["Y"]) if rmy.size else np.array([]),
        ]
        self.cache.clear()
        self.cache[key] = irm
        return irm

    def report_corrector_error(
        self, array_of_pv_names, error_indices, error_description
    ):
        error_pvs = array_of_pv_names[error_indices]
        # Message to be printed to the console can contain the whole
        # list and reason because not limited on space
        logger.error(f"(SOFB) Correctors {error_description}: {error_pvs}")

        # If more than one PV in list, show how many more.
        more_to_show = " +{}".format(len(error_pvs) - 1) if len(error_pvs) > 1 else ""

        # This message goes into the error PV so we keep it short
        exception_message = "{}{} {}".format(
            error_pvs[0],
            more_to_show,
            error_description,
        )
        raise CalculationException(exception_message)

    def correction(self):
        # Correction is scaled by this fraction <= 1
        afrac = caget("SR-CS-SOFB-01:AFRAC")

        all_enabled_bpms = self.lattice.get_element_values(
            "BPM", "enabled", pytac.RB, dtype=np.bool_
        )
        bpms_x_enabled = np.logical_and(
            all_enabled_bpms,
            self.lattice.get_element_values(
                "BPM", "x_sofb_disabled", pytac.RB, dtype=np.bool_
            )
            == 0,
        )
        bpms_y_enabled = np.logical_and(
            all_enabled_bpms,
            self.lattice.get_element_values(
                "BPM", "y_sofb_disabled", pytac.RB, dtype=np.bool_
            )
            == 0,
        )
        correctors_x_enabled = (
            self.lattice.get_element_values(
                "HSTR", "h_sofb_disabled", pytac.RB, dtype=np.bool_
            )
            == 0
        )
        correctors_y_enabled = (
            self.lattice.get_element_values(
                "VSTR", "v_sofb_disabled", pytac.RB, dtype=np.bool_
            )
            == 0
        )

        # Check for any correctors with nonzero error count
        array_of_error_pv_names = self.psc_error_names[
            np.concatenate((correctors_x_enabled, correctors_y_enabled))
        ]
        psc_errors = np.array(caget(array_of_error_pv_names))
        if psc_errors.any():
            error_indices = np.nonzero(psc_errors)[0]
            self.report_corrector_error(
                array_of_error_pv_names, error_indices, "with errors"
            )

        # Check for any correctors with STATE not ON
        array_of_psc_state_pv_names = self.psc_state_names[
            np.concatenate((correctors_x_enabled, correctors_y_enabled))
        ]
        psc_states = np.array(caget(array_of_psc_state_pv_names))
        if not (psc_states == PSC_STATE_ON).all():
            error_indices = np.nonzero(psc_states != PSC_STATE_ON)[0]
            self.report_corrector_error(
                array_of_psc_state_pv_names, error_indices, "not ON"
            )

        # calculate inverse response matrix on demand
        irm = self.get_irm(
            correctors_x_enabled,
            correctors_y_enabled,
            bpms_x_enabled,
            bpms_y_enabled,
            self.mu,
        )

        # Get the values required to calculate corrections
        BPMs_x_values = self.lattice.get_element_values(
            "BPM", "x", pytac.RB, dtype=np.float64
        )[bpms_x_enabled]
        correctors_x_values = self.lattice.get_element_values(
            "HSTR", "x_kick", pytac.RB, dtype=np.float64
        )[correctors_x_enabled]

        BPMs_y_values = self.lattice.get_element_values(
            "BPM", "y", pytac.RB, dtype=np.float64
        )[bpms_y_enabled]
        correctors_y_values = self.lattice.get_element_values(
            "VSTR", "y_kick", pytac.RB, dtype=np.float64
        )[correctors_y_enabled]

        # Calculate horizontal corrections
        if not irm[0].size == 0:
            # Array of deltas for each x corrector
            hdelta = np.dot(irm[0], BPMs_x_values)

            # Scale deltas so that largest < step_limit
            hdelta = hdelta * self.correction_scale_factor(hdelta)
            hstr_pvs = np.array(
                self.lattice.get_element_pv_names("HSTR", "x_kick", pytac.SP)
            )[correctors_x_enabled]
            # Apply
            caput(hstr_pvs, correctors_x_values - hdelta * afrac)

        # Calculate vertical corrections
        if not irm[1].size == 0:
            # Array of deltas for each y corrector
            vdelta = np.dot(irm[1], BPMs_y_values)

            # Scale deltas so that largest < step_limit
            vdelta = vdelta * self.correction_scale_factor(vdelta)
            vstr_pvs = np.array(
                self.lattice.get_element_pv_names("VSTR", "y_kick", pytac.SP)
            )[correctors_y_enabled]
            # Apply
            caput(vstr_pvs, correctors_y_values - vdelta * afrac)

        caput("CS-CS-MSTAT-01:FBHEART", 10)

    def correction_scale_factor(self, unscaled_steps):
        """Calculate the scale factor <= 1.0 to be applied to all
        steps, so that all are within the limit for maximum step.

        The factor scale factor calculated is the largest which satisfies:
        max(abs(scale_factor * unscaled_steps)) < step_limit
        """
        EPS = 1e-9
        largest_step = max(abs(unscaled_steps))
        if largest_step > EPS:
            scale_factor = min(1.0, self.step_limit / largest_step)
        else:
            scale_factor = 1.0
        return scale_factor
