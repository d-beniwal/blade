"""Two things live here, both on the one pin workflow (blade/pinregion, playbooks/pin_workflow_v2.md). `analyse_pin` is the "tomo-pin fit" button of the virtual-beamline page: IMAGE ANALYSIS ONLY - it recognises the pin in a frame and
returns its geometry for an overlay; it never moves a motor (user 2026-11-15). `fit_pin_in_view` (MCP `vbl_centre_pin`) is the separate, simulator-only MOVE: if the pin is recognised in the frame, centre its axis on the lit window and put
its tip a fixed fraction below the top of the window, so the whole cone is visible.

`fit_pin_in_view` is a FINE move for a pin that is already (at least partly) in the picture. It never searches: if no pin is recognised the answer is `found: False` with the reason and nothing moves
(use `pin_find.find_pin` to search for a pin that is not in view yet).

Recognition is `pinregion.measure_frame` (pin region first, geometry measured inside it). Moves use the sample stage of the E hutch (aero X moves the pin axis sideways,
samE.y moves it vertically) with the static image-shift signs of `sim.json stage_E` (`col_per_base`, `row_per_y`: mm of image shift per mm of motor). On an instrument that cannot be written
(the real beamline) `set` raises ReadOnlyError, so there it can only be used with `apply=False`, which reports the moves it WOULD make (a proposal)."""
import numpy as np
from ._util import accepts_world
from ..pinregion import measure_frame, find_pin_region_final, pin_geometry as region_geometry, pin_like

TOP_FRAC = 0.2           # the tip goes this fraction of the footprint height below its top edge (same convention as `pinregion.measure`)
TOL_PX = 4.0             # converged when the axis and the tip are within this many full-resolution pixels of their targets
MAX_STEP_MM = 1.5        # never move a motor more than this in one go: a bad recognition must not fling the stage across its travel


def _position(m):
    """(axis column, tip row, how) of the recognised pin in full-resolution pixels, or (None, None, reason)."""
    v = m.get("view") or {}
    if m.get("usable") and m.get("pin_col_raw") is not None and m.get("top_row") is not None:
        return float(m["pin_col_raw"]), float(m["top_row"]), "whole pin in view"
    loc = v.get("locate")
    if v.get("state") == "partial" and loc and loc.get("axis_col") is not None and loc.get("top_row") is not None:
        return float(loc["axis_col"]), float(loc["top_row"]), "pin partly in view (position from the cone model)"
    if v.get("state") == "partial":
        return None, None, ("a pin-like dark object is partly in view but its edges are not reliable enough to position it (%s); not guessed - move it into the lit area by hand "
                            "or use the pin search" % ("; ".join(m.get("reasons") or []) or "unreliable edges"))
    return None, None, v.get("why") or "; ".join(m.get("reasons") or []) or m.get("message", "no pin recognised")


