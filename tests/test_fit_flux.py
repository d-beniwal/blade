#!/usr/bin/env python3
"""Flux-chain fits (blade/physics/flux_fit.py + beamline_twins/1-ID/physics/fits/flux.json) vs the numbers logged at 1-ID.  No hardware.
Run: python -I tests/test_fit_flux.py   (xraydb is used only for cross-checks and is skipped when missing)"""
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from blade.physics import flux_fit as F  # noqa: E402

J = json.loads((ROOT / "beamline_twins/1-ID/physics/fits/flux.json").read_text())
PAR, DATA = J["params"], J["data"]


def ok(msg):
    print("PASS", msg)


close = lambda a, b, tol: abs(a - b) <= tol

# 1) JSON params == embedded fallback (module works without the file)
fb = F._FALLBACK
assert close(PAR["wb_sigma_mm"]["value"], fb["wb_sigma_mm"], 5e-4) and close(PAR["gain_exponent"]["value"], fb["gain_exponent"], 1e-9)
assert list(PAR["flux_rel_knots"]["value"]["E_keV"]) == list(fb["flux_E_keV"]) and np.allclose(PAR["flux_rel_knots"]["value"]["rel"], fb["flux_rel"], atol=0.006)
assert PAR["dark_kHz"]["value"] == fb["dark_kHz"] and close(PAR["fs_leak_aligned"]["value"], fb["fs_leak_aligned"], 1e-12)
ok("flux.json params match the embedded fallbacks")

# 2) WB slit -> flux: the three within-session ratios (model within 1.5 %), and the old 0.14 mm vs fitted 0.147 mm
for pair in DATA["wb_pairs"]:
    if pair["class_"].startswith("primary"):
        assert abs(pair["ratio_model_at_0p147"] / pair["ratio_obs"] - 1) < 0.015, pair
r1, r2 = F.wb_flux_ratio(0.5, 0.5), F.wb_flux_ratio(0.8, 0.7, 0.4, 0.4)
assert close(r1, 1.724, 0.02) and close(r2, 1.444, 0.03), (r1, r2)
assert close(F.wb_flux_factor(3.0, 3.0), 1.0, 1e-6) and F.wb_flux_factor(0.3, 0.3, cx=0.3) < 0.7 * F.wb_flux_factor(0.3, 0.3)
assert abs(F.wb_position_sensitivity(0.3, 0.3, "h", 0.0)) < 1e-3 and F.wb_position_sensitivity(0.3, 0.3, "h", 0.1) < 0
ok(f"WB slits: sigma {F.P['wb_sigma_mm']} mm gives x{r1:.3f} (0.3^2->0.5^2, logged 1.724) and x{r2:.3f} (0.4^2->0.8x0.7, logged 1.444)")

# 3) off-resonance steering scan reproduced (137-145 kHz, 23 points) within 0.6 kHz
pts = DATA["steering_scan"]["points"]
peak = 145.0
errs = [peak * F.steering_flux_factor(xp, yp) - k for xp, yp, k in pts]
assert max(abs(e) for e in errs) < 1.0, max(abs(e) for e in errs)
assert F.steering_flux_factor(15.6, -0.14) > 0.999 and F.steering_flux_factor(5, 0) < F.steering_flux_factor(15, 0)
ok(f"steering profile reproduces {len(pts)} logged B3 points, max error {max(abs(e) for e in errs):.2f} kHz")

# 4) IC: gain scaling, clip, dark
assert close(F.ic_gain_factor(100.0), 2 ** -F.P['gain_exponent'], 1e-9) and close(F.ic_gain_factor(2000.0, exponent=1.0) * 40, 1.0, 1e-9)
r = float(F.ic_rate_scaled(176.0, 5.0, 200.0, ic="icE1"))
assert 999.9 < r <= F.IC_CLIP_KHZ + 1e-9 and F.IC_CLIP_KHZ == 999.988            # 176 kHz at 50 nA/V -> 5 nA/V saturates the scaler
assert close(float(F.ic_rate_scaled(176.0, 50.0, 100.0)), F.ic_dark_kHz() + (176 - F.ic_dark_kHz()) * 0.5, 1e-9)
assert close(F.ic_dark_kHz("icE6"), 1.846, 1e-9) and close(F.ic_dark_kHz(None, 1.0, 0.02), 2.0, 1e-9) and close(F.ic_dark_kHz("icE4"), 0.928, 1e-9)
# the logged gain pairs give p = 0.93-0.995
ps = [g["p"] for g in DATA["gain_pairs"] if g["use"]]
assert len(ps) == 3 and all(0.9 < p < 1.01 for p in ps) and abs(np.mean(ps) - F.P["gain_exponent"]) < 1e-3
ok(f"IC: rate ~ gain^-{F.P['gain_exponent']} (pairs {ps}), clip 999988, per-IC dark floors")

# 5) physical IC model round trip + gas response sanity
f0 = 3e12
rate = float(F.ic_rate_from_flux(f0, 80.7, 50.0, "N2", 10.0, dark_kHz=1.0, clip=False))
assert close(float(F.ic_flux_from_rate(rate, 80.7, 50.0, "N2", 10.0, dark_kHz=1.0)) / f0, 1.0, 1e-9)
n2 = F.ic_gas_energy_response([52.0, 71.7, 90.0], "N2")
ar = F.ic_gas_energy_response([52.0, 71.7, 90.0], "Ar")
assert 0.9 < n2[0] < 1.1 and n2[1] == 1.0 and 0.8 < n2[2] < 1.4 and ar[0] > 1.5 and ar[2] < 0.8         # N2 ~flat, Ar falls steeply
ok(f"IC gas response: N2 {np.round(n2, 2).tolist()}, Ar {np.round(ar, 2).tolist()} (52/71.7/90 keV)")

