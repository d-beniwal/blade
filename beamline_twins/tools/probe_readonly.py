"""READ-ONLY probe of the 1-ID motors/records named in the open-conflicts list (pending/open_conflicts_and_gaps.md, plan step C2).

    python beamline_twins/tools/probe_readonly.py                  # default: LIST what would be read; no network, nothing contacted
    python beamline_twins/tools/probe_readonly.py --run            # read from the beamline (asks you to type READ first; --yes skips the prompt)
    python beamline_twins/tools/probe_readonly.py --run --group hem,samc --out my.csv   # default (no --group) = everything, incl. the 'registry' and 'metadata' groups
    python beamline_twins/tools/probe_readonly.py --groups         # list the groups

Run it only when you are on the beamline network and the beamline staff agree. It writes one CSV (default pending/desc_probe_<UTC>.csv).

WHY IT CANNOT CHANGE ANYTHING: it only lists PVs and hands them to the read-only gate blade/instrument/readonly.py (one network read path = a channel-access GET;
every name validated against an allow-list of read-only fields first; every pyepics write entry point disabled; no put/monitor/process anywhere). tests/test_probe_readonly.py checks each layer.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# ---- the guard lives in the package now: blade/instrument/readonly.py (validate_pv, READ_FIELDS, EXPLICIT_PVS, Reader, tripwire) ---------------------------
sys.path.insert(0, str(ROOT))
from blade.instrument.readonly import (READ_FIELDS, EXPLICIT_PVS, ReadOnlyViolation, ReaderUnavailable, Reader, validate_pv, _LETTERS)  # noqa: E402,F401

# ---- what to read (groups follow the conflict ids A1..A23 of pending/open_conflicts_and_gaps.md) ------------------------------------------------------------
def _motors(prefix, nums, fields=("DESC", "RBV", "EGU", "HLM", "LLM")):
    return [f"{prefix}m{n}.{f}" for n in nums for f in fields]


def _calc(rec):
    """Transform/calc record: description, link strings, calc strings and current values (read-only)."""
    return [f"{rec}.DESC"] + [f"{rec}.{k}{c}" for k in ("INP", "CLC", "OUT") for c in _LETTERS] + [f"{rec}.{c}" for c in _LETTERS]


def build_groups():
    g = {}
    g["hem"] = (_motors("1idHEM:", [1, 4, 5, 6, 7, 8]) + _calc("1id:userTran3")
                + ["1idsft1:m1.DESC", "1idsft1:m1.RBV"], "A1/A2/A23: HEM axis roles; which userTran3 output drives which motor; old Z2 Aero still present?")
    g["hem_old"] = ([f"1ida:m{n}.DESC" for n in (11, 13, 17, 30, 32)] + [f"1ida:m{n}.RBV" for n in (11, 13, 17, 30, 32)],
                    "A23: do the 2024-2026 HEM PVs still exist?")
    g["fs"] = (_motors("1ide1:", [75, 77], ("DESC", "RBV", "EGU")), "A3: fast shutter E x/y")
    g["samc"] = (_motors("1idc:", [25, 26, 27, 28, 29, 31], ("DESC", "RBV", "EGU")) + _motors("1idGalil1:", [1, 2], ("DESC", "RBV", "EGU")),
                 "A4-A6: LabMotion SMS (C) x/y/z, rotations, m31, old Galil PVs")
    g["lensc"] = (_motors("1idc:", [99, 100, 101, 102, 103, 104], ("DESC", "RBV", "EGU")), "A7/A8: lens L1 / L5(RD) motors (C)")
    g["fourc"] = (_motors("1idc:", [40, 74, 75, 76, 85, 86, 88], ("DESC", "RBV", "EGU")) + _motors("1idcAMCI:", [2, 3, 4, 5, 6], ("DESC", "RBV", "EGU")),
                  "A14: four-circle axis roles")
    g["hydra"] = (_motors("1idc:", [7], ("DESC", "RBV", "EGU")) + _motors("1ide1:", [7], ("DESC", "RBV", "EGU")), "A9: Hydra D4 z")
    g["slitb"] = (_motors("1idb:", [32, 58, 59, 60, 61], ("DESC", "RBV", "EGU")), "A10: B Kohzu slit blade motors")
    g["nfd2"] = (_motors("1ide1:", [6], ("DESC", "RBV", "EGU")) + _motors("1ide:", [6], ("DESC", "RBV", "EGU")), "A12: NF D2 TiltY prefix")
    g["ehl"] = (_motors("1ide1:", [9, 10], ("DESC", "RBV", "EGU")) + _motors("1ide:", [9], ("DESC", "RBV", "EGU")) + _motors("1idcAMCI:", [16], ("DESC", "RBV", "EGU")),
                "A13: E HL-SMS map; the two m9")
    g["stackb"] = (_motors("1idb:", [43, 45, 25, 64], ("DESC", "RBV", "EGU")), "A21: B hutch 'Stack1' motors")
    g["saxs"] = (_motors("1ide1:", [49], ("DESC", "RBV", "EGU")), "A22: SAXS D6 shield")
    g["misc"] = (_motors("1idc:", [16, 33], ("DESC", "RBV", "EGU")) + _motors("1ide1:", [69, 70, 71], ("DESC", "RBV", "EGU")),
                 "B10: motors named only in the metadata map")
    g["cameras"] = ([p for p in sorted(EXPLICIT_PVS) if ":cam1:" in p], "A15-A17: camera identity strings (no image arrays are read)")
    g["ses"] = (["S01ID-PSS:SES:BeamBlockingM"], "A22: E-station shutter status")
    return g


def _motor_base(pv):
    m = re.match(r"^([A-Za-z0-9_\-]+:m\d+)(\.\w+)?$", pv)
    return m.group(1) if m else None


MOTOR_FIELDS = ("DESC", "RBV", "EGU", "HLM", "LLM", "PREC")


def registry_group():
    """EVERYTHING the twin knows (beamline_twins/1-ID/cs_registry.json): every motor (DESC, RBV, EGU, limits), every IC scaler channel (count + name)."""
    f = ROOT / "beamline_twins" / "1-ID" / "cs_registry.json"
    if not f.is_file():
        return [], "cs_registry.json not found"
    reg = json.loads(f.read_text())
    out, seen = [], set()

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("pv"), str) and _motor_base(o["pv"]):
                seen.add(_motor_base(o["pv"]))
            if isinstance(o.get("counts_pv"), str):
                out.append(o["counts_pv"])
                m = re.match(r"^(.*)\.S(\d+)$", o["counts_pv"])
                if m:
                    out.append(f"{m.group(1)}.NM{m.group(2)}")
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(reg)
    for b in sorted(seen):
        out += [f"{b}.{k}" for k in MOTOR_FIELDS]
    return out, "every motor and IC channel in the twin / CS-Studio registry (even the settled ones)"


def metadata_group(mpe_xml=None):
    """Every PV of the NeXus metadata map (CSV + XML): motors with DESC/RBV/EGU/limits; other records with DESC plus the PV itself. Names that fail
    validate_pv (not <record>.<FIELD>) are skipped, never read."""
    cands = [Path(mpe_xml)] if mpe_xml else [Path(os.environ.get("BLADE_MPE_XML", "")), Path.home() / "ANL-research/S1ID/0.beamline_control/mpe_xml"]
    d = next((c for c in cands if str(c) and (c / "docs").is_dir()), None)
    if d is None:
        return [], "mpe_xml folder not found (use --mpe-xml DIR)"
    pvs = set()
    for fp in (d / "docs").glob("*1ide_metadata_devices_pvs.csv"):
        for row in csv.reader(fp.open()):
            if len(row) > 2 and row[2]:
                pvs.add(row[2].strip())
    for fp in d.glob("1id_instr_attributes_trans.xml"):
        pvs.update(re.findall(r'source="([^"]+)"', fp.read_text()))
    out = []
    for pv in sorted(pvs):
        b = _motor_base(pv)
        if b:
            out += [f"{b}.{k}" for k in MOTOR_FIELDS]
        else:
            rec = pv.split(".")[0]
            out += [pv, f"{rec}.DESC"]
    return out, "every PV of the NeXus metadata map (mpe_xml CSV + XML)"


GROUPS = build_groups()


def select(names, mpe_xml=None):
    GROUPS["registry"] = registry_group()
    GROUPS["metadata"] = metadata_group(mpe_xml)
    if not names:
        names = list(GROUPS)
    bad = [n for n in names if n not in GROUPS]
    if bad:
        raise SystemExit(f"unknown group(s) {bad}; known: {', '.join(GROUPS)}")
    plan, seen, skipped = [], set(), []
    for n in names:
        for pv in GROUPS[n][0]:
            try:
                validate_pv(pv)                                  # whole plan is validated before anything is contacted
            except ReadOnlyViolation:
                if n in ("registry", "metadata"):                # generated groups: names outside the allow-list are skipped, never read
                    skipped.append(pv)
                    continue
                raise                                            # hand-written groups must be clean: fail loudly
            if pv not in seen:
                seen.add(pv)
                plan.append((n, pv))
    if skipped:
        print(f"note: {len(set(skipped))} generated names are outside the read-only allow-list and were skipped (not read): {sorted(set(skipped))[:6]} ...")
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", action="store_true", help="actually read from the beamline (default: only list)")
    ap.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    ap.add_argument("--group", default="", help="comma list of groups (default all); see --groups")
    ap.add_argument("--groups", action="store_true", help="list groups and exit")
    ap.add_argument("--mpe-xml", default="", help="folder with docs/*.csv and 1id_instr_attributes_trans.xml (default: S1ID/0.beamline_control/mpe_xml)")
    ap.add_argument("--backend", default="auto", choices=["auto", "pyepics", "caget"])
    ap.add_argument("--timeout", type=float, default=2.0, help="seconds per PV")
    ap.add_argument("--out", default="", help="CSV path (default pending/desc_probe_<UTC>.csv)")
    a = ap.parse_args(argv)
    if a.groups:
        select([], a.mpe_xml or None)
        for n, (pvs, why) in GROUPS.items():
            print(f"{n:9s} {len(pvs):4d} PVs  {why}")
        return 0
    plan = select([x for x in a.group.split(",") if x], a.mpe_xml or None)
    if not a.run:
        for n, pv in plan:
            print(f"{n:9s} {pv}")
        print(f"\n{len(plan)} PVs listed, NOTHING contacted (dry listing). Add --run to read them (read-only).")
        return 0
    print(f"About to READ {len(plan)} PVs from the beamline control system (channel-access GET only; no write, no motion).")
    if not a.yes and input("Type READ to continue: ").strip() != "READ":
        print("cancelled")
        return 1
    try:
        rd = Reader(a.backend, a.timeout)
    except ReaderUnavailable as e:
        raise SystemExit(str(e))
    out = Path(a.out) if a.out else ROOT / "pending" / f"desc_probe_{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["group", "pv", "status", "value", "utc"])
        for n, pv in plan:
            st, val = rd.read(pv)
            n_ok += st == "ok"
            w.writerow([n, pv, st, val, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")])
            f.flush()
            print(f"{n:9s} {pv:34s} {st:11s} {val}")
    print(f"\nbackend {rd.backend}; {n_ok}/{len(plan)} PVs answered; wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
