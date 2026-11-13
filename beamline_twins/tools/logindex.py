#!/usr/bin/env python3
"""Searchable index of the beamline experiment logs (stdlib only: zipfile + sqlite3/FTS5).

The logs (docx/xlsx/ods, years of them, ~1.7 GB mostly embedded images) are read ONCE into a local SQLite database plus per-document text
files, so a question like "what did we do about the E-hutch slit alignment in startups" is a query, not a re-read.

    python beamline_twins/tools/logindex.py build                         # extract + index (default source: the logs_src folder of the knowledge tree)
    python beamline_twins/tools/logindex.py catalog                       # one line per document (kind, dates, energy, sizes)
    python beamline_twins/tools/logindex.py outline <doc>                 # headings with line numbers
    python beamline_twins/tools/logindex.py show <doc> [--lines 10-60 | --section "Energy"] [--ctx]
    python beamline_twins/tools/logindex.py search "slit AND alignment" [--kind startup] [--year 2025] [--topic slit] [-n 30]
    python beamline_twins/tools/logindex.py topic slit [--kind startup]   # sections of the logs about a topic, ranked
    python beamline_twins/tools/logindex.py params energy_keV [--kind startup]   # every extracted value + summary statistics
    python beamline_twins/tools/logindex.py images <doc> [--names image3.png ...] [--out DIR]   # pull embedded screenshots to look at

Output lives in the knowledge tree (logs_index/, outside the repo: the logs are users' unpublished experiment records; the repo is public).
Doc ids look like '2025-startup_jan25_explog'; a citation is '<doc>:L<line>'.
"""
import argparse
import json
import os
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import logextract  # noqa: E402

TWINS = HERE.parent
sys.path.insert(0, str(TWINS.parent))
from blade import paths  # noqa: E402   (knowledge locations are configuration, see blade/paths.py)
DEFAULT_SRC = paths.knowledge_dir("logs_src")
DEFAULT_BL = "1-ID"

# ----------------------------------------------------------------------------- classification
STARTUP_NAME = re.compile(r"startup|(^|[_\-])mpe[_\-]|lastlight|techcomm|brightness|alignment_reference|am[_\-]?setup|amsetup", re.I)


def classify(rel):
    name = Path(rel).stem
    if Path(rel).suffix.lower() in (".xlsx", ".ods"):
        return "tables"
    return "startup" if STARTUP_NAME.search(name) else "user"


# ----------------------------------------------------------------------------- topics (regex tags per line)
TOPICS = {
    "energy":      r"\bkev\b|\bE_?hem\b|\bhem\b|mono(chromator)?|\bedge\b|energy|wavelength|emon|userTran3|\bTh1\b|bragg",
    "foil":        r"\bfoil|\bE_?cal|\bmu_?t\b|\but\s*=|calibrat\w* (the )?energy",
    "undulator":   r"undulator|\bgap\b|harmonic|\bID\b|\bSCU\b|\bPMU\b|brightness mode|taper|bunch",
    "wb_slit":     r"\bWB\b|white[- ]beam",
    "slit":        r"slit|kohzu|\bhsize|\bvsize|\bhcenter|\bvcenter|zero_slits|aperture",
    "lens":        r"\blens|\bCRL|focus|focal|\bstack|lens alignment|\bBCS\b",
    "ion_chamber": r"\bIC\d?_?\w*|ion chamber|preamp|\bkHz\b|nA/V|\bflux\b|photon",
    "shutter":     r"shutter|\bFS\b|\bfast[- ]shutter|\bfes\b|\bsbs\b",
    "sample_stage": r"sam[EC]\b|\baero|rotation axis|axis of rotation|\bpin\b|wedge|\btilt|\bhexapod|\bMTS\b|\bsmsE?\b|stage|\bsample (position|align)|goniometer|\bomega\b",
    "tomo":        r"\btomo|\bgh1\b|\bpg[15]\b|\bPG\d\b|\bGH1\b|microscope|scintillator|\bLuAG|pixel size|retiga|\bcamera\b|\bobjective",
    "detector":    r"\bGE\d?\b|pixirad|varex|hydra|\bHS\b|\bD[1-6]\b|detector|eiger|\bdsam\b|panel|sample[- ]to[- ]detector|distance",
    "calibration": r"ceo2|ceria|lab6|calibrant|\bmidas\b|calibration|beam center|\btilts?\b|\bbc\b|\bpyfai\b|geometry",
    "alignment":   r"align|center(ing|ed)?\b|beam (position|size|center)|steer|\bscan\b.{0,20}(slit|focus|gap)|find the beam|in the beam|peak up",
    "software":    r"\bRE\(|\bbluesky|\bqserver|\bqueue|\bioc\b|\bepics|caput|\bcaget|\bmacro|\bplan\b|\bphoebus|\bcs-studio|\bmedm|\bspec\b|\bipython|\bdm\b|data management|\bmda\b|\bhdf",
    "problem":     r"problem|issue|\bfail|\bbroken|crash|\bnot work|noise|drift|vibrat|clipp|lost beam|beam dump|trip|\bstuck|error|\bfix",
    "beam_size":   r"beam size|\bfwhm\b|\bfootprint|µm ?x|um ?x|\bspot",
    "exposure":    r"exposure|\bframe rate|\bfps\b|\bms\b|trigger|\bfly|\bsnake|step scan|\bn_?frames",
}
TOPIC_RE = {k: re.compile(v, re.I) for k, v in TOPICS.items()}

