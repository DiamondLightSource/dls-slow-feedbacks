from softioc import builder


RING_MODES = ["SR", "SRI13", "SRI0913", "SRLE3ps", "SRLEm3ps",
              "SRLETHz", "SRI0913_MOGA", "SRI21", "VMX", "VMXSP", "VMXTHz",
              "DIAD", "DIADSP", "DIADTHz"]

DIAD_MODES = ['DIAD', 'DIADSP', 'DIADTHz']


class RingMode(object):

    def __init__(self):
        self.records()
        self.listeners = []

    def records(self):
        builder.SetDeviceName('SR-CS-RING-01')
        self.mode = builder.mbbOut("MODE", on_update=self.set_mode,
                                   *zip(RING_MODES, range(len(RING_MODES))))

    def init(self):
        self.mode.set(RING_MODES.index("VMX"))

    def set_mode(self, mode):
        for l in self.listeners:
            l(RING_MODES[mode])

    def add_listener(self, listener):
        self.listeners.append(listener)
