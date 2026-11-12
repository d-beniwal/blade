#!/usr/bin/env python3
"""Aggregate statistics from the experiment-log index (stdlib only): which energies/edges, detectors, slits, gaps and flux levels recur across beamtimes.

    python beamline_twins/tools/logstats.py            # print markdown
    python beamline_twins/tools/logstats.py --write    # write beamline_twins/<bl>/physics/07_typical_parameters.md

Reads logs_index/logs.sqlite (build it with logindex.py). The output contains ONLY aggregates (counts, ranges, common values): no names, samples or
document ids of user logs, so it is safe to commit. Values are regex-extracted from free text: use `logindex.py params <name>` to see the source lines.
"""
import argparse
import json
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from logindex import connect, TWINS  # noqa: E402

EDGES = {"Re": 71.676, "Au": 80.725, "Yb": 61.332, "Tb": 51.996, "Ho": 55.618, "Ta": 67.416, "Pr": 41.991, "Bi": 90.526, "Hf": 65.351, "Ir": 76.111,
         "Sm": 46.834, "Pt": 78.395, "W": 69.525, "Pb": 88.005, "Er": 57.486, "Tm": 59.390, "Os": 73.871, "Gd": 50.239, "Dy": 53.789, "Lu": 63.314}
DETECTORS = {"GE": r"\bGE\d?\b|\bGE 41|hydra", "Hydra (4-panel GE)": r"hydra", "Pixirad": r"pixirad", "Pilatus": r"pilatus", "Varex": r"varex", "Eiger": r"eiger",
             "Retiga (NF)": r"retiga", "PG1 tomo": r"\bPG1\b|pg1", "GH1 tomo": r"\bGH1\b|gh1", "PG5 tomo": r"\bPG5\b|pg5|SP5", "tomo (any)": r"tomo|radiograph",
             "SAXS/WAXS": r"saxs|waxs", "Spectrum Logic": r"spectrum ?logic|splogic", "BrillianSe": r"brillianse"}


def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "-"


def nearest_edge(e):
    k = min(EDGES, key=lambda x: abs(EDGES[x] - e))
    return k if abs(EDGES[k] - e) < 0.35 else None


