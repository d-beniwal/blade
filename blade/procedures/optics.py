"""Focus procedures: camera objective focus and lens tilt scans (interface: blade/instrument/base.py)."""
import numpy as np
from scipy.ndimage import gaussian_filter
from ..analysis.frame import analyze_frame, fit_peak
from ._util import accepts_world


@accepts_world
def focus_camera(inst, cam, half_range_mm=0.4, n=17):
    """Camera objective focus: scan the focus motor and maximise edge sharpness of the beam footprint (mean gradient magnitude)."""
    f0 = inst.ctl(f"{cam}.focus")
    xs = np.linspace(f0 - half_range_mm, f0 + half_range_mm, n)
    metric = []
    for x in xs:
        inst.set(f"{cam}.focus", float(x))
        img = inst.frame(cam, bin_=2).astype(np.float32)
        gy, gx = np.gradient(gaussian_filter(img, 1.0))
        metric.append(float(np.mean(np.hypot(gx, gy))))
    pk, _ = fit_peak(xs, metric)
    inst.set(f"{cam}.focus", pk)
    return {"focus_mm": xs.tolist(), "sharpness": metric, "best_focus_mm": pk}


@accepts_world
def lens_scan(inst, lens, cam, half_range_deg=0.05, n=21):
    """Tilt scan of a lens: the focused beam on the tomo is narrowest at the best tilt; metric = footprint area / peak (smaller = better focus)."""
    from ..physics import lens as plens
    L = plens.LENSES_1ID[lens]
    motor = "th" if L["orientation"] in ("upr", "up", "inv", "down") else "phi"
    p = inst.cams[cam]["pixel_um"] * 1e-3
    c0 = inst.ctl(f"{lens}.{motor}")
    xs = np.linspace(c0 - half_range_deg, c0 + half_range_deg, n)
    size = []
    for x in xs:
        inst.set(f"{lens}.{motor}", float(x))
        img = inst.frame(cam, bin_=2).astype(np.float32)
        an = analyze_frame(img, p * 2e3)
        size.append(float(an["box_px"]["height" if motor == "th" else "width"]) if an.get("beam") else float("nan"))
    s = np.array(size, float)
    ok = np.isfinite(s)
    best = float(xs[ok][np.argmin(s[ok])]) if ok.any() else c0
    inst.set(f"{lens}.{motor}", best)
    return {"motor": motor, "tilt_deg": xs.tolist(), "size_px": size, "best_tilt_deg": best, "predicted_tilt_deg": plens.focus_motor_target(lens, inst.ctl("hem.energy"))[1]}
