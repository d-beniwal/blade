#!/usr/bin/env python3
"""Load, validate and render a beamline twin (stdlib only).

    python beamline_twins/tools/twin.py check  1-ID          # validate; exit 1 on errors
    python beamline_twins/tools/twin.py render 1-ID          # write 1-ID/layout.md (generated, do not edit)
    python beamline_twins/tools/twin.py show   1-ID [--kind slit] [--hutch E]

Programmatic use (e.g. a future simulator):  from twin import load; t = load("1-ID"); t["path"]  # elements in beam order
Schema and conventions: beamline_twins/README.md
"""
import argparse
import json
import sys
from pathlib import Path

TWINS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TWINS.parent))
from blade import paths  # noqa: E402   (photos live in the knowledge tree, see blade/paths.py)


def photos_dir(bl):
    """Folder holding the reference photos / screenshots of twin `bl` (knowledge tree, NOT the repo)."""
    return paths.knowledge_dir("twin_photos", bl)


KINDS = {"source", "shutter", "fast_shutter", "slit", "ic", "crl", "lens", "mono", "foil", "attenuator", "stage",
         "sample_stage", "sample_holder", "detector", "beamstop", "unknown"}
CONF = ("confirmed", "seen", "code", "inferred", "unseen")      # strongest to weakest
PLACEMENT = {"in_line", "retractable", "alt"}
SIDE = {"above", "below"}
REQUIRED = ("id", "name", "kind", "conf")


def _no_dups(pairs):
    keys = [k for k, _ in pairs]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise ValueError(f"duplicate JSON key(s) {dup} (the later one would silently win)")
    return dict(pairs)


def load(beamline, base=None):
    """Return {'beamline', 'hutches', 'path', 'assemblies', 'photos', 'dir'}. 'path' = every element in beam order (hutch order, then list order)."""
    d = Path(base or TWINS) / beamline
    rd = lambda p: json.loads(p.read_text(), object_pairs_hook=_no_dups)
    bl = rd(d / "beamline.json")
    hutches = {h: rd(d / "hutches" / f"{h}.json") for h in bl["hutch_order"] if (d / "hutches" / f"{h}.json").exists()}
    path = []
    for h in bl["hutch_order"]:
        for el in hutches.get(h, {}).get("elements", []):
            path.append({**el, "hutch": h, "index": len(path)})
    assemblies = {p.stem: rd(p) for p in sorted((d / "assemblies").glob("*.json"))}
    photos = {p["id"]: p for p in rd(d / "sources" / "photos.json")["photos"]}
    reg = d / "cs_registry.json"          # facts read from the CS-Studio displays (csdisplays.py extract): motors, IC channels, camera prefixes
    if reg.is_file():
        cs = rd(reg).get("elements", {})
        for e in path:
            if e["id"] in cs:
                e["cs"] = cs[e["id"]]
    return {"beamline": bl, "hutches": hutches, "path": path, "assemblies": assemblies, "photos": photos, "dir": d}


