"""Knowledge-base viewer test (no hardware, no private data): builds a tiny SYNTHETIC knowledge base with the real schema (knowledge_base/schema.sql),
boots the real GUI server on a free port and checks every /api/kb route, image serving, safety (read-only DB, no path traversal, LIKE/FTS escaping)
and the 'KB missing' behaviour. Run: python -I tests/test_kb_gui.py"""
import io, json, os, sqlite3, sys, tempfile, threading, urllib.error, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
from PIL import Image
from blade import kb_api
from blade.gui import H

empty = Path(tempfile.mkdtemp())                       # 1) KB missing
kb_api.KB_DIR = empty
srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"


def get(path, raw=False):
    try:
        with urllib.request.urlopen(base + path) as r:
            b = r.read()
            return r.status, r.headers.get("Content-Type", ""), (b if raw else json.loads(b))
    except urllib.error.HTTPError as e:
        b = e.read()
        return e.code, e.headers.get("Content-Type", ""), (b if raw else json.loads(b))


st, ct, page = get("/kb", raw=True)
assert st == 200 and "text/html" in ct and b"knowledge base" in page and b'id="theme"' in page and b"/api/kb/status" in page
for must in (b"data-tab", b"openCite", b"/kb-image", b"procsearch"):
    assert must in page, must
for other in ("/", "/twin", "/vbl"):
    assert b'href="/kb"' in get(other, raw=True)[2], other                        # every page links to the viewer
st, _, s = get("/api/kb/status")
assert st == 200 and s["available"] is False and "kb.py ingest" in s["hint"], s
st, _, e = get("/api/kb/procs")
assert st == 404 and e["available"] is False, (st, e)
assert get("/kb-image?sha=abcdef", raw=True)[0] == 404
print("PASS /kb page served; missing knowledge base reported cleanly (status unavailable, API 404 with hint)")

# 2) synthetic KB with the real schema
kb = Path(tempfile.mkdtemp())
kb_api.KB_DIR = kb
con = sqlite3.connect(kb / "kb.sqlite")
con.executescript((ROOT / "knowledge_base" / "schema.sql").read_text())
SHA = {n: ("%02x" % (17 * (i + 1))) * 32 for i, n in enumerate("abc")}
con.execute("INSERT INTO docs VALUES('2025-startup_x','x.docx',2025,'docx','startup','Startup X','','','2025-02-01','2025-02-02',1,6,0,2,2)")
con.execute("INSERT INTO docs VALUES('2024-user_y','y.docx',2024,'docx','user','User Y','','','2024-05-01','2024-05-02',1,3,0,0,1)")
L = [("2025-startup_x", 1, "Setup", "Beam", "", "2025-02-01", "Align slits to the hotspot on pg5"),
     ("2025-startup_x", 2, "Setup", "Beam", "", "2025-02-01", "With pg5 at position: [IMG image1.png]"),
     ("2025-startup_x", 3, "Setup", "Beam", "", "2025-02-01", "100% flux_scan done, hot spot ok"),
     ("2025-startup_x", 4, "Setup", "Pin", "", "2025-02-02", "Pin in beam [IMG image2.png] [ALT x]"),
     ("2025-startup_x", 5, "Setup", "Pin", "", "2025-02-02", "Zeroed aero"),
     ("2025-startup_x", 6, "Setup", "Pin", "", "2025-02-02", ""),
     ("2024-user_y", 1, "S", "", "", "2024-05-01", "hotspot drifted"), ("2024-user_y", 2, "S", "", "", "", "second"), ("2024-user_y", 3, "S", "", "", "", "third")]
