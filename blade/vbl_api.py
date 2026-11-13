"""HTTP helpers for the virtual-beamline page (/vbl) of `blade gui`. SIMULATION ONLY: these functions read and change the shared virtual-beamline session
(runs/vbl/default.json) and never touch hardware. Kept apart from gui.py (which is otherwise read-only)."""
import threading
from . import registry
from .vbl import store, imaging, procedures as P
from .vbl.world import control_specs, CAMERAS

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
               "z_m": w.z, "foils": w.sim["foils"]["elements"] + ["out"], "scenarios": ["startup", "camera_in_beam", "ready_for_pin", "aligned"]}
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


def fit_profile(x, y, kind):
    """Fit a 1-D profile. kind: 'gauss' (peak: a*exp(-(x-m)^2/2s^2)+c), 'scurve' (step/edge: c + a*(1+erf((x-m)/(s*sqrt2)))/2; a<0 = falling edge)
    or 'auto' (the one with the smaller residual). Returns {kind, params{...}, errors, curve[], r2} or {error}."""
    import numpy as np
    from scipy.optimize import curve_fit
    from scipy.ndimage import uniform_filter1d
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 8:
        return {"error": "too few points"}
    if kind == "auto":
        fits = [f for f in (fit_profile(x, y, "gauss"), fit_profile(x, y, "scurve")) if "error" not in f]
        return min(fits, key=lambda f: f["rms"]) if fits else {"error": "no fit converged"}
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


def profile(body, session=store.DEFAULT):
    """Intensity along a line drawn on the camera image. body: camera, bin, x0,y0,x1,y1 (fractions 0..1 of the image width/height), width (px, averaged across
    the line), fit ('none'|'gauss'|'scurve'|'auto'). Renders a fresh frame at that bin (real counts, not the 8-bit display) and samples it bilinearly."""
    import numpy as np
    from scipy.ndimage import map_coordinates
    with _LOCK:
        w = store.require(session)
        cam = body.get("camera", "gh1")
        b = int(body.get("bin", 2))
        img = imaging.render(w, cam, bin_=b).astype(np.float32)
        store.save(w, session)
        pix_um = w.cams[cam]["pixel_um"]
    H, W = img.shape
    x0, y0, x1, y1 = (float(body[k]) for k in ("x0", "y0", "x1", "y1"))
    p0 = np.array([x0 * W - 0.5, y0 * H - 0.5]); p1 = np.array([x1 * W - 0.5, y1 * H - 0.5])
    L = float(np.hypot(*(p1 - p0)))
    if L < 2:
        raise ValueError("line too short: drag a longer line on the image")
    n = int(L) + 1
    t = np.linspace(0, 1, n)
    d = (p1 - p0) / L
    perp = np.array([-d[1], d[0]])
    wpx = max(1, int(body.get("width", 5)))
    offs = np.linspace(-(wpx - 1) / 2, (wpx - 1) / 2, wpx)
    acc = np.zeros(n)
    for o in offs:
        xs = p0[0] + t * (p1[0] - p0[0]) + o * perp[0]
        ys = p0[1] + t * (p1[1] - p0[1]) + o * perp[1]
        acc += map_coordinates(img, [ys, xs], order=1, mode="nearest")
    y = acc / wpx
    um_per = pix_um * b
    dist = t * L * um_per
    out = {"camera": cam, "bin": b, "n": n, "length_um": L * um_per, "pixel_um": pix_um, "width_px": wpx, "dist_um": [float(v) for v in dist],
           "counts": [float(v) for v in y], "p0_px": [float((p0[0] + 0.5) * b), float((p0[1] + 0.5) * b)], "p1_px": [float((p1[0] + 0.5) * b), float((p1[1] + 0.5) * b)]}
    kind = body.get("fit", "none")
    if kind and kind != "none":
        f = fit_profile(dist, y, kind)
        if "centre" in f.get("params", {}):
            c = f["params"]["centre"]
            f["centre_frac"] = [x0 + (x1 - x0) * c / (L * um_per), y0 + (y1 - y0) * c / (L * um_per)]
            f["centre_px"] = [float(f["centre_frac"][0] * W * b), float(f["centre_frac"][1] * H * b)]
        out["fit"] = f
    return out
