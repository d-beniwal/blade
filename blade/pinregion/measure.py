"""The ONE per-frame pin measurement of BLADE (pin workflow v2, playbooks/pin_workflow_v2.md): frame -> region (stage 1) -> geometry from the region (stage 2) -> verdict (stage 3), returned
as the dict the alignment procedures (procedures/pin_alignment.py, procedures/pin_fit.py) consume. It replaced the old global dark-pixel segmentation (analysis/pin/pinfit.py +
measure_frame), retired 2026-11-17: there is no second recogniser to fall back on.

Nothing here searches the image globally for the pin: every number is measured inside / along the stage-1 region, so a wrong object cannot enter. The "beam" of a frame is its half-maximum footprint
(footprint.py, the alignment target; the pin region tells it which part to ignore); the lit window (`fov`, region.py) is only what the geometry judges clipping against.
Also here: `fit_axis` (x(w) = c + a cos w + b sin w) and `overlay_jpeg` (the detections drawn on the frame)."""
import numpy as np
from PIL import Image, ImageDraw
from .. import config as cfg
from .region import find_pin_region_final
from .footprint import beam_footprint
from .geometry import pin_geometry, pin_like

MIN_WINDOW_PX = 150          # a lit window smaller than this (either side) is "no beam" (beam off the detector / shutter closed)
TOP_TARGET_FRAC = 0.2        # a partly visible pin is asked to move so that its tip lies this fraction of the window height below the window top
TOO_LOW_FRAC = 0.55          # tip deeper than this fraction of the window height: the pin is asked to move up
STEP_FRAC = 0.15             # step (fraction of the window width) when a pin is known to be cut on one side but its axis cannot be located


_NO_BEAM = {"cx": float("nan"), "cy": float("nan"), "box": [0, 0, 0, 0], "width": 0.0, "height": 0.0, "method": "failed"}


def _cone_tip_row(geo, width_px):
    """Row at which the two measured flank lines are `width_px` apart (the learned top width): the tip of a pin whose top is hidden / cut. None if the lines never get that far apart."""
    (sl, il), (sr, ir) = geo["lines"]["L"], geo["lines"]["R"]
    d = sr - sl
    return None if abs(d) < 1e-6 else float((width_px - (ir - il)) / d)


def _locate(geo, prior_w):
    """Position of a pin that is only partly in the window but whose two flanks were measured (cone model with the width learned in this run): {axis_col, top_row, top_clipped, cut_left,
    cut_right, rows_cut_frac}, else None."""
    p = geo["pin"]
    cl = geo["view"]["clipped"]
    if not (p["flanks_measured"]["L"] and p["flanks_measured"]["R"]) or p["axis_col_px"] is None:
        return None
    top_row = p["tip_row_px"]
    if cl["top"]:
        top_row = _cone_tip_row(geo, prior_w) if prior_w else None      # the fitted top is the window edge, not the pin: only the cone model can say where it really is
        if top_row is None:
            return None
    return {"axis_col": float(p["axis_col_px"]), "top_row": float(top_row), "top_clipped": bool(cl["top"]), "cut_left": bool(cl["left"]), "cut_right": bool(cl["right"]), "rows_cut_frac": 0.0}


def _hint(geo, beam, prior_w):
    """Which stage move would bring a partly visible pin into the window (image px -> mm through the profile's static image-shift signs)."""
    p, cl = geo["pin"], geo["view"]["clipped"]
    y0, fw, fh = float(beam["box"][2]), beam["width"], beam["height"]         # targets are set on the beam footprint (the alignment target); clipping was judged against the lit window
    h = {}
    both = p["flanks_measured"]["L"] and p["flanks_measured"]["R"]
    if not both and p["axis_col_px"] is None:                                  # ONE flank and no learned width: could be a false region on a plain beam (7 % of the pin-free KB frames were accepted as
        return h                                                               # such regions), so it earns no move hint - the caller searches instead (or fails with 'no usable hint')
    if cl["left"] or cl["right"]:
        if p["axis_col_px"] is not None:
            dx = beam["cx"] - p["axis_col_px"]                               # image px the pin must move right (+) / left (-)
        else:
            dx = (1.0 if cl["left"] else -1.0) * (abs(geo["margins"]["left_px" if cl["left"] else "right_px"]) + STEP_FRAC * fw) if cl["left"] != cl["right"] else None
        if dx is not None:
            h["x_mm"] = cfg.px_to_mm(dx / cfg.IMAGE_COL_PER_X)
            h["x_image_dir"] = "right" if dx > 0 else "left"
    tgt = y0 + TOP_TARGET_FRAC * fh
    if cl["top"] and both:
        tip = _cone_tip_row(geo, prior_w) if prior_w else None
        dy = (tgt - tip) if tip is not None else 0.4 * fh                      # unknown depth above the window: step by 40 % of its height
    elif both and p["tip_row_px"] > y0 + TOO_LOW_FRAC * fh:
        dy = tgt - p["tip_row_px"]                                            # tip too deep in the window: image px the pin must move up (-)
    else:
        dy = None
    if dy is not None:
        h["y_mm"] = cfg.px_to_mm(dy / cfg.IMAGE_ROW_PER_Y)
    if h:
        h["from"] = "pin region geometry"
    return h


