"""Optimize: run a procedure on a COPY of the model and turn what it changed into a PROPOSAL.

The procedures (blade/procedures: gap/Th2/energy, camera, slits, ...) are written for any `Instrument`; here they run on a private copy of the simulator that
sync + estimate have made agree with the real beamline. The control values they end up with, compared with the values they started from, are the proposed changes.
A proposal is DATA (what to set, in simulator coordinates and - where the mapping is verified - the number to read on the real panel); applying it to a read-only
instrument raises ReadOnlyError, so BLADE can propose and a human can act, but BLADE cannot command the beamline."""
from dataclasses import dataclass, field
from ..instrument import pvmap
from ..instrument.base import Instrument
from ..instrument.sim import SimInstrument

# controls that are only intermediate settings of a procedure (restored at its end) are filtered by comparing start and end values; these tolerances drop numerical dust
# controls with hysteresis must be approached from one side (logbooks: "open to ~9.5 mm first, then setundgap"): control -> how far to overshoot on the open side (mm)
APPROACH_FROM_OPEN_MM = {"und.gap": 0.3}
TOL = {"mm": 5e-4, "deg": 5e-5, "keV": 5e-5, "urad": 5e-3, "s": 1e-4, "idx": 0.5, "": 0.5}


@dataclass
class Change:
    control: str
    before: object
    after: object
    unit: str = ""
    real_display: float | None = None       # the number a person would read on the real panel after the change (only with a verified mapping)
    pv: str | None = None                    # the PV that reads it back (information only)
    mapped: bool = False
    approach_open_mm: float = 0.0            # >0: open this much beyond the target first, then close to it (hysteresis)

    def to_dict(self):
        return self.__dict__.copy()


@dataclass
class Proposal:
    procedure: str
    changes: list
    predicted: dict = field(default_factory=dict)        # model metrics before/after the whole procedure
    result: dict | None = None                           # what the procedure returned (scans, fits)
    notes: list = field(default_factory=list)

    def to_dict(self):
        return {"procedure": self.procedure, "changes": [c.to_dict() for c in self.changes], "predicted": self.predicted, "notes": self.notes,
                "result": self.result}

    def apply(self, inst: Instrument):
        """Command the proposed values on `inst`. A read-only instrument (the real beamline) raises ReadOnlyError at the first change - by design."""
        for c in self.changes:
            if c.approach_open_mm:
                inst.set(c.control, c.after + c.approach_open_mm)
            inst.set(c.control, c.after)
        return [c.control for c in self.changes]


def _metrics(m: SimInstrument, ics=("icB1", "icE4")):
    out = {}
    for ic in ics:
        try:
            out[f"{ic}_kHz"] = round(float(m.ic_kHz(ic)), 3)
        except Exception:
            pass
    return out


def propose(model: SimInstrument, procedure, *args, twin="1-ID", metrics=_metrics, **kw):
    """Run `procedure(inst, *args, **kw)` on a copy of `model`; return the Proposal (the model itself is untouched)."""
    work = model.copy()
    specs = work.controls()
    before = dict(work.world.s["ctl"])
    m0 = metrics(work)
    res = procedure(work, *args, **kw)
    after = dict(work.world.s["ctl"])
    m1 = metrics(work)
    mapping = pvmap.load_controls(twin)
    changes = []
    for name, b in before.items():
        a = after[name]
        unit = specs[name][2] if name in specs else ""
        if isinstance(b, str) or isinstance(a, str):
            if a == b:
                continue
        elif abs(float(a) - float(b)) <= TOL.get(unit, 1e-6):
            continue
        e = mapping.get(name)
        real = e.to_real_display(a) if (e is not None and e.usable and not isinstance(a, str)) else None
        changes.append(Change(name, b, a, unit, real, e.pv_name if e else None, bool(e and e.usable), APPROACH_FROM_OPEN_MM.get(name, 0.0)))
    unmapped = [c.control for c in changes if not c.mapped]
    notes = [f"{c.control}: approach from the open side (set {c.after + c.approach_open_mm:.4f} first, then {c.after:.4f}) because of hysteresis" for c in changes if c.approach_open_mm]
    if unmapped:
        notes.append(f"{len(unmapped)} proposed change(s) have no verified PV mapping: the proposal is in simulator coordinates only for {unmapped}")
    try:
        import json
        res_json = json.loads(json.dumps(res, default=float))
    except Exception:
        res_json = None
    return Proposal(getattr(procedure, "__name__", str(procedure)), changes, {"before": m0, "after": m1}, res_json, notes)
