"""Virtual beamline (blade.vbl): physics checks against numbers in the logs, the tomo-camera views (beam on camera, slit edges sharp/blurry, pin), the operator
procedures, the start-of-beamtime sequence from random misalignments, `blade align` on the vbl backend, the MCP tools and the GUI endpoints. SIMULATION ONLY.
Run: python -I tests/test_vbl.py   (env `blade`: numpy, scipy, xraydb)"""
import json, math, os, sys, tempfile, threading, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()          # sessions and runs stay out of the repo
import numpy as np
from blade.vbl.world import VirtualBeamline, SLIT_IDS
from blade.vbl import imaging as im, procedures as P, store
from blade.physics import lens as plens


def ok(msg):
    print("PASS", msg)


# ---------------------------------------------------------------------------------------------------------------------------------- flux physics
w = VirtualBeamline(seed=1, scenario="aligned")
ic0 = w.ic_kHz("icB1")
assert 165 < ic0 < 190, ic0                                                   # logged reference: IC_B1 = 174-178.5 kHz at WB 0.3x0.3, 200 mA
dark = w.sim["ic"]["dark_kHz"]
w.set("wbSlits.hsize", 0.5); w.set("wbSlits.vsize", 0.5)
w.advance(6000.0)                                                             # the mono warms up (thermal shift of the Th2 optimum) ...
w.set("hem.th2_offset", w.sim["hem"]["th2_offset_deg"] + w.s["truth"]["th2_err_deg"] + w._thermal_target())
ratio = (w.ic_kHz("icB1") - dark) / (ic0 - dark)
assert abs(ratio - 1.72) < 0.12, ratio                                        # log: 0.3 -> 0.5 mm WB raised IC_B1 x1.72 for an area ratio of x2.78
ok(f"icB1 = {ic0:.0f} kHz (logs 174-178) and WB 0.3 -> 0.5 mm flux x{ratio:.2f} (logs x1.72, area x2.78)")

w = VirtualBeamline(seed=1, scenario="aligned")
base = w.ic_kHz("icB1") - dark
w.set("ring.current", 150.0)
assert abs((w.ic_kHz("icB1") - dark) / base - 0.75) < 0.03
w.set("ring.current", 200.0)
w.set("foilB.pos", "Re")
mu = w.mu_t()
assert abs(mu - 1.4) < 0.1, mu
w.set("hem.energy", 71.676 + 0.035)
assert w.mu_t() > mu + 0.2                                                    # +35 eV moves mu_t a lot (log: 0.946 -> 1.402 for +35 eV at Re)
ok("flux linear in ring current; mu_t(Re) = b at the calibrated energy and steep across the edge")

# undulator: scan finds the optimum, hysteresis, width
w = VirtualBeamline(seed=4, scenario="startup")
w.set("samE.y", 26.0)
g = P.nominal_gap(w)
P.open_gap(w, g["gap_mm"]); w.set("und.gap", g["gap_mm"])
r = P.gap_scan(w, g["gap_mm"], 0.30, 61)
assert abs(r["peak_gap_mm"] - w.optimal_gap(w.ctl("hem.energy"))) < 0.02, (r["peak_gap_mm"], w.optimal_gap(w.ctl("hem.energy")))
assert 0.05 < r["fwhm_mm"] < 0.13, r["fwhm_mm"]                               # logs: 0.07-0.11 mm
w.set("und.gap", r["peak_gap_mm"] + 0.2); w.set("und.gap", r["peak_gap_mm"])
a = w.source_flux()
assert w.gap_actual() == w.ctl("und.gap")                                      # approached from the open (large-gap) side: repeatable
w.set("und.gap", r["peak_gap_mm"] - 0.2); w.set("und.gap", r["peak_gap_mm"])  # approached from the closed side: the real gap lags (hysteresis)
assert abs(w.gap_actual() - w.ctl("und.gap") - w.sim["undulator"]["hysteresis_mm"]) < 1e-9
assert abs(w.source_flux() - a) > 0.002 * a
ok(f"gap scan: peak error {abs(r['peak_gap_mm'] - w.optimal_gap(w.ctl('hem.energy'))) * 1e3:.1f} um, FWHM {r['fwhm_mm']:.3f} mm, hysteresis visible")

