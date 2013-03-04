"magnet position PVs"

import traceback
import mml
from softioc import builder
import cothread
from cothread.catools import caget, ca_nothing
from numpy import *

def bind1st(x, f):
    def g(*args, **kw):
        f(x, *args, **kw)
    return g

class magnets_server(object):

    def __init__(self):

        self.bpmen = zeros(len(mml.ao["bpmx"].s)) == 0

        self.wf = [None, None]

        builder.SetDeviceName("SR-DI-EBPM-01")
        builder.WaveformOut("S", initial_value = mml.ao["bpmx"].s)

        nm = (("hcm", 'SR-PC-HSTR-01'),
              ("vcm", 'SR-PC-VSTR-01'))

        for i, (k, v) in enumerate(nm):
            builder.SetDeviceName(v)
            w = builder.WaveformOut(
                "I", initial_value = zeros(len(mml.ao[k].s)))
            builder.WaveformOut("S", initial_value = mml.ao[k].s)
            self.wf[i] = w

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
        en = [None, None]

        # get corrector enables
        en[0] = caget("SR-PC-HSTR-01:ENABLED") == 0
        en[1] = caget("SR-PC-VSTR-01:ENABLED") == 0

        # get bpm enables
        bpmen = caget("SR-DI-EBPM-01:ENABLED") == 0


        # get corrector readbacks
        for p in range(2):
            pvs = mml.ao[fam[p]].readback[en[p]]
            hv[p] = caget(pvs)
            # update max value and name
            i = argmax(abs(array(hv[p])))
            self.maxval[p].set(hv[p][i])
            self.maxname[p].set(pvs[i])

        # write to waveforms (disabled are set to zero)
        for p in range(2):
            w = self.wf[p].get()
            w[en[p]] = hv[p]
            w[en[p] == False] = 0
            self.wf[p].set(w)

    def update(self, key, value):
        "update corrector enabled vector from individual records"
        (k, i) = key
        r = self.cenabled[k]
        wf = r.get()
        wf[i] = value
        r.set(wf)

    def create_controls(self):

        self.cenabled = [None, None]
        self.maxval = [None, None]
        self.maxname = [None, None]

        fams = ["hcm", "vcm"]
        records = [[], []]

        for p in range(2):
            f = fams[p]

            # build concentrator vector
            envec = (mml.ao[f].enabled == 0)
            builder.SetDeviceName("SR-PC-%sSTR-01" % "HV"[p])

            # maximum value and name
            self.maxval[p] = builder.aOut("MAXI", initial_value = 0)
            self.maxname[p] = builder.stringOut("MAXNAME")

            self.cenabled[p] = builder.WaveformIn("ENABLED",
                                                  initial_value = envec)
            # build individual controls
            for n, c in enumerate(mml.ao[f].devices):
                builder.SetDeviceName(c)
                r = builder.mbbOut('DISABLED', ("Enabled", 0), ("Disabled", 1),
                                   on_update = bind1st((p, n), self.update))
                records[p].append(r)
        self.records = records

    def write(self):
        # set initial control values
        for p in range(2):
            for n, r in enumerate(self.records[p]):
                r.set(self.cenabled[p].get()[n])
