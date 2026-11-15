"""Slit and fast-shutter alignment procedures (camera image of a closed slit, or an ion chamber downstream) (interface: blade/instrument/base.py)."""
import numpy as np
from ..analysis.frame import analyze_frame, fit_peak
from ._util import accepts_world


@accepts_world
def slit_image_centre(inst, slit, cam, closed_mm=0.1, restore=True):
    """Kohzu slit alignment on the tomo (the logbook recipe): close the slit to closed_mm in both directions, read the centre of its dim image in px, and
    return the shift (mm in slit centre units) that puts it on the hotspot of the OPEN beam. Moves the slit to closed_mm for the measurement and back."""
    p = inst.cams[cam]["pixel_um"] * 1e-3
    h0, v0 = inst.ctl(f"{slit}.hsize"), inst.ctl(f"{slit}.vsize")
    ref = analyze_frame(inst.frame(cam), p * 1e3)
    if not ref.get("beam"):
        return {"ok": False, "reason": "no beam on the camera"}
    inst.set(f"{slit}.hsize", closed_mm)
    inst.set(f"{slit}.vsize", closed_mm)
    an = analyze_frame(inst.frame(cam), p * 1e3)
    if restore:
        inst.set(f"{slit}.hsize", h0)
        inst.set(f"{slit}.vsize", v0)
    if not an.get("beam"):
        return {"ok": False, "reason": "the closed slit passes no beam on the camera (slit is far off the beam: scan its centre)"}
    c = an["centroid_px"]
    hs = inst.sim["slits"]["hsign"]
    d_h = (ref["hotspot_px"]["x"] - c["x"]) * p            # +u mm: how far the open-beam hotspot is to the right of the slit image
    d_v = -(ref["hotspot_px"]["y"] - c["y"]) * p
    return {"ok": True, "slit": slit, "slit_image_px": c, "hotspot_px": ref["hotspot_px"], "delta_hcenter_mm": d_h * hs, "delta_vcenter_mm": d_v,
            "note": "move the centre by the deltas, repeat until |delta| < ~0.01 mm. The beam is not symmetric about the slit's mechanical zero; zero only afterwards."}


@accepts_world
def align_slit(inst, slit, cam, sizes=(0.8, 0.5, 0.3, 0.2, 0.1), tol_mm=0.004, extra=2, target_px=None):
    """Kohzu slit alignment as in the logs: close the slit step by step (1.1 -> 0.1 mm in the Jul 2024 series), at each size move its centre so the slit's
    image sits on the hotspot of the open beam, finish at 0.1 mm and repeat a few times; the slit is reopened at the end. Only the centre moves."""
    p = inst.cams[cam]["pixel_um"] * 1e-3
    h0, v0 = inst.ctl(f"{slit}.hsize"), inst.ctl(f"{slit}.vsize")
    ref = analyze_frame(inst.frame(cam), p * 1e3)
    if not ref.get("beam"):
        return {"ok": False, "reason": "no beam on the camera"}
    cc = inst.sim["cameras"][cam]
    if target_px is None:                        # logs: align to a target pixel (960,600 on a 1920x1200 frame), after centring the camera on the hotspot
        target_px = ((cc["cols"] - 1) / 2.0, (cc["rows"] - 1) / 2.0)
    ref = {"hotspot_px": {"x": target_px[0], "y": target_px[1]}}
    hs = inst.sim["slits"]["hsign"]
    hist, last = [], None
    plan = [s_ for s_ in sizes if s_ < min(h0, v0)] + [sizes[-1]] * extra
    for s_ in plan:
        inst.set(f"{slit}.hsize", s_)
        inst.set(f"{slit}.vsize", s_)
        an = analyze_frame(inst.frame(cam), p * 1e3)
        if not an.get("beam"):
            # the slit is off the beam by more than the footprint: find the beam with an ion chamber downstream of it (slit_ic_scan), then continue
            inst.set(f"{slit}.hsize", h0)
            inst.set(f"{slit}.vsize", v0)
            coarse = [slit_ic_scan(inst, slit, ax, ic=_ic_after(inst, slit), half_range=1.8, n=61, size=0.3, apply=True) for ax in ("h", "v")]
            hist.append({"coarse_ic_scan": [{"axis": c["axis"], "found": c["found"], "peak_centre_mm": c["peak_centre_mm"]} for c in coarse]})
            inst.set(f"{slit}.hsize", s_)
            inst.set(f"{slit}.vsize", s_)
            an = analyze_frame(inst.frame(cam), p * 1e3)
            if not an.get("beam"):
                inst.set(f"{slit}.hsize", h0)
                inst.set(f"{slit}.vsize", v0)
                return {"ok": False, "slit": slit, "reason": f"no image of the slit closed to {s_} mm even after an IC scan", "history": hist}
        c = an["centroid_px"]
        dh, dv = (ref["hotspot_px"]["x"] - c["x"]) * p * hs, -(ref["hotspot_px"]["y"] - c["y"]) * p
        inst.set(f"{slit}.hcenter", inst.ctl(f"{slit}.hcenter") + dh)
        inst.set(f"{slit}.vcenter", inst.ctl(f"{slit}.vcenter") + dv)
        hist.append({"size_mm": s_, "dh": dh, "dv": dv})
        last = max(abs(dh), abs(dv))
    inst.set(f"{slit}.hsize", h0)
    inst.set(f"{slit}.vsize", v0)
    return {"ok": bool(last is not None and last < max(tol_mm, 0.012)), "slit": slit, "hcenter": inst.ctl(f"{slit}.hcenter"), "vcenter": inst.ctl(f"{slit}.vcenter"),
            "last_shift_mm": last, "history": hist}


