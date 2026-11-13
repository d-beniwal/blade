"""1-D fitting library ported from the areaDetector ADViewers ImageJ plugins (Gaussian_Profiler, LiveFitter_EPICSUserCalc) and ImageJ's CurveFitter families.

Source: https://github.com/areaDetector/ADViewers (ImageJ/EPICS_areaDetector/; copyright UChicago Argonne LLC et al., see its LICENSE; the algorithms are re-implemented in Python, no source copied). Only numpy + scipy. Nothing here touches hardware.

Conventions (differ from ImageJ on purpose, so parameters have names):
  gaussian        offset + amp*exp(-(x-centre)^2/(2 sigma^2))          (ImageJ's 'b' is the PEAK value offset+amp; we report both: amp and peak)
  slit_positive   offset + slope*x + h/2*[erf((x-c+w/2)/(s*sqrt2)) - erf((x-c-w/2)/(s*sqrt2))],  h > 0   (bright aperture on a dark field: slit seen in transmission)
  slit_negative   same, h < 0                                                                              (dark blocker/pin/blade in a bright field)
  erf_edge        offset + step*erf((x-centre)/(sigma*sqrt2))          (ImageJ 'Error Function' y=a+b*erf((x-c)/d), with d = sigma*sqrt2 made explicit)
`fit(x, y, model)` returns {model, params, errors, r2, rms, derived, curve, formula, ok}; it never raises on bad data (ok=False + error).
"""
import numpy as np
from scipy.optimize import least_squares
from scipy.special import erf

SQ2 = 2.0 ** 0.5
FWHM_K = 2.0 * np.sqrt(2.0 * np.log(2.0))          # 2.3548: FWHM = FWHM_K * sigma (Gaussian_Profiler: 2*sigma*sqrt(2 ln 2))


# --------------------------------------------------------------------------------------------------------------------------------- model functions
def _gaussian(x, offset, amp, centre, sigma):
    return offset + amp * np.exp(-0.5 * ((x - centre) / sigma) ** 2)


def _gaussian_nooff(x, amp, centre, sigma):
    return amp * np.exp(-0.5 * ((x - centre) / sigma) ** 2)


def _erf_edge(x, offset, step, centre, sigma):
    return offset + step * erf((x - centre) / (sigma * SQ2))


def _slit(x, offset, slope, centre, width, height, sigma):
    """LiveFitter's slitEquation: a+b*x+e/2*erf((x-c+d/2)/(f*sqrt2)) - e/2*erf((x-c-d/2)/(f*sqrt2)); a=offset b=slope c=centre d=width e=height f=sigma."""
    return offset + slope * x + 0.5 * height * (erf((x - centre + width / 2) / (sigma * SQ2)) - erf((x - centre - width / 2) / (sigma * SQ2)))


def _slit_bowed(x, offset, centre, width, height, sigma, k1, k2):
    """Slit with a non-flat plateau: offset + h*(1 + k1*u + k2*u^2) * 1/2[erf(..) - erf(..)], u = (x-centre)/(width/2). NOT in LiveFitter (its plateau is a straight tilt);
    added because a real gh1 slit window (hot-core beam) fitted with the flat model gave an edge sigma 14x too wide (see playbook)."""
    u = (x - centre) / max(width / 2.0, 1e-12)
    return offset + height * (1.0 + k1 * u + k2 * u * u) * 0.5 * (erf((x - centre + width / 2) / (sigma * SQ2)) - erf((x - centre - width / 2) / (sigma * SQ2)))


def _poly(n):
    def f(x, *c):
        return sum(ci * x ** i for i, ci in enumerate(c))
    f.n = n
    return f


def _exp(x, a, b):
    return a * np.exp(-b * x)


def _exp_offset(x, a, b, c):
    return a * np.exp(-b * x) + c


def _exp_recovery(x, a, b, c):
    return a * (1.0 - np.exp(-b * x)) + c


def _exp_recovery_nooff(x, a, b):
    return a * (1.0 - np.exp(-b * x))


def _power(x, a, b):
    return a * np.power(x, b)


def _log_shift(x, a, b, c):
    return a + b * np.log(x - c)


def _rodbard(x, a, b, c, d):
    return d + (a - d) / (1.0 + np.power(x / c, b))


def _gamma_variate(x, a, b, c, d):
    t = np.clip(x - a, 0, None)
    return b * np.power(t, c) * np.exp(-t / d)


