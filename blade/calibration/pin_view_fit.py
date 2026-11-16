"""Pin-in-view model for the 1-ID E-station tomo camera, built from the curated `tomopin` images of the knowledge base (OFFLINE; never imported at runtime).

Question: which stage / slit / camera values must hold so the tungsten alignment pin appears on the tomo detector?  What the logs support is a
CAPTURE-RANGE model, not an absolute regression, because the numbers that matter are re-zeroed every cycle (slit centres, aero user zero) and the
pin is mounted differently each time (samYE).  Three layers:

  1. geometry (`lateral_margin_mm`, `footprint_h_mm`, `tip_window_mm`): the pin is seen when its silhouette overlaps the lit, in-FOV window.  Constants
     come from `camera_fit` (pixel size, pin cone) and the twin (Kohzu slits ~ unity magnification, WB footprint 1.6-2.2 x the WB gap).
  2. calibration from the logs (`collect`): the aero-X DIAL value at which the axis sat on the beam in each cycle, how far it moved between cycles,
     the slit sizes and stage values attached to each pin frame, and the as-found axis moves written in the logs.
  3. a recipe with tolerances (`summarize` -> fits/pin_view.json + pin_view.md).

RELIABILITY (AGENTS.md): only tier-A panel facts are used; a value is attached to an image only if it is the LAST one logged before the image in the same
document, at most MAX_BACK lines earlier (not "nearest": a slit panel just after an image is the next setting, not the one in the image); excluded tier-B/C
counts and stale/ambiguous items are reported.  PRIVACY: the repo is public, so `summarize` returns aggregates only (no document ids of user logs);
the per-image table with ids goes to the knowledge tree (`write_private`).
"""
import json
import math
import sqlite3
from pathlib import Path

import numpy as np

from blade import paths
from blade.calibration import camera_fit as cf

MAX_BACK = 30            # lines: a panel older than this is not attached to the image
ALIGNED_USER_MM = 0.2    # aero user position |x| below this = axis zeroed on the beam
GH1_NATIVE_W_PX = 4096     # GS3-U3-89S6M (user 2026-11-15; profiles/s1id cameras.gh1.spec); logged frames are ROI crops (850-1940 px wide)
PG1_NATIVE_W_PX = 1920     # GS3-U3-23S6M
FITS = Path(__file__).resolve().parent.parent.parent / "beamline_twins" / "1-ID" / "physics" / "fits"
# (device, quantity) per variable; WB slits appear under two device names (wbeam, wbslits), C/B Kohzu under several
VARS = {
    "samXE_mm": [("samxe", "rbv")], "samYE_mm": [("samye", "rbv")], "samZE_mm": [("samze", "rbv")],
    "aeroRot_deg": [("aerorot", "rbv_user")],
    "E_slit_h": [("kohzuedn", "size_h"), ("kohzueup", "size_h")], "E_slit_v": [("kohzuedn", "size_v"), ("kohzueup", "size_v")],
    "WB_h": [("wbeam", "size_h"), ("wbslits", "size_h")], "WB_v": [("wbeam", "size_v"), ("wbslits", "size_v")],
    "C_slit_h": [("ckslitds", "size_h"), ("ckslitus", "size_h"), ("ckuzds", "size_h"), ("ckuzus", "size_h")], "B_slit_h": [("bkohzu", "size_h")],
    "tomoX_mm": [("imgx", "rbv_user")], "tomoZ_mm": [("imgz", "rbv_user")], "tomoY_mm": [("imgye", "rbv_user")], "tomoChi_deg": [("imgchie", "rbv_user")],
    "energy_keV": [("hemenergy(kev)", "energy"), ("hemenergyaenergykev", "calc")],
}
MIN_OF = {"E_slit_h", "E_slit_v", "WB_h", "WB_v", "C_slit_h"}      # several devices -> the most restrictive (smallest) opening

# ----------------------------------------------------------------------------------------------------------------------------- geometry
KOHZU_E_MAG = 1.0                      # "100 um in the slit control = 100 um on the tomo" (S25b:L189-203); C slit 0.110 -> 0.120 mm at the sample (D22:L178)
WB_FOOTPRINT_MAG = (1.6, 2.2)          # footprint / WB gap: 820 um FWHM (H) and 1050 um (V) for 0.5 mm (one session) and "~1.1 mm for WB 0.5-0.6" (09 notes): n=2


