"magnet position PVs"

import traceback
import mml
from softioc import builder
import cothread
from cothread.catools import caget, ca_nothing, FORMAT_CTRL
from numpy import *


class magnets_server(object):

    def __init__(self):

        self.bpmen = zeros(len(mml.ao["bpmx"].s)) == 0

        self.wf = [None, None]
        self.rwf = [None, None]

        builder.SetDeviceName("SR-DI-EBPM-01")
        builder.WaveformOut("S", initial_value = mml.ao["bpmx"].s)

        nm = (("hcm", 'SR-PC-HSTR-01'),
              ("vcm", 'SR-PC-VSTR-01'))

        for i, (k, v) in enumerate(nm):
            builder.SetDeviceName(v)
            w = builder.WaveformOut(
                "I", initial_value = zeros(len(mml.ao[k].s)))
            rw = builder.WaveformOut(
                "MAG", initial_value = zeros(len(mml.ao[k].s)))
            builder.WaveformOut("S", initial_value = mml.ao[k].s)
            self.wf[i] = w
            self.rwf[i] = rw

        self.create_controls()


    def init(self):
        self.write()
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

        fam = ["hcm", "vcm"]
        hv = [None, None]
        mag = [None, None]
        rhv = [None, None]
        en = [None, None]

        # get corrector enables
        en[0] = caget("SR-PC-HSTR-01:SLOW:ENABLED") == 0
        en[1] = caget("SR-PC-VSTR-01:SLOW:ENABLED") == 0

        # get corrector readbacks
        for p in range(2):
            pvs = mml.ao[fam[p]].readback[en[p]]
            hv[p] = caget(pvs, format=FORMAT_CTRL)
            # convert to relative magnitude
            mag[p] = [x.upper_ctrl_limit - x.lower_ctrl_limit for x in hv[p]]
            rhv[p] = 2 * abs(array(hv[p]) / mag[p])
            # update max value and name
            i = argmax(abs(array(rhv[p])))
            self.maxval[p].set(rhv[p][i])
            self.maxname[p].set(pvs[i])

        # write to waveforms (disabled are set to zero)
        for p in range(2):
            w = self.wf[p].get()
            w[en[p]] = hv[p]
            w[en[p] == False] = 0
            self.wf[p].set(w)

            rw = self.rwf[p].get()
            rw[en[p]] = rhv[p]
            rw[en[p] == False] = 0
            self.rwf[p].set(rw)

    def update(self, key, value, mode, element):
        "update corrector enabled vector from individual records"
        (k, i) = key
        if element == 'cor':
            r = self.cenabled[mode][k]
        elif element == 'bpm':
            r = self.benabled[mode][k]
        else:
            raise ValueError
        wf = r.get()
        wf[i] = value
        r.set(wf)

    def create_controls(self):

        self.cenabled = {}
        self.cenabled['slow'] = [None, None]
        self.cenabled['fast'] = [None, None]
        self.benabled = {}
        self.benabled['slow'] = [None, None]
        self.benabled['fast'] = [None, None]
        self.maxval = [None, None]
        self.maxname = [None, None]

        corr_fams = ["hcm", "vcm"]
        bpm_fams = ["bpmx", "bpmy"]

        self.records = {}
        for dev in ['cor', 'bpm']:
            self.records[dev] = {}
            for speed in ['slow', 'fast']:
                self.records[dev][speed] = [[], []]

        for p in range(2):
            corr_fam = corr_fams[p]

            # build concentrator vector
            envec = (mml.ao[corr_fam].enabled == 0)
            builder.SetDeviceName("SR-PC-%sSTR-01" % "HV"[p])

            # maximum value and name
            self.maxval[p] = builder.aOut("MAXI", initial_value = 0)
            self.maxname[p] = builder.stringOut("MAXNAME")

            self.cenabled['slow'][p] = builder.WaveformIn("SLOW:ENABLED",
                                                  initial_value = envec)
            self.cenabled['fast'][p] = builder.WaveformIn("FAST:ENABLED",
                                                  initial_value = envec)
            # build individual controls
            for n, c in enumerate(mml.ao[corr_fam].devices):
                builder.SetDeviceName(c)
                self.records['cor']['slow'][p].append(
                    builder.mbbOut(
                        'SLOW:DISABLED', ("Enabled", 0), ("Disabled", 1),
                        on_update=lambda x, n=n, p=p:
                            self.update((p, n), x, 'slow', 'cor')))
                self.records['cor']['fast'][p].append(
                    builder.mbbOut(
                        'FAST:DISABLED', ("Enabled", 0), ("Disabled", 1),
                        on_update=lambda x, n=n, p=p:
                            self.update((p, n), x, 'fast', 'cor')))

            # Build slow and fast BPM enabled vectors
            bpm_fam = bpm_fams[p]  # One vector for both planes
            builder.SetDeviceName("SR-PC-%sBPM-01" % "HV"[p])
            for n, c in enumerate(mml.ao[bpm_fam].devices):
                self.records['bpm']['slow'][p].append(
                    builder.mbbOut(
                        '%03d:SLOW:DISABLED' % (n+1),
                        ("Enabled", 0), ("Disabled", 1),
                        on_update=lambda x, n=n, p=p:
                            self.update((p, n), x, 'slow', 'bpm')))
                self.records['bpm']['fast'][p].append(
                    builder.mbbOut(
                        '%03d:FAST:DISABLED' % (n+1),
                        ("Enabled", 0), ("Disabled", 1),
                        on_update=lambda x, n=n, p=p:
                            self.update((p, n), x, 'fast', 'bpm')))

            bpm_envec = zeros(len(mml.ao[bpm_fam].enabled))
            self.benabled['slow'][p] = builder.WaveformIn("SLOW:ENABLED",
                    initial_value = bpm_envec)
            self.benabled['fast'][p] = builder.WaveformIn("FAST:ENABLED",
                    initial_value = bpm_envec)

    def write(self):
        # set initial control values
        for mode in ['slow', 'fast']:
            for p in range(2):
                for n, r in enumerate(self.records['cor'][mode][p]):
                    r.set(self.cenabled[mode][p].get()[n])
                for n, r in enumerate(self.records['bpm'][mode][p]):
                    r.set(self.benabled[mode][p].get()[n])