# ----------------------------------------------------------------------------- parameter extraction
NUM = r"(\d+(?:\.\d+)?)"
SIGNED = r"(-?\d+(?:\.\d+)?)"
PARAM_PATTERNS = [
    ("energy_keV", re.compile(NUM + r"\s*keV", re.I), 1),
    ("E_hem_keV", re.compile(r"\bE_?hem\s*[=:]?\s*" + NUM, re.I), 1),
    ("wavelength_A", re.compile(NUM + r"\s*(?:Å|angstrom)", re.I), 1),
    ("mu_t", re.compile(r"\b(?:ut|mu_?t)\s*=\s*" + NUM, re.I), 1),
    ("gap_mm", re.compile(r"\b(?:ID\s*)?gap\s*(?:=|:|to|at|of)?\s*" + NUM + r"\s*mm", re.I), 1),
    ("harmonic_n", re.compile(r"\bn\s*=\s*(\d{1,2})\b(?!\s*[\d.]*\s*(?:mm|um|kHz|keV))"), 1),
    ("ring_current_mA", re.compile(NUM + r"\s*mA\b", re.I), 1),
    ("th1_offset_deg", re.compile(r"\bTh1\s*offset\s*=?\s*" + SIGNED, re.I), 1),
    ("ic_rate_kHz", re.compile(r"\b(IC_?\w*)\s*=\s*" + NUM + r"\s*kHz", re.I), 2),
    ("preamp_gain", re.compile(r"(\d+)\s*([npµu]A)/V", re.I), 0),
    ("distance_mm", re.compile(r"\b(?:Dsam|SDD|dist(?:ance)?\w*|D\s*=)\s*(?:~|=|:|of|at)?\s*" + NUM + r"\s*mm", re.I), 1),
    ("pixel_um", re.compile(NUM + r"\s*(?:um|µm|micron)s?\b(?:\s*/?\s*(?:px|pixel))?", re.I), 1),
    ("exposure_s", re.compile(r"\bexposure(?:\s*time)?\s*(?:=|:|of|to|at)?\s*" + NUM + r"\s*(ms|s)\b", re.I), 0),
    ("foil_wheel", re.compile(r"\bfoil\s*wheel\s*=\s*" + SIGNED, re.I), 1),
    ("edge", re.compile(r"\b(Au|Re|Pt|Bi|W|Ta|Pb|Ir|Os|Hf|U|Th|Pd|Ag|Cu|Mo|Zr|Nb|Ru|Rh|Sn|Ce|Er|Yb|Tm|Gd|Hg|Tl)\s*[- ]?K[- ]?(?:edge|\b)", re.I), 1),
    ("lens_count", re.compile(r"\b(\d{1,3})\s*(?:x\s*)?(?:Si\s*|Al\s*|Be\s*|diamond\s*)?lens(?:es)?\b", re.I), 1),
]
SLIT_RE = re.compile(r"(?P<name>WB|[A-Za-z_]*[Ss]lits?[A-Za-z_0-9 ]{0,10}?|Kohzu[A-Za-z_0-9]*|[A-Z]_Kuz\w*|BCS\w*)\s*(?:=|:|to|at|@|\()?\s*" + NUM + r"\s*(?:mm)?\s*[x×X]\s*" + NUM)
WBPOS_RE = re.compile(r"WB\s*=\s*" + NUM + r"\s*x\s*" + NUM + r"\s*@\s*\[\s*" + SIGNED + r"\s*,\s*" + SIGNED + r"\s*\]")

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d\d)-(?P<m>\d\d)-(?P<d>\d\d)"),
    re.compile(r"(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?P<mon>[A-Za-z]{3,9})\.?,?\s+(?P<y>20\d\d)"),
    re.compile(r"(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>20\d\d)"),
    re.compile(r"(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>(?:20)?\d\d)\b"),
    re.compile(r"(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<d>\d{1,2})\b(?!\d)"),                       # 'Jan 27' (year from the document)
]
LABELS = ["Brief setup description", "Samples", "Environment", "X-ray sample setup", "X-ray detectors", "X-ray energy", "Experimenters", "Beamline scientists", "GUP title", "Experiment time"]


