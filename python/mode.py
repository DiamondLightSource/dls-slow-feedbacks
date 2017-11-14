from softioc import builder
from pytac import load_csv


RING_MODES = ["SR", "SRI13", "SRI0913", "SRLE3ps", "SRLEm3ps",
              "SRLETHz", "SRI0913_MOGA", "SRI21", "VMX", "VMXSP", "VMXTHz",
              "DIAD", "DIADSP", "DIADTHz"]

DIAD_MODES = ['DIAD', 'DIADSP', 'DIADTHz']

DEFAULT_RING_MODE = 'VMX'

DATAROOT = "/dls_sw/work/common/matlab/mml/machine/diamondopsdata"


def load_pml_lattice(ringmode):
    lattice = load_csv.load(ringmode)
    return lattice


class RingMode(object):

    def __init__(self):
        self.records()
        self.listeners = []
        self.name = DEFAULT_RING_MODE
        self.lattice = load_pml_lattice(self.name)

    def records(self):
        builder.SetDeviceName('SR-CS-RING-01')
        self.mode = builder.mbbOut("MODE", on_update=self.set_mode,
                                   *zip(RING_MODES, range(len(RING_MODES))))

    def init(self):
        self.mode.set(RING_MODES.index(self.name))

    def set_mode(self, mode):
        self.name = RING_MODES[mode]
        lattice = load_pml_lattice(self.name)
        for l in self.listeners:
            l(lattice)

    def add_listener(self, listener):
        self.listeners.append(listener)
