"""Physics-models page test (no hardware, stdlib + the simulator): boots the real GUI server on a free port and checks the /physics page, the model catalogue, that every
parameter is read live from sim.json, that the catalogue covers every section of sim.json, that every referenced file exists, and that every curve is computed by the simulator.
Run: python -I tests/test_physics_page.py"""
import json, math, os, re, sys, tempfile, threading, urllib.error, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
from blade.gui import H, _Server
from blade.vbl import physics_doc, world as W

srv = _Server(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"


def get(path):
    try:
        with urllib.request.urlopen(base + path) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def ok(msg):
    print("PASS", msg)


# 1) the page is served and has the shared theme machinery and the nav links
st, ct, body = get("/physics")
assert st == 200 and "text/html" in ct and b"physics models" in body
for must in (b'id="theme"', b"blade.theme", b"/api/vbl/physics", b"/api/vbl/physics/curve", b'href="/vbl"', b'href="/kb"'):
    assert must in body, must
themes = set(re.findall(rb":root\[data-theme=([a-z]+)\]", body))
assert {b"light", b"dark", b"midnight", b"paper", b"contrast"} <= themes, themes
ok("/physics served with the theme picker, all themes and nav links")
for page, link in (("/vbl", b'href="/physics"'), ("/twin", b'href="/physics"'), ("/kb", b'href="/physics"')):
    assert link in get(page)[2], page
ok("the virtual-beamline, twin and knowledge-base pages link to /physics")

# 2) the catalogue
st, _, raw = get("/api/vbl/physics")
D = json.loads(raw)
assert st == 200 and D["twin"] == "1-ID" and len(D["models"]) >= 20
sec_ids = {s["id"] for s in D["sections"]}
ids = [m["id"] for m in D["models"]]
assert len(ids) == len(set(ids)), "duplicate model ids"
STATUS = {"fitted", "validated", "textbook", "assumed", "mixed"}
for m in D["models"]:
    assert m["section"] in sec_ids and m["status"] in STATUS, m["id"]
    assert m["summary"] and (m.get("limits") or m["status"] in ("validated", "textbook")), f"{m['id']}: every fitted/mixed/assumed model must state its limits"
    assert m.get("evidence"), f"{m['id']}: no evidence listed"
assert {s for s in sec_ids} == {m["section"] for m in D["models"]}, "a section has no models"
ok(f"{len(D['models'])} models in {len(sec_ids)} sections, unique ids, valid status, limits and evidence present")

# 3) every parameter is a live read of sim.json
sim = W.load_sim()
roots = set()
for m in D["models"]:
    for p in m["params"]:
        v = sim
        for k in p["path"].split("."):
            assert isinstance(v, dict) and k in v, f"{m['id']}: path {p['path']} not in sim.json"
            v = v[k]
        assert p["found"] and p["value"] == v, (m["id"], p["path"])
        roots.add(p["path"].split(".")[0])
ok("every parameter path exists in sim.json and the page value equals the file")
covered_exempt = {"schema", "id", "note", "z_known"}
missing = sorted(set(sim) - covered_exempt - roots)
assert not missing, f"sim.json sections not described on the physics page: {missing}"
ok("every section of sim.json is described by at least one model")

# 4) referenced files exist (tests, fit notes, physics notes, code files)
twin = ROOT / "beamline_twins" / "1-ID"
for m in D["models"]:
    for ev in m["evidence"]:
        for t in re.findall(r"tests/test_\w+\.py", ev):
            assert (ROOT / t).exists(), (m["id"], t)
        for f in re.findall(r"(?:physics/)?fits/(\w+\.md)", ev):
            assert (twin / "physics" / "fits" / f).exists(), (m["id"], f)
    for c in m.get("code", []):
        for f in re.findall(r"(blade/[\w/]+\.py)", c):
            assert (ROOT / f).exists(), (m["id"], f)
for t in D["tests"]:
    assert (ROOT / t).exists(), t
ok("every referenced test, fit note and code file exists")

# 5) every curve is computed by the simulator and is finite; unknown curves are refused
names = sorted({m["curve"] for m in D["models"] if m.get("curve")})
assert len(names) >= 8, names
for n in names:
    st, ct, raw = get(f"/api/vbl/physics/curve?name={n}")
    c = json.loads(raw)
    assert st == 200 and c["series"] and c["xlabel"] and c["ylabel"], n
    for s in c["series"]:
        assert len(s["x"]) == len(s["y"]) >= 5 and all(math.isfinite(v) for v in s["x"] + s["y"]), (n, s["name"])
assert get("/api/vbl/physics/curve?name=nope")[0] == 404
ok(f"{len(names)} curves computed by the simulator, finite; unknown curve refused")

# 6) the curves agree with the model facts stated on the page
w = physics_doc._world()
c = physics_doc.curve("und_peak")
for s in c["series"]:                                        # the gap-scan peak is at the optimal gap (x = 0) and ~1 % wide in energy
    i = max(range(len(s["y"])), key=lambda k: s["y"][k])
    assert abs(s["x"][i]) < 8.0, (s["name"], s["x"][i])      # peak within 8 um of the optimal gap
th = physics_doc.curve("th2")["series"][0]
half = [x for x, y in zip(th["x"], th["y"]) if y >= 0.5]
fwhm = (max(half) - min(half)) * 1e-3
assert abs(fwhm - sim["hem"]["th2_rocking_fwhm_deg"]) < 2e-4, fwhm
fl = physics_doc.curve("foil")
re_ = [s for s in fl["series"] if s["name"] == "Re"][0]
step = max(re_["y"]) - min(re_["y"])
assert abs(step - sim["foils"]["b"]["Re"]) / sim["foils"]["b"]["Re"] < 0.1, step
ok(f"gap-scan peak at the optimal gap; Th2 FWHM {fwhm * 1e3:.2f} mdeg = sim.json; Re edge step {step:.2f} = b")

# 7) the page fires its curve requests together: they must all succeed (server backlog) and equal the serial result (curves share one world, so they are serialised)
serial = {n: physics_doc.curve(n) for n in names}
res, errs = {}, []
def go(n):
    for _ in range(3):
        try:
            res.setdefault(n, []).append(json.loads(get(f"/api/vbl/physics/curve?name={n}")[2]))
        except Exception as e:                                 # a reset connection would show up here
            errs.append((n, repr(e)))
ths = [threading.Thread(target=go, args=(n,)) for n in names for _ in range(2)]
[t.start() for t in ths]; [t.join() for t in ths]
assert not errs, errs[:3]
assert all(c["series"] == serial[n]["series"] for n in res for c in res[n]), "concurrent curve requests disagree with the serial result"
ok(f"{sum(len(v) for v in res.values())} concurrent curve requests: no resets, results identical to serial")
print("physics page OK")
