#!/usr/bin/env python3
"""Aggregate statistics from the transcribed panel facts (tables fact_obs / fact_dev, see factnorm.py).

    factstats.py devices            # per-device position stats, limits, dial/user offset, step sizes -> <KB_ROOT>/facts/analysis/device_stats.json
    factstats.py report             # aggregated markdown for the twin (no raw per-image values) -> stdout

Everything here is aggregated (counts, quantiles, modal values); raw per-image numbers stay in the private KB.
RELIABILITY (user rule 2026-11-13): only tier-A readings (see factnorm.py: clean, conf >= 0.9, no doubt flags, passed the
cross-checks) enter any statistic here. Tier B/C are counted (`n_excluded`) but never used for numbers.
Position stats use user-coordinate readbacks only (rbv_user, else rbv).
"""
import argparse
import collections
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb  # noqa: E402

OUT = kb.KB_ROOT / "facts" / "analysis"
TIER = "A"


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def modal(xs, nd=6, top=4):
    c = collections.Counter(round(x, nd) for x in xs)
    return [[v, n] for v, n in c.most_common(top)]


def era(date):
    return (date or "")[:4] or "?"


def device_stats(min_images=3):
    db = kb.connect()
    devs = db.execute("SELECT * FROM fact_dev WHERE n_images>=? ORDER BY n_obs DESC", (min_images,)).fetchall()
    out = {}
    for d in devs:
        rows = db.execute("SELECT sha256,date,quantity,value,unit,pv,conf,doc_id,ln FROM fact_obs WHERE device=? AND value IS NOT NULL AND tier=?",
                          (d["device"], TIER)).fetchall()
        n_excl = db.execute("SELECT COUNT(*) FROM fact_obs WHERE device=? AND tier!=?", (d["device"], TIER)).fetchone()[0]
        byq = collections.defaultdict(list)
        for r in rows:
            byq[r["quantity"]].append(r)
        # user-coordinate readback per image: the "(user)" field of a full window, else the compact window's readback
        per = {}
        for r in byq.get("rbv", []):
            per.setdefault(r["sha256"], []).append((r["value"], r["date"]))
        for r in byq.get("rbv_user", []):
            per[r["sha256"]] = [(r["value"], r["date"])]          # a full window's (user) field wins over a compact one
        rec = {"display": d["display"], "hutch": d["hutch"], "units": json.loads(d["units"]), "n_images": d["n_images"],
               "first": d["first_date"], "last": d["last_date"], "motor_nos": json.loads(d["motor_nos"]), "n_excluded": n_excl}
        pvs = db.execute("SELECT pv,n,share FROM fact_pvmap WHERE device=? ORDER BY n DESC", (d["device"],)).fetchall()
        rec["pv_candidates"] = [[p["pv"], p["n"], p["share"]] for p in pvs[:4]]
        if per:
            vals = [statistics.median(v for v, _ in lst) for lst in per.values()]
            rec["position"] = {"quantity": "user readback", "n": len(vals), "min": min(vals), "p10": q(vals, .1), "median": q(vals, .5),
                               "p90": q(vals, .9), "max": max(vals), "modal": modal(vals, 4)}
            ys = collections.defaultdict(list)
            for lst in per.values():
                for v, dt in lst:
                    ys[era(dt)].append(v)
            rec["position_by_year"] = {y: {"n": len(v), "median": q(v, .5), "min": min(v), "max": max(v)} for y, v in sorted(ys.items()) if len(v) >= 2}
        lim = {}
        for k in ("hi_user", "lo_user", "hi_dial", "lo_dial"):
            if byq.get(k):
                lim[k] = modal([r["value"] for r in byq[k]], 5, 3)
        if lim:
            rec["limits"] = lim
        # dial - user offset from images that carry both readbacks
        u = {(r["sha256"]): r["value"] for r in byq.get("rbv_user", [])}
        dl = {(r["sha256"]): r["value"] for r in byq.get("rbv_dial", [])}
        offs = [dl[s] - u[s] for s in u if s in dl]
        if offs:
            rec["dial_minus_user"] = {"n": len(offs), "modal": modal(offs, 4, 4), "min": min(offs), "max": max(offs)}
        st = [r["value"] for k in ("step", "step_h", "step_v") for r in byq.get(k, []) if r["value"] > 0]
        if st:
            rec["tweak_step"] = {"n": len(st), "modal": modal(st, 6, 5), "min": min(st), "max": max(st)}
        # drive vs readback gap (following error at the moment of the screenshot)
        sp = {r["sha256"]: r["value"] for r in byq.get("drive_user", []) + byq.get("setpoint", [])}
        rb = {r["sha256"]: r["value"] for r in byq.get("rbv_user", []) + byq.get("rbv", [])}
        gaps = [abs(sp[s] - rb[s]) for s in sp if s in rb]
        if gaps:
            rec["follow_error"] = {"n": len(gaps), "median": q(gaps, .5), "p90": q(gaps, .9), "max": max(gaps)}
        sz = {}
        for k in ("size_h", "size_v", "center_h", "center_v"):
            if byq.get(k):
                v = [r["value"] for r in byq[k]]
                sz[k] = {"n": len(v), "median": q(v, .5), "min": min(v), "max": max(v), "modal": modal(v, 4, 4)}
        if sz:
            rec["slit"] = sz
        out[d["device"]] = rec
    return out


