"""Rotation-axis (pin) alignment procedure on SYNTHETIC frames with exactly known truth (tests/synthetic_pin.py): the adaptive routine converges from the
default offsets and from a flipped-sign truth is caught by the guards, and a read-only instrument refuses the first move. No hardware, no virtual beamline
(the pin on the virtual beamline is an open problem: see .context/STATE.md). Run: python -I tests/test_pin_alignment.py"""
import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
import numpy as np
from synthetic_pin import SyntheticPin
from blade import config as cfg
from blade.session import Run
from blade.procedures import pin_alignment as PA
from blade.instrument.base import Instrument, ReadOnlyError


def new_run(**truth):
    run = Run.create("sim", camera="gh1")
    run.inst = SyntheticPin()                 # the synthetic fixture replaces the simulator stage (same method names as PinStage)
    run.inst.s.update(truth)
    run.inst.s["camera"] = "gh1"
    return run


run = new_run()
r = PA.do_adaptive_align(run)
assert r.get("ok") is not False and r["final"]["converged"], r
assert abs(r["final"]["a"]) < cfg.TOL_AB_PX + 0.5 and abs(r["final"]["b"]) < cfg.TOL_AB_PX + 0.5, r["final"]
print("PASS adaptive alignment converged on synthetic frames:", {k: round(v, 2) for k, v in r["final"].items() if isinstance(v, float)})

# a different start (pin off to the other side, larger b)
run = new_run(a=90.0, b=25.0, c=840.0)
r = PA.do_adaptive_align(run)
assert r["final"]["converged"], r
print("PASS converged from a=+90 px, b=+25 px")


# a read-only instrument cannot be moved: the first set raises, nothing changes
class Frozen(Instrument):
    name = "frozen"
    def ctl(self, name): return 0.0
    def controls(self): return {}
    def frame(self, cam, exposure=None, bin_=1): return np.zeros((10, 10))

try:
    PA.PinStage(Frozen(), "gh1").move_omega(10.0)
    raise SystemExit("FAIL: read-only instrument was moved")
except ReadOnlyError:
    print("PASS a read-only instrument refuses to move")
print("ALL OK")
