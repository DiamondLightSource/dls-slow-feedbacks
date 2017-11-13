"waveforms and control PVs"

import traceback
import pytac
from softioc import builder
import cothread
from cothread.catools import caget, ca_nothing, FORMAT_CTRL
import numpy as np


class WaveformsServer(object):

    PLANES = [0, 1]
    FAMILIES = {
            'cor': [('HSTR', 'b0'), ('VSTR', 'a0')],
            'bpm': [('BPM', 'x'), ('BPM', 'y')]
            }
    SPEEDS = ['slow', 'fast']

    def __init__(self, ring_mode):
        self.lattice = ring_mode.lattice
        self.wf = {}
        self.records = {}
        self.latched = None
        self.create_info_waveforms()
        self.create_control_and_waveform_pvs()

    def init(self):
        for device in ['cor', 'bpm']:
            for mode in self.SPEEDS:
                for plane in self.PLANES:
                    self.write(device, mode, plane)
        cothread.Spawn(self.timer)

    def timer(self):
        while True:
            try:
                cothread.Sleep(1.0)
                self.tick()
            except ca_nothing, pv_error:
                print 'PV error', pv_error
            except:
                traceback.print_exc()

    def tick(self):
        "read from individual correctors, write to corrector vector"
        fam = self.FAMILIES['cor']
        hv = [None, None]
        mag = [None, None]
        rhv = [None, None]

        # get corrector readbacks
        for p in self.PLANES:
            pvs = self.lattice.get_pv_names(fam[p][0], fam[p][1], pytac.RB)
            hv[p] = caget(pvs, format=FORMAT_CTRL)
            # convert to relative magnitude
            mag[p] = [x.upper_ctrl_limit - x.lower_ctrl_limit for x in hv[p]]
            rhv[p] = 2 * abs(np.array(hv[p]) / mag[p])
            # update max value and name
            i = np.argmax(abs(np.array(rhv[p])))
            self.maxval[p].set(rhv[p][i])
            self.maxname[p].set(pvs[i])

            w = self.wf['current'][p].get()
            w = hv[p]
            self.wf['current'][p].set(w)

            rw = self.wf['mag'][p].get()
            rw = rhv[p]
            self.wf['mag'][p].set(rw)

        # update individule records on waveform change. we must latch the
        # change to prevent the record and waveform from recursivly updating
        if self.latched:
            self.write(*self.latched)
            self.latched = None
            return

    def update(self, key, value, mode, element):
        "update corrector enabled vector from individual records"
        (k, i) = key
        r = self.wf[element][mode][k]
        wf = r.get()
        wf[i] = value
        r.set(wf)

    def create_info_waveforms(self):
        builder.SetDeviceName("SR-DI-EBPM-01")
        builder.WaveformOut("S", initial_value = self.lattice.get_family_s("BPM"))

        nm = (("HSTR", 'SR-PC-HSTR-01'),
              ("VSTR", 'SR-PC-VSTR-01'))

        self.wf['current'] = []
        self.wf['mag'] = []
        for i, (k, v) in enumerate(nm):
            elements = self.lattice.get_elements(k)
            builder.SetDeviceName(v)
            self.wf['current'].append(builder.WaveformOut(
                "I", initial_value = np.zeros(len(elements))))
            self.wf['mag'].append(builder.WaveformOut(
                "MAG", initial_value = np.zeros(len(elements))))
            builder.WaveformOut("S", initial_value = self.lattice.get_family_s(k))

    def create_control_and_waveform_pvs(self):
        self.maxval = [None, None]
        self.maxname = [None, None]

        # Declare individule records and waveforms
        for dev in ['cor', 'bpm']:
            self.wf[dev] = {}
            self.records[dev] = {}
            for speed in self.SPEEDS:
                self.records[dev][speed] = [[], []]
                self.wf[dev][speed] = [None, None]  # Will be indexed by plane

        for p in self.PLANES:
            # Build vectors of maximum magnet values
            builder.SetDeviceName("SR-PC-%sSTR-01" % "HV"[p])
            self.maxval[p] = builder.aOut("MAXI", initial_value = 0)
            self.maxname[p] = builder.stringOut("MAXNAME")

            # Build individual controls and connected waveforms
            device_name_func = {
                    'cor': lambda p: "SR-PC-%sSTR-01" % "HV"[p],
                    'bpm': lambda p: "SR-PC-%sBPM-01" % "HV"[p]
                    }
            for fam_type in self.FAMILIES.keys():
                fam, field = self.FAMILIES[fam_type][p]
                ## Create waveform PVs
                for speed in self.SPEEDS:
                    builder.SetDeviceName(device_name_func[fam_type](p))
                    self.wf[fam_type][speed][p] = builder.WaveformOut(
                        "%s:ENABLED" % speed.upper(),
                        on_update=lambda _, f=fam_type, s=speed, p=p:
                            self.latch(f, s, p),
                        initial_value=np.zeros(len(self.lattice.get_elements(fam))))
                ## Create individual control PVs
                for n, c in enumerate(self.lattice.get_device_names(fam, field)):
                    # Replace bpm names with plane-dependent names
                    c = c.replace('DI-EBPM', 'PC-%sBPM' % 'HV'[p])
                    builder.SetDeviceName(c)
                    for speed in self.SPEEDS:
                        self.records[fam_type][speed][p].append(
                            builder.mbbOut(
                                '%s:DISABLED' % speed.upper(),
                                ("Enabled", 0), ("Disabled", 1),
                                on_update =
                                    lambda x, n=n, p=p, s=speed, f=fam_type:
                                        self.update((p, n), x, s, f)))

    def latch(self, device_type, speed, plane):
        self.latched = (device_type, speed, plane)

    def write(self, device, mode, plane):
        for r, x in zip(self.records[device][mode][plane],
                        self.wf[device][mode][plane].get()):
            r.set(x)
