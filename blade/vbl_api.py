"""HTTP helpers for the virtual-beamline page (/vbl) of `blade gui`. SIMULATION ONLY: these functions read and change the shared virtual-beamline session
(runs/vbl/default.json) and never touch hardware. Kept apart from gui.py (which is otherwise read-only)."""
import threading
from . import registry
from .vbl import store, imaging, procedures as P
from .vbl.world import control_specs, CAMERAS
from .physics import core as pcore

_LOCK = threading.RLock()


def state_payload(session=store.DEFAULT, reveal=False):
    with _LOCK:
        w = store.load(session)
        if w is None:
            return {"session": None, "scenarios": ["startup", "camera_in_beam", "ready_for_pin", "aligned"], "cameras": CAMERAS}
        snap = w.snapshot()
        specs = {k: {"lo": v[0], "hi": v[1], "unit": v[2], "doc": v[3]} for k, v in control_specs().items()}
        cams = {c: {"hutch": w.sim["cameras"][c]["hutch"], "stage": w.sim["cameras"][c]["stage"], "pixel_um": w.cams[c]["pixel_um"], "rows": w.sim["cameras"][c]["rows"],
                    "cols": w.sim["cameras"][c]["cols"], "z_m": w.z[w.sim["cameras"][c]["z_key"]]} for c in CAMERAS}
        out = {"session": session, "scenario": w.s["scenario"], "seed": w.s["seed"], "snapshot": snap, "specs": specs, "cameras": cams, "log": w.s["log"][-12:],
               "z_m": w.z, "foils": w.sim["foils"]["elements"] + ["out"],
               "edges_keV": {el: round(float(pcore.edge_keV(el)), 4) for el in w.sim["foils"]["elements"]}, "scenarios": ["startup", "camera_in_beam", "ready_for_pin", "aligned"]}
        if reveal:
            out["truth"] = w.truth_report()
        return out


def frame_png(camera, bin_=2, exposure=None, auto=True, session=store.DEFAULT):
    with _LOCK:
        w = store.require(session)
        img = imaging.render(w, camera, exposure=exposure, bin_=bin_)
        cc = w.sim["cameras"][camera]
        if auto:
            u8 = imaging.to_u8(img)
        else:
            exp = w.ctl(f"{camera}.exposure") if exposure is None else exposure
            u8 = imaging.to_u8(img, lo=cc["bg"], hi=cc["bg"] + 1.2 * cc["full"] * exp / 0.1)
        return imaging.png_gray8(u8)


def apply_set(body, session=store.DEFAULT):
    with _LOCK:
        w = store.require(session)
        rb = w.set(body["name"], body["value"])
        store.save(w, session)
        return {"name": body["name"], "readback": rb}


def reset(body, session=store.DEFAULT):
    with _LOCK:
        store.reset(int(body.get("seed", 0)), body.get("scenario", "startup"), session)
        return {"ok": True}


def run_tool(body):
    """Run a registered vbl_* tool by name with JSON args (the GUI's operator-action buttons)."""
    name = body.get("name", "")
    if not name.startswith("vbl_"):
        raise ValueError("only vbl_* tools can be run from the page")
    with _LOCK:
        return registry.invoke(name, **(body.get("args") or {}))


# ---------------------------------------------------------------------------------------------------------------------------------- line profile + fits
def _gauss(x, a, m, s, c):
    import numpy as np
    return a * np.exp(-0.5 * ((x - m) / s) ** 2) + c


def _scurve(x, a, m, s, c):
    from scipy.special import erf
    return c + a * 0.5 * (1.0 + erf((x - m) / (s * 2 ** 0.5)))


# slit kinds of the tomo-view profile (blade.imganalysis.fitting, ported from areaDetector ADViewers' LiveFitter slit fit). 'bowed' = plateau curved by k1,k2 (real
# gh1 slit windows have a hot core; the flat/tilted LiveFitter model then gives an edge sigma ~14x too wide), 'flat' = LiveFitter's straight tilt.
SLIT_KINDS = {"slit_pos": "slit_positive_bowed", "slit_neg": "slit_negative_bowed", "slit_pos_flat": "slit_positive", "slit_neg_flat": "slit_negative"}


def _fit_slit(x, y, kind):
    """Slit fit through blade.imganalysis, returned in the same shape as the legacy gauss/scurve fits plus derived slit values (edges, aperture, edge width)."""
    import numpy as np
    from .imganalysis import fitting as F
    r = F.fit(x, y, SLIT_KINDS[kind])
    if not r.get("ok"):
        return {"error": r.get("error", "slit fit failed")}
    d = r["derived"]
    return {"kind": kind, "model": r["model"], "params": r["params"], "errors": r["errors"], "r2": r["r2"], "rms": r["rms"], "curve": r["curve"], "derived": d,
            "formula": r["formula"], "aperture": d["aperture"], "edges": [d["left_edge"], d["right_edge"]], "width_10_90": d["edge_width_10_90"], "edge_fwhm": d["edge_fwhm"]}


