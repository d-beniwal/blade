"""Ground truth from the beamline's CS-Studio/Phoebus displays (.bob): extract devices/motors/PVs and check the twin + profile against them.

    python beamline_twins/tools/csdisplays.py extract [--bl 1-ID]   # parse <cs_displays>/1id/*.bob -> beamline_twins/<bl>/cs_registry.json (tracked: PV names only)
    python beamline_twins/tools/csdisplays.py check   [--bl 1-ID]   # twin + profile vs the displays; exit 1 on any ERROR (WARN/INFO are listed)
    python beamline_twins/tools/csdisplays.py show LABEL [--bl ..]  # registry record(s) whose label/twin id contains LABEL

The display folder is configuration (`cs_displays` in blade/paths.py, see `python -m blade.paths`), not part of this repo. Stdlib only.
What is read: the hutch layout screens (1ID_top_panel, 1idb/1idc/1ide_layout) - each button there opens the device panel and carries its macros
(`P`=IOC prefix, `M<n>`/`M<n>_NAME`=motor + its name, `A`/`S`/`N`=preamp/scaler/channel, `SLIT`/`mXp..`=slit and its four motors, camera `P`/`R`).
The displays are the operator's own record: where one of them contradicts another the registry keeps BOTH (`conflicts`) and the check warns."""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
TWINS = HERE.parent
sys.path.insert(0, str(TWINS.parent))
from blade import paths  # noqa: E402

# hutch -> (layout display, {bob label: [twin element ids it stands for]}); one button can stand for several twin elements (HRM = 2 crystals)
LAYOUT = {
    "A": ("1ID_top_panel.bob", {}),     # hutch A is only the button strip of the top panel (handled in TOP_A below)
    "B": ("1idb_layout.bob", {"IC1": ["icB1"], "Al CRL": ["alCRL"], "IC2": ["icB2"], "CRL": ["crlB"], "IC3": ["icB3"], "HRM": ["hrmC1", "hrmC2"],
                              "IC4": ["icB4"], "IC5": ["icB5"], "Foil": ["foilB"], "Atten": ["attenB"], "IC8": ["icB8"], "Stack1": ["stackB1", "stackB2"], "B-FS": ["fsB"], "Cork": ["cork"],
                              "KOHZU B": ["slitB"], "IC6": ["icB6"], "B-TOMO": ["tomoB"], "BL3": ["bl3"], "BL4": ["bl4"], "BL5": ["bl5"], "IC7": ["icB7"]}),
    "C": ("1idc_layout.bob", {"IC1": ["icC1"], "IC2": ["icC2"], "Slit 1": ["slitCus"], "fourc": ["fourC"], "IC3": ["icC3"], "L1": ["lens1C"], "L2": ["lens2C"],
                              "L3": ["lens3C"], "L4": ["lens4C"], "L5(RD)": ["lens5C"], "L6(RD)": ["lens6C"], "AttenC": ["attenC"], "Slit 2": ["slitCds"],
                              "IC4": ["icC4"], "LabMotion SMS": ["samC"], "DBA": ["dba"], "Tomo D1": ["tomoC"], "Stop": ["stopC"], "Shield": ["shieldC"],
                              "Varex D2": ["d2C"], "Lens7": ["lens7C"]}),
    "E": ("1ide_layout.bob", {"IC1+2": ["icE12"], "Slit US": ["slitEus"], "IC3": ["icE3"], "FS": ["fsE"], "Lens1": ["lens1E"], "Lens2": ["lens2E"],
                              "Lens3": ["lens3E"], "Lens4": ["lens4E"], "Slit DS": ["slitEds"], "IC4": ["icE4"], "Aero SMS": ["samE"], "HL-SMS": ["hl_sms"],
                              "Tomo D1": ["tomoE"], "NF D2": ["d2E"], "IC5": ["icE5"], "D3": ["d3"], "IC6": ["icE6"], "Hydra D4": ["hydra"], "VFF D5": ["vff"],
                              "Radiography": ["radiograph"], "IC8": ["icE8"], "SAXS D6": ["saxs"]}),
}
TOP_A = {"Filter": "filterA", "Slits": "wbSlits"}      # top-panel buttons that belong to hutch A (labels sit above the buttons; matched by title macro)
# lines of the layouts that are controls, not beam elements (kept in the registry as `aux`)
AUX = {"IOCs", "Preamps", "Scaler", "Keyence", "Temperature", "Furnace", "SoftGlue", "Tilt-Sensor", "Keithely", "Shutter & Atten", "Det Writer", "User_Setup",
       "CAM-1", "CAM-5", "CAM-7", "CAM-9", "Shutter", "Aero_Trans", "IC1+2 trans", "Labmotion", "On", "Off"}


