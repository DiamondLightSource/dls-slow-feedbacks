import logging
import os
import time
from typing import Literal

import cothread
import numpy as np
import pytac
from cothread.catools import FORMAT_TIME, camonitor, caput
from scipy.io import loadmat
from softioc import builder

from dls_slow_feedbacks import mode

logger = logging.getLogger(name="dls_slow_feedbacks")


class VefbConstants:
    VEMIT_TARGET_INITIAL = 8.0  # pm rad
    AFRAC_INITIAL = 0.25  # unitless
    IIRF_PARAM_INITIAL = 0.25  # unitless
    MAX_TS_AGE = 0.35  # seconds
    SQUAD_DELTA_MAX_INITIAL = 0.1  # amps
    VEMIT_TARGET_ERR_MAX_INITIAL = 2.5  # pm rad
    VEMIT_FB_START_ERR_MAX_INITIAL = 2.5  # pm rad
    VEMIT_EXTRA_TARGET_ERR_MAX_INITIAL = 0.2  # pm rad
    VEMIT_SINGLE_DELTA_INITIAL = 0.005  # amps
    NO_VALUE_TIMEOUT_INITIAL = 2.0  # seconds
    MAX_ERROR_TIME_INITIAL = 24.0  # seconds
    MAX_RECOVERY_TIME_INITIAL = 120.0  # seconds
    MIN_CAM_RECOVERY_TIME_INITIAL = 35.0  # seconds
    MAX_CAM_RECOVERY_TIME_INITIAL = 50.0  # seconds
    NO_EFFECT_FACTOR_DELTA_MAX_INITIAL = 3.0  # amps
    VEMIT_ACCEPTABLE_ERR_INITIAL = 0.5  # pm rad


class EmittanceStatus:
    # Successful emittance calculation.
    OK = 0
    # Successful emittance calculation on invalid beam (no beam or injecting).
    FORCED = 1
    # All emittance processing switched off.
    DISABLED = 2

    # Injecting beam, calculation postponed.
    INJECTING = 3
    # No beam present in machine, nothing to calculate.
    NO_BEAM = 4
    # Image too bright, pixels saturated.
    SATURATED = 5
    # Image too faint for reliable fit.
    TOO_DIM = 6

    # Error in emittance calculation, probable bad beam image.
    FIT_ERROR = 7

    # No triggers because triggering is currently disabled.
    NO_TRIGGER = 8
    # Cameras not in sticky state, manual intervention needed.
    CAMERA_OFF = 9
    # Cameras stalled, recovery not in progress, recovery needed.
    STALLED = 10

    # Attempting to automatically recovery cameras.
    RECOVERING = 11
    # Camera recovery failed.
    RECOVER_FAILED = 12


class VefbStatus:
    # Feedback operation successful.
    OK = 0

    # Feedback suspended during injection.
    INJECTING = 1

    # Emittance calc reports error status. Feedback suspended.
    EMITTANCE_WARNING = 2

    # Error of unknown type (e.g. uncaught exception). Feedback stops.
    UNKNOWN_ERROR = 3

    # No stored beam. Feedback stops.
    NO_STORED_BEAM = 4

    # Ring mode change with feedback running. Feedback stops.
    RING_MODE_CHANGE = 5

    # Magnet change exceeds threshold. Feedback stops if running.
    MAGNET_DELTA_ERROR = 6

    # Emittance value outside tolerable values. Feedback suspended.
    BAD_EMITTANCE_VALUE = 7

    # A parameter required for feedback to run. Feedback stopped/won't start.
    MISSING_CALC_PARAMETERS = 8

    # Error reading from/writing to magnet or with magnet drive levels.
    # Feedback stops if running.
    MAGNET_ERROR = 9

    # Cameras are in recovery. Feedback suspended.
    RECOVERING_CAMERAS = 10

    # No value from emittance IOC. Feedback suspended.
    NO_EMITTANCE_VALUE = 11

    # Time feedback is suspended due to errors exceeds theshold.
    # Feedback stops.
    PERSISTENT_EMITTANCE_ERRORS = 12

    # Applying corrections is having no effect.
    # Feedback stops before skew quads driven to bad position.
    HAVING_NO_EFFECT = 13

    # VEMIT is too far away from target to start.
    # Feedback stops.
    AWAY_FROM_TARGET = 14

    # Calculation method changed while running feedback.
    # Feedback stops.
    METHOD_CHANGE = 15


# Monitors:


class PVMonitor:
    """A class to monitor a single PV and update internal variables when the PV
    changes value."""

    def __init__(self, name):
        self.name = name
        self.ok = False
        self.value = None
        self.timestamp = 0
        self._sub = camonitor(
            name, self.on_update, format=FORMAT_TIME, notify_disconnect=True
        )

    def on_update(self, value) -> None:
        """Camonitor callback"""
        self.ok = value.ok
        if value.ok:
            self.value = +value
            self.timestamp = value.timestamp
        else:
            self.value = None
            self.timestamp = time.time()

    def close(self) -> None:
        """Close the camonitor connection"""
        self._sub.close()