def build(con):
    docs = con.execute("select * from docs").fetchall()
    yr = Counter((d["year"], d["kind"]) for d in docs)
    o = ["# Typical parameters across the 1-ID experiment logs (generated)", "",
         f"Generated {date.today().isoformat()} by `beamline_twins/tools/logstats.py` from the local log index ({len(docs)} documents, "
         f"{min(d['year'] for d in docs)}-{max(d['year'] for d in docs)}). Aggregates only; values are regex-extracted from free text, so use "
         "`logindex.py params <name>` to inspect sources. Header energies come from each beamtime's 'X-ray energy' field (62 of 86 user logs fill it in).", "",
         "## Corpus", "", "| year | startup/setup logs | user logs | spreadsheets |", "|--:|--:|--:|--:|"]
    for y in sorted({d["year"] for d in docs}):
        o.append(f"| {y} | {yr[(y, 'startup')]} | {yr[(y, 'user')]} | {yr[(y, 'tables')]} |")

    # ---- energies from headers
    hdr = [(d["year"], json.loads(d["header"] or "{}")) for d in docs if d["kind"] in ("user", "startup")]
    edge_ct, edge_years, loose = Counter(), defaultdict(set), []
    for y, h in hdr:
        t = (h.get("X-ray energy") or "").strip()
        if not t:
            continue
        nums = [float(x) for x in re.findall(r"(?<![\d.])(\d{2,3}(?:\.\d+)?)\s*(?:k?eV)?", t) if 30 <= float(x) <= 110]
        tok = re.findall(r"\b([A-Z][a-z]?)\b[ -]*(?:K[- ]?)?edge", t)
        name = tok[0] if tok and tok[0] in EDGES else (nearest_edge(nums[0]) if nums else None)
        if name:
            edge_ct[name] += 1
            edge_years[name].add(y)
        elif nums:
            loose.append(nums[0])
    o += ["", "## Energies: the beamline runs ON absorption edges", "",
          "Each beamtime's monochromator energy is calibrated on a foil K-edge (the `Emon`/`E_scan` procedure). Count = beamtimes whose header names that edge (or an energy within 0.35 keV of it); "
          "tabulated K-edge energy from xraydb.", "", "| edge | K-edge (keV) | beamtimes | years seen |", "|---|--:|--:|---|"]
    for k, n in edge_ct.most_common():
        o.append(f"| {k} | {EDGES[k]} | {n} | {', '.join(str(y) for y in sorted(edge_years[k]))} |")
    if loose:
        o.append(f"\nOther stated energies (no edge): {', '.join(f'{x:g}' for x in sorted(set(loose)))} keV (HRM-based ~52 keV, ~100 keV and similar).")

    # ---- detectors per year
    o += ["", "## Detectors and cameras mentioned in beamtime headers", "", "| detector / camera | " + " | ".join(str(y) for y in sorted({d['year'] for d in docs if d['kind'] == 'user'})) + " | total |",
          "|---|" + "--:|" * (len({d['year'] for d in docs if d['kind'] == 'user'}) + 1)]
    uyears = sorted({d["year"] for d in docs if d["kind"] == "user"})
    for nm, rx in DETECTORS.items():
        cnt, tot = [], 0
        for y in uyears:
            n = sum(1 for yy, h in hdr if yy == y and re.search(rx, (h.get("X-ray detectors") or "") + " " + (h.get("X-ray sample setup") or ""), re.I))
            cnt.append(n); tot += n
        o.append(f"| {nm} | " + " | ".join(str(c) for c in cnt) + f" | {tot} |")
    o.append("")
    px = Counter()
    for _, h in hdr:
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:um|µm|μm)\s*/\s*(?:px|pixel)|(\d+(?:\.\d+)?)\s*(?:um|µm|μm)\s*(?:pixel|px)", (h.get("X-ray detectors") or ""), re.I):
            px[float(m.group(1) or m.group(2))] += 1
    o.append("Pixel sizes stated in headers (um/px: count): " + ", ".join(f"{k:g}: {v}" for k, v in px.most_common(8)))
    dist = [r["value"] for r in con.execute("select value from params where name='distance_mm' and value between 100 and 10000")]
    if dist:
        o.append(f"\nDetector/sample distances stated in the text, 100-10000 mm: {len(dist)} values, median {statistics.median(dist):g}; most common " +
                 ", ".join(f"{v:g} (x{n})" for v, n in Counter(dist).most_common(8)))

    # ---- WB slits
    wb = con.execute("select p1.doc_id, p1.ln, p1.value h, p2.value v from params p1 join params p2 on p1.doc_id=p2.doc_id and p1.ln=p2.ln and p2.name='slit_v_mm' and p2.aux=p1.aux "
                     "where p1.name='slit_h_mm' and upper(p1.aux) like 'WB%'").fetchall()
    sz = Counter((r["h"], r["v"]) for r in wb)
    o += ["", "## White-beam (WB) slit sizes written in the logs (H x V mm)", "", f"{len(wb)} occurrences; most common: " + ", ".join(f"{h:g} x {v:g} (x{n})" for (h, v), n in sz.most_common(10)), ""]

    # ---- undulator gap + harmonic on the same line
    gh = con.execute("select g.value gap, h.value n, count(*) c from params g join params h on g.doc_id=h.doc_id and g.ln=h.ln and h.name='harmonic_n' where g.name='gap_mm' and g.value<20 "
                     "group by g.value, h.value order by c desc").fetchall()
    o += ["## Undulator gap / harmonic pairs recorded together (mm, n)", "", "| gap (mm) | harmonic n | times |", "|--:|--:|--:|"]
    o += [f"| {r['gap']:g} | {int(r['n'])} | {r['c']} |" for r in gh[:12]]
    gaps = [r["value"] for r in con.execute("select value from params where name='gap_mm' and value<20")]
    if gaps:
        o.append(f"\nAll gap values <20 mm ({len(gaps)}): min {min(gaps):g}, median {statistics.median(gaps):g}, max {max(gaps):g} mm.")

    # ---- calibration numbers
    lim = {"ring_current_mA": "and value between 20 and 250", "ic_rate_kHz": "and value > 20", "exposure_s": "and value between 0.005 and 100"}

    def rng(name):
        return [r["value"] for r in con.execute(f"select value from params where name=? {lim.get(name, '')}", (name,))]
    o += ["", "## Calibration / flux numbers", ""]
    for name, label, unit in (("mu_t", "mu*t at the calibration edge ('ut')", ""), ("th1_offset_deg", "HEM Th1 offset", "deg"), ("ring_current_mA", "ring current quoted", "mA"),
                              ("ic_rate_kHz", "ion-chamber rates quoted", "kHz"), ("exposure_s", "exposure times quoted", "s")):
        v = rng(name)
        if not v:
            continue
        cm = ", ".join(f"{k:g} (x{n})" for k, n in Counter(round(x, 3) for x in v).most_common(6))
        o.append(f"- **{label}**: {len(v)} values; min {min(v):g}, median {statistics.median(v):g}, max {max(v):g} {unit}; most common {cm}")
    th = con.execute("select d.date_first d, p.value v from params p join docs d on d.id=p.doc_id where p.name='th1_offset_deg' and d.date_first!='' order by d.date_first").fetchall()
    if th:
        o.append("\nTh1 offset history (deg, by document date): " + "; ".join(f"{r['d'][:7]}: {r['v']:g}" for r in th))
    return "\n".join(o) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bl", default="1-ID")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    md = build(connect(a.bl))
    if a.write:
        out = TWINS / a.bl / "physics"
        out.mkdir(exist_ok=True)
        (out / "07_typical_parameters.md").write_text(md)
        print("wrote", out / "07_typical_parameters.md")
    else:
        print(md)


if __name__ == "__main__":
    main()