def check(t):
    errs, warns = [], []
    bl, ids, photos = t["beamline"], {}, t["photos"]
    for h in bl["hutch_order"]:
        if h not in t["hutches"]:
            errs.append(f"hutch file missing: hutches/{h}.json")
    for el in t["path"]:
        where = f"{el['hutch']}/{el.get('id', '?')}"
        for k in REQUIRED:
            if k not in el:
                errs.append(f"{where}: missing '{k}'")
        if el.get("id") in ids:
            errs.append(f"{where}: duplicate id (also in hutch {ids[el['id']]})")
        ids[el.get("id")] = el["hutch"]
        if el.get("kind") not in KINDS:
            errs.append(f"{where}: kind '{el.get('kind')}' not in {sorted(KINDS)}")
        if el.get("conf") not in CONF:
            errs.append(f"{where}: conf '{el.get('conf')}' not in {CONF}")
        if el.get("placement", "in_line") not in PLACEMENT:
            errs.append(f"{where}: placement '{el.get('placement')}' not in {sorted(PLACEMENT)}")
        if el.get("side", "above") not in SIDE:
            errs.append(f"{where}: side '{el.get('side')}' not in {sorted(SIDE)}")
        if el.get("conf") in ("seen", "confirmed") and not el.get("src") and not el.get("user"):
            errs.append(f"{where}: conf '{el['conf']}' needs a 'src' photo id (or a 'user' statement with its date)")
        for p in el.get("src", []):
            if p not in photos:
                errs.append(f"{where}: unknown photo id '{p}'")
            elif el.get("id") not in photos[p].get("elements", []) and p not in ("p11",):
                warns.append(f"{where}: cites {p} but photos.json[{p}].elements does not list it")
        if el.get("assembly") and el["assembly"] not in t["assemblies"]:
            errs.append(f"{where}: unknown assembly '{el['assembly']}'")
    for el in t["path"]:
        w = f"{el['hutch']}/{el['id']}"
        gids = {g["id"] for g in t["hutches"][el["hutch"]].get("groups", [])}
        if el.get("group") and el["group"] not in gids:
            errs.append(f"{w}: group '{el['group']}' not declared in hutches/{el['hutch']}.json 'groups'")
        if "panel_x" in el and (not isinstance(el["panel_x"], (int, float)) or isinstance(el["panel_x"], bool)):
            errs.append(f"{w}: panel_x must be a number (pixel along the beam line on the operator-panel screenshot)")
        if el.get("panel_x") is not None and not t["hutches"][el["hutch"]].get("panel"):
            errs.append(f"{w}: panel_x given but the hutch file has no 'panel' (source screenshot + width)")
    for h, hd in t["hutches"].items():
        if hd.get("panel") and hd["panel"].get("src") not in photos:
            errs.append(f"hutches/{h}.json: panel.src '{hd['panel'].get('src')}' is not in photos.json")
    for el in t["path"]:
        if el.get("near") and el["near"] not in ids:
            errs.append(f"{el['hutch']}/{el['id']}: near '{el['near']}' does not exist")
    for el in t["path"]:
        if el.get("z_m") is not None:
            w = f"{el['hutch']}/{el['id']}"
            if not isinstance(el["z_m"], (int, float)) or isinstance(el["z_m"], bool):
                errs.append(f"{w}: z_m must be a number (metres from the source) or null")
            if el.get("z_conf") not in CONF + ("definition",):
                errs.append(f"{w}: z_m set but z_conf '{el.get('z_conf')}' not in {CONF + ('definition',)}")
            if not el.get("z_src"):
                errs.append(f"{w}: z_m set but z_src (where the number comes from) is missing")
        elif el.get("z_conf") or el.get("z_src"):
            errs.append(f"{el['hutch']}/{el['id']}: z_conf/z_src given without z_m")
    zs = [(el["z_m"], el["id"]) for el in t["path"] if isinstance(el.get("z_m"), (int, float))]
    for (a, ia), (b, ib) in zip(zs, zs[1:]):
        if b < a:
            errs.append(f"z_m not monotone along the beam: {ia} ({a}) then {ib} ({b})")
    for aid, a in t["assemblies"].items():
        if a.get("element") not in ids:
            errs.append(f"assembly {aid}: element '{a.get('element')}' not in any hutch")
        for p in a.get("src", []):
            if p not in photos:
                errs.append(f"assembly {aid}: unknown photo id '{p}'")
    for pid, p in photos.items():
        for e in p.get("elements", []):
            if e not in ids:
                errs.append(f"photos.json[{pid}]: element '{e}' does not exist")
        if not (photos_dir(t["beamline"]["id"]) / p["file"]).exists():
            warns.append(f"photos.json[{pid}]: local copy {p['file']} not present (photos live in the knowledge tree: twin_photos/, see `python -m blade.paths`)")
    return errs, warns


def _snap(el):
    s = el.get("state") or {}
    bits = [f"{k}={v}" for k, v in s.items() if k not in ("when", "note") and v is not None]
    return ", ".join(bits)


def _dev(el):
    return " / ".join(x for x in (el.get("dev"), el.get("pv")) if x)


def _strip(els):
    parts, last = [], None
    for e in els:
        n = e["name"].split(" (")[0]
        pl = e.get("placement", "in_line")
        g = e.get("group")
        sep = "  |  " if (last is not None and g is not None and g != last and not e.get("near")) else " - "
        if g is not None and not e.get("near"):
            last = g
        parts.append((sep, {"in_line": n, "retractable": f"[{n}]", "alt": f"({n})"}[pl]))
    lines, cur = [], "beam >"
    for sep, p in parts:
        if len(cur) + len(p) + len(sep) > 96:
            lines.append(cur)
            cur = "     "
        cur += f"{sep}{p}"
    return "\n".join(lines + [cur + " >"])


