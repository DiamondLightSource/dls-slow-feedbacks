from collections.abc import Callable

from pytac import cothread_cs, load_csv
from pytac.lattice import EpicsLattice
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

D2_RING_MODES = ["48", "49"]
RING_MODES.extend(D2_RING_MODES)

DEFAULT_RING_MODE = "49"

DATAROOT = "/dls_sw/work/common/matlab/mml/machine-new/diamondopsdata"


def load_pml_lattice(ringmode: str) -> EpicsLattice:
    """Load the elements of the lattice for a given ring mode."""
    # Increase CA timeouts to improve reliability
    cs = cothread_cs.CothreadControlSystem(timeout=5.0)
    lattice = load_csv.load(ringmode, control_system=cs)
    return lattice


class RingMode:
    """Manage the ring mode and its associated lattice."""

    def __init__(self) -> None:
        self.create_records()
        self.listeners: list[Callable] = []
        self.name: str = DEFAULT_RING_MODE
        self.lattice: EpicsLattice = load_pml_lattice(self.name)

    def init(self) -> None:
        """Assign the ring mode to its associated PV."""
        self.mode.set(RING_MODES.index(self.name))

    def set_mode(self, mode: int) -> None:
        """Set the ring mode and reload the lattice."""
        self.name = RING_MODES[mode]
        self.lattice = load_pml_lattice(self.name)
        for listener in self.listeners:
            listener(self.lattice)

    def add_listener(self, listener: Callable) -> None:
        """Add a listener to respond to changes in the lattice."""
        self.listeners.append(listener)

    def create_records(self) -> None:
        """Define a pv for the ring mode."""
        builder.SetDeviceName("SR-CS-RING-01")
        self.mode = builder.mbbOut(
            "MODE",
            *RING_MODES,
            on_update=self.set_mode,
            always_update=True,
            ONSV="MAJOR",
        )