def footprint_h_mm(wb_h_mm, e_slit_h_mm=None, wb_mag=1.9):
    """Lit width at the E tomo camera: the smaller of the WB-defined footprint (wb_mag x gap; 1.6-2.2 measured) and the E slit opening (unity)."""
    f = wb_mag * wb_h_mm
    return f if e_slit_h_mm is None else min(f, KOHZU_E_MAG * e_slit_h_mm)


def lateral_margin_mm(axis_dial_mm, beam_dial_mm, footprint_mm, fov_mm, pin_group="B", depth_um=0.0, require_flat_top=False, pin_offset_mm=0.0):
    """Distance [mm] by which the pin silhouette (width at `depth_um` below the tip) sits inside the lit window (footprint ∩ camera FOV, centred on the beam).
    The pin is at axis + `pin_offset_mm` (its offset from the rotation axis across the beam at the current omega; ~0 once samXE/samZE are aligned).
    > 0: seen (silhouette overlaps the window).  With `require_flat_top`: the whole width must fit, i.e. usable for alignment.  Negative = how far off."""
    pp = cf.pin_params(pin_group)
    w = cf.pin_width_um(depth_um, pp["top_width_um"], pp["half_angle_deg"]) / 1000.0
    half = 0.5 * min(footprint_mm, fov_mm)
    d = abs(axis_dial_mm + pin_offset_mm - beam_dial_mm)
    return (half - d - w / 2.0) if require_flat_top else (half - d + w / 2.0)


def tip_window_mm(footprint_v_mm, pin_group="B"):
    """The pin tip is on screen (cone enters from below, apex up) while the tip height lies inside the lit vertical window: a samYE window this wide
    (minus the flat-top height 0). Outside it the cone either is below the window (not visible) or fills it (tip off-screen)."""
    return footprint_v_mm


def capture_fraction(axis_offsets_mm, footprint_mm, fov_mm, pin_group="B", pin_offset_mm=0.0):
    """Fraction of `axis_offsets_mm` (axis-to-beam distances, pin on the axis unless `pin_offset_mm`) for which the pin is already seen without moving aero X."""
    return float(np.mean([lateral_margin_mm(o, 0.0, footprint_mm, fov_mm, pin_group, pin_offset_mm=pin_offset_mm) > 0 for o in axis_offsets_mm])) if len(axis_offsets_mm) else float("nan")


# ----------------------------------------------------------------------------------------------------------------------------- data
def _kb():
    p = paths.knowledge_dir("kb") / "kb.sqlite"
    if not p.is_file():
        raise FileNotFoundError(f"knowledge base not found: {p} (python -m blade.paths)")
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def _manual():
    f = paths.knowledge_dir("kb") / "pin_view_manual.json"
    return json.loads(f.read_text()) if f.is_file() else {}


def _last_before(con, doc, ln, devq):
    """Last tier-A value of (device, quantity) logged at or before `ln` in `doc`, at most MAX_BACK lines back -> (value, lines_back) or None;
    also the number of excluded tier-B/C rows in the same window."""
    r = con.execute("select value,ln from fact_obs where doc_id=? and device=? and quantity=? and tier='A' and ln<=? and ln>=? order by ln desc limit 1",
                    (doc, devq[0], devq[1], ln, ln - MAX_BACK)).fetchone()
    nonA = con.execute("select count(*) from fact_obs where doc_id=? and device=? and quantity=? and tier<>'A' and ln<=? and ln>=?",
                       (doc, devq[0], devq[1], ln, ln - MAX_BACK)).fetchone()[0]
    return (r[0], ln - r[1]) if r else None, nonA


