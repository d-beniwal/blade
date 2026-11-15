"""The real-beamline instrument (blade/instrument/epics.py) is READ-ONLY, and only verified PV mappings reach the simulator. No network, no EPICS needed.
Run: python -I tests/test_instrument_readonly.py"""
import re, sys, types
from dataclasses import replace
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from blade.instrument import epics as E, pvmap
from blade.instrument.base import Instrument, ReadOnlyError
from blade.instrument.readonly import ReadOnlyViolation


class FakeReader:
    """Stands in for blade.instrument.readonly.Reader: serves a dict, records every name it is asked for."""
    def __init__(self, data): self.data, self.asked = data, []
    def read(self, pv):
        self.asked.append(pv)
        return ("ok", str(self.data[pv])) if pv in self.data else ("no_response", "")


ics = pvmap.load_ics()
ic1 = ics["icB1"]
data = {ic1.counts_pv: 352000.0, ic1.time_pv: 2.0, "1ide1:m34.RBV": 1.5}
rd = FakeReader(data)
inst = E.EpicsReader(reader=rd)

# 1. it is an Instrument that refuses to be written - every way in
assert isinstance(inst, Instrument) and inst.writable is False
for name, val in (("samE.x", 0.1), ("und.gap", 10.0), ("nonsense", 1)):
    try:
        inst.set(name, val)
        raise AssertionError("set() did not refuse")
    except ReadOnlyError:
        pass
assert not hasattr(inst, "move") and not hasattr(inst, "put")
print("PASS set() always raises ReadOnlyError; there is no move/put")

# 2. the shipped mapping has nothing verified yet: controls are NOT readable as sim values, ICs are (display ground truth), reads go through the gate
assert inst.controls() == {}
try:
    inst.ctl("samE.x"); raise AssertionError("an unverified mapping was used")
except E.Unmapped as e:
    assert "not usable" in str(e)
try:
    inst.ctl("und.gap"); raise AssertionError("an unmapped control was read")
except E.Unmapped:
    pass
assert abs(inst.ic_kHz("icB1") - 352000.0 / 2.0 / 1e3) < 1e-9
assert rd.asked == [ic1.time_pv, ic1.counts_pv]
try:
    inst.read_pv("1ide1:m34.VAL"); raise AssertionError("a .VAL read passed the gate")
except ReadOnlyViolation:
    pass
assert "1ide1:m34.VAL" not in rd.asked
print("PASS unverified/unmapped controls are refused; IC rate read; a non-read field never reaches the reader")

# 3. a verified entry (scale + offset numbers) IS used: sim = scale * raw + offset; the display inverse is only a number for humans
e0 = pvmap.load_controls()["samE.x"]
ok_e = replace(e0, status="verified", scale=-1.0, offset=0.25)
inst.map = {**inst.map, "samE.x": ok_e}
assert abs(inst.ctl("samE.x") - (-1.5 + 0.25)) < 1e-12 and set(inst.controls()) <= {"samE.x"}
assert abs(ok_e.to_real_display(-1.25) - 1.5) < 1e-12
half = replace(e0, status="verified", scale=1.0, offset=None)
assert not half.usable                                  # verified but without a transform: still not used
snap = inst.snapshot()
assert snap["controls"]["samE.x"]["sim"] == -1.25 and snap["controls"]["samE.y"]["status"] == "no_response" and snap["controls"]["samE.y"]["usable_mapping"] is False
assert snap["ics"]["icB1"]["kHz_raw"] == 176.0 and "icE12" not in snap["ics"]
print("PASS a verified mapping is applied; snapshot reports unreadable / unverified items instead of guessing")

# 4. the camera channel is get-only (fake pvapy)
fake = types.ModuleType("pvapy")
class Chan:
    def __init__(self, name): self.name = name
    def get(self, req): return "frame"
    def put(self, *a): raise AssertionError("PUT REACHED THE CHANNEL")
fake.Channel = Chan
sys.modules["pvapy"] = fake
ch = E._GetOnlyChannel("1idGH1:Pva1:Image")
assert ch.get("x") == "frame"
for bad in ("put", "putGet", "monitor", "startMonitor"):
    try:
        getattr(ch, bad); raise AssertionError(f"{bad} reachable")
    except ReadOnlyViolation:
        pass
try:
    E.validate_name("bad name;rm"); raise AssertionError("bad channel name accepted")
except ReadOnlyViolation:
    pass
del sys.modules["pvapy"]
print("PASS the PVA channel exposes get only; channel names are validated")

# 5. the source has no write / monitor / process / acquire vocabulary
def code_of(path):
    src = Path(path).read_text()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    return re.sub(r'"""(?:.|\n)*?"""', "", code)
for f in ("blade/instrument/epics.py", "blade/instrument/pvmap.py"):
    code = code_of(ROOT / f)
    for tok in [r"\bcaput", r"\.put\(", r"\.putGet\(", r"\bsg_put", r"put_complete", r"\bpvput", r"\bmonitor", r"\.add_callback", r"\bstartMonitor", r"\.Acquire\b",
                r"os\.system", r"subprocess", r"shell\s*=\s*True", r"\beval\(", r"\bexec\(", r"\bsocket\b", r"\bp4p\b", r"\.process\(", r"\.VAL\b"]:
        assert not re.search(tok, code), f"forbidden token {tok} in {f}"
print("PASS epics.py / pvmap.py contain no write, monitor, process, acquire or shell vocabulary")

# 6. the package has no other route to the beamline: only readonly.py (and pyepics/pvapy inside epics.py) may import epics tooling
for f in (ROOT / "blade").rglob("*.py"):
    code = code_of(f)
    if f.name in ("readonly.py", "epics.py") and f.parent.name == "instrument":
        continue
    assert not re.search(r"^\s*(import|from)\s+(epics|pvapy|p4p|caproto)\b", code, re.M), f"{f.relative_to(ROOT)} imports an EPICS package outside the read-only gate"
print("PASS no module outside blade/instrument/{readonly,epics}.py imports an EPICS package")
print("instrument read-only OK")