# Disagreements between the displays and other records that were looked at by hand (2026-11-13); kept, never resolved by guessing.
KNOWN_CONFLICTS = [
    {"what": "fast shutter E: display labels FS_X = 1ide1:m75, FS_Y = 1ide1:m77; log-panel motor descriptions 'FS2X E' = m77, 'FS2Y E' = m75 and mpe_bluesky x_pv m77 / y_pv m75",
     "kept": "m77 = x, m75 = y (descriptions + code)"},
    {"what": "LabMotion SMS (C): display labels m25 samZ, m27 samX; log-panel descriptions samXC = m25, samZC = m27 and mpe_bluesky x = m25, z = m27",
     "kept": "x = m25, z = m27 (descriptions + code); y = m26 on display and logs (mpe_bluesky says 1idGalil1:m1)"},
    {"what": "1idc:m31: display label LabMotion_TransX / Trans_X, log-panel description 'rotXC'", "kept": "role left open"},
    {"what": "Hydra D4 z: display opens P=1idc: M=m7 (Hydra_D4); mpe_bluesky has 1ide1:m7; not seen on the log panels", "kept": "1idc:m7 (display; explicit PV)"},
    {"what": "d2E in mpe_bluesky (P=1ide1:, x m103, z m50, shield m47) uses the D3 'GE_X/GE_Z in E' stage and the Tomo D1 shielding motor, not the NF D2 axes", "kept": "twin follows the display"},
]


def _macros(el):
    m = el.find("macros")
    return {c.tag: (c.text or "") for c in m} if m is not None else {}


def _clean(s):
    return (s or "").strip()


def _resolve(mc):
    """Expand $(NAME) references between macro values (e.g. M1='$(P2)m8' with P2='1idcAMCI:')."""
    out = dict(mc)
    for _ in range(3):
        out = {k: re.sub(r"\$\((\w+)\)", lambda m: out.get(m.group(1), m.group(0)), v) for k, v in out.items()}
    return out


def _device(file, mc):
    """One display panel opened by a button -> a compact device record."""
    mc = _resolve(mc)
    f = file.split("/")[-1]
    P = mc.get("P", "")
    d = {"panel": f}
    if P:
        d["P"] = P
    if "T" in mc:
        d["title"] = mc["T"]
    motors = []
    for k, v in mc.items():
        m = re.fullmatch(r"M(\d+)", k)
        if not m or "$" in v:
            continue
        n = m.group(1)
        pre = mc.get("P" + n, P)
        pre = P if pre in ("$(P)", "") else pre
        v = v.rstrip(":")
        if v and not v.startswith("sm") and "?" not in v:
            motors.append({"pv": f"{pre}{v}", "name": _clean(mc.get(f"M{n}_NAME")) or None})
    if "M" in mc and "$" not in mc["M"] and mc["M"].startswith("m"):
        motors.append({"pv": f"{P}{mc['M'].rstrip(':')}", "name": mc.get("T")})
    if motors:
        d["motors"] = sorted(motors, key=lambda x: (re.sub(r"\D", "", x["pv"].split(":")[-1]) or "0").zfill(4))
    if re.search(r"slit", f, re.I) and "SLIT" in mc:
        h = mc.get("H", "").replace("$(SLIT)", mc["SLIT"])
        d["slit"] = {"name": mc["SLIT"], "pv": f"{P}{h[:-1] if h.endswith('H') else mc['SLIT']}", "h": h, "v": mc.get("V", "").replace("$(SLIT)", mc["SLIT"])}
        mm = {k: f"{P}{mc[k]}" for k in ("mXp", "mXn", "mYp", "mYn") if k in mc}
        if mm:
            d["slit"]["motors"] = mm
    if re.search(r"SR570", f) and "A" in mc and "N" in mc:
        sp = mc.get("PS") or P
        d["ic"] = {"preamp": f"{P}{mc['A']}", "scaler": f"{sp}{mc.get('S', '')}", "channel": int(mc["N"]),
                   "counts_pv": f"{sp}{mc.get('S', '')}.S{mc['N']}"}
    if re.search(r"ADSpinnaker|pointGrey|PerkinElmer|ADEPT|pilatus|eiger", f, re.I) or ("R" in mc and P and "cam" in mc.get("R", "")):
        d["camera"] = {"prefix": P, "driver": f.replace(".bob", ""), "model": mc.get("C")}
    if "PD" in mc:
        d["camera_prefix"] = mc["PD"]
    return d


