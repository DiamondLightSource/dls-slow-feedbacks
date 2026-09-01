import logging
import traceback
from pathlib import Path

import cothread
import numpy as np
from cothread.catools import ca_nothing, caget
from pytac.lattice import EpicsLattice
from scipy.io import loadmat
from softioc import builder

from dls_slow_feedbacks import mode, sofb

logger = logging.getLogger(name="dls_slow_feedbacks")

CURRENT_THRESHOLD = 2.0  # mA


class SofbServer:
    def __init__(self, ring_mode: mode.RingMode) -> None:
        self.power: int = 0  # ON=1/OFF=0
        self.sofb: sofb.Sofb = sofb.Sofb(ring_mode.lattice)
        self.create_records(ring_mode.lattice)
        ring_mode.add_listener(self.set_data_dir)

    def set_data_dir(self, lattice: EpicsLattice, dataroot: Path) -> None:
        """Load the BPM response matrix."""
        self.sofb.cache.clear()
        path = dataroot / lattice.name
        self.sofb.set_lattice(lattice)

        try:
            rm_path = path / "GoldenBPMResp.mat"
            bpm_resp = loadmat(rm_path)
            if bpm_resp["Rmat"][0, 0]["Units"] != "Hardware":
                raise ValueError("BPM response matrix is not set to hardware units")

            rm_x = bpm_resp["Rmat"][0, 0]["Data"]
            rm_y = bpm_resp["Rmat"][1, 1]["Data"]
            self.sofb.set_rm(rm_x, rm_y)
            self.matrix_error.set(0)
            logger.info(f"Sofb loading {lattice.name}")
        except BaseException:
            logger.exception(f"Failed to load matrix data {lattice.name}")
            self.sofb.rm_x = None
            self.sofb.rm_y = None
            self.matrix_error.set(1)

    def start(self) -> None:
        """Start the feedback loop."""
        cothread.Spawn(self.run)

    def run(self) -> None:
        """Main feedback loop."""
        logger.info("Sofb started")
        while True:
            cothread.Sleep(1.0)
            try:
                if self.power:
                    self.perform_correction()
            except Exception as e:
                self.handle_exception(e)

    def perform_correction(self) -> None:
        """Safely perform the slow orbit feedback correction"""
        current = caget("SR-DI-DCCT-01:SIGNAL")
        if current > CURRENT_THRESHOLD:
            self.sofb.apply_correction()
            self.calc_error.set(0)
            self.pv_error.set("OK")
        else:
            self.power_pv.set(0)
            self.calc_error.set(1)

    def handle_exception(self, exception: Exception) -> None:
        """Handle exceptions raised during the feedback loop."""
        self.calc_error.set(1)
        self.power_pv.set(0)

        if isinstance(exception, sofb.CalculationError):
            self.pv_error.set(str(exception))
        elif isinstance(exception, ca_nothing):
            self.pv_error.set(exception.name)
        else:
            self.pv_error.set("An unexpected error occurred")

        traceback.print_exc()

    def run_single(self, value: int) -> None:
        """Run a single correction."""
        try:
            self.sofb.apply_correction()
            self.calc_error.set(0)
            self.pv_error.set("OK")
        except Exception as e:
            self.handle_exception(e)

    def set_power(self, power: int) -> None:
        """Turn the feedback loop on or off."""
        self.power = power

    def get_corrector_magnet_ids(self, lattice: EpicsLattice) -> list[float]:
        """Get the corrector magnet IDs."""
        mag_ids = []
        for mag in lattice.get_element_device_names("HSTR", "x_kick"):
            if mag[4] == "S":
                mag_ids.append(int(mag[2:4]) + 0.1 * (int(mag[-2:]) - 2))
            elif mag[10:14] == "SCOR":
                mag_ids.append(int(mag[2:4]) + 0.5 + (2.0 / 30) * (int(mag[-2:])))
            else:
                mag_ids.append(int(mag[2:4]) + 0.1 * int(mag[-2:]))
        return mag_ids

    def create_records(self, lattice: EpicsLattice) -> None:
        """Define PV's for slow orbit feedback."""
        builder.SetDeviceName("SR-CS-SOFB-01")

        self.power_pv = builder.mbbOut(
            "ONOFF", "OFF", "ON", initial_value=self.power, on_update=self.set_power
        )

        builder.aOut("AFRAC", initial_value=0.2, DRVH=1, DRVL=0, PREC=4, EGU="1")

        builder.aOut(
            "MU", 0, initial_value=self.sofb.mu, on_update=self.sofb.set_mu, PREC=3
        )

        # Corrector magnet ID, in floating point format: cell.position_in_cell
        # This matches the format of SR-DI-EBPM-01:BPMID
        mag_ids = self.get_corrector_magnet_ids(lattice)
        builder.WaveformIn("CMID", initial_value=mag_ids)

        # PVs for demonstrating SVD effect
        bpms = lattice.get_elements("BPM")
        svd_length = len(bpms)
        for plane in ["X", "Y"]:
            sv_pvs = sofb.SingularValuePVs()
            sv_pvs.length = builder.aIn(f"SVD:{plane}:LENGTH", initial_value=svd_length)

            sv_pvs.s = builder.WaveformIn(
                f"SVD:{plane}:S",
                initial_value=[0.0] * svd_length,
                datatype=np.float64,
            )

            sv_pvs.s_inv = builder.WaveformIn(
                f"SVD:{plane}:S_INV",
                initial_value=[0.0] * svd_length,
                datatype=np.float64,
            )

            sv_pvs.s_inv_cut = builder.WaveformIn(
                f"SVD:{plane}:S_INV_CUT",
                initial_value=[0.0] * svd_length,
                datatype=np.float64,
            )
            self.sofb.svd_pvs[plane] = sv_pvs

        builder.aOut(
            "CORRECT", initial_value=0, on_update=self.run_single, always_update=True
        )

        builder.aOut(
            "LIMIT",
            initial_value=self.sofb.step_limit,
            DRVH=0.5,
            DRVL=1e-3,
            on_update=self.sofb.set_step_limit,
            PREC=3,
        )

        self.matrix_error = builder.boolIn(
            "EMATRIX",
            DESC="Matrix Error",
            initial_value=1,
            ZNAM="OK",
            ONAM="SOFB MATRIX",
        )

        self.calc_error = builder.boolIn(
            "ECALC",
            DESC="Calculation Error",
            initial_value=0,
            ZNAM="OK",
            ONAM="SOFB CALC",
        )

        self.pv_error = builder.stringIn("EPV", DESC="PV Error", initial_value="OK")
