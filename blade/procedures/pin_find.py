"""Bring the alignment pin into view of the E-station tomo camera - using the 3-D mount model as the search aid.

Problem: the tip of the pin is a ~0.1 mm target; the lit window of the tomo camera is ~1 mm; the pin height changes with every mount (logged samYE of the pins in view spans
0.04-20 mm) and the rotation axis moves by up to ~1.3 mm between cycles. Searching for the tip in (x, y) is a 2-D raster. The mount is not just a pin, though: the brass
chuck below it is ~7 mm wide and opaque at 50-90 keV, and it sits a known distance (`protrusion_mm`, from the mount model) under the tip. So:

  1. reference frame with the pin parked sideways (clear beam) -> the lit window;
  2. raise the stage in steps of 0.7 window heights until anything shadows the window (the tip if it is laterally inside the window, else the chuck's top edge);
  3. chuck found -> scan aero X: the shadowed interval is chuck width + window wide, its middle is the pin axis -> centre it;
  4. lower the stage by the protrusion and scan +-1 mm: the pin tip is in view when the shadow is narrow and its top lies inside the window.
A 2-D raster needs (y range / step) x (x range / step) frames; this needs their SUM.
REACH LIMIT (found 2026-11-15 with the real alignment files, pin tip on the beam at samY = 25.65 mm, travel limit 29.81 mm): the chuck's top edge reaches the beam at samE.y = (tip-on-beam y) + protrusion,
so the chuck trick needs tip-on-beam y <= y_max - protrusion (~24.8 mm). Above that only a pin already inside the tip's own lateral capture (|axis - beam| < ~window/2 + pin radius) is found; the search then
reports 'nothing shadowed the window'. A taller mount (lower tip) or a lower samY zero is needed for the wide-target search.

`plan_pin_search` is read-only (runs on any instrument, also the real one: it only reads controls and static knowledge) and returns the window, the search ranges and the frame
budget; `find_pin` executes the search and needs a writable instrument (the simulator; on the real beamline `set` raises ReadOnlyError - BLADE only proposes there)."""
import math
import numpy as np
from scipy import ndimage
from ._util import accepts_world
from ..physics import pin_mount

BIN = 4
THR_FRAC = 0.02
LIT_FRAC = 0.15


def _geom(inst, cam):
    """Static + read-back geometry: pixel (mm, at BIN), prior block, mount, the E slit / WB gap read-backs."""
    sE = inst.sim["stage_E"]
    p = inst.cams[cam]["pixel_um"] * 1e-3 * BIN
    return sE, sE["pin"]["search_prior"], pin_mount.from_sim(inst.sim), p