def parse_date(text, default_year):
    for k, rx in enumerate(DATE_PATTERNS):
        m = rx.search(text)
        if not m:
            continue
        g = m.groupdict()
        try:
            y = int(g.get("y") or default_year)
            y = y + 2000 if y < 100 else y
            if g.get("mon"):
                mon = MONTHS.get(g["mon"][:3].lower())
                if not mon or (k == 4 and g["mon"][:3].lower() not in MONTHS):
                    continue
            else:
                mon = int(g["m"])
            return date(y, mon, int(g["d"])).isoformat()
        except (ValueError, TypeError):
            continue
    return ""


# ----------------------------------------------------------------------------- build
SCHEMA = """
CREATE TABLE docs(id TEXT PRIMARY KEY, relpath TEXT, year INT, ext TEXT, kind TEXT, title TEXT, header TEXT, exp_time TEXT, date_first TEXT, date_last TEXT,
                  size_mb REAL, n_lines INT, n_tables INT, n_images INT, n_headings INT);
CREATE TABLE lines(doc_id TEXT, ln INT, h1 TEXT, h2 TEXT, h3 TEXT, date TEXT, style TEXT, text TEXT, PRIMARY KEY(doc_id, ln));
CREATE VIRTUAL TABLE fts USING fts5(text, headings, doc_id UNINDEXED, ln UNINDEXED, tokenize="unicode61 remove_diacritics 2 tokenchars '_'");
CREATE TABLE tags(doc_id TEXT, ln INT, tag TEXT);
CREATE TABLE params(doc_id TEXT, ln INT, name TEXT, value REAL, aux TEXT, raw TEXT);
CREATE INDEX tags_tag ON tags(tag, doc_id); CREATE INDEX params_name ON params(name); CREATE INDEX lines_doc ON lines(doc_id);
"""


def out_dir(bl):
    """Index location: the logs_index folder of the knowledge tree (blade/paths.py); $BLADE_LOGINDEX_DIR overrides it (used by the tests)."""
    return paths.knowledge_dir("logs_index", bl)


def doc_id(rel):
    p = Path(rel)
    suffix = "" if p.suffix.lower() == ".docx" else p.suffix.lower()          # a .xlsx and .ods may share a stem
    return f"{p.parts[0][:4]}-{p.stem}{suffix}".replace(" ", "_")


