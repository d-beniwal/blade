#!/usr/bin/env python3
"""Facts layer: numbers transcribed from log panel screenshots (motor/slit/scaler/energy/undulator windows).

    facts.py build [--per 30]     # select legible, value-rich panels, group by log document -> <KB_ROOT>/facts/packs/pack_NNN.json
    facts.py todo                 # packs that have no result file yet
    facts.py check FILE.json ...  # validate result files (does not touch the DB)
    facts.py load [FILE ...]      # check + (re)load into table `facts` (default: all facts/results/*.json)
    facts.py stats
    facts.py schema               # the result format agents must write

Data (packs, results, brief) stays outside the repo in <KB_ROOT>/facts/ (unpublished user records).
Every fact keeps provenance: sha256 of the image + a log citation (doc_id:ln of its first appearance).
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb  # noqa: E402

FACTS = kb.KB_ROOT / "facts"
KINDS = {"motor_rbv", "motor_setpoint", "motor_step", "motor_limit", "slit_size", "slit_center", "slit_step",
         "slit_blade", "scaler", "calc", "energy", "gap", "current", "preamp", "status", "text_field", "other"}
LEGIBLE = {"yes", "partial", "no"}

SCHEMA = """{
  "pack": "pack_007",
  "images": [
    { "sha10": "c219c09735",                      # first 10 hex of the image sha256 (from the pack)
      "legible": "yes|partial|no",                 # could you read the numbers at full size?
      "panel_type": "motor|slit|scaler|energy_calc|undulator|shutter|preamp|multi|detector|other",
      "title": "window/panel title as written, '' if none",
      "hutch": "A|B|C|E|''",                       # only if the panel/caption shows it
      "readings": [
        { "label": "B24 L4B Th (Rx)",              # the widget/row/field name EXACTLY as written
          "pv": "1ide:m24",                        # record name only if visible on screen, else ""
          "kind": "motor_rbv|motor_setpoint|motor_step|motor_limit|slit_size|slit_center|slit_step|slit_blade|scaler|calc|energy|gap|current|preamp|status|text_field|other",
          "value": -0.7648280,                     # number, or null if not numeric / unreadable
          "text": "-0.7648280",                    # the characters as seen (keeps sign, digits, e-notation)
          "unit": "deg",                           # as shown ('' if none)
          "conf": 0.95,                            # 0-1: how sure you are of the digits
          "note": "" } ],
      "note": "anything unusual (cropped, partly covered, widget not a number, limits shown, etc.)" } ]
}"""

BRIEF = """# Transcribing panel screenshots into numbers (BLADE knowledge base, 1-ID)

You get one pack (a JSON list of images from experiment logs, grouped by log document and in document order, each with the log text around it).
For EVERY image: open it at FULL SIZE with the Read tool (path = <KB_ROOT>/<path>), read every number, and write the result file.

Rules
- Transcribe what is on screen, nothing else. Do NOT guess, interpolate or "correct" digits. If a digit is unreadable use value null, conf <= 0.3 and say so in note.
- One reading per number/field. A motor widget gives several: its readback (the big value), the setpoint/drive box if shown, the tweak step (the small box between < >),
  and limits if a limits/"More" panel is open. Slit panels: size and centre per slit, plus the step boxes. Scalers: one reading per tile. Keep the label exactly as written
  (e.g. "B24 L4B Th (Rx)", "IC1-B (kHz)", "Und A gap (mm)", "Kohzu_E_up H-size"). The printed unit goes in `unit`; do not convert units.
- If the title/label shows an EPICS record (1ide:m24, 1ida:...), put it in `pv`; otherwise leave "".
- `kind`: use the closest value from the schema list. A motor tile's big number is motor_rbv; the entry field below it is motor_setpoint when it differs or is the only value.
- Naming conventions (keep them, the loader groups on them): a motorx_more window gives separate readings for user and dial, label "<name> Readback (user)", "<name> Readback (dial)",
  "<name> Drive (user)", "<name> Hi limit (dial)", "<name> Lo limit (user)", "<name> Tweak". A compact motor window: "<name> [compact]" (rbv), "<name> [compact] entry" (setpoint), "<name> [compact] step".
  Per-blade slit positions: kind slit_blade. SR570 preamps / gain-offset selectors: kind preamp (value = number if numeric, else text with unit as shown). A motor shown "Moving": rbv = current value, setpoint = target, note "moving".
  A readback shown as -0.000000 keeps text "-0.000000" and value 0.0. A digit cut off by the window edge: give the visible digits, conf 0.8, note "last digit cropped".