def plan_pin_search(inst, cam="gh1"):
    """READ-ONLY search plan from the current settings: expected lit window, ranges to search (from the logs' priors) and the number of frames needed with and without
    the chuck trick. Moves nothing."""
    sE, pri, M, _ = _geom(inst, cam)
    cc = inst.sim["cameras"][cam]
    pix = inst.cams[cam]["pixel_um"] * 1e-3
    fov_h, fov_v = cc["cols"] * pix, cc["rows"] * pix
    wb_h, wb_v = inst.ctl("wbSlits.hsize"), inst.ctl("wbSlits.vsize")
    e_h, e_v = inst.ctl("slitEus.hsize"), inst.ctl("slitEus.vsize")
    win_h = min(pri["wb_footprint_mag"] * wb_h, pri["kohzu_E_mag"] * e_h, fov_h)
    win_v = min(pri["wb_footprint_mag"] * wb_v, pri["kohzu_E_mag"] * e_v, fov_v)
    tip_w = M.p["pin"]["top_width_um"] * 1e-3
    y_lo, y_hi = inst.spec("samE.y")[:2]
    x_half = pri["aerox_prior_halfwidth_mm"]
    step_y, step_x = 0.7 * win_v, 0.7 * win_h
    ny = math.ceil((y_hi - y_lo) / step_y) + 1
    x_range = 2 * (x_half + M.chuck_radius_mm() + 0.5 * win_h)
    nx_chuck = math.ceil(x_range / step_x) + 1
    capture_tip = win_h + tip_w                                    # lateral window in which the bare tip is seen
    nx_tip = math.ceil(2 * x_half / capture_tip) + 1
    return {
        "moves_anything": False,
        "lit_window_mm": {"h": win_h, "v": win_v, "from": "min(WB gap x footprint magnification, E slit opening, camera FOV)"},
        "ranges": {"samE.y": [y_lo, y_hi], "samE.aerox_centre": pri["aerox_prior_mm"], "samE.aerox_half_width": x_half,
                   "real_aerox_dial_prior_mm": "-3.0 +- 0.3 (recent cycles; dial coordinate, see sim.json search_prior.aerox_src)"},
        "steps": ["clear-beam reference with the pin parked sideways", f"raise samE.y in {step_y:.2f} mm steps until the window is shadowed",
                  f"scan samE.aerox in {step_x:.2f} mm steps over +-{x_range / 2:.1f} mm: the middle of the shadowed interval is the pin axis",
                  f"lower samE.y by the pin protrusion ({M.p['pin']['protrusion_mm']:.1f} mm, +-20 % photo estimate) and scan +-1 mm"],
        "frames_with_chuck": ny + nx_chuck + 6,
        "frames_tip_only_raster": ny * nx_tip,
        "tip_only_note": "tip-only search needs the pin axis within the tip capture width; the chuck trick tolerates the axis anywhere within chuck radius + window of the beam",
        "mount": {"tip_height_above_plate_mm": M.tip_height_mm, "chuck_radius_mm": M.chuck_radius_mm(), "chuck_top_below_tip_mm": M.part_tip_offset_mm("chuck", "top")},
        "uncertainty": "mount dimensions are photo estimates (sim.json stage_E.pin.mount._note); the logged pin heights span 20 mm, so y is always searched",
    }


class _Look:
    """One camera look: shadow of the pin/mount against the clear-beam reference."""
    def __init__(self, inst, cam, ref, bg):
        self.inst, self.cam, self.ref, self.bg = inst, cam, ref, bg
        self.lit = ref > bg + LIT_FRAC * (np.percentile(ref, 99.5) - bg)      # the whole footprint, not just the hot core (the tip often sits in the dim part)
        self.rows, self.cols = np.nonzero(self.lit)
        self.n_lit = max(int(self.lit.sum()), 1)
        sm = ndimage.gaussian_filter(ref, 3.0)                                      # the WINDOW that sizes the search steps: where the beam is above ~40 % of its peak
        core = sm > bg + 0.4 * (np.percentile(sm, 99.5) - bg)
        cy, cx = np.nonzero(core)
        self.core_r0 = int(cy.min()) if cy.size else int(self.rows.min())
        self.core_c0 = int(cx.min()) if cx.size else int(self.cols.min())
        self.core_w = int(cx.max() - cx.min() + 1) if cx.size else int(self.cols.max() - self.cols.min() + 1)
        self.core_h = int(cy.max() - cy.min() + 1) if cy.size else int(self.rows.max() - self.rows.min() + 1)
        self.frames = 0

    def shot(self):
        """Look once: shadow fraction of the lit window and the geometry of its LARGEST connected piece (stray specks / window-edge slivers are ignored)."""
        img = self.inst.frame(self.cam, bin_=BIN).astype(np.float32)
        self.frames += 1
        sh = self.lit & (img < self.bg + 0.5 * (self.ref - self.bg))
        out = {"f": float(sh.sum()) / self.n_lit, "mask": sh}
        if sh.any():
            lab, n = ndimage.label(sh)
            big = lab == (1 + int(np.argmax(ndimage.sum(sh, lab, range(1, n + 1)))))
            ys, xs = np.nonzero(big)
            width = big.sum(axis=1)
            t = int(ys.min())
            cc = np.nonzero(big[t:t + 6].any(axis=0))[0]
            above = ~sh[max(t - 14, 0):max(t - 2, 0), int(cc.min()):int(cc.max()) + 1]
            out["lit_above"] = float(above.mean()) if above.size >= 10 and t >= 16 else 0.0          # lit pixels right above the top: the top is a real tip, not a clipped shaft
            out.update({"top_row": int(ys.min()), "bottom_row": int(ys.max()), "x_min": int(xs.min()), "x_max": int(xs.max()), "max_row_width": int(width.max()),
                        "top_width": float(width[int(ys.min()):int(ys.min()) + 6].mean()), "top_centre_col": float(xs[ys <= ys.min() + 6].mean())})
        return out

    @property
    def lit_w(self):
        return int(self.cols.max() - self.cols.min() + 1)

    @property
    def lit_h(self):
        return int(self.rows.max() - self.rows.min() + 1)


