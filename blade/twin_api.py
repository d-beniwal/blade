"""Read-only data for the twin viewer (`/twin` in `blade gui`). Pure functions: they read profile JSON and the twin folder directly and never
touch `blade.config`'s global state, so browsing twins cannot disturb a running alignment. Never connects to anything."""
import importlib.util
import json
from . import config as cfg
from . import paths

_mod = None


def _twin_module():
    """beamline_twins/tools/twin.py loaded by path (it lives outside the package so the twins stay plain data + one stdlib tool)."""
    global _mod
    if _mod is None:
        f = paths.TWINS_DIR / "tools" / "twin.py"
        spec = importlib.util.spec_from_file_location("blade_twin_tool", f)
        _mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_mod)
    return _mod


def read_profile(name):
    """Merged profile dict (default_config.json + optional active_config.json), without loading it into blade.config."""
    d = cfg.profile_dir(name)
    prof = json.loads((d / "default_config.json").read_text())
    if (d / "active_config.json").is_file():
        cfg._merge(prof, json.loads((d / "active_config.json").read_text()))
    return prof


def _twin_exists(tid):
    return bool(tid) and (paths.TWINS_DIR / tid / "beamline.json").is_file()


def profile_list():
    out = []
    for n in cfg.profiles():
        p = read_profile(n)
        tid = p.get("twin")
        out.append({"name": n, "beamline": p.get("beamline", n), "description": p.get("description", ""), "twin": tid if _twin_exists(tid) else None,
                    "twin_declared": tid})
    return {"default": paths.DEFAULT_PROFILE, "profiles": out}


def photo_file(tid, photo_id_or_file):
    """Local path of an INDEXED photo (only files listed in photos.json are ever served), or None."""
    if not _twin_exists(tid):
        return None
    t = _twin_module().load(tid, paths.TWINS_DIR)
    for p in t["photos"].values():
        if photo_id_or_file in (p["id"], p["file"]):
            f = _twin_module().photos_dir(tid) / p["file"]
            return f if f.is_file() else None
    return None


def _blade_targets(prof, elements):
    """Twin elements the profile's station motors belong to (motor name 'samE.ry' -> element 'samE'): {element_id: [motor names]}."""
    ids = {e["id"] for e in elements}
    hits = {}
    for sname, st in (prof.get("stations") or {}).items():
        for role, m in st.get("motors", {}).items():
            nm = m.get("name", "")
            prefix = nm.split(".")[0]
            if prefix in ids:
                hits.setdefault(prefix, []).append(f"{nm} (station {sname}, role {role})")
    return hits


def twin_payload(profile):
    prof = read_profile(profile)
    stations = {s: {"description": v.get("description", ""), "motors": {r: {"name": m.get("name"), "pv": m.get("pv"), "role": m.get("role")}
                                                                          for r, m in v.get("motors", {}).items()}}
                for s, v in (prof.get("stations") or {}).items()}
    out = {"profile": {"name": profile, "beamline": prof.get("beamline", profile), "description": prof.get("description", ""),
                       "backends": prof.get("backends", []), "default_camera": prof.get("default_camera"), "default_station": prof.get("default_station"),
                       "cameras": {k: {"hutch": v.get("hutch"), "pixel_um": v.get("pixel_um"), "pv_prefix": v.get("pv_prefix"), "note": v.get("note")}
                                   for k, v in prof.get("cameras", {}).items()}, "stations": stations},
           "twin": None, "twin_declared": prof.get("twin")}
    tid = prof.get("twin")
    if not _twin_exists(tid):
        return out
    tm = _twin_module()
    t = tm.load(tid, paths.TWINS_DIR)
    errs, warns = tm.check(t)
    bl = t["beamline"]
    els = t["path"]
    out["twin"] = {
        "id": tid, "name": bl["name"], "frame": bl["frame"], "hutch_order": bl["hutch_order"], "snapshot": bl.get("snapshot", {}),
        "hutches": {h: {"description": bl["hutches"].get(h, ""), "coverage": bl.get("coverage", {}).get(h, ""), "note": t["hutches"].get(h, {}).get("note", ""),
                        **{k: t["hutches"].get(h, {})[k] for k in ("groups", "panel", "aux_panels", "lasers") if k in t["hutches"].get(h, {})}}
                    for h in bl["hutch_order"]},
        "elements": els, "assemblies": t["assemblies"],
        **{k: bl[k] for k in ("detector_iocs", "ioc_panels", "header_pvs", "beam_types", "ic_readout") if k in bl},
        "overview": bl.get("operator_screens", {}).get("overview_cs01"),
        "photos": [{**p, "local": (tm.photos_dir(tid) / p["file"]).is_file()} for p in t["photos"].values()],
        "conf_order": list(tm.CONF), "conf_counts": {c: sum(1 for e in els if e["conf"] == c) for c in tm.CONF},
        "blade_targets": _blade_targets(prof, els), "check": {"errors": errs, "warnings": warns},
        "any_distance": any(isinstance(e.get("z_m"), (int, float)) for e in els),
    }
    return out