def parse_layout(path):
    """[(x, label, [device records])] of the action buttons of one layout display, left to right (inner group offsets ignored: layouts are flat)."""
    r = ET.parse(path).getroot()
    out = []
    for w in r.iter("widget"):
        if w.get("type") != "action_button":
            continue
        label = _clean(w.findtext("text"))
        devs = []
        for a in w.iter("action"):
            f = _clean(a.findtext("file"))
            if f.endswith(".bob") and "1id_IOC" not in f:
                devs.append(_device(f, _macros(a)))
            elif a.findtext("command"):
                pass
        if devs or label:
            out.append((int(_clean(w.findtext("x")) or 0), label, devs))
    return sorted(out, key=lambda t: t[0])


def parse_top(path):
    """Top panel (A..E buttons). Returns {hutch letter: [(label, devs)]} using the hutch letters printed above the button groups (x ranges)."""
    r = ET.parse(path).getroot()
    letters = sorted((int(_clean(w.findtext("x"))), _clean(w.findtext("text"))) for w in r.iter("widget")
                     if w.get("type") == "label" and _clean(w.findtext("text")) in ("A", "B", "C", "E"))
    res = {h: [] for _, h in letters}
    for x, label, devs in parse_layout(path):
        h = None
        for lx, L in letters:
            if x >= lx - 40:
                h = L
        if h:
            res[h].append((x, label, devs))
    return res