con.executemany("INSERT INTO lines(doc_id,ln,h1,h2,h3,date,text) VALUES(?,?,?,?,?,?,?)", L)
for n, col in (("a", 40), ("b", 200), ("c", 120)):
    d = kb / "images" / SHA[n][:2]
    d.mkdir(parents=True)
    Image.new("L", (400, 300), col).save(d / f"{SHA[n]}.png")
    con.execute("INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (SHA[n], "png", 1000, 400, 300, "L", 5, 0.0, 50, 5, 0, 99, 3, "00ff", f"images/{SHA[n][:2]}/{SHA[n]}.png"))
con.execute("INSERT INTO image_refs VALUES('2025-startup_x','image1.png',?,2,0,'Setup','Beam','','2025-02-01',0,'With pg5 at position:','Align slits','Zeroed')", (SHA["a"],))
con.execute("INSERT INTO image_refs VALUES('2025-startup_x','image2.png',?,4,1,'Setup','Pin','','2025-02-02',0,'Pin in beam','','')", (SHA["b"],))
for sha, key, val, src in ((SHA["a"], "class", "tomo_view", "rule"), (SHA["a"], "subject", "beam_only", "vision"), (SHA["a"], "camera", "pg5", "rule"),
                           (SHA["b"], "class", "tomo_view", "rule"), (SHA["b"], "subject", "pin", "vision"), (SHA["b"], "hutch", "E", "rule"),
                           (SHA["c"], "class", "panel_screenshot", "rule"), (SHA["c"], "device", "Kohzu_E_up", "vision")):
    con.execute("INSERT INTO labels VALUES(?,?,?,?,?,?,?)", (sha, key, val, src, 0.8, "2026-11-12", None))
con.execute("INSERT INTO ref_fts VALUES('2025-startup_x','image1.png',?,'Setup Beam With pg5 at position: Align slits')", (SHA["a"],))
con.execute("INSERT INTO ref_fts VALUES('2025-startup_x','image2.png',?,'Setup Pin Pin in beam')", (SHA["b"],))
rec = {"id": "demo", "name": "Demo procedure", "goal": "g", "steps": [{"n": 1, "action": "do <b>x</b>", "evidence": "log", "cites": ["2025-startup_x:L2"]}], "images": []}
con.execute("INSERT INTO procedures VALUES('demo','Demo procedure','g','w','E',1,1,'now',?)", (json.dumps(rec),))
con.execute("INSERT INTO proc_fts VALUES('demo','step','step 1: scan the undulator gap with undscangap')")
con.execute("INSERT INTO procedure_numbers VALUES('demo',1,'hotspot_pixel','960,600','px','pg5 2025','2025','2025-startup_x:L2')")
con.commit()
con.close()

st, _, s = get("/api/kb/status")
assert s["available"] and (s["docs"], s["images"], s["procedures"], s["lines"]) == (2, 3, 1, 9) and s["years"] == [2024, 2025], s
f = get("/api/kb/facets")[2]
assert ["tomo_view", 2] in f["class"] and ["pin", 1] in f["subject"] and ["Kohzu_E_up", 1] in f["device"]
assert get("/api/kb/procs")[2]["procedures"][0]["id"] == "demo" and get("/api/kb/proc?id=demo")[2]["steps"][0]["n"] == 1
assert get("/api/kb/proc?id=nope")[0] == 400
r = get("/api/kb/procsearch?q=" + urllib.parse.quote("undscan"))[2]["results"]
assert r and r[0]["id"] == "demo" and "<mark>undscangap</mark>" in r[0]["hits"][0]["snippet"], r
assert get("/api/kb/procsearch?q=" + urllib.parse.quote('"; DROP TABLE x --'))[0] == 200            # hostile FTS input is neutralised
assert get("/api/kb/numbers?q=hotspot")[2]["numbers"][0]["value"] == "960,600"
print("PASS status/facets/procedures: list, record, FTS search (snippet marked, hostile input safe), numbers")

r = get("/api/kb/images?q=pg5")[2]
assert r["total"] == 1 and r["images"][0]["subject"] == "beam_only" and r["images"][0]["cite"] == "2025-startup_x:L2", r
assert get("/api/kb/images?cls=tomo_view")[2]["total"] == 2 and get("/api/kb/images?subject=pin")[2]["total"] == 1
assert get("/api/kb/images?hutch=E&cls=tomo_view")[2]["images"][0]["sha"] == SHA["b"][:16]
assert get("/api/kb/images?device=Kohzu")[2]["total"] == 1 and get("/api/kb/images?q=Kohzu")[2]["total"] == 1       # device label found by free text too
assert get("/api/kb/images?limit=1&offset=1")[2]["images"].__len__() == 1
i = get("/api/kb/imginfo?sha=" + SHA["a"][:10])[2]
assert i["best"]["subject"]["value"] == "beam_only" and i["citations"][0]["same_line"] == "With pg5 at position:" and i["citations"][0]["before"] == "Align slits" and len(i["labels"]) == 3, i
st, ct, jb = get(f"/kb-image?sha={SHA['a'][:12]}&w=64", raw=True)
assert st == 200 and ct == "image/jpeg" and Image.open(io.BytesIO(jb)).size[0] <= 64 and (kb / "thumbs").is_dir()
st, ct, pb = get(f"/kb-image?sha={SHA['a'][:12]}", raw=True)
assert st == 200 and ct == "image/png" and Image.open(io.BytesIO(pb)).size == (400, 300)
for bad in ("../../etc/passwd", "zz", "ab", "%2e%2e%2f%2e%2e%2fetc", "0" * 64, SHA["a"][:2]):             # traversal / malformed / unknown / ambiguous ids are refused
    assert get(f"/kb-image?sha={bad}", raw=True)[0] == 400, bad
print("PASS images: text + label filters, paging, info with label history, thumbnail + original, hostile ids refused")

r = get("/api/kb/text?q=" + urllib.parse.quote("hot spot"))[2]
assert r["total"] == 3 and [h["ln"] for h in r["hits"]] == [1, 3, 1], r              # words are ANDed as substrings, so "hot spot" also finds the "hotspot" spelling
assert get("/api/kb/text?q=" + urllib.parse.quote("hotspot"))[2]["total"] == 2
assert get("/api/kb/text?q=" + urllib.parse.quote("100%"))[2]["total"] == 1 and get("/api/kb/text?q=" + urllib.parse.quote("flux_scan"))[2]["total"] == 1
assert get("/api/kb/text?q=%25")[2]["total"] == 1 and get("/api/kb/text?q=_")[2]["total"] == 1                # % and _ are literal, not wildcards
assert get("/api/kb/text?q=hotspot&year=2024")[2]["total"] == 1 and get("/api/kb/text?q=hotspot&kind=startup")[2]["total"] == 1
w = get("/api/kb/cite?c=" + urllib.parse.quote("2025-startup_x:L4") + "&ctx=2")[2]
assert (w["from"], w["to"]) == (2, 6) and w["mark"] == [4, 4]
assert [x["ln"] for x in w["lines"] if x["imgs"]] == [2, 4] and w["lines"][2]["imgs"][0]["sha"] == SHA["b"][:16] and "[IMG" not in w["lines"][2]["text"] and "[ALT" not in w["lines"][2]["text"]
assert get("/api/kb/cite?c=garbage")[0] == 400 and get("/api/kb/cite?c=" + urllib.parse.quote("nodoc:L1"))[0] == 400
o = get("/api/kb/outline?doc=2025-startup_x")[2]
assert [s["h3"] or s["h2"] for s in o["sections"]] == ["Beam", "Pin"] and o["sections"][0]["n"] == 3 and len(get("/api/kb/docs?kind=user")[2]["docs"]) == 1
assert get("/api/kb/nonsense")[0] == 404
print("PASS log text: AND search, literal %/_ , year/kind filters, citation window with inline images, outline, bad cite refused")

try:
    kb_api._con().execute("INSERT INTO docs(doc_id) VALUES('x')")
    raise SystemExit("database is writable from the viewer")
except sqlite3.OperationalError:
    pass
print("PASS the viewer opens the database read-only")
