"""Per-element PV map for the twin viewer: every PV/control/readback the CS-Studio displays expose for each twin element.

    python beamline_twins/tools/pvmap.py build [--bl 1-ID]   # cs_registry.json + the display templates -> beamline_twins/<bl>/pv_map.json
    python beamline_twins/tools/pvmap.py show ID [--bl ..]   # print the map of one twin element

Source = the operator displays only (the registry made by csdisplays.py, plus the PV field lists that the device panels - motorx.bob, SR570.bob,
scaler32_full_calc.bob, 4slitGraphic.bob - actually bind). Nothing is guessed and nothing is read from hardware. Field names are those the panels use;
`access` is the usual direction for that EPICS field (read = monitored, write = setpoint/command), not something checked on the live IOC.
The result is generated (re-run after `csdisplays.py extract`); the twin viewer attaches it to each element as `pvmap`. Stdlib only."""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TWINS = HERE.parent
sys.path.insert(0, str(TWINS.parent))
from blade import paths  # noqa: E402

# panel file (relative to the display folder) -> (macro whose fields we list, template name)
TEMPLATE_SRC = {"motor": ("motors/motorx.bob", "M"), "preamp": ("ip/SR570.bob", "A"), "scaler": ("scaler/scaler32_full_calc.bob", "S")}
SLIT_SRC = "optics/4slitGraphic.bob"
READ = {".RBV", ".DMOV", ".HLM", ".LLM", ".HLS", ".LLS", ".LVIO", ".STAT", ".DESC", ".T", ".VELO"}     # usually monitored
LABEL = {".VAL": "setpoint", ".RBV": "readback", ".DMOV": "done moving", ".HLM": "high limit", ".LLM": "low limit", ".HLS": "high limit switch",
         ".LLS": "low limit switch", ".LVIO": "soft-limit violation", ".STOP": "stop", ".SET": "set/use mode", ".SYNC": "sync setpoint to readback",
         ".TWF": "tweak forward", ".TWR": "tweak reverse", ".TWV": "tweak step", ".VELO": "velocity", ".DESC": "description", ".STAT": "alarm status",
         "_able.VAL": "enable/disable", ".CNT": "start/stop counting", ".TP": "count time (s)", ".T": "elapsed time (s)", ".TP1": "preset time (internal)",
         "sens_num.VAL": "sensitivity number", "sens_unit.VAL": "sensitivity unit", "gain_mode.VAL": "gain mode", "low_freq.VAL": "low-pass/high-pass low freq",
         "high_freq.VAL": "filter high freq", "filter_type.VAL": "filter type", "invert_on.VAL": "invert input", "blank_on.VAL": "blank input",
         "offset_on.VAL": "input offset on", "offset_num.VAL": "input offset number", "offset_unit.VAL": "input offset unit", "offset_sign.VAL": "input offset sign",
         "bias_on.VAL": "bias on", "bias_put.VAL": "bias voltage", "init.PROC": "initialise preamp", "reset.PROC": "reset preamp"}


def _fields(bob, macro):
    """Sorted unique PV tails bound to $(P)$(<macro>) in one panel, e.g. ['.DMOV', '.RBV', ...]."""
    txt = Path(bob).read_text(errors="replace")
    tails = set(re.findall(r"<pv_name>\$\(P\)\$\(%s\)([^<$]*)</pv_name>" % macro, txt))
    return sorted(t for t in tails if t)


def templates(bl="1-ID"):
    base = paths.knowledge_dir("cs_displays", bl)
    out = {}
    for name, (rel, macro) in TEMPLATE_SRC.items():
        out[name] = {"source": rel, "fields": _fields(base / rel, macro)}
    sc = out["scaler"]["fields"]
    out["scaler"]["fields"] = [f for f in sc if not re.fullmatch(r"\.S\d+", f) and not f.startswith("_calc") and f in (".CNT", ".T", ".TP")]
    # preamp: keep the ones that carry a user-meaningful setting
    out["preamp"]["fields"] = [f for f in out["preamp"]["fields"] if not re.search(r"tweak|inc|dec|put$|cal|u_", f) or f in ("bias_put.VAL",)]
    txt = (base / SLIT_SRC).read_text(errors="replace")
    sl = sorted(set(re.findall(r"<pv_name>\$\(P\)\$\(H\)([A-Za-z]+\.[A-Z]+)</pv_name>", txt)))
    out["slit_axis"] = {"source": SLIT_SRC, "fields": [f for f in sl if not re.search(r"tweak|t2|DRV|CoordSys", f)]}
    for t in out.values():
        t["fields"] = _meta(t["fields"])
    return out