def extract(bl="1-ID"):
    root = paths.knowledge_dir("cs_displays", bl)
    d1 = root / "1id"
    if not d1.is_dir():
        sys.exit(f"CS-Studio displays not found at {d1} - set the 'cs_displays' path (python -m blade.paths)")
    reg = {"schema": 1, "beamline": bl, "source": "CS-Studio/Phoebus .bob displays (1id/*.bob), parsed by beamline_twins/tools/csdisplays.py",
           "display_dates": {}, "elements": {}, "aux": {}, "slits": {}, "cameras": {}, "conflicts": []}
    for f in ("1ID_MAIN.bob", "1idb_layout.bob", "1idc_layout.bob", "1ide_layout.bob"):
        t = (d1 / f).read_text(errors="ignore")
        m = re.search(r"Last update:?\s*([0-9\-]+)", t)
        if m:
            reg["display_dates"][f] = m.group(1)
    top = parse_top(d1 / "1ID_top_panel.bob")
    occ_total, occ_seen = {}, {}
    for h, (lay, alias) in LAYOUT.items():
        if h != "A":
            for _x, lab, _d in parse_layout(d1 / lay):
                occ_total.setdefault(h, {})[lab] = occ_total.get(h, {}).get(lab, 0) + 1
    for h, (lay, alias) in LAYOUT.items():
        if h == "A":
            continue
        for x, label, devs in parse_layout(d1 / lay):
            if label in AUX:
                reg["aux"].setdefault(h, {})[label] = devs
                continue
            ids = alias.get(label)
            if ids and label in occ_total.get(h, {}) and occ_total[h][label] > 1 and occ_total[h][label] == len(ids):   # repeated label: k-th button = k-th id
                occ_seen[(h, label)] = occ_seen.get((h, label), 0) + 1
                ids = [ids[occ_seen[(h, label)] - 1]]
            if not ids:
                if devs:
                    reg["aux"].setdefault(h, {})[label or f"x{x}"] = devs
                continue
            for i in ids:
                reg["elements"][i] = {"hutch": h, "label": label, "x": x, "devices": devs}
    # ICs shown only as a scaler read-out text box sit next to their SR570 button, nothing more to do.
    # A: filter + WB slits + HEM from the top panel
    for x, label, devs in top.get("A", []):
        if any(d["panel"].startswith("2filter") for d in devs):
            reg["elements"]["filterA"] = {"hutch": "A", "label": "Filter", "x": x, "devices": devs}
        if any(d.get("slit") for d in devs) and "WB" in json.dumps(devs):
            reg["elements"]["wbSlits"] = {"hutch": "A", "label": "WB Slits", "x": x, "devices": devs}
        if label == "HE Mono":
            reg["elements"]["hem"] = {"hutch": "A", "label": "HE Mono", "x": x, "devices": devs}
    # the six slits: every record found anywhere, keyed by slit PV; slit motors from the top panel (4slitGraphic macros), conflicts recorded
    seen = {}
    for lay in ("1ID_top_panel.bob", "1idb_layout.bob", "1idc_layout.bob", "1ide_layout.bob"):
        for x, label, devs in (parse_layout(d1 / lay)):
            for dv in devs:
                if "slit" in dv:
                    s = dv["slit"]
                    seen.setdefault(f"{dv['P']}{s['h'][:-1] if s['h'].endswith('H') else s['name']}", []).append((lay, s.get("motors")))
    for key, recs in sorted(seen.items()):
        ms = [m for _, m in recs if m]
        reg["slits"][key] = {"motors": ms[0] if ms else None, "from": [l for l, m in recs if m][:1]}
    # test_slits panels list the four motors without roles: use them to cross-check the motor SET
    for h, (lay, _a) in LAYOUT.items():
        if h == "A":
            continue
        for x, label, devs in parse_layout(d1 / lay):
            for dv in devs:
                if dv["panel"] == "test_slits.bob" and "motors" in dv:
                    sname = next((d["slit"]["name"] for d in devs if "slit" in d), None)
                    pvs = {m["pv"] for m in dv["motors"]}
                    sd = next((d["slit"] for d in devs if "slit" in d), None)
                    top_s = reg["slits"].get(f"{dv['P']}{sd['h'][:-1] if sd and sd['h'].endswith('H') else sname}") if sd else None
                    if top_s and top_s["motors"] and pvs != set(top_s["motors"].values()):
                        reg["conflicts"].append({"what": f"slit {dv['P']}{sname}: motor set differs between panels",
                                                 "test_slits": sorted(pvs), "4slitGraphic": sorted(top_s["motors"].values()),
                                                 "files": [lay, "1ID_top_panel.bob"]})
    reg["conflicts"] += KNOWN_CONFLICTS
    # cameras seen anywhere (prefix -> model/driver, with the elements that open them)
    for i, e in reg["elements"].items():
        for dv in e["devices"]:
            c = dv.get("camera")
            if c and c["prefix"]:
                reg["cameras"].setdefault(c["prefix"], {"driver": c["driver"], "model": c["model"], "elements": []})
                if i not in reg["cameras"][c["prefix"]]["elements"]:
                    reg["cameras"][c["prefix"]]["elements"].append(i)
    # IOC control tabs
    reg["ioc_control"] = ioc_panel(d1 / "1id_IOC.bob")
    out = TWINS / bl / "cs_registry.json"
    out.write_text(json.dumps(reg, indent=1, sort_keys=False) + "\n")
    print(f"wrote {out.relative_to(TWINS.parent)}: {len(reg['elements'])} elements, {len(reg['slits'])} slits, {len(reg['cameras'])} cameras, "
          f"{sum(len(v) for v in reg['aux'].values())} aux, {len(reg['conflicts'])} conflicts")