def build(src, bl):
    src = Path(src).expanduser().resolve()
    if not src.is_dir():
        raise SystemExit(f"log source not found: {src} (set --src)")
    out = out_dir(bl)
    (out / "text").mkdir(parents=True, exist_ok=True)
    db = out / "logs.sqlite"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    files = sorted(p for p in src.rglob("*") if p.suffix.lower() in (".docx", ".xlsx", ".ods") and not p.name.startswith(("~$", ".")))
    bad = []
    for f in files:
        rel = str(f.relative_to(src))
        did = doc_id(rel)
        year = int(re.match(r"(\d{4})", Path(rel).parts[0]).group(1)) if re.match(r"\d{4}", Path(rel).parts[0]) else 0
        try:
            raw = logextract.extract(f)
        except Exception as e:                                   # a corrupt file must not stop the index
            bad.append((rel, repr(e)))
            continue
        h1 = h2 = h3 = ""
        cur_date = ""
        title, exp_time, hdr, header_label = "", "", {}, None
        n_tab = n_img = n_head = 0
        text_lines = []
        rows_l, rows_f, rows_t, rows_p = [], [], [], []
        for ln, (style, text) in enumerate(raw, 1):
            t = text.rstrip()
            text_lines.append(t)
            sl = style.lower()
            if sl.startswith("title") and not title and t.strip():
                title = t.strip()
            if sl.startswith("heading") or sl.startswith("sheet"):
                n_head += 1
                lvl = 1 if sl in ("heading1",) or sl.startswith("sheet") else 2 if sl == "heading2" else 3
                if sl.startswith("sheet"):
                    h1, h2, h3 = t.strip("[]"), "", ""
                elif lvl == 1:
                    h1, h2, h3 = t.strip(), "", ""
                elif lvl == 2:
                    h2, h3 = t.strip(), ""
                else:
                    h3 = t.strip()
                d = parse_date(t, year)
                if d and (lvl == 1 or not cur_date):
                    cur_date = d
            if sl == "table":
                n_tab += 1
            n_img += t.count("[IMG ")
            for lab in LABELS:                                     # header block: 'X-ray energy: 71.676 keV' (+ following lines)
                if t.strip().lower().startswith(lab.lower()) and ln < 40:
                    header_label = lab
                    v = t.split(":", 1)[1].strip() if ":" in t else ""
                    hdr[lab] = v
                    break
            else:
                if header_label and ln < 40 and not sl.startswith("heading") and t.strip():
                    hdr[header_label] = (hdr.get(header_label, "") + " " + t.strip()).strip()
                elif sl.startswith("heading"):
                    header_label = None
            if "Experiment time" in hdr and not exp_time:
                exp_time = hdr["Experiment time"]
            ldate = parse_date(t, year) if re.search(r"\b20\d\d\b|\d/\d", t) and len(t) < 160 else ""
            rows_l.append((did, ln, h1, h2, h3, cur_date or ldate, style, t))
            if t.strip():
                rows_f.append((t, f"{h1} {h2} {h3}".strip(), did, ln))
                for tag, rx in TOPIC_RE.items():
                    if rx.search(t):
                        rows_t.append((did, ln, tag))
                rows_p += list(extract_params(did, ln, t))
        dates = [r[5] for r in rows_l if r[5]]
        kind = classify(rel)
        con.execute("INSERT INTO docs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (did, rel, year, f.suffix.lower()[1:], kind, title or Path(rel).stem, json.dumps(hdr), exp_time, min(dates) if dates else "", max(dates) if dates else "",
                     round(f.stat().st_size / 1e6, 2), len(raw), n_tab, n_img, n_head))
        con.executemany("INSERT INTO lines VALUES(?,?,?,?,?,?,?,?)", rows_l)
        con.executemany("INSERT INTO fts(text,headings,doc_id,ln) VALUES(?,?,?,?)", rows_f)
        con.executemany("INSERT INTO tags VALUES(?,?,?)", rows_t)
        con.executemany("INSERT INTO params VALUES(?,?,?,?,?,?)", rows_p)
        (out / "text" / f"{did}.txt").write_text("\n".join(f"{i:5d}  {x}" for i, x in enumerate(text_lines, 1)) + "\n")
    con.commit()
    meta = {"source": str(src), "n_docs": con.execute("select count(*) from docs").fetchone()[0], "bad": bad}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    con.close()
    write_catalog(bl)
    return meta


