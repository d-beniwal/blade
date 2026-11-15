"""Sync: read the beamline (READ-ONLY) and make the simulator agree with it - for the part BLADE can vouch for.

`take(instrument)` -> `Snapshot`: for the real beamline (`EpicsReader`) every value comes from a verified PV mapping; everything else is listed under `unmapped`
with the reason, never guessed. For a stand-in 'real' beamline that is itself a simulator (tests, dry runs) every control is available.
`apply(model, snapshot)` puts the usable control values into a model `SimInstrument` as state (no simulated motion) and says what it skipped.
`compare(model, snapshot)` lists where model and beamline disagree (controls, ion-chamber rates relative to each other)."""
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from ..instrument.base import Instrument
from ..instrument.sim import SimInstrument


@dataclass
class Snapshot:
    source: str                                   # instrument name ('epics-readonly', 'sim', ...)
    utc: str
    controls: dict                                # {control: value in SIMULATOR coordinates} - only what is usable
    unmapped: dict                                # {control: why it is not usable}
    ics_kHz: dict                                 # {ic: raw rate kHz} (gain not removed)
    raw: dict = field(default_factory=dict)       # the instrument's own raw snapshot (real: per-PV status), kept for the record
    frame: dict | None = None                     # {"camera", "shape", "path"?} of a captured frame, if any

    def to_dict(self):
        return asdict(self)


def take(inst: Instrument, camera=None, frame_dir=None, bin_=1):
    """One snapshot of `inst`. With `camera`, also captures one frame (a read; the camera is not touched) and stores it as .npy under `frame_dir` if given."""
    utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if isinstance(inst, SimInstrument):
        snap = inst.snapshot()
        sn = Snapshot(inst.name, utc, dict(snap["controls"]), {}, dict(snap["ic_kHz"]), {"time_s": snap["time_s"]})
    else:
        raw = inst.snapshot()                     # EpicsReader: per-PV records with mapping status
        controls = {n: r["sim"] for n, r in raw["controls"].items() if "sim" in r}
        unmapped = {}
        for n, r in raw["controls"].items():
            if "sim" in r:
                continue
            unmapped[n] = (f"not readable ({r['status']})" if r["status"] != "ok" else f"mapping not usable (status '{r['mapping_status']}'); raw {r['raw']}")
        ics = {i: r["kHz_raw"] for i, r in raw["ics"].items() if r.get("kHz_raw") is not None}
        sn = Snapshot(inst.name, raw.get("utc", utc), controls, unmapped, ics, raw)
    if camera:
        img = inst.frame(camera, bin_=bin_)
        sn.frame = {"camera": camera, "shape": list(img.shape), "bin": bin_}
        sn._image = img                           # kept in memory for the estimator; written out below if asked
        if frame_dir:
            import numpy as np
            p = Path(frame_dir) / f"frame_{camera}_{utc.replace(':', '')}.npy"
            p.parent.mkdir(parents=True, exist_ok=True)
            np.save(p, img)
            sn.frame["path"] = str(p)
    return sn


def apply(model: SimInstrument, snap: Snapshot, assume_thermal_equilibrium=True):
    """Assign the snapshot's usable controls to the model. Returns {"assigned": [...], "skipped": {...}, "not_in_snapshot": [...], "assumptions": [...]}: the
    third is the controls the model keeps at their previous values because the real beamline's value is unknown. ASSUMPTION (on by default, listed in the
    report): the HEM crystal's thermal state (a hidden, slow quantity driven by the WB-slit power) is at equilibrium for the synced WB-slit opening - true for a
    beamline that has been running for ~an hour; set assume_thermal_equilibrium=False for a cold start."""
    r = model.assign(snap.controls)
    r["assumptions"] = []
    if assume_thermal_equilibrium:
        w = model.world
        w.s["th2_thermal_deg"] = w._thermal_target()
        model._post()
        r["assumptions"].append("mono thermal state at equilibrium for the synced WB-slit opening")
    known = set(model.controls())
    r["not_in_snapshot"] = sorted(known - set(snap.controls))
    r["unmapped_reason"] = snap.unmapped
    return r


def compare(model: SimInstrument, snap: Snapshot, rel_tol=0.02):
    """Disagreements between the model (after `apply`) and the snapshot: controls (should be none by construction, listed for drift) and the ion-chamber pattern.
    IC rates are compared up to ONE common factor (the real gain / scaler scale is not known): ratio of each IC to icB1 (or the first common IC)."""
    out = {"controls": {}, "ics": {}}
    for n, v in snap.controls.items():
        if n in model.controls():
            d = float(model.ctl(n)) - float(v) if not isinstance(v, str) else (0.0 if model.ctl(n) == v else None)
            if d:
                out["controls"][n] = d
    common = [i for i in snap.ics_kHz if i in model.sim["ic"]["ids"] and snap.ics_kHz[i] > 0]
    if common:
        ref = "icB1" if "icB1" in common else common[0]
        sm_ref, mo_ref = snap.ics_kHz[ref], max(model.ic_kHz(ref), 1e-9)
        for i in common:
            real_ratio, model_ratio = snap.ics_kHz[i] / sm_ref, model.ic_kHz(i) / mo_ref
            out["ics"][i] = {"real_over_ref": real_ratio, "model_over_ref": model_ratio, "agree": abs(real_ratio / max(model_ratio, 1e-12) - 1.0) < max(rel_tol, 0.25)}
        out["ic_reference"] = ref
    return out


def save(snap: Snapshot, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap.to_dict(), indent=1, default=float))
    return p
