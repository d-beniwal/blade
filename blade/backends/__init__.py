"""Instrument backends: `sim` (simulator, default) and `epics` (real beamline, pvapy + pyepics)."""
from .. import config as cfg


def get_backend(name, state=None, seed=0, camera=None):
    if name not in cfg.BACKENDS:
        raise NotImplementedError(f"backend '{name}' is not enabled in profile '{cfg.PROFILE}' (backends: {list(cfg.BACKENDS)})")
    if name == "sim":
        from .sim import SimInstrument
        return SimInstrument(state, seed)
    if name == "epics":   # real beamline: needs an explicit --camera (pixel size / PVs)
        from .epics import EpicsInstrument
        return EpicsInstrument(state, camera=camera or (state or {}).get("camera"))
    raise NotImplementedError(f"unknown backend '{name}'. Use --backend sim (simulator) or --backend epics --camera <name> (real beamline).")
