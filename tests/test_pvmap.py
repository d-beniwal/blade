"""Every twin element exposes its PVs (beamline_twins/1-ID/pv_map.json, built from the CS-Studio displays) in the /api/twin payload.
Usage: python -I tests/test_pvmap.py"""
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
from blade import twin_api

t = twin_api.twin_payload("s1id")["twin"]
els = {e["id"]: e for e in t["elements"]}
assert t["pv_templates"] and {"motor", "preamp", "scaler", "slit_axis"} <= set(t["pv_templates"])
nomap = sorted(i for i, e in els.items() if not e["pvmap"])
assert nomap == ["endB", "shutter_a", "undulator"], nomap            # only elements that are not buttons on the operator layout
bad = []
for i, e in els.items():
    if e["kind"] == "ic" and i != "icE12":
        g = [g for g in e["pvmap"]["groups"] if g["type"] == "ic_readout"]
        if not (g and ".S" in g[0]["readback"]["pv"] and g[0]["preamp"]["record"] and g[0]["scaler"]["record"]):
            bad.append(i)
assert not bad, bad
assert els["icB1"]["pvmap"]["groups"][0]["readback"]["pv"] == "1id:S1:scaler1.S3"
assert els["icE3"]["pvmap"]["groups"][0]["readback"]["pv"] == "1ide2:S1:scaler1.S5"
assert not any(g["type"] == "ic_readout" for g in els["icE12"]["pvmap"]["groups"])          # no IC1+2 read-out button exists on the E display
assert any(g["type"] == "motors" for g in els["foilB"]["pvmap"]["groups"])
assert any(g["type"] == "slit" for g in els["slitB"]["pvmap"]["groups"])
assert any(g["type"] == "camera" for g in els["tomoC"]["pvmap"]["groups"])
print("pvmap ok:", len(els) - len(nomap), "elements mapped;", sum(1 for e in els.values() if e["kind"] == "ic"), "ion chambers")
