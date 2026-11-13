#!/usr/bin/env python3
"""Normalise transcribed panel facts into per-device observations and a device registry.

    factnorm.py build        # (re)build tables fact_obs, fact_dev, fact_pvmap from `facts`
    factnorm.py devices [-n 60] [--hutch E]
    factnorm.py show DEVICE  # all observations of one device (key as in `devices`)

fact_obs : one row per (image, device, quantity): value, unit, date, hutch, conf, provenance (sha256, doc_id, ln)
fact_dev : one row per canonical device: hutch, units, n_obs, n_images, dates, label variants
fact_pvmap : (device, pv) with counts - CANDIDATES only; a pv is never assigned to a device when two or more
             different pvs compete for it (twin rule: no guessed assignments)
Roles for motors: rbv_user rbv_dial drive_user drive_dial hi_user hi_dial lo_user lo_dial step rbv setpoint
Roles for slits : size_h size_v center_h center_v step_h step_v blade_top/bottom/left/right
Other kinds keep quantity = kind (scaler, calc, energy, gap, current, preamp, status ...).
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb  # noqa: E402

SCHEMA = """
DROP TABLE IF EXISTS fact_obs; DROP TABLE IF EXISTS fact_dev; DROP TABLE IF EXISTS fact_pvmap;
CREATE TABLE fact_obs(id INTEGER PRIMARY KEY, fact_id INT, sha256 TEXT, doc_id TEXT, ln INT, date TEXT, device TEXT, quantity TEXT,
  value REAL, unit TEXT, pv TEXT, hutch TEXT, conf REAL, kind TEXT, label TEXT, panel_type TEXT, tier TEXT, flags TEXT);
CREATE INDEX fo_dev ON fact_obs(device, quantity); CREATE INDEX fo_img ON fact_obs(sha256); CREATE INDEX fo_doc ON fact_obs(doc_id, ln);
CREATE TABLE fact_dev(device TEXT PRIMARY KEY, display TEXT, hutch TEXT, kinds TEXT, units TEXT, n_obs INT, n_images INT,
  first_date TEXT, last_date TEXT, labels TEXT, motor_nos TEXT);
