"""Stage 2 of the pin workflow: pin geometry derived from the stage-1 region (edgecone.find_pin_region_final). Nothing here searches the image globally: every measurement is made
inside / along the region (flank lines, top edge), so a wrong object cannot enter.
Image coordinates: x = column, y = row (down), px of the frame passed in."""
import numpy as np
from scipy import ndimage as ndi
from scipy.stats import siegelslopes

MIN_FLANK_DEG, MAX_FLANK_DEG = 5.0, 30.0   # pin flank half angle limits
MIN_FLANK_ROWS = 30         # inlier rows needed to call a flank 'measured'
MAX_FLANK_RMS = 2.5         # px, residual of the inliers about the fitted line
EDGE_MARGIN_PX = 6          # corners / top closer than this to the lit window's edge count as clipped
TOP_RIM_FRAC = 0.05         # ... and a top closer than this fraction of the window height to its top edge: the window's soft rim, not a pin top (a pin whose top is cut by the window top gets its
                            # rim fitted as 'top' with an inflated width; on 85 real frames the nearest tip is 0.155 of the window height from the top)


def _top_edge(g, lines, y_top, w_top):
    """Flat top: per column inside the pin, the row of the steepest bright-above / dark-below step near y_top, sub-pixel; line through them (repeated medians).
    Returns dict(slope, icpt, rms, n) or None."""
    (sl, il), (sr, ir) = lines["L"], lines["R"]
    H, W = g.shape
    if w_top < 24:
        return None
    sig = max(1.5, 0.0012 * max(H, W))
    Lg = np.log(ndi.gaussian_filter(g.astype(np.float64), sig) + 0.03 * max(np.percentile(g, 97), 1e-6))
    dy = np.gradient(Lg, axis=0)
    r0, r1 = int(max(y_top - 12 - 0.006 * H, 2)), int(min(y_top + 12 + 0.006 * H, H - 3))
    xl, xr = sl * y_top + il, sr * y_top + ir
    xs = np.arange(int(xl + 0.2 * (xr - xl)), int(xr - 0.2 * (xr - xl)), 2)
    xs = xs[(xs >= 0) & (xs < W)]
    pos, st = [], []
    for x in xs:
        col = dy[r0:r1, x]
        k = int(np.argmin(col))
        if 0 < k < len(col) - 1:
            d = col[k - 1] - 2 * col[k] + col[k + 1]
            off = 0.5 * (col[k - 1] - col[k + 1]) / d if abs(d) > 1e-12 else 0.0
        else:
            off = 0.0
        pos.append(r0 + k + off); st.append(-col[k])
    pos, st = np.array(pos), np.array(st)
    if len(pos) < 12:
        return None
    ok = st > 0.4 * np.median(st)
    if ok.sum() < 12:
        return None
    for band in (6.0, 3.0, 2.0):
        sl_t, ic_t = siegelslopes(pos[ok], xs[ok])
        res = pos - (sl_t * xs + ic_t)
        ok = ok & (np.abs(res) < band)
        if ok.sum() < 12:
            return None
    sl_t, ic_t = siegelslopes(pos[ok], xs[ok])
    return dict(slope=float(sl_t), icpt=float(ic_t), rms=float(np.sqrt(np.mean((pos[ok] - (sl_t * xs[ok] + ic_t)) ** 2))), n=int(ok.sum()))