def render(t):
    bl, path = t["beamline"], t["path"]
    o = [f"# {bl['name']} - twin layout", "",
         "> GENERATED by `beamline_twins/tools/twin.py render` from the JSON files. Do not edit; edit the JSON and re-render.", "",
         f"Beam order: {' > '.join(bl['hutch_order'])}. Frame: {bl['frame']['x']}", "",
         f"Confidence per element: " + ", ".join(f"{c} {sum(1 for e in path if e['conf'] == c)}" for c in CONF) + f" (total {len(path)}). "
         "`[name]` = retractable (moved into the beam), `(name)` = alternative position, `|` = boundary between the boxed groups drawn on the operator panel. Distances (`z_m`) are known only where a source exists; unknown ones are blank, never guessed.", ""]
    for h in bl["hutch_order"]:
        els = [e for e in path if e["hutch"] == h]
        hd = t["hutches"].get(h, {})
        o += [f"## Hutch {h}", "", bl["hutches"].get(h, ""), "", f"Coverage: {bl['coverage'].get(h, '-')}", "", "```", _strip(els), "```", ""]
        if hd.get("groups"):
            o += ["Panel groups: " + "; ".join(f"**{g['name']}**: " + ", ".join(e['name'] for e in els if e.get('group') == g['id']) for g in hd["groups"]), ""]
        if hd.get("aux_panels"):
            o += [f"Auxiliary panels ({hd['aux_panels']['src']}): " + ", ".join(hd["aux_panels"]["items"]) + ".", ""]
        if hd.get("lasers"):
            o += [f"Lasers ({hd['lasers']['src']}): " + ", ".join(hd["lasers"]["items"]) + ".", ""]
        o += [
              "| # | id | name | kind | conf | z (m) | device / PV | snapshot (2026-10-20) | photos |", "|--:|---|---|---|---|--:|---|---|---|"]
        for e in els:
            o.append(f"| {e['index'] + 1} | `{e['id']}` | {e['name']} | {e['kind']}{'*' if e.get('tomo') else ''} | {e['conf']} | {'' if e.get('z_m') is None else e['z_m']} | {_dev(e)} | {_snap(e)} | {', '.join(e.get('src', []))} |")
        o.append("")
    zk = [e for e in path if e.get("z_m") is not None]
    o += [f"`*` = tomo detector. Distances (z, m from the source): {len(zk)} of {len(path)} elements known.", "",
          "## Known distances (m from the source)", "", "| z (m) | element | hutch | basis | source |", "|--:|---|---|---|---|"]
    o += [f"| {e['z_m']} | `{e['id']}` {e['name']} | {e['hutch']} | {e['z_conf']} | {e['z_src']} |" for e in zk]
    o += ["", "", "## Slits (size / centre, mm, snapshot)", "", "| id | hutch | name | H size | V size | H centre | V centre |", "|---|---|---|---|---|---|---|"]
    for e in (x for x in path if x["kind"] == "slit"):
        s = e.get("state", {})
        o.append(f"| `{e['id']}` | {e['hutch']} | {e['name']} | {s.get('hsize_mm')} | {s.get('vsize_mm')} | {s.get('hcenter_mm')} | {s.get('vcenter_mm')} |")
    o += ["", "## Detectors", "", "| id | hutch | name | tomo | placement | conf | notes |", "|---|---|---|---|---|---|---|"]
    for e in (x for x in path if x["kind"] == "detector"):
        o.append(f"| `{e['id']}` | {e['hutch']} | {e['name']} | {'yes' if e.get('tomo') else ''} | {e.get('placement', 'in_line')} | {e['conf']} | {e.get('notes', '')[:140]} |")
    di = bl.get("detector_iocs")
    if di:
        o += ["", "## Detector IOCs (operator panel 'IOC Control', " + di["src"] + ")", "", di["note"], "", "| label | IOC prefix | camera | twin element | note |", "|---|---|---|---|---|"]
        o += [f"| {x['label']} | {('`' + x['prefix'] + '`') if x.get('prefix') else '(not legible)'} | {x['camera']} | {x['element'] or ('(one of: ' + ', '.join(x['candidates']) + ')' if x.get('candidates') else '(not assigned)')} | {x.get('note', '')} |" for x in di["items"]]
    ip = bl.get("ioc_panels")
    if ip:
        o += ["", "## Other IOC Control tabs", "", ip["note"], ""] + [f"- **{k}**: {', '.join(v) if isinstance(v, list) else v}" for k, v in ip.items() if k not in ("src", "note", "meaning", "Detector(E)")] + ["", ip["meaning"]]
    for aid, a in t["assemblies"].items():
        o += ["", f"## Assembly `{aid}` - {a['name']}", "", a["note"], "", "| level | name | motor | device | units | limits | readback |", "|--:|---|---|---|---|---|---|"]
        for s in a["stack_top_to_bottom"]:
            o.append(f"| {s['level']} | {s['name']} | {s.get('motor', '')} | {s.get('device', '')} | {s.get('units', '')} | {s.get('limits', '')} | {s.get('readback', '')} |")
    ph = t["photos"]
    o += ["", "## Photo index", "", "| id | hutch | type | shows |", "|---|---|---|---|"]
    o += [f"| {p['id']} | {p['hutch']} | {p['type']} | {p['shows'][:150]} |" for p in ph.values()]
    return "\n".join(o) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "render", "show"])
    ap.add_argument("beamline")
    ap.add_argument("--kind")
    ap.add_argument("--hutch")
    a = ap.parse_args()
    t = load(a.beamline)
    if a.cmd == "check":
        errs, warns = check(t)
        for w in warns:
            print("WARN ", w)
        for e in errs:
            print("ERROR", e)
        print(f"{len(t['path'])} elements, {len(t['assemblies'])} assemblies, {len(t['photos'])} photos: {len(errs)} errors, {len(warns)} warnings")
        sys.exit(1 if errs else 0)
    if a.cmd == "render":
        out = t["dir"] / "layout.md"
        out.write_text(render(t))
        print("wrote", out)
    if a.cmd == "show":
        for e in t["path"]:
            if (not a.kind or e["kind"] == a.kind) and (not a.hutch or e["hutch"] == a.hutch):
                print(f"{e['index'] + 1:3d} {e['hutch']} {e['id']:<10} {e['kind']:<12} {e['conf']:<9} {e['name']}")


if __name__ == "__main__":
    main()
