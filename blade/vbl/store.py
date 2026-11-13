"""Persistent virtual-beamline session, shared by the MCP tools, the `vbl` backend of `blade align` and the GUI (/vbl). One JSON file per session under
runs/vbl/ (BLADE_RUNS respected): the whole world state (controls + hidden truth). SIMULATION ONLY."""
import json
import os
from .. import paths
from .world import VirtualBeamline

DEFAULT = "default"


def _dir():
    d = paths.RUNS_DIR / "vbl"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path(session=DEFAULT):
    if session != os.path.basename(session) or not session:
        raise ValueError("bad session name")
    return _dir() / f"{session}.json"


def exists(session=DEFAULT):
    return path(session).is_file()


def load(session=DEFAULT):
    """The session's VirtualBeamline, or None if it has not been created (call reset)."""
    f = path(session)
    if not f.is_file():
        return None
    return VirtualBeamline(state=json.loads(f.read_text()))


def save(world, session=DEFAULT):
    f = path(session)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(world.s, default=float))
    os.replace(tmp, f)


def reset(seed=0, scenario="startup", session=DEFAULT):
    w = VirtualBeamline(seed=seed, scenario=scenario)
    w.log(f"session reset: scenario={scenario} seed={seed}")
    save(w, session)
    return w


def require(session=DEFAULT):
    w = load(session)
    if w is None:
        raise RuntimeError("no virtual-beamline session yet: call vbl_reset first (scenario 'startup' = everything misaligned)")
    return w