# ---------------------------------------------------------------------------------------------------------------------------------- camera: beam search and view
w = VirtualBeamline(seed=2, scenario="startup")
w.set("samE.y", 26.0)
for s in SLIT_IDS[1:]:
    w.set(f"{s}.hsize", 3.0); w.set(f"{s}.vsize", 3.0)
assert P.analyze_frame(im.render(w, "gh1"), 0.69)["beam"]                       # startup now begins with the beam already on gh1
w.set("tomoE.x", w.sim["tomo_stages"]["tomoE"]["out_x_mm"])                     # park the camera out
dark_img = im.render(w, "gh1")                                                # camera is parked out of the beam: dark frame
assert not P.analyze_frame(dark_img, 0.69)["beam"] and dark_img.mean() < 7000
fb = P.find_beam_on_camera(w, "gh1", 3.5)
assert fb["found"] and fb["centred"] and not fb["analysis"]["touches_frame"], fb      # find-beam must leave the footprint inside the frame, not in a corner
c = P.centre_camera_on_beam(w, "gh1", "footprint")
assert c["ok"] and not c["analysis"]["touches_frame"], c
x0 = w.ctl("tomoE.x")
a1 = P.analyze_frame(im.render(w, "gh1"), 0.69)["centroid_px"]["x"]
w.set("tomoE.x", x0 + 0.10)                                                   # +0.10 mm of stage moves the image by 145 px (to the left)
a2 = P.analyze_frame(im.render(w, "gh1"), 0.69)["centroid_px"]["x"]
assert abs((a1 - a2) - 0.10 / 0.69e-3) < 8, (a1, a2)
ok(f"camera dark when out; beam found at x={fb['x_mm']:.2f} mm; 0.10 mm stage move = {a1 - a2:.0f} px (expected 145)")

# ---------------------------------------------------------------------------------------------------------------------------------- GUI line profile + fits
from blade import vbl_api
from blade.vbl import store as _st
_st.reset(1, "startup", "prof")
_w = _st.require("prof"); P.find_beam_on_camera(_w, "gh1"); _st.save(_w, "prof")
_e = vbl_api.profile(dict(camera="gh1", bin=2, width=9, x0=0.05, y0=0.5, x1=0.35, y1=0.5, fit="scurve"), "prof")["fit"]
assert "error" not in _e and _e["r2"] > 0.95 and _e["params"]["step"] > 0 and 45 < _e["width_10_90"] < 160, _e          # footprint left edge: rising S-curve, ~100 um 10-90 (the mottled beam biases a single-line fit a little)
_g = vbl_api.profile(dict(camera="gh1", bin=2, width=9, x0=0.0, y0=0.5, x1=1.0, y1=0.5, fit="gauss"), "prof")["fit"]
assert "error" not in _g and 0.0 < _g["params"]["centre"] < 1339 and _g["fwhm"] > 300, _g
assert vbl_api.profile(dict(camera="gh1", bin=2, width=9, x0=0.0, y0=0.5, x1=1.0, y1=0.5, fit="auto"), "prof")["fit"]["kind"] in ("gauss", "scurve")
ok(f"line profile: S-curve edge 10-90 = {_e['width_10_90']:.0f} um (R2 {_e['r2']:.3f}); Gaussian FWHM {_g['fwhm']:.0f} um")

