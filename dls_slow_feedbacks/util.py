from dls_slow_feedbacks import mode, waveforms


def get_bpm_and_corrector_feedback_disabled_pvs() -> list:
    """Return a list of the PVs created for 'BPMs and Correctors enabled' in feedbacks

    This can be used to generate a Burt request file for these PVs, should this be
    required when the lattice changes.
    """
    pvs = []
    ring_mode = mode.RingMode()
    waveform_obj = waveforms.WaveformsServer(ring_mode)
    for family in waveform_obj.records.values():
        for feedback_speed in family.values():
            for plane in feedback_speed:
                for record in plane:
                    pvs.append(record.name)

    return pvs
