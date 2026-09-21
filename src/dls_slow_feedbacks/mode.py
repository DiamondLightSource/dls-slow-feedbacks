from collections.abc import Callable
from pathlib import Path

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

RING_MODES_D2 = ["48", "49"]

DEFAULT_RING_MODE = "I04"
DEFAULT_RING_MODE_D2 = "49"

DATAROOT = Path("/dls_sw/work/common/matlab/mml/machine-new/diamondopsdata")
DATAROOT_D2 = Path("/dls_sw/work/common/matlab/mml/machine-new/diamond2opsdata")


def load_pml_lattice(ringmode: str) -> EpicsLattice:
    """Load the elements of the lattice for a given ring mode."""
    # Increase CA timeouts to improve reliability
    cs = cothread_cs.CothreadControlSystem(timeout=5.0)
    lattice = load_csv.load(ringmode, control_system=cs)
    return lattice


class RingMode:
    """Manage the ring mode and its associated lattice."""

    def __init__(self, diamond2: bool = False) -> None:
        self.create_records(diamond2)
        self.listeners: list[Callable] = []
        if diamond2:
            self.name: str = DEFAULT_RING_MODE_D2
            self.dataroot: Path = DATAROOT_D2
        else:
            self.name: str = DEFAULT_RING_MODE
            self.dataroot: Path = DATAROOT
        self.lattice: EpicsLattice = load_pml_lattice(self.name)

    def init(self) -> None:
        """Assign the ring mode to its associated PV."""
        if self.name in RING_MODES_D2:
            self.mode.set(RING_MODES_D2.index(self.name))
        else:
            self.mode.set(RING_MODES.index(self.name))

    def set_mode(self, mode: int) -> None:
        """Set the ring mode and reload the lattice."""
        if self.name in RING_MODES_D2:
            self.name = RING_MODES_D2[mode]
        else:
            self.name = RING_MODES[mode]

        self.lattice = load_pml_lattice(self.name)
        for listener in self.listeners:
            listener(self.lattice, self.dataroot)

    def add_listener(self, listener: Callable) -> None:
        """Add a listener to respond to changes in the lattice."""
        self.listeners.append(listener)

    def create_records(self, diamond2: bool = False) -> None:
        """Define a pv for the ring mode."""
        if diamond2:
            ringmodes = RING_MODES_D2
        else:
            ringmodes = RING_MODES

        builder.SetDeviceName("SR-CS-RING-01")
        self.mode = builder.mbbOut(
            "MODE",
            *ringmodes,
            on_update=self.set_mode,
            always_update=True,
            ONSV="MAJOR",
        )