# ---------------------------------------------------------------------------------------------------------------------------------- slit edges: sharp vs blurry
w = VirtualBeamline(seed=1, scenario="ready_for_pin")
w.set("samE.y", 26.0)                                                         # pin out
w.set("slitEus.hsize", 3.0); w.set("slitEus.vsize", 3.0)
w.set("slitEds.hsize", 3.0); w.set("slitEds.vsize", 3.0)
img, info = im.render(w, "gh1", return_info=True, with_noise=False)
an_wb = P.analyze_frame(img, 0.69)
assert info["h"]["low_side"]["id"] == "wbSlits" and info["h"]["low_side"]["penumbra_px"] > 20
wb_w = an_wb["edge_width_10_90_px"]
assert min(wb_w["left"], wb_w["right"], wb_w["bottom"]) > 40, wb_w                  # logs: WB-limited ramps 60-100 px (top is a sharp step on a pedestal in this scenario: another aperture defines it)
w.set("slitEus.hsize", 0.45); w.set("slitEus.vsize", 0.40)                    # now the E upstream slit is IN the beam: it defines the edges
w.set("slitEus.hcenter", w.ctl("slitEus.hcenter"));
img2, info2 = im.render(w, "gh1", return_info=True, with_noise=False)
an_s = P.analyze_frame(img2, 0.69)
assert info2["h"]["low_side"]["id"] == "slitEus" and info2["h"]["low_side"]["penumbra_px"] < 3
sw = an_s["edge_width_10_90_px"]
assert max(sw["left"], sw["right"], sw["top"], sw["bottom"]) < 16, sw         # logs: Kohzu E edges 5-10 px (0.78-1.17 um/px)
assert an_s["box_px"]["width"] < an_wb["box_px"]["width"] * 0.7
ok(f"WB-limited edges {wb_w['left']:.0f}/{wb_w['right']:.0f} px (blurry), E-slit-limited {sw['left']:.0f}/{sw['right']:.0f} px (sharp, footprint shrinks)")

# ---------------------------------------------------------------------------------------------------------------------------------- pin
w = VirtualBeamline(seed=3, scenario="ready_for_pin")
p_mm = 0.69e-3
cols = []
for om in (-60.0, -30.0, 0.0, 30.0, 60.0):
    w.set("samE.ry", om)
    img = im.render(w, "gh1", with_noise=False)
    ref = im.render(w, "gh1", with_noise=False, with_pin=False)                    # flat field: the beam is mottled, so divide it out before thresholding
    row = int(0.62 * img.shape[0])
    prof = img[row].astype(float)
    lit0 = np.nonzero(ref[row] > 0.5 * np.percentile(ref[row], 99))[0]
    rat = np.where(ref[row] > 0.2 * ref[row].max(), prof / np.maximum(ref[row].astype(float), 1.0), 1.0)
    inside = np.nonzero(rat < (rat[lit0.min():lit0.max()].max() + rat[lit0.min():lit0.max()].min()) / 2.0)[0]
    # truth column vs the measured silhouette centre (mid of the longest dark run inside the beam)
    truth = (w.pin_state()["u"] - w.camera_view("gh1")[1]) / p_mm + (img.shape[1] - 1) / 2.0
    dark_run = inside[(inside > lit0.min()) & (inside < lit0.max())]
    cols.append((om, truth, float(dark_run.mean())))
for om, tr, ms in cols:
    assert abs(tr - ms) < 12.0, (om, tr, ms)                                  # silhouette centre follows the true sinusoid (cone widens with row)
cs = np.array([t for _, t, _ in cols])
oms = np.radians([o for o, _, _ in cols])
A = np.c_[np.ones(5), np.cos(oms), np.sin(oms)]
fit = np.linalg.lstsq(A, cs, rcond=None)[0]
assert abs(fit[1] - w.pin_state(0)["a"] / p_mm) < 1.0 and abs(fit[2] - w.pin_state(0)["b"] / p_mm) < 1.0
w.set("samE.ry", 0.0)
x_before = w.pin_state()["u"]
w.set("samE.x", w.ctl("samE.x") + 0.05)
assert (w.pin_state()["u"] - x_before) < 0 and abs((w.pin_state()["u"] - x_before) + 0.05) < 1e-9     # +x moves the pin image left (hardware-confirmed sign)
w.set("samE.aerox", 0.05)
assert abs(w.pin_state()["c"] - w.pin_state()["c"]) == 0
ok("pin silhouette follows x(w) = c + a cos w + b sin w; +x moves it left")

# ---------------------------------------------------------------------------------------------------------------------------------- lens focus
w = VirtualBeamline(seed=2, scenario="camera_in_beam")
w.set("samE.y", 26.0)
for s in ("slitEus", "slitEds"):
    w.set(s + ".hsize", 1.5); w.set(s + ".vsize", 1.5)