def registry(min_images=3):
    """Aggregated device registry for the beamline twin (no raw per-image values). PV is only LINKED when the string was printed on a window
    title (tier A readings), seen on >= 3 images, carried by >= 90 % of that device's PV-bearing readings, and not claimed by another device
    in the same hutch; otherwise the PVs stay a candidate list (twin rule: never attach on a guess)."""
    st = device_stats(min_images)
    db = kb.connect()
    # which devices carry each pv (tier A only)
    pvdev = collections.defaultdict(collections.Counter)
    for r in db.execute("SELECT device, pv FROM fact_obs WHERE pv!='' AND tier='A'"):
        pvdev[r["pv"]][r["device"]] += 1
    out = {}
    for dev, rec in st.items():
        if not (rec.get("position") or rec.get("limits") or rec.get("tweak_step") or rec.get("slit")):
            continue
        pvc = collections.Counter()
        for r in db.execute("SELECT pv FROM fact_obs WHERE device=? AND pv!='' AND tier='A'", (dev,)):
            pvc[r["pv"]] += 1
        tot = sum(pvc.values())
        linked, cands = None, []
        for pv, n in pvc.most_common(4):
            # a rival is another device carrying this pv; label fragments of the SAME device ("samxehilimit", "samxe[compact]hi") do not count
            rivals = [d for d in pvdev[pv] if d != dev and pvdev[pv][d] >= 3 and dev not in d and d not in dev]
            cands.append({"pv": pv, "n": n, "share": round(n / tot, 3), "also_on": rivals[:3]})
        if cands and cands[0]["n"] >= 3 and cands[0]["share"] >= 0.9 and not cands[0]["also_on"]:
            linked = cands[0]["pv"]
        e = {k: rec[k] for k in ("display", "hutch", "units", "n_images", "first", "last", "motor_nos", "n_excluded") if k in rec}
        e["pv"] = linked
        e["pv_status"] = "visible_on_screen" if linked else ("ambiguous" if cands else "none_on_screen")
        e["pv_candidates"] = cands
        for k in ("position", "position_by_year", "limits", "dial_minus_user", "tweak_step", "follow_error", "slit"):
            if k in rec:
                e[k] = rec[k]
        out[dev] = e
    return out


BASE_DEV = ("wbeam", "kohzueup", "kohzuedn", "ckslitus", "ckslitds", "bkslit")


def baseline(min_images=3):
    """Per-energy baseline states: medians over screenshots whose energy comes from the log text around them (strict: all energy mentions in the
    preceding 40 lines agree within 0.15 keV). Tier-A slit readings only. Aggregated: per-image values stay in the private KB."""
    import factphysics as fp
    import sqlite3 as s3
    db = kb.connect()
    db.row_factory = s3.Row
    st = collections.defaultdict(dict)
    meta = {}
    for r in db.execute("SELECT sha256,doc_id,ln,date,device,quantity,value FROM fact_obs WHERE tier='A' AND quantity IN ('size_h','size_v','center_h','center_v') AND device IN (%s)" % ",".join("?" * len(BASE_DEV)), BASE_DEV):
        st[r["sha256"]][r["device"] + "." + r["quantity"]] = r["value"]
        meta[r["sha256"]] = (r["doc_id"], r["ln"], r["date"])
    bins = collections.defaultdict(list)
    for sha, (doc, ln, date) in meta.items():
        ec = fp.energy_context(db, doc, ln)
        if ec:
            bins[round(ec[0] * 2) / 2].append((sha, doc, date, ec[0], st[sha]))
    out = {}
    for b, lst in sorted(bins.items()):
        if len(lst) < min_images:
            continue
        rec = {"energy_bin_keV": b, "n_images": len(lst), "n_logs": len({x[1] for x in lst}), "energies_keV": [round(min(x[3] for x in lst), 3), round(max(x[3] for x in lst), 3)],
               "years": sorted({x[2][:4] for x in lst}), "values": {}}
        keys = sorted({k for x in lst for k in x[4]})
        for k in keys:
            v = [x[4][k] for x in lst if k in x[4]]
            if len(v) >= 3:
                rec["values"][k] = {"n": len(v), "median": q(v, .5), "p10": q(v, .1), "p90": q(v, .9), "modal": modal(v, 3, 3)}
        out[str(b)] = rec
    return out


def cmd_devices():
    OUT.mkdir(parents=True, exist_ok=True)
    s = device_stats()
    (OUT / "device_stats.json").write_text(json.dumps(s, indent=1))
    print(f"{len(s)} devices (>=3 images) -> {OUT/'device_stats.json'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["devices", "registry", "baseline"])
    a = ap.parse_args()
    if a.cmd == "devices":
        cmd_devices()
    elif a.cmd == "baseline":
        b = baseline()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "baseline.json").write_text(json.dumps(b, indent=1))
        for k, v in b.items():
            print(f"E~{k} keV: {v['n_images']} images / {v['n_logs']} logs, {v['years']}")
            for kk, vv in v["values"].items():
                print(f"    {kk:22s} median {vv['median']:.3f}  p10..p90 {vv['p10']:.3f}..{vv['p90']:.3f}  n={vv['n']}")
    else:
        r = registry()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "registry.json").write_text(json.dumps(r, indent=1))
        c = collections.Counter(v["pv_status"] for v in r.values())
        print(f"{len(r)} devices in registry; pv status {dict(c)} -> {OUT/'registry.json'}")


if __name__ == "__main__":
    main()
