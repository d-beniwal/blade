"""Knowledge-base label curation test (no hardware, no private data): a SYNTHETIC knowledge base with the real schema; checks rename / delete / set / add /
remove, that the curation log makes every change survive a re-ingest-like reappearance of the old labels (replay, idempotent), the daily backup, input
validation, and the HTTP route's guard (local Host, X-Blade-Edit header, confirm flag). Run: python -I tests/test_kb_curate.py"""
import json, os, sqlite3, sys, tempfile, threading, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
from blade import kb_api, kb_curate
from blade.gui import H

kb = Path(tempfile.mkdtemp())
con = sqlite3.connect(kb / "kb.sqlite")
con.executescript((ROOT / "knowledge_base" / "schema.sql").read_text())
SHA = {n: ("%02x" % (17 * (i + 1))) * 32 for i, n in enumerate("abc")}
for n in "abc":
    con.execute("INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (SHA[n], "png", 1, 4, 4, "L", 5, 0.0, 50, 5, 0, 99, 3, "00", "x.png"))
LAB = [("a", "subject", "pin", "vision"), ("a", "class", "tomo_view", "rule"), ("b", "subject", "pin", "rule"), ("c", "subject", "beam_only", "vision")]
con.executemany("INSERT INTO labels VALUES(?,?,?,?,?,?,?)", [(SHA[n], k, v, s, 0.8, "2026-11-12", None) for n, k, v, s in LAB])
con.commit()
con.close()


def best(n, key):
    c = sqlite3.connect(kb / "kb.sqlite")
    r = c.execute("SELECT value FROM label_best WHERE sha256=? AND key=?", (SHA[n], key)).fetchone()
    c.close()
    return r and r[0]


def count(sql, *a):
    c = sqlite3.connect(kb / "kb.sqlite")
    r = c.execute(sql, a).fetchone()[0]
    c.close()
    return r


def refused(body, why):
    try:
        kb_curate.submit(kb, body, confirmed=True)
    except kb_curate.CurateError:
        return
    raise SystemExit("accepted: " + why)


# 1) rename a value everywhere (the real use: subject pin -> tomopin)
r = kb_curate.submit(kb, {"op": "rename", "key": "subject", "old": "pin", "new": "tomopin"}, confirmed=True)
assert r["changed"] == 2 and best("a", "subject") == "tomopin" and best("b", "subject") == "tomopin" and best("c", "subject") == "beam_only"
assert count("SELECT COUNT(*) FROM labels WHERE value='pin'") == 0 and list(kb.glob("kb.sqlite.bak-curate-*")), "daily backup missing"
print("PASS rename changes every label of that value on every image, and a backup copy was made")

# 2) persistence: an ingest / labelling pass brings the OLD value back -> replay fixes it, and replay is idempotent
c = sqlite3.connect(kb / "kb.sqlite")
c.execute("INSERT INTO labels VALUES(?,?,?,?,?,?,?)", (SHA["c"], "subject", "pin", "rule", 0.3, "2026-11-20", "keyword in nearby text"))
c.commit()
c.close()
assert kb_curate.replay(kb, quiet=True)["changed"] == 1 and best("c", "subject") == "beam_only" and count("SELECT COUNT(*) FROM labels WHERE value='pin'") == 0
assert kb_curate.replay(kb, quiet=True)["changed"] == 0
print("PASS the log is replayed after the old label returns (idempotent: second replay changes nothing)")

# 3) per-image add / set / remove
kb_curate.submit(kb, {"op": "add", "sha": SHA["c"][:10], "key": "sample", "value": "W pin"}, confirmed=True)
assert best("c", "sample") == "W pin"
kb_curate.submit(kb, {"op": "set", "sha": SHA["c"], "key": "subject", "value": "radiograph"}, confirmed=True)
assert best("c", "subject") == "radiograph" and count("SELECT COUNT(*) FROM labels WHERE sha256=? AND key='subject'", SHA["c"]) == 1
kb_curate.submit(kb, {"op": "remove", "sha": SHA["a"], "key": "class"}, confirmed=True)
assert best("a", "class") is None and best("a", "subject") == "tomopin"
kb_curate.submit(kb, {"op": "remove", "sha": SHA["b"], "key": "subject", "value": "tomopin"}, confirmed=True)
assert best("b", "subject") is None
kb_curate.submit(kb, {"op": "delete_value", "key": "subject", "value": "radiograph"}, confirmed=True)
assert best("c", "subject") is None
c = sqlite3.connect(kb / "kb.sqlite")                                  # simulate a rebuild that restores every ORIGINAL label, then replay the log
c.execute("DELETE FROM labels")
c.executemany("INSERT INTO labels VALUES(?,?,?,?,?,?,?)", [(SHA[n], k, v, s, 0.8, "2026-11-12", None) for n, k, v, s in LAB])
c.commit()
c.close()
kb_curate.replay(kb, quiet=True)
assert (best("a", "subject"), best("a", "class"), best("b", "subject"), best("c", "subject"), best("c", "sample")) == ("tomopin", None, None, None, "W pin")
assert len(kb_curate.read_log(kb)) == 6 and kb_curate.history(kb)["log"][0]["op"] == "delete_value"
print("PASS add / set / remove / delete_value; replaying the log on a database restored to the ORIGINAL labels reproduces every correction")

# 4) validation
refused({"op": "nope", "key": "subject"}, "unknown op")
refused({"op": "rename", "key": "bad key!", "old": "a", "new": "b"}, "bad key")
refused({"op": "rename", "key": "subject", "old": "x", "new": "x"}, "same value")
refused({"op": "rename", "key": "subject", "old": "nothing_here", "new": "y"}, "rename of a label that does not exist")
refused({"op": "add", "sha": "zz", "key": "subject", "value": "v"}, "bad sha")
refused({"op": "add", "sha": "ee" * 32, "key": "subject", "value": "v"}, "unknown image")
refused({"op": "add", "sha": SHA["a"], "key": "subject", "value": "  "}, "empty value")
try:
    kb_curate.submit(kb, {"op": "add", "sha": SHA["a"], "key": "k", "value": "v"}, confirmed=False)
    raise SystemExit("accepted without confirmation")
except kb_curate.CurateError:
    pass
assert len(kb_curate.read_log(kb)) == 6, "a refused request must not be logged"
print("PASS invalid / unconfirmed requests refused and not logged")

# 5) HTTP route guard
kb_api.KB_DIR = kb
srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"


def post(body, headers=None, host=None):
    h = {"Content-Type": "application/json", **({"X-Blade-Edit": "1"} if headers is None else headers)}
    if host:
        h["Host"] = host
    req = urllib.request.Request(base + "/api/kb/curate", json.dumps(body).encode(), h)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


b = {"op": "add", "sha": SHA["b"], "key": "subject", "value": "tomopin", "confirm": True}
assert post(b, headers={})[0] == 400 and post(b, host="evil.example.com")[0] == 400 and post({**b, "confirm": False})[0] == 400
assert best("b", "subject") is None, "guard let an edit through"
st, d = post(b)
assert st == 200 and d["ok"] and best("b", "subject") == "tomopin"
assert json.load(urllib.request.urlopen(base + "/api/kb/labelvalues?key=subject"))["values"] == [["tomopin", 2]]
assert ["subject", 2] in json.load(urllib.request.urlopen(base + "/api/kb/labelkeys"))["keys"]
assert json.load(urllib.request.urlopen(base + "/api/kb/curation?limit=1"))["log"][0]["value"] == "tomopin"
page = urllib.request.urlopen(base + "/kb").read()
assert b"openLabelMgr" in page and b"/api/kb/curate" in page and b'data-act="del"' in page
print("PASS HTTP: edits need the local Host + X-Blade-Edit header + confirm flag; label manager / log routes and page controls present")