class WFMonitor:
    """A class to monitor a list of PVs and update internal variables when the PVs
    change value."""

    def __init__(self, names, dtype=np.double):
        self.names = names
        self.ok = False
        self.oks = np.zeros(len(names), dtype=np.bool)
        self.values = np.zeros(len(names), dtype=dtype)
        self.timestamps = np.zeros(len(names))
        self._subs = camonitor(
            names, self.on_update, format=FORMAT_TIME, notify_disconnect=True
        )

    def on_update(self, value, index) -> None:
        """Camonitor callback"""
        self.oks[index] = value.ok
        if value.ok:
            self.values[index] = +value
            self.timestamps[index] = value.timestamp
        else:
            self.values[index] = np.nan
            self.timestamps[index] = time.time()
        self.ok = all(self.oks)

    def close(self) -> None:
        """Close the camonitor connection"""
        for sub in self._subs:
            sub.close()


class SkewQuadrupoles:
    def __init__(self, pv_names):
        self._squad_pv_names = pv_names
        self.monitors()
        self.sp = None
        self.sum_delta = np.zeros(self.num)
        self._use_setpoint = False

        self.last_levels_ok_fail: None | str = None
        self.last_drvl_fail = None
        self.last_drvh_fail = None

    @property
    def num(self) -> int:
        return len(self._squad_pv_names)

    def check_state(self) -> bool:
        return self.ok and self.drive_levels_ok()

    @property
    def ok(self) -> bool:
        pvs = [self.seti, self.seti_drvls, self.seti_drvls]
        return all([s.ok for s in pvs])  # noqa: C419

    def drive_levels_ok(self) -> bool:
        """Check that DRVL < DRVH for each squad PV"""
        for a, b, c in zip(
            self.seti_drvls.values,
            self.seti_drvhs.values,
            self._squad_pv_names,
            strict=True,
        ):
            if a >= b:
                if self.last_levels_ok_fail != c:
                    logger.warning(f"Drive check DRVH <= DRVL {c}")
                    self.last_levels_ok_fail = c
                return False
        self.last_levels_ok_fail = None
        return True

    def make_setpoint(self) -> None:
        """Update the self.sp array with the current values of squad PVs and reset
        self.sum_delta to an array of zeros."""
        if self.seti.ok:
            self.sp = +self.seti.values
            self.sum_delta = np.zeros(self.num)

    def use_setpoint(self, use) -> None:
        """Setpoint is only enabled when vefb is run in loop mode."""
        if use and (self.sp is None or not self._use_setpoint):
            self.make_setpoint()
        self._use_setpoint = use

    def values_within_levels(self, values) -> bool:
        """Check if squad PV values are within the valid range."""
        drvhs = self.seti_drvhs.values
        drvls = self.seti_drvls.values

        for i in range(self.num):
            if values[i] < self.drvls[i]:
                if self.last_drvl_fail != i:
                    logger.warning(
                        f"DRVL check {self._squad_pv_names[i]}: "
                        f"New SQUAD value {values[i]} < DRVL {drvls[i]}"
                    )
                    self.last_drvl_fail = i
                    self.last_drvh_fail = None
                return False

        for i in range(self.num):
            if values[i] > self.drvhs[i]:
                if self.last_drvh_fail != i:
                    logger.warning(
                        f"DRVH check {self._squad_pv_names[i]}: "
                        f"New SQUAD value {values[i]} > DRVH {drvhs[i]}"
                    )
                    self.last_drvh_fail = i
                    self.last_drvl_fail = None
                return False

        self.last_drvl_fail = None
        self.last_drvh_fail = None

        return True

    def apply_correction(self, delta) -> bool:
        """Do final calculation and apply correction to PVs"""
        if self._use_setpoint:
            if self.sp is None:
                return False
            self.sum_delta += delta
            new_sqvals = self.sp + self.sum_delta
        elif self.seti.ok:
            new_sqvals = self.seti.values + delta
        else:
            return False

        if not self.ok:
            return False

        if not self.values_within_levels(new_sqvals):
            return False

        results = caput(self._squad_pv_names, new_sqvals, throw=False)
        ok = np.all(map(bool, results))
        if not ok:
            logger.error("Caput error")
            for s in [str(r) for r in results if not bool(r)]:
                logger.error(f"{s}")
        return ok

    def monitors(self) -> None:
        """Setup squad PV monitoring."""
        self.seti = WFMonitor(self._squad_pv_names)

        squad_pv_drvhs = [f"{name}.DRVH" for name in self._squad_pv_names]
        squad_pv_drvls = [f"{name}.DRVL" for name in self._squad_pv_names]

        self.seti_drvhs = WFMonitor(squad_pv_drvhs)
        self.seti_drvls = WFMonitor(squad_pv_drvls)

        self.drvhs = self.seti_drvhs.values
        self.drvls = self.seti_drvls.values

    def set_pv_names(self, squad_pv_names) -> None:
        """Restarts squad monitoring. Called when the ringmode is changed as this may
        change which PVs we need to monitor."""
        self._squad_pv_names = squad_pv_names

        self.seti.close()
        self.seti_drvhs.close()
        self.seti_drvls.close()
        self.monitors()


