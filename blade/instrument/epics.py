"""`EpicsReader`: the REAL beamline as a READ-ONLY `Instrument`. It can look; it cannot touch.

  ctl(name)       read-back of a control, from its verified PV mapping (blade/instrument/pvmap.py); an unmapped / unverified control raises `Unmapped`
  ic_kHz(ic)      ion-chamber RATE in raw kHz (scaler counts / count time); the preamp gain is NOT removed (gain = rate^-0.955, see physics/fits/flux.md)
  frame(cam)      ONE camera frame: a PVA GET of the NTNDArray image (no waiting for a trigger, no acquisition control)
  snapshot()      raw reads of every mapped PV + the ICs, with per-item status - the input of blade.loop.sync
  set(...)        ALWAYS raises ReadOnlyError (inherited). There is no put / monitor / process / acquire call anywhere in this file (tests/test_instrument_readonly.py
                  scans the source for them), every channel-access read goes through blade/instrument/readonly.py (name allow-list + tripwire on pyepics writes),
                  and the PVA channel is wrapped so that only `get` exists.
User decision 2026-11-15: BLADE does not command the real beamline. Commanding it would be a new, separate, explicitly requested piece of work."""
import time
import numpy as np
from .. import config as cfg
from . import pvmap
from .base import Instrument, ReadOnlyError
from .readonly import Reader, validate_pv, ReadOnlyViolation


class Unmapped(KeyError):
    """The control has no usable (verified) PV mapping, so the real beamline's value of it is not known to BLADE."""


class _GetOnlyChannel:
    """Wraps a pvapy Channel so that ONLY `get` is reachable (belt and braces: this file never calls anything else anyway)."""

    def __init__(self, pv_name):
        import pvapy as pva
        self._chan = pva.Channel(pv_name)

    def get(self, request):
        return self._chan.get(request)

    def __getattr__(self, name):
        raise ReadOnlyViolation(f"channel attribute {name!r} is not available: the PVA channel is get-only")


class EpicsReader(Instrument):
    name = "epics-readonly"
    writable = False

    def __init__(self, twin="1-ID", reader=None, backend="auto", timeout=2.0):
        from ..vbl.world import load_sim, control_specs
        self.twin = twin
        self._reader = reader or Reader(backend, timeout)
        self.sim, self.z = load_sim(twin), {k: v for k, v in load_sim(twin)["z_m"].items() if not k.startswith("_")}
        self.cams = cfg.CAMERA_INFO
        self._specs = control_specs(twin)
        self.map = pvmap.load_controls(twin)
        self.ics = pvmap.load_ics(twin)

    # -- the one primitive ----------------------------------------------------------------------------------------------------
    def read_pv(self, pv):
        """(status, text) of one validated read ('ok' | 'no_response' | 'error')."""
        return self._reader.read(validate_pv(pv))

    def read_float(self, pv):
        st, v = self.read_pv(pv)
        if st != "ok":
            raise ConnectionError(f"{pv}: {st} {v}")
        return float(v)

    # -- Instrument interface -------------------------------------------------------------------------------------------------
    def controls(self):
        return {n: s for n, s in self._specs.items() if n in self.map and self.map[n].usable}

    def ctl(self, name):
        e = self.map.get(name)
        if e is None:
            raise Unmapped(f"{name}: no PV mapping at all (beamline_twins/{self.twin}/control_pv_map.json)")
        if not e.usable:
            raise Unmapped(f"{name}: mapping not usable ({e.why_unusable()}); raw readback is available via read_pv('{e.pv_name}')")
        return e.to_sim(self.read_float(e.pv_name))

    def ic_kHz(self, ic):
        ch = self.ics.get(ic)
        if ch is None:
            raise Unmapped(f"{ic}: no scaler channel on the CS-Studio displays")
        t = self.read_float(ch.time_pv)
        if t <= 0:
            raise ConnectionError(f"{ch.time_pv}: count time {t}")
        return self.read_float(ch.counts_pv) / t / 1e3

    def mu_t(self):
        raise NotImplementedError("mu_t needs two mapped ICs around the foil; derive it from the snapshot's IC rates (blade.loop.sync) instead")

    def frame(self, cam, exposure=None, bin_=1):
        """One frame of camera `cam` (profile `cameras.<cam>.pv_prefix` + `camera_pva_suffix`). `exposure`/`bin_` are ignored: the camera is not touched."""
        prefix = (cfg.CAMERA_INFO.get(cam) or {}).get("pv_prefix")
        if not prefix:
            raise Unmapped(f"camera {cam}: no pv_prefix in the profile")
        from pvapy.utility.adImageUtility import AdImageUtility
        chan = _GetOnlyChannel(validate_name(prefix + cfg.CAMERA_PVA_SUFFIX))
        pv = chan.get("field(value,dimension,uniqueId,attribute,codec,uncompressedSize)")
        _uid, img, *_ = AdImageUtility.reshapeNtNdArray(pv)
        return np.asarray(img)

    def snapshot(self):
        """Raw read of everything BLADE knows how to read. Items that cannot be read are reported, not guessed."""
        out = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "twin": self.twin, "controls": {}, "ics": {}}
        for name, e in self.map.items():
            st, v = self.read_pv(e.pv_name)
            rec = {"pv": e.pv_name, "status": st, "raw": None, "usable_mapping": e.usable, "mapping_status": e.status}
            if st == "ok":
                try:
                    rec["raw"] = float(v)
                    if e.usable:
                        rec["sim"] = e.to_sim(rec["raw"])
                except ValueError:
                    rec["status"] = f"not_a_number:{v}"
            out["controls"][name] = rec
        for ic, ch in self.ics.items():
            st_c, c = self.read_pv(ch.counts_pv)
            st_t, t = self.read_pv(ch.time_pv)
            rec = {"counts_pv": ch.counts_pv, "time_pv": ch.time_pv, "preamp": ch.preamp, "status": st_c if st_c != "ok" else st_t}
            if st_c == "ok" and st_t == "ok":
                try:
                    rec["kHz_raw"] = float(c) / float(t) / 1e3 if float(t) > 0 else None
                except (ValueError, ZeroDivisionError):
                    rec["status"] = "not_a_number"
            out["ics"][ic] = rec
        return out

    def wait(self, seconds):
        """Nothing to wait for on a read-only instrument (reads do not move anything); kept so procedures written for the simulator do not break."""
        return None

    # set(...) is inherited: raises ReadOnlyError


def validate_name(name):
    """A camera image channel name: same character restrictions as every PV name (no field part)."""
    import re
    if not re.match(r"^[A-Za-z0-9_:\-]+$", name) or len(name) > 80:
        raise ReadOnlyViolation(f"bad channel name {name!r}")
    return name
