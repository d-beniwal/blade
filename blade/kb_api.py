"""Read-only data for the knowledge-base viewer (`/kb` in `blade gui`): procedures, labelled log images and the log text, from the local knowledge base
built by `knowledge_base/kb.py` (SQLite + image files, OUTSIDE this repo: unpublished user logs). Everything here opens the database read-only,
resolves images only through the `images` table (never a client-supplied path) and never touches hardware or `blade.config` state.

KB location: $KB_ROOT, else <workspace>/kb_1ID (a sibling of this repo's parent, same default as knowledge_base/kb.py)."""
import io
import json
import os
import re
import sqlite3
from pathlib import Path

from . import paths

KB_DIR = Path(os.environ["KB_ROOT"]).expanduser() if os.environ.get("KB_ROOT") else paths.ROOT.parent / "kb_1ID"
IMG_RE = re.compile(r"\[IMG ([^\]]+)\]")
ALT_RE = re.compile(r"\[ALT [^\]]*\]")
CITE_RE = re.compile(r"^(?P<doc>[^:]+):L(?P<a>\d+)(?:-(?P<b>\d+))?$")
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff"}


def available():
    return (KB_DIR / "kb.sqlite").is_file()


def _con():
    db = KB_DIR / "kb.sqlite"
    if not db.is_file():
        raise FileNotFoundError(f"knowledge base not found at {db} (build it with knowledge_base/kb.py ingest; override the folder with $KB_ROOT)")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _fts(q):
    """User text -> a safe FTS5 query: every word must occur (AND), the last one as a prefix."""
    toks = re.findall(r"[\w.+\-]+", q or "")
    if not toks:
        return None
    return " ".join(f'"{t}"' for t in toks[:-1]) + (" " if len(toks) > 1 else "") + f'"{toks[-1]}"*'


def _like_terms(q):
    return [t for t in re.findall(r"[^\s]+", q or "") if t][:8]


def _rows(cur):
    return [dict(r) for r in cur]


def _has(con, table):
    return con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is not None


# ------------------------------------------------------------------------------------------------------------------------------ status / facets
def status():
    if not available():
        return {"available": False, "root": str(KB_DIR), "hint": "Build the knowledge base first: python knowledge_base/kb.py ingest (see knowledge_base/README.md), or set $KB_ROOT."}
    con = _con()
    one = lambda sql: con.execute(sql).fetchone()[0]
    out = {"available": True, "root": str(KB_DIR), "docs": one("SELECT COUNT(*) FROM docs"), "lines": one("SELECT COUNT(*) FROM lines"),
           "images": one("SELECT COUNT(*) FROM images"), "citations": one("SELECT COUNT(*) FROM image_refs"),
           "procedures": one("SELECT COUNT(*) FROM procedures") if _has(con, "procedures") else 0}
    out["years"] = [r[0] for r in con.execute("SELECT DISTINCT year FROM docs WHERE year>0 ORDER BY 1")]
    out["kinds"] = [r[0] for r in con.execute("SELECT DISTINCT kind FROM docs ORDER BY 1")]
    return out


def facets():
    con = _con()
    out = {}
    for key in ("class", "subject", "camera", "hutch", "device"):
        out[key] = [[r[0], r[1]] for r in con.execute(
            "SELECT value, COUNT(*) n FROM label_best WHERE key=? GROUP BY value ORDER BY n DESC LIMIT 60", (key,))]
    out["source"] = [[r[0], r[1]] for r in con.execute("SELECT source, COUNT(*) FROM label_best WHERE key='class' GROUP BY source")]
    return out


# ------------------------------------------------------------------------------------------------------------------------------ procedures
def proc_list():
    con = _con()
    if not _has(con, "procedures"):
        return {"procedures": []}
    return {"procedures": _rows(con.execute("SELECT id, name, goal, n_steps, n_cites, scope FROM procedures ORDER BY id"))}


def proc_get(pid):
    con = _con()
    r = con.execute("SELECT json FROM procedures WHERE id=?", (pid,)).fetchone()
    if not r:
        raise ValueError(f"unknown procedure {pid!r}")
    return json.loads(r[0])


def proc_search(q):
    con = _con()
    f = _fts(q)
    if not f or not _has(con, "proc_fts"):
        return {"results": []}
    hits = {}
    for r in con.execute("SELECT proc_id, kind, snippet(proc_fts, 2, '<mark>', '</mark>', '…', 14) AS snip FROM proc_fts WHERE proc_fts MATCH ? ORDER BY rank LIMIT 120", (f,)):
        hits.setdefault(r["proc_id"], []).append({"kind": r["kind"], "snippet": _clean_snip(r["snip"])})
    names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM procedures")}
    return {"results": [{"id": k, "name": names.get(k, k), "hits": v[:6], "n": len(v)} for k, v in sorted(hits.items(), key=lambda kv: -len(kv[1]))]}


def numbers(q):
    con = _con()
    like = f"%{q}%"
    return {"numbers": _rows(con.execute(
        "SELECT proc_id, step_n, quantity, value, unit, context, era, cites FROM procedure_numbers WHERE quantity LIKE ? OR context LIKE ? ORDER BY proc_id, step_n LIMIT 300",
        (like, like)))}


