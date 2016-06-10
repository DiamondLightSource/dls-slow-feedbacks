"magnet position PVs"

import traceback
import mml
from softioc import builder
import cothread
from cothread.catools import caget, ca_nothing, FORMAT_CTRL
from numpy import *


class magnets_server(object):


    PLANES = [0, 1]
    FAMILIES = {
            'cor': ['hcm', 'vcm'],
            'bpm': ['bpmx', 'bpmy'],
            }
    SPEEDS = ['slow', 'fast']


    def __init__(self):
        self.wf = {}
        self.records = {}
        self.create_info_waveforms()
        self.create_control_and_waveforms()

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
        fam = self.FAMILIES['cor']
        hv = [None, None]
        mag = [None, None]
        rhv = [None, None]
        en = [None, None]

        # get corrector enables
        en[0] = caget("SR-PC-HSTR-01:SLOW:ENABLED") == 0
        en[1] = caget("SR-PC-VSTR-01:SLOW:ENABLED") == 0

        # get corrector readbacks
        for p in self.PLANES:
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
        for p in self.PLANES:
            w = self.wf['current'][p].get()
            w[en[p]] = hv[p]
            w[en[p] == False] = 0
            self.wf['current'][p].set(w)

            rw = self.wf['mag'][p].get()
            rw[en[p]] = rhv[p]
            rw[en[p] == False] = 0
            self.wf['mag'][p].set(rw)

    def update(self, key, value, mode, element):
        "update corrector enabled vector from individual records"
        (k, i) = key
        r = self.wf[element][mode][k]
        wf = r.get()
        wf[i] = value
        r.set(wf)

    def create_info_waveforms(self):
        builder.SetDeviceName("SR-DI-EBPM-01")
        builder.WaveformOut("S", initial_value = mml.ao["bpmx"].s)

        nm = (("hcm", 'SR-PC-HSTR-01'),
              ("vcm", 'SR-PC-VSTR-01'))

        self.wf['current'] = []
        self.wf['mag'] = []
        for i, (k, v) in enumerate(nm):
            builder.SetDeviceName(v)
            self.wf['current'].append(builder.WaveformOut(
                "I", initial_value = zeros(len(mml.ao[k].s))))
            self.wf['mag'].append(builder.WaveformOut(
                "MAG", initial_value = zeros(len(mml.ao[k].s))))
            builder.WaveformOut("S", initial_value = mml.ao[k].s)

    def create_control_and_waveforms(self):
        self.maxval = [None, None]
        self.maxname = [None, None]

        bpm_fams = ["bpmx", "bpmy"]

        # Declare individule records and waveforms
        for dev in ['cor', 'bpm']:
            self.wf[dev] = {}
            self.records[dev] = {}
            for speed in self.SPEEDS:
                self.records[dev][speed] = [[], []]
                self.wf[dev][speed] = [None, None]

        for p in self.PLANES:
            corr_fam = self.FAMILIES['cor'][p]

            # build concentrator vector
            envec = (mml.ao[corr_fam].enabled == 0)
            builder.SetDeviceName("SR-PC-%sSTR-01" % "HV"[p])

            # maximum value and name
            self.maxval[p] = builder.aOut("MAXI", initial_value = 0)
            self.maxname[p] = builder.stringOut("MAXNAME")

            for speed in self.SPEEDS:
                self.wf['cor'][speed][p] = builder.WaveformIn(
                        speed.upper() + ":ENABLED", initial_value=envec)

            # build individual controls
            fam_pv_func = {
                    'cor': lambda _, s: '%s:DISABLED' % s.upper(),
                    'bpm': lambda p, s: '%s:%s:DISABLED' % ("HV"[p], s.upper())
                    }
            for fam_type in ['cor', 'bpm']:
                fam = self.FAMILIES[fam_type][p]
                for n, c in enumerate(mml.ao[fam].devices):
                    builder.SetDeviceName(c)
                    for speed in self.SPEEDS:
                        self.records[fam_type][speed][p].append(
                            builder.mbbOut(
                                fam_pv_func[fam_type](p, speed),
                                ("Enabled", 0), ("Disabled", 1),
                                on_update=lambda x, n=n, p=p:
                                    self.update((p, n), x, speed, fam_type)))

            bpm_fam = self.FAMILIES['bpm'][p]
            bpm_envec = zeros(len(mml.ao[bpm_fam].enabled))
            builder.SetDeviceName("SR-DI-EBPM-01")
            for speed in self.SPEEDS:
                self.wf['bpm'][speed][p] = builder.WaveformIn(
                        "%s:%s:DISABLED" % ("HV"[p], speed.upper()),
                        initial_value=bpm_envec)

    def write(self):
        # set initial control values
        for mode in self.SPEEDS:
            for p in self.PLANES:
                for dev in ['cor', 'bpm']:
                    for n, r in enumerate(self.records[dev][mode][p]):
                        r.set(self.wf[dev][mode][p].get()[n])
