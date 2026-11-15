"""Which real PV reads back which simulator control - and which ion chamber is which scaler channel. Used by the READ-ONLY reader and the sync.

Two sources, never mixed up:
  * controls: `beamline_twins/<bl>/control_pv_map.json` (hand-maintained). An entry is USABLE only if `status == "verified"` and `scale` and `offset` are numbers
    (sim = scale * raw + offset). Anything else is reported but never fed into the simulator (user rule 2026-11-13: no guessed assignments).
  * ion chambers: derived from `beamline_twins/<bl>/pv_map.json` (generated from the CS-Studio displays = ground truth): counts `<scaler>.S<n>` and time `<scaler>.T`.
There is deliberately NO real-ward direction: `to_real_display` only turns a simulator value into the number a HUMAN would read on the panel; nothing here
(or anywhere in BLADE) can send a value to the beamline."""
import json
from dataclasses import dataclass
from functools import lru_cache
from .. import paths
from .readonly import validate_pv


@dataclass(frozen=True)
class Entry:
    control: str
    pv: str                   # record, e.g. "1ide1:m34"
    field: str = "RBV"
    unit: str = ""
    status: str = "unverified"
    scale: float | None = None
    offset: float | None = None
    source: str = ""
    note: str = ""

    @property
    def pv_name(self):
        return validate_pv(f"{self.pv}.{self.field}")

    @property
    def usable(self):
        return self.status == "verified" and self.scale is not None and self.offset is not None

    def why_unusable(self):
        if self.usable:
            return None
        if self.status != "verified":
            return f"status is '{self.status}', not 'verified'"
        return "no numeric scale/offset"

    def to_sim(self, raw):
        if not self.usable:
            raise ValueError(f"{self.control}: mapping not usable ({self.why_unusable()})")
        return self.scale * float(raw) + self.offset

    def to_real_display(self, sim_value):
        """The number a person would read on the real panel for a simulator value. For DISPLAY only (a proposal shown to a human); not a command."""
        if not self.usable or not self.scale:
            return None
        return (float(sim_value) - self.offset) / self.scale


@dataclass(frozen=True)
class IcChannel:
    ic: str
    scaler: str               # record, e.g. "1id:S1:scaler1"
    channel: int
    preamp: str | None = None

    @property
    def counts_pv(self):
        return validate_pv(f"{self.scaler}.S{self.channel}")

    @property
    def time_pv(self):
        return validate_pv(f"{self.scaler}.T")


def _read(twin, name):
    return json.loads((paths.TWINS_DIR / twin / name).read_text())


@lru_cache(maxsize=4)
def load_controls(twin="1-ID"):
    doc = _read(twin, "control_pv_map.json")
    out = {}
    for name, e in doc["controls"].items():
        out[name] = Entry(control=name, pv=e["pv"], field=e.get("field", "RBV"), unit=e.get("unit", ""), status=e.get("status", "unverified"),
                          scale=e.get("scale"), offset=e.get("offset"), source=e.get("source", ""), note=e.get("note", ""))
    return out


@lru_cache(maxsize=4)
def load_ics(twin="1-ID"):
    """{ic id: IcChannel} for every ion chamber that has a read-out on the displays (icE12 has none, flagged in the twin)."""
    els = _read(twin, "pv_map.json")["elements"]
    out = {}
    for eid, e in els.items():
        for g in e.get("groups", []):
            if g.get("type") == "ic_readout" and g.get("scaler"):
                out[eid] = IcChannel(eid, g["scaler"]["record"], int(g["scaler"]["channel"]), (g.get("preamp") or {}).get("record"))
    return out


def coverage(twin="1-ID", control_names=None):
    """What the sync can and cannot see: usable / listed-but-unverified / missing controls, and the ICs."""
    ctl = load_controls(twin)
    names = list(control_names) if control_names is not None else None
    usable = sorted(n for n, e in ctl.items() if e.usable)
    unverified = sorted(n for n, e in ctl.items() if not e.usable)
    out = {"usable": usable, "listed_not_usable": {n: ctl[n].why_unusable() for n in unverified}, "ics": sorted(load_ics(twin))}
    if names is not None:
        out["no_mapping"] = sorted(n for n in names if n not in ctl)
    return out
