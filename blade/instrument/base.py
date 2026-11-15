"""The ONE interface between BLADE's procedures/loop and "a beamline" - real or simulated.

A beamline, for BLADE, is a set of named CONTROLS (the twin's control names, e.g. `und.gap`, `slitEus.hsize`, `samE.x`), a few READ-OUTS (ion-chamber counts,
camera frames) and static knowledge about the machine (`sim`: distances, camera sizes, ... from `beamline_twins/<bl>/sim.json`). Everything an operator-level
procedure needs is here and nothing else:

    inst.ctl(name)            read-back of a control
    inst.set(name, value)     command a control; returns the read-back. Raises ReadOnlyError on an instrument that cannot be written
    inst.spec(name)           (lo, hi, unit, description)
    inst.ic_kHz(ic)           ion-chamber rate;  inst.mu_t()  foil-edge absorption read from the ICs
    inst.frame(cam, exposure=None, bin_=1)    one camera frame (numpy array)
    inst.wait(seconds)        let things settle (the simulator advances its clock; a real instrument sleeps)
    inst.snapshot()           every control + derived read-backs, as a JSON-safe dict

Two kinds of instrument exist:
  * `SimInstrument` (blade/instrument/sim.py): the virtual beamline - writable, has a hidden truth (tests/scoring only: `.truth()`).
  * `EpicsReader` (blade/instrument/epics.py): the real beamline - READ-ONLY by construction (user decision 2026-11-15: nothing in BLADE may command the real
    beamline for now). `set` always raises ReadOnlyError there; see that file for the guards.
Procedures must only use this interface (plus `inst.sim` / `inst.cams` / `inst.z`, which are static), so the same code runs on both."""


class ReadOnlyError(PermissionError):
    """Raised by any attempt to command (write) an instrument that is read-only (the real beamline)."""


class Instrument:
    name = "instrument"
    writable = False
    sim = None            # static machine knowledge (twin sim.json)
    cams = None           # camera info from the profile ({name: {"pixel_um": ...}})
    z = None              # {element id: distance from the source (m)}

    # -- reads ------------------------------------------------------------------------------------------------------------
    def controls(self):
        """{name: (lo, hi, unit, description)} of every control this instrument knows."""
        raise NotImplementedError

    def spec(self, name):
        return self.controls()[name]

    def ctl(self, name):
        raise NotImplementedError

    def ic_kHz(self, ic):
        raise NotImplementedError

    def mu_t(self):
        raise NotImplementedError

    def frame(self, cam, exposure=None, bin_=1):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError

    def camera_z_m(self, cam):
        """Distance of a camera from the source (m) - static knowledge."""
        return self.z[self.sim["cameras"][cam]["z_key"]]

    # -- writes (refused unless `writable`) ---------------------------------------------------------------------------------
    def set(self, name, value):
        raise ReadOnlyError(f"{self.name} instrument is read-only: refusing to set {name!r}")

    def wait(self, seconds):
        raise NotImplementedError
