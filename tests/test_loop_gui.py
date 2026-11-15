"""Sync & Loop page (no hardware): /loop is served with the ribbon, /api/loop/state reports the read-only mapping (nothing verified yet -> nothing used) and the ICs, and the
stand-in dry run endpoint returns a before/after score. Run: python -I tests/test_loop_gui.py"""
import json, os, sys, tempfile, threading, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
from blade.gui import H, _Server

srv = _Server(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
get = lambda p: urllib.request.urlopen(base + p).read()
post = lambda p, b: json.loads(urllib.request.urlopen(urllib.request.Request(base + p, data=json.dumps(b).encode(), method="POST", headers={"Content-Type": "application/json"})).read())

page = get("/loop").decode()
assert 'id="bnav"' in page and 'aria-current="page"' in page and "READ-ONLY" in page and "cannot command" in page
S = json.loads(get("/api/loop/state"))
assert S["read_only"] and S["mapping"] and not any(m["usable"] for m in S["mapping"]), "the shipped mapping has nothing verified: nothing may be used"
assert len(S["ics"]) >= 10 and all(c["counts_pv"].startswith(("1id", "1ide")) for c in S["ics"]) and S["dry_run"] is None
D = post("/api/loop/dryrun", {"seed": 5, "iterations": 1})
assert D["simulation_only"] and D["turns"][0]["score_after"] < D["turns"][0]["score_before"] / 3, D["turns"][0]
S2 = json.loads(get("/api/loop/state"))
assert S2["dry_run"]["seed"] == 5
print("PASS /loop page, read-only mapping state, stand-in dry run (score %.1f -> %.1f)" % (D["turns"][0]["score_before"], D["turns"][0]["score_after"]))
print("loop GUI OK")
