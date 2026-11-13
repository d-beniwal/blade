"""Synthetic-data tests for blade.analysis (fits ported from ADViewers). Run: python -I tests/test_analysis.py"""
import sys, tempfile, os
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blade.imganalysis import fitting as F, profile as P
from blade import registry

rng = np.random.default_rng(3)
x = np.linspace(0, 400, 401)

# gaussian: truth recovered, FWHM relation, contrast like Gaussian_Profiler
y = 100 + 900 * np.exp(-0.5 * ((x - 187.3) / 21.0) ** 2) + rng.normal(0, 5, x.size)
r = F.fit(x, y, "gaussian")
assert r["ok"] and abs(r["params"]["centre"] - 187.3) < 0.5 and abs(r["params"]["sigma"] - 21) < 0.7, r
assert abs(r["derived"]["fwhm"] - 2.3548 * 21) < 2 and abs(r["derived"]["peak"] - 1000) < 15 and abs(r["derived"]["contrast_pct"] - 900) < 30

# slit, positive and negative, with tilt
for model, sign in (("slit_positive", 1), ("slit_negative", -1)):
    base = 50 if sign > 0 else 1000
    yy = base + 0.02 * x + sign * 900 / 2 * (F.erf((x - 210 + 60) / (6 * 2 ** 0.5)) - F.erf((x - 210 - 60) / (6 * 2 ** 0.5))) + rng.normal(0, 5, x.size)
    r = F.fit(x, yy, model)
    p = r["params"]
    assert r["ok"] and r["r2"] > 0.99, r
    assert abs(p["centre"] - 210) < 1 and abs(p["width"] - 120) < 2 and abs(p["sigma"] - 6) < 1, (model, p)
    a = F.auto(x, yy)
    assert a["ok"] and a["model"] == model, a["model"]

# edge
ye = 20 + 300 * (1 + F.erf((x - 123 - 0) / (9 * 2 ** 0.5))) / 2 + rng.normal(0, 3, x.size)
r = F.fit(x, ye, "erf_edge")
assert abs(r["params"]["centre"] - 123) < 1 and abs(r["params"]["sigma"] - 9) < 1, r
# polynomial / exponential / bad input
assert abs(F.fit(x, 3 + 2 * x, "line")["params"]["b"] - 2) < 1e-6
assert F.fit(x, 5 * np.exp(-x / 80) + 1, "exponential_offset")["r2"] > 0.999
assert not F.fit([1, 2, 3], [1, 2, 3], "gaussian")["ok"] and not F.fit(x, y, "nope")["ok"]
m = F.moments(x, y)
assert abs(m["centroid"] - 187.3) < 2 and abs(m["fwhm_halfmax"] - 2.3548 * 21) < 4

# ROI + line profiles on an image, absolute pixel scale
H, W = 200, 500
yy_, xx_ = np.mgrid[0:H, 0:W]
img = 10 + 500 * np.exp(-0.5 * (((xx_ - 300) / 30.0) ** 2 + ((yy_ - 100) / 15.0) ** 2)) + rng.normal(0, 2, (H, W))
pr = P.rect_profile(img, 200, 90, 400, 110, "horizontal", pixel_um=0.69)
assert abs(F.fit(pr["x"], pr["y"], "gaussian")["params"]["centre"] - 300 * 0.69) < 1.0
pv = P.rect_profile(img, 290, 0, 310, 200, "vertical", pixel_um=1.0)
assert abs(F.fit(pv["x"], pv["y"], "gaussian")["params"]["centre"] - 100) < 1
pl = P.line_profile(img, 150, 100, 450, 100, pixel_um=1.0, width=5)
assert abs(F.fit(pl["x"], pl["y"], "gaussian")["params"]["centre"] - 300) < 1, "absolute scale start"

# MCP tools through the registry (image from file)
registry.load_modules()
assert {"analysis_list_models", "analysis_fit_profile", "analysis_fit_roi", "analysis_fit_line"} <= set(registry.TOOLS)
with tempfile.TemporaryDirectory() as d:
    f = os.path.join(d, "frame.npy"); np.save(f, img)
    out = registry.invoke("analysis_fit_roi", image_path=f, x0=200, y0=90, x1=400, y1=110, pixel_um=1.0)
    assert out["fit"]["ok"] and out["fit"]["model"] == "gaussian", out["fit"].get("model")
    assert abs(out["fit"]["params"]["centre"] - 300) < 1
out = registry.invoke("analysis_fit_profile", x=x.tolist(), y=y.tolist(), model="gaussian")
assert out["fit"]["ok"]
print("test_analysis OK")