def measure_frame(img, omega, prior=None, beam_prior=None, pixel_um=None):
    """Pin + lit-window measurement of one frame. Returns a JSON-able dict (never raises on a bad frame; private keys start with `_`).

    `prior` = {"top_width": px, "half_angle_deg": deg} learned earlier in this run (optional): it rescues frames where one flank is hidden (axis = visible corner +- width/2) and flags a
    different object (width / angle disagree beyond the profile tolerances). A frame is `usable` only if the pin's flanks were measured as real pin edges and its top corners lie inside the
    lit window; everything else is rejected with `reasons`, never guessed. `beam_prior` = the footprint learned from clean frames of this run (used when the pin hides part of it).
    Keys: omega, status, message, pin_col (None unless usable), pin_col_raw, usable, quality (both_flanks | one_sided_left | one_sided_right | None), reasons, top_row, top_width (px), half_angle_deg,
    identity (pin | other | unknown), pin_object, full_view, notes, beam {cx, cy, box [x0, x1, y0, y1], width, height, method pin-excluded | p90-coarse | prior | failed}, view {state in_view | partial | absent | other_object | no_beam, hint, why,
    locate}, region_score."""
    g = np.asarray(img, float)
    H, W = g.shape
    out = {"omega": float(omega), "status": "no_pin", "message": "no pin-like object", "pin_col": None, "pin_col_raw": None, "usable": False, "quality": None, "reasons": [], "top_row": None,
           "top_width": None, "half_angle_deg": None, "full_view": False, "notes": [], "identity": "unknown", "pin_object": False, "region_score": None}
    coarse = beam_footprint(g)                                                  # pin-independent first look: is there a beam at all?
    if coarse is None or coarse["width"] < MIN_WINDOW_PX or coarse["height"] < MIN_WINDOW_PX:
        out["beam"] = dict(_NO_BEAM)
        out["status"], out["message"] = "no_beam", "no lit window found"
        out["view"] = {"state": "no_beam", "hint": None, "why": "no lit footprint found (beam off the detector / shutter closed?)"}
        return out
    prior_w = float((prior or {}).get("top_width") or 0) or None
    res = find_pin_region_final(g)
    geo = pin_geometry(g, res, pixel_um=pixel_um, prior={"top_width_px": prior_w} if prior_w else None)
    out["region_score"] = float(res.get("score", 0.0))
    ok_, bad = pin_like(res, geo, g.shape)
    poly = res.get("polygon") if ok_ else None
    pin_geom = None
    if poly:                                                                    # extents of the pin region: the footprint ignores these columns / rows
        xs = [x for x, _ in poly]
        pin_geom = (float(min(xs)), float(max(xs)), float(geo["pin"]["tip_row_px"]))
    b = beam_footprint(g, pin_present=bool(ok_), geom=pin_geom)
    if beam_prior and (b is None or b.get("method") != "pin-excluded"):         # the footprint is fixed during a run: reuse the one learned from clean frames
        b = dict(beam_prior, method="prior")
    out["beam"] = b if b else dict(_NO_BEAM)
    if not ok_:
        out["reasons"] = bad
        out["view"] = {"state": "absent", "hint": None, "why": "no pin visible: " + "; ".join(bad)}
        return out
    out["_geo"], out["_polygon"] = geo, res.get("polygon")
    p, meas, cl = geo["pin"], geo["pin"]["flanks_measured"], geo["view"]["clipped"]
    out.update(status="ok", message="pin region found", pin_object=True, quality=geo["quality"], top_row=p["tip_row_px"], top_width=p["top_width_px"], half_angle_deg=p["half_angle_deg"],
               pin_col_raw=p["axis_col_px"], full_view=bool(geo["view"]["state"] == "in_view"), reasons=list(geo["reasons"]), identity="pin",
               notes=["region score %.2f" % out["region_score"]])
    # identity against the pin learned in this run (stage 4): only a two-flank width means anything
    if meas["L"] and meas["R"]:
        nom = float((prior or {}).get("half_angle_deg") or cfg.NOMINAL_HALF_ANGLE_DEG)
        why = []
        if prior_w and abs(p["top_width_px"] - prior_w) / prior_w > cfg.TOP_WIDTH_TOL:
            why.append("top width %.0f px vs %.0f px learned for the pin" % (p["top_width_px"], prior_w))
        for side, ang in (("left", p["half_angle_left_deg"]), ("right", p["half_angle_right_deg"])):
            if abs(ang - nom) > cfg.HALF_ANGLE_TOL_DEG:
                why.append("%s flank half-angle %.1f deg vs %.1f" % (side, ang, nom))
        if why:
            out.update(identity="other", reasons=out["reasons"] + ["a different object: " + "; ".join(why)], pin_col_raw=None, quality=None)
            out["view"] = {"state": "other_object", "hint": None, "why": "a pin-like object is in view but it is not the pin learned in this run (" + "; ".join(why) + ")"}
            return out
    visible_clipped = (geo["quality"] == "one_sided_left" and cl["left"]) or (geo["quality"] == "one_sided_right" and cl["right"])
    usable = bool(geo["usable"]) and not visible_clipped and p["axis_col_px"] is not None
    out["usable"] = usable
    if usable:
        out["pin_col"] = float(p["axis_col_px"])
        out["view"] = {"state": "in_view", "hint": None, "why": geo["quality"]}
        return out
    loc = _locate(geo, prior_w)
    hint = _hint(geo, out["beam"], prior_w)
    view = {"state": "partial", "hint": hint or None, "why": "; ".join(out["reasons"]) or "pin partly outside the lit window"}
    if loc:
        view["locate"] = loc
    out["view"] = view
    return out


