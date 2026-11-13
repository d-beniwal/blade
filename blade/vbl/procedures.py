"""Operator-level procedures on the virtual beamline: the scans and image measurements that the logbooks describe, plus the whole start-of-beamtime
sequence. They use ONLY what an operator can observe (IC counts, mu_t, camera frames); the hidden truth enters only through `readiness()`, which
scores the result (tests / debugging).

Order of the start-of-beamtime sequence (from 25 user logs, see playbooks/virtual_beamline.md and beamline_twins/1-ID/physics/09_alignment_procedure.md):
  energy + flux: gap scan (high -> low) -> Th2 tweak -> foil edge scan (E_scan) -> energy so that mu_t = b -> Th2/gap again
  beam on the tomo camera -> steering vs the WB-slit image -> Kohzu slits centred on the hotspot (closed to 0.1 mm, tomo image) -> camera focus
  -> (rotation axis with the pin: `blade align`, the same code that runs on the real stage)."""
import math
import numpy as np
from scipy.optimize import curve_fit
from scipy.ndimage import gaussian_filter, gaussian_filter1d
from scipy.special import erf
from ..physics import core as pcore, undulator as pund
from . import imaging
from .world import SLIT_IDS, FS_IDS, LENS_IDS


# ------------------------------------------------------------------------------------------------------------------------------ image analysis
def _hotspot(a, bg, blk=8):
    """Hotspot (px): centroid of the brightest part of the heavily smoothed image (robust against the +-20 % mottle that moves a plain argmax around)."""
    h, w = (a.shape[0] // blk) * blk, (a.shape[1] // blk) * blk
    b = a[:h, :w].reshape(h // blk, blk, w // blk, blk).mean((1, 3)) - bg
    sm = gaussian_filter(b, 400.0 / (blk * 2.0) * 0.5 if False else 5.0)
    m = sm > 0.85 * sm.max()
    ys, xs = np.nonzero(m)
    wts = sm[m]
    return int((xs * wts).sum() / wts.sum() * blk + blk / 2), int((ys * wts).sum() / wts.sum() * blk + blk / 2)


def _gauss_centre(p, i0, i1):
    """Centre of a Gaussian beam seen through a window [i0, i1] (the footprint): log-parabola fit over the inner 80 % of the window, the way the logs fit
    the hotspot (Gaussian fit). Returns None if the profile shows no curvature (flat/ambiguous)."""
    n = i1 - i0 + 1
    if n < 40:
        return None
    lo, hi = int(i0 + 0.1 * n), int(i1 - 0.1 * n)
    x = np.arange(lo, hi + 1, dtype=float)
    y = p[lo:hi + 1].astype(float)
    if y.max() <= 0 or (y <= 0).any():
        return None
    try:
        c = np.polyfit(x - x.mean(), np.log(y), 2, w=y / y.max())
    except Exception:
        return None
    if c[0] >= -1e-9:
        return None
    mu = -c[1] / (2 * c[0]) + x.mean()
    return float(mu) if (lo - 0.5 * n <= mu <= hi + 0.5 * n) else None


def analyze_frame(img, pixel_um=1.0):
    """What an operator reads off a tomo frame: is the beam there, where is its footprint, the hotspot, the edge widths and the saturation.
    Positions are in pixels (col, row) of the frame."""
    a = img.astype(np.float32)
    bg = float(np.percentile(a, 20))
    sm = gaussian_filter(a, 6.0)
    peak = float(np.percentile(sm, 99.7))
    noise = float(sm[sm <= np.percentile(sm, 50)].std()) + 1.0
    if peak - bg < max(8.0 * noise, 0.04 * bg):
        return {"beam": False, "background": bg, "max": float(a.max())}
    thr = bg + 0.12 * (peak - bg)
    mask = sm > thr
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    hx, hy = _hotspot(a, bg)
    gx = _gauss_centre(sm[y0 + (y1 - y0) // 5: y1 - (y1 - y0) // 5 + 1, :].mean(0) - bg, x0, x1)
    gy = _gauss_centre(sm[:, x0 + (x1 - x0) // 5: x1 - (x1 - x0) // 5 + 1].mean(1) - bg, y0, y1)
    if gx is not None and gy is not None:
        hx, hy = gx, gy
    fine = gaussian_filter(a, 1.0)                                  # edge widths from a lightly smoothed frame (the 6 px smoothing above would add to them)
    prof_x = fine[y0 + (y1 - y0) // 4: y1 - (y1 - y0) // 4 + 1, :].mean(0) - bg
    prof_y = fine[:, x0 + (x1 - x0) // 4: x1 - (x1 - x0) // 4 + 1].mean(1) - bg

    def edge_width(p, i_edge, inside_sign):
        """10-90 % width (px) of the edge near index i_edge on profile p (inside_sign=+1: beam on the +index side)."""
        i_edge = min(max(i_edge, 0), len(p) - 1)
        i0 = max(i_edge - 200, 0)
        i1 = min(i_edge + 200, len(p) - 1)
        seg = p[i0:i1 + 1] if inside_sign > 0 else p[i0:i1 + 1][::-1]
        k_edge = (i_edge - i0) if inside_sign > 0 else (i1 - i_edge)              # index of the footprint edge in `seg`
        # the beam is not flat-topped (hot core, mottle): 100 % is the shelf where the edge ramp ends, found by walking inward from the steepest
        # gradient until the rise flattens (< 20 % of its peak), not the global maximum
        sm_ = gaussian_filter1d(seg.astype(float), 10.0)
        gr = np.gradient(sm_)
        lo_k, hi_k = max(k_edge - 60, 0), min(k_edge + 60, len(seg) - 1)
        g = lo_k + int(np.argmax(gr[lo_k:hi_k + 1]))
        j = g
        while j < len(seg) - 6 and np.max(gr[j:j + 6]) > 0.2 * gr[g]:
            j += 1
        top = float(sm_[j])
        lo, hi = 0.1 * top, 0.9 * top
        try:
            a10 = int(np.argmax(seg > lo))
            a90 = int(np.argmax(seg > hi))
            return float(abs(a90 - a10))
        except Exception:
            return float("nan")

    sat = float((a >= 65000).mean())
    return {"beam": True, "background": bg, "max": float(a.max()), "saturated_fraction": sat,
            "box_px": {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "width": x1 - x0 + 1, "height": y1 - y0 + 1},
            "box_mm": {"width": (x1 - x0 + 1) * pixel_um * 1e-3, "height": (y1 - y0 + 1) * pixel_um * 1e-3},
            "centroid_px": {"x": float(xs.mean()), "y": float(ys.mean())}, "hotspot_px": {"x": int(hx), "y": int(hy)},
            "edge_width_10_90_px": {"left": edge_width(prof_x, x0, +1), "right": edge_width(prof_x, x1, -1), "top": edge_width(prof_y, y0, +1),
                                    "bottom": edge_width(prof_y, y1, -1)},
            "touches_frame": bool(x0 <= 2 or y0 <= 2 or x1 >= a.shape[1] - 3 or y1 >= a.shape[0] - 3),
            "mean_in_beam": float(a[mask].mean()), "pixel_um": pixel_um}


def grab(world, cam, exposure=None, bin_=1):
    return imaging.render(world, cam, exposure=exposure, bin_=bin_)


def _fit_peak(x, y):
    """Peak position of a noisy scan by a Gaussian fit (falls back to the max)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    i = int(np.argmax(y))
    try:
        f = lambda t, a, m, s, c: a * np.exp(-0.5 * ((t - m) / s) ** 2) + c
        p, _ = curve_fit(f, x, y, p0=[y.max() - y.min(), x[i], (x.max() - x.min()) / 8.0, y.min()], maxfev=4000)
        if x.min() <= p[1] <= x.max():
            return float(p[1]), float(abs(p[2]) * 2.3548)
    except Exception:
        pass
    return float(x[i]), float("nan")


# ------------------------------------------------------------------------------------------------------------------------------ energy / flux
def open_gap(world, gap=9.5):
    """'Open to ~9.5 mm first, then setundgap': approach the working gap from the open side so the hysteresis is repeatable."""
    world.set("und.gap", max(world.ctl("und.gap"), gap) + 0.3)


def nominal_gap(world, E_keV=None, apply=False):
    """Gap for the best harmonic at the mono energy from the (inferred) period: the operator's starting guess before a gap scan."""
    E = world.ctl("hem.energy") if E_keV is None else E_keV
    u = world.sim["undulator"]
    best = None
    for k in world.harmonics():
        try:
            g = pund.gap_for_energy_mm(E, k, u["period_mm"])
        except ValueError:
            continue
        a = world.harm_amp(k, g)
        if g >= u["gap_limits_mm"][0] and (best is None or a > best[1]):
            best = (g, a, k)
    if best is None:
        raise ValueError("no harmonic reaches this energy inside the gap limits")
    if apply:
        world.set("und.gap", float(best[0]))
    return {"gap_mm": best[0], "harmonic": best[2], "E_keV": E, "applied": bool(apply)}


def gap_scan(world, centre, half_range=0.2, n=40, ic="icB1", apply=True):
    """undscangap: scan the gap high -> low around `centre` against an IC at the current mono energy; returns the curve and the peak; with apply=True
    sets the gap to the fitted peak (approached from the open side, as the logs insist)."""
    gaps = np.linspace(centre + half_range, centre - half_range, n)
    world.set("und.gap", min(gaps[0] + 0.3, world.sim["undulator"]["gap_limits_mm"][1]))      # open first
    counts = []
    for g in gaps:
        world.set("und.gap", float(g))
        world.advance(1.0)
        counts.append(world.ic_kHz(ic))
    pk, fwhm = _fit_peak(gaps, counts)
    if apply:
        world.set("und.gap", min(pk + 0.3, world.sim["undulator"]["gap_limits_mm"][1]))
        world.set("und.gap", pk)
    return {"gap": gaps.tolist(), "counts_kHz": [round(c, 2) for c in counts], "peak_gap_mm": pk, "fwhm_mm": fwhm, "max_kHz": float(max(counts)), "ic": ic, "applied": apply}


def th2_scan(world, half_range=0.004, n=21, ic="icB1", apply=True):
    """Tweak Th2 across +-half_range deg (the logs only tweak by hand in 0.0002 deg steps; a scan is the same thing done systematically)."""
    c0 = world.ctl("hem.th2_offset")
    xs = np.linspace(c0 - half_range, c0 + half_range, n)
    vals = []
    for x in xs:
        world.set("hem.th2_offset", float(x))
        vals.append(world.ic_kHz(ic))
    pk, fwhm = _fit_peak(xs, vals)
    world.set("hem.th2_offset", pk if apply else c0)
    return {"th2_offset": xs.tolist(), "counts_kHz": [round(v, 2) for v in vals], "peak_th2_offset_deg": pk, "fwhm_deg": fwhm, "applied": apply}


def select_edge(world, element="Re"):
    """Set the HEM energy readout to the tabulated K-edge energy of the foil (the energy the operator works at for that edge; the true edge is offset by
    the hidden energy miscalibration, which E scan / calibrate energy then find)."""
    E = float(pcore.edge_keV(element))
    world.set("hem.energy", E)
    return {"element": element, "edge_keV": round(E, 4), "hem.energy": E}


def edge_scan(world, element="Re", half_range_keV=0.12, n=49, apply=False):
    """E_scan: with the foil in, step the HEM energy across the foil K edge, record mu_t, fit mu_t(E) = dif + b*(1+erf((E-pos)/wid))/2 (the beamline's
    E_scan.gpl form). Returns the fit and the energy at which mu_t = b (the operators' calibrated energy). Restores foil/energy unless apply=True."""
    e0 = world.ctl("hem.energy")
    foil0 = world.ctl("foilB.pos")
    world.set("foilB.pos", element)
    Es = np.linspace(e0 - half_range_keV, e0 + half_range_keV, n)
    mu = []
    for E in Es:
        world.set("hem.energy", float(E))
        world.advance(5.0)
        mu.append(world.mu_t())
    mu = np.array(mu, float)
    f = lambda E, dif, b, pos, wid: dif + b * 0.5 * (1 + erf((E - pos) / wid))
    try:
        p, _ = curve_fit(f, Es, mu, p0=[mu.min(), mu.max() - mu.min(), Es[np.argmax(np.gradient(mu))], 0.06], maxfev=8000)
        dif, b, pos, wid = [float(v) for v in p]
        wid = abs(wid)
    except Exception as e:
        dif = b = pos = wid = float("nan")
    Etar = None
    if np.isfinite(b):
        lo, hi = Es.min(), Es.max()
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if f(mid, dif, b, pos, wid) < b else (lo, mid)
        Etar = 0.5 * (lo + hi)
    world.set("hem.energy", float(Etar if (apply and Etar) else e0))
    if not apply:
        world.set("foilB.pos", foil0)
    return {"energy_keV": Es.tolist(), "mu_t": [round(float(v), 4) for v in mu], "fit": {"dif": dif, "b": b, "pos_keV": pos, "wid_keV": wid},
            "energy_for_mu_t_equals_b_keV": Etar, "element": element, "applied": apply}


def calibrate_energy(world, element="Re", target_b=None, max_iter=4):
    """Energy calibration the way the operators do it: E_scan fit -> adjust the Th1 offset (userTran3) until mu_t = b at the HEM readout energy -> re-check
    with mu_t. Th1 offset moves the real energy by -45 eV per mdeg at 71.7 keV. Returns the final mu_t and offset."""
    E_read = world.ctl("hem.energy")
    d = pcore.d_spacing_cubic(pcore.SI_A, (1, 1, 1))
    hist = []
    for it in range(max_iter):
        sc = edge_scan(world, element, apply=False)
        fit = sc["fit"]
        if not np.isfinite(fit["b"]):
            raise RuntimeError("edge fit failed (is the beam on the B ICs and the energy within 0.12 keV of the edge?)")
        b = fit["b"] if target_b is None else target_b
        # real-energy shift needed so that the edge sits where mu_t = b at the readout energy: dE = (energy found) - (readout)
        dE = sc["energy_for_mu_t_equals_b_keV"] - E_read
        # raising the Th1 offset lowers the real energy: dE/doffset = dEdtheta (keV/deg)
        dEdth = pcore.energy_shift_from_angle_keV(E_read, d, 1e-3) / 1e-3
        world.set("hem.th1_offset", float(world.ctl("hem.th1_offset") + dE / dEdth))
        world.set("foilB.pos", element)
        mu = float(np.mean([world.mu_t() for _ in range(3)]))
        world.set("foilB.pos", "out")
        hist.append({"iteration": it, "edge_fit": fit, "shift_keV": dE, "th1_offset": world.ctl("hem.th1_offset"), "mu_t_after": mu})
        if abs(mu - b) < 0.05:
            break
    return {"converged": abs(mu - b) < 0.08, "mu_t": mu, "b": b, "th1_offset": world.ctl("hem.th1_offset"), "history": hist}


# ------------------------------------------------------------------------------------------------------------------------------ camera, hotspot, slits
def tune_exposure(world, cam, target=0.35, apply=True):
    """Set the camera exposure so the brightest part of the beam reaches `target` of the camera's nominal full scale (operators lengthen the exposure to find a
    dim beam and shorten it when the core saturates). Iterates a few times from the current exposure. Returns the exposure (s)."""
    cc = world.sim["cameras"][cam]
    exp = world.ctl(f"{cam}.exposure")
    peak = 0.0
    for _ in range(5):
        img = grab(world, cam, exposure=exp, bin_=4).astype(np.float32)
        peak = float(np.percentile(img, 99.5)) - cc["bg"]
        if peak > 60000 - cc["bg"]:                       # saturated: the real brightness is unknown, back off
            exp = max(exp / 8.0, 0.002)
            continue
        if peak <= 20:
            if exp >= 10.0:
                return {"ok": False, "reason": "no signal even at 10 s: the beam is not on the camera", "exposure_s": world.ctl(f"{cam}.exposure")}
            exp = min(exp * 8.0, 10.0)
            continue
        new = float(np.clip(round(exp * target * cc["full"] / peak, 4), 0.002, 10.0))
        if abs(math.log(new / exp)) < 0.12:
            exp = new
            break
        exp = new
    if apply:
        world.set(f"{cam}.exposure", exp)
    return {"ok": True, "exposure_s": exp}


def find_beam_on_camera(world, cam, half_range_mm=3.0, step_mm=None, centre=True):
    """Bring the tomo camera in and move it until the beam is on the sensor (the operators go to x~0, then X/Y). Searches a raster around 0 with a long
    (>= 1 s) exposure so a still-unoptimised beam is seen; returns the first stage position where the beam is seen, with the frame analysis (at the
    camera's own exposure). The first sighting is usually the beam's corner at the frame edge, so by default (`centre`) the stage is then moved to put the
    footprint in the middle of the frame (what the operators do: "found beam ... beam centre desired ..."). Leaves the camera there."""
    cc = world.sim["cameras"][cam]
    st = cc["stage"]
    p = world.cams[cam]["pixel_um"] * 1e-3
    fov_x, fov_y = cc["cols"] * p, cc["rows"] * p
    step = step_mm or 0.6 * min(fov_x, fov_y)
    sp = world.spec(f"{st}.x")
    xs = [x for x in np.arange(-half_range_mm, half_range_mm + 1e-9, step) if sp[0] <= x <= sp[1]]
    ys = np.arange(-half_range_mm, half_range_mm + 1e-9, step)
    xs = sorted(xs, key=abs)
    world.set(f"{st}.x", float(xs[0]))
    tried = 0
    for y in sorted(ys, key=abs):
        world.set(f"{st}.y", float(np.clip(y, *world.spec(f"{st}.y")[:2])))
        for x in xs:
            world.set(f"{st}.x", float(x))
            tried += 1
            an = analyze_frame(grab(world, cam, exposure=max(world.ctl(f"{cam}.exposure"), 1.0), bin_=4), p * 4e3)      # long exposure while searching
            if an.get("beam"):
                te = tune_exposure(world, cam)
                seen = {"x_mm": world.ctl(f"{st}.x"), "y_mm": world.ctl(f"{st}.y")}
                cen = centre_camera_on_beam(world, cam, "footprint") if centre else None
                return {"found": True, "stage": st, "x_mm": world.ctl(f"{st}.x"), "y_mm": world.ctl(f"{st}.y"), "first_seen_at": seen,
                        "centred": bool(cen and cen.get("ok")), "positions_tried": tried, "exposure_s": world.ctl(f"{cam}.exposure"),
                        "analysis": analyze_frame(grab(world, cam), p * 1e3)}
    return {"found": False, "positions_tried": tried}


def centre_camera_on_beam(world, cam, which="hotspot", iterations=8):
    """Move the tomo stage so the hotspot (or footprint centre) sits at the middle of the frame, as the operators do before zeroing X,Y."""
    cc = world.sim["cameras"][cam]
    st = cc["stage"]
    p = world.cams[cam]["pixel_um"] * 1e-3
    sg = world.sim["tomo_stages"]
    last = None
    for _ in range(iterations):
        tune_exposure(world, cam)
        an = analyze_frame(grab(world, cam, bin_=2), p * 2e3)
        if not an.get("beam"):
            return {"ok": False, "reason": "no beam in the frame; use find_beam_on_camera"}
        if which == "hotspot":
            px = an["hotspot_px"]
        else:                                   # footprint: centre of its bounding box (the centroid of a beam cut by the frame edge is biased inward)
            b = an["box_px"]
            px = {"x": (b["x0"] + b["x1"]) / 2.0, "y": (b["y0"] + b["y1"]) / 2.0}
        dx_px = px["x"] * 2 - (cc["cols"] - 1) / 2.0
        dy_px = px["y"] * 2 - (cc["rows"] - 1) / 2.0
        world.set(f"{st}.x", float(np.clip(world.ctl(f"{st}.x") + sg["xsign"] * dx_px * p, *world.spec(f"{st}.x")[:2])))
        world.set(f"{st}.y", float(np.clip(world.ctl(f"{st}.y") - sg["ysign"] * dy_px * p, *world.spec(f"{st}.y")[:2])))
        last = (dx_px, dy_px)
        if abs(dx_px) < 3 and abs(dy_px) < 3 and not an["touches_frame"]:
            break
    an = analyze_frame(grab(world, cam), p * 1e3)
    return {"ok": True, "stage": st, "x_mm": world.ctl(f"{st}.x"), "y_mm": world.ctl(f"{st}.y"), "residual_px": last, "analysis": an}


def steering_check(world, cam):
    """Compare the hotspot with the centre of the WB-slit image on the tomo (open all other slits first). Returns the offset in px/mm and the steering
    change (urad) that would remove it - the 'request orbit steering' step of the logs. Does not move anything."""
    p = world.cams[cam]["pixel_um"] * 1e-3
    an = analyze_frame(grab(world, cam), p * 1e3)
    if not an.get("beam"):
        return {"ok": False, "reason": "no beam on the camera"}
    zc = world.camera_view(cam)[0]
    if an["touches_frame"]:
        return {"ok": False, "reason": "the footprint is not fully inside the frame: centre the camera on it first (centre_camera_on_beam which='footprint'), or the WB image is larger than the field of view", "analysis": an}
    b = an["box_px"]
    cx, cy = (b["x0"] + b["x1"]) / 2.0, (b["y0"] + b["y1"]) / 2.0
    dx, dy = (an["hotspot_px"]["x"] - cx) * p, -(an["hotspot_px"]["y"] - cy) * p      # mm, hotspot minus footprint centre (u right, v up)
    return {"ok": True, "hotspot_minus_footprint_mm": {"h": dx, "v": dy}, "hotspot_minus_footprint_px": {"h": dx / p, "v": -dy / p},
            "suggested_steering_urad": {"xp": -dx * 1e3 / zc, "yp": -dy * 1e3 / zc},     # mm / m = mrad -> x1e3 = urad
            "note": "steering moves the hotspot; the footprint is fixed by the slits. Apply only part of it, then re-measure (a hotspot offset of <10-15 px is accepted).",
            "footprint_box_px": b}


def slit_image_centre(world, slit, cam, closed_mm=0.1, restore=True):
    """Kohzu slit alignment on the tomo (the logbook recipe): close the slit to closed_mm in both directions, read the centre of its dim image in px, and
    return the shift (mm in slit centre units) that puts it on the hotspot of the OPEN beam. Moves the slit to closed_mm for the measurement and back."""
    p = world.cams[cam]["pixel_um"] * 1e-3
    h0, v0 = world.ctl(f"{slit}.hsize"), world.ctl(f"{slit}.vsize")
    ref = analyze_frame(grab(world, cam), p * 1e3)
    if not ref.get("beam"):
        return {"ok": False, "reason": "no beam on the camera"}
    world.set(f"{slit}.hsize", closed_mm)
    world.set(f"{slit}.vsize", closed_mm)
    an = analyze_frame(grab(world, cam), p * 1e3)
    if restore:
        world.set(f"{slit}.hsize", h0)
        world.set(f"{slit}.vsize", v0)
    if not an.get("beam"):
        return {"ok": False, "reason": "the closed slit passes no beam on the camera (slit is far off the beam: scan its centre)"}
    c = an["centroid_px"]
    hs = world.sim["slits"]["hsign"]
    d_h = (ref["hotspot_px"]["x"] - c["x"]) * p            # +u mm: how far the open-beam hotspot is to the right of the slit image
    d_v = -(ref["hotspot_px"]["y"] - c["y"]) * p
    return {"ok": True, "slit": slit, "slit_image_px": c, "hotspot_px": ref["hotspot_px"], "delta_hcenter_mm": d_h * hs, "delta_vcenter_mm": d_v,
            "note": "move the centre by the deltas, repeat until |delta| < ~0.01 mm. The beam is not symmetric about the slit's mechanical zero; zero only afterwards."}


def align_slit(world, slit, cam, sizes=(0.8, 0.5, 0.3, 0.2, 0.1), tol_mm=0.004, extra=2, target_px=None):
    """Kohzu slit alignment as in the logs: close the slit step by step (1.1 -> 0.1 mm in the Jul 2024 series), at each size move its centre so the slit's
    image sits on the hotspot of the open beam, finish at 0.1 mm and repeat a few times; the slit is reopened at the end. Only the centre moves."""
    p = world.cams[cam]["pixel_um"] * 1e-3
    h0, v0 = world.ctl(f"{slit}.hsize"), world.ctl(f"{slit}.vsize")
    ref = analyze_frame(grab(world, cam), p * 1e3)
    if not ref.get("beam"):
        return {"ok": False, "reason": "no beam on the camera"}
    cc = world.sim["cameras"][cam]
    if target_px is None:                        # logs: align to a target pixel (960,600 on a 1920x1200 frame), after centring the camera on the hotspot
        target_px = ((cc["cols"] - 1) / 2.0, (cc["rows"] - 1) / 2.0)
    ref = {"hotspot_px": {"x": target_px[0], "y": target_px[1]}}
    hs = world.sim["slits"]["hsign"]
    hist, last = [], None
    plan = [s_ for s_ in sizes if s_ < min(h0, v0)] + [sizes[-1]] * extra
    for s_ in plan:
        world.set(f"{slit}.hsize", s_)
        world.set(f"{slit}.vsize", s_)
        an = analyze_frame(grab(world, cam), p * 1e3)
        if not an.get("beam"):
            # the slit is off the beam by more than the footprint: find the beam with an ion chamber downstream of it (slit_ic_scan), then continue
            world.set(f"{slit}.hsize", h0)
            world.set(f"{slit}.vsize", v0)
            coarse = [slit_ic_scan(world, slit, ax, ic=_ic_after(world, slit), half_range=1.8, n=61, size=0.3, apply=True) for ax in ("h", "v")]
            hist.append({"coarse_ic_scan": [{"axis": c["axis"], "found": c["found"], "peak_centre_mm": c["peak_centre_mm"]} for c in coarse]})
            world.set(f"{slit}.hsize", s_)
            world.set(f"{slit}.vsize", s_)
            an = analyze_frame(grab(world, cam), p * 1e3)
            if not an.get("beam"):
                world.set(f"{slit}.hsize", h0)
                world.set(f"{slit}.vsize", v0)
                return {"ok": False, "slit": slit, "reason": f"no image of the slit closed to {s_} mm even after an IC scan", "history": hist}
        c = an["centroid_px"]
        dh, dv = (ref["hotspot_px"]["x"] - c["x"]) * p * hs, -(ref["hotspot_px"]["y"] - c["y"]) * p
        world.set(f"{slit}.hcenter", world.ctl(f"{slit}.hcenter") + dh)
        world.set(f"{slit}.vcenter", world.ctl(f"{slit}.vcenter") + dv)
        hist.append({"size_mm": s_, "dh": dh, "dv": dv})
        last = max(abs(dh), abs(dv))
    world.set(f"{slit}.hsize", h0)
    world.set(f"{slit}.vsize", v0)
    return {"ok": bool(last is not None and last < max(tol_mm, 0.012)), "slit": slit, "hcenter": world.ctl(f"{slit}.hcenter"), "vcenter": world.ctl(f"{slit}.vcenter"),
            "last_shift_mm": last, "history": hist}


def _ic_after(world, slit):
    """Nearest ion chamber downstream of the slit (the counter an operator would watch)."""
    zs = world.z[slit]
    cand = [(world.z[i], i) for i in world.sim["ic"]["ids"] if world.z[i] > zs]
    return min(cand)[1]


def slit_ic_scan(world, slit, axis="h", ic="icE4", half_range=1.0, n=41, size=0.1, apply=False):
    """Coarse slit alignment with an ion chamber (when the camera cannot see the slit image yet): close the slit to `size`, scan its centre across
    +-half_range mm and read the IC downstream. The peak of the count rate is where the beam passes the slit. Restores the size; with apply=True sets
    the centre to the peak."""
    k_size, k_c = f"{slit}.{axis}size", f"{slit}.{axis}center"
    s0, c0 = world.ctl(k_size), world.ctl(k_c)
    world.set(k_size, size)
    xs = np.linspace(c0 - half_range, c0 + half_range, n)
    vals = []
    for x in xs:
        world.set(k_c, float(x))
        vals.append(world.ic_kHz(ic))
    world.set(k_size, s0)
    pk, fwhm = _fit_peak(xs, vals)
    dark = world.sim["ic"]["dark_kHz"]
    found = max(vals) > 3 * dark
    world.set(k_c, pk if (apply and found) else c0)
    return {"slit": slit, "axis": axis, "centre_mm": xs.tolist(), "counts_kHz": [round(v, 2) for v in vals], "peak_centre_mm": pk if found else None, "fwhm_mm": fwhm, "found": found, "ic": ic}


def align_fast_shutter(world, fs, ic=None, half_range=2.5, n=51, apply=True):
    """Centre a fast shutter's window on the beam (log: B-FS aligned with IC6, E-FS with IC4/IC6): with the other slits open, scan the FS blade centre over
    +-half_range mm in each direction against the nearest IC downstream; the IC plateau (window contains the whole beam) is bounded by the half-maximum
    points and its middle is where the window is centred on the beam. fs: 'fsB' or 'fsE'."""
    ic = ic or _ic_after(world, fs)
    dark = world.sim["ic"]["dark_kHz"]
    out = {"fs": fs, "ic": ic}
    for ax in ("h", "v"):
        key = f"{fs}.{ax}center"
        c0 = world.ctl(key)
        xs = np.linspace(c0 - half_range, c0 + half_range, n)
        ys = []
        for x in xs:
            world.set(key, float(x))
            ys.append(world.ic_kHz(ic) - dark)
        y = np.array(ys)
        if y.max() <= 3 * dark:
            world.set(key, c0)
            out[ax] = {"found": False}
            continue
        idx = np.nonzero(y > 0.5 * y.max())[0]
        edges = (float(xs[idx[0]]), float(xs[idx[-1]]))
        centre = 0.5 * (edges[0] + edges[1])
        world.set(key, centre if apply else c0)
        out[ax] = {"found": True, "edges_mm": edges, "centre_mm": centre, "plateau_width_mm": edges[1] - edges[0]}
    return out


def focus_camera(world, cam, half_range_mm=0.4, n=17):
    """Camera objective focus: scan the focus motor and maximise edge sharpness of the beam footprint (mean gradient magnitude)."""
    f0 = world.ctl(f"{cam}.focus")
    xs = np.linspace(f0 - half_range_mm, f0 + half_range_mm, n)
    metric = []
    for x in xs:
        world.set(f"{cam}.focus", float(x))
        img = grab(world, cam, bin_=2).astype(np.float32)
        gy, gx = np.gradient(gaussian_filter(img, 1.0))
        metric.append(float(np.mean(np.hypot(gx, gy))))
    pk, _ = _fit_peak(xs, metric)
    world.set(f"{cam}.focus", pk)
    return {"focus_mm": xs.tolist(), "sharpness": metric, "best_focus_mm": pk}


def lens_scan(world, lens, cam, half_range_deg=0.05, n=21):
    """Tilt scan of a lens: the focused beam on the tomo is narrowest at the best tilt; metric = footprint area / peak (smaller = better focus)."""
    from ..physics import lens as plens
    L = plens.LENSES_1ID[lens]
    motor = "th" if L["orientation"] in ("upr", "up", "inv", "down") else "phi"
    p = world.cams[cam]["pixel_um"] * 1e-3
    c0 = world.ctl(f"{lens}.{motor}")
    xs = np.linspace(c0 - half_range_deg, c0 + half_range_deg, n)
    size = []
    for x in xs:
        world.set(f"{lens}.{motor}", float(x))
        img = grab(world, cam, bin_=2).astype(np.float32)
        an = analyze_frame(img, p * 2e3)
        size.append(float(an["box_px"]["height" if motor == "th" else "width"]) if an.get("beam") else float("nan"))
    s = np.array(size, float)
    ok = np.isfinite(s)
    best = float(xs[ok][np.argmin(s[ok])]) if ok.any() else c0
    world.set(f"{lens}.{motor}", best)
    return {"motor": motor, "tilt_deg": xs.tolist(), "size_px": size, "best_tilt_deg": best, "predicted_tilt_deg": plens.focus_motor_target(lens, world.energy_actual_keV())[1]}


# ------------------------------------------------------------------------------------------------------------------------------ whole sequence
def startup_sequence(world, element="Re", cam="gh1", log=None, align_slits=("slitEus", "slitEds")):
    """The start-of-beamtime sequence on the virtual beamline, as an executable record of the logbook procedure. Returns the list of step results.
    Uses only observables; the final score comes from readiness()."""
    steps = []
    say = lambda name, res: (steps.append({"step": name, **({"result": res} if res is not None else {})}), log and log(name))
    cc = world.sim["cameras"][cam]
    st = cc["stage"]
    # 1 settings: open downstream slits, remove attenuators/foil
    for sid in SLIT_IDS[1:]:
        world.set(f"{sid}.hsize", max(world.ctl(f"{sid}.hsize"), 3.0))
        world.set(f"{sid}.vsize", max(world.ctl(f"{sid}.vsize"), 3.0))
    world.set("foilB.pos", "out")
    world.set("attenB.pos", 0)
    world.set("attenC.pos", 0)
    say("open downstream slits 3x3 mm (the logs say 2x2 or wider), foil and attenuators out", None)
    for fs in FS_IDS:
        say(f"align fast shutter {fs} on the beam (IC plateau)", align_fast_shutter(world, fs))
    # 2 energy readout at the edge, nominal gap
    e_edge = pcore.edge_keV(element)
    world.set("hem.energy", float(round(e_edge, 3)))
    g = nominal_gap(world)
    open_gap(world, g["gap_mm"])
    world.set("und.gap", g["gap_mm"])
    say("HEM at the foil edge energy, undulator at the nominal gap", g)
    # 3 gap scan
    say("gap scan (wide)", gap_scan(world, world.ctl("und.gap"), 0.30, 61, "icB1"))
    # 4 Th2 tweak, gap again
    say("Th2 scan", th2_scan(world, 0.006, 31, "icB1"))
    say("gap scan (fine)", gap_scan(world, world.ctl("und.gap"), 0.10, 41, "icB1"))
    # 5 energy calibration on the foil edge
    cal = calibrate_energy(world, element)
    say("energy calibration (E_scan, Th1 offset so that mu_t = b)", cal)
    say("Th2 scan after the energy change", th2_scan(world, 0.004, 21, "icB1"))
    say("gap scan after Th2", gap_scan(world, world.ctl("und.gap"), 0.06, 31, "icB1"))
    cal = calibrate_energy(world, element)
    say("energy re-check (mu_t)", cal)
    # 6 camera into the beam, then steering (hotspot vs WB-slit image) before the final flux optimisation
    fb = find_beam_on_camera(world, cam, half_range_mm=3.5)
    say("bring the tomo camera into the beam", {k: v for k, v in fb.items() if k != "analysis"})
    if fb.get("found"):
        say("centre the camera on the beam", {k: v for k, v in centre_camera_on_beam(world, cam, "footprint").items() if k != "analysis"})
        say("focus the camera", focus_camera(world, cam))
        p_mm = world.cams[cam]["pixel_um"] * 1e-3
        for it in range(8):
            sc = steering_check(world, cam)
            if not sc.get("ok"):
                break
            off = max(abs(sc["hotspot_minus_footprint_px"]["h"]), abs(sc["hotspot_minus_footprint_px"]["v"]))
            if off < 12.0:
                break
            s = sc["suggested_steering_urad"]
            world.set("steer.xp", world.ctl("steer.xp") + 0.9 * s["xp"])
            world.set("steer.yp", world.ctl("steer.yp") + 0.9 * s["yp"])
            for fs in FS_IDS:                    # the beam moved: a fast shutter that was centred before may now clip it (the logs re-centre FS after steering)
                align_fast_shutter(world, fs)
            centre_camera_on_beam(world, cam, "footprint")
        for fs in FS_IDS:
            align_fast_shutter(world, fs)
        say("steering vs the WB-slit image", steering_check(world, cam))
        say("re-centre the camera on the hotspot", {k: v for k, v in centre_camera_on_beam(world, cam, "hotspot").items() if k != "analysis"})
        say("exposure re-tuned", tune_exposure(world, cam))
        say("gap scan after steering", gap_scan(world, world.ctl("und.gap"), 0.10, 41, "icB1"))
        say("Th2 scan after steering", th2_scan(world, 0.004, 21, "icB1"))
        say("energy re-check", calibrate_energy(world, element))
        say("exposure re-tuned (flux is now optimal)", tune_exposure(world, cam))
        # 7 slits
        for sl in align_slits:
            say(f"align {sl} on the hotspot (closed to 0.1 mm, tomo image)", align_slit(world, sl, cam))
    return steps


# ------------------------------------------------------------------------------------------------------------------------------ truth check
def readiness(world):
    """Hidden truth vs settings, as a checklist with tolerances. FOR TESTS/SCORING (reveals the answers)."""
    c, T, sim = world.s["ctl"], world.s["truth"], world.sim
    E = c["hem.energy"]
    rep = {}
    # flux
    f_now = world.source_flux()
    gopt = world.optimal_gap(E)
    sv = dict(world.s)
    rep["undulator_gap_error_mm"] = c["und.gap"] + (world.s["gap_hyst"]) - gopt
    rep["th2_error_deg"] = world.th2_error_deg()
    rep["source_flux_relative_to_best"] = f_now / max(world.best_amp(E) * world.ring_scale(), 1e-9)
    # energy: mu_t of the foil at the current state vs target b
    el = "Re"
    b = sim["foils"]["b"][el]
    mu = -math.log(world._foil_T_smooth(el, world.energy_actual_keV()))
    rep["energy_mu_t_Re"] = mu
    rep["energy_mu_t_error"] = mu - b
    # steering / hotspot vs WB slit centre (in urad)
    xp, yp = world.steer_rad()
    wbl, wbh = world.slit_edges("wbSlits", "h")
    wvl, wvh = world.slit_edges("wbSlits", "v")
    zwb = world.z["wbSlits"]
    rep["wb_slit_centre_minus_hotspot_um"] = {"h": ((wbl + wbh) / 2 - xp * zwb * 1e3) * 1e3, "v": ((wvl + wvh) / 2 - yp * zwb * 1e3) * 1e3}
    # slits
    sl = {}
    for sid in SLIT_IDS[1:] + FS_IDS:
        lo, hi = world.slit_edges(sid, "h")
        vlo, vhi = world.slit_edges(sid, "v")
        bc = world.beam_centre(world.z[sid])
        sl[sid] = {"h_um": ((lo + hi) / 2 - bc[0]) * 1e3, "v_um": ((vlo + vhi) / 2 - bc[1]) * 1e3}
    rep["slit_centre_minus_beam_um"] = sl
    # cameras
    cams = {}
    for cam, cc in sim["cameras"].items():
        if not isinstance(cc, dict) or "stage" not in cc:
            continue
        zc, uc, vc, p, rows, cols = world.camera_view(cam)
        bc = world.beam_centre(zc)
        cams[cam] = {"beam_minus_camera_axis_px": {"h": (bc[0] - uc) / p, "v": -(bc[1] - vc) / p}, "focus_error_mm": world.camera_focus_error_mm(cam)}
    rep["cameras"] = cams
    # pin / axis (px on gh1)
    ps = world.pin_state(0.0)
    p = world.cams["gh1"]["pixel_um"] * 1e-3
    rep["axis"] = {"a_px": ps["a"] / p, "b_px": ps["b"] / p, "axis_minus_beam_px": (ps["c"] - world.beam_centre(world.z["samE"])[0]) / p,
                   "tilt_rx_deg": T["pin"]["tilt_rx_deg"] + c["samE.rx"]}
    tol = {"undulator_gap_error_mm": 0.02, "th2_error_deg": 0.0007, "energy_mu_t_error": 0.1}
    rep["ok"] = {"gap": abs(rep["undulator_gap_error_mm"]) < tol["undulator_gap_error_mm"], "th2": abs(rep["th2_error_deg"]) < tol["th2_error_deg"],
                 "energy": abs(rep["energy_mu_t_error"]) < tol["energy_mu_t_error"],
                 "steering_wb_vs_hotspot": max(abs(v) for v in rep["wb_slit_centre_minus_hotspot_um"].values()) < 60.0,
                 "slits_E": all(max(abs(v) for v in sl[k].values()) < 100.0 for k in ("slitEus", "slitEds"))}
    rep["tolerances"] = tol
    return rep