def _bic(f, n):
    import numpy as np
    return n * np.log(max(f["rms"], 1e-12) ** 2) + len(f["params"]) * np.log(n)


def fit_profile(x, y, kind):
    """Fit a 1-D profile. kind: 'gauss' (peak: a*exp(-(x-m)^2/2s^2)+c), 'scurve' (step/edge: c + a*(1+erf((x-m)/(s*sqrt2)))/2; a<0 = falling edge),
    'slit_pos' / 'slit_neg' (bright window / dark blocker = erf pair with a bowed plateau; params offset, centre, width, height, sigma, k1, k2; also
    'slit_pos_flat' / 'slit_neg_flat' = LiveFitter's straight-tilt version), or 'auto' (best of all of them by BIC). Returns {kind, params{...}, errors,
    curve[], r2} (slit kinds also edges, aperture, width_10_90) or {error}."""
    import numpy as np
    from scipy.optimize import curve_fit
    from scipy.ndimage import uniform_filter1d
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 8:
        return {"error": "too few points"}
    if kind in SLIT_KINDS:
        return _fit_slit(x, y, kind)
    if kind == "auto":
        fits = [f for f in (fit_profile(x, y, "gauss"), fit_profile(x, y, "scurve"), fit_profile(x, y, "slit_pos"), fit_profile(x, y, "slit_neg")) if "error" not in f]
        return min(fits, key=lambda f: _bic(f, len(x))) if fits else {"error": "no fit converged"}
    ys = uniform_filter1d(y, max(3, len(y) // 40), mode="nearest")
    span = float(x[-1] - x[0])
    n = max(3, len(y) // 10)
    try:
        if kind == "gauss":
            i = int(np.argmax(ys)); c0 = float(np.percentile(y, 5)); a0 = float(ys[i] - c0)
            half = c0 + a0 / 2
            above = np.nonzero(ys > half)[0]
            s0 = max((x[above[-1]] - x[above[0]]) / 2.355, span / 200) if len(above) > 1 else span / 10
            p, cov = curve_fit(_gauss, x, y, p0=[a0, x[i], s0, c0], maxfev=8000)
            f = _gauss
            names = ["amplitude", "centre", "sigma", "offset"]
        elif kind == "scurve":
            lo, hi = float(np.mean(ys[:n])), float(np.mean(ys[-n:]))
            g = np.abs(np.gradient(ys, x))
            i = int(np.argmax(g))
            p, cov = curve_fit(_scurve, x, y, p0=[hi - lo, x[i], span / 40, lo], maxfev=8000)
            f = _scurve
            names = ["step", "centre", "sigma", "base"]
        else:
            return {"error": "unknown fit kind " + str(kind)}
    except Exception as e:
        return {"error": f"{kind} fit failed: {e}"}
    p = list(map(float, p)); p[2] = abs(p[2])
    err = [float(v) for v in np.sqrt(np.abs(np.diag(cov)))] if np.all(np.isfinite(cov)) else [None] * 4
    fit = f(x, *p)
    ss_res, ss_tot = float(np.sum((y - fit) ** 2)), float(np.sum((y - y.mean()) ** 2)) or 1.0
    out = {"kind": kind, "params": dict(zip(names, p)), "errors": dict(zip(names, err)), "r2": 1 - ss_res / ss_tot, "rms": float(np.sqrt(ss_res / len(y))),
           "fwhm": 2.3548 * p[2], "width_10_90": 2.563 * p[2], "curve": [float(v) for v in fit]}
    return out


def projections(body, session=store.DEFAULT):
    """Row/column intensity sums of the camera image, and optionally of a box. body: camera, bin, optional x0,y0,x1,y1 (box corners as fractions 0..1 of the
    image width/height). Returns cols (sum over rows for every column, length = image width), rows (sum over columns for every row), and, if a box is given,
    box = {c0,c1,r0,r1 (pixel indices, end exclusive), cols (per column inside the box, summed over the box rows), rows (per row, summed over the box columns), total}.
    Sums are of the real rendered counts (not the 8-bit display)."""
    import numpy as np
    with _LOCK:
        w = store.require(session)
        cam = body.get("camera", "gh1")
        b = int(body.get("bin", 2))
        img = imaging.render(w, cam, bin_=b).astype(np.float64)
        store.save(w, session)
        pix_um = w.cams[cam]["pixel_um"]
    H, W = img.shape
    out = {"camera": cam, "bin": b, "cols_n": W, "rows_n": H, "pixel_um": pix_um, "cols": img.sum(axis=0).tolist(), "rows": img.sum(axis=1).tolist()}
    if all(k in body for k in ("x0", "y0", "x1", "y1")):
        xa, xb = sorted((float(body["x0"]), float(body["x1"])))
        ya, yb = sorted((float(body["y0"]), float(body["y1"])))
        c0 = min(W - 1, max(0, int(np.floor(xa * W)))); c1 = min(W, max(c0 + 1, int(np.ceil(xb * W))))
        r0 = min(H - 1, max(0, int(np.floor(ya * H)))); r1 = min(H, max(r0 + 1, int(np.ceil(yb * H))))
        sub = img[r0:r1, c0:c1]
        out["box"] = {"c0": c0, "c1": c1, "r0": r0, "r1": r1, "cols": sub.sum(axis=0).tolist(), "rows": sub.sum(axis=1).tolist(), "total": float(sub.sum()),
                      "size_um": [float((c1 - c0) * b * pix_um), float((r1 - r0) * b * pix_um)]}
    if body.get("fit") in ("gauss", "auto"):
        def _fit(vals, i0):
            import numpy as np
            v = np.asarray(vals, float); x = i0 + 0.5 + np.arange(len(v))            # x in binned-pixel units (pixel centres)
            f = fit_profile(x, v, "gauss")
            tot = float(v.sum()); cen = float((x * v).sum() / tot) if tot > 0 else None   # centroid of the (background-subtracted) profile
            vb = np.clip(v - np.percentile(v, 5), 0, None); tb = float(vb.sum()); cen_b = float((x * vb).sum() / tb) if tb > 0 else None
            if "error" in f:
                return {"error": f["error"], "centroid_px": None if cen_b is None else cen_b * b}
            q = f["params"]
            return {"centre_px": q["centre"] * b, "centre_err_px": (f["errors"]["centre"] or 0) * b, "fwhm_px": f["fwhm"] * b, "fwhm_um": f["fwhm"] * b * pix_um,
                    "r2": f["r2"], "curve": f["curve"], "centroid_px": cen_b * b if cen_b is not None else None, "centre_x": q["centre"]}
        out["fit"] = {"cols": _fit(out["cols"], 0), "rows": _fit(out["rows"], 0)}
        if "box" in out:
            bx = out["box"]
            out["box"]["fit"] = {"cols": _fit(bx["cols"], bx["c0"]), "rows": _fit(bx["rows"], bx["r0"])}
    return out


def profile(body, session=store.DEFAULT):
    """Profile of the drawn box on the camera image, with an optional fit. body: camera, bin, x0,y0,x1,y1 (box corners as fractions 0..1 of the image width/height),
    direction ('h' = along x, mean over the box rows; 'v' = along y, mean over the box columns; the ImageJ rectangle-profile semantics), fit ('none'|'gauss'|'scurve'|
    'slit_pos'|'slit_neg'|'slit_pos_flat'|'slit_neg_flat'|'auto'). Renders a fresh frame at that bin (real counts, not the 8-bit display). dist_um is the absolute
    position along the frame (um from its left/top edge), so fitted centres/edges are in detector coordinates. A fit also carries marks_frac: where its centre/edges
    lie on the image (fractions), for the overlay."""
    import numpy as np
    from .imganalysis import profile as IP
    with _LOCK:
        w = store.require(session)
        cam = body.get("camera", "gh1")
        b = int(body.get("bin", 2))
        img = imaging.render(w, cam, bin_=b).astype(np.float64)
        store.save(w, session)
        pix_um = w.cams[cam]["pixel_um"]
    H, W = img.shape
    d = "v" if body.get("direction", "h") == "v" else "h"
    xa, xb = sorted((float(body["x0"]), float(body["x1"])))
    ya, yb = sorted((float(body["y0"]), float(body["y1"])))
    um_per = pix_um * b
    pr = IP.rect_profile(img, xa * W, ya * H, xb * W, yb * H, "vertical" if d == "v" else "horizontal", um_per, absolute=True)
    roi = pr["roi"]
    dist = np.asarray(pr["x"], float) + 0.5 * um_per                              # pixel centres
    y = np.asarray(pr["y"], float)
    n_along = H if d == "v" else W
    out = {"camera": cam, "bin": b, "direction": d, "n": int(len(y)), "pixel_um": pix_um, "frame_um": n_along * um_per, "dist_um": [float(v) for v in dist],
           "counts": [float(v) for v in y], "box_px": [roi["x0"] * b, roi["y0"] * b, roi["x1"] * b, roi["y1"] * b],
           "box_um": [float((roi["x1"] - roi["x0"]) * um_per), float((roi["y1"] - roi["y0"]) * um_per)],
           "box_frac": [roi["x0"] / W, roi["y0"] / H, roi["x1"] / W, roi["y1"] / H], "rows_averaged": int(roi["y1"] - roi["y0"]) if d == "h" else int(roi["x1"] - roi["x0"])}
    kind = body.get("fit", "none")
    if kind and kind != "none":
        f = fit_profile(dist, y, kind)
        if "error" not in f:
            bx = out["box_frac"]
            cx, cy = 0.5 * (bx[0] + bx[2]), 0.5 * (bx[1] + bx[3])
            at = (lambda pos: [pos / (n_along * um_per), cy]) if d == "h" else (lambda pos: [cx, pos / (n_along * um_per)])
            f["centre_frac"] = at(f["params"]["centre"])
            f["centre_px"] = [f["centre_frac"][0] * W * b, f["centre_frac"][1] * H * b]
            if f.get("edges"):
                f["edges_frac"] = [at(e) for e in f["edges"]]
        out["fit"] = f
    return out