@accepts_world
def fit_pin_in_view(inst, cam="gh1", apply=True, max_iter=4):
    """Look, and if the pin is recognised, move aero X and samE.y until its axis sits on the footprint centre and its tip at TOP_FRAC of the footprint height (at most `max_iter`
    looks). `apply=False` measures once and returns the moves it would make without making them. Returns {found, state, moved, converged, moves, controls, offsets_px, frames, reason}."""
    sE = inst.sim["stage_E"]
    kx, ky = float(sE["col_per_base"]), float(sE["row_per_y"])
    p_mm = inst.cams[cam]["pixel_um"] * 1e-3                      # full-resolution frames: bin 1
    lo_x, hi_x = inst.spec("samE.aerox")[:2]
    lo_y, hi_y = inst.spec("samE.y")[:2]
    log, frames, moved = [], 0, False
    for it in range(max_iter if apply else 1):
        m = measure_frame(inst.frame(cam, bin_=1).astype(float), inst.ctl("samE.ry"))
        frames += 1
        state = (m.get("view") or {}).get("state", "unknown")
        col, row, how = _position(m)
        if col is None:
            return {"found": False, "state": state, "moved": moved, "frames": frames, "reason": how, "log": log,
                    "note": "nothing was recognised as the tomo pin in this frame; use the pin search (vbl_find_pin) to bring it into view first" if not moved else
                            "the pin was lost after a move"}
        b = m["beam"]
        tgt_col, tgt_row = float(b["cx"]), float(b["box"][2]) + TOP_FRAC * float(b["height"])
        dcol, drow = tgt_col - col, tgt_row - row                 # image shift still needed (px): + = right / down
        off = {"axis_col_px": round(col, 1), "tip_row_px": round(row, 1), "target_col_px": round(tgt_col, 1), "target_row_px": round(tgt_row, 1),
               "to_move_px": [round(dcol, 1), round(drow, 1)]}
        d_ax = float(np.clip(dcol * p_mm / kx, -MAX_STEP_MM, MAX_STEP_MM))       # image shift (mm) = col_per_base * d(aero X)
        d_y = float(np.clip(drow * p_mm / ky, -MAX_STEP_MM, MAX_STEP_MM))        # image shift (mm) = row_per_y * d(samE.y)
        ax0, y0 = inst.ctl("samE.aerox"), inst.ctl("samE.y")
        ax1, y1 = float(np.clip(ax0 + d_ax, lo_x, hi_x)), float(np.clip(y0 + d_y, lo_y, hi_y))
        log.append({"look": it + 1, "how": how, **off, "d_aerox_mm": round(ax1 - ax0, 4), "d_samE_y_mm": round(y1 - y0, 4)})
        done = abs(dcol) <= TOL_PX and abs(drow) <= TOL_PX
        if not apply:
            return {"found": True, "state": state, "moved": False, "converged": done, "frames": frames, "log": log, "offsets_px": off,
                    "proposed": {"samE.aerox": ax1, "samE.y": y1}, "note": "apply=False: nothing was moved"}
        if done:
            return {"found": True, "state": state, "moved": moved, "converged": True, "frames": frames, "log": log, "offsets_px": off,
                    "controls": {"samE.aerox": ax0, "samE.y": y0}}
        inst.set("samE.aerox", ax1)
        inst.set("samE.y", y1)
        moved = True
    # out of iterations: report where it ended
    m = measure_frame(inst.frame(cam, bin_=1).astype(float), inst.ctl("samE.ry"))
    col, row, how = _position(m)
    return {"found": col is not None, "state": (m.get("view") or {}).get("state", "unknown"), "moved": moved, "converged": False, "frames": frames + 1, "log": log,
            "controls": {"samE.aerox": inst.ctl("samE.aerox"), "samE.y": inst.ctl("samE.y")}, "reason": None if col is not None else how}


def _seg(a, b, W, H):
    return [[a[0] / W, a[1] / H], [b[0] / W, b[1] / H]]


_PRIOR = {}              # per camera: recent top widths (px) from two-flank frames - rescues one-flank frames; reset with `reset_pin_prior()`


def reset_pin_prior(cam=None):
    _PRIOR.pop(cam, None) if cam else _PRIOR.clear()


@accepts_world
def analyse_pin(inst, cam="gh1"):
    """IMAGE ANALYSIS ONLY (moves nothing, writes nothing to the instrument): one full-resolution frame -> the pin geometry, as an overlay for the page and numbers.
    Pin region detector + geometry measured inside that region (blade/pinregion, playbooks/pin_workflow_v2.md). Points of the overlay are fractions (0..1) of the frame width/height, so they draw on the image at any bin. Returns {recognised, usable, quality, state,
    status, message, reasons, why, numbers{...}, overlay{...}}; `overlay` holds only what was really found (region polygon, lit window, virtual top corners, flank lines - a flank that
    was not measured is listed in `hidden_flank` -, axis). Not usable (clipped, one flank only) still shows what was measured, flagged `usable: False`: nothing is hidden or guessed."""
    img = inst.frame(cam, bin_=1).astype(float)
    pix = inst.cams[cam]["pixel_um"]
    return pin_geometry(img, pix, cam=cam)


