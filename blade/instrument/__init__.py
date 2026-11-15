"""Instruments: the one interface (`Instrument`) between procedures/loop and a beamline, with the simulator (`SimInstrument`) and the READ-ONLY real-beamline
reader (`blade.instrument.epics.EpicsReader`, imported on demand: it needs pyepics). See blade/instrument/base.py."""
from .base import Instrument, ReadOnlyError
from .sim import SimInstrument

__all__ = ["Instrument", "ReadOnlyError", "SimInstrument"]
