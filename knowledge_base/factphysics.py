#!/usr/bin/env python3
"""Fit points and model comparisons from the transcribed panel facts.

    factphysics.py hem     # HEM energy-transform records: E vs Th1/Th2/Chi2/Z2 outputs and offsets (same screenshot)
    factphysics.py gap     # undulator gap vs energy pairs (same screenshot) against the fitted gap model

RELIABILITY RULE (user 2026-11-13): only tier-A readings are used (factnorm.py); an energy is only paired with a value from the SAME screenshot
(never from nearby text) for these two fits; every row keeps its provenance (doc_id:ln, sha10) and the exclusions are counted in the output.
Aggregated results (no raw per-image values beyond the fit points needed for the plot) are written to
<repo>/beamline_twins/1-ID/physics/fits/facts_*.json ; raw per-image rows stay in <KB_ROOT>/facts/analysis/.
"""
import argparse
import collections
import json
import math
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import kb  # noqa: E402

FITS = HERE.parent / "beamline_twins" / "1-ID" / "physics" / "fits"
OUT = kb.KB_ROOT / "facts" / "analysis"


def rows_by_image(db, where, params=()):
    img = collections.defaultdict(list)
    for r in db.execute(f"SELECT sha256,date,doc_id,ln,label,quantity,value,unit,tier,device FROM fact_obs WHERE {where}", params):
        img[r["sha256"]].append(r)
    return img


def _norm(label):
    return re.sub(r"\s+", "", label).lower()


def hem_points():
    db = kb.connect()
    db.row_factory = __import__("sqlite3").Row
    img = rows_by_image(db, "(label LIKE '%HEM Energy%' OR label LIKE '%Th1 output%' OR label LIKE '%Th2 output%' OR label LIKE '%Z2 output%' OR label LIKE '%Chi2 output%'"
                            " OR label LIKE '%Th1 offset%' OR label LIKE '%Th2 offset%' OR label LIKE '%Z2 offset%' OR label LIKE 'T h1 %' OR label LIKE 'T h2 %' OR label LIKE 'Z 2 %' OR label LIKE 'C hi2 %' OR label LIKE 'E nergy keV%')")
    pts, excluded = [], collections.Counter()
    for sha, rs in img.items():
        d = {}
        for r in rs:
            n = _norm(r["label"])
            key = None
            if re.search(r"energy\(?kev\)?$", n) and "gap" not in n and "reference" not in n:
                key = "E"
            else:
                m = re.search(r"(th1|th2|chi2|z2)(output|offset|semi-?corr)", n)
                if m:
                    key = m.group(1) + "_" + ("out" if m.group(2) == "output" else "off" if m.group(2) == "offset" else "semi")
            if not key:
                continue
            if r["tier"] != "A":
                excluded[r["tier"] + ":" + key] += 1
                continue
            d.setdefault(key, []).append((r["value"], r["date"], r["doc_id"], r["ln"]))
        if "E" in d and any(k in d for k in ("th1_out", "th2_out", "z2_out")):
            row = {k: v[0][0] for k, v in d.items()}
            row.update(date=d["E"][0][1], cite=f"{d['E'][0][2]}:L{d['E'][0][3]}", sha10=sha[:10])
            pts.append(row)
    return pts, excluded


def _lstsq(X, y):
    import numpy as np
    p = np.linalg.lstsq(X, y, rcond=None)[0]
    r = y - X @ p
    dof = max(len(y) - len(p), 1)
    cov = (r @ r / dof) * np.linalg.inv(X.T @ X)
    return p, r, np.sqrt(np.diag(cov))