def collect(con=None):
    """Per-image state for every image whose best `subject` label is 'tomopin'. Returns (rows, notes)."""
    con = con or _kb()
    man = _manual()
    excl = {e["sha8"]: set(e["fields"]) for e in man.get("exclude_attached", [])}
    imgs = con.execute("""select substr(i.sha256,1,8), r.doc_id, r.ln, d.date_first, i.width, i.height from image_index i join image_refs r on r.sha256=i.sha256
        join docs d on d.doc_id=r.doc_id where i.subject='tomopin' group by i.sha256 order by r.doc_id, r.ln""").fetchall()
    rows, nonA_total = [], 0
    for sha8, doc, ln, date, w, h in imgs:
        rec = {"sha8": sha8, "doc": doc, "ln": ln, "date": date, "vars": {}, "stale_excluded": sorted(excl.get(sha8, []))}
        for name, devqs in VARS.items():
            if name in excl.get(sha8, ()):
                continue
            vals = []
            for dq in devqs:
                v, n = _last_before(con, doc, ln, dq)
                nonA_total += n
                if v:
                    vals.append(v)
            if vals:
                rec["vars"][name] = {"value": min(v[0] for v in vals) if name in MIN_OF else vals[0][0], "lines_back": min(v[1] for v in vals)}
        for o in man.get("override_attached", []):
            if o["sha8"] == sha8:
                for k, v in o["values"].items():
                    rec["vars"][k] = {"value": v, "lines_back": None, "source": "log text (overrides an older panel)"}
        rows.append(rec)
    return rows, {"n_images": len(rows), "excluded_nonA_rows_in_windows": nonA_total, "max_back_lines": MAX_BACK}


def axis_on_beam(con=None):
    """Aero-X dial positions at which the rotation axis sat on the beam (user position zeroed: |user| < 0.2, or flagged by the manual list), one per
    (document, panel), with the E-slit centre logged just before (None if absent). The dial is the encoder coordinate; the user value is re-zeroed."""
    con = con or _kb()
    man = {(o["doc"], o["ln"]) for o in _manual().get("axis_on_beam_overrides", [])}
    out = []
    for doc, ln, dial in con.execute("select doc_id, ln, value from fact_obs where tier='A' and device='aerox(ine)' and quantity='rbv_dial' group by doc_id, ln"):
        u = con.execute("select value from fact_obs where doc_id=? and ln=? and device='aerox(ine)' and quantity='rbv_user' and tier='A' limit 1", (doc, ln)).fetchone()
        if u is None or not (abs(u[0]) < ALIGNED_USER_MM or (doc, ln) in man):
            continue
        sl = [x[0] for x in (con.execute("select value from fact_obs where doc_id=? and device=? and quantity='center_h' and tier='A' and ln<=? and ln>=? order by ln desc limit 1",
                                         (doc, d, ln, ln - MAX_BACK)).fetchone() for d in ("kohzuedn", "kohzueup")) if x]
        date = con.execute("select date_first from docs where doc_id=?", (doc,)).fetchone()[0]
        out.append({"doc": doc, "ln": ln, "date": date, "dial_mm": dial, "user_mm": u[0], "e_slit_center_h_mm": float(np.mean(sl)) if sl else None})
    return sorted(out, key=lambda r: r["date"])


# ----------------------------------------------------------------------------------------------------------------------------- summary
def _stats(vals):
    a = np.array(vals, float)
    return {"n": int(a.size), "min": round(float(a.min()), 5), "median": round(float(np.median(a)), 5), "max": round(float(a.max()), 5)} if a.size else {"n": 0}