def fit_axis(omegas, cols, weights=None):
    """x(w) = c + a cos w + b sin w (optionally weighted). Returns dict with c, a, b, rms, residuals, rad, phase_deg (their rad*sin(w+st))."""
    om = np.radians(np.asarray(omegas, float))
    x = np.asarray(cols, float)
    if len(x) < 3:
        return {"ok": False, "reason": f"need >=3 valid angles, have {len(x)}"}
    A = np.c_[np.ones_like(om), np.cos(om), np.sin(om)]
    sw = np.sqrt(np.ones_like(x) if weights is None else np.asarray(weights, float))
    (c, a, b), *_ = np.linalg.lstsq(A * sw[:, None], x * sw, rcond=None)
    res = x - A @ [c, a, b]
    return {"ok": True, "c": float(c), "a": float(a), "b": float(b), "rms": float(np.sqrt(np.mean(res ** 2))),
            "residuals": [float(v) for v in res], "n": int(len(x)),
            "rad": float(np.hypot(a, b)), "phase_deg": float(np.degrees(np.arctan2(a, b)))}


def overlay_jpeg(img, m, path, scale=2):
    """Contrast-scaled frame with the detections drawn on it: lit window, pin region polygon, flank lines, top edge, pin axis column."""
    lo, hi = np.percentile(img, [1, 99.5])
    g = np.clip((img.astype(np.float32) - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
    im = Image.fromarray(g).convert("RGB").resize((img.shape[1] // scale, img.shape[0] // scale))
    d = ImageDraw.Draw(im)
    s = 1.0 / scale
    b = m["beam"]
    if b["width"] > 0:
        bx0, bx1, by0, by1 = b["box"]
        d.rectangle([bx0 * s, by0 * s, bx1 * s, by1 * s], outline=(80, 200, 120))
        d.line([b["cx"] * s, 0, b["cx"] * s, im.size[1]], fill=(80, 200, 120), width=1)
    geo = m.get("_geo")
    if m["pin_object"] and geo and geo.get("found"):
        p = geo["pin"]
        ytop, ybot = p["visible_rows"]
        if m.get("_polygon"):
            pts = [(x * s, y * s) for x, y in m["_polygon"]]
            d.line(pts + pts[:1], fill=(90, 150, 255), width=1)
        for k in ("L", "R"):
            sl, il = geo["lines"][k]
            d.line([(sl * ytop + il) * s, ytop * s, (sl * ybot + il) * s, ybot * s], fill=(255, 200, 0) if p["flanks_measured"][k] else (255, 140, 0), width=1)
        (xl, yl), (xr, yr) = p["top_left"], p["top_right"]
        d.line([xl * s, yl * s, xr * s, yr * s], fill=(255, 80, 80), width=2)
        col = m["pin_col"] if m["pin_col"] is not None else m["pin_col_raw"]
        if col is not None:
            d.line([col * s, p["tip_row_px"] * s, col * s, ybot * s], fill=(255, 80, 80) if m["usable"] else (160, 160, 160), width=1)
    d.text((6, 4), f"omega {m['omega']:+.1f} deg  pin col {m['pin_col'] if m['pin_col'] is None else round(m['pin_col'], 1)}  "
                   f"window cx {b['cx']:.1f}  [{m['status']}; {m['view']['state']}"
                   + (f"; {m['quality']}" if m["usable"] else "; NOT USED: " + "; ".join(m["reasons"])[:90]) + "]", fill=(255, 255, 255))
    im.save(path, quality=85)