def cmd_hem():
    import numpy as np
    from blade.physics import mono_fit
    pts, excl = hem_points()
    pts = [p for p in pts if 30 < p["E"] <= 130]
    OUT.mkdir(parents=True, exist_ok=True)
    out = {"n_records": len(pts), "excluded_readings_by_tier": dict(excl), "rule": "tier-A readings only; energy and outputs from the SAME screenshot"}
    # --- Z2 = c / tan(2 theta_B) + d   (distinct (E, Z2) pairs: repeated screenshots of the same state count once)
    z = sorted({(round(p["E"], 3), p["z2_out"]) for p in pts if "z2_out" in p})
    E = np.array([a for a, _ in z]); Z = np.array([b for _, b in z])
    th = np.radians([mono_fit.bragg_deg(e) for e in E])
    A = 1 / np.tan(2 * th)
    pc, rc, ec = _lstsq(np.c_[A, np.ones_like(A)], Z)
    p0, r0, _ = _lstsq(A[:, None], Z)
    out["z2"] = {"form": "Z2[mm] = c / tan(2 theta_B(E)) + d", "c": float(pc[0]), "c_err": float(ec[0]), "d": float(pc[1]), "d_err": float(ec[1]),
                 "n": len(z), "E_range": [float(E.min()), float(E.max())], "rms_mm": float(np.sqrt(np.mean(rc ** 2))), "max_abs_mm": float(np.abs(rc).max()),
                 "old_model": {"form": "Z2 = c / tan(2 theta_B)", "c": float(p0[0]), "rms_mm": float(np.sqrt(np.mean(r0 ** 2))), "max_abs_mm": float(np.abs(r0).max())},
                 "points": [[float(e), float(zz)] for e, zz in z]}
    # --- Th1 and Th2 are calc records: out = s * theta_B(E) + offset, where the offset is the operator-set field printed in the SAME screenshot.
    #     Regress (out - printed offset) on theta_B through the origin: the slope is the calc record's own angle scale (no per-day fitting needed).
    def scale_fit(outk, offk):
        rr = [(mono_fit.bragg_deg(p["E"]), p[outk] - p[offk], p) for p in pts if outk in p and offk in p]
        if len(rr) < 3:
            return None
        thb = np.array([r[0] for r in rr]); yy = np.array([r[1] for r in rr])
        pp, res_, ee = _lstsq(thb[:, None], yy)
        resid = yy - thb * pp[0]
        return {"model": f"{outk} = s * theta_B(E) + {offk}", "s": float(pp[0]), "s_err": float(ee[0]), "n": len(rr),
                "rms_deg": float(np.sqrt(np.mean(resid ** 2))), "max_abs_deg": float(np.abs(resid).max()),
                "E_range": [float(min(r[2]["E"] for r in rr)), float(max(r[2]["E"] for r in rr))]}
    out["th1_scale"] = scale_fit("th1_out", "th1_off")
    out["th2_scale"] = scale_fit("th2_out", "th2_off")
    # offset history (distinct printed offsets with their first/last date)
    hist = collections.defaultdict(list)
    for p in pts:
        if "th1_off" in p:
            hist[(round(p["th1_off"], 5), round(p.get("th2_off", float("nan")), 5))].append(p["date"])
    out["offset_history"] = sorted(({"th1_offset": k[0], "th2_offset": None if k[1] != k[1] else k[1], "first": min(v), "last": max(v), "n": len(v)} for k, v in hist.items()),
                                   key=lambda x: x["first"])
    era = collections.defaultdict(list)
    for p in pts:
        if "th1_out" in p:
            era[p["date"][:4]].append(p["th1_out"] - mono_fit.bragg_deg(p["E"]))
    out["th1_minus_bragg_by_year"] = {k: {"median": statistics.median(v), "min": min(v), "max": max(v), "n": len(v)} for k, v in sorted(era.items())}
    t = collections.defaultdict(list)
    for p in pts:
        if "th1_out" in p and "th2_out" in p:
            t[p["date"][:4]].append(p["th2_out"] - p["th1_out"])
    out["th2_minus_th1_by_year"] = {k: {"median": statistics.median(v), "min": min(v), "max": max(v), "n": len(v)} for k, v in sorted(t.items())}
    # --- Chi2 output vs E: smooth polynomial
    c = sorted({(round(p["E"], 3), p["chi2_out"]) for p in pts if "chi2_out" in p})
    Ec = np.array([a for a, _ in c]); Cc = np.array([b for _, b in c])
    best = None
    for deg in (2, 3, 4):
        co = np.polyfit(Ec - 70.0, Cc, deg)
        rs = Cc - np.polyval(co, Ec - 70.0)
        rms = float(np.sqrt(np.mean(rs ** 2)))
        if best is None or rms < best[1] * 0.5:
            best = (deg, rms, co, float(np.abs(rs).max()))
    out["chi2"] = {"form": "Chi2_out[deg] = polynomial(E - 70 keV)", "degree": best[0], "coef_high_to_low": [float(x) for x in best[2]], "rms_deg": best[1], "max_abs_deg": best[3],
                   "n": len(c), "E_range": [float(Ec.min()), float(Ec.max())], "points": [[float(e), float(v)] for e, v in c]}
    (OUT / "hem_fit.json").write_text(json.dumps(out, indent=1))
    z2 = out["z2"]
    print(f"{len(pts)} tier-A HEM transform records; excluded readings: {dict(excl)}")
    print(f"Z2 = {z2['c']:.4f}/tan(2thB) {z2['d']:+.4f} mm   rms {z2['rms_mm']*1000:.2f} um (max {z2['max_abs_mm']*1000:.2f} um), n={z2['n']}, E {z2['E_range']}")
    print(f"   old model Z2=c/tan(2thB): c={z2['old_model']['c']:.3f} rms {z2['old_model']['rms_mm']:.3f} mm max {z2['old_model']['max_abs_mm']:.3f} mm")
    for k in ("th1_scale", "th2_scale"):
        v = out.get(k)
        if v:
            print(f"{k}: {v['model']}  s = {v['s']:.7f} +- {v['s_err']:.1e}  rms {v['rms_deg']:.1e} deg (max {v['max_abs_deg']:.1e}) n={v['n']}")
    print("offset history (Th1, Th2 printed offsets):", [(h['first'][:7], h['th1_offset'], h['th2_offset'], h['n']) for h in out['offset_history']])
    print(f"Chi2(E): degree {out['chi2']['degree']} rms {out['chi2']['rms_deg']:.2e} deg max {out['chi2']['max_abs_deg']:.2e}; coef {out['chi2']['coef_high_to_low']}")