def extract_params(did, ln, t):
    seen = set()
    for name, rx, grp in PARAM_PATTERNS:
        for m in rx.finditer(t):
            try:
                if name == "preamp_gain":
                    val, aux = float(m.group(1)), m.group(2).replace("µ", "u")
                elif name == "exposure_s":
                    val, aux = float(m.group(1)) * (1e-3 if m.group(2).lower() == "ms" else 1.0), m.group(2)
                elif name == "edge":
                    val, aux = 0.0, m.group(1).capitalize()
                elif name == "ic_rate_kHz":
                    val, aux = float(m.group(2)), m.group(1)
                else:
                    val, aux = float(m.group(grp)), ""
            except ValueError:
                continue
            key = (name, val, aux)
            if key not in seen:
                seen.add(key)
                yield (did, ln, name, val, aux, t.strip()[:200])
    for m in SLIT_RE.finditer(t):
        nm = m.group("name").strip()
        if re.search(r"slit|wb|kohzu|kuz|bcs", nm, re.I):
            yield (did, ln, "slit_h_mm", float(m.group(2)), nm, t.strip()[:200])
            yield (did, ln, "slit_v_mm", float(m.group(3)), nm, t.strip()[:200])
    m = WBPOS_RE.search(t)
    if m:
        yield (did, ln, "wb_h_center_mm", float(m.group(3)), "", t.strip()[:200])
        yield (did, ln, "wb_v_center_mm", float(m.group(4)), "", t.strip()[:200])


# ----------------------------------------------------------------------------- queries
def connect(bl):
    db = out_dir(bl) / "logs.sqlite"
    if not db.exists():
        raise SystemExit(f"no index yet: run `logindex.py build` first ({db})")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def write_catalog(bl):
    con = connect(bl)
    rows = con.execute("select * from docs order by year, coalesce(nullif(date_first,''),'9999'), id").fetchall()
    tagc = defaultdict(Counter)
    for r in con.execute("select doc_id, tag, count(*) n from tags group by doc_id, tag"):
        tagc[r["doc_id"]][r["tag"]] = r["n"]
    o = ["# Log catalog (generated by logindex.py; local only)", "",
         f"{len(rows)} documents. kind: startup = beamline setup/commissioning/alignment logs, user = user-experiment logs, tables = spreadsheets.", "",
         "| doc id | kind | dates | X-ray energy (header) | lines | tbl | img | top topics |", "|---|---|---|---|--:|--:|--:|---|"]
    for r in rows:
        h = json.loads(r["header"] or "{}")
        top = ", ".join(f"{k} {v}" for k, v in tagc[r["id"]].most_common(4))
        o.append(f"| {r['id']} | {r['kind']} | {r['date_first']}..{r['date_last']} | {(h.get('X-ray energy') or '')[:40]} | {r['n_lines']} | {r['n_tables']} | {r['n_images']} | {top} |")
    (out_dir(bl) / "catalog.md").write_text("\n".join(o) + "\n")


def where(args, alias=""):
    c, p = [], []
    a = alias + "." if alias else ""
    if getattr(args, "kind", None):
        c.append(f"{a}doc_id IN (SELECT id FROM docs WHERE kind=?)"); p.append(args.kind)
    if getattr(args, "year", None):
        c.append(f"{a}doc_id IN (SELECT id FROM docs WHERE year=?)"); p.append(args.year)
    if getattr(args, "doc", None) and not isinstance(args.doc, list):
        c.append(f"{a}doc_id LIKE ?"); p.append(f"%{args.doc}%")
    return c, p