- Several windows in one image: every reading is kept, `label` carries the window name. Repeated identical windows: keep each.
- Not a numeric panel (raw detector image, plot, ring-status page): legible "no", panel_type "other", readings [], and say what it is in note.
- Use the log text only to fill `hutch`/`note` or to disambiguate a label; the numbers come from the pixels. If the log text states a value and the image disagrees, report the image and mention it in note.
- Read in batches (several images per step) and write the result file once at the end (or in two halves for big packs) with the Write tool at the path given in your task.
- Output must be strict JSON in the schema below (no comments, no trailing commas). One entry per image in the pack, same order, every image present.

Schema
""" + SCHEMA + "\n"


def sha10(s):
    return s[:10]


def _near(db, doc, ln, span=3):
    rows = db.execute("SELECT ln,text FROM lines WHERE doc_id=? AND ln BETWEEN ? AND ? ORDER BY ln", (doc, ln - span, ln + span)).fetchall()
    out = []
    for r in rows:
        t = re.sub(r"\s+", " ", (r["text"] or "")).strip()
        t = re.sub(r"\[\[?img[^\]]*\]\]?", "[img]", t)
        if t:
            out.append(f"L{r['ln']}: {t[:160]}")
    return out


def candidates(db):
    q = """
    SELECT i.sha256, i.path, i.width, i.height,
      (SELECT value FROM label_best b WHERE b.sha256=i.sha256 AND b.key='subject') subject,
      (SELECT value FROM label_best b WHERE b.sha256=i.sha256 AND b.key='device')  device,
      (SELECT value FROM label_best b WHERE b.sha256=i.sha256 AND b.key='legible') legible,
      (SELECT value FROM label_best b WHERE b.sha256=i.sha256 AND b.key='value_rich') vrich
    FROM images i
    WHERE (SELECT value FROM label_best b WHERE b.sha256=i.sha256 AND b.key='class')='panel_screenshot'"""
    out = []
    for r in db.execute(q):
        if r["subject"] not in ("motor_panel", "slit_panel", "scaler_ic", "multi_panel", "energy_calc", "undulator", "shutter_pss", "detector_ctrl"):
            continue
        if r["legible"] not in ("yes", "partial") or r["vrich"] not in ("yes", "partial"):
            continue
        out.append(r)
    return out


def build(per):
    db = kb.connect()
    cands = candidates(db)
    items = []
    for r in cands:
        ref = db.execute("SELECT * FROM image_refs WHERE sha256=? ORDER BY doc_id, ln LIMIT 1", (r["sha256"],)).fetchone()
        nrefs = db.execute("SELECT COUNT(*) FROM image_refs WHERE sha256=?", (r["sha256"],)).fetchone()[0]
        hdr = " > ".join(x for x in (ref["h1"], ref["h2"], ref["h3"]) if x)
        items.append({
            "sha10": sha10(r["sha256"]), "sha256": r["sha256"], "path": r["path"], "size": f"{r['width']}x{r['height']}",
            "label_subject": r["subject"], "label_device": r["device"], "label_legible": r["legible"],
            "doc": ref["doc_id"], "ln": ref["ln"], "date": ref["date"] or "", "n_refs": nrefs, "headings": hdr[:200],
            "caption_before": (ref["before"] or "")[:200], "caption_after": (ref["after"] or "")[:200],
            "same_line": (ref["same_line"] or "")[:160], "near_text": _near(db, ref["doc_id"], ref["ln"]),
        })
    items.sort(key=lambda x: (x["doc"], x["ln"]))
    # pack boundaries: aim for `per` images, but never split a doc if the pack stays under 1.5*per
    packs, cur = [], []
    for it in items:
        cur.append(it)
        if len(cur) >= per:
            packs.append(cur)
            cur = []
    if cur:
        packs.append(cur)
    (FACTS / "packs").mkdir(parents=True, exist_ok=True)
    (FACTS / "results").mkdir(parents=True, exist_ok=True)
    for f in (FACTS / "packs").glob("pack_*.json"):
        f.unlink()
    for n, p in enumerate(packs, 1):
        (FACTS / "packs" / f"pack_{n:03d}.json").write_text(json.dumps({"pack": f"pack_{n:03d}", "kb_root": str(kb.KB_ROOT), "images": p}, indent=1))
    (FACTS / "BRIEF.md").write_text(BRIEF)
    print(f"{len(items)} candidate panels -> {len(packs)} packs of <= {per} in {FACTS/'packs'}; brief: {FACTS/'BRIEF.md'}")


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def check_file(path):
    """returns (errors, pack_dict, result_dict)"""
    errs = []
    try:
        res = json.loads(Path(path).read_text())
    except Exception as e:
        return [f"{path}: not valid JSON ({e})"], None, None
    pname = res.get("pack", "")
    pf = FACTS / "packs" / f"{pname}.json"
    if not pf.exists():
        return [f"{path}: unknown pack '{pname}'"], None, res
    pack = json.loads(pf.read_text())
    byid = {i["sha10"]: i for i in pack["images"]}
    seen = set()
    for k, im in enumerate(res.get("images", [])):
        s = im.get("sha10")
        if s not in byid:
            errs.append(f"image #{k}: sha10 {s} not in pack")
            continue
        if s in seen:
            errs.append(f"{s}: duplicated")
        seen.add(s)
        if im.get("legible") not in LEGIBLE:
            errs.append(f"{s}: legible must be yes|partial|no")
        if not isinstance(im.get("readings"), list):
            errs.append(f"{s}: readings must be a list")
            continue
        if im.get("legible") == "yes" and not im["readings"] and "other" not in str(im.get("panel_type")):
            errs.append(f"{s}: legible yes but no readings")
        for j, rd in enumerate(im["readings"]):
            tag = f"{s}[{j}]"
            if not str(rd.get("label", "")).strip():
                errs.append(f"{tag}: empty label")
            if rd.get("kind") not in KINDS:
                errs.append(f"{tag}: kind '{rd.get('kind')}' not in schema")
            v = rd.get("value")
            if v is not None and not _num(v):
                errs.append(f"{tag}: value must be number or null (got {v!r})")
            if v is None and not str(rd.get("text", "")).strip():
                errs.append(f"{tag}: null value needs the raw text")
            c = rd.get("conf")
            if not _num(c) or not 0 <= c <= 1:
                errs.append(f"{tag}: conf must be 0-1")
            if v is not None and str(rd.get("text", "")).strip():
                m = re.search(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", str(rd["text"]).replace(",", ""))
                if m and abs(float(m.group()) - v) > 1e-6 * max(1, abs(v)) + 1e-9:
                    errs.append(f"{tag}: value {v} != text '{rd['text']}'")
    missing = set(byid) - seen
    if missing:
        errs.append(f"{len(missing)} pack images missing from result: {sorted(missing)[:6]}...")
    return errs, pack, res


def load(files):
    db = kb.connect()
    db.execute("""CREATE TABLE IF NOT EXISTS facts(
      id INTEGER PRIMARY KEY, sha256 TEXT, doc_id TEXT, ln INT, date TEXT, panel_type TEXT, title TEXT, hutch TEXT,
      label TEXT, pv TEXT, kind TEXT, value REAL, text TEXT, unit TEXT, conf REAL, note TEXT, legible TEXT, pack TEXT, created TEXT, image_note TEXT)""")
    try:
        db.execute("ALTER TABLE facts ADD COLUMN image_note TEXT")
    except Exception:
        pass
    db.execute("CREATE INDEX IF NOT EXISTS facts_sha ON facts(sha256)")
    db.execute("CREATE INDEX IF NOT EXISTS facts_label ON facts(label)")
    db.execute("CREATE INDEX IF NOT EXISTS facts_doc ON facts(doc_id, ln)")
    files = files or sorted(str(p) for p in (FACTS / "results").glob("pack_*.json"))
    bad = 0
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for f in files:
        errs, pack, res = check_file(f)
        if errs:
            bad += 1
            print(f"REJECT {f}: {len(errs)} problems"), [print("   ", e) for e in errs[:12]]
            continue
        byid = {i["sha10"]: i for i in pack["images"]}
        db.execute("DELETE FROM facts WHERE pack=?", (res["pack"],))
        n = 0
        for im in res["images"]:
            it = byid[im["sha10"]]
            for rd in im["readings"]:
                db.execute("INSERT INTO facts(sha256,doc_id,ln,date,panel_type,title,hutch,label,pv,kind,value,text,unit,conf,note,legible,pack,created,image_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (it["sha256"], it["doc"], it["ln"], it["date"], im.get("panel_type", ""), im.get("title", ""), im.get("hutch", ""),
                            rd["label"].strip(), rd.get("pv", ""), rd["kind"], rd.get("value"), rd.get("text", ""), rd.get("unit", ""),
                            rd["conf"], rd.get("note", ""), im["legible"], res["pack"], now, im.get("note", "")))
                n += 1
        db.commit()
        print(f"loaded {f}: {len(res['images'])} images, {n} readings")
    if bad:
        sys.exit(1)


def todo():
    done = {p.stem for p in (FACTS / "results").glob("pack_*.json")}
    left = [p.stem for p in sorted((FACTS / "packs").glob("pack_*.json")) if p.stem not in done]
    print(f"{len(left)} packs without results:", " ".join(left))


def stats():
    db = kb.connect()
    try:
        n, ni = db.execute("SELECT COUNT(*), COUNT(DISTINCT sha256) FROM facts").fetchone()
    except Exception:
        print("no facts table yet")
        return
    print(f"{n} readings from {ni} images")
    for r in db.execute("SELECT kind, COUNT(*) c, ROUND(AVG(conf),2) a FROM facts GROUP BY kind ORDER BY c DESC"):
        print(f"  {r['kind']:15s} {r['c']:6d}  mean conf {r['a']}")
    print("top labels:")
    for r in db.execute("SELECT label, COUNT(*) c FROM facts GROUP BY label ORDER BY c DESC LIMIT 25"):
        print(f"  {r['c']:5d}  {r['label']}")



# ------------------------------------------------------------------ blind audit
def audit_build(seed=7, per_image=18):
    """one random image per pack; a random sample of its tier-A readings. The agent gets LABELS ONLY (not our values)."""
    import random
    rnd = random.Random(seed)
    db = kb.connect()
    (FACTS / "audit").mkdir(parents=True, exist_ok=True)
    items, key = [], {}
    for pf in sorted((FACTS / "packs").glob("pack_*.json")):
        pack = json.loads(pf.read_text())
        cand = []
        for im in pack["images"]:
            rows = db.execute("SELECT f.label, f.text, f.value, f.kind, f.unit FROM facts f JOIN fact_obs o ON o.fact_id=f.id WHERE f.sha256=? AND o.tier='A' AND f.kind NOT IN ('other')",
                              (im["sha256"],)).fetchall()
            if len(rows) >= 8:
                cand.append((im, rows))
        if not cand:
            continue
        im, rows = rnd.choice(cand)
        pick = rnd.sample(rows, min(per_image, len(rows)))
        items.append({"sha10": im["sha10"], "path": im["path"], "pack": pack["pack"], "labels": [r["label"] for r in pick]})
        key[im["sha10"]] = [{"label": r["label"], "text": r["text"], "value": r["value"], "kind": r["kind"]} for r in pick]
    (FACTS / "audit" / "key.json").write_text(json.dumps(key, indent=1))
    half = (len(items) + 1) // 2
    for n, part in enumerate((items[:half], items[half:]), 1):
        (FACTS / "audit" / f"audit_{n}.json").write_text(json.dumps({"audit": f"audit_{n}", "kb_root": str(kb.KB_ROOT), "images": part}, indent=1))
    print(f"{len(items)} audit images, {sum(len(i['labels']) for i in items)} labels -> {FACTS/'audit'}")


def audit_score():
    import math
    key = json.loads((FACTS / "audit" / "key.json").read_text())
    tot = ok = 0
    bad = []
    per_pack = {}
    for n in (1, 2):
        f = FACTS / "audit" / f"result_{n}.json"
        if not f.exists():
            continue
        spec = {i["sha10"]: i for i in json.loads((FACTS / "audit" / f"audit_{n}.json").read_text())["images"]}
        for im in json.loads(f.read_text())["images"]:
            exp = key.get(im["sha10"], [])
            got = {}
            for a in im["answers"]:
                got.setdefault(a["label"], []).append(str(a.get("text", "")).strip())
            for e in exp:
                tot += 1
                g = got.get(e["label"], [])
                def num(t):
                    m = re.search(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", t.replace(",", ""))
                    return float(m.group()) if m else None
                match = False
                for t in g:
                    a, b = num(t), e["value"]
                    if a is not None and b is not None:
                        match |= abs(a - b) <= 1e-6 * max(1, abs(b)) + 1e-9
                    else:
                        match |= t.strip().lower() == str(e["text"]).strip().lower()
                pk = spec[im["sha10"]]["pack"]
                d = per_pack.setdefault(pk, [0, 0])
                d[1] += 1
                if match:
                    ok += 1
                    d[0] += 1
                else:
                    bad.append((pk, im["sha10"], e["label"], e["text"], g))
    print(f"audit: {ok}/{tot} readings reproduced exactly ({100*ok/max(tot,1):.1f} %)")
    for pk, (a, b) in sorted(per_pack.items()):
        if a != b:
            print(f"  {pk}: {a}/{b}")
    for b in bad[:60]:
        print("  MISMATCH", b)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("--per", type=int, default=30)
    sp.add_parser("todo")
    c = sp.add_parser("check")
    c.add_argument("files", nargs="+")
    l = sp.add_parser("load")
    l.add_argument("files", nargs="*")
    sp.add_parser("stats")
    sp.add_parser("audit-build")
    sp.add_parser("audit-score")
    sp.add_parser("schema")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.per)
    elif a.cmd == "todo":
        todo()
    elif a.cmd == "check":
        for f in a.files:
            errs, _, res = check_file(f)
            print(f, "OK" if not errs else f"{len(errs)} problems")
            for e in errs[:20]:
                print("   ", e)
    elif a.cmd == "load":
        load(a.files)
    elif a.cmd == "stats":
        stats()
    elif a.cmd == "audit-build":
        audit_build()
    elif a.cmd == "audit-score":
        audit_score()
    else:
        print(SCHEMA)


if __name__ == "__main__":
    main()
