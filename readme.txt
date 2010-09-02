RF Feedback IOC CS-DI-IOC-09
============================

Removes dispersive component from the correctors by adjusting the RF
frequency. The algorithm is:

dispersion_correctors_per_hz = pinv(orbit_response_matrix) * dispersion_per_hz
delta_rf = pinv(dispersion_correctors_per_hz) * hcm

Where pinv is matrix or vector pseudo-inverse (numpy)

PVs are SR-CS-RFFB-01