def cmd_search(args):
    con = connect(args.bl)
    c, p = where(args, "f")
    if args.topic:
        c.append("(f.doc_id || ':' || f.ln) IN (SELECT doc_id || ':' || ln FROM tags WHERE tag=?)"); p.append(args.topic)
    sql = ("SELECT f.doc_id, f.ln, l.h1, l.h2, l.date, snippet(fts, 0, '[', ']', ' ... ', 18) AS s FROM fts f JOIN lines l ON l.doc_id=f.doc_id AND l.ln=f.ln "
           "WHERE fts MATCH ?" + "".join(" AND " + x for x in c) + " ORDER BY bm25(fts) LIMIT ?")
    q = args.query if re.search(r"\b(AND|OR|NOT|NEAR)\b|\"", args.query) else " ".join(f'"{w}"' for w in args.query.split())
    rows = con.execute(sql, [q] + p + [args.n]).fetchall()
    for r in rows:
        print(f"{r['doc_id']}:L{r['ln']}  [{r['date'] or '-'}] {r['h1'][:25]} > {r['h2'][:30]}\n      {r['s']}")
    print(f"-- {len(rows)} hits (max {args.n}); `show <doc> --lines a-b` for context")


def cmd_show(args):
    con = connect(args.bl)
    docs = [r["id"] for r in con.execute("select id from docs where id like ? order by id", (f"%{args.doc}%",))]
    if not docs:
        raise SystemExit("no such document")
    if len(docs) > 1 and args.doc not in docs:
        raise SystemExit("ambiguous: " + ", ".join(docs))
    did = args.doc if args.doc in docs else docs[0]
    lo, hi = 1, 10 ** 9
    if args.lines:
        a, _, b = args.lines.partition("-")
        lo, hi = int(a), int(b or a)
    if args.section:
        r = con.execute("select min(ln) lo, max(ln) hi from lines where doc_id=? and (h1 like ? or h2 like ? or h3 like ?)", (did, *[f"%{args.section}%"] * 3)).fetchone()
        if r["lo"] is None:
            raise SystemExit("no such section; try `outline`")
        lo, hi = r["lo"], r["hi"]
    if args.ctx:
        lo, hi = max(1, lo - 4), hi + 4
    for r in con.execute("select ln, style, text from lines where doc_id=? and ln between ? and ? order by ln limit ?", (did, lo, hi, args.max)):
        if r["text"].strip() or args.all:
            print(f"{r['ln']:5d} {'#' if r['style'].lower().startswith(('heading', 'title')) else ' '} {r['text']}")


def cmd_outline(args):
    con = connect(args.bl)
    did = con.execute("select id from docs where id like ? order by id", (f"%{args.doc}%",)).fetchone()
    if not did:
        raise SystemExit("no such document")
    did = did["id"]
    d = con.execute("select * from docs where id=?", (did,)).fetchone()
    print(f"{did}  [{d['kind']}] {d['date_first']}..{d['date_last']}  lines={d['n_lines']}  header={d['header'][:300]}")
    for r in con.execute("select ln, style, text, date from lines where doc_id=? and (lower(style) like 'heading%' or lower(style) like 'title%' or style like 'sheet:%' and text like '[SHEET%') order by ln", (did,)):
        lvl = {"heading1": 0, "heading2": 1, "heading3": 2}.get(r["style"].lower(), 0)
        print(f"{r['ln']:5d} {'  ' * lvl}{r['text'][:110]}  {r['date'] if lvl == 0 else ''}")


def cmd_catalog(args):
    write_catalog(args.bl)
    print((out_dir(args.bl) / "catalog.md").read_text())


def cmd_topic(args):
    con = connect(args.bl)
    c, p = where(args, "t")
    rows = con.execute("SELECT l.doc_id, l.h1, l.h2, min(l.ln) lo, max(l.ln) hi, count(*) n FROM tags t JOIN lines l ON l.doc_id=t.doc_id AND l.ln=t.ln WHERE t.tag=?" +
                       "".join(" AND " + x for x in c) + " GROUP BY l.doc_id, l.h1, l.h2 ORDER BY n DESC LIMIT ?", [args.topic] + p + [args.n]).fetchall()
    for r in rows:
        print(f"{r['n']:4d}  {r['doc_id']}:L{r['lo']}-{r['hi']}  {r['h1'][:30]} > {r['h2'][:40]}")
    tot = con.execute("select count(*) from tags where tag=?", (args.topic,)).fetchone()[0]
    print(f"-- topic '{args.topic}': {tot} tagged lines in total. topics: {', '.join(TOPICS)}")