w.set("lens2E.x", 0.0)
motor, tilt = plens.focus_motor_target("lens2E", w.energy_actual_keV())
w.set(f"lens2E.{motor}", tilt - 0.03)
r = P.lens_scan(w, "lens2E", "gh1", 0.05, 21)
assert abs(r["best_tilt_deg"] - r["predicted_tilt_deg"]) < 0.015, r["best_tilt_deg"]
ok(f"lens tilt scan optimum {r['best_tilt_deg']:+.4f} deg vs beamline prediction {r['predicted_tilt_deg']:+.4f} deg (logs: within 0.002-0.010)")

# ---------------------------------------------------------------------------------------------------------------------------------- start-of-beamtime sequence from random misalignments
for seed in (3, 5, 8):
    w = VirtualBeamline(seed=seed, scenario="startup")
    P.startup_sequence(w, "Re", "gh1")
    r = w.truth_report()
    assert all(r["ok"].values()), (seed, r["ok"])
    assert abs(r["energy_mu_t_error"]) < 0.1
    assert 150 < w.ic_kHz("icB1") < 190, w.ic_kHz("icB1")
ok("start-of-beamtime sequence from random misalignments: gap, Th2, energy (mu_t = b), steering, E slits all within tolerance; icB1 back at ~176 kHz (3 seeds)")

# ---------------------------------------------------------------------------------------------------------------------------------- blade align on the vbl backend + MCP tools
from blade import registry
tools = registry.load_modules()
assert {"vbl_reset", "vbl_set", "vbl_get_frame", "vbl_startup_sequence", "vbl_gap_scan", "vbl_align_slit", "vbl_readiness"} <= set(tools)
r = registry.invoke("vbl_reset", seed=11, scenario="ready_for_pin")
assert r["ok"]
f = registry.invoke("vbl_get_frame", camera="gh1", bin=2)
assert f["analysis"]["beam"] and Path(f["png"]).is_file()
try:
    registry.invoke("vbl_set", control="und.gap", value=2.0)
    raise SystemExit("limit not enforced")
except ValueError:
    pass
registry.invoke("new_run", backend="vbl", camera="gh1")
res = registry.invoke("align_adaptive")
assert res["final"]["converged"], res
tr = registry.invoke("vbl_readiness")["axis"]
assert abs(tr["a_px"]) < 2.5 and abs(tr["b_px"]) < 2.5 and abs(tr["axis_minus_beam_px"]) < 3.0, tr
ok(f"`blade align adaptive` on the virtual beamline converged (truth a={tr['a_px']:+.2f}, b={tr['b_px']:+.2f}, axis-beam={tr['axis_minus_beam_px']:+.2f} px)")

# ---------------------------------------------------------------------------------------------------------------------------------- GUI endpoints
from blade import gui
port = 8780 + os.getpid() % 100
threading.Thread(target=gui.serve, args=(port, None), daemon=True).start()
time.sleep(0.8)
base = f"http://localhost:{port}"
get = lambda p: urllib.request.urlopen(base + p).read()
post = lambda p, b: json.loads(urllib.request.urlopen(urllib.request.Request(base + p, data=json.dumps(b).encode(), method="POST", headers={"Content-Type": "application/json"})).read())
post("/api/vbl/reset", {"scenario": "ready_for_pin", "seed": 2})
st = json.loads(get("/api/vbl/state"))
assert st["scenario"] == "ready_for_pin" and "icB1" in st["snapshot"]["ic_kHz"] and "truth" not in st
assert "truth" in json.loads(get("/api/vbl/state?reveal=1"))
assert post("/api/vbl/set", {"name": "wbSlits.hsize", "value": 0.25})["readback"] == 0.25
assert get("/api/vbl/frame?camera=gh1&bin=4")[:8] == b"\x89PNG\r\n\x1a\n"
assert b"BLADE virtual beamline" in get("/vbl")
try:
    post("/api/vbl/tool", {"name": "new_run", "args": {}})
    raise SystemExit("non-vbl tool accepted")
except urllib.error.HTTPError:
    pass
ok("GUI /vbl: state, set, frame (PNG), tools; truth only on request; non-vbl tools refused")
print("ALL OK")
