"""The twin and the s1id profile agree with the CS-Studio display registry (beamline_twins/1-ID/cs_registry.json), and the registry is not stale.
The check itself needs only the tracked registry; the staleness part runs only when the display folder (paths 'cs_displays') is present.
Usage: python -I tests/test_cs_registry.py"""
import json, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "beamline_twins/tools"))
import csdisplays as C  # noqa: E402
from blade import paths  # noqa: E402

assert C.check("1-ID") == 0, "twin/profile contradict the CS-Studio displays (see ERROR lines above)"
print("PASS twin + profile have no contradictions with the display registry")
reg = json.loads((ROOT / "beamline_twins/1-ID/cs_registry.json").read_text())
# spot facts read straight off the displays (the settled mappings of 2026-11-13)
assert reg["cameras"]["1idPG1:"]["elements"] == ["radiograph"] and reg["cameras"]["1idGH1:"]["elements"] == ["tomoE"] and reg["cameras"]["1idSP5:"]["elements"] == ["tomoC"]
ms = {m["pv"]: m["name"] for d in reg["elements"]["samE"]["devices"] for m in d.get("motors", [])}
assert ms["1ide1:m34"] == "samX" and ms["1ide1:m35"] == "samY" and ms["1ide1:m36"] == "samZ" and ms["1ide:m9"].startswith("Aero Rot")
ic = [d["ic"] for d in reg["elements"]["icE3"]["devices"] if "ic" in d][0]
assert ic["counts_pv"] == "1ide2:S1:scaler1.S5" and ic["preamp"] == "1ide:A3"
print("PASS cameras, sample-stage motors, IC read-out as on the displays")
d1 = paths.knowledge_dir("cs_displays", "1-ID") / "1id"
if d1.is_dir():
    import os
    old = (ROOT / "beamline_twins/1-ID/cs_registry.json").read_text()
    C.extract("1-ID")
    new = (ROOT / "beamline_twins/1-ID/cs_registry.json").read_text()
    (ROOT / "beamline_twins/1-ID/cs_registry.json").write_text(old)
    assert old == new, "cs_registry.json is stale: run beamline_twins/tools/csdisplays.py extract"
    print("PASS registry matches a fresh extraction of the displays")
else:
    print("SKIP staleness: display folder not available")
print("cs registry OK")
