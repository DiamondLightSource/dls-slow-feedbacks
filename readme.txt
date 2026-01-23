Physics Applications IOC CS-DI-IOC-09
=====================================

Glossary
-------
rffb - Radio Frequency FeedBacks
sofb - Slow Orbit FeedBacks
tfb - Tune FeedBacks
vefb - Vertical Emittance FeedBacks
bpm - Beam Position Monitor
bpmx/bpmy - x and y position values for each BPM
hcm/vcm - Horizontal Correction Matrix / Vertical Correction Matrix

1) RINGMODE
-------

The ringmode PV is hosted by this IOC. It is queried by most high level
applications to determine which golden matrices to use, as well as many
accelerator physics applications including middlelayer.

2) BPM & CORRECTOR ENABLE
-------------------

PVs and EDL to disable each horizontal and vertical corrector and BPM from the
feedback algorithms. BPMs and correctors can be controlled for SOFB and FOFB
independently.

A GUI to display where the correctors are operating within their range and
the PVs backing this are also included in this module.

3) RFFB
-------

Removes dispersive component from the correctors by adjusting the RF
frequency. The algorithm is:

dispersion_correctors_per_hz = pinv(orbit_response_matrix) * dispersion_per_hz
delta_rf = pinv(dispersion_correctors_per_hz) * hcm

Where pinv is matrix or vector pseudo-inverse (numpy)

PVs are SR-CS-RFFB-01:XXX

4) SOFB
-------

Corrects orbit, single correction or feedback

Algorithm is:

delta_correctors = pinv(orbit_response_matrix) * orbit

(pure integral control)

5) TFB
-------

Tune feedback, single correction or feedback

Corrects the global tune based on the inverse golden tune response matrix.

delta_quads = pinv(tune_response_matrix) * tune_error

Tune feedback also contains code for attaching itself to the quadrupole PSC
via a PV forwarding mechanism. It then writes into an offset field which
adjusts the quadupole setpoint.

6) VEFB
-------

Maintains the vertical emittance at a target value using the skew quadrupoles.

The algorithm is:

squad_delta = pinv(response_vector) * vertical_emittance_error
