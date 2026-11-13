"""Fitted focusing-optics models (blade.physics.optics_fit): reproduce the logged tuples they were fitted on, agree with the JSON, and agree with
blade.vbl's penumbra. No hardware. Run: python -I tests/test_fit_optics.py   (vbl cross-check needs numpy/scipy; skipped if missing)"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from blade.physics import optics_fit as O, lens as L

close = lambda a, b, tol: abs(a - b) <= tol
J = json.load(open(ROOT / "beamline_twins/1-ID/physics/fits/optics.json"))
n = 0


def ok(name):
    global n
    n += 1
    print("PASS", name)


# 1. JSON params == module constants (so the embedded fallbacks cannot drift)
for k, v in J["params"].items():
    assert O.P[k] == v, (k, O.P[k], v)
ok("params json == module")

# 2. tilt lens: the four logged focus tilts (2026 startup log, Hf edge 65.351 keV; sample plane and +205 mm) within 2 mdeg
for lens, dz, th in (("lens1E", 0.0, 0.11875), ("lens1E", 0.205, 0.132), ("lens2E", 0.0, 0.10579), ("lens2E", 0.205, 0.11865)):
    got = O.tilt_for_focus_deg(lens, 65.351, O.P["z_sample_E_m"] + dz)
    assert close(got, th, 0.002), (lens, dz, got, th)
ok("tilt lens reproduces the 4 logged optima (<2 mdeg)")
# motor targets incl. zero/sign: logged 'real' optima 0.107/-0.168 (sample) and 0.121/-0.181 (+205 mm)
for lens, dz, real in (("lens1E", 0, 0.107), ("lens1E", 0.205, 0.121), ("lens2E", 0, -0.168), ("lens2E", 0.205, -0.181)):
    m, t = O.lens_motor_target(lens, 65.351, O.P["z_sample_E_m"] + dz)
    assert m == "th" and close(t, real, 0.0015), (lens, dz, t, real)
ok("motor targets match logged real optima (<1.5 mdeg); old model error was up to 10 mdeg")

# 3. energy scaling: theta ~ 1/E^2 (Feb 2026, 51.935 keV, raw 0.1730 / -0.2302 incl. zeros)
for lens, raw in (("lens1E", 0.1730), ("lens2E", -0.2302)):
    m, t = O.lens_motor_target(lens, 51.935)
    assert close(t, raw, 0.005), (lens, t, raw)
ok("1/E^2 scaling reproduces Feb-2026 tilts (<5 mdeg)")

# 4. identifiability facts recorded in the JSON
tl = J["fits"]["tilt_lens"]
assert close(tl["z_sample_E_m"]["value"], 69.49, 0.05) and close(tl["tilt_c"]["value"], 2.11, 0.05)
assert 1.9 < tl["tilt_c"]["value"] - tl["tilt_c"]["unc"] and tl["tilt_c"]["value"] + tl["tilt_c"]["unc"] < 2.4
assert tl["variants"]["c_equal_1"]["chi2"] > 20 and tl["variants"]["c_equal_1"]["p_offset_m"] > 1e6      # c = 1 fails (the 'nonsense')
chis = [v["chi2"] for v in tl["variants"]["p_profile"].values()]
assert max(chis) - min(chis) < 0.05                                                                       # p unconstrained
ok("c=2.11+-0.17, z_sample=69.49+-0.15 m, c=1 rejected, p unconstrained")

# 5. focus sensitivity, B stack on tomoB, defaults differ from the old lens.py model
s = O.focus_shift_mm_per_mdeg("lens1E", 0.11875, 65.351)
assert 12 < s < 19, s
m, t = O.lens_motor_target("lens4B", 55.618, 43.0)
assert close(abs(t), 0.822, 0.04) and close(O.lens_motor_target("lens5B", 55.618, 43.0)[1], 0.775, 0.02)
old = L.focus_motor_target("lens1E", 65.351)[1]
assert abs(old - 0.105) < 0.001 and abs(O.lens_motor_target("lens1E", 65.351, 71.5)[1] - old) > 0.05          # c=2 at 71.5 m is far from the old target
for k, v in O.STACKS.items():
    r = L.LENSES_1ID[k]
    assert (r["from_source_m"], r["tooth_um"], r["orientation"], r["zero_deg"], r["material"]) == (v["z_m"], v["tooth_um"], v["orientation"], v["zero_deg"], v["material"])
ok("focus sensitivity ~15 mm/mdeg; B-stack check; STACKS table equals blade.physics.lens")

# 6. delta(E) vs xraydb (if present)
try:
    import xraydb
    for E in (52.0, 65.351, 90.5):
        d = xraydb.xray_delta_beta("Si", 2.33, E * 1e3)[0]
        assert abs(O.delta(E) / d - 1) < 0.01, (E, O.delta(E), d)
    assert abs(O.delta(55.618, "Al") / xraydb.xray_delta_beta("Al", 2.70, 55618)[0] - 1) < 0.01
    for E in (45.0, 75.0):
        assert abs(O.mu_per_cm(E, "Al") / xraydb.material_mu("Al", E * 1e3, density=2.70) - 1) < 0.02
    ok("delta(E) and mu(E) within 1 % (delta) / 2 % (mu) of xraydb")
except ImportError:
    print("SKIP xraydb checks")

# 7. spot size vs energy: Nov-2024 series (FWHM um) within 1.6 um; brightness/regular ratios; bounds
for E, h, v in ((61.293, 30.5, 25.2), (62.3, 34.2, 31.5), (60.7, 29.4, 23.8), (60.3, 30.2, 23.5)):
    assert close(O.crl_spot_nov24_um(E, "h"), h, 1.6) and close(O.crl_spot_nov24_um(E, "v"), v, 1.6), E
assert close(O.spot_size_um(61.26, "brightness", "v") / O.spot_size_um(61.26, "regular", "v"), 0.738, 0.01)
assert O.spot_size_um(63.0, "regular", "v") > O.spot_size_um(61.26, "regular", "v")
lo, hi = O.source_fwhm_bounds_um("regular", "v")
assert 19 < lo < 20.5 and 28 < hi < 30 and O.source_fwhm_bounds_um("brightness", "h")[0] > 15
ok("CRL spot vs energy and mode comparison")

# 8. edge penumbra equals the vbl ray map; Fresnel scale equals the vbl's; logged slit-size ratio
w = None
try:
    import numpy as np
    from blade.vbl.world import VirtualBeamline
    from blade.vbl import imaging as im
    w = VirtualBeamline(seed=0)
except Exception as e:                                   # pragma: no cover
    print("SKIP vbl cross-check:", e)
if w is not None:
    zc = w.camera_view("gh1")[0]
    _, info = im.axis_profile(w, "h", "gh1", np.linspace(-1, 1, 401))
    S = w.sim["source"]["size_um_fwhm"]["h"] / O.FWHM_PER_SIGMA
    for e in info["edges"]:
        if e["id"] in w.z:
            assert close(e["penumbra_sigma_mm"] * 1e3, O.edge_penumbra_sigma_um(w.z[e["id"]], zc, S), 2e-4 * e["penumbra_sigma_mm"] * 1e3), e["id"]
            assert close(e["fresnel_scale_um"], O.fresnel_scale_um(w.energy_actual_keV(), w.z[e["id"]], zc), 0.05), (e["id"], e["fresnel_scale_um"])
    ok("penumbra and Fresnel scale agree with blade.vbl")
assert close(O.slit_image_size_mm(0.110, 60.8, O.P["z_sample_E_m"]) , 0.1257, 0.0005)
assert abs(O.slit_image_size_mm(0.110, 60.8, 69.49) - 0.120) < abs(O.slit_image_size_mm(0.110, 60.8, 71.5) - 0.120)
assert O.fringe_visibility(21.0, 12.0) < 1e-6 and O.fringe_visibility(0.34, 3.9) > 0.8         # WB-slit rim washed out, E-DS rim survives
ok("slit footprint (0.110 -> 0.12 mm tuple) and rim visibility")

# 9. hotspot / absorption / clipping
assert close(O.steering_shift_mm(-6.0, 25.0), -0.150, 1e-9) and close(O.steering_shift_mm(1.0, 69.49), 0.0695, 1e-3)
assert close(O.stack_transmission(61.0, "Al", 1000.0), math.exp(-0.0732), 0.002)
assert close(O.aperture_transmission(0.2, 0.45), 0.735, 0.01) and O.aperture_transmission(10.0, 0.45) < 0.05
ok("steering lever, stack absorption, aperture clip")

print("ALL PASS (%d groups)" % n)
