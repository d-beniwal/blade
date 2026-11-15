"""The beamline probe (beamline_twins/tools/probe_readonly.py) can only READ. No network, no EPICS needed.
Usage: python -I tests/test_probe_readonly.py"""
import re, sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "beamline_twins/tools"))
import probe_readonly as P  # noqa: E402

# 1. the validator accepts reads and rejects everything that could act on a device
for ok in ["1idHEM:m1.DESC", "1idc:m25.RBV", "1id:userTran3.OUTB", "1id:userTran3.CLCL", "1id:S1:scaler1.S3", "1id:S1:scaler1.NM3", "S01ID-PSS:SES:BeamBlockingM", "1idSP5:cam1:Model_RBV"]:
    P.validate_pv(ok)
for bad in ["", "1idHEM:m1", "1idHEM:m1.VAL", "1idHEM:m1.PROC", "1idHEM:m1.SPMG", "1idHEM:m1.STOP", "1idHEM:m1.TWF", "1idHEM:m1.HOMF", "1idHEM:m1.JOGF", "1idHEM:m1.SET",
            "1idHEM:m1.DESC;x", "1idHEM:m1 .DESC", "1idHEM:m1.desc", "$(P)m1.DESC", "1idSP5:cam1:Acquire", "1idSP5:cam1:Model_RBV.PROC", "x" * 90, None, 5]:
    try:
        P.validate_pv(bad)
    except P.ReadOnlyViolation:
        continue
    raise AssertionError(f"validator accepted {bad!r}")
assert not (P.READ_FIELDS & {"VAL", "PROC", "SPMG", "STOP", "TWF", "TWR", "HOMF", "HOMR", "JOGF", "JOGR", "SET", "FOFF", "CNT", "CNT"})
print("PASS validator accepts only the read fields / allow-listed names")

# 2. every planned PV (all groups incl. generated ones) passes the validator
plan = P.select([])
assert len(plan) > 500 and all(P.validate_pv(pv) for _, pv in plan)
print(f"PASS whole plan ({len(plan)} PVs) is read-only")

# 3. the sources: no write, monitor, shell, eval anywhere; exactly one network read path, in the gate (blade/instrument/readonly.py), none in the probe itself
def _code(path):
    src = Path(path).read_text()
    body = re.sub(r"# ---- TRIPWIRE.*?# ---- end TRIPWIRE[^\n]*\n", "", src, flags=re.S)
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    return re.sub(r'"""(?:.|\n)*?"""', "", code)                  # docstrings may talk about writes
FORBIDDEN = [r"\bcaput", r"\.put\(", r"\bsg_put", r"put_complete", r"\bpvput", r"\bcamonitor", r"\.add_callback", r"os\.system", r"shell\s*=\s*True", r"\bPopen\b", r"\beval\(", r"\bexec\(", r"\bsocket\b", r"\bpvapy\b", r"\bp4p\b"]
gate = ROOT / "blade/instrument/readonly.py"
for f in (P.__file__, gate):
    code = _code(f)
    for tok in FORBIDDEN:
        assert not re.search(tok, code), f"forbidden token {tok} in {Path(f).name}"
pc, gc = _code(P.__file__), _code(gate)
assert "subprocess" not in pc and ".caget(" not in pc
assert gc.count("subprocess.run(") == 1 and gc.count(".caget(") == 1
assert '[self._exe, "-t", "-w"' in gc and 'os.path.basename(exe) != "caget"' in gc
print("PASS sources have one read path (caget, in the gate) and no write/monitor/shell tokens")

# 4. pyepics backend with a fake package: only caget is ever called, and every write entry point raises after Reader() is built
calls = []
fake = types.ModuleType("epics")
fake.caget = lambda pv, **k: calls.append(("get", pv)) or "x"
fake.caput = lambda *a, **k: calls.append(("PUT",))
fake.caput_many = lambda *a, **k: calls.append(("PUT",))
fake.ca = types.SimpleNamespace(put=lambda *a, **k: calls.append(("PUT",)), put_complete=lambda *a, **k: 1, sg_put=lambda *a, **k: 1)
class _PV:
    def put(self, *a, **k): calls.append(("PUT",))
fake.PV = _PV
sys.modules["epics"] = fake
r = P.Reader("pyepics")
for fn in (lambda: fake.caput("a", 1), lambda: fake.caput_many([]), lambda: fake.ca.put(1, 2), lambda: fake.ca.sg_put(1), lambda: fake.PV().put(1)):
    try:
        fn()
    except P.ReadOnlyViolation:
        continue
    raise AssertionError("a write entry point was not disabled")
assert r.read("1idHEM:m1.DESC") == ("ok", "x") and calls == [("get", "1idHEM:m1.DESC")]
try:
    r.read("1idHEM:m1.VAL")
    raise AssertionError("read() accepted .VAL")
except P.ReadOnlyViolation:
    pass
assert calls == [("get", "1idHEM:m1.DESC")]
del sys.modules["epics"]
print("PASS pyepics backend: writes are disabled, only caget is called, a bad name never reaches the network")

# 5. default run and an unconfirmed --run contact nothing
class Boom:
    def __init__(self, *a, **k): raise AssertionError("network backend constructed")
P.Reader = Boom
assert P.main([]) == 0 and P.main(["--group", "hem"]) == 0
import builtins
builtins.input = lambda *_: "no"
assert P.main(["--run", "--group", "hem"]) == 1
print("PASS default listing and an unconfirmed --run never construct a reader")
print("probe_readonly OK")