def _chapman(x, a, b, c):
    return a * np.power(1.0 - np.exp(-b * x), c)


def _moments_line(x, y):
    return [float(np.mean(y)), 0.0]


# --------------------------------------------------------------------------------------------------------------------------------- initial guesses
def _split(x, y):
    """Smoothed profile, baseline/top levels, and the half-level crossing points (used by several guesses)."""
    k = max(3, len(y) // 40)
    ys = np.convolve(np.pad(y, (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    lo, hi = float(np.percentile(ys, 5)), float(np.percentile(ys, 95))
    return ys, lo, hi


def _crossings(x, ys, level):
    """x positions where the smoothed profile crosses `level` (linear interpolation)."""
    s = ys - level
    idx = np.nonzero(np.sign(s[:-1]) * np.sign(s[1:]) < 0)[0]
    out = []
    for i in idx:
        t = s[i] / (s[i] - s[i + 1])
        out.append(float(x[i] + t * (x[i + 1] - x[i])))
    return out


def _guess_gaussian(x, y):
    ys, lo, hi = _split(x, y)
    span = float(x[-1] - x[0])
    i = int(np.argmax(ys))
    half = _crossings(x, ys, lo + (hi - lo) / 2)
    left = [c for c in half if c < x[i]]
    right = [c for c in half if c > x[i]]
    fwhm = (min(right) - max(left)) if left and right else span / 5
    sig = max(fwhm / FWHM_K, span / 300)
    return [lo, hi - lo, float(x[i]), sig]


def _guess_slit(x, y, positive):
    """Same ideas as LiveFitter's initialParams (centroid for c, area/height for d) but taken from half-level crossings, which are robust to a tilt."""
    ys, lo, hi = _split(x, y)
    span = float(x[-1] - x[0])
    yy = ys if positive else (hi + lo - ys)                      # dark slit -> flip so the aperture is the high part
    half = _crossings(x, yy, lo + (hi - lo) / 2)
    if len(half) >= 2:
        c0, w0 = 0.5 * (half[0] + half[-1]), half[-1] - half[0]
    else:                                                          # fall back to LiveFitter's centroid / area-over-height estimate
        w = yy - yy.min()
        c0 = float((w * x).sum() / max(w.sum(), 1e-12))
        w0 = float(w.sum() / max(w.max(), 1e-12) * (x[1] - x[0]))
    h0 = hi - lo
    return [lo if positive else hi, 0.0, c0, max(w0, span / 100), h0 if positive else -h0, max(span / 100, 1e-9)]


def _guess_bowed(x, y, positive):
    g = _guess_slit(x, y, positive)                               # offset, slope, centre, width, height, sigma
    return [g[0], g[2], g[3], g[4], g[5], 0.0, -0.1]


def _guess_edge(x, y):
    ys, lo, hi = _split(x, y)
    n = max(3, len(y) // 10)
    a, b = float(np.mean(ys[:n])), float(np.mean(ys[-n:]))
    g = np.abs(np.gradient(ys, x))
    i = int(np.argmax(g))
    span = float(x[-1] - x[0])
    return [(a + b) / 2, (b - a) / 2, float(x[i]), span / 40]


def _guess_generic(n, x, y):
    return [float(np.mean(y))] + [1.0] * (n - 1)


# --------------------------------------------------------------------------------------------------------------------------------- model table
def _models():
    M = {}

    def add(name, f, names, formula, guess, bounds=None, ij=None):
        M[name] = {"f": f, "names": names, "formula": formula, "guess": guess, "bounds": bounds, "imagej": ij}

    add("gaussian", _gaussian, ["offset", "amp", "centre", "sigma"], "y = offset + amp*exp(-(x-centre)^2/(2 sigma^2))", _guess_gaussian,
        lambda x, y: ([-np.inf, -np.inf, x[0] - (x[-1] - x[0]), (x[1] - x[0]) / 20], [np.inf, np.inf, x[-1] + (x[-1] - x[0]), (x[-1] - x[0]) * 2]), "Gaussian")
    add("gaussian_nooffset", _gaussian_nooff, ["amp", "centre", "sigma"], "y = amp*exp(-(x-centre)^2/(2 sigma^2))",
        lambda x, y: _guess_gaussian(x, y)[1:], None, "Gaussian (no offset)")
    add("erf_edge", _erf_edge, ["offset", "step", "centre", "sigma"], "y = offset + step*erf((x-centre)/(sigma*sqrt2))", _guess_edge, None, "Error Function")
    add("slit_positive", _slit, ["offset", "slope", "centre", "width", "height", "sigma"],
        "y = offset+slope*x + h/2*[erf((x-c+w/2)/(s*sqrt2)) - erf((x-c-w/2)/(s*sqrt2))], h>0", lambda x, y: _guess_slit(x, y, True), None, "Slit - Positive")
    add("slit_negative", _slit, ["offset", "slope", "centre", "width", "height", "sigma"],
        "same, h<0 (dark slit / blocker in a bright field)", lambda x, y: _guess_slit(x, y, False), None, "Slit - Negative")
    for sign, nm in ((True, "slit_positive_bowed"), (False, "slit_negative_bowed")):
        add(nm, _slit_bowed, ["offset", "centre", "width", "height", "sigma", "k1", "k2"],
            "y = offset + h*(1+k1*u+k2*u^2)*1/2[erf((x-c+w/2)/(s*sqrt2)) - erf((x-c-w/2)/(s*sqrt2))], u=(x-c)/(w/2), h" + (">0" if sign else "<0") + " (not in ImageJ)",
            lambda x, y, sign=sign: _guess_bowed(x, y, sign), None, None)
    for n in range(1, 9):
        add("line" if n == 1 else f"poly{n}", _poly(n), [chr(ord("a") + i) for i in range(n + 1)],
            "y = " + " + ".join(f"{chr(ord('a') + i)}*x^{i}" if i > 1 else (f"{chr(ord('a') + i)}*x" if i == 1 else "a") for i in range(n + 1)),
            lambda x, y, n=n: list(np.polyfit(x, y, n)[::-1]), None, "Straight Line" if n == 1 else f"{n}th Degree Polynomial")
    add("exponential", _exp, ["a", "b"], "y = a*exp(-b*x)", lambda x, y: [float(y[0]) or 1.0, 1.0 / max(x[-1] - x[0], 1e-9)], None, "Exponential")
    add("exponential_offset", _exp_offset, ["a", "b", "c"], "y = a*exp(-b*x) + c",
        lambda x, y: [float(y[0] - y[-1]), 3.0 / max(x[-1] - x[0], 1e-9), float(y[-1])], None, "Exponential with Offset")
    add("exp_recovery", _exp_recovery, ["a", "b", "c"], "y = a*(1-exp(-b*x)) + c",
        lambda x, y: [float(y[-1] - y[0]), 3.0 / max(x[-1] - x[0], 1e-9), float(y[0])], None, "Exponential Recovery")
    add("exp_recovery_nooffset", _exp_recovery_nooff, ["a", "b"], "y = a*(1-exp(-b*x))",
        lambda x, y: [float(y[-1]), 3.0 / max(x[-1] - x[0], 1e-9)], None, "Exponential Recovery (no offset)")
    add("power", _power, ["a", "b"], "y = a*x^b (x>0)", lambda x, y: [float(np.mean(y)), 1.0], None, "Power")
    add("log", _log_shift, ["a", "b", "c"], "y = a + b*ln(x-c) (x>c)", lambda x, y: [float(np.mean(y)), 1.0, float(x.min() - 0.1 * (x.max() - x.min()) - 1e-6)], None, "y = a+b*ln(x-c)")
    add("rodbard", _rodbard, ["a", "b", "c", "d"], "y = d + (a-d)/(1+(x/c)^b)",
        lambda x, y: [float(y[0]), 1.0, float(np.median(x[x > 0]) if (x > 0).any() else 1.0), float(y[-1])], None, "Rodbard")
    add("gamma_variate", _gamma_variate, ["a", "b", "c", "d"], "y = b*(x-a)^c*exp(-(x-a)/d)",
        lambda x, y: [float(x[0]), float(np.max(y)), 1.0, float((x[-1] - x[0]) / 4)], None, "Gamma Variate")
    add("chapman_richards", _chapman, ["a", "b", "c"], "y = a*(1-exp(-b*x))^c", lambda x, y: [float(np.max(y)), 1.0 / max(x[-1] - x[0], 1e-9), 1.0], None, "Chapman-Richards")
    return M


MODELS = _models()


def list_models():
    """{name: {params, formula, imagej}} for the model catalogue."""
    return {k: {"params": v["names"], "formula": v["formula"], "imagej": v["imagej"]} for k, v in MODELS.items()}


# --------------------------------------------------------------------------------------------------------------------------------- the fitter
def _derived(model, p):
    d = {}
    if model.startswith("gaussian"):
        sig = abs(p["sigma"])
        d["fwhm"] = FWHM_K * sig
        if "offset" in p:                                        # Gaussian_Profiler: peak I = fit peak, BG = offset, contrast = 100*(I-Ib)/Ib
            d["peak"] = p["offset"] + p["amp"]
            d["background"] = p["offset"]
            d["contrast_pct"] = 100.0 * p["amp"] / p["offset"] if p["offset"] else float("nan")
    elif model == "erf_edge":
        d["fwhm_of_derivative"] = FWHM_K * abs(p["sigma"])
        d["width_10_90"] = 2.5631 * abs(p["sigma"])
    elif model.startswith("slit"):
        d["edge_fwhm"] = FWHM_K * abs(p["sigma"])
        d["edge_width_10_90"] = 2.5631 * abs(p["sigma"])
        d["left_edge"] = p["centre"] - p["width"] / 2
        d["right_edge"] = p["centre"] + p["width"] / 2
        d["aperture"] = p["width"]
    return d


def fit(x, y, model="gaussian", p0=None, weights=None, restarts=4):
    """Least-squares fit of a named 1-D model (see MODELS) with data-derived starting values and, for gaussian/slit, physical bounds. x, y: 1-D arrays.
    p0: optional dict/list of starting values. weights: optional per-point 1/sigma. Slit models retry from perturbed starts (LiveFitter retried up to 4 times
    until goodness >= 0.7) and keep the best by R^2. Returns a JSON-safe dict; ok=False with 'error' when nothing converged."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = MODELS.get(model)
    if m is None:
        return {"ok": False, "error": f"unknown model '{model}'", "models": sorted(MODELS)}
    good = np.isfinite(x) & np.isfinite(y)
    x, y = x[good], y[good]
    npar = len(m["names"])
    if len(x) < max(npar + 2, 6):
        return {"ok": False, "error": f"too few points ({len(x)}) for {model}"}
    order = np.argsort(x)
    x, y = x[order], y[order]
    w = None if weights is None else np.asarray(weights, float)[good][order]
    span = float(x[-1] - x[0])
    if span <= 0:
        return {"ok": False, "error": "x has zero range"}
    try:
        start = list(p0.values()) if isinstance(p0, dict) else list(p0) if p0 is not None else m["guess"](x, y)
    except Exception as e:
        return {"ok": False, "error": f"cannot guess start values: {e}"}
    lo, hi = (-np.inf,) * npar, (np.inf,) * npar
    if m["bounds"] is not None:
        lo, hi = m["bounds"](x, y)
    if model.startswith("slit"):
        pos = model.startswith("slit_positive")
        ymin, ymax = float(y.min()), float(y.max())
        rng = max(ymax - ymin, 1e-12)
        dx = float(np.median(np.diff(x)))
        h_lo, h_hi = (0.05 * rng, 2 * rng) if pos else (-2 * rng, -0.05 * rng)
        if model.endswith("_bowed"):                              # offset, centre, width, height, sigma, k1, k2
            lo = [ymin - rng, x[0], 2 * dx, h_lo, 0.3 * dx, -2.0, -2.0]
            hi = [ymax + rng, x[-1], span, h_hi, span / 4, 2.0, 2.0]
        else:                                                      # offset, slope, centre, width, height, sigma: bounds inspired by LiveFitter, in x units
            lo = [ymin - rng, -2 * rng / span, x[0], 2 * dx, h_lo, 0.3 * dx]
            hi = [ymax + rng, 2 * rng / span, x[-1], span, h_hi, span / 4]
    scale = float(np.std(y)) or 1.0

    def resid(p):
        r = m["f"](x, *p) - y
        return r / scale if w is None else r * w / scale

    best = None
    rs = np.random.default_rng(0)
    starts = [np.array(start, float)]
    if restarts and (model.startswith("slit") or model.startswith("gaussian") or model == "erf_edge"):
        for _ in range(restarts):
            starts.append(starts[0] * (1 + 0.25 * rs.standard_normal(npar)) + 0.05 * span * rs.standard_normal(npar) * np.isin(np.arange(npar), _pos_idx(model)))
    for s0 in starts:
        try:
            s0 = np.clip(s0, np.array(lo, float), np.array(hi, float))
            r = least_squares(resid, s0, bounds=(lo, hi), method="trf", max_nfev=4000)
        except Exception:
            continue
        if not np.all(np.isfinite(r.x)):
            continue
        if best is None or r.cost < best.cost:
            best = r
        if model.startswith("slit") and _r2(y, m["f"](x, *best.x)) >= 0.995:
            break
    if best is None:
        return {"ok": False, "error": f"{model} fit did not converge"}
    p = best.x
    fitted = m["f"](x, *p)
    r2 = _r2(y, fitted)
    err = [None] * npar
    try:                                                          # covariance from the Jacobian, scaled by the residual variance
        J = best.jac
        dof = max(len(x) - npar, 1)
        s2 = float(np.sum((fitted - y) ** 2)) / dof
        cov = np.linalg.inv(J.T @ J) * s2 / scale ** 2 * scale ** 2
        e = np.sqrt(np.abs(np.diag(cov)))
        err = [float(v) if np.isfinite(v) else None for v in e]
    except Exception:
        pass
    params = {n: float(v) for n, v in zip(m["names"], p)}
    if "sigma" in params:
        params["sigma"] = abs(params["sigma"])
    if model.startswith("slit"):
        params["width"] = abs(params["width"])
    return {"ok": True, "model": model, "formula": m["formula"], "params": params, "errors": dict(zip(m["names"], err)), "r2": r2,
            "rms": float(np.sqrt(np.mean((fitted - y) ** 2))), "derived": _derived(model, params), "x": x.tolist(), "curve": fitted.tolist(), "n": int(len(x))}


def _pos_idx(model):
    return {"gaussian": [2], "erf_edge": [2], "slit_positive": [2, 3], "slit_negative": [2, 3], "slit_positive_bowed": [1, 2], "slit_negative_bowed": [1, 2]}.get(model, [])


def _r2(y, f):
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1.0
    return float(1.0 - np.sum((y - f) ** 2) / ss_tot)


def auto(x, y, models=("gaussian", "erf_edge", "slit_positive", "slit_negative", "slit_positive_bowed", "slit_negative_bowed")):
    """Fit several models and return the best by adjusted residual (BIC-like penalty on parameter count), plus the table of all of them."""
    res = {m: fit(x, y, m) for m in models}
    ok = {m: r for m, r in res.items() if r.get("ok")}
    if not ok:
        return {"ok": False, "error": "no model converged", "tried": {m: r.get("error") for m, r in res.items()}}
    n = len(np.asarray(x))
    def score(r):
        k = len(r["params"])
        return n * np.log(max(r["rms"], 1e-12) ** 2) + k * np.log(n)
    best = min(ok, key=lambda m: score(ok[m]))
    out = dict(ok[best])
    out["compared"] = {m: {"r2": r["r2"], "rms": r["rms"]} for m, r in ok.items()}
    out["chosen_by"] = "BIC"
    return out


def moments(x, y, baseline=None):
    """Model-free profile statistics from Gaussian_Profiler: intensity-weighted centroid and RMS width (sqrt of the second moment), max and min, and FWHM
    from half-max crossings of the (baseline-subtracted) profile. baseline: level to subtract (default: the 5th percentile)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    bg = float(np.percentile(y, 5)) if baseline is None else float(baseline)
    w = np.clip(y - bg, 0, None)
    s = float(w.sum())
    if s <= 0:
        return {"ok": False, "error": "no signal above baseline"}
    mean = float((w * x).sum() / s)
    rms = float(np.sqrt((w * (x - mean) ** 2).sum() / s))
    ys, lo, hi = _split(x, y)
    half = _crossings(x, ys, bg + 0.5 * (float(ys.max()) - bg))
    i = int(np.argmax(ys))
    left = [c for c in half if c < x[i]]
    right = [c for c in half if c > x[i]]
    return {"ok": True, "centroid": mean, "rms_width": rms, "baseline": bg, "max": float(y.max()), "min": float(y.min()), "x_at_max": float(x[i]),
            "fwhm_halfmax": float(min(right) - max(left)) if left and right else None,
            "contrast_pct": float(100 * (y.max() - bg) / bg) if bg else None}