def _acc(tail):
    return "read" if tail in READ else "write"


def _meta(fields):
    return [{"field": f, "what": LABEL.get(f, ""), "access": _acc(f)} for f in fields]


def build_element(el, tpl):
    groups = []
    for d in el["devices"]:
        panel = d.get("panel")
        if d.get("ic"):
            ic = d["ic"]
            groups.append({"type": "ic_readout", "title": f"Ion chamber read-out ({d.get('title') or panel})", "panel": panel,
                           "readback": {"pv": ic["counts_pv"], "what": f"counts, scaler channel {ic['channel']}", "access": "read"},
                           "scaler": {"record": ic["scaler"], "channel": ic["channel"]}, "preamp": {"record": ic["preamp"]}})
        if d.get("motors"):
            groups.append({"type": "motors", "title": f"Motors ({d.get('title') or panel})", "panel": panel,
                           "motors": [{"pv": m["pv"], "name": m.get("name")} for m in d["motors"]]})
        if d.get("slit"):
            s = d["slit"]
            ax = {}
            for axis, mac in (("horizontal", s.get("h")), ("vertical", s.get("v"))):
                if mac:
                    ax[axis] = {"record": d["P"] + mac}
            groups.append({"type": "slit", "title": f"Slit software axes ({d.get('title') or panel})", "panel": panel, "name": s.get("name"), "axes": ax,
                           "blade_motors": s.get("motors") or {}})
        if d.get("camera"):
            c = d["camera"]
            groups.append({"type": "camera", "title": f"Camera / detector IOC ({d.get('title') or panel})", "panel": panel, "prefix": c["prefix"],
                           "driver": c["driver"], "model": c.get("model"),
                           "note": "Full parameter list is in the driver panel above; it is not enumerated here."})
        if not any(k in d for k in ("ic", "motors", "slit", "camera")):
            groups.append({"type": "panel", "title": f"Panel {panel}", "panel": panel, "P": d.get("P"),
                           "note": "Opens a control panel; the layout button gives only its IOC prefix, no individual PVs were extracted."})
    return groups


def _top(pairs):
    """Most frequent value of a [[value, count], ...] list (None when empty)."""
    return max(pairs, key=lambda p: p[1])[0] if pairs else None


def registry_index(bl):
    """PV -> what the logbook panel screenshots say about it (panel_registry.json; tier-A statistics only).
    linked[pv]   = the ONE device label whose window title printed that PV (rule of the registry: >=3 images, >=90 % share, not claimed twice)
    cands[pv]    = device labels that merely list the PV among several candidates (ambiguous: never used as a name)."""
    f = TWINS / bl / "panel_registry.json"
    if not f.is_file():
        return {}, {}
    pr = json.loads(f.read_text())
    linked, cands = {}, {}
    for key, v in pr.items():
        if re.search(r"readback", key):
            continue
        if v.get("pv_status") == "visible_on_screen" and v.get("pv"):
            linked.setdefault(v["pv"], []).append((key, v))
        for c in v.get("pv_candidates") or []:
            if v.get("pv_status") != "visible_on_screen":
                cands.setdefault(c["pv"], []).append(v.get("display") or key)
    return linked, cands


def _log_info(entries):
    """Merge the registry entries of one PV; if they disagree on the device label (e.g. 'B24 L4B Th (Rx)' and 'B24 L4B Th' = the same title read twice) keep the longest."""
    key, v = max(entries, key=lambda kv: len(kv[1].get("display") or ""))
    units = v.get("units") or {}
    u = max(units, key=units.get) if units else None
    lim = v.get("limits") or {}
    out = {"log_label": v.get("display"), "log_images": v.get("n_images"), "log_first": v.get("first"), "log_last": v.get("last")}
    if u:
        out["units"] = "deg" if u in ("degrees", "o") else u
    if v.get("tweak_step", {}).get("modal"):
        out["step"] = _top(v["tweak_step"]["modal"])
    if lim.get("hi_user") and lim.get("lo_user"):
        out["limits"] = {"lo": _top(lim["lo_user"]), "hi": _top(lim["hi_user"]), "frame": "user"}
    return out