# 6) attenuator wheels: printed tables (cm -> mm), lengths, and vs xraydb
tb = DATA["attenuator_tables"]
assert len(tb["attenB"]) == 11 and len(tb["attenC"]) == 8
assert F.attenuator_thickness_mm("attenB", 2) == 1.016 and F.attenuator_thickness_mm("attenB", 8) == 6.20 and F.attenuator_layers("attenB", 6) == ("Pb", 3.0)
assert F.attenuator_thickness_mm("attenC", 1) == 2.32 and F.attenuator_thickness_mm("attenC", 7) == 16.45
step = np.polyfit(range(8), [F.attenuator_thickness_mm("attenC", i) for i in range(8)], 1)[0]
assert close(step, 2.34, 0.03), step
T2 = float(F.attenuator_transmission("attenB", 2, 71.7))
assert close(T2, 0.402, 0.004) and close(T2 ** F.P["cu_t_eff_ratio"], 0.3906, 0.004)         # nominal 0.402, measured 0.3906 (+3.1 % thickness)
assert float(F.attenuator_transmission("attenC", 0, 80.0)) == 1.0
assert float(F.attenuator_transmission("attenB", 5, 85.0)) > 1e3 * float(F.attenuator_transmission("attenB", 5, 90.0))   # Pb K edge at 88.0 keV
try:
    from blade.physics import core
    for wh, pos, E in (("attenB", 2, 71.7), ("attenB", 4, 52.0), ("attenB", 8, 80.7), ("attenC", 3, 71.7), ("attenC", 1, 90.0), ("attenB", 6, 75.0), ("attenB", 5, 95.0), ("attenB", 5, 86.5)):
        mat, t = F.attenuator_layers(wh, pos)
        a, b = float(F.attenuator_transmission(wh, pos, E)), core.transmission(mat, t, E)
        assert abs(math.log(a) - math.log(b)) < 0.02 * max(1.0, -math.log(b)) + 0.01, (wh, pos, E, a, b)
    # Pb foil ut = 0.56 -> thickness at 86.5 keV from the embedded table is 0.248 mm (logged 252/441 kHz)
    mu = float(F._mu_rho("Pb", 86.5)) * 11.34
    assert close(0.56 / mu * 10, 0.248, 0.006)
    ok("attenuators: printed tables, B pos 2 -> T 0.402 nominal / 0.391 with the fitted thickness, embedded mu tables vs xraydb within 2 %")
except ImportError:
    print("SKIP: xraydb not installed (attenuator cross-check)")
    ok("attenuators: printed tables and B pos 2 transmission")

# 7) flux vs energy: knots, interpolation, clamping
c = F.flux_vs_energy_correction([41.99, 52.0, 61.33, 71.68, 80.73, 86.75, 90.53])
assert np.allclose(c, F.P["flux_rel"], rtol=1e-6) and close(float(F.flux_vs_energy_correction(71.7)), 1.0, 0.01)
assert close(float(F.flux_vs_energy_correction(95.0)), F.P["flux_rel"][-1], 1e-9) and 0.34 < float(F.flux_vs_energy_correction(88.0)) < 0.55
rows = DATA["ic_flux_rows"]
b1 = [x for x in rows["B1"] if 71.5 < x["E_keV"] < 71.8]
assert close(np.mean([x["rate_kHz_norm"] for x in b1]) , 174.1, 0.5)
ok("flux vs energy: 7 knots reproduced (relative to 71.7 keV): " + ", ".join(f"{v:.2f}" for v in c))

# 8) fast shutter, BPM, mu_t
assert F.fs_leakage_fraction() == 8e-5 and F.fs_leakage_fraction(3.0) == 8e-5 and 0.3 < F.fs_leakage_fraction(1.6) < 0.9 and F.fs_leakage_fraction(0.5) == 1.0
m, s = F.fs_window_y()
assert close(m, 1.69, 0.01) and 0.1 < s < 0.2 and [x["width"] for x in DATA["fs_measurements"]["Y_opening_mm"]] == [1.74, 1.8197, 1.5]
ha, va = F.bpm_angle_urad(10, -3)
assert close(ha, -11.5, 0.05) and close(va, -23.1, 0.05)
ha2, va2 = F.bpm_angle_urad(11, -3)
assert close(ha2, -10.4, 0.5) and close(va2, -22.8, 0.5)
assert close(F.mu_t_from_counts(1129240, 270944), 1.4641 - 0.0, 0.03)       # logged 1.46415
ok("fast shutter leakage/window, BPM-vs-steering (3 states), mu_t offset")

# 9) data tables are internally consistent
assert all(abs(x["rate_kHz_norm"] - x["rate_kHz_raw"] * (200 / x["I_mA"]) * (x["gain_nA_per_V"] / 50) * (F.wb_flux_factor(0.3, 0.3) / F.wb_flux_factor(x["wb_h"], x["wb_v"]))) < 0.006 * x["rate_kHz_norm"] for x in rows["B1"] + rows["B3"])
assert len(rows["B1"]) == 14 and len(rows["B3"]) == 18 and len(DATA["steering_scan"]["points"]) == 23
ok("ic_flux_rows normalisation reproducible (14 B1 + 18 B3 rows)")
print("ALL PASS")
