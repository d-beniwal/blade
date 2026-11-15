"""Shared helper for the procedures: they take an `Instrument` (blade/instrument/base.py); for convenience (tests, notebooks, older callers) a bare
`VirtualBeamline` world is accepted too and wrapped (no copy: the caller's world object is what changes)."""
import functools


def as_instrument(x):
    from ..instrument.base import Instrument
    if isinstance(x, Instrument):
        return x
    from ..vbl.world import VirtualBeamline
    if isinstance(x, VirtualBeamline):
        from ..instrument.sim import SimInstrument
        return SimInstrument(x)
    raise TypeError(f"expected an Instrument (or a VirtualBeamline), got {type(x).__name__}")


def accepts_world(fn):
    @functools.wraps(fn)
    def wrapper(inst, *a, **k):
        return fn(as_instrument(inst), *a, **k)
    return wrapper
