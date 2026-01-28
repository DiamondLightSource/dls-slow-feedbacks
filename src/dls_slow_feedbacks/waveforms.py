import logging

import cothread
import numpy as np
import pytac
from cothread.catools import FORMAT_CTRL, ca_nothing, caget
from softioc import builder

logger = logging.getLogger(name="dls_slow_feedbacks")


class WaveformsServer:
    """Creates waveforms and control PVs which are used by the feedback algorithms."""

    # x/y planes (horizontal/vertical planes)
    PLANES = [0, 1]
    FAMILIES = {
        "cor": [("HSTR", "x_kick"), ("VSTR", "y_kick")],
        "bpm": [("BPM", "x"), ("BPM", "y")],
    }
    SPEEDS = ["slow", "fast"]

    def __init__(self, ring_mode):
        self.lattice = ring_mode.lattice
        self.wf = {}
        self.records = {}
        self.latched = None
        self.create_info_waveforms()
        self.create_control_and_waveform_pvs()

    def start(self):
        for device in ["cor", "bpm"]:
            for mode in self.SPEEDS:
                for plane in self.PLANES:
                    self.update_individual_from_wf(device, mode, plane)
        cothread.Spawn(self.run)

    def run(self):
        while True:
            try:
                cothread.Sleep(1.0)
                self.tick()
            except ca_nothing as pv_error:
                logger.error(f"PV error: {pv_error}")
            except BaseException:
                logger.exception("Unexpected error")

    def tick(self):
        """Read from individual correctors, write to corrector vector/waveform."""
        fam = self.FAMILIES["cor"]
        xy_corrector_values = [None, None]
        mag = [None, None]
        rhv = [None, None]

        # get corrector readbacks
        for p in self.PLANES:
            corrector_pvs = self.lattice.get_element_pv_names(
                fam[p][0], fam[p][1], pytac.RB
            )
            xy_corrector_values[p] = caget(corrector_pvs, format=FORMAT_CTRL)
            # convert to relative magnitude
            mag[p] = [
                corr_value.upper_ctrl_limit - corr_value.lower_ctrl_limit
                for corr_value in xy_corrector_values[p]
            ]
            rhv[p] = 2 * abs(np.array(xy_corrector_values[p]) / mag[p])
            # update max value and name
            i = np.argmax(abs(np.array(rhv[p])))
            self.maxval[p].set(rhv[p][i])
            self.maxname[p].set(corrector_pvs[i])

            w = xy_corrector_values[p]
            self.wf["current"][p].set(w)

            rw = rhv[p]
            self.wf["mag"][p].set(rw)

        # update individual records on waveform change. we must latch the
        # change to prevent the record and waveform from recursively updating
        if self.latched:
            self.update_individual_from_wf(*self.latched)
            self.latched = None
            return

    def update_wf_from_individual(self, key, value, mode, element):
        """Update corrector enabled vector/waveform from individual records"""
        (k, i) = key
        r = self.wf[element][mode][k]
        # softioc returns an immutable reference to the numpy array, so we must copy it
        # and then modify the data before setting it back
        wf = np.copy(r.get())
        wf[i] = value
        r.set(wf)

    def create_info_waveforms(self):
        """Creates waveform PVs which collate 'I', 'MAG' and 'S' PVs for all
        horizontal and vertical correctors."""
        builder.SetDeviceName("SR-DI-EBPM-01")
        builder.WaveformOut(
            "S", initial_value=self.lattice.get_family_s("BPM"), datatype=np.float64
        )

        nm = (("HSTR", "SR-PC-HSTR-01"), ("VSTR", "SR-PC-VSTR-01"))

        self.wf["current"] = []
        self.wf["mag"] = []
        for family, device_prefix in nm:
            elements = self.lattice.get_elements(family)
            builder.SetDeviceName(device_prefix)
            self.wf["current"].append(
                builder.WaveformOut(
                    "I", initial_value=np.zeros(len(elements)), datatype=np.float64
                )
            )
            self.wf["mag"].append(
                builder.WaveformOut(
                    "MAG", initial_value=np.zeros(len(elements)), datatype=np.float64
                )
            )
            builder.WaveformOut(
                "S",
                initial_value=self.lattice.get_family_s(family),
                datatype=np.float64,
            )

    def create_control_and_waveform_pvs(self):
        """Create pythonSoftIOC PVs."""
        self.maxval = [None, None]
        self.maxname = [None, None]

        # Declare individual records and waveforms
        for dev in ["cor", "bpm"]:
            self.wf[dev] = {}
            self.records[dev] = {}
            for speed in self.SPEEDS:
                self.records[dev][speed] = [[], []]
                self.wf[dev][speed] = [None, None]  # Will be indexed by plane

        for p in self.PLANES:
            # Build vectors of maximum magnet values
            builder.SetDeviceName("SR-PC-{}STR-01".format("HV"[p]))
            self.maxval[p] = builder.aOut("MAXI", initial_value=0)
            self.maxname[p] = builder.stringOut("MAXNAME")

            # Build individual controls and connected waveforms
            device_name_func = {
                "cor": lambda p: "SR-PC-{}STR-01".format("HV"[p]),
                "bpm": lambda p: "SR-PC-{}BPM-01".format("HV"[p]),
            }
            for fam_type in self.FAMILIES.keys():
                fam, field = self.FAMILIES[fam_type][p]
                # Create waveform PVs
                for speed in self.SPEEDS:
                    builder.SetDeviceName(device_name_func[fam_type](p))
                    self.wf[fam_type][speed][p] = builder.WaveformOut(
                        f"{speed.upper()}:ENABLED",
                        on_update=lambda _, f=fam_type, s=speed, p=p: self.latch(
                            f, s, p
                        ),
                        initial_value=np.zeros(len(self.lattice.get_elements(fam))),
                        datatype=np.int32,
                    )
                # Create individual control PVs
                for n, c in enumerate(
                    self.lattice.get_element_device_names(fam, field)
                ):
                    # Replace bpm names with plane-dependent names
                    c = c.replace("DI-EBPM", "PC-{}BPM".format("HV"[p]))
                    builder.SetDeviceName(c)
                    for speed in self.SPEEDS:
                        self.records[fam_type][speed][p].append(
                            builder.mbbOut(
                                f"{speed.upper()}:DISABLED",
                                "Enabled",
                                "Disabled",
                                on_update=lambda x, n=n, p=p, s=speed, f=fam_type: (
                                    self.update_wf_from_individual((p, n), x, s, f)
                                ),
                            )
                        )

    def latch(self, device_type, speed, plane):
        """A latch to stop recursive calls between update_individual_from_wf() and
        update_wf_from_individual(). ie if we are updating the wf PVs from the
        individual PVs we apply a latch to stop the individual PVs from updating the
        waveforms."""
        self.latched = (device_type, speed, plane)

    def update_individual_from_wf(self, device, mode, plane):
        """Copies values from a single vector/waveform collation PV to a list of
        individual PVs."""
        for r, x in zip(
            self.records[device][mode][plane],
            self.wf[device][mode][plane].get(),
            strict=True,
        ):
            r.set(x)