def summarize(con=None):
    """Aggregates only (public). Document ids and line numbers of user logs are NOT included."""
    con = con or _kb()
    rows, notes = collect(con)
    axis = axis_on_beam(con)
    man = _manual()
    env = {}
    for name in VARS:
        vs = [(r["vars"][name]["value"], r["doc"]) for r in rows if name in r["vars"]]
        env[name] = dict(_stats([v for v, _ in vs]), n_sessions=len({d for _, d in vs}))
    dials = [a["dial_mm"] for a in axis]
    # one value per cycle (month): the dial is constant within a cycle, so n counts cycles, not panels
    by_cycle = {}
    for a in axis:
        by_cycle.setdefault(a["date"][:7], []).append(a)
    cyc = [{"cycle": k, "dial_mm": round(float(np.mean([x["dial_mm"] for x in v])), 4), "e_slit_center_h_mm": (None if all(x["e_slit_center_h_mm"] is None for x in v) else
            round(float(np.mean([x["e_slit_center_h_mm"] for x in v if x["e_slit_center_h_mm"] is not None])), 3))} for k, v in sorted(by_cycle.items())]
    for c in cyc:
        c["dial_minus_slit_centre_mm"] = None if c["e_slit_center_h_mm"] is None else round(c["dial_mm"] - c["e_slit_center_h_mm"], 3)
    shifts = [abs(b["dial_mm"] - a["dial_mm"]) for a, b in zip(cyc, cyc[1:])]
    coarse = [m["value"] for m in man.get("coarse_axis_moves_mm", [])]
    fine = [m["value"] for m in man.get("fine_axis_moves_mm", [])]
    recent = [c["dial_mm"] for c in cyc if c["cycle"] >= "2025-10"]
    return {
        "built": "2026-11-15", "source": "knowledge-base images with subject=tomopin (curated by the user 2026-11-15) + tier-A panel facts + hand-read log lines",
        "images": notes, "envelope_at_pin_frames": env,
        "axis_on_beam_by_cycle": cyc,
        "axis_dial_recent_cycles_mm": {"values": [round(x, 3) for x in recent], "mean": round(float(np.mean(recent)), 3) if recent else None,
                                       "sd": round(float(np.std(recent, ddof=1)), 3) if len(recent) > 1 else None,
                                       "half_range": round(0.5 * (max(recent) - min(recent)), 3) if recent else None},
        "cycle_to_cycle_axis_shift_mm": [round(s, 3) for s in shifts],
        "coarse_axis_moves_mm": sorted(coarse), "fine_axis_moves_mm": sorted(fine),
        "dial_minus_slit_centre_constant_across_cycles": bool(len({c["dial_minus_slit_centre_mm"] for c in cyc if c["dial_minus_slit_centre_mm"] is not None}) == 1
                                                          or (lambda v: len(v) > 1 and max(v) - min(v) < 0.05)([c["dial_minus_slit_centre_mm"] for c in cyc if c["dial_minus_slit_centre_mm"] is not None])),
        "capture_vs_footprint": {cam: {f"{fp:.1f}mm": capture_fraction(shifts, fp, fov) for fp in (0.6, 1.0, 1.3, 2.0, 3.0)}
                                 for cam, fov in (("gh1", cf.fov_mm(GH1_NATIVE_W_PX, cf.pixel_um("gh1"))), ("pg1", cf.fov_mm(PG1_NATIVE_W_PX, cf.pixel_um("pg1"))))},
        "capture_note": "full-sensor FOV (an ROI crop shrinks it: 850-1940 px = 0.59-1.34 mm for GH1); fraction of the 5 cycle-to-cycle shifts of the on-beam aero dial for which a pin sitting on an axis left at the PREVIOUS cycle's dial is already on screen",
        "model_constants": {"gh1_fov_h_mm": round(cf.fov_mm(GH1_NATIVE_W_PX, cf.pixel_um("gh1")), 4), "pg1_fov_h_mm": round(cf.fov_mm(PG1_NATIVE_W_PX, cf.pixel_um("pg1")), 4),
                            "kohzu_E_mag": KOHZU_E_MAG, "wb_footprint_mag": list(WB_FOOTPRINT_MAG), "pin_B": cf.pin_params("B"), "pin_A": cf.pin_params("A")},
    }


def write_private(rows, axis, out_dir):
    """Per-image table WITH document ids (user logs): knowledge tree only."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pin_view_rows.json").write_text(json.dumps({"rows": rows, "axis_on_beam": axis}, indent=1))


if __name__ == "__main__":
    con = _kb()
    s = summarize(con)
    FITS.mkdir(parents=True, exist_ok=True)
    (FITS / "pin_view.json").write_text(json.dumps(s, indent=1))
    rows, _ = collect(con)
    write_private(rows, axis_on_beam(con), paths.knowledge_dir("scratch") / "pin_model")
    print(json.dumps(s, indent=1)[:6000])