def pin_geometry(img, pix, cam=None):
    """Pin analysis of any full-resolution frame array (simulated, real or logged) - same output as `analyse_pin`, no instrument needed. `pix` = um per pixel; `cam` keys the
    learned top-width prior (None: no prior)."""
    H, W = img.shape
    res = find_pin_region_final(img)
    hist = _PRIOR.setdefault(cam, []) if cam else []
    prior = {"top_width_px": float(np.median(hist))} if len(hist) >= 2 else None
    geo = region_geometry(img, res, pixel_um=pix, prior=prior)
    nums = {"pixel_um": pix, "frame_px": [W, H], "region_score": float(res.get("score", 0.0))}
    base = {"recognised": False, "usable": False, "quality": None, "identity": None, "state": "absent", "status": "no_pin", "message": "no pin-like object", "reasons": [], "why": None,
            "notes": [], "numbers": nums, "overlay": {}}
    if not geo.get("found"):
        base["why"] = "No pin visible in this frame."
        base["reasons"] = ["no object with two long straight edges leaning like the pin's flanks"]
        return base
    p = geo["pin"]
    ok_, bad = pin_like(res, geo, img.shape)
    tw, ang = p["top_width_px"], p["half_angle_deg"]
    if not ok_:
        base["why"] = "No pin visible in this frame."              # a rejected candidate is never drawn or reported as a pin; the technical reasons stay in `reasons` / `notes`
        base["reasons"] = bad
        base["notes"] = ["candidate region rejected: " + "; ".join(bad)]
        return base
    fov = geo["fov"]
    fov_ov = {"box": [fov[0] / W, fov[1] / H, fov[2] / W, fov[3] / H], "centre": [0.5 * (fov[0] + fov[2]) / W, 0.5 * (fov[1] + fov[3]) / H]}
    y_top, y_bot = p["visible_rows"]
    (sl, il), (sr, ir) = geo["lines"]["L"], geo["lines"]["R"]
    meas = p["flanks_measured"]
    nums["visible_height_px"] = p["visible_height_px"]
    nums["fov_px"] = fov
    if not (meas["L"] and meas["R"]):
        # TIER 1 - only part of the pin is visible (one flank): identify the visible region and the flank that was really measured. No corners, no axis, no top width, no angles:
        # whatever lies outside the lit window, or on the unmeasured side, is not reported.
        side, (s_, i_) = ("left", (sl, il)) if meas["L"] else ("right", (sr, ir))
        ys = np.arange(max(y_top, fov[1]), min(y_bot, fov[3]) + 1.0)
        xs = s_ * ys + i_
        keep = (xs >= fov[0]) & (xs <= fov[2])
        ov = {"polygon": [[x / W, y / H] for x, y in res["polygon"]], "fov": fov_ov}
        if keep.sum() >= 2:
            ya, yb = ys[keep][0], ys[keep][-1]
            ov[side + "_flank"] = _seg((s_ * ya + i_, ya), (s_ * yb + i_, yb), W, H)
        ov["footprint"] = fov_ov
        ov["hidden_flank"] = []
        return {"recognised": True, "usable": True, "quality": "region_only", "identity": "pin", "state": "partial", "status": "region", "geometry": False,
                "message": "pin region found; only one flank visible, geometry not fitted", "reasons": [], "why": None,
                "notes": ["region score %.2f" % res.get("score", 0.0), "one flank visible (%s): region only" % side], "numbers": nums, "overlay": ov}
    # TIER 2 - both flanks measured: the pin's geometry
    if cam:
        hist.append(float(tw))
        del hist[:-30]
    (xl, yl), (xr, yr) = p["top_left"], p["top_right"]
    ov = {"polygon": [[x / W, y / H] for x, y in res["polygon"]], "fov": fov_ov, "footprint": fov_ov, "hidden_flank": [],
          "top": _seg((xl, yl), (xr, yr), W, H), "left_flank": _seg((xl, yl), (sl * y_bot + il, y_bot), W, H), "right_flank": _seg((xr, yr), (sr * y_bot + ir, y_bot), W, H)}
    if p["axis_col_px"] is not None:
        tn = np.tan(np.radians(p["axis_tilt_deg"]))
        ov["axis"] = _seg((p["axis_col_px"], p["tip_row_px"]), (p["axis_col_px"] + tn * (y_bot - p["tip_row_px"]), y_bot), W, H)
    nums.update(axis_col_px=p["axis_col_px"], tip_row_px=p["tip_row_px"], top_width_px=tw, top_width_um=p["top_width_um"], half_angle_deg=ang, angle_left_deg=p["half_angle_left_deg"],
                angle_right_deg=p["half_angle_right_deg"], axis_tilt_deg=p["axis_tilt_deg"], top_tilt_deg=p["top_tilt_deg"], top_rms_px=p["top_rms_px"],
                flank_rms_px=[p["flank_rms_px"]["L"], p["flank_rms_px"]["R"]], flank_inlier_rows=[p["flank_inlier_rows"]["L"], p["flank_inlier_rows"]["R"]], margins=geo["margins"],
                axis_offset_from_fov_centre_um=None if geo["axis_offset_from_fov_centre_px"] is None or pix is None else geo["axis_offset_from_fov_centre_px"] * pix,
                tip_below_footprint_top_frac=geo["tip_depth_below_fov_top_frac"], full_view=bool(geo["view"]["state"] == "in_view"))
    nums["axis_offset_from_footprint_centre_um"] = nums["axis_offset_from_fov_centre_um"]     # key the page / older code reads
    return {"recognised": True, "usable": bool(geo["usable"]), "quality": geo["quality"], "identity": "pin", "state": geo["view"]["state"], "status": "ok" if geo["usable"] else "partial",
            "geometry": True, "message": "pin found, both flanks measured", "reasons": geo["reasons"], "why": (geo["reasons"] or [None])[0], "notes": ["region score %.2f" % res.get("score", 0.0)],
            "numbers": nums, "overlay": ov}