class VefbServer:
    """The main class which provides the vertical emittance feedback PV interface,
    and contains the algorithms for making single and loop corrections."""

    def __init__(self, ring_mode):
        squad_pv_names = ring_mode.lattice.get_element_pv_names("SQUAD", "a1", pytac.SP)
        self.skew_quads = SkewQuadrupoles(squad_pv_names)

        self.loop_enabled = False
        self.enabled_first_time = False
        self.time_step = 0.2

        self.IRM = None
        self.skewhw = None
        self.IRM_old = None
        self.skewhw_old = None
        self.IRM_new = None
        self.skewhw_new = None

        self.last = None
        self.vemit_filtered = VefbConstants.VEMIT_TARGET_INITIAL
        self.last_calc_status = VefbStatus.OK
        self.delta = 0

        self.recovering_cameras = False

        self.error_or_recover_time = 0
        self.error_time = 0
        self.current_time = time.time()
        self.recovery_start_time = self.current_time
        self.sum_delta_oor = 0
        self.no_value_start_time = self.current_time

        self.monitors()
        self.records()

        ring_mode.add_listener(self.set_data_dir)

    def start(self) -> None:
        cothread.Spawn(self.run)

    def init_wait(self, wait_time: float) -> None:
        """Wait a few seconds to ensure all camonitor connections are connected. If
        connections fail then we continue anyway after the wait time has elapsed."""
        logger.debug("Vefb init wait")
        end_time = time.time() + wait_time

        while True:
            monitors = [
                self.skew_quads,
                self.vemit,
                self.beam_current,
                self.emit_status,
            ]

            if np.all([pv.ok for pv in monitors]):
                logger.debug("Vefb initialised ok")
                return
            if time.time() > end_time:
                logger.warning("Init timeout")
                return
            cothread.Sleep(self.time_step)

    def run(self) -> None:
        """Main runtime loop"""
        self.init_wait(3.0)
        logger.info("Vefb started")
        while True:
            try:
                cothread.Sleep(self.time_step)
                self.perform_correction(self.loop_enabled)

            except BaseException:
                logger.exception("Vemit FB raised unexpected exception")
                self.handle_status(VefbStatus.UNKNOWN_ERROR, False)

    def run_single(self, value) -> None:
        """Called when SR-CS-VEFB-01:SINGLE changes value. This does a single
        correction"""
        logger.info("Single correct pressed")
        if not self.loop_enabled:
            try:
                self.perform_correction(True, True)
            except BaseException:
                logger.exception("Vemit FB raised unexpected exception")
                self.handle_status(VefbStatus.UNKNOWN_ERROR, True)
        else:
            logger.warning(
                "Single correct disabled in loopback mode. Skipping correction."
            )

    def add_single(self, value) -> None:
        """Called when SR-CS-VEFB-01:ADD_DELTA changes value. This directly adds
        a delta to squad PVs."""
        if not self.loop_enabled:
            try:
                self.run_add_delta(self.vemit_single_delta.get())
            except BaseException:
                logger.exception("Vemit FB raised unexpected exception")
                self.handle_status(VefbStatus.UNKNOWN_ERROR, True)
        else:
            logger.warning(
                "Add delta disabled in loopback mode. Skipping delta addition."
            )

    def sub_single(self, value) -> None:
        """Called when SR-CS-VEFB-01:SUB_DELTA changes value. This directly subtracts
        a delta from squad PVs."""
        if not self.loop_enabled:
            try:
                self.run_add_delta(-self.vemit_single_delta.get())
            except BaseException:
                logger.exception("Vemit FB raised unexpected exception")
                self.handle_status(VefbStatus.UNKNOWN_ERROR, True)
        else:
            logger.warning(
                "Subtract delta disabled in loopback mode. Skipping delta subtraction."
            )

    def error_check(self) -> Literal[8, 4, 9, 10, 14, 1, 2, 0]:
        """Check for common error conditions."""
        status = VefbStatus.OK

        self.check_camera_state()

        if not self.calc_parameters_ok():
            return VefbStatus.MISSING_CALC_PARAMETERS

        if not self.have_stored_beam():
            status = VefbStatus.NO_STORED_BEAM

        elif not self.skew_quads.check_state():
            status = VefbStatus.MAGNET_ERROR

        elif self.recovering_cameras:
            status = VefbStatus.RECOVERING_CAMERAS

        elif self.away_from_target():
            status = VefbStatus.AWAY_FROM_TARGET

        elif self.is_injecting():
            status = VefbStatus.INJECTING

        elif self.emittance_status_bad():
            status = VefbStatus.EMITTANCE_WARNING

        return status

    def perform_correction(self, do_correction, single=False) -> None:
        """Check for errors, then run the appropriate correction, finally handle any
        resulting errors."""
        status = self.error_check()

        if single and status == VefbStatus.AWAY_FROM_TARGET:
            status = VefbStatus.OK

        if status == VefbStatus.OK:
            if single:
                status = self.single_correct()
            elif do_correction:
                status = self.loop_correct()
            else:
                status = self.calc_only()

        self.vemit_filtered_pv.set(self.vemit_filtered)

        self.handle_status(status, single)

        self.enabled_first_time = False

    def set_data_dir(self, lattice) -> None:
        """This function is used to load the configuration for a different ringmode. It
        is called when the ringmode PV is updated."""
        self.last = None
        self.IRM = None
        self.IRM_old = None
        self.skewhw_old = None
        self.IRM_new = None
        self.skewhw_new = None

        squad_pv_names = lattice.get_element_pv_names("SQUAD", "a1", pytac.SP)
        self.skew_quads.set_pv_names(squad_pv_names)

        try:
            self.skewhw_old = np.ones(self.skew_quads.num)
            logger.debug(f"Skewhw_old: {self.skewhw_old}")

            rm_file = os.path.join(
                mode.DATAROOT, lattice.name, "GoldenCouplingEmittance.mat"
            )
            logger.info(f"Vefb loading {lattice.name}")
            logger.debug(f"Loading matrix {lattice.name} {rm_file}")
            load_rm = loadmat(rm_file)
            rm = load_rm["RM"]
            logger.debug(f"RM_old: {rm}")
            self.IRM_old = 1 / rm[0][0]
            logger.debug(f"IRM_old: {self.IRM_old}")

        except BaseException:
            logger.exception("Ringmode_change raised unexpected exception")

        try:
            rm_file = os.path.join(mode.DATAROOT, lattice.name, "GoldenSkewVector.mat")
            logger.debug(f"LoadSkewVector {lattice.name} {rm_file}")

            load_rm = loadmat(rm_file)
            rm = load_rm["RM"]
            logger.debug(f"RM_new: {rm}")
            skew = load_rm["skewhw"][0]
            logger.debug(f"Skew_new: {skew}")
            self.IRM_new = 1 / rm[0][0]
            self.skewhw_new = skew
            logger.debug(f"IRM_new: {self.IRM_new}")
            logger.debug(f"Skewhw_new: {self.skewhw_new}")

        except BaseException:
            logger.exception("Ringmode_change raised unexpected exception")

        self.update_calc_parameters()

        if self.loop_enabled:
            self.handle_status(VefbStatus.RING_MODE_CHANGE, True)
        else:
            self.handle_status(VefbStatus.OK, True)

    def on_method_change(self, value) -> None:
        """Callback for SR-CS-VEFB-01:METHOD. Allows users to change the vefb aglorithm
        being used"""
        if self.loop_enabled:
            self.handle_status(VefbStatus.METHOD_CHANGE, True)
        self.update_calc_parameters()

    def update_calc_parameters(self) -> None:
        """Update calculation params when the vefb algorithm or ringmode changes."""
        if self.method_pv.get() == 0:
            self.IRM = self.IRM_old
            self.skewhw = self.skewhw_old
        else:
            self.IRM = self.IRM_new
            self.skewhw = self.skewhw_new
        logger.debug(f"IRM: {self.IRM}")
        logger.debug(f"Skewhw: {self.skewhw}")

    def handle_status(self, status: int, single: bool) -> None:
        """Handle any errors which occurred since the last check. Check for
        persistant errors and update the status PV."""
        do_correction = single or self.loop_enabled

        status = self.persistent_error_check(status)
        status = self.no_effect_check(status)

        status = self.filter_errors(status, do_correction)
        calc_status = status

        if not single:
            self.last_calc_status = calc_status
            self.calc_status_pv.set(calc_status)

        if do_correction:
            old_status = self.status_pv.get()
            if status != old_status:
                ok_states = [VefbStatus.OK, VefbStatus.INJECTING]
                if status not in ok_states or old_status not in ok_states:
                    logger.info(f"Status change: {old_status} -> {status}")

            self.status_pv.set(status)
            if status not in [
                VefbStatus.OK,
                VefbStatus.INJECTING,
                VefbStatus.EMITTANCE_WARNING,
                VefbStatus.NO_EMITTANCE_VALUE,
                VefbStatus.BAD_EMITTANCE_VALUE,
                VefbStatus.RECOVERING_CAMERAS,
            ]:
                self.enable_loop_pv.set(0)

    def persistent_error_check(self, status: int) -> int:
        """Check for re-occuring errors. The feedback loop may be disabled if an
        error persists."""
        current_time = time.time()
        diff = current_time - self.current_time

        if status in [VefbStatus.OK]:
            self.error_or_recover_time = 0
            self.error_time = 0
        elif status in [VefbStatus.INJECTING]:
            pass
        elif status in [VefbStatus.RECOVERING_CAMERAS]:
            self.error_or_recover_time += diff
        else:
            self.error_or_recover_time += diff
            self.error_time += diff

        if (
            self.loop_enabled
            and self.error_or_recover_time > self.max_recovery_time_pv.get()
        ):
            logger.error(
                f"Time in error/recovery exceeds timeout {self.max_recovery_time_pv}"
            )
            status = VefbStatus.PERSISTENT_EMITTANCE_ERRORS

        elif self.loop_enabled and (self.error_time > self.max_error_time_pv.get()):
            logger.error(f"Time in error exceeds timeout {self.max_error_time_pv}")
            status = VefbStatus.PERSISTENT_EMITTANCE_ERRORS

        self.current_time = current_time

        return status

    def no_effect_check(self, status) -> int:
        """Check whether the applied corrections are moving the emittance towards the
        desired target. This is only used in loop mode."""
        if not self.loop_enabled or status not in [VefbStatus.OK]:
            return status

        err = abs(self.vemit_filtered - self.vemit_target_pv.get())

        if err > self.vemit_acceptable_error_pv.get():
            self.sum_delta_oor += self.delta

            sum_delta_oor_threshold = self.oor_factor_max_pv.get() * self.IRM

            if (
                self.no_effect_error_enable_pv.get() == 1
                and abs(self.sum_delta_oor) > sum_delta_oor_threshold
            ):
                logger.debug(
                    f"oor v:{self.vemit_filtered:.2f} "
                    f"t:{self.vemit_target_pv.get():.2f} "
                    f"me:{self.vemit_acceptable_error_pv.get():.2f}"
                )
                logger.error(
                    f"sum_delta_oor {self.sum_delta_oor:.6f} "
                    f"exceeds threshold {sum_delta_oor_threshold:.6f}"
                )

                status = VefbStatus.HAVING_NO_EFFECT

        else:
            self.sum_delta_oor = 0

        return status

    def filter_errors(self, status, do_correction) -> int:
        if status in [VefbStatus.NO_EMITTANCE_VALUE]:
            if self.last_calc_status not in [VefbStatus.NO_EMITTANCE_VALUE]:
                self.no_value_start_time = self.current_time - VefbConstants.MAX_TS_AGE
                status = VefbStatus.OK
            else:
                no_value_time = self.current_time - self.no_value_start_time
                if no_value_time < self.no_value_timeout.get():
                    status = VefbStatus.OK
                elif do_correction:
                    logger.warning(
                        f"No value for {no_value_time:.2f}. "
                        f"Exceeds threshold ({self.no_value_timeout.get():.2f})"
                    )

        else:
            self.no_value_start_time = self.current_time

        return status

    def check_camera_state(self) -> None:
        """Check that the two pinhole cameras which calculate the vertical emittance
        are in a healthy state."""
        if self.recovering_cameras:
            current_time = time.time()
            min_recovery_timeout = self.min_camera_recovery_time_pv.get()
            max_recovery_timeout = self.max_camera_recovery_time_pv.get()
            recovery_time = current_time - self.recovery_start_time

            if recovery_time > min_recovery_timeout and self.camera_recovery_complete():
                logger.info(f"Camera recovery successful after {recovery_time} seconds")
                self.recovering_cameras = False

            elif recovery_time > max_recovery_timeout:
                logger.warning(
                    f"Camera recovery timeout {max_recovery_timeout} seconds exceeded"
                )
                self.recovering_cameras = False

        elif self.cam_recovery_enable_pv.get() == 1:
            self.recovering_cameras = self.camera_recovery_started()
            if self.recovering_cameras:
                current_time = time.time()
                self.recovery_start_time = current_time
                logger.info("Camera recovery started")

    def camera_recovery_started(self) -> int:
        emit_status = self.emit_status.value
        return emit_status == EmittanceStatus.RECOVERING

    def camera_recovery_complete(self) -> int:
        emit_status = self.emit_status.value
        return emit_status == EmittanceStatus.OK

    def have_stored_beam(self) -> bool:
        return (
            self.beam_current.ok
            and self.beam_current.value > self.dcct_threshold_pv.get()
        )

    def is_injecting(self) -> bool:
        return self.emit_status.value == EmittanceStatus.INJECTING

    def emittance_status_bad(self) -> bool:
        if not self.emit_status.ok:
            return False
        return self.emit_status.value not in [
            EmittanceStatus.OK,
            EmittanceStatus.FORCED,
            EmittanceStatus.INJECTING,
        ]

    def away_from_target(self) -> bool:
        if (
            not self.loop_enabled and not self.is_injecting()
        ) or self.enabled_first_time:
            target = self.vemit_target_pv.get()
            threshold = self.vemit_fb_start_err_max_pv.get()
            err = min(
                abs(self.vemit.value - target), abs(self.vemit_mean.value - target)
            )
            if err > threshold:
                return True
        return False

    def set_loop_enabled(self, value) -> None:
        """Called when SR-CS-VEFB-01:LOOP is updated. This switched vefb to run in loop
        mode which requires some reconfiguration which is done in this function."""
        logger.info(f"LOOP ENABLE: {value}")
        enabled = value == 1
        self.loop_enabled = enabled
        self.enabled_first_time = True
        self.error_or_recover_time = 0
        self.error_time = 0
        if enabled:
            self.vemit_filtered = self.vemit_target_pv.get()
            self.sum_delta_oor = 0
        self.skew_quads.use_setpoint(enabled)

    def loop_correct(self) -> Literal[8, 11, 7, 6, 9, 0]:
        return self.do_calc(True)

    def single_correct(self) -> Literal[8, 11, 7, 6, 9, 0]:
        return self.do_calc(True, False, False)

    def calc_only(self) -> Literal[8, 11, 7, 6, 9, 0]:
        return self.do_calc(False)

    def calc_parameters_ok(self) -> bool:
        return (
            self.IRM is not None
            and self.skewhw is not None
            and len(self.skewhw) == self.skew_quads.num
        )

    def do_calc(
        self, apply_calc, use_filter=True, check_limits=True
    ) -> Literal[8, 11, 7, 6, 9, 0]:
        """Calculates the delta to apply and then calls self.apply_delta() which
        applies the delta."""
        if not self.calc_parameters_ok():
            return VefbStatus.MISSING_CALC_PARAMETERS

        target = self.vemit_target_pv.get()
        vemit = self.vemit.value
        ts = self.vemit.timestamp

        current_time = time.time()
        age = current_time - ts

        # Timestamps ok?
        if age > VefbConstants.MAX_TS_AGE:
            return VefbStatus.NO_EMITTANCE_VALUE

        truncated = False
        vemit_raw = vemit

        # values ok?
        if check_limits:
            vmax = (
                target + self.vemit_err_max_pv.get() + self.vemit_extra_err_max_pv.get()
            )
            if vemit > vmax:
                if apply_calc:
                    vemit = vmax
                    truncated = True

            vmin = (
                target - self.vemit_err_max_pv.get() - self.vemit_extra_err_max_pv.get()
            )
            if vemit < vmin:
                if apply_calc:
                    vemit = vmin
                    truncated = True

        # apply filter (IIR) if required
        if use_filter:
            filter_frac = self.iir_frac_pv.get()
            filtered = filter_frac * vemit + (1 - filter_frac) * self.vemit_filtered
            vemit_used = filtered
            self.vemit_filtered = filtered
        else:
            vemit_used = vemit

        if check_limits:
            if truncated:
                logger.info(f"Vemit truncated: {vemit_raw} {vemit} {vemit_used}")

            vwrite_max = target + self.vemit_err_max_pv.get()
            if vemit_used > vwrite_max:
                if apply_calc:
                    logger.warning(
                        f"Vemit too high - skip: {vemit_used} MAX: {vwrite_max}"
                    )
                return VefbStatus.BAD_EMITTANCE_VALUE
            vwrite_min = target - self.vemit_err_max_pv.get()
            if vemit_used < vwrite_min:
                if apply_calc:
                    logger.warning(
                        f"Vemit too low - skip: {vemit_used} MIN: {vwrite_min}"
                    )
                return VefbStatus.BAD_EMITTANCE_VALUE

        # calc skew quad delta
        fraction = self.afrac_pv.get()
        delta = -fraction * self.IRM * (vemit_used - target)

        return self.apply_delta(delta, apply_calc, check_limits)

    def run_add_delta(self, delta) -> None:
        """Rather than calculating a delta. This function just verifies a given delta
        which is then applied by calling self.apply_delta()"""
        if self.check_status_on_delta_pv.get() == 0:
            status = VefbStatus.OK
        else:
            status = self.error_check()

        if status == VefbStatus.OK or status == VefbStatus.AWAY_FROM_TARGET:
            status = self.apply_delta(delta)

        self.handle_status(status, True)

    def apply_delta(
        self, delta, apply_calc=True, check_limits=False
    ) -> Literal[6, 9, 0]:
        """Perform final validations before calling apply_correction which
        outputs the correction to the skew quadrupoles."""
        # check delta within limits and raise error or scale
        delta_max = self.squad_delta_max_pv.get()
        if check_limits:
            if np.abs(delta) > delta_max:
                return VefbStatus.MAGNET_DELTA_ERROR
        else:
            if delta_max <= 0:
                if apply_calc:
                    logger.error("Max delta non positive")
                return VefbStatus.MAGNET_DELTA_ERROR

            if delta > delta_max:
                if apply_calc:
                    logger.info(f"Delta scaled: {delta} -> {delta_max}")
                delta = delta_max
            elif delta < -delta_max:
                if apply_calc:
                    logger.info(f"Delta scaled: {delta} -> {-delta_max}")
                delta = -delta_max

        self.delta = delta

        # same correction applied to all skew quads
        sq_delta = delta * self.skewhw

        if apply_calc:
            # apply correction to skew quads
            ok = self.skew_quads.apply_correction(sq_delta)
            if not ok:
                return VefbStatus.MAGNET_ERROR

        return VefbStatus.OK

    def monitors(self) -> None:
        """Setup camonitoring of key PVs"""
        self.vemit = PVMonitor("SR-DI-EMIT-01:VEMIT")
        self.vemit_mean = PVMonitor("SR-DI-EMIT-01:VEMIT_MEAN")
        self.beam_current = PVMonitor("SR-DI-DCCT-01:SIGNAL")
        self.emit_status = PVMonitor("SR-DI-EMIT-01:STATUS")

    def records(self) -> None:
        """Setup pythonSoftIOC records hosted by this IOC. These provide a user
        interface for controlling and monitoring vefb."""
        builder.SetDeviceName("SR-CS-VEFB-01")

        self.enable_loop_pv = builder.mbbOut(
            "LOOP",
            ("OFF", "MINOR"),
            ("ON", "NO_ALARM"),
            initial_value=0,
            on_update=self.set_loop_enabled,
        )

        self.single_pv = builder.aOut(
            "SINGLE", initial_value=0, on_update=self.run_single, always_update=True
        )

        self.add_delta_pv = builder.aOut(
            "ADD_DELTA", initial_value=0, on_update=self.add_single, always_update=True
        )

        self.sub_delta_pv = builder.aOut(
            "SUB_DELTA", initial_value=0, on_update=self.sub_single, always_update=True
        )

        self.method_pv = builder.mbbOut(
            "METHOD",
            "OLD",
            "NEW",
            # Minor alarm when running in Old method
            ZRSV="MINOR",
            ONSV="NO_ALARM",
            on_update=self.on_method_change,
            initial_value=1,
        )

        self.afrac_pv = builder.aOut(
            "AFRAC",
            initial_value=VefbConstants.AFRAC_INITIAL,
            DRVH=1,
            DRVL=0,
            PREC=2,
            EGU="1",
        )

        self.iir_frac_pv = builder.aOut(
            "IIRF_PARAM",
            initial_value=VefbConstants.IIRF_PARAM_INITIAL,
            DRVH=1,
            DRVL=0,
            PREC=2,
            EGU="1",
        )

        self.dcct_threshold_pv = builder.aOut(
            "DCCT_THRESHOLD", initial_value=5, DRVH=1000, DRVL=0, PREC=4, EGU="mA"
        )

        self.vemit_single_delta = builder.aOut(
            "VEMIT_SINGLE_DELTA",
            initial_value=VefbConstants.VEMIT_SINGLE_DELTA_INITIAL,
            DRVH=VefbConstants.SQUAD_DELTA_MAX_INITIAL,
            DRVL=0.0,
            PREC=4,
            EGU="A",
        )

        self.check_status_on_delta_pv = builder.mbbOut(
            "CHECK_STATUS_ON_DELTA", "DISABLED", "ENABLED", initial_value=1
        )

        self.vemit_err_max_pv = builder.aOut(
            "VEMIT_TARGET_ERR_MAX",
            initial_value=VefbConstants.VEMIT_TARGET_ERR_MAX_INITIAL,
            DRVH=100.0,
            DRVL=0.0,
            PREC=4,
            EGU="pm rad",
        )

        self.vemit_fb_start_err_max_pv = builder.aOut(
            "VEMIT_FB_START_ERR_MAX",
            initial_value=VefbConstants.VEMIT_FB_START_ERR_MAX_INITIAL,
            DRVH=100.0,
            DRVL=0.0,
            PREC=4,
            EGU="pm rad",
        )

        self.vemit_extra_err_max_pv = builder.aOut(
            "VEMIT_EXTRA_TARGET_ERR_MAX",
            initial_value=VefbConstants.VEMIT_EXTRA_TARGET_ERR_MAX_INITIAL,
            DRVH=100.0,
            DRVL=0.0,
            PREC=4,
            EGU="pm rad",
        )

        self.vemit_acceptable_error_pv = builder.aOut(
            "VEMIT_ACCEPTABLE_ERR",
            initial_value=VefbConstants.VEMIT_ACCEPTABLE_ERR_INITIAL,
            DRVH=100.0,
            DRVL=0.0,
            PREC=4,
            EGU="pm rad",
        )

        self.oor_factor_max_pv = builder.aOut(
            "NO_EFFECT_FACTOR_DELTA_MAX",
            initial_value=VefbConstants.NO_EFFECT_FACTOR_DELTA_MAX_INITIAL,
            PREC=4,
            EGU="A",
        )

        self.vemit_target_pv = builder.aOut(
            "VEMIT_TARGET",
            initial_value=VefbConstants.VEMIT_TARGET_INITIAL,
            DRVH=100.0,
            DRVL=0.0,
            PREC="1",
            EGU="pm rad",
        )

        self.vemit_filtered_pv = builder.aOut(
            "VEMIT_FILTERED",
            initial_value=VefbConstants.VEMIT_TARGET_INITIAL,
            DRVH=100.0,
            DRVL=0.0,
            PREC="2",
            EGU="pm rad",
        )

        self.no_effect_error_enable_pv = builder.mbbOut(
            "NO_EFFECT_ERRORS", "DISABLED", "ENABLED", initial_value=1
        )

        self.no_value_timeout = builder.aOut(
            "NO_VALUE_TIMEOUT",
            initial_value=VefbConstants.NO_VALUE_TIMEOUT_INITIAL,
            DRVL=0.0,
            PREC=1,
            EGU="s",
        )

        self.max_error_time_pv = builder.aOut(
            "MAX_ERROR_TIME",
            initial_value=VefbConstants.MAX_ERROR_TIME_INITIAL,
            DRVL=0.0,
            PREC=1,
            EGU="s",
        )

        self.max_recovery_time_pv = builder.aOut(
            "MAX_RECOVERY_TIME",
            initial_value=VefbConstants.MAX_RECOVERY_TIME_INITIAL,
            DRVL=0.0,
            PREC=1,
            EGU="s",
        )

        self.min_camera_recovery_time_pv = builder.aOut(
            "MIN_CAM_RECOVERY_TIME",
            initial_value=VefbConstants.MIN_CAM_RECOVERY_TIME_INITIAL,
            DRVL=0.0,
            PREC=1,
            EGU="s",
        )

        self.max_camera_recovery_time_pv = builder.aOut(
            "MAX_CAM_RECOVERY_TIME",
            initial_value=VefbConstants.MAX_CAM_RECOVERY_TIME_INITIAL,
            DRVL=0.0,
            PREC=1,
            EGU="s",
        )

        self.cam_recovery_enable_pv = builder.mbbOut(
            "CAM_RECOVERY", "DISABLED", "ENABLED", initial_value=1
        )

        self.squad_delta_max_pv = builder.aOut(
            "SQUAD_DELTA_MAX",
            initial_value=VefbConstants.SQUAD_DELTA_MAX_INITIAL,
            PREC=4,
            EGU="A",
        )

        self.status_pv = builder.mbbOut(
            "STATUS",
            ("Ok", "NO_ALARM"),
            ("Injecting", "NO_ALARM"),
            ("Bad emittance status", "MINOR"),
            ("Unknown error", "MAJOR"),
            ("No stored beam", "MAJOR"),
            ("Ringmode change during FB", "MAJOR"),
            ("Skew Quad delta error", "MAJOR"),
            ("Bad emittance value", "MINOR"),
            ("Missing calc parameters", "MAJOR"),
            ("Skew Quad read/write err", "MAJOR"),
            ("Recovering cameras", "MINOR"),
            ("No emittance value", "MINOR"),
            ("Persistent emittance err", "MAJOR"),
            ("Having no effect", "MAJOR"),
            ("Away from target", "MAJOR"),
            ("Method change during FB", "MAJOR"),
            initial_value=VefbStatus.OK,
        )

        self.calc_status_pv = builder.mbbOut(
            "CALC_STATUS",
            ("Ok", "NO_ALARM"),
            ("Injecting", "NO_ALARM"),
            ("Bad emittance status", "MINOR"),
            ("Unknown error", "MINOR"),
            ("No stored beam", "MINOR"),
            ("Ringmode change during FB", "MINOR"),
            ("Skew Quad delta error", "MINOR"),
            ("Bad emittance value", "MINOR"),
            ("Missing calc parameters", "MINOR"),
            ("Skew Quad read/write err", "MINOR"),
            ("Recovering cameras", "MINOR"),
            ("No emittance value", "MINOR"),
            ("Persistent emittance err", "MINOR"),
            ("Invalid error status", "MINOR"),  # 'Having no effect' is not valid here
            ("Away from target", "MINOR"),
            ("Method change during FB", "MINOR"),
            initial_value=VefbStatus.OK,
        )
