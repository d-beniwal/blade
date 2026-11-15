"""Tomo-camera procedures: exposure, finding and centring the beam, steering check (interface: blade/instrument/base.py)."""
import math
import numpy as np
from ..analysis.frame import analyze_frame
from ._util import accepts_world


@accepts_world
def tune_exposure(inst, cam, target=0.35, apply=True):
    """Set the camera exposure so the brightest part of the beam reaches `target` of the camera's nominal full scale (operators lengthen the exposure to find a
    dim beam and shorten it when the core saturates). Iterates a few times from the current exposure. Returns the exposure (s)."""
    cc = inst.sim["cameras"][cam]
    exp = inst.ctl(f"{cam}.exposure")
    peak = 0.0
    for _ in range(5):
        img = inst.frame(cam, exposure=exp, bin_=4).astype(np.float32)
        peak = float(np.percentile(img, 99.5)) - cc["bg"]
        if peak > 60000 - cc["bg"]:                       # saturated: the real brightness is unknown, back off
            exp = max(exp / 8.0, 0.002)
            continue
        if peak <= 20:
            if exp >= 10.0:
                return {"ok": False, "reason": "no signal even at 10 s: the beam is not on the camera", "exposure_s": inst.ctl(f"{cam}.exposure")}
            exp = min(exp * 8.0, 10.0)
            continue
        new = float(np.clip(round(exp * target * cc["full"] / peak, 4), 0.002, 10.0))
        if abs(math.log(new / exp)) < 0.12:
            exp = new
            break
        exp = new
    if apply:
        inst.set(f"{cam}.exposure", exp)
    return {"ok": True, "exposure_s": exp}


@accepts_world
def find_beam_on_camera(inst, cam, half_range_mm=3.0, step_mm=None, centre=True):
    """Bring the tomo camera in and move it until the beam is on the sensor (the operators go to x~0, then X/Y). Searches a raster around 0 with a long
    (>= 1 s) exposure so a still-unoptimised beam is seen; returns the first stage position where the beam is seen, with the frame analysis (at the
    camera's own exposure). The first sighting is usually the beam's corner at the frame edge, so by default (`centre`) the stage is then moved to put the
    footprint in the middle of the frame (what the operators do: "found beam ... beam centre desired ..."). Leaves the camera there."""
    cc = inst.sim["cameras"][cam]
    st = cc["stage"]
    p = inst.cams[cam]["pixel_um"] * 1e-3
    fov_x, fov_y = cc["cols"] * p, cc["rows"] * p
    step = step_mm or 0.6 * min(fov_x, fov_y)
    sp = inst.spec(f"{st}.x")
    xs = [x for x in np.arange(-half_range_mm, half_range_mm + 1e-9, step) if sp[0] <= x <= sp[1]]
    ys = np.arange(-half_range_mm, half_range_mm + 1e-9, step)
    xs = sorted(xs, key=abs)
    inst.set(f"{st}.x", float(xs[0]))
    tried = 0
    for y in sorted(ys, key=abs):
        inst.set(f"{st}.y", float(np.clip(y, *inst.spec(f"{st}.y")[:2])))
        for x in xs:
            inst.set(f"{st}.x", float(x))
            tried += 1
            an = analyze_frame(inst.frame(cam, exposure=max(inst.ctl(f"{cam}.exposure"), 1.0), bin_=4), p * 4e3)      # long exposure while searching
            if an.get("beam"):
                te = tune_exposure(inst, cam)
                seen = {"x_mm": inst.ctl(f"{st}.x"), "y_mm": inst.ctl(f"{st}.y")}
                cen = centre_camera_on_beam(inst, cam, "footprint") if centre else None
                return {"found": True, "stage": st, "x_mm": inst.ctl(f"{st}.x"), "y_mm": inst.ctl(f"{st}.y"), "first_seen_at": seen,
                        "centred": bool(cen and cen.get("ok")), "positions_tried": tried, "exposure_s": inst.ctl(f"{cam}.exposure"),
                        "analysis": analyze_frame(inst.frame(cam), p * 1e3)}
    return {"found": False, "positions_tried": tried}