def pin_geometry(g, res, pixel_um=None, prior=None):
    """g: the frame (2-D), res: edgecone.find_pin_region_final(g). prior: {"top_width_px": ..} learned in this run from two-flank frames (rescues one-flank frames).
    Returns a JSON-able dict: found, quality, usable, reasons, view{state,...}, pin{axis_col, tip_row, top corners, top width, half angles, axis tilt, top tilt, ...}, fov, margins."""
    if res.get("polygon") is None or not res.get("refined"):
        return {"found": False, "usable": False, "quality": None, "reasons": ["no pin region"], "view": {"state": "absent"}}
    ref = res["refined"]
    lines = ref["lines"]
    (sl, il), (sr, ir) = lines["L"], lines["R"]
    vis = ref.get("found_by_data", {})
    stats = ref.get("stats", {})
    good = {k: bool(vis.get(k)) and stats.get(k, {}).get("n_inliers", 0) >= MIN_FLANK_ROWS and stats.get(k, {}).get("rms_px", 99) <= MAX_FLANK_RMS for k in ("L", "R")}
    ang0 = {"L": float(np.degrees(np.arctan(-sl))), "R": float(np.degrees(np.arctan(sr)))}
    for k in ("L", "R"):
        if not (MIN_FLANK_DEG <= ang0[k] <= MAX_FLANK_DEG):             # a 'flank' at the wrong angle is the window edge / mottle, not the pin
            good[k] = False
    y_top, y_bot = ref["y_top"], ref["y_bottom"]
    xl0, xr0 = sl * y_top + il, sr * y_top + ir
    top = _top_edge(g, lines, y_top, xr0 - xl0)
    # virtual corners: flank lines meet the (possibly tilted) top line
    corners = {}
    if top is not None:
        m_, c_ = top["slope"], top["icpt"]                       # y = m x + c
        for k, (a_, b_) in (("L", (sl, il)), ("R", (sr, ir))):
            x = (a_ * c_ + b_) / (1 - a_ * m_)
            corners[k] = (float(x), float(m_ * x + c_))
        tip_row = float(m_ * 0.5 * (corners["L"][0] + corners["R"][0]) + c_)
    else:
        corners = {"L": (float(xl0), float(y_top)), "R": (float(xr0), float(y_top))}
        tip_row = float(y_top)
    ang = {"L": float(np.degrees(np.arctan(-sl))), "R": float(np.degrees(np.arctan(sr)))}
    width_px = corners["R"][0] - corners["L"][0]
    reasons, quality = [], None
    if good["L"] and good["R"]:
        quality, axis_col = "both_flanks", 0.5 * (corners["L"][0] + corners["R"][0])
        hw = None
    elif good["L"] or good["R"]:
        vis_side = "L" if good["L"] else "R"
        quality = "one_sided_" + ("left" if vis_side == "L" else "right")
        wp = (prior or {}).get("top_width_px")
        if wp:
            axis_col = corners[vis_side][0] + (0.5 if vis_side == "L" else -0.5) * wp
        else:
            axis_col = None
            reasons.append("one flank only and no learned top width: axis column not reliable")
        reasons.append(f"{'right' if vis_side == 'L' else 'left'} flank not measurable (hidden against a margin or off the image)")
    else:
        axis_col = None
        reasons.append("neither flank has enough consistent edge rows")
    # relation to the lit window (field of view)
    fov = res.get("fov") or (0.0, 0.0, float(g.shape[1]), float(g.shape[0]))
    x0, y0, x1, y1 = fov
    marg = {"left_px": corners["L"][0] - x0, "right_px": x1 - corners["R"][0], "top_px": tip_row - y0,
            "fov_centre": [0.5 * (x0 + x1), 0.5 * (y0 + y1)], "fov_size": [x1 - x0, y1 - y0]}
    clipped = {"top": marg["top_px"] < max(EDGE_MARGIN_PX, TOP_RIM_FRAC * (y1 - y0)), "left": marg["left_px"] < EDGE_MARGIN_PX, "right": marg["right_px"] < EDGE_MARGIN_PX}
    if clipped["top"]: reasons.append("top touches the lit window's edge")
    if clipped["left"]: reasons.append("left top corner at the lit window's edge")
    if clipped["right"]: reasons.append("right top corner at the lit window's edge")
    state = "in_view" if (quality == "both_flanks" and not any(clipped.values())) else "partial"
    px = lambda v: None if v is None or pixel_um is None else float(v * pixel_um)
    out = {"found": True, "quality": quality, "usable": bool(quality == "both_flanks" and not any(clipped.values())) or (quality or "").startswith("one_sided") and axis_col is not None and not clipped["top"],
           "reasons": reasons, "view": {"state": state, "clipped": clipped},
           "pin": {"axis_col_px": axis_col, "tip_row_px": tip_row, "top_left": corners["L"], "top_right": corners["R"], "top_width_px": float(width_px), "top_width_um": px(width_px),
                   "half_angle_left_deg": ang["L"], "half_angle_right_deg": ang["R"], "half_angle_deg": float(np.mean([ang[k] for k in ("L", "R") if good[k]] or [0.5 * (ang["L"] + ang["R"])])),
                   "axis_tilt_deg": float(np.degrees(np.arctan(0.5 * (sl + sr)))),
                   "top_tilt_deg": None if top is None else float(np.degrees(np.arctan(top["slope"]))), "top_rms_px": None if top is None else top["rms"],
                   "visible_rows": [float(y_top), float(y_bot)], "visible_height_px": float(y_bot - y_top),
                   "flank_rms_px": {k: stats.get(k, {}).get("rms_px") for k in ("L", "R")}, "flank_inlier_rows": {k: stats.get(k, {}).get("n_inliers") for k in ("L", "R")},
                   "flanks_measured": good},
           "fov": [float(v) for v in fov], "margins": marg, "lines": {"L": [float(sl), float(il)], "R": [float(sr), float(ir)]},
           "axis_offset_from_fov_centre_px": None if axis_col is None else float(axis_col - marg["fov_centre"][0]),
           "tip_depth_below_fov_top_frac": float((tip_row - y0) / max(y1 - y0, 1)),
           "region_score": float(res.get("score", 0.0))}
    return out


def pin_like(res, geo, shape):
    """Shared acceptance test: is the region + geometry something a pin can be (frame `shape` = (rows, cols))? Returns (ok, reasons). Each MEASURED flank must lean like a pin flank;
    the top width is only judged when both flanks are measured (with one flank the other side is the window edge or inferred, so its width means nothing)."""
    H, W = shape
    if not geo.get("found"):
        return False, ["no object with two long straight edges leaning like the pin's flanks"]
    p = geo["pin"]
    good = p["flanks_measured"]
    bad = []
    if not res.get("found"):
        bad.append("region score %.2f below the acceptance level" % res.get("score", 0.0))
    if not any(good.values()):
        bad.append("neither flank could be measured as a pin-like edge")
    for k, name, key in (("L", "left", "half_angle_left_deg"), ("R", "right", "half_angle_right_deg")):
        if good[k] and not (MIN_FLANK_DEG <= p[key] <= MAX_FLANK_DEG):
            bad.append("%s flank half-angle %.1f deg is not pin-like" % (name, p[key]))
    if good["L"] and good["R"] and not (0.015 * W <= p["top_width_px"] <= 0.35 * W):
        bad.append("top width %.0f px is not pin-like for this frame" % p["top_width_px"])
    if p["visible_height_px"] < 0.08 * H:
        bad.append("only %.0f px of pin height visible" % p["visible_height_px"])
    return (not bad), bad
