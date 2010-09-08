Physics Applications IOC CS-DI-IOC-09
=====================================

1) CORRECTOR ENABLE
-------------------

PVs and EDL to disable each horizontal and vertical corrector from the feedback
algorithms.

2) RFFB
-------

Removes dispersive component from the correctors by adjusting the RF
frequency. The algorithm is:

dispersion_correctors_per_hz = pinv(orbit_response_matrix) * dispersion_per_hz
delta_rf = pinv(dispersion_correctors_per_hz) * hcm

Where pinv is matrix or vector pseudo-inverse (numpy)

PVs are SR-CS-RFFB-01:XXX

3) SOFB
-------

Corrects orbit, single correction or feedback

Need SOFB position display for new correctiors, get s pos out of MML...

