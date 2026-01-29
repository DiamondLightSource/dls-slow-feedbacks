import logging

import numpy as np
import pytac
from cothread.catools import caget, caput
from pytac.lattice import EpicsLattice

logger = logging.getLogger(name="dls_slow_feedbacks")

# Used to stop from dividing by zero when calculating correction scaling
MIN_SF_CORRECTION_STEP = 1e-9
# PSC Enum constant
PSC_STATE_ON = 2


class SingularValuePVs:
    """Stores references to PV objects that can be set to provide
    waveforms representing SVD Data."""

    def __init__(self) -> None:
        # Requires injecting of fields from instantiating class
        self.s = None
        self.s_inv = None
        self.s_inv_cut = None
        self.length = None


def tkv_reg(m: np.ndarray, mu: float, singular_values: SingularValuePVs) -> np.ndarray:
    """Tikhonov regularization of a matrix, m."""
    u, s, vt = np.linalg.svd(m, full_matrices=False)
    # We use nan_to_num here to catch the case of singular m and zero mu.
    si = np.nan_to_num(s / (mu + s**2))

    if singular_values is not None:
        singular_values.s.set(s)
        singular_values.s_inv.set(np.nan_to_num(1 / s))
        singular_values.s_inv_cut.set(si)
        singular_values.length.set(np.count_nonzero(s))
    return np.dot(vt.T * si, u.T)


class CalculationError(Exception):
    pass


class Sofb:
    def __init__(self, lattice: EpicsLattice) -> None:
        self.set_lattice(lattice)
        self.step_limit: float = 0.1
        self.mu: float = 0.01
        self.svd_pvs: dict = {"X": None, "Y": None}
        self.cache: dict = {}
        self.rm_x: np.ndarray | None = None
        self.rm_y: np.ndarray | None = None

    def set_lattice(self, lattice: EpicsLattice) -> None:
        """Set the lattice and extract the psc names."""
        self.lattice = lattice
        device_names = np.concatenate(
            (
                lattice.get_element_device_names("HSTR", "x_kick"),
                lattice.get_element_device_names("VSTR", "y_kick"),
            )
        )
        self.psc_error_names = np.array([d + ":ERCSUM" for d in device_names])
        self.psc_state_names = np.array([d + ":STATE" for d in device_names])

    def set_rm(self, rm_x: np.ndarray | None, rm_y: np.ndarray | None) -> None:
        """Set the response matrices."""
        self.rm_x = rm_x
        self.rm_y = rm_y

    def set_step_limit(self, step_limit: float) -> None:
        """Set the step limit for the correction."""
        self.step_limit = step_limit

    def set_mu(self, mu: float) -> None:
        """Set the mu value for the correction."""
        self.mu = mu

    def get_irm(
        self,
        h_enable: np.ndarray,
        v_enable: np.ndarray,
        h_bpm_enable: np.ndarray,
        v_bpm_enable: np.ndarray,
        mu: float,
    ) -> list[np.ndarray]:
        """Calculate the inverse response matrix for the given correctors and BPMs."""
        key = (
            tuple(h_enable),
            tuple(v_enable),
            tuple(h_bpm_enable),
            tuple(v_bpm_enable),
            mu,
        )
        if key in self.cache:
            return self.cache[key]
        logger.info("New response matrix")
        irm: list[np.ndarray] = [np.array([]), np.array([])]

        if self.rm_x is None or self.rm_y is None:
            raise CalculationError("Response matrices not set.")
        else:
            rm_x = self.rm_x[np.ix_(h_bpm_enable, h_enable)]
            rm_y = self.rm_y[np.ix_(v_bpm_enable, v_enable)]
            irm = [
                tkv_reg(rm_x, mu, self.svd_pvs["X"]) if rm_x.size else np.array([]),
                tkv_reg(rm_y, mu, self.svd_pvs["Y"]) if rm_y.size else np.array([]),
            ]
            self.cache.clear()
            self.cache[key] = irm
        return irm

    def report_corrector_error(
        self,
        array_of_pv_names: np.ndarray,
        error_indices: np.ndarray,
        error_description: str,
    ) -> None:
        """Log corrector error and raise CalculationError exception"""
        error_pvs = array_of_pv_names[error_indices]
        # Message to be printed to the console can contain the whole
        # list and reason because not limited on space
        logger.error(f"Correctors {error_description}: {error_pvs}")

        # If more than one PV in list, show how many more.
        more_to_show = f" +{len(error_pvs) - 1}" if len(error_pvs) > 1 else ""

        # This message goes into the error PV so we keep it short
        exception_message = f"{error_pvs[0]}{more_to_show} {error_description}"
        raise CalculationError(exception_message)

    def apply_correction(self) -> None:
        """Do final calculation and apply correction to PVs"""
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
        bpms_x_values = self.lattice.get_element_values(
            "BPM", "x", pytac.RB, dtype=np.float64
        )[bpms_x_enabled]
        correctors_x_values = self.lattice.get_element_values(
            "HSTR", "x_kick", pytac.RB, dtype=np.float64
        )[correctors_x_enabled]

        bpms_y_values = self.lattice.get_element_values(
            "BPM", "y", pytac.RB, dtype=np.float64
        )[bpms_y_enabled]
        correctors_y_values = self.lattice.get_element_values(
            "VSTR", "y_kick", pytac.RB, dtype=np.float64
        )[correctors_y_enabled]

        # Calculate horizontal corrections
        if not irm[0].size == 0:
            # Array of deltas for each x corrector
            hdelta = np.dot(irm[0], bpms_x_values)

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
            vdelta = np.dot(irm[1], bpms_y_values)

            # Scale deltas so that largest < step_limit
            vdelta = vdelta * self.correction_scale_factor(vdelta)
            vstr_pvs = np.array(
                self.lattice.get_element_pv_names("VSTR", "y_kick", pytac.SP)
            )[correctors_y_enabled]
            # Apply
            caput(vstr_pvs, correctors_y_values - vdelta * afrac)

        caput("CS-CS-MSTAT-01:FBHEART", 10)

    def correction_scale_factor(self, unscaled_steps: np.ndarray) -> float:
        """Calculate the scale factor <= 1.0 to be applied to all
        steps, so that all are within the limit for maximum step.

        The scale factor calculated is the largest which satisfies:
        max(abs(scale_factor * unscaled_steps)) < step_limit
        """
        largest_step = max(abs(unscaled_steps))
        if largest_step > MIN_SF_CORRECTION_STEP:
            scale_factor = min(1.0, self.step_limit / largest_step)
        else:
            scale_factor = 1.0
        return scale_factor