def _clean_snip(s):
    """snippet() output with only <mark> kept (everything else escaped), safe to inject as HTML"""
    s = (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s.replace("&lt;mark&gt;", "<mark>").replace("&lt;/mark&gt;", "</mark>")


# ------------------------------------------------------------------------------------------------------------------------------ images
_IMG_SQL = ("SELECT x.sha256, x.width, x.height, x.class, x.subject, x.camera, x.hutch, x.class_source, x.n_refs, "
            "(SELECT value FROM label_best b WHERE b.sha256=x.sha256 AND b.key='device') AS device, "
            "(SELECT value FROM label_best b WHERE b.sha256=x.sha256 AND b.key='legible') AS legible, "
            "(SELECT value FROM label_best b WHERE b.sha256=x.sha256 AND b.key='value_rich') AS value_rich, "
            "(SELECT doc_id||':L'||ln FROM image_refs r WHERE r.sha256=x.sha256 ORDER BY doc_id, ln LIMIT 1) AS cite, "
            "(SELECT COALESCE(NULLIF(same_line,''), before) FROM image_refs r WHERE r.sha256=x.sha256 ORDER BY doc_id, ln LIMIT 1) AS cap "
            "FROM image_index x WHERE 1=1")


def image_search(q="", cls="", subject="", camera="", hutch="", source="", device="", offset=0, limit=60):
    con = _con()
    where, args = "", []
    f = _fts(q)
    if f:
        where += (" AND (x.sha256 IN (SELECT sha256 FROM ref_fts WHERE ref_fts MATCH ?)"
                  " OR x.sha256 IN (SELECT sha256 FROM label_best WHERE key IN ('device','subject','camera') AND value LIKE ?))")
        args += [f, f"%{q.strip()}%"]
    for col, v in (("class", cls), ("subject", subject), ("camera", camera), ("hutch", hutch), ("class_source", source)):
        if v:
            where += f" AND x.{col}=?"
            args.append(v)
    if device:
        where += " AND x.sha256 IN (SELECT sha256 FROM label_best WHERE key='device' AND value LIKE ?)"
        args.append(f"%{device}%")
    total = con.execute("SELECT COUNT(*) FROM image_index x WHERE 1=1" + where, args).fetchone()[0]
    rows = _rows(con.execute(_IMG_SQL + where + " ORDER BY cite LIMIT ? OFFSET ?", args + [min(int(limit), 200), max(int(offset), 0)]))
    for r in rows:
        r["sha"] = r.pop("sha256")[:16]
    return {"total": total, "images": rows}


def _resolve(con, sha):
    if not re.fullmatch(r"[0-9a-f]{6,64}", sha or ""):
        raise ValueError("bad image id")
    rows = con.execute("SELECT * FROM images WHERE sha256 LIKE ?", (sha + "%",)).fetchall()
    if len(rows) != 1:
        raise ValueError(f"image {sha!r} matches {len(rows)} images")
    return rows[0]


def image_info(sha):
    con = _con()
    i = _resolve(con, sha)
    full = i["sha256"]
    info = {k: i[k] for k in ("sha256", "ext", "bytes", "width", "height", "mode", "n_colors", "sat", "mean", "std", "entropy")}
    labels = _rows(con.execute("SELECT key, value, source, confidence, created, note FROM labels WHERE sha256=? ORDER BY key, created", (full,)))
    best = {r["key"]: r for r in con.execute("SELECT key, value, source FROM label_best WHERE sha256=?", (full,))}
    refs = _rows(con.execute("SELECT doc_id, name, ln, h1, h2, h3, date, same_line, before, after FROM image_refs WHERE sha256=? ORDER BY doc_id, ln", (full,)))
    return {"image": info, "labels": labels, "best": {k: dict(v) for k, v in best.items()}, "citations": refs}


def image_bytes(sha, width=0):
    """(bytes, mime) of an image or its JPEG thumbnail (cached under <KB>/thumbs/); the file is found via the images table only."""
    con = _con()
    i = _resolve(con, sha)
    f = (KB_DIR / i["path"]).resolve()
    if KB_DIR.resolve() not in f.parents or not f.is_file():
        raise FileNotFoundError("image file missing")
    width = max(0, min(int(width or 0), 2400))
    if width == 0:
        return f.read_bytes(), MIME.get(i["ext"].lower(), "application/octet-stream")
    cache = KB_DIR / "thumbs" / f"{i['sha256'][:24]}_{width}.jpg"
    if cache.is_file():
        return cache.read_bytes(), "image/jpeg"
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        im = Image.open(f)
        if im.mode.startswith("I") or im.mode == "F":                      # 16/32-bit detector frames: stretch to 8 bit
            import numpy as np
            a = np.asarray(im, dtype=float)
            lo, hi = np.percentile(a, [0.5, 99.5])
            im = Image.fromarray(np.clip((a - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype("uint8"))
        im = im.convert("RGB")
        im.thumbnail((width, width))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        data = buf.getvalue()
        try:
            cache.parent.mkdir(exist_ok=True)
            cache.write_bytes(data)
        except OSError:
            pass
        return data, "image/jpeg"
    except Exception:                                                       # unreadable by PIL (emf/wmf/...): send the original bytes
        return f.read_bytes(), MIME.get(i["ext"].lower(), "application/octet-stream")


# ------------------------------------------------------------------------------------------------------------------------------ log text
def _clean(t):
    return " ".join(ALT_RE.sub("", IMG_RE.sub("", t or "")).replace("\xa0", " ").split())


def text_search(q, year="", kind="", offset=0, limit=60):
    con = _con()
    terms = _like_terms(q)
    if not terms:
        return {"total": 0, "hits": []}
    where, args = "", []
    for t in terms:
        where += " AND l.text LIKE ? ESCAPE '\\'"
        args.append("%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if year:
        where += " AND d.year=?"
        args.append(int(year))
    if kind:
        where += " AND d.kind=?"
        args.append(kind)
    base = " FROM lines l JOIN docs d ON d.doc_id=l.doc_id WHERE 1=1" + where
    total = con.execute("SELECT COUNT(*)" + base, args).fetchone()[0]
    rows = con.execute("SELECT l.doc_id, l.ln, l.h1, l.h2, l.h3, l.date, l.text, d.kind, d.year" + base + " ORDER BY d.year DESC, l.doc_id, l.ln LIMIT ? OFFSET ?",
                       args + [min(int(limit), 200), max(int(offset), 0)]).fetchall()
    hits = []
    for r in rows:
        h = dict(r)
        h["text"] = _clean(h["text"])[:400]
        hits.append(h)
    return {"total": total, "hits": hits, "terms": terms}


def doc_list(q="", year="", kind=""):
    con = _con()
    where, args = "", []
    if q:
        where += " AND (doc_id LIKE ? OR title LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if year:
        where += " AND year=?"
        args.append(int(year))
    if kind:
        where += " AND kind=?"
        args.append(kind)
    return {"docs": _rows(con.execute(
        "SELECT doc_id, year, kind, title, exp_time, date_first, date_last, n_lines, n_images FROM docs WHERE 1=1" + where + " ORDER BY year DESC, doc_id", args))}


def doc_outline(doc):
    con = _con()
    rows = con.execute("SELECT h1, h2, h3, MIN(ln) AS ln, COUNT(*) AS n FROM lines WHERE doc_id=? GROUP BY h1, h2, h3 ORDER BY MIN(ln)", (doc,)).fetchall()
    d = con.execute("SELECT * FROM docs WHERE doc_id=?", (doc,)).fetchone()
    if not d:
        raise ValueError("unknown document")
    return {"doc": {k: d[k] for k in ("doc_id", "year", "kind", "title", "exp_time", "date_first", "date_last", "n_lines", "n_images")}, "sections": _rows(rows)}


def doc_window(doc, a, b, ctx=0):
    """Log lines doc:L(a-ctx)..L(b+ctx) with their headings; image markers become `imgs` entries (id, class, subject) so the page can show them inline."""
    con = _con()
    d = con.execute("SELECT doc_id, year, kind, title, date_first, date_last, n_lines FROM docs WHERE doc_id=?", (doc,)).fetchone()
    if not d:
        raise ValueError("unknown document")
    lo, hi = max(1, int(a) - int(ctx)), min(d["n_lines"] + 5, int(b) + int(ctx))
    refs = {(r["name"], r["ln"]): r["sha256"] for r in con.execute("SELECT name, ln, sha256 FROM image_refs WHERE doc_id=? AND ln BETWEEN ? AND ?", (doc, lo, hi))}
    cls = {}
    lines = []
    for r in con.execute("SELECT ln, h1, h2, h3, date, text FROM lines WHERE doc_id=? AND ln BETWEEN ? AND ? ORDER BY ln", (doc, lo, hi)):
        imgs = []
        for m in IMG_RE.finditer(r["text"] or ""):
            sha = refs.get((m.group(1), r["ln"]))
            if sha:
                if sha not in cls:
                    cls[sha] = {x["key"]: x["value"] for x in con.execute("SELECT key, value FROM label_best WHERE sha256=?", (sha,))}
                imgs.append({"sha": sha[:16], "class": cls[sha].get("class"), "subject": cls[sha].get("subject"), "device": cls[sha].get("device")})
        lines.append({"ln": r["ln"], "h1": r["h1"], "h2": r["h2"], "h3": r["h3"], "date": r["date"], "text": _clean(r["text"]), "imgs": imgs})
    return {"doc": dict(d), "from": lo, "to": hi, "mark": [int(a), int(b)], "lines": lines}


def cite_window(c, ctx=8):
    m = CITE_RE.match((c or "").strip())
    if not m:
        raise ValueError(f"bad citation {c!r} (expected doc:L<line> or doc:L<a>-<b>)")
    a = int(m["a"])
    b = int(m["b"] or m["a"])
    return doc_window(m["doc"], a, b, ctx)