@accepts_world
def centre_camera_on_beam(inst, cam, which="hotspot", iterations=8):
    """Move the tomo stage so the hotspot (or footprint centre) sits at the middle of the frame, as the operators do before zeroing X,Y."""
    cc = inst.sim["cameras"][cam]
    st = cc["stage"]
    p = inst.cams[cam]["pixel_um"] * 1e-3
    sg = inst.sim["tomo_stages"]
    last = None
    for _ in range(iterations):
        tune_exposure(inst, cam)
        an = analyze_frame(inst.frame(cam, bin_=2), p * 2e3)
        if not an.get("beam"):
            return {"ok": False, "reason": "no beam in the frame; use find_beam_on_camera"}
        if which == "hotspot":
            px = an["hotspot_px"]
        else:                                   # footprint: centre of its bounding box (the centroid of a beam cut by the frame edge is biased inward)
            b = an["box_px"]
            px = {"x": (b["x0"] + b["x1"]) / 2.0, "y": (b["y0"] + b["y1"]) / 2.0}
        dx_px = px["x"] * 2 - (cc["cols"] - 1) / 2.0
        dy_px = px["y"] * 2 - (cc["rows"] - 1) / 2.0
        inst.set(f"{st}.x", float(np.clip(inst.ctl(f"{st}.x") + sg["xsign"] * dx_px * p, *inst.spec(f"{st}.x")[:2])))
        inst.set(f"{st}.y", float(np.clip(inst.ctl(f"{st}.y") - sg["ysign"] * dy_px * p, *inst.spec(f"{st}.y")[:2])))
        last = (dx_px, dy_px)
        if abs(dx_px) < 3 and abs(dy_px) < 3 and not an["touches_frame"]:
            break
    an = analyze_frame(inst.frame(cam), p * 1e3)
    return {"ok": True, "stage": st, "x_mm": inst.ctl(f"{st}.x"), "y_mm": inst.ctl(f"{st}.y"), "residual_px": last, "analysis": an}


@accepts_world
def steering_check(inst, cam):
    """Compare the hotspot with the centre of the WB-slit image on the tomo (open all other slits first). Returns the offset in px/mm and the steering
    change (urad) that would remove it - the 'request orbit steering' step of the logs. Does not move anything."""
    p = inst.cams[cam]["pixel_um"] * 1e-3
    an = analyze_frame(inst.frame(cam), p * 1e3)
    if not an.get("beam"):
        return {"ok": False, "reason": "no beam on the camera"}
    zc = inst.camera_z_m(cam)
    if an["touches_frame"]:
        return {"ok": False, "reason": "the footprint is not fully inside the frame: centre the camera on it first (centre_camera_on_beam which='footprint'), or the WB image is larger than the field of view", "analysis": an}
    b = an["box_px"]
    cx, cy = (b["x0"] + b["x1"]) / 2.0, (b["y0"] + b["y1"]) / 2.0
    dx, dy = (an["hotspot_px"]["x"] - cx) * p, -(an["hotspot_px"]["y"] - cy) * p      # mm, hotspot minus footprint centre (u right, v up)
    return {"ok": True, "hotspot_minus_footprint_mm": {"h": dx, "v": dy}, "hotspot_minus_footprint_px": {"h": dx / p, "v": -dy / p},
            "suggested_steering_urad": {"xp": -dx * 1e3 / zc, "yp": -dy * 1e3 / zc},     # mm / m = mrad -> x1e3 = urad
            "note": "steering moves the hotspot; the footprint is fixed by the slits. Apply only part of it, then re-measure (a hotspot offset of <10-15 px is accepted).",
            "footprint_box_px": b}