def ioc_panel(path):
    r = ET.parse(path).getroot()
    tabs = {}
    for tab in r.iter("tab"):
        name = _clean(tab.findtext("name"))
        rows = []
        for w in tab.iter("widget"):
            mc = _macros(w)
            if mc.get("NAME") or mc.get("P"):
                rows.append({"name": mc.get("NAME"), "prefix": mc.get("P") or None, "title": mc.get("T"), "model": mc.get("C"), "viewer": mc.get("PATH_CSS") or None})
        if rows:
            tabs[name] = rows
    return tabs


# ----------------------------------------------------------------------------------------------------------------------------------- check
def _flat_motors(rec):
    out = {}
    for dv in rec["devices"]:
        for m in dv.get("motors", []):
            out[m["pv"]] = m["name"]
    return out


def check(bl="1-ID"):
    import twin as T  # noqa: E402 (same folder)
    reg = json.loads((TWINS / bl / "cs_registry.json").read_text())
    t = T.load(bl)
    errs, warns, info = [], [], []
    E = {e["id"]: e for e in t["path"]}
    # 1. every mapped element exists in the twin, and the order along the beam per hutch is the display order
    for i in reg["elements"]:
        if i not in E:
            errs.append(f"registry element '{i}' (display label '{reg['elements'][i]['label']}') is not in the twin")
    for h, (lay, alias) in LAYOUT.items():
        if h == "A":
            continue
        recs = sorted(((r["x"], i) for i, r in reg["elements"].items() if r["hutch"] == h), key=lambda z: z[0])
        want, seen_x = [], set()
        for x, i in recs:
            if (x, reg["elements"][i]["label"]) not in seen_x:        # one button = one entry (HRM = 2 crystals)
                seen_x.add((x, reg["elements"][i]["label"])); want.append(i)
        have = [e["id"] for e in t["path"] if e["id"] in set(want) and e.get("placement") != "alt"]
        want = [i for i in want if E[i].get("placement") != "alt"]
        if want != have:
            errs.append(f"hutch {h}: order along the beam differs. display: {want}  twin: {have}")
        missing = [e["id"] for e in t["path"] if e.get("hutch") == h and e["id"] not in reg["elements"] and e["kind"] != "unknown"]
        if missing:
            info.append(f"hutch {h}: twin elements with no button on the display (fine for items drawn but not clickable): {missing}")
        d1 = paths.knowledge_dir("cs_displays", bl) / "1id"
        unmapped = [lab for _, lab, devs in parse_layout(d1 / lay) if lab and lab not in alias and lab not in AUX] if d1.is_dir() else []   # needs the displays; the rest only the registry
        if unmapped:
            warns.append(f"hutch {h}: display buttons not mapped to a twin element: {unmapped}")
    # 2. twin controls / pv versus the display motors and prefixes
    for i, e in E.items():
        rec = reg["elements"].get(i)
        if not rec:
            continue
        mot = _flat_motors(rec)
        for k, pv in (e.get("controls") or {}).items():
            if isinstance(pv, str) and re.fullmatch(r"\w+:m\d+", pv) and mot and pv not in mot:
                warns.append(f"{i}: controls.{k} = {pv} is not among the display motors {sorted(mot)}")
        for pv in [e.get("pv")] if e.get("pv") else []:
            pre = [dv.get("P") for dv in rec["devices"] if dv.get("P")]
            sl = [dv["slit"]["pv"] for dv in rec["devices"] if "slit" in dv]
            if sl and pv not in sl:
                errs.append(f"{i}: slit pv {pv} != display slit PV {sl}")
    # 3. IC read-out
    for i, rec in reg["elements"].items():
        for dv in rec["devices"]:
            ic = dv.get("ic")
            if ic and i in E and not (E[i].get("readout") or (E[i].get("cs") or {}).get("ic")):
                info.append(f"{i}: twin has no IC read-out channel yet; display says {ic['counts_pv']} (preamp {ic['preamp']})")
    # 4. sample stage assembly vs the Aero stacks
    asm = t["assemblies"].get("samE")
    if asm:
        mot = {}
        for rec_id in ("samE",):
            mot.update(_flat_motors(reg["elements"][rec_id]))
        for lv in asm["stack_top_to_bottom"]:
            pv = lv.get("motor")
            if pv and pv not in mot and pv not in ("1ide1:m101", "1ide1:m102"):
                errs.append(f"samE assembly level {lv['level']} '{lv['name']}' motor {pv} is not on the Aero_SMS display ({sorted(mot)})")
            elif pv in mot:
                info.append(f"samE level {lv['level']} {pv}: display name '{mot[pv]}' vs twin '{lv['name']}' / {lv.get('device')}")
        for pv, name in (("1ide1:m101", "Aero_X"), ("1ide1:m102", "Aero_Z")):
            if not any(lv.get("motor") == pv for lv in asm["stack_top_to_bottom"]):
                errs.append(f"samE assembly lacks {pv} ({name})")
    # 5. profile
    prof = json.loads((TWINS.parent / "profiles" / "s1id" / "default_config.json").read_text())
    st = prof["stations"]["E"]
    mot = _flat_motors(reg["elements"]["samE"])
    aero_trans = {"1ide1:m101": "Aero_X", "1ide1:m102": "Aero_Z"}
    for role, m in st["motors"].items():
        if m["pv"] not in mot and m["pv"] not in aero_trans:
            errs.append(f"profile s1id station E motor {role} {m['pv']} is not on the Aero displays")
        else:
            info.append(f"profile motor {role} {m['pv']} -> display name '{mot.get(m['pv']) or aero_trans.get(m['pv'])}' (profile name {m['name']})")
    cams = reg["cameras"]
    ioc = {r["prefix"]: r for rows in reg["ioc_control"].values() for r in rows if r["prefix"]}
    for name, c in prof["cameras"].items():
        p = c.get("pv_prefix")
        if p is None:
            warns.append(f"profile camera {name} (hutch {c['hutch']}) has no pv_prefix")
        elif p not in cams and p not in ioc:
            errs.append(f"profile camera {name}: prefix {p} appears neither on a layout nor in the IOC control panel")
    # 6. detector IOC table of the twin vs the IOC panel and the layouts
    for it in t["beamline"]["detector_iocs"]["items"]:
        p = it.get("prefix")
        if p and p not in ioc and p not in cams:
            warns.append(f"detector_iocs {it['camera']}: prefix {p} is not in the display IOC list")
        if p in cams and it.get("element") is None:
            warns.append(f"detector_iocs {it['camera']} ({p}) is opened from element(s) {cams[p]['elements']} on the displays but is unassigned in the twin")
        if p in cams and it.get("element") and it["element"] not in cams[p]["elements"] and it["element"] not in ("hydra", "d3"):
            errs.append(f"detector_iocs {it['camera']} ({p}) is assigned to {it['element']} but the displays open it from {cams[p]['elements']}")
    for c in reg["conflicts"]:
        extra = f"  {c['test_slits']} vs {c['4slitGraphic']}" if "test_slits" in c else (f"  -> kept: {c['kept']}" if "kept" in c else "")
        warns.append("display conflict: " + c["what"] + extra)
    for s in info:
        print("INFO ", s)
    for s in warns:
        print("WARN ", s)
    for s in errs:
        print("ERROR", s)
    print(f"{len(errs)} errors, {len(warns)} warnings, {len(info)} info")
    return 1 if errs else 0


def show(bl, needle):
    reg = json.loads((TWINS / bl / "cs_registry.json").read_text())
    for i, e in reg["elements"].items():
        if needle.lower() in i.lower() or needle.lower() in e["label"].lower():
            print(i, json.dumps(e, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["extract", "check", "show"])
    ap.add_argument("label", nargs="?")
    ap.add_argument("--bl", default="1-ID")
    a = ap.parse_args()
    if a.cmd == "extract":
        extract(a.bl)
    elif a.cmd == "check":
        sys.exit(check(a.bl))
    else:
        show(a.bl, a.label or "")
