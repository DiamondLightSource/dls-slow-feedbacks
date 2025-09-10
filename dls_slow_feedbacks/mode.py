from pytac import cothread_cs, load_csv
from softioc import builder


RING_MODES = [
    "SR",
    "UNUSED",
    "SRI0913",
    "I04",
    "SRLEm3ps",
    "SRLETHz",
    "I04SP",
    "I04THz",
    "VMX",
    "VMXSP",
    "VMXTHz",
    "DIAD",
    "DIADSP",
    "DIADTHz",
]

D2_RING_MODES = [
    "48",
]

RING_MODES.extend(D2_RING_MODES)

DEFAULT_RING_MODE = "48"

DATAROOT = "/home/zrv91478/Documents"


def load_pml_lattice(ringmode):
    # Increase CA timeouts to improve reliability
    cs = cothread_cs.CothreadControlSystem(timeout=5.0)

    lattice = load_csv.load(ringmode, control_system=cs)
    return lattice


class RingMode(object):
    def __init__(self):
        self.records()
        self.listeners = []
        self.name = DEFAULT_RING_MODE
        self.lattice = load_pml_lattice(self.name)

    def records(self):
        builder.SetDeviceName("SR-CS-RING-01")
        self.mode = builder.mbbOut(
            "MODE",
            on_update=self.set_mode,
            always_update=True,
            *RING_MODES,
            ONSV="MAJOR"
        )

    def init(self):
        self.mode.set(RING_MODES.index(self.name))

    def set_mode(self, mode):
        self.name = RING_MODES[mode]
        self.lattice = load_pml_lattice(self.name)
        for listener in self.listeners:
            listener(self.lattice)

    def add_listener(self, listener):
        self.listeners.append(listener)
