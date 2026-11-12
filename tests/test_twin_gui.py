"""Twin viewer test (no hardware, stdlib only): boots the real GUI server on a free port and checks the twin routes, profile switching and photo safety.
Run: python -I tests/test_twin_gui.py"""
import json, os, sys, tempfile, threading, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
from blade import config as cfg
from blade.gui import H

srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"


def get(path):
    try:
        with urllib.request.urlopen(base + path) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


loaded_before = (cfg.PROFILE, cfg.STATION)

st, ct, body = get("/twin")
assert st == 200 and "text/html" in ct and b"beamline twin" in body
st, _, body = get("/")
assert st == 200 and b'href="/twin"' in body                       # the monitor links to the twin viewer

L = json.loads(get("/api/profiles")[2])
names = {p["name"]: p for p in L["profiles"]}
assert {"s1id", "demo"} <= set(names) and names["s1id"]["twin"] == "1-ID" and names["demo"]["twin"] is None, names

d = json.loads(get("/api/twin?profile=s1id")[2])                    # profile switch -> twin
t = d["twin"]
assert t and t["id"] == "1-ID" and len(t["elements"]) >= 70 and t["check"]["errors"] == [], t and t["check"]
assert t["hutch_order"] == ["SRC", "A", "B", "C", "E"]
assert [e["index"] for e in t["elements"]] == list(range(len(t["elements"])))      # beam order, contiguous
assert {e["id"] for e in t["elements"] if e["kind"] == "slit"} >= {"wbSlits", "slitB", "slitCus", "slitCds", "slitEus", "slitEds"}
assert "samE" in t["blade_targets"] and any("samE.ry" in m for m in t["blade_targets"]["samE"]), t["blade_targets"]
zs = {e["id"]: e["z_m"] for e in t["elements"] if e.get("z_m") is not None}
assert zs["undulator"] == 0.0 and zs["samE"] == 71.5 and zs["lens1E"] == 67.7 and len(zs) == 12, zs     # known distances only; none invented
assert all(e.get("z_conf") and e.get("z_src") for e in t["elements"] if e.get("z_m") is not None)
assert list(zs.values()) == sorted(zs.values())                       # monotone along the beam
assert "samE" in t["assemblies"] and t["assemblies"]["samE"]["stack_top_to_bottom"]
assert d["profile"]["cameras"]["gh1"]["hutch"] == "E"

d = json.loads(get("/api/twin?profile=demo")[2])                    # a profile without a twin is reported, not an error
assert d["twin"] is None and d["twin_declared"] is None and d["profile"]["name"] == "demo"

assert get("/api/twin?profile=nope")[0] == 404                      # unknown profile

# photos: only indexed files; no path tricks
st, ct, body = get("/twin-photo/1-ID/p14")
if (ROOT / "beamline_twins/1-ID/sources/photos/PXL_20261020_210118769.jpg").exists():
    assert st == 200 and "image" in ct and body[:2] == b"\xff\xd8"
for bad in ("/twin-photo/1-ID/../beamline.json", "/twin-photo/1-ID/..%2Fbeamline.json", "/twin-photo/../1-ID/p14", "/twin-photo/1-ID/p99", "/twin-photo/1-ID", "/twin-photo/nope/p14"):
    assert get(bad)[0] == 404, bad

assert (cfg.PROFILE, cfg.STATION) == loaded_before                  # browsing twins must not change the loaded BLADE profile
srv.shutdown()
print("twin GUI OK")