def gap_points():
    """(gap, energy) from the SAME screenshot: ID Gap Control readbacks, 'Und2.1 Gap Rdbk' + 'DS Und2.1 E', 'DS Und gap' + 'X Energy'."""
    import sqlite3
    db = kb.connect()
    db.row_factory = sqlite3.Row
    img = rows_by_image(db, "(label LIKE '%Und%' OR label LIKE '%ID Gap Control%' OR label LIKE '%X Energy%')")
    pts, excl = [], collections.Counter()
    for sha, rs in img.items():
        g, e = None, None
        for r in rs:
            n = _norm(r["label"])
            isg = ("gap" in n) and any(k in n for k in ("avgcurrent", "rdbk", "dsundgap", "dsund")) and "desired" not in n and "set" not in n and "tpr" not in n
            ise = (("energy" in n or n.endswith("e(kev)")) and any(k in n for k in ("avgcurrent", "dsund", "xenergy"))) and "desired" not in n and "tpr" not in n and "scu" not in n
            if isg or ise:
                if r["tier"] != "A":
                    excl[r["tier"]] += 1
                    continue
            if isg and g is None:
                g = r
            elif ise and e is None:
                e = r
        if g and e and 5 < g["value"] < 40 and 30 < e["value"] < 130:
            pts.append({"gap": g["value"], "E": e["value"], "date": g["date"], "cite": f"{g['doc_id']}:L{g['ln']}", "sha10": sha[:10]})
    return pts, excl


def cmd_gap():
    import numpy as np
    from blade.physics import undulator
    sim = json.loads((HERE.parent / "beamline_twins" / "1-ID" / "sim.json").read_text())["undulator"]
    per, coef = sim["period_mm"], tuple(sim["k_coef"])
    pts, excl = gap_points()
    out_rows, nsel = [], collections.Counter()
    for p in sorted(pts, key=lambda x: x["E"]):
        # harmonic = the one whose model gap is closest to the readback (the screenshot does not show n)
        cand = []
        for n_ in (3, 5, 7, 9, 11, 13):
            try:
                cand.append((abs(undulator.gap_for_energy_mm(p["E"], n_, per, coef=coef) - p["gap"]), n_))
            except ValueError:
                pass
        if not cand:
            continue
        n = min(cand)[1]
        gm = undulator.gap_for_energy_mm(p["E"], n, per, coef=coef)
        out_rows.append({**p, "n": n, "gap_model": round(gm, 4), "resid_mm": round(p["gap"] - gm, 4)})
        nsel[n] += 1
    res = [r["resid_mm"] for r in out_rows]
    out = {"n": len(out_rows), "excluded_readings_by_tier": dict(excl), "harmonic_counts": dict(nsel), "model": {"period_mm": per, "k_coef": list(coef)},
           "resid_mm": {"median": statistics.median(res) if res else None, "rms": float(np.sqrt(np.mean(np.square(res)))) if res else None, "max_abs": max(abs(x) for x in res) if res else None},
           "rows": out_rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gap_fit.json").write_text(json.dumps(out, indent=1))
    print(f"{len(out_rows)} tier-A (gap, E) pairs from one screenshot; excluded {dict(excl)}; harmonics {dict(nsel)}")
    print("residual vs sim.json gap model:", out["resid_mm"])
    for r in out_rows:
        print(f"  {r['date']:10s} E={r['E']:8.3f} gap={r['gap']:7.3f} n={r['n']:2d} model={r['gap_model']:7.3f} d={r['resid_mm']:+.4f}  {r['cite']}")



ENERGY_RE = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d{1,4})?)\s*keV|(?<![\d.])(\d{2})p(\d{1,4})\s*keV", re.I)


def energies_in(text):
    out = []
    for m in ENERGY_RE.finditer(text or ""):
        v = float(m.group(1)) if m.group(1) else float(m.group(2) + "." + m.group(3))
        if 30 <= v <= 130:
            out.append(v)
    return out