CREATE TABLE fact_pvmap(device TEXT, pv TEXT, n INT, share REAL, unique_pv INT);
"""

ROLE_SUFFIX = [
    (r"\bHi limit \(user\)$", "hi_user"), (r"\bHi limit \(dial\)$", "hi_dial"),
    (r"\bLo limit \(user\)$", "lo_user"), (r"\bLo limit \(dial\)$", "lo_dial"),
    (r"\bReadback \(user\)$", "rbv_user"), (r"\bReadback \(dial\)$", "rbv_dial"),
    (r"\bDrive \(user\)$", "drive_user"), (r"\bDrive \(dial\)$", "drive_dial"),
    (r"\bTweak$", "step"), (r"\[compact\] step$", "step"), (r"\[compact\] entry$", "setpoint"),
    (r"\[compact\]$", "rbv"), (r"\bentry$", "setpoint"), (r"\bstep$", "step"),
    (r"\bblade (top|bottom|left|right)$", None),
]
SLIT_RE = re.compile(r"^(?P<dev>.+?)\s+(?P<ax>[HV])[-_ ]?(?P<q>SIZE|CENTER)(?:\s+(?P<tail>step|entry))?$", re.I)
BLADE_RE = re.compile(r"^(?P<dev>.+?)\s+blade\s+(?P<side>top|bottom|left|right)(?:\s+(?P<tail>step))?$", re.I)
LEAD_NO = re.compile(r"^(?P<no>\d{1,3})\s+(?P<rest>.+)$")
SERIAL = re.compile(r"\s*\(?\d{6}\)?\s*$")
PVHUTCH = {"1ida": "A", "1idb": "B", "1idc": "C", "1ide": "E", "1ide1": "E", "1idfoc": "", "1idd": "D"}


def devkey(name):
    n = re.sub(r"\s+", " ", name).strip()
    n = SERIAL.sub("", n).strip()
    return re.sub(r"[\s_]+", "", n).lower()


def parse_label(label, kind):
    """-> (device_key, display, quantity, motor_no)"""
    lab = re.sub(r"\s+", " ", label).strip()
    m = SLIT_RE.match(lab)
    if m:
        ax = m["ax"].lower()
        q = ("size_" if m["q"].lower() == "size" else "center_") + ax
        if m["tail"]:
            q = ("step_" + ax) if m["tail"].lower() == "step" else q
        return devkey(m["dev"]), m["dev"], q, None
    m = BLADE_RE.match(lab)
    if m:
        q = "blade_" + m["side"].lower() + ("_step" if m["tail"] else "")
        return devkey(m["dev"]), m["dev"], q, None
    if kind in ("motor_rbv", "motor_setpoint", "motor_step", "motor_limit"):
        for pat, role in ROLE_SUFFIX:
            mm = re.search(pat, lab)
            if mm and role:
                base = lab[:mm.start()].strip()
                break
        else:
            base, role = lab, {"motor_rbv": "rbv", "motor_setpoint": "setpoint", "motor_step": "step", "motor_limit": "limit"}[kind]
        no = None
        ln = LEAD_NO.match(base)
        if ln:
            no, base = int(ln["no"]), ln["rest"]
        return devkey(base), SERIAL.sub("", base).strip(), role, no
    if kind in ("slit_step", "slit_size", "slit_center"):
        return devkey(lab), lab, kind, None
    return devkey(lab), lab, kind, None


def pv_hutch(pv):
    m = re.match(r"^(1id[a-z]*\d?)[:_]", pv or "")
    return PVHUTCH.get(m.group(1), "") if m else ""


def doc_date_fallback(doc):
    m = re.match(r"^(\d{4})", doc)
    return m.group(1) if m else ""



# ---------------------------------------------------------------------------------------------
# Reliability. Tier A = clean (used for fits, limits, offsets, steps); B = minor doubt (counted, NOT used for
# numbers); C = excluded everywhere. A reading is C when ANY hard flag fires. Nothing guessed is ever used.
# ---------------------------------------------------------------------------------------------
HARD_NOTE = re.compile(r"guess|assum|infer|memory|uncertain|unclear|unsure|ambig|obscur|hidden|covered|tooltip|cursor|blurr|illegible|unreadable|"
                       r"may be|likely|looks like|probably|inconsisten|differs|mismatch|disagree|not visible|too small|tiny|"
                       r"truncated|title cropped|no printed label|low confidence|odd|not sure|estimated", re.I)
SOFT_NOTE = re.compile(r"crop|cut off|clipped|partly|overlap|partial", re.I)
CROP_OK = re.compile(r"last digit (may be )?cropped", re.I)
OFFSET_TOL = 1e-5


def _clean_note(note):
    return CROP_OK.sub("", note or "")


def reading_flags(f):
    """flags for ONE reading from its own record (conf, value, notes, legibility)"""
    fl = []
    if f["value"] is None:
        fl.append("null_value")
    if (f["conf"] or 0) < 0.8:
        fl.append("conf<0.8")
    elif f["conf"] < 0.9:
        fl.append("conf<0.9")
    if f["legible"] == "no":
        fl.append("illegible_image")
    note = f["note"] or ""
    if CROP_OK.search(note):
        fl.append("last_digit_cropped")
    rest = _clean_note(note)
    if HARD_NOTE.search(rest):
        fl.append("hard_note")
    elif SOFT_NOTE.search(rest):
        fl.append("soft_note")
    if f["legible"] == "partial":
        fl.append("partial_image")
    if re.search(r"title cropped|\(title|column \d", f["label"] or "", re.I):
        fl.append("hard_note")          # device identity unknown: the tile's title was cut off
    return fl


def group_checks(rows):
    """objective cross-checks inside one (image, device): returns {row index: [flags]} """
    out = collections.defaultdict(list)
    by = collections.defaultdict(list)
    for i, r in enumerate(rows):
        by[r["quantity"]].append(i)

    def val(q):
        return [(i, rows[i]["value"]) for i in by.get(q, []) if rows[i]["value"] is not None]

    # (1) user<->dial relation must be one consistent calibration. Two hypotheses (motor direction):
    #     pos: dial = user + c   (rbv, drive, hi<->hi, lo<->lo)      neg: dial = c - user   (hi_user<->lo_dial, lo_user<->hi_dial)
    def cluster(vals):
        best, bestn = None, 0
        for o in vals:
            n = sum(1 for x in vals if abs(x - o) <= OFFSET_TOL + 1e-6 * abs(o))
            if n > bestn:
                best, bestn = o, n
        return best, bestn

    def pairs_for(mapping, sign):
        res = []
        for a_, b_ in mapping:
            for (iu, vu) in val(a_):
                for (idl, vd) in val(b_):
                    res.append(((vd - vu) if sign > 0 else (vd + vu), iu, idl))
        return res

    pos = pairs_for((("rbv_user", "rbv_dial"), ("drive_user", "drive_dial"), ("hi_user", "hi_dial"), ("lo_user", "lo_dial")), +1)
    neg = pairs_for((("rbv_user", "rbv_dial"), ("drive_user", "drive_dial"), ("hi_user", "lo_dial"), ("lo_user", "hi_dial")), -1)
    # Consistent if ANY hypothesis explains all of its pairs (>=2 pairs). Flag only when none does and the best one has >=3 pairs.
    cands = []
    for pr in (pos, neg):
        if len(pr) >= 2:
            c, n = cluster([p_[0] for p_ in pr])
            cands.append((n, len(pr), c, pr))
    if cands and not any(n == tot for n, tot, _, _ in cands):
        big = [t for t in cands if t[1] >= 3]
        if big:
            n, tot, c, pr = max(big, key=lambda t: (t[0] / t[1], t[0]))
            if n > tot / 2 and n >= 2:
                for o, iu, idl in pr:
                    if abs(o - c) > OFFSET_TOL + 1e-6 * abs(c):
                        out[iu].append("offset_inconsistent")
                        out[idl].append("offset_inconsistent")
            else:
                for o, iu, idl in pr:
                    out[iu].append("offset_no_majority")
                    out[idl].append("offset_no_majority")
    # (2) hi > lo, and the readback must sit inside the limits (user coordinates)
    for hq, lq in (("hi_user", "lo_user"), ("hi_dial", "lo_dial")):
        for (ih, vh) in val(hq):
            for (il, vl) in val(lq):
                if vh <= vl:
                    out[ih].append("hi<=lo")
                    out[il].append("hi<=lo")
    for rq, hq, lq in (("rbv_user", "hi_user", "lo_user"), ("rbv_dial", "hi_dial", "lo_dial")):
        for (ir, vr) in val(rq):
            for (ih, vh) in val(hq):
                if vr > vh + 1e-3 + 1e-6 * abs(vh):
                    out[ir].append("rbv>hi")
                    out[ih].append("rbv>hi")
            for (il, vl) in val(lq):
                if vr < vl - 1e-3 - 1e-6 * abs(vl):
                    out[ir].append("rbv<lo")
                    out[il].append("rbv<lo")
    # (3) slit sizes cannot be negative
    for q in ("size_h", "size_v"):
        for (i, v) in val(q):
            if v < 0:
                out[i].append("negative_size")
    return out


def tier_of(flags):
    hard = {"null_value", "conf<0.8", "illegible_image", "hard_note", "offset_inconsistent", "offset_no_majority",
            "hi<=lo", "rbv>hi", "rbv<lo", "negative_size"}
    if any(f in hard for f in flags):
        return "C"
    if any(f in ("conf<0.9", "last_digit_cropped", "soft_note", "partial_image") for f in flags):
        return "B"
    return "A"


def build():
    db = kb.connect()
    db.executescript(SCHEMA)
    # date lookup: image_refs.date else nearest preceding non-empty lines.date in the doc
    refdate = {r[0]: r[1] for r in db.execute("SELECT sha256, MIN(date) FROM image_refs WHERE date!='' GROUP BY sha256")}
    cache = {}

    def date_for(sha, doc, ln):
        if sha in refdate:
            return refdate[sha]
        if doc not in cache:
            cache[doc] = [(r[0], r[1]) for r in db.execute("SELECT ln,date FROM lines WHERE doc_id=? AND date!='' ORDER BY ln", (doc,))]
        best = ""
        for l, d in cache[doc]:
            if l <= ln:
                best = d
            else:
                break
        return best or doc_date_fallback(doc)

    imghutch = {r[0]: r[1] for r in db.execute("SELECT sha256, value FROM label_best WHERE key='hutch'")}
    rows = db.execute("SELECT * FROM facts").fetchall()
    obs = []
    for f in rows:
        dev, disp, q, no = parse_label(f["label"], f["kind"])
        if not dev:
            continue
        hut = pv_hutch(f["pv"]) or f["hutch"] or imghutch.get(f["sha256"], "")
        obs.append({"f": f, "device": dev, "quantity": q, "value": f["value"], "hutch": hut, "flags": reading_flags(f)})
    groups = collections.defaultdict(list)
    for i, o in enumerate(obs):
        groups[(o["f"]["sha256"], o["device"])].append(i)
    for key, idxs in groups.items():
        sub = [obs[i] for i in idxs]
        for local, fl in group_checks(sub).items():
            obs[idxs[local]]["flags"].extend(fl)
    n = 0
    for o in obs:
        f = o["f"]
        tier = tier_of(o["flags"])
        db.execute("INSERT INTO fact_obs(fact_id,sha256,doc_id,ln,date,device,quantity,value,unit,pv,hutch,conf,kind,label,panel_type,tier,flags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f["id"], f["sha256"], f["doc_id"], f["ln"], date_for(f["sha256"], f["doc_id"], f["ln"]), o["device"], o["quantity"], f["value"],
                    f["unit"], f["pv"], o["hutch"], f["conf"], f["kind"], f["label"], f["panel_type"], tier, ",".join(sorted(set(o["flags"])))))
        n += 1
    # registry (motor numbers kept from the leading '36 ' in labels)
    nos = collections.defaultdict(collections.Counter)
    for f in rows:
        dev, disp, q, no = parse_label(f["label"], f["kind"])
        if no is not None:
            nos[dev][no] += 1
    disp_names = collections.defaultdict(collections.Counter)
    for f in rows:
        dev, disp, q, no = parse_label(f["label"], f["kind"])
        disp_names[dev][disp] += 1
    for (dev,) in db.execute("SELECT DISTINCT device FROM fact_obs").fetchall():
        o = db.execute("SELECT hutch, kind, unit, date, sha256 FROM fact_obs WHERE device=?", (dev,)).fetchall()
        hc = collections.Counter(r["hutch"] for r in o if r["hutch"])
        uc = collections.Counter(r["unit"] for r in o if r["unit"])
        kc = collections.Counter(r["kind"] for r in o)
        ds = sorted(r["date"] for r in o if r["date"])
        db.execute("INSERT INTO fact_dev VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (dev, disp_names[dev].most_common(1)[0][0], hc.most_common(1)[0][0] if hc else "",
                    json.dumps(dict(kc)), json.dumps(dict(uc)), len(o), len({r["sha256"] for r in o}),
                    ds[0] if ds else "", ds[-1] if ds else "", json.dumps(dict(disp_names[dev].most_common(6))),
                    json.dumps(dict(nos[dev].most_common(4)))))
    # PV candidates: how often each pv string sits on each device's readings
    pvc = collections.defaultdict(collections.Counter)
    pvdev = collections.defaultdict(collections.Counter)
    for r in db.execute("SELECT device, pv FROM fact_obs WHERE pv!=''"):
        pvc[r["device"]][r["pv"]] += 1
        pvdev[r["pv"]][r["device"]] += 1
    for dev, c in pvc.items():
        tot = sum(c.values())
        for pv, k in c.items():
            uniq = 1 if len(pvdev[pv]) == 1 and len(c) == 1 else 0
            db.execute("INSERT INTO fact_pvmap VALUES(?,?,?,?,?)", (dev, pv, k, round(k / tot, 3), uniq))
    db.commit()
    nd = db.execute("SELECT COUNT(*) FROM fact_dev").fetchone()[0]
    print(f"{n} observations, {nd} devices")


def devices(n, hutch):
    db = kb.connect()
    q = "SELECT * FROM fact_dev" + (" WHERE hutch=?" if hutch else "") + " ORDER BY n_obs DESC LIMIT ?"
    for r in db.execute(q, ((hutch, n) if hutch else (n,))):
        pv = db.execute("SELECT pv,n FROM fact_pvmap WHERE device=? ORDER BY n DESC LIMIT 3", (r["device"],)).fetchall()
        print(f"{r['n_obs']:5d} {r['n_images']:4d}img  {r['hutch'] or '-':1s}  {r['device']:24s} {r['first_date'][:7]}..{r['last_date'][:7]}  pv: {[(p['pv'], p['n']) for p in pv]}")


def reliability():
    db = kb.connect()
    tot = db.execute("SELECT COUNT(*) FROM fact_obs").fetchone()[0]
    print(f"{tot} observations")
    for r in db.execute("SELECT tier, COUNT(*) c FROM fact_obs GROUP BY tier ORDER BY tier"):
        print(f"  tier {r['tier']}: {r['c']:6d}  ({100*r['c']/tot:.1f} %)")
    cnt = collections.Counter()
    for (fl,) in db.execute("SELECT flags FROM fact_obs WHERE flags!=''"):
        for x in fl.split(","):
            cnt[x] += 1
    print("flags:", dict(cnt.most_common()))
    print("tier C by kind:", db.execute("SELECT kind, COUNT(*) FROM fact_obs WHERE tier='C' GROUP BY kind ORDER BY 2 DESC LIMIT 8").fetchall())


def show(dev):
    db = kb.connect()
    for r in db.execute("SELECT date,quantity,value,unit,conf,doc_id,ln FROM fact_obs WHERE device=? ORDER BY date,quantity", (devkey(dev),)):
        print(f"{r['date']:10s} {r['quantity']:12s} {r['value']!s:>14s} {r['unit']:6s} c={r['conf']} {r['doc_id']}:L{r['ln']}")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("build")
    d = sp.add_parser("devices")
    d.add_argument("-n", type=int, default=60)
    d.add_argument("--hutch", default="")
    sp.add_parser("reliability")
    s = sp.add_parser("show")
    s.add_argument("device")
    a = ap.parse_args()
    {"build": build, "devices": lambda: devices(a.n, a.hutch), "show": lambda: show(a.device), "reliability": reliability}[a.cmd]()


if __name__ == "__main__":
    main()