def cmd_params(args):
    con = connect(args.bl)
    c, p = where(args, "pr")
    rows = con.execute("SELECT pr.doc_id, pr.ln, pr.value, pr.aux, pr.raw, d.date_first FROM params pr JOIN docs d ON d.id=pr.doc_id WHERE pr.name=?" +
                       "".join(" AND " + x for x in c) + " ORDER BY d.date_first, pr.doc_id, pr.ln", [args.name] + p).fetchall()
    for r in rows[: args.n]:
        print(f"{r['doc_id']}:L{r['ln']}  {r['value']:g} {r['aux']}  | {r['raw'][:90]}")
    vals = [r["value"] for r in rows]
    if vals:
        cnt = Counter(round(v, 3) for v in vals).most_common(5)
        print(f"-- {len(vals)} values in {len(set(r['doc_id'] for r in rows))} docs; min {min(vals):g} median {statistics.median(vals):g} max {max(vals):g}; most common: " +
              ", ".join(f"{v:g} (x{n})" for v, n in cnt))
    names = [r[0] for r in con.execute("select distinct name from params order by name")]
    print("-- parameter names: " + ", ".join(names))


def cmd_images(args):
    con = connect(args.bl)
    d = con.execute("select id, relpath from docs where id like ? order by id", (f"%{args.doc}%",)).fetchone()
    if not d:
        raise SystemExit("no such document")
    meta = json.loads((out_dir(args.bl) / "meta.json").read_text())
    path = Path(meta["source"]) / d["relpath"]
    names = args.names
    if not names:
        names = []
        for r in con.execute("select ln, text from lines where doc_id=? and text like '%[IMG %' order by ln", (d["id"],)):
            for m in re.finditer(r"\[IMG ([^\]]+)\]", r["text"]):
                names.append((m.group(1), r["ln"]))
        if not args.extract:
            for n, ln in names:
                print(f"L{ln}: {n}")
            print(f"-- {len(names)} images; add --extract (optionally --names ...) to write them to --out")
            return
        names = [n for n, _ in names]
    outd = Path(args.out or out_dir(args.bl) / "images" / d["id"])
    outd.mkdir(parents=True, exist_ok=True)
    for n in names:
        (outd / n).write_bytes(logextract.image_bytes(path, n))
    print(f"wrote {len(names)} images to {outd}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bl", default=DEFAULT_BL)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--src", default=os.environ.get("BLADE_EXPLOGS") or str(DEFAULT_SRC))
    sub.add_parser("catalog")
    for name in ("search", "topic", "params", "show", "outline", "images"):
        s = sub.add_parser(name)
        if name == "search":
            s.add_argument("query"); s.add_argument("--topic", choices=sorted(TOPICS))
        if name == "topic":
            s.add_argument("topic", choices=sorted(TOPICS))
        if name == "params":
            s.add_argument("name")
        if name in ("show", "outline", "images"):
            s.add_argument("doc")
        if name == "show":
            s.add_argument("--lines"); s.add_argument("--section"); s.add_argument("--ctx", action="store_true"); s.add_argument("--all", action="store_true"); s.add_argument("--max", type=int, default=400)
        if name == "images":
            s.add_argument("--names", nargs="*"); s.add_argument("--out"); s.add_argument("--extract", action="store_true")
        if name in ("search", "topic", "params"):
            s.add_argument("--kind", choices=["startup", "user", "tables"]); s.add_argument("--year", type=int); s.add_argument("-n", type=int, default=30)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        m = build(a.src, a.bl)
        print(f"indexed {m['n_docs']} documents into {out_dir(a.bl)}; unreadable: {len(m['bad'])}")
        for rel, e in m["bad"]:
            print("  BAD", rel, e)
        return
    {"catalog": cmd_catalog, "search": cmd_search, "topic": cmd_topic, "params": cmd_params, "show": cmd_show, "outline": cmd_outline, "images": cmd_images}[a.cmd](a)


if __name__ == "__main__":
    main()