@accepts_world
def find_pin(inst, cam="gh1", max_frames=120):
    """Execute the search (writable instrument only). Returns {found, controls: {samE.y, samE.aerox}, tip_px, frames, log}. Leaves the stage at the best position."""
    sE, pri, M, p = _geom(inst, cam)
    log = []
    bg = float(inst.sim["cameras"][cam]["bg"])
    xs_lo, xs_hi = inst.spec("samE.aerox")[:2]
    yl, yh = inst.spec("samE.y")[:2]
    x0 = float(np.clip(pri["aerox_prior_mm"], xs_lo, xs_hi))
    park = sE["pin"]["park_aerox_mm"]
    # 1. clear-beam reference
    inst.set("samE.aerox", float(np.clip(x0 + park, xs_lo, xs_hi)))
    ref = inst.frame(cam, bin_=BIN).astype(np.float32)
    inst.set("samE.aerox", x0)
    if float(np.percentile(ref, 99.5)) - bg < 0.05 * max(bg, 1.0):
        return {"found": False, "reason": "no beam on the camera in the reference frame (find the beam first)", "frames": 1, "log": log}
    L = _Look(inst, cam, ref, bg)
    L.frames = 1
    win_v_mm, win_h_mm = L.core_h * p, L.core_w * p
    log.append({"step": "reference", "lit_window_mm": [round(win_h_mm, 3), round(win_v_mm, 3)], "note": "half-maximum window; steps are sized by it"})
    prot = M.p["pin"]["protrusion_mm"]
    # 2. raise until something shadows the window. The chuck (21 mm tall, opaque) keeps shadowing it once it has entered, so coarse steps of ~the protrusion cannot skip it;
    #    then bisect back to where the shadow starts.
    step_c = max(0.8 * prot, 0.7 * win_v_mm)
    hit = None
    for y in list(np.arange(yl, yh, step_c)) + [yh]:                     # always include the top of the travel
        inst.set("samE.y", float(y))
        r = L.shot()
        if r["f"] > THR_FRAC:
            hit = (float(y), r)
            break
        if L.frames > max_frames:
            break
    if hit is None:
        return {"found": False, "reason": "nothing shadowed the window over the whole samE.y range at the prior aero X", "frames": L.frames, "log": log}
    lo, hi, r = max(hit[0] - step_c, yl), hit[0], hit[1]
    while hi - lo > 0.5 * win_v_mm:
        mid = 0.5 * (lo + hi)
        inst.set("samE.y", float(mid))
        rm = L.shot()
        if rm["f"] > THR_FRAC:
            hi, r = mid, rm
        else:
            lo = mid
    hit = (hi, r)
    y_hit, r = hit
    log.append({"step": "first shadow", "samE.y": round(y_hit, 3), "shadow_fraction": round(r["f"], 3),
                "meaning": "the highest part of the mount that is laterally in the window: the tip, the shaft, or the chuck's top edge (the tip is then at most `protrusion` above)"})
    # 3. aero X scan at this height: whatever is in the beam (tip, shaft, chuck), the middle of the shadowed interval is the pin axis
    y_scan = min(y_hit + 0.3 * win_v_mm, yh)
    inst.set("samE.y", float(y_scan))
    half = pri["aerox_prior_halfwidth_mm"] + M.chuck_radius_mm() + 0.5 * win_h_mm
    step_x = max(0.7 * win_h_mm, 0.1)
    xs = [x for x in np.arange(x0 - half, x0 + half + 1e-9, step_x) if xs_lo <= x <= xs_hi]
    hits = []
    for x in xs:
        inst.set("samE.aerox", float(x))
        if L.shot()["f"] > THR_FRAC:
            hits.append(float(x))
        if L.frames > max_frames:
            break
    if not hits:
        return {"found": False, "reason": "the shadow vanished during the aero X scan", "frames": L.frames, "log": log}
    xc = 0.5 * (min(hits) + max(hits))
    inst.set("samE.aerox", float(np.clip(xc, xs_lo, xs_hi)))
    width = max(hits) - min(hits) + step_x - win_h_mm
    log.append({"step": "aero X scan", "shadowed_from_to": [round(min(hits), 3), round(max(hits), 3)], "axis_on_beam_at": round(xc, 3), "resolution_mm": round(step_x, 3),
                "object_width_mm": round(width, 2), "object": "chuck" if width > 2.0 * M.p["pin"]["shaft_diameter_mm"] + 1.0 else "pin / shaft"})
    # 4. the tip is the highest point of the mount: it is at most `protrusion` above where the shadow first appeared. Lower the stage until a narrow tip sits inside the window.
    ys_main = [v for v in np.arange(y_scan - 0.6 * prot, y_scan - prot - 1.5 - 1e-9, -0.5 * win_v_mm) if yl <= v <= yh]       # where the tip should be (protrusion +-40 %) first
    ys_rest = [v for v in np.arange(y_scan, y_scan - 0.6 * prot + 1e-9, -0.5 * win_v_mm) if yl <= v <= yh]                    # then the part nearest the first shadow
    ys = ys_main + ys_rest
    best = None
    for v in ys:
        inst.set("samE.y", float(v))
        r = L.shot()
        if r["f"] <= THR_FRAC:
            continue
        top_margin = (r["top_row"] - L.core_r0) / L.core_h                      # tip inside the half-maximum window (solid beam), away from its top edge
        inside_x = r["x_min"] > L.core_c0 and r["x_max"] < L.core_c0 + L.core_w         # whole silhouette laterally inside the window
        narrow = r["top_width"] < 0.5 * L.core_w
        if narrow and inside_x and top_margin >= 0.1 and r["f"] < 0.5 and r["lit_above"] > 0.8:      # a tip leaves most of the window lit; a window filled by the chuck is not a tip
            best = (top_margin, v, r)
            break                                                           # first stage position (coming down) that shows the whole tip
    if best is None:
        return {"found": False, "reason": "no narrow tip fully inside the lit window while lowering the stage", "frames": L.frames, "log": log}
    _, v, r = best
    inst.set("samE.y", float(v))
    # lateral polish: the tip's offset from the window centre, undone with aero X (static sign/scale `col_per_base`: mm of image shift per mm of aero X)
    kb = float(sE["col_per_base"])
    lit_c = L.core_c0 + 0.5 * L.core_w
    for _ in range(2):
        r = L.shot()
        if r["f"] <= THR_FRAC:
            break
        dx_mm = (r["top_centre_col"] - lit_c) * p
        if abs(dx_mm) < 0.04:
            break
        inst.set("samE.aerox", float(np.clip(inst.ctl("samE.aerox") - dx_mm / kb, xs_lo, xs_hi)))
    r = L.shot()
    if r["f"] <= THR_FRAC or r["f"] >= 0.5 or r["lit_above"] < 0.8 or r["top_row"] < L.core_r0 + 0.05 * L.core_h:
        return {"found": False, "reason": "the tip left the window during the lateral polish", "frames": L.frames, "log": log}
    cx = r["top_centre_col"]
    tip_px = {"x": float(cx), "y": float(r["top_row"]), "frame_shape": list(ref.shape)}
    off_mm = (cx - lit_c) * p
    log.append({"step": "fine y scan + lateral polish", "samE.y": round(inst.ctl("samE.y"), 3), "tip_offset_from_window_centre_mm": round(off_mm, 3)})
    return {"found": True, "controls": {"samE.y": inst.ctl("samE.y"), "samE.aerox": inst.ctl("samE.aerox")}, "tip_px_bin4": tip_px, "tip_offset_from_window_centre_mm": off_mm,
            "frames": L.frames, "log": log}
