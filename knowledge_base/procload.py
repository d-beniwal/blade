#!/usr/bin/env python3
"""Validate + load procedure records (JSON) into kb.sqlite, and query them.

    procload.py schema                 # print the record schema (what extraction agents must write)
    procload.py check FILE.json        # validate: required fields, step numbering, and EVERY citation resolves to a real log line
    procload.py load [FILE.json ...]   # check, then (re)load into the DB (default: all <KB_ROOT>/procedures/*.json)
    procload.py list
    procload.py show ID [--md]         # render a procedure (markdown)
    procload.py search "gap AND scan" [-n 20]     # FTS over steps/notes/numbers
    procload.py number QUANTITY        # every logged value of a quantity across procedures (LIKE match)

Citation syntax everywhere: `doc_id:L<ln>` or `doc_id:L<a>-<b>` (doc ids as in `kb.py show`, e.g. 2025-startup_jan25_explog:L97).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb  # noqa: E402

SCHEMA = """{
  "id": "energy_calibration",                      # procedure id (from procpack.py list)
  "name": "...", "goal": "one or two sentences: what is achieved and why it matters",
  "when_performed": "trigger/frequency (e.g. every energy change; start of each beamtime)",
  "scope": ["E"],                                   # hutches (A/B/C/E) and/or devices involved
  "prerequisites": [ {"text": "...", "cites": ["doc:L12"]} ],
  "tools": [ {"name": "E_scan", "kind": "spec_macro|epics_gui|pv|bluesky|script|hardware", "text": "what it does / typical args", "cites": []} ],
  "steps": [ {"n": 1, "action": "imperative sentence", "where": "hutch/device", "tool": "command or GUI used", "signal": "what is watched",
              "done_when": "stop criterion", "evidence": "log|inferred",       # log = stated in a log; inferred = your synthesis (say why in action)
              "values": [ {"quantity": "gap_scan_range", "value": "+-0.2", "unit": "mm", "context": "n=7 Re edge", "era": "2025", "cites": ["doc:L33"]} ],
              "cites": ["doc:L31", "doc:L33-36"] } ],
  "variants": [ {"label": "short", "text": "how the practice differs (by era / hutch / user group / technique)", "cites": []} ],
  "typical_numbers": [ {"quantity": "...", "value": "number or range, as logged", "unit": "...", "context": "...", "era": "2024-2026", "cites": []} ],
  "pitfalls": [ {"text": "what goes wrong / how it is noticed / the fix", "cites": []} ],
  "success_criteria": [ {"text": "...", "cites": []} ],
  "images": [ {"sha10": "abcdef0123", "step": 4, "shows": "what the image shows"} ],   # only images listed in the pack
  "open_questions": [ {"text": "what the logs do not say"} ],
  "related": ["undulator_gap_tuning"],
  "vbl_relevance": [ {"item": "peak gap vs energy", "informs": "sim.json undulator / vbl procedures.gap_scan", "how": "calibrates harmonic gap curve"} ],
  "sources": {"n_sections_read": 0, "docs": ["doc ids that contributed"], "eras": "2022-2026"}
}"""

CITE = re.compile(r"^(?P<doc>[^:]+):L(?P<a>\d+)(?:-(?P<b>\d+))?$")


def cites_of(rec):
    """every (path, cite-string) in a record"""
    out = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "cites" and isinstance(v, list):
                    out.extend((path, c) for c in v)
                else:
                    walk(v, path + [k])
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, path + [i])
    walk(rec, [])
    return out


def check(rec, con):
    errs = []
    for f in ("id", "name", "goal", "steps"):
        if not rec.get(f):
            errs.append(f"missing field {f}")
    steps = rec.get("steps") or []
    if [s.get("n") for s in steps] != list(range(1, len(steps) + 1)):
        errs.append("steps must be numbered 1..N in order")
    for s in steps:
        for f in ("action", "evidence"):
            if not s.get(f):
                errs.append(f"step {s.get('n')}: missing {f}")
        if s.get("evidence") not in ("log", "inferred"):
            errs.append(f"step {s.get('n')}: evidence must be log|inferred")
        if s.get("evidence") == "log" and not s.get("cites"):
            errs.append(f"step {s.get('n')}: evidence=log needs cites")
    maxln = {r[0]: r[1] for r in con.execute("SELECT doc_id, MAX(ln) FROM lines GROUP BY doc_id")}
    n_ok = 0
    for path, c in cites_of(rec):
        m = CITE.match(str(c).strip())
        if not m:
            errs.append(f"bad citation syntax {c!r} at {'/'.join(map(str, path))}")
        elif m["doc"] not in maxln:
            errs.append(f"unknown doc in citation {c!r}")
        elif int(m["a"]) > maxln[m["doc"]] or int(m["b"] or m["a"]) > maxln[m["doc"]]:
            errs.append(f"line out of range in citation {c!r} (doc has {maxln[m['doc']]} lines)")
        else:
            n_ok += 1
    known = {r[0] for r in con.execute("SELECT substr(sha256,1,10) FROM images")}
    for im in rec.get("images") or []:
        if im.get("sha10") not in known:
            errs.append(f"unknown image {im.get('sha10')}")
    return errs, n_ok


def expand(c):
    m = CITE.match(c.strip())
    a, b = int(m["a"]), int(m["b"] or m["a"])
    return m["doc"], a, b


def load_one(con, rec):
    pid = rec["id"]
    for t in ("procedure_steps", "procedure_numbers", "procedure_notes", "procedure_cites"):
        con.execute(f"DELETE FROM {t} WHERE proc_id=?", (pid,))
    con.execute("DELETE FROM procedures WHERE id=?", (pid,))
    con.execute("DELETE FROM proc_fts WHERE proc_id=?", (pid,))
    allc = cites_of(rec)
    con.execute("INSERT INTO procedures VALUES(?,?,?,?,?,?,?,?,?)",
                (pid, rec["name"], rec["goal"], rec.get("when_performed"), ", ".join(map(str, rec.get("scope") or [])), len(rec["steps"]), len(allc),
                 kb.now(), json.dumps(rec)))
    fts = lambda kind, text: con.execute("INSERT INTO proc_fts VALUES(?,?,?)", (pid, kind, text))
    fts("goal", f"{rec['name']}. {rec['goal']} {rec.get('when_performed') or ''}")
    for s in rec["steps"]:
        con.execute("INSERT INTO procedure_steps VALUES(?,?,?,?,?,?,?,?,?)",
                    (pid, s["n"], s["action"], s.get("where"), s.get("tool"), s.get("signal"), s.get("done_when"), s["evidence"], ", ".join(s.get("cites") or [])))
        fts("step", f"step {s['n']}: {s['action']} | {s.get('where') or ''} | {s.get('tool') or ''} | watch: {s.get('signal') or ''} | done: {s.get('done_when') or ''}")
        for v in s.get("values") or []:
            con.execute("INSERT INTO procedure_numbers VALUES(?,?,?,?,?,?,?,?)",
                        (pid, s["n"], v.get("quantity"), str(v.get("value")), v.get("unit"), v.get("context"), v.get("era"), ", ".join(v.get("cites") or [])))
            fts("number", f"{v.get('quantity')} = {v.get('value')} {v.get('unit') or ''} ({v.get('context') or ''})")
    for v in rec.get("typical_numbers") or []:
        con.execute("INSERT INTO procedure_numbers VALUES(?,?,?,?,?,?,?,?)",
                    (pid, None, v.get("quantity"), str(v.get("value")), v.get("unit"), v.get("context"), v.get("era"), ", ".join(v.get("cites") or [])))
        fts("number", f"{v.get('quantity')} = {v.get('value')} {v.get('unit') or ''} ({v.get('context') or ''})")
    for kind, key in (("prereq", "prerequisites"), ("tool", "tools"), ("variant", "variants"), ("pitfall", "pitfalls"), ("success", "success_criteria"),
                      ("image", "images"), ("open", "open_questions"), ("vbl", "vbl_relevance")):
        for it in rec.get(key) or []:
            text = it.get("text") or " | ".join(f"{k}: {v}" for k, v in it.items() if k != "cites" and v)
            if kind in ("tool", "variant") and it.get("name") or it.get("label"):
                text = f"{it.get('name') or it.get('label')}: {it.get('text') or ''}"
            con.execute("INSERT INTO procedure_notes VALUES(?,?,?,?)", (pid, kind, text, ", ".join(it.get("cites") or [])))
            fts(kind, text)
    for _, c in allc:
        doc, a, b = expand(c)
        for ln in range(a, min(b, a + 200) + 1):
            con.execute("INSERT INTO procedure_cites VALUES(?,?,?)", (pid, doc, ln))
    for r in rec.get("related") or []:
        con.execute("INSERT INTO procedure_notes VALUES(?,?,?,?)", (pid, "related", r, ""))


def files(a):
    return [Path(f) for f in a.files] if getattr(a, "files", None) else sorted((kb.KB_ROOT / "procedures").glob("*.json"))


def cmd_check(a):
    con = kb.connect()
    rec = json.loads(Path(a.file).read_text())
    errs, n_ok = check(rec, con)
    print(f"{rec.get('id')}: {len(rec.get('steps') or [])} steps, {n_ok} valid citations, {len(errs)} problems")
    for e in errs[:60]:
        print("  -", e)
    sys.exit(1 if errs else 0)


def cmd_load(a):
    con = kb.connect()
    bad = 0
    for f in files(a):
        rec = json.loads(f.read_text())
        errs, n_ok = check(rec, con)
        if errs:
            bad += 1
            print(f"SKIP {f.name}: {len(errs)} problems (first: {errs[0]})")
            continue
        load_one(con, rec)
        con.commit()
        print(f"loaded {rec['id']}: {len(rec['steps'])} steps, {n_ok} citations")
    sys.exit(1 if bad else 0)


def render_md(rec):
    L = [f"# {rec['name']}  (`{rec['id']}`)", "", f"**Goal.** {rec['goal']}", f"**When.** {rec.get('when_performed') or '-'}   **Scope.** {', '.join(map(str, rec.get('scope') or []))}", ""]
    for key, title in (("prerequisites", "Prerequisites"), ("tools", "Tools")):
        if rec.get(key):
            L += [f"## {title}"] + [f"- {x.get('name', '') + ': ' if x.get('name') else ''}{x.get('text', '')} {x.get('cites') or ''}" for x in rec[key]] + [""]
    L.append("## Steps")
    for s in rec["steps"]:
        L.append(f"{s['n']}. **{s['action']}**  _[{s['evidence']}]_  {s.get('cites') or ''}")
        for k in ("where", "tool", "signal", "done_when"):
            if s.get(k):
                L.append(f"   - {k}: {s[k]}")
        for v in s.get("values") or []:
            L.append(f"   - {v.get('quantity')} = {v.get('value')} {v.get('unit') or ''} ({v.get('context') or ''}) {v.get('cites') or ''}")
    for key, title in (("variants", "Variants"), ("typical_numbers", "Typical numbers"), ("pitfalls", "Pitfalls"), ("success_criteria", "Success criteria"),
                       ("open_questions", "Open questions"), ("vbl_relevance", "Virtual-beamline relevance")):
        if rec.get(key):
            L += ["", f"## {title}"]
            for x in rec[key]:
                L.append("- " + " | ".join(f"{k}: {v}" for k, v in x.items() if v))
    return "\n".join(L)


def cmd_show(a):
    con = kb.connect()
    r = con.execute("SELECT json FROM procedures WHERE id=?", (a.id,)).fetchone()
    if not r:
        sys.exit("not loaded")
    rec = json.loads(r[0])
    print(render_md(rec) if a.md else json.dumps(rec, indent=1))


def cmd_list(a):
    con = kb.connect()
    for r in con.execute("SELECT id, n_steps, n_cites, name FROM procedures ORDER BY id"):
        print(f"{r['id']:28s} {r['n_steps']:3d} steps {r['n_cites']:4d} cites  {r['name']}")


def cmd_search(a):
    con = kb.connect()
    for r in con.execute("SELECT proc_id, kind, text FROM proc_fts WHERE proc_fts MATCH ? LIMIT ?", (a.query, a.n)):
        print(f"{r['proc_id']:26s} {r['kind']:8s} {r['text'][:150]}")


def cmd_number(a):
    con = kb.connect()
    for r in con.execute("SELECT * FROM procedure_numbers WHERE quantity LIKE ? ORDER BY proc_id, step_n", (f"%{a.q}%",)):
        print(f"{r['proc_id']:24s} s{r['step_n'] or '-'} {r['quantity']} = {r['value']} {r['unit'] or ''}  ({r['context'] or ''}) [{r['era'] or ''}] {r['cites']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("schema").set_defaults(f=lambda a: print(SCHEMA))
    s = sp.add_parser("check"); s.add_argument("file"); s.set_defaults(f=cmd_check)
    s = sp.add_parser("load"); s.add_argument("files", nargs="*"); s.set_defaults(f=cmd_load)
    sp.add_parser("list").set_defaults(f=cmd_list)
    s = sp.add_parser("show"); s.add_argument("id"); s.add_argument("--md", action="store_true"); s.set_defaults(f=cmd_show)
    s = sp.add_parser("search"); s.add_argument("query"); s.add_argument("-n", type=int, default=20); s.set_defaults(f=cmd_search)
    s = sp.add_parser("number"); s.add_argument("q"); s.set_defaults(f=cmd_number)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