def energy_context(db, doc, ln, back=40, fwd=5, tol=0.15):
    """Energy for a screenshot from the log text around it. STRICT: every energy mentioned in [ln-back, ln+fwd] must agree within `tol` keV;
    otherwise None (ambiguous or absent). Returns (E, distance_lines, n_mentions) or None."""
    ms = []
    for r in db.execute("SELECT ln, text FROM lines WHERE doc_id=? AND ln BETWEEN ? AND ? ORDER BY ln", (doc, ln - back, ln + fwd)):
        for v in energies_in(r["text"]):
            ms.append((r["ln"], v))
    if not ms:
        return None
    vs = [v for _, v in ms]
    if max(vs) - min(vs) > tol:
        return None
    before = [m for m in ms if m[0] <= ln] or ms
    near = max(before, key=lambda m: m[0])
    return near[1], abs(ln - near[0]), len(ms)


LENS_DEV = {  # canonical names -> device keys in fact_dev (all tier-A user readbacks)
    "L1E_th": "l1eth", "L2E_th": "l2eth", "L1E_y": "l1ey(inv)", "L2E_y": "l2ey(upr)",
    "L4B_th": "b24l4bth(rx)", "L5B_th": "b29l5bth(rx)", "L4B_y": "b22l4by(upright)", "L5B_y": "b47l5by(inv)",
}


def cmd_lens():
    import sqlite3
    import numpy as np
    from blade.physics import lens as L
    db = kb.connect()
    db.row_factory = sqlite3.Row
    inv = {v: k for k, v in LENS_DEV.items()}
    inv["b24l4bth"] = "L4B_th"
    inv["b29l5bth"] = "L5B_th"
    inv["b22l4by"] = "L4B_y"
    img = collections.defaultdict(dict)
    meta = {}
    n_ex = collections.Counter()
    for r in db.execute("SELECT sha256,doc_id,ln,date,device,quantity,value,tier FROM fact_obs WHERE quantity IN ('rbv','rbv_user')"):
        if r["device"] in inv:
            if r["tier"] != "A":
                n_ex[r["device"]] += 1
                continue
            img[r["sha256"]][inv[r["device"]]] = r["value"]
            meta[r["sha256"]] = (r["doc_id"], r["ln"], r["date"])
    rows, no_energy = [], 0
    for sha, d in img.items():
        doc, ln, date = meta[sha]
        ec = energy_context(db, doc, ln)
        if not ec:
            no_energy += 1
            continue
        rows.append({"sha10": sha[:10], "date": date, "cite": f"{doc}:L{ln}", "E": ec[0], "E_dist_lines": ec[1], "E_mentions": ec[2], **d})
    OUT.mkdir(parents=True, exist_ok=True)
    out = {"n_images_with_lens_readback": len(img), "n_without_unambiguous_energy": no_energy, "excluded_readings_by_device": dict(n_ex), "rows": rows}
    print(f"{len(img)} images with tier-A lens readbacks; {no_energy} dropped (no unambiguous energy in the log text); {len(rows)} kept")
    # model comparison: tilt vs energy for the th motors
    res = {}
    for key, name in (("L1E_th", "lens1E"), ("L2E_th", "lens2E"), ("L4B_th", "lens4B"), ("L5B_th", "lens5B")):
        pts = [(r["E"], r[key], r["date"], r["cite"]) for r in rows if key in r]
        if not pts:
            continue
        Eg = np.array([p[0] for p in pts]); T = np.array([p[1] for p in pts])
        focus = L.DEFAULT_FOCUS_E_M if name.endswith("E") else None
        if focus is None:
            continue
        pred = np.array([L.focus_motor_target(name, e)[1] for e in Eg])
        res[key] = {"n": len(pts), "E_range": [float(Eg.min()), float(Eg.max())], "resid_deg_median": float(np.median(T - pred)),
                    "resid_deg_rms": float(np.sqrt(np.mean((T - pred) ** 2))), "points": [[float(a), float(b), c, d] for a, b, c, d in pts],
                    "pred": [float(x) for x in pred]}
    out["model_check"] = res
    (OUT / "lens_points.json").write_text(json.dumps(out, indent=1))
    for k, v in res.items():
        print(f"{k}: n={v['n']} E {v['E_range']}  logged - model (focus at 71.5 m): median {v['resid_deg_median']:+.4f} deg, rms {v['resid_deg_rms']:.4f}")
    for r in sorted(rows, key=lambda x: (x.get('L1E_th') is None, x['E'])):
        print(f"  {r['date']:10s} E={r['E']:7.3f} (d={r['E_dist_lines']:2d}) " + "  ".join(f"{k}={r[k]:.4f}" for k in LENS_DEV if k in r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["hem", "gap", "lens"])
    a = ap.parse_args()
    if a.cmd == "hem":
        cmd_hem()
    elif a.cmd == "gap":
        cmd_gap()
    else:
        cmd_lens()


if __name__ == "__main__":
    main()