def _ic_after(inst, slit):
    """Nearest ion chamber downstream of the slit (the counter an operator would watch)."""
    zs = inst.z[slit]
    cand = [(inst.z[i], i) for i in inst.sim["ic"]["ids"] if inst.z[i] > zs]
    return min(cand)[1]


@accepts_world
def slit_ic_scan(inst, slit, axis="h", ic="icE4", half_range=1.0, n=41, size=0.1, apply=False):
    """Coarse slit alignment with an ion chamber (when the camera cannot see the slit image yet): close the slit to `size`, scan its centre across
    +-half_range mm and read the IC downstream. The peak of the count rate is where the beam passes the slit. Restores the size; with apply=True sets
    the centre to the peak."""
    k_size, k_c = f"{slit}.{axis}size", f"{slit}.{axis}center"
    s0, c0 = inst.ctl(k_size), inst.ctl(k_c)
    inst.set(k_size, size)
    xs = np.linspace(c0 - half_range, c0 + half_range, n)
    vals = []
    for x in xs:
        inst.set(k_c, float(x))
        vals.append(inst.ic_kHz(ic))
    inst.set(k_size, s0)
    pk, fwhm = fit_peak(xs, vals)
    dark = inst.sim["ic"]["dark_kHz"]
    found = max(vals) > 3 * dark
    inst.set(k_c, pk if (apply and found) else c0)
    return {"slit": slit, "axis": axis, "centre_mm": xs.tolist(), "counts_kHz": [round(v, 2) for v in vals], "peak_centre_mm": pk if found else None, "fwhm_mm": fwhm, "found": found, "ic": ic}


@accepts_world
def align_fast_shutter(inst, fs, ic=None, half_range=2.5, n=51, apply=True):
    """Centre a fast shutter's window on the beam (log: B-FS aligned with IC6, E-FS with IC4/IC6): with the other slits open, scan the FS blade centre over
    +-half_range mm in each direction against the nearest IC downstream; the IC plateau (window contains the whole beam) is bounded by the half-maximum
    points and its middle is where the window is centred on the beam. fs: 'fsB' or 'fsE'."""
    ic = ic or _ic_after(inst, fs)
    dark = inst.sim["ic"]["dark_kHz"]
    out = {"fs": fs, "ic": ic}
    for ax in ("h", "v"):
        key = f"{fs}.{ax}center"
        c0 = inst.ctl(key)
        xs = np.linspace(c0 - half_range, c0 + half_range, n)
        ys = []
        for x in xs:
            inst.set(key, float(x))
            ys.append(inst.ic_kHz(ic) - dark)
        y = np.array(ys)
        if y.max() <= 3 * dark:
            inst.set(key, c0)
            out[ax] = {"found": False}
            continue
        idx = np.nonzero(y > 0.5 * y.max())[0]
        edges = (float(xs[idx[0]]), float(xs[idx[-1]]))
        centre = 0.5 * (edges[0] + edges[1])
        inst.set(key, centre if apply else c0)
        out[ax] = {"found": True, "edges_mm": edges, "centre_mm": centre, "plateau_width_mm": edges[1] - edges[0]}
    return out
