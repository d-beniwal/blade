"""`vbl` backend: the pin/rotation-axis alignment (`blade align ...`) runs on the full virtual beamline instead of the stand-alone simulator.

The beamline state lives in the shared virtual-beamline session (runs/vbl/default.json), so beam set-up done with the vbl_* tools (energy, slits,
camera) is what the pin sees, and the GUI page /vbl shows the same instrument. New session -> scenario 'ready_for_pin' (beam + flux good, pin in view).
SIMULATION ONLY: nothing here touches EPICS."""
import numpy as np
from .. import config as cfg
from ..vbl import store, imaging
from ..vbl.world import VirtualBeamline

MOTOR = {"x": "samE.x", "y": "samE.y", "z": "samE.z", "base": "samE.aerox"}


class VblInstrument:
    name = "vbl"

    def __init__(self, state=None, seed=0, camera=None, scenario="ready_for_pin", session=store.DEFAULT):
        self.session = session
        self.s = state or {"camera": camera or "gh1", "session": session, "n_acq": 0}
        w = store.load(session)
        if w is None:
            w = store.reset(seed, scenario, session)
        self.w = w

    # -- state -------------------------------------------------------------------------------------------------------------------------
    def _sync(self):
        self.w = store.load(self.session) or self.w          # the GUI / vbl_* tools may have changed the beamline since the last call

    def get_state(self):
        store.save(self.w, self.session)
        return self.s

    def get_omega(self):
        self._sync()
        return float(self.w.ctl("samE.ry"))

    def positions(self):
        self._sync()
        return {"omega": float(self.w.ctl("samE.ry")), **{k: float(self.w.ctl(v)) for k, v in MOTOR.items()}}

    def move_omega(self, deg):
        self._sync()
        self.w.set("samE.ry", float(deg))
        store.save(self.w, self.session)

    def move(self, motor, mm):
        if motor not in MOTOR:
            raise ValueError(f"unknown motor {motor}")
        self._sync()
        name = MOTOR[motor]
        self.w.set(name, float(self.w.ctl(name) + mm))
        store.save(self.w, self.session)

    def acquire(self):
        self._sync()
        img = imaging.render(self.w, self.s.get("camera") or "gh1")
        self.s["n_acq"] = self.s.get("n_acq", 0) + 1
        store.save(self.w, self.session)
        return img

    # -- truth (for tests only) --------------------------------------------------------------------------------------------------------
    def true_pin_col(self, omega=None):
        zc, uc, vc, p, rows, cols = self.w.camera_view(self.s.get("camera") or "gh1")
        ps = self.w.pin_state(omega)
        return (ps["u"] - uc) / p + (cols - 1) / 2.0
