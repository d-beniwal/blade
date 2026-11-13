"""GUI editor back end on COPIES of the twin/profile (nothing tracked is touched): confirmation + old-value guards, field allow-list, typed values,
rollback when the twin check fails, verified-needs-evidence, audit log, byte-identical rewrite of the hutch files, and the local-only request check,
then the real HTTP route. Usage: python -I tests/test_edit_api.py"""
import json, os, shutil, sys, tempfile, threading, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
shutil.copytree(ROOT / "beamline_twins", tmp / "twins", ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(ROOT / "profiles", tmp / "profiles")
os.environ.update(BLADE_TWINS_DIR=str(tmp / "twins"), BLADE_PROFILES_DIR=str(tmp / "profiles"), BLADE_EDITS=str(tmp / "edits"))
sys.path.insert(0, str(ROOT))
from blade import edit_api as E  # noqa: E402

def ed(**k):
    b = dict(target="element", twin="1-ID", confirm=True); b.update(k); return E.apply_edit(b)
def refuses(why, **k):
    try:
        ed(**k)
    except E.EditError as e:
        print("PASS refused:", why, "-", str(e)[:70]); return
    raise AssertionError("accepted: " + why)

# hutch files are rewritten byte-identically (except SRC's one multi-line element)
for n in "ABCE":
    f = tmp / "twins/1-ID/hutches" / f"{n}.json"; s = f.read_text()
    assert E.dump_hutch(json.loads(s), E._tail(s)) == s, n
print("PASS hutch A/B/C/E re-serialise byte-identically")

def cur(eid, field):
    return [x for x in json.loads((tmp / "twins/1-ID/hutches/E.json").read_text())["elements"] if x["id"] == eid][0].get(field)
pv0 = cur("slitEus", "pv")
refuses("not confirmed", id="slitEus", field="pv", old=pv0, new="x:", **{"confirm": False})
refuses("stale old value", id="slitEus", field="pv", old="something else", new="1ide1:Kohzu_E_up2")
refuses("field not in allow-list", id="slitEus", field="kind", old="slit", new="ic")
refuses("bad enum", id="slitEus", field="conf", old="seen", new="certain")
refuses("bad JSON", id="slitEus", field="state", old=cur("slitEus", "state"), new="{oops")
refuses("no change", id="slitEus", field="pv", old=pv0, new=pv0)
r = ed(id="slitEus", field="pv", old=pv0, new="1ide1:Kohzu_E_upX")
assert r["ok"]
r = ed(id="slitEus", field="notes", old=cur("slitEus", "notes"), new="edited in test")
e = [x for x in json.loads((tmp / "twins/1-ID/hutches/E.json").read_text())["elements"] if x["id"] == "slitEus"][0]
assert e["notes"] == "edited in test" and E._twin_check("1-ID") == []
print("PASS element edit written, twin still valid")
r = ed(id="samE", field="z_m", old=cur("samE", "z_m"), new="71.4")
assert r["new"] == 71.4
r = ed(id="icE3", field="controls", old=cur("icE3", "controls"), new='{"a": 1}')
print("PASS typed values (number, JSON)")
# rollback: removing the name breaks the twin check
refuses("empty name", id="icE3", field="name", old=cur("icE3", "name"), new=" ")
before = (tmp / "twins/1-ID/hutches/SRC.json").read_text()
refuses("twin check fails (conf 'seen' without a photo/user source) -> rolled back", id="undulator", field="conf", old="code", new="seen")
assert (tmp / "twins/1-ID/hutches/SRC.json").read_text() == before
print("PASS file unchanged after the rejected edit")

# profile
def pe(**k):
    b = dict(target="profile", confirm=True, profile="s1id"); b.update(k); return E.apply_edit(b)
r = pe(path="cameras.retiga2.pv_prefix", old="QIMAGE2:", new="QIMAGE2:")if False else None
for bad in ({"path": "limits.max_rot_deg", "old": 90.0, "new": "200"}, {"path": "cameras.gh1.nope", "old": None, "new": "x"}):
    try: pe(**bad); raise AssertionError("accepted " + bad["path"])
    except E.EditError: pass
r = pe(path="cameras.gh1.pixel_um", old=0.69, new="0.7")
assert json.loads((tmp / "profiles/s1id/default_config.json").read_text())["cameras"]["gh1"]["pixel_um"] == 0.7
try: pe(path="cameras.gh1.pixel_um", old=0.7, new="abc"); raise AssertionError("accepted text for a number")
except E.EditError: pass
print("PASS profile edits: allow-list, typed, written")

# verify list
def ve(**k):
    b = dict(target="verify", confirm=True); b.update(k); return E.apply_edit(b)
try: ve(id="retiga2-prefix", field="status", old="unverified", new="verified"); raise AssertionError("verified without evidence")
except E.EditError as e: print("PASS verified needs a note first -", str(e)[:50])
ve(id="retiga2-prefix", field="note", old="", new="staff confirmed in B, 2026-12-01")
ve(id="retiga2-prefix", field="status", old="unverified", new="verified")
it = [x for x in E.verify_items("1-ID") if x["id"] == "retiga2-prefix"][0]
assert it["status"] == "verified" and it["status_changed"]
print("PASS verify item moved to verified with evidence")
log = [json.loads(l) for l in (tmp / "edits/edits.jsonl").read_text().splitlines()]
assert len(log) >= 7 and all({"t", "where", "old", "new"} <= set(x) for x in log)
print("PASS audit log has", len(log), "entries")

# request guard + the real route
class H(dict):
    def get(self, k, d=None): return super().get(k, d)
for hd in ({"Host": "evil.example", "X-Blade-Edit": "1"}, {"Host": "localhost:8765"}):
    try: E.check_request(H(hd)); raise AssertionError("accepted " + str(hd))
    except E.EditError: pass
E.check_request(H({"Host": "127.0.0.1:8765", "X-Blade-Edit": "1"}))
print("PASS local-only + header guard")
from blade.gui import H as Handler  # noqa: E402
srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
def post(body, hdr=True):
    rq = urllib.request.Request(f"http://127.0.0.1:{port}/api/edit", data=json.dumps(body).encode(), headers=({"X-Blade-Edit": "1"} if hdr else {}))
    try:
        with urllib.request.urlopen(rq) as r: return r.status, json.load(r)
    except urllib.error.HTTPError as e: return e.code, json.load(e)
c, r = post(dict(target="verify", twin="1-ID", id="fsE-xy", field="note", old="", new="x"), hdr=False)
assert c == 400 and "header" in r["error"]
c, r = post(dict(target="verify", twin="1-ID", id="fsE-xy", field="note", old="", new="jog test pending"))
assert c == 400 and "not confirmed" in r["error"]
c, r = post(dict(target="verify", twin="1-ID", id="fsE-xy", field="note", old="", new="jog test pending", confirm=True))
assert c == 200 and r["ok"]
with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/twin?profile=s1id") as rr:
    t = json.load(rr)["twin"]
assert any(x["id"] == "fsE-xy" and x["note"] == "jog test pending" for x in t["verify"])
print("PASS HTTP route: header, confirmation, success; twin payload carries the verify list")
shutil.rmtree(tmp)
# every item of the REAL to-verify list points at something that exists
real = json.loads((ROOT / "beamline_twins/1-ID/verify.json").read_text())["items"]
els = {e["id"] for f in (ROOT / "beamline_twins/1-ID/hutches").glob("*.json") for e in json.loads(f.read_text())["elements"]}
prof = json.loads((ROOT / "profiles/s1id/default_config.json").read_text())
ids = [x["id"] for x in real]; assert len(ids) == len(set(ids))
for x in real:
    assert x["status"] in E.VSTATUS and {"subject", "value", "why", "how", "ref"} <= set(x), x["id"]
    r = x["ref"]
    if r["target"] == "element":
        assert r["id"] in els, x["id"]
    elif r["target"] == "profile":
        n = prof
        for k in r["path"].split("."):
            n = n[k]
assert prof["cameras"]["retiga2"]["pv_prefix"] == "QIMAGE2:" and any(x["id"] == "retiga2-prefix" and x["status"] != "verified" for x in real)
print("PASS the real to-verify list: unique ids, complete, every ref exists; retiga2 prefix QIMAGE2: is on the list")
print("edit api OK")
