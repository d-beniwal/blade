#!/usr/bin/env python3
"""BLADE knowledge base for 1-ID: images + text from the experiment logs, labelled and searchable.

Needs the `blade` conda env (Pillow, numpy). Data root (outside the repo): the "kb" folder of the knowledge tree, see blade/paths.py (`python -m blade.paths`).

    kb.py ingest [--doc ID ...]            # sync text from logindex's logs.sqlite, extract every embedded image (content-addressed), auto-label
    kb.py stats                            # counts per class / source / year
    kb.py search "pin AND pg5" [--class detector_frame] [--subject pin] [--camera pg5] [-n 20]   # full-text over captions/headings, joined with labels
    kb.py show <sha-prefix>                # properties, labels history, every citation (doc:line) with its surrounding text
    kb.py sheet [--class tomo_view] [--unlabelled] [--doc ID] [--start 0] [-n 30]   # contact sheet JPEG for visual review
    kb.py label <sha-prefix>... key=value ... [--source vision|human] [--conf 0.9] [--note TEXT]
    kb.py labelfile FILE.tsv [--source vision]   # bulk: sha<TAB>key<TAB>value[<TAB>conf[<TAB>note]] per line
    kb.py addimage FILE... key=value ... [--note TEXT]   # standalone reference image (no log citation), human labels
    kb.py near <sha-prefix> [--max-dist 8]       # near-duplicate images (dhash Hamming distance)
    kb.py export --out FILE.jsonl [--class ...]  # one JSON object per image (labels + citations) for training / other tools

Citations are '<doc_id>:L<line>' - the same ids as beamline_twins/tools/logindex.py, so `logindex.py show <doc> --lines` reads the surrounding text.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
from blade import paths  # noqa: E402   (knowledge locations are configuration, see blade/paths.py)
KB_ROOT = paths.knowledge_dir("kb")
LOGS_SRC = paths.knowledge_dir("logs_src")
LOGS_DB = paths.knowledge_dir("logs_index") / "logs.sqlite"
DB = KB_ROOT / "kb.sqlite"

IMG_RE = re.compile(r"\[IMG ([^\]]+)\]")
ALT_RE = re.compile(r"\[ALT [^\]]*\]")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    KB_ROOT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=120)
    con.row_factory = sqlite3.Row
    con.executescript((HERE / "schema.sql").read_text())
    return con


# ----------------------------------------------------------------------------- image properties
def props(data):
    """Pixel statistics used for rule labelling + dedup. Returns dict (all None-safe)."""
    import io
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    try:
        im = Image.open(io.BytesIO(data))
        w, h, mode = im.width, im.height, im.mode
        if mode.startswith("I") or mode == "F":                                  # 16/32-bit: scale to 8 bit
            a = np.asarray(im, dtype=np.float64)
            lo, hi = np.percentile(a, [0.5, 99.5])
            im = Image.fromarray(np.clip((a - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype(np.uint8))
        rgb = im.convert("RGB")
        rgb.thumbnail((192, 192), Image.NEAREST)
        cols = rgb.getcolors(maxcolors=200000)
        n_colors = len(cols) if cols else 200000
        arr = np.asarray(rgb, dtype=np.int16)
        sat = float((np.abs(arr[..., 0] - arr[..., 1]) + np.abs(arr[..., 1] - arr[..., 2])).mean())
        g = np.asarray(im.convert("L").resize((192, 192) if max(w, h) > 192 else (w, h), Image.BILINEAR), dtype=np.float64)
        hist = np.bincount(g.astype(np.uint8).ravel(), minlength=256) / g.size
        ent = float(-(hist[hist > 0] * np.log2(hist[hist > 0])).sum())
        p1, p99 = np.percentile(g, [1, 99])
        s = np.asarray(im.convert("L").resize((9, 8), Image.BILINEAR), dtype=np.float64)
        bits = (s[:, 1:] > s[:, :-1]).ravel()
        dh = "%016x" % int("".join("1" if b else "0" for b in bits), 2)
        return dict(width=w, height=h, mode=mode, n_colors=n_colors, sat=sat, mean=float(g.mean()), std=float(g.std()),
                    p1=float(p1), p99=float(p99), entropy=ent, dhash=dh)
    except Exception as e:                                                       # emf/wmf/corrupt: still keep the bytes
        return dict(width=None, height=None, mode="ERR:" + type(e).__name__, n_colors=None, sat=None, mean=None, std=None,
                    p1=None, p99=None, entropy=None, dhash=None)


# ----------------------------------------------------------------------------- rule labels (cheap first pass; vision/human override)
CAMERA = re.compile(r"\b(pg1|pg5|gh1|pg-?[0-9]|retiga2?|lambda|eiger|pilatus|dexela|ge[1-5]?)\b", re.I)
HUTCH = re.compile(r"\b([ABCE])[\s-]?hutch\b|\b1-?ID-?([ABCE])\b|\bhutch\s*([ABCE])\b", re.I)
SUBJECT = [                                                                       # first match wins; ordered most specific first
    ("pin", re.compile(r"(?<!diode )\b(alignment pin|w pin|tungsten pin|needle|pin)\b(?! diode)", re.I)),   # "pin diode" is a detector, not the alignment pin
    ("dark", re.compile(r"\bdark(s| field| frame)?\b", re.I)),
    ("flat_or_beam_only", re.compile(r"\bflat|white[- ]?field|open beam|no sample|hotspot|beam (position|shape|profile|on)|optical axis|direct beam", re.I)),
    ("radiograph", re.compile(r"radiograph|projection|tomo(graphy)?\b|\bnf\b|sample (in|on)", re.I)),
    ("motor_panel", re.compile(r"motor|position(s)?\b|zero(ed)?|\bvelo|\bhi\b.*\blo\b", re.I)),
]


def rule_labels(p, ctx):
    """[(key, value, confidence, note)] from pixel statistics + the text around the image."""
    out = []
    w, h = p["width"], p["height"]
    if w is None:
        return [("class", "unreadable", 0.9, p["mode"])]
    nc, sat = p["n_colors"], p["sat"]
    if min(w, h) < 80:
        cls, conf = "icon", 0.8
    elif sat < 6 and p["mean"] < 205 and min(w, h) >= 200:
        cls, conf = "tomo_view", 0.5                  # grayscale + dark: detector frame (raw or in a viewer window); vision pass confirms/subclasses
    elif sat < 6:
        cls, conf = "plot_or_text", 0.5               # grayscale + mostly white: plot, terminal, table
    elif nc > 5000:
        cls, conf = "photo", 0.55
    elif sat >= 15 and nc <= 3000:
        cls, conf = "panel_screenshot", 0.55          # EPICS/MEDM panels (motors, slits, scalers)
    elif nc <= 3000:
        cls, conf = "screenshot", 0.4
    else:
        cls, conf = "unknown", 0.2
    out.append(("class", cls, conf, f"n_colors={nc} sat={sat:.1f} {w}x{h}"))
    text = " ".join(ctx[k] or "" for k in ("same_line", "before", "after", "h2", "h3"))
    m = CAMERA.search(text)
    if m:
        out.append(("camera", m.group(1).lower(), 0.5, "named in nearby text"))
    m = HUTCH.search(text)
    if m:
        out.append(("hutch", next(g for g in m.groups() if g).upper(), 0.5, "named in nearby text"))
    for name, rx in SUBJECT if cls == "tomo_view" else ():          # text keywords describe the SESSION, not the image: only trust them as a hint on detector frames
        if rx.search(text):
            out.append(("subject", name, 0.3, "keyword in nearby text"))
            break
    return out


# ----------------------------------------------------------------------------- ingest
def sync_text(con):
    """Copy docs/lines/tags/params from the logindex database (the text index is the single extractor of the logs)."""
    if not LOGS_DB.exists():
        sys.exit(f"{LOGS_DB} missing: run beamline_twins/tools/logindex.py build first")
    con.execute("ATTACH DATABASE ? AS L", (str(LOGS_DB),))
    for t in ("docs", "lines", "tags", "params"):
        con.execute(f"DELETE FROM {t}")
        con.execute(f"INSERT INTO {t} SELECT * FROM L.{t}")
    con.commit()
    con.execute("DETACH DATABASE L")


def context_for(rows, i):
    """Caption-ish text around line index i of a doc (rows: list of Row ordered by ln)."""
    def clean(t):
        return " ".join(ALT_RE.sub("", IMG_RE.sub("", t or "")).replace("|", " ").split())
    same = clean(rows[i]["text"])
    def scan(rng):
        got = []
        for j in rng:
            c = clean(rows[j]["text"])
            if c:
                got.append(c)
            if len(got) == 2:
                break
        return got
    before = scan(range(i - 1, max(i - 8, -1), -1))[::-1]
    after = scan(range(i + 1, min(i + 8, len(rows))))
    return same, " / ".join(before), " / ".join(after)


def ingest(docs=None):
    con = connect()
    sync_text(con)
    todo = [r for r in con.execute("SELECT doc_id, relpath FROM docs WHERE n_images > 0 ORDER BY doc_id")
            if not docs or r["doc_id"] in docs]
    known = {r[0] for r in con.execute("SELECT sha256 FROM images")}
    n_new = n_ref = 0
    for d in todo:
        did, path = d["doc_id"], LOGS_SRC / d["relpath"]
        rows = con.execute("SELECT * FROM lines WHERE doc_id=? ORDER BY ln", (did,)).fetchall()
        refs = [(i, m.group(1)) for i, r in enumerate(rows) for m in IMG_RE.finditer(r["text"] or "")]
        if not refs:
            continue
        if path.suffix.lower() != ".docx" or not path.exists():
            print(f"  skip {did}: {path.suffix} images not supported / file missing")
            continue
        con.execute("DELETE FROM image_refs WHERE doc_id=?", (did,))
        con.execute("DELETE FROM ref_fts WHERE doc_id=?", (did,))
        with zipfile.ZipFile(path) as z:
            members = {Path(n).name: n for n in z.namelist() if "/media/" in n}
            for k, (i, name) in enumerate(refs):
                if name not in members:
                    continue
                data = z.read(members[name])
                sha = hashlib.sha256(data).hexdigest()
                r = rows[i]
                same, before, after = context_for(rows, i)
                ctx = dict(same_line=same, before=before, after=after, h2=r["h2"], h3=r["h3"])
                if sha not in known:
                    ext = Path(name).suffix.lower().lstrip(".") or "bin"
                    rel = f"images/{sha[:2]}/{sha}.{ext}"
                    (KB_ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
                    (KB_ROOT / rel).write_bytes(data)
                    p = props(data)
                    con.execute("INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (sha, ext, len(data), p["width"], p["height"], p["mode"], p["n_colors"], p["sat"], p["mean"], p["std"],
                                 p["p1"], p["p99"], p["entropy"], p["dhash"], rel))
                    for key, val, conf, note in rule_labels(p, ctx):
                        con.execute("INSERT INTO labels VALUES(?,?,?,?,?,?,?)", (sha, key, val, "rule", conf, now(), note))
                    known.add(sha)
                    n_new += 1
                con.execute("INSERT OR REPLACE INTO image_refs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (did, name, sha, r["ln"], k, r["h1"], r["h2"], r["h3"], r["date"], int((r["text"] or "").lstrip().startswith("|")),
                             same, before, after))
                con.execute("INSERT INTO ref_fts VALUES(?,?,?,?)",
                            (did, name, sha, " ".join(x for x in (r["h1"], r["h2"], r["h3"], before, same, after, d["relpath"]) if x)))
                n_ref += 1
        con.commit()
        print(f"  {did}: {len(refs)} refs")
    print(f"images: +{n_new} new unique, {n_ref} citations; total unique {con.execute('SELECT COUNT(*) FROM images').fetchone()[0]}")


# ----------------------------------------------------------------------------- queries
def resolve(con, prefix):
    rows = con.execute("SELECT sha256 FROM images WHERE sha256 LIKE ?", (prefix + "%",)).fetchall()
    if len(rows) != 1:
        sys.exit(f"'{prefix}' matches {len(rows)} images")
    return rows[0][0]


def cmd_stats(a):
    con = connect()
    print("class x source:")
    for r in con.execute("SELECT value, source, COUNT(*) n FROM label_best WHERE key='class' GROUP BY 1,2 ORDER BY n DESC"):
        print(f"  {r['value']:18s} {r['source']:7s} {r['n']}")
    print("subject:", [(r[0], r[1]) for r in con.execute("SELECT value, COUNT(*) FROM label_best WHERE key='subject' GROUP BY 1 ORDER BY 2 DESC")])
    print("camera: ", [(r[0], r[1]) for r in con.execute("SELECT value, COUNT(*) FROM label_best WHERE key='camera' GROUP BY 1 ORDER BY 2 DESC")])
    print("per year (citations):", [(r[0], r[1]) for r in con.execute(
        "SELECT substr(doc_id,1,4), COUNT(*) FROM image_refs GROUP BY 1")])
    print("unique/total:", con.execute("SELECT COUNT(*) FROM images").fetchone()[0], "/", con.execute("SELECT COUNT(*) FROM image_refs").fetchone()[0])


def cmd_search(a):
    con = connect()
    q = ("SELECT DISTINCT f.sha256, x.class, x.subject, x.camera, x.hutch, x.class_source, x.n_refs, "
         "(SELECT doc_id||':L'||ln FROM image_refs r WHERE r.sha256=f.sha256 LIMIT 1) AS cite, "
         "(SELECT COALESCE(NULLIF(same_line,''), before) FROM image_refs r WHERE r.sha256=f.sha256 LIMIT 1) AS cap "
         "FROM ref_fts f JOIN image_index x ON x.sha256=f.sha256 WHERE ref_fts MATCH ?")
    args = [a.query]
    for col, v in (("class", a.cls), ("subject", a.subject), ("camera", a.camera), ("hutch", a.hutch)):
        if v:
            q += f" AND x.{col}=?"
            args.append(v)
    for r in con.execute(q + " LIMIT ?", args + [a.n]):
        print(f"{r['sha256'][:10]}  {str(r['class']):16s} {str(r['subject']):18s} {str(r['camera']):7s} {str(r['hutch']):2s} "
              f"[{r['class_source']}] x{r['n_refs']}  {r['cite']}  {(r['cap'] or '')[:70]}")


def cmd_show(a):
    con = connect()
    sha = resolve(con, a.sha)
    i = con.execute("SELECT * FROM images WHERE sha256=?", (sha,)).fetchone()
    print(dict(i))
    print("labels (history):")
    for r in con.execute("SELECT * FROM labels WHERE sha256=? ORDER BY key, created", (sha,)):
        print(f"  {r['key']:8s} = {r['value']:20s} [{r['source']} {r['confidence']}] {r['note'] or ''}")
    print("citations:")
    for r in con.execute("SELECT * FROM image_refs WHERE sha256=?", (sha,)):
        print(f"  {r['doc_id']}:L{r['ln']} [{r['date']}] {r['h1']} > {r['h2']} > {r['h3']}\n     before: {r['before']}\n     line:   {r['same_line']}\n     after:  {r['after']}")
    print("file:", KB_ROOT / i["path"])


def cmd_sheet(a):
    from PIL import Image, ImageDraw, ImageFont
    Image.MAX_IMAGE_PIXELS = None
    con = connect()
    q = "SELECT x.sha256, x.path, x.class, x.subject, x.camera, (SELECT doc_id||':L'||ln FROM image_refs r WHERE r.sha256=x.sha256 LIMIT 1) cite, " \
        "(SELECT COALESCE(NULLIF(same_line,''), before) FROM image_refs r WHERE r.sha256=x.sha256 LIMIT 1) cap FROM image_index x WHERE 1=1"
    args = []
    if a.cls:
        q += " AND x.class=?"; args.append(a.cls)
    if a.unlabelled:
        q += " AND x.class_source='rule'"
    if a.doc:
        q += " AND x.sha256 IN (SELECT sha256 FROM image_refs WHERE doc_id=?)"; args.append(a.doc)
    if a.ids:                                            # fixed list of sha prefixes (one per line): stable under relabelling
        ids = [x.split()[0] for x in Path(a.ids).read_text().splitlines() if x.strip()]
        q += " AND (" + " OR ".join("x.sha256 LIKE ?" for _ in ids) + ")"; args += [i + "%" for i in ids]
    rows = con.execute(q + " ORDER BY cite LIMIT ? OFFSET ?", args + [a.n, a.start]).fetchall()
    if not rows:
        sys.exit("no images")
    T, cols = a.thumb, a.cols
    rws = math.ceil(len(rows) / cols)
    sheet = Image.new("RGB", (cols * T, rws * (T + 34)), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=11)
    except TypeError:
        font = ImageFont.load_default()
    for k, r in enumerate(rows):
        x, y = (k % cols) * T, (k // cols) * (T + 34)
        try:
            im = Image.open(KB_ROOT / r["path"])
            if im.mode.startswith("I") or im.mode == "F":
                import numpy as np
                arr = np.asarray(im, dtype=float); lo, hi = np.percentile(arr, [0.5, 99.5])
                im = Image.fromarray(np.clip((arr - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype("uint8"))
            im = im.convert("RGB"); im.thumbnail((T - 4, T - 4))
            sheet.paste(im, (x + 2, y + 2))
        except Exception:
            d.text((x + 6, y + 6), "unreadable", fill=(255, 120, 120), font=font)
        d.text((x + 3, y + T), f"#{a.start + k} {r['sha256'][:8]} {r['class'] or ''}", fill=(255, 255, 255), font=font)
        d.text((x + 3, y + T + 14), (r["cap"] or "")[:34], fill=(180, 200, 255), font=font)
    out = KB_ROOT / "review"
    out.mkdir(exist_ok=True)
    f = out / f"sheet_{Path(a.ids).stem if a.ids else (a.cls or 'all')}_{a.start}.jpg"
    sheet.save(f, quality=85)
    print(f)
    for k, r in enumerate(rows):
        print(f"#{a.start + k}\t{r['sha256'][:10]}\t{r['cite']}\t{(r['cap'] or '')[:90]}")


def add_label(con, sha, key, val, source, conf, note):
    con.execute("INSERT INTO labels VALUES(?,?,?,?,?,?,?)", (sha, key, val, source, conf, now(), note))


def cmd_label(a):
    con = connect()
    kv = [x.split("=", 1) for x in a.items if "=" in x]
    shas = [resolve(con, x) for x in a.items if "=" not in x]
    for sha in shas:
        for k, v in kv:
            add_label(con, sha, k, v, a.source, a.conf, a.note)
    con.commit()
    print(f"labelled {len(shas)} image(s) with {kv}")


def cmd_addimage(a):
    """Register standalone reference images (no log citation), e.g. CS-Studio screenshots, with human labels: addimage FILE... key=value ..."""
    con = connect()
    kv = [x.split("=", 1) for x in a.items if "=" in x]
    known = {r[0] for r in con.execute("SELECT sha256 FROM images")}
    for f in (Path(x) for x in a.items if "=" not in x):
        data = f.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if sha not in known:
            ext = f.suffix.lower().lstrip(".") or "bin"
            rel = f"images/{sha[:2]}/{sha}.{ext}"
            (KB_ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
            (KB_ROOT / rel).write_bytes(data)
            p = props(data)
            con.execute("INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sha, ext, len(data), p["width"], p["height"], p["mode"], p["n_colors"], p["sat"], p["mean"], p["std"],
                         p["p1"], p["p99"], p["entropy"], p["dhash"], rel))
        add_label(con, sha, "origin", "reference:" + f.name, "human", 1.0, a.note)
        for k, v in kv:
            add_label(con, sha, k, v, "human", 1.0, a.note)
        print(f"{sha[:12]}  {f.name}  {'(already present)' if sha in known else 'added'}")
    con.commit()


def cmd_labelfile(a):
    con = connect()
    n = 0
    for ln in Path(a.file).read_text().splitlines():
        f = ln.split("\t")
        if len(f) < 3 or ln.startswith("#"):
            continue
        add_label(con, resolve(con, f[0]), f[1], f[2], a.source, float(f[3]) if len(f) > 3 and f[3] else a.conf, f[4] if len(f) > 4 else None)
        n += 1
    con.commit()
    print(f"{n} labels added")


def cmd_near(a):
    con = connect()
    sha = resolve(con, a.sha)
    h = int(con.execute("SELECT dhash FROM images WHERE sha256=?", (sha,)).fetchone()[0], 16)
    for r in con.execute("SELECT sha256, dhash FROM images WHERE dhash IS NOT NULL AND sha256!=?", (sha,)):
        dist = bin(h ^ int(r["dhash"], 16)).count("1")
        if dist <= a.max_dist:
            print(dist, r["sha256"][:10])


def cmd_export(a):
    con = connect()
    q = "SELECT * FROM image_index" + (" WHERE class=?" if a.cls else "")
    with open(a.out, "w") as fh:
        n = 0
        for r in con.execute(q, [a.cls] if a.cls else []):
            rec = dict(r)
            rec["labels"] = [dict(x) for x in con.execute("SELECT key,value,source,confidence,note FROM label_best WHERE sha256=?", (r["sha256"],))]
            rec["citations"] = [dict(x) for x in con.execute(
                "SELECT doc_id,ln,date,h1,h2,h3,before,same_line,after FROM image_refs WHERE sha256=?", (r["sha256"],))]
            fh.write(json.dumps(rec) + "\n"); n += 1
    print(f"{n} records -> {a.out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("ingest"); s.add_argument("--doc", nargs="*"); s.set_defaults(f=lambda a: ingest(a.doc))
    sp.add_parser("stats").set_defaults(f=cmd_stats)
    s = sp.add_parser("search"); s.add_argument("query"); s.add_argument("--class", dest="cls"); s.add_argument("--subject")
    s.add_argument("--camera"); s.add_argument("--hutch"); s.add_argument("-n", type=int, default=20); s.set_defaults(f=cmd_search)
    s = sp.add_parser("show"); s.add_argument("sha"); s.set_defaults(f=cmd_show)
    s = sp.add_parser("sheet"); s.add_argument("--class", dest="cls"); s.add_argument("--unlabelled", action="store_true")
    s.add_argument("--doc"); s.add_argument("--ids"); s.add_argument("--start", type=int, default=0); s.add_argument("-n", type=int, default=30)
    s.add_argument("--thumb", type=int, default=220); s.add_argument("--cols", type=int, default=6); s.set_defaults(f=cmd_sheet)
    s = sp.add_parser("label"); s.add_argument("items", nargs="+"); s.add_argument("--source", default="vision", choices=["vision", "human", "rule"])
    s.add_argument("--conf", type=float, default=0.8); s.add_argument("--note"); s.set_defaults(f=cmd_label)
    s = sp.add_parser("addimage"); s.add_argument("items", nargs="+"); s.add_argument("--note"); s.set_defaults(f=cmd_addimage)
    s = sp.add_parser("labelfile"); s.add_argument("file"); s.add_argument("--source", default="vision", choices=["vision", "human", "rule"])
    s.add_argument("--conf", type=float, default=0.8); s.set_defaults(f=cmd_labelfile)
    s = sp.add_parser("near"); s.add_argument("sha"); s.add_argument("--max-dist", type=int, default=8); s.set_defaults(f=cmd_near)
    s = sp.add_parser("export"); s.add_argument("--out", required=True); s.add_argument("--class", dest="cls"); s.set_defaults(f=cmd_export)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
