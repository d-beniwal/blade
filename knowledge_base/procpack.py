#!/usr/bin/env python3
"""Build per-procedure SOURCE PACKS from the log text in kb.sqlite: the sections of the logs that actually describe how a calibration /
alignment is done, ranked by keyword + heading match, with line citations (doc:L<ln>) and the KB's labelled images attached.

    procpack.py list                        # the procedure catalogue (id, name)
    procpack.py build [ID ...]              # write <KB_ROOT>/procedures/packs/<ID>.md (+ .json index) for all / the named procedures
    procpack.py preview ID [-n 15]          # top-ranked sections (doc, heading, score) without writing

A pack is INPUT for the extraction agents (kb procedures are written from packs, not from raw logs); the ranking is deliberately generous
(better to include a marginal section than to miss the one clean write-up). Regexes are case-insensitive.
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb  # noqa: E402

# id: (name, core regex [counts 1/hit], aux regex [0.25/hit], heading regex [+6 if any of h1/h2/h3 match])
PROCEDURES = {
    "energy_calibration": (
        "Energy calibration with a foil absorption edge (E_scan / Emon / mu_t)",
        r"E_?scan|Emon|\bmu_?t\b|calibrat\w* (the )?energy|energy calib|absorption edge|\bfoil\b|edge (scan|fit)|CalcRecord|userTran3|\bpos\b.*\bwid\b",
        r"\bkeV\b|\bHEM\b|\bTh1\b|\bTh2\b|\berf\b|\bdif\b|transform",
        r"energy|calibrat|\bfoil|edge|E_?scan|mu_?t"),
    "undulator_gap_tuning": (
        "Undulator gap / harmonic tuning for maximum flux (undscangap, setundgap)",
        r"undscangap|setundgap|undulator|\bgap\b|harmonic|taper|brightness mode|\bSCU\b|\bPMU\b",
        r"\bIC\d?\b|flux|peak|kHz|\bkeV\b",
        r"undulator|\bgap\b|harmonic|brightness|flux|taper"),
    "mono_tuning": (
        "Monochromator (HEM) tuning: Th1/Th2/Chi2, rocking, flux maximisation",
        r"\bTh2\b|\bTh1\b|\bChi2\b|\bHEM\b|mono(chromator)?|rocking|\bbragg\b|second crystal|Z2",
        r"\bIC\d?\b|flux|peak|max|tweak|kHz",
        r"mono|\bTh2\b|\bHEM\b|energy|flux"),
    "wb_slits_and_steering": (
        "White-beam slits, hotspot and orbit/beam steering request",
        r"\bWB\b|white[- ]beam|hot ?spot|steer\w*|orbit|\bBPM\b|\bXBPM\b|\bW_Beam\b|BLSteering",
        r"slit|urad|center|centre|hsize|vsize|position",
        r"\bWB\b|white|steer|hot ?spot|orbit|beam position"),
    "tomo_camera_optical_axis": (
        "Tomo-camera optical-axis alignment (hotspot, camera position, pg1/pg5/gh1/retiga)",
        r"hot ?spot|optical axis|\bpg[15]\b|\bgh1\b|retiga|tomo ?(cam|camera|detector|X|Y|Z)\b|tomo[CE]|beam (on|in) (the )?(tomo|camera)|pixel size|scintillator",
        r"\bpix(els?)?\b|slit|zero|re-?zero|position",
        r"optical|tomo|align|hot ?spot|camera|pg[15]|gh1"),
    "kohzu_slits_alignment": (
        "Kohzu/hutch slit alignment and centring (B/C/E upstream-downstream)",
        r"kohzu|\bslits?\b.*\b(align|center|centre|zero|scan|close|open)|\b(align|center|centre|zero|scan|close|open)\w*\b.*\bslits?\b|\bhcenter|\bvcenter|\bhsize|\bvsize|zero_slits",
        r"\bus\b|\bds\b|upstream|downstream|\bpix(els?)?\b|0\.1|tomo",
        r"slit"),
    "fast_shutter_alignment": (
        "Fast-shutter (B/E) alignment and PSS shutter checks",
        r"fast[- ]shutter|\bFS\b|\bPSS\b|\bfes\b|shutter",
        r"\bIC\d?\b|blade|edge|close|open|counts",
        r"shutter"),
    "ic_preamp_flux": (
        "Ion-chamber / SR570 preamp setup, flux and attenuation checks",
        r"\bIC\d?\b|ion chamber|preamp|SR570|nA/V|\bkHz\b|\bflux\b|dark (current|count)|sensitivity|attenuat\w+",
        r"\bsaturat|dark|gain|foil|photons?|offset",
        r"\bIC\b|ion chamber|preamp|flux|attenuat"),
    "rotation_axis_alignment": (
        "Rotation-axis alignment with the W pin (aeroX, samX/samZ, zero angle, wedge, tilt)",
        r"rotation axis|axis of rotation|\bpin\b|W[- ]pin|aero ?[XYZ]|\baero\b|\bwedge\b|samX|samZ|rotX|\bzero angle|ry error|axis tilt|\bTx\b",
        r"\bdeg\b|\bpix(els?)?\b|\bum\b|180|360|centre|center",
        r"rotation|axis|\bpin\b|wedge|aero|stage"),
    "lens_alignment_focusing": (
        "Lens (CRL stack) alignment and focusing (th/phi/chi/y, narrowest line)",
        r"\blens(es)?\b|\bCRL\b|focus\w*|focal|\bstack\b|lens alignment|narrowest|\bphi\b|\bchi\b",
        r"\bdeg\b|\bpix(els?)?\b|\bum\b|line|tomo|scan",
        r"lens|focus|crl"),
    "nf_detector_and_beamstop": (
        "Near-field detector alignment, beamstop and sample-to-detector distance",
        r"near[- ]?field|\bNF\b|beam ?stop|\bbs\b|nf det|detector distance|sample[- ]to[- ]detector|\bmid\b macro|sample height",
        r"\bum\b|touch|back off|step|image",
        r"near|\bNF\b|beamstop|detector|distance"),
    "ff_detector_calibration": (
        "Far-field detector geometry calibration (CeO2 / LaB6, MIDAS/GSAS-II)",
        r"CeO2|LaB6|ceria|calibrant|\bMIDAS\b|GSAS|far[- ]field|\bFF\b.*\b(det|calib)|detector (geometry|calibration|tilt)|Ge[1-5]\b|Pilatus|Eiger|Dexela|Lambda|powder (ring|standard)",
        r"\bring\b|distance|\btilt\b|\bmm\b|wavelength|\bkeV\b",
        r"calib|CeO2|LaB6|detector|far"),
    "tomo_setup_and_scan": (
        "Tomography setup: centre of rotation, exposure/frames, tomo scan parameters",
        r"\btomo(graphy)?\b|projections?|flat[- ]?field|dark[- ]?field|\bflats?\b|\bdarks?\b|centre of rotation|center of rotation|\bCOR\b|rotation speed|continuous (acq|scan)|tomocupy|switch_to_tomo",
        r"exposure|\bfps\b|frames?|\bdeg\b|\bsec\b|\bs\b",
        r"tomo"),
    "beam_size_and_mode_changes": (
        "Changing beam size / brightness mode / stability and drift checks",
        r"beam size|brightness mode|beam (motion|stability|drift)|top-?up|beam dump|orbit|drift|repeatab\w+|beam profile",
        r"slit|\bmm\b|urad|\bum\b|stable|stability",
        r"brightness|beam (size|profile|motion)|stab|drift|repeat"),
}

SEC_CHAR_CAP = 6000                  # one section's text cap in a pack
PACK_CHAR_CAP = 150_000              # whole pack cap (~40k tokens)
PER_DOC_MAX = 5                      # sections per document (startup logs repeat; avoid one doc dominating)
MIN_SCORE = 4.0


def sections(con):
    """{(doc, h1, h2, h3): [row, ...]} in line order."""
    secs = defaultdict(list)
    for r in con.execute("SELECT doc_id, ln, h1, h2, h3, date, text FROM lines ORDER BY doc_id, ln"):
        secs[(r["doc_id"], r["h1"] or "", r["h2"] or "", r["h3"] or "")].append(r)
    return secs


def score_section(rows, key, core, aux, head):
    hh = " ".join(key[1:])
    s = 6.0 if head.search(hh) else 0.0
    for r in rows:
        t = r["text"] or ""
        s += len(core.findall(t)) + 0.25 * len(aux.findall(t))
    chars = sum(len(r["text"] or "") for r in rows)
    return s, chars


def rank(con, pid, secs=None):
    name, core, aux, head = PROCEDURES[pid]
    core, aux, head = (re.compile(x, re.I) for x in (core, aux, head))
    secs = secs or sections(con)
    docs_kind = {r["doc_id"]: r["kind"] for r in con.execute("SELECT doc_id, kind FROM docs")}
    out = []
    for key, rows in secs.items():
        if docs_kind.get(key[0]) == "tables":
            continue
        s, chars = score_section(rows, key, core, aux, head)
        if s < MIN_SCORE or chars < 80:
            continue
        # prefer dense write-ups: score per 1k chars, with a floor on absolute score; startup logs get a bonus (they describe procedure)
        dens = s / max(chars / 1000, 0.5)
        out.append((s * 0.6 + dens * 2 + (3 if docs_kind.get(key[0]) == "startup" else 0), s, chars, key, rows))
    out.sort(key=lambda x: -x[0])
    return out


def pick(ranked):
    per_doc = defaultdict(int)
    chosen, total = [], 0
    for sc, s, chars, key, rows in ranked:
        if per_doc[key[0]] >= PER_DOC_MAX:
            continue
        c = min(chars, SEC_CHAR_CAP)
        if total + c > PACK_CHAR_CAP:
            continue
        chosen.append((sc, s, chars, key, rows))
        per_doc[key[0]] += 1
        total += c
    chosen.sort(key=lambda x: (x[3][0], x[4][0]["ln"]))                         # doc order, then position
    return chosen, total


def image_notes(con, doc, ln, name, cache):
    """'[IMG sha10 class/subject device]' for a marker, from the KB labels."""
    r = con.execute("SELECT sha256 FROM image_refs WHERE doc_id=? AND name=? AND ln=?", (doc, name, ln)).fetchone()
    if not r:
        return f"[IMG {name}]"
    sha = r["sha256"]
    if sha not in cache:
        lab = {x["key"]: x["value"] for x in con.execute("SELECT key, value FROM label_best WHERE sha256=?", (sha,))}
        bits = [lab.get("class", "?"), lab.get("subject", ""), lab.get("device", "")]
        cache[sha] = f"[IMG {sha[:10]} " + " / ".join(b for b in bits if b) + "]"
    return cache[sha]


def render(con, pid, chosen, total):
    name = PROCEDURES[pid][0]
    cache = {}
    lines = [f"# SOURCE PACK: {pid} - {name}", "",
             f"{len(chosen)} log sections, ~{total // 1000} kB. Citation format `doc:L<line>`; `[IMG <sha10> class/subject/device]` = an image in the KB "
             f"(`kb.py show <sha10>`; file under kb_1ID/images/). Text is verbatim from the logs (user names are in doc ids; do not copy personal names into outputs).", ""]
    for sc, s, chars, key, rows in chosen:
        doc, h1, h2, h3 = key
        lines.append(f"## {doc} | {h1} > {h2} > {h3}  (score {s:.0f}, {chars} chars)")
        used = 0
        for r in rows:
            t = (r["text"] or "").rstrip()
            if not t.strip():
                continue
            t = re.sub(r"\[IMG ([^\]]+)\]", lambda m: image_notes(con, doc, r["ln"], m.group(1), cache), t)
            t = re.sub(r"\[ALT [^\]]*\]", "", t)
            row = f"L{r['ln']}{' [' + r['date'] + ']' if r['date'] else ''}: {t.strip()}"
            used += len(row)
            if used > SEC_CHAR_CAP:
                lines.append("...(section truncated)")
                break
            lines.append(row)
        lines.append("")
    return "\n".join(lines)


def cmd_build(a):
    con = kb.connect()
    secs = sections(con)
    out = kb.KB_ROOT / "procedures" / "packs"
    out.mkdir(parents=True, exist_ok=True)
    for pid in (a.ids or PROCEDURES):
        ranked = rank(con, pid, secs)
        chosen, total = pick(ranked)
        (out / f"{pid}.md").write_text(render(con, pid, chosen, total))
        idx = [dict(doc=k[0], h1=k[1], h2=k[2], h3=k[3], score=round(s, 1), chars=c, first_ln=rows[0]["ln"]) for _, s, c, k, rows in chosen]
        (out / f"{pid}.json").write_text(json.dumps(idx, indent=1))
        print(f"{pid:28s} {len(chosen):3d} sections from {len({k[3][0] for k in chosen}):3d} docs, {total // 1000:4d} kB  (candidates {len(ranked)})")


def cmd_preview(a):
    con = kb.connect()
    ranked = rank(con, a.id)
    for sc, s, chars, key, rows in ranked[: a.n]:
        print(f"{sc:6.1f} s={s:5.1f} {chars:6d}c  {key[0]} | {key[1]} > {key[2]} > {key[3]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("list").set_defaults(f=lambda a: [print(f"{k:28s} {v[0]}") for k, v in PROCEDURES.items()])
    s = sp.add_parser("build"); s.add_argument("ids", nargs="*"); s.set_defaults(f=cmd_build)
    s = sp.add_parser("preview"); s.add_argument("id", choices=list(PROCEDURES)); s.add_argument("-n", type=int, default=15); s.set_defaults(f=cmd_preview)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
