"""Synthetic-data tests for blade.analysis (fits ported from ADViewers). Run: python -I tests/test_analysis.py"""
import sys, tempfile, os
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()          # vbl sessions stay out of the repo
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blade.imganalysis import fitting as F, profile as P
ROOT = Path(__file__).resolve().parents[1]
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

# bowed plateau (hot-core beam): the flat-top slit model over-estimates the edge sigma, the bowed one recovers it
u = (x - 200) / 150.0
yb = 300 + 8000 * (1 - 0.1 * u - 0.5 * u * u) * 0.5 * (F.erf((x - 200 + 150) / (7 * 2 ** 0.5)) - F.erf((x - 200 - 150) / (7 * 2 ** 0.5))) + rng.normal(0, 30, x.size)
rb, rf = F.fit(x, yb, "slit_positive_bowed"), F.fit(x, yb, "slit_positive")
assert abs(rb["params"]["sigma"] - 7) < 2 and abs(rb["derived"]["aperture"] - 300) < 4 and rb["r2"] > rf["r2"], (rb["params"], rf["params"])
assert rf["params"]["sigma"] > 3 * rb["params"]["sigma"], "flat model should blur the edge"
assert F.auto(x, yb)["model"] == "slit_positive_bowed"
ydark = 9000 - (yb - 300)
assert F.fit(x, ydark, "slit_negative_bowed")["ok"]

# GUI path (vbl_api.profile = drawn box, direction h/v, fit kinds) on a simulated frame
from blade.vbl import store
from blade import vbl_api
store.reset(5, "ready_for_pin", "t_analysis")
box = dict(x0=0.0, y0=0.15, x1=1.0, y1=0.35)
for kind in ("slit_pos", "slit_neg", "slit_pos_flat", "slit_neg_flat", "auto", "gauss", "scurve", "none"):
    for d in ("h", "v"):
        r = vbl_api.profile(dict(camera="gh1", bin=2, direction=d, fit=kind, **box), "t_analysis")
        assert r["direction"] == d and len(r["dist_um"]) == len(r["counts"]) == r["n"] and r["rows_averaged"] > 0
        assert "error" not in r.get("fit", {}), (kind, d, r["fit"])
rh = vbl_api.profile(dict(camera="gh1", bin=2, direction="h", fit="slit_pos", **box), "t_analysis")
rv = vbl_api.profile(dict(camera="gh1", bin=2, direction="v", fit="auto", x0=0.3, y0=0.0, x1=0.7, y1=1.0), "t_analysis")
f = rh["fit"]
assert f["kind"] == "slit_pos" and len(f["edges"]) == 2 and f["aperture"] > 0 and len(f["edges_frac"]) == 2 and "centre_frac" in f
assert abs(f["edges_frac"][0][1] - 0.25) < 0.01 and f["edges_frac"][0][0] < f["edges_frac"][1][0]     # markers sit on the box mid-row, ordered
assert rh["dist_um"][0] > 0 and rh["dist_um"][-1] < rh["frame_um"] and rv["frame_um"] != rh["frame_um"]  # absolute positions inside the frame
assert abs(rv["fit"]["centre_frac"][0] - 0.5) < 0.01                                                      # vertical profile: marker on the box mid-column

# real gh1 frame (local only: knowledge tree data/, outside the repo). Edges read off the image: window ~310-1035 um (0.69 um/px), see playbooks/image_analysis.md
from blade import paths  # noqa: E402
real = paths.knowledge_dir("data") / "tomo_alignment/alignment_pin/alignment_pin_000044.h5"
if real.exists():
    import h5py
    with h5py.File(real) as h:
        im = h["exchange/data"][...].astype(float).mean(0) - h["exchange/data_dark"][0].astype(float)
    pr = P.rect_profile(im, 250, 380, 1750, 460, "horizontal", 0.69)
    fb = F.fit(pr["x"], pr["y"], "slit_positive_bowed")
    assert fb["r2"] > 0.995 and abs(fb["derived"]["left_edge"] - 308) < 15 and abs(fb["derived"]["right_edge"] - 1038) < 15 and fb["params"]["sigma"] < 20, fb["params"]
    assert F.fit(pr["x"], pr["y"], "slit_positive")["params"]["sigma"] > 50      # flat model blurs the same edge
    pp = P.rect_profile(im, 600, 900, 1350, 940, "horizontal", 0.69)
    fn = F.fit(pp["x"], pp["y"], "slit_negative_bowed")
    assert fn["r2"] > 0.98 and abs(fn["derived"]["aperture"] - 261) < 10, fn["params"]      # the pin shadow
    print("real gh1 frame checks OK")
else:
    print("(real gh1 frame not found: skipped)")
print("test_analysis OK")