BLADE_ROLE = {"mXp": "X+ blade", "mXn": "X- blade", "mYp": "Y+ blade", "mYn": "Y- blade"}


def slit_roles(bl):
    """motor PV -> 'X+ blade (slit 1idc:Kslitus)': from the slit software records the operator top panel binds (cs_registry 'slits')."""
    cs = json.loads((TWINS / bl / "cs_registry.json").read_text())
    return {pv: f"{BLADE_ROLE[k]} (slit {rec})" for rec, d in cs.get("slits", {}).items() for k, pv in d["motors"].items() if k in BLADE_ROLE}


def enrich(elements, bl):
    """Add to every motor: log label / units / tweak step / soft limits (from the log panels, tier A), `shared_with` (other twin elements whose
    display button drives the same PV) and, for PVs that stay unlabelled, `candidates` (ambiguous log labels, never assigned)."""
    linked, cands = registry_index(bl)
    roles = slit_roles(bl)
    users = {}
    for eid, el in elements.items():
        for g in el["groups"]:
            for m in g.get("motors") or []:
                users.setdefault(m["pv"], set()).add(eid)
            for pv in (g.get("blade_motors") or {}).values():
                users.setdefault(pv, set()).add(eid)
    n_lab = 0
    for eid, el in elements.items():
        for g in el["groups"]:
            for m in g.get("motors") or []:
                if m["pv"] in linked:
                    m.update(_log_info(linked[m["pv"]]))
                elif m["pv"] in cands:
                    m["candidates"] = sorted(set(cands[m["pv"]]))
                if m["pv"] in roles:
                    m["role"] = roles[m["pv"]]
                others = sorted(users[m["pv"]] - {eid})
                if others:
                    m["shared_with"] = others
                n_lab += bool(m.get("name") or m.get("log_label"))
    return n_lab


def build(bl="1-ID"):
    reg = json.loads((TWINS / bl / "cs_registry.json").read_text())
    tpl = templates(bl)
    out = {"schema": 2, "beamline": bl, "source": "cs_registry.json + CS-Studio device panels + panel_registry.json (tier-A log-panel labels/limits; see tools/pvmap.py)", "templates": tpl,
           "elements": {eid: {"label": el.get("label"), "groups": build_element(el, tpl)} for eid, el in reg["elements"].items()}}
    enrich(out["elements"], bl)
    (TWINS / bl / "pv_map.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def report(bl="1-ID"):
    """Motors by label status: what is resolved and what stays open (with candidates)."""
    o = json.loads((TWINS / bl / "pv_map.json").read_text())
    seen, rows = set(), []
    for eid, el in o["elements"].items():
        for g in el["groups"]:
            for m in g.get("motors") or []:
                if m["pv"] in seen:
                    continue
                seen.add(m["pv"])
                how = "display" if m.get("name") else "log panel" if m.get("log_label") else "slit blade" if m.get("role") else "ambiguous" if m.get("candidates") else "unlabelled"
                rows.append((how, eid, m["pv"], m.get("name") or m.get("log_label") or ", ".join(m.get("candidates") or [])))
    from collections import Counter
    print(Counter(r[0] for r in rows))
    for r in sorted(rows):
        if r[0] in ("ambiguous", "unlabelled"):
            print(*r, sep=" | ")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("build", "show", "report"))
    ap.add_argument("id", nargs="?")
    ap.add_argument("--bl", default="1-ID")
    a = ap.parse_args()
    if a.cmd == "build":
        o = build(a.bl)
        print(f"wrote {TWINS / a.bl / 'pv_map.json'}: {len(o['elements'])} elements")
    elif a.cmd == "report":
        report(a.bl)
    else:
        o = json.loads((TWINS / a.bl / "pv_map.json").read_text())
        print(json.dumps(o["elements"].get(a.id), indent=1))


if __name__ == "__main__":
    main()
