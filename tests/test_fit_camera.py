"""Camera / detector fit test (no hardware, no private KB data): blade.physics.camera_fit against its own fitted JSON
(beamline_twins/1-ID/physics/fits/camera.json) plus synthetic checks of every model.
Run: ~/miniconda3/envs/blade/bin/python -I tests/test_fit_camera.py   (numpy only, < 10 s)"""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from blade.physics import camera_fit as cf

J = json.loads((ROOT / "beamline_twins/1-ID/physics/fits/camera.json").read_text())
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(detail)) if detail != "" else ""))
    if not cond:
        FAILS.append(name)


close = lambda a, b, tol: abs(a - b) <= tol

# ---- 1. pixel size = sensor pitch / magnification; every logged value reproduced
for r in J["pixel_size"]["rows"]:
    model = r["sensor_pitch_um"] / r["magnification"]
    logged = [x for x in r["pixel_um_logged"] if isinstance(x, (int, float))]
    check("pixel %s: pitch/M %.4f vs logged %s" % (r["id"], model, logged), close(model, r["pixel_um_model"], 5e-4) and all(abs(model / x - 1) < 0.015 for x in logged))
check("pixel_um() lookups (PG1 1.172, PG1 7.5X 0.7813, GH1 0.69, NF 1.48, retiga2 0.987)",
      close(cf.pixel_um("pg1"), 1.172, 1e-9) and close(cf.pixel_um("pg1", 7.5), 0.78133, 1e-4) and close(cf.pixel_um("gh1"), 0.69, 1e-9)
      and close(cf.pixel_um("nf"), 1.48, 1e-9) and close(cf.pixel_um("retiga2"), 0.98667, 1e-4))
check("PG1 7.5X: theoretical vs fitted 0.78125 um/px within 0.02 %", abs(cf.pixel_um("pg1", 7.5) / 0.78125 - 1) < 2e-4)
check("GH1 FOV 1940 px x 0.69 um = 1.339 mm", close(cf.fov_mm(1940, 0.69), 1.3386, 1e-3))
check("phase-contrast rule (2025 log): 79.8 mm at 0.2385 A, 62.9 mm at 0.3024 A",
      close(cf.phase_contrast_distance_mm(0.2385, 0.69), 79.8, 0.1) and close(cf.phase_contrast_distance_mm(0.3024, 0.69), 62.9, 0.1))

# ---- 2. fallback constants identical to the JSON (clean clone without the file still works)
fb = cf._FALLBACK
check("fallback pin/texture/edges/dust/nf identical to JSON",
      fb["pin"] == J["pin"]["recommended"] and fb["texture"] == J["texture"]["recommended"] and fb["dust"] == J["dust"]["by_camera"]
      and fb["nf_pooled"] == J["nf_bby_vs_detz"]["pooled_2023_2025"] and fb["edges"]["gh1_all"] == J["slit_edges"]["gh1_all"] and fb["scint"] == J["scintillator"]["tables"]
      and fb["spreads"]["wedge_deg"] == J["startup_spreads"]["wedge_deg"]["values"])
check("module loaded the JSON (not the fallback)", cf.P["pin"] == J["pin"]["recommended"])

# ---- 3. tungsten pin: K edge, transmission, edge softness
muW = lambda E: cf.mu_per_cm("W", E)
check("W mu jumps across the K edge 69.525 keV (xraydb: 66 -> 200 /cm)", close(muW(62), 65.9, 1.0) and close(muW(71.676), 200.2, 1.0) and muW(71.676) / muW(69.4) > 1.9, (muW(62), muW(71.676)))
check("round W pin, 104.5 um chord at 71.676 keV transmits 0.123 (sim assumes 0.08 -> needs 126 um)",
      close(cf.pin_transmission(0.0, 52.25, 71.676), 0.123, 0.004) and close(math.log(0.08) / -(muW(71.676) * 1e-4), 126.1, 0.5))
check("pin chord geometry: centre = diameter, edge = 0", close(cf.pin_chord_um(0, 50), 100, 1e-9) and cf.pin_chord_um(50, 50) == 0.0)
pin = cf.pin_params("B")
check("pin B: top 104.5 um, half angle 7.8 deg; width grows 2 tan(half) per um depth", pin["top_width_um"] == 104.5 and pin["half_angle_deg"] == 7.8
      and close(cf.pin_width_um(1000.0), 104.5 + 2000 * math.tan(math.radians(7.8)), 1e-9))
A = cf.pin_params("A")
check("pin A (wide): ~180 um top, 14.8 deg; JSON groups A/B separated (n=8, n=3; half angles 14.8+-0.25 / 7.8+-0.06)",
      A["half_angle_deg"] == 14.8 and J["pin"]["group_A"]["half_angle_deg"]["n"] == 8 and J["pin"]["group_B"]["half_angle_deg"]["n"] == 3
      and close(J["pin"]["group_A"]["half_angle_deg"]["mean"], 14.77, 0.01) and close(J["pin"]["group_B"]["half_angle_deg"]["mean"], 7.79, 0.01))
# numeric chord profile vs the analytic 10-90 % formula (R=100 um, mu=200/cm)
R_, mu_um = 100.0, muW(71.676) * 1e-4
s = np.linspace(1e-3, 60, 600001)
T = np.exp(-mu_um * 2 * np.sqrt(R_ ** 2 - (R_ - s) ** 2))
w_num = s[np.argmax(T < 0.1)] - s[np.argmax(T < 0.9)]          # T falls with depth s into the silhouette
check("edge 10-90 %% of a round pin: formula %.2f um vs numeric %.2f um (<12 %%)" % (cf.pin_edge_width_1090_um(R_, 71.676), w_num), abs(cf.pin_edge_width_1090_um(R_, 71.676) / w_num - 1) < 0.12)
mA = J["pin"]["edge_1090_um_groupA"]
check("measured thick-pin edge width (median %.1f um, n=%d) lies inside the model range of 71.7 and 52 keV for R=80-140 um" % (mA["median"], mA["n"]),
      cf.pin_edge_width_1090_um(140, 71.676) < mA["median"] < cf.pin_edge_width_1090_um(80, 52))

# ---- 4. scintillator absorption
ab = lambda E: cf.scintillator_absorption("LuAG", 50, E)
check("LuAG Lu K edge 63.3 keV: absorption x>3 between 62 and 64 keV (50 um: %.3f -> %.3f)" % (ab(62), ab(64)), ab(64) / ab(62) > 3.0)
check("scintillator absorption falls with energy above the edge and rises with thickness", ab(90) < ab(71.676) < ab(64) and cf.scintillator_absorption("LuAG", 100, 71.676) > ab(71.676))
check("YAG absorbs far less than LuAG at 71.7 keV (Z)", cf.scintillator_absorption("YAG", 50, 71.676) < 0.4 * ab(71.676))
r = cf.relative_light("LuAG", 50, 71.676) / cf.relative_light("LuAG", 50, 52)
check("counts factor LuAG 50 um, 71.7 vs 52 keV (energy-integrating) = %.2f" % r, 2.0 < r < 3.2)
check("resolution model: monotonic in scintillator thickness; 20 um LuAG 5X ~2.7 um FWHM", cf.resolution_fwhm_um(0.69, 0.14, 50) > cf.resolution_fwhm_um(0.69, 0.14, 20) > cf.resolution_fwhm_um(0.69, 0.14, 5)
      and close(cf.resolution_fwhm_um(0.69, 0.14, 20), 2.73, 0.02))

# ---- 5. texture generator and the estimator used on the screenshots
est = [cf.fit_acf_length_um(cf.texture_field(1024, 0.69, seed=s), 0.69)[0] for s in range(3)]
true_l = cf.texture_params()["corr_len_um_bias_corrected"]
check("texture: estimator on synthetic fields (true %.0f um) gives %.1f um (bias -10..-40 %%, as documented)" % (true_l, np.mean(est)), 0.6 * true_l < np.mean(est) < 1.0 * true_l)
f = cf.texture_field(512, 0.69, seed=1)
check("texture rms = %.3f (target %.2f), mean 1" % (f.std(), cf.texture_params()["rms_rel"]), close(f.std(), cf.texture_params()["rms_rel"], 0.004) and close(f.mean(), 1.0, 1e-3))
psd = cf.texture_psd([1e-4, 0.1], 26.0)
check("texture PSD shape: flat below 1/(2 pi l), -3 slope above", psd[0] > 0.99 and close(np.log(cf.texture_psd(0.2, 26) / cf.texture_psd(0.1, 26)) / math.log(2), -3.0, 0.02))
tp = cf.texture_params()
check("texture recommendation within the measured IQR (16-50 um), slope -2.45", 16 <= tp["corr_len_um"] <= 50 and close(tp["psd_slope"], -2.45, 1e-9))
check("measured texture samples recorded (PG n=%d, GH1 n=%d)" % (J["texture"]["pg"]["n"], J["texture"]["gh1"]["n"]), J["texture"]["pg"]["n"] >= 30 and J["texture"]["gh1"]["n"] >= 20 and len(J["texture"]["frames"]) == J["texture"]["pg"]["n"] + J["texture"]["gh1"]["n"])

# ---- 6. edges, dust
x = np.linspace(-50, 50, 20001)
e = cf.edge_profile(x, 19.0)
check("edge_profile: 10-90 %% width equals the requested 19 um", close(x[np.argmax(e > 0.9)] - x[np.argmax(e > 0.1)], 19.0, 0.02))
check("slit edges: PG median 38 um (n=63), GH1 median 19 um (n=15), min 8-10 um", cf.slit_edge_width_um("pg1")["n"] == 63 and close(cf.slit_edge_width_um("pg1")["median"], 38.3, 0.05)
      and close(cf.slit_edge_width_um("gh1")["median"], 19.1, 0.05) and 8 <= cf.slit_edge_width_um("gh1")["min"] <= 10)
d = cf.dust_params("pg1")
check("dust: ~29 spots/mm^2, ~4 um equivalent diameter", 20 < d["density_per_mm2"] < 40 and 3 < d["diameter_um_median"] < 5)

# ---- 7. photon-transfer protocol on synthetic Poisson data
rng = np.random.default_rng(5)
K_true, rn_e = 3.0, 6.0                                       # e-/ADU, read noise [e-]
means, vars_ = [], []
for sig_e in np.geomspace(300, 60000, 12):                    # electrons
    a = (rng.poisson(sig_e, 200000) + rng.normal(0, rn_e, 200000)) / K_true
    b = (rng.poisson(sig_e, 200000) + rng.normal(0, rn_e, 200000)) / K_true
    means.append((a.mean() + b.mean()) / 2)
    vars_.append(np.var(a - b) / 2)
K, rn, _ = cf.ptc_fit(means, vars_)
check("PTC fit recovers gain %.2f e/ADU (true 3.0) and read noise %.1f e (true 6.0)" % (K, rn), close(K, K_true, 0.1) and close(rn, rn_e, 1.0))

# ---- 8. diffraction detector geometry and NF stage
for c_ in J["diffraction"]["ceo2_calibrations"]:
    pitch = cf.pixel_pitch_from_calibration(c_["beam_centre_px"], c_["beam_centre_mm"])
    check("calibration %s: pixel pitch %.3f / %.3f um = 172" % (c_["src"], pitch[0], pitch[1]), all(close(p, 172.0, 0.01) for p in pitch))
    check("   wavelength 12.39842/E = 0.20221 A at %.5f keV" % c_["energy_keV"], close(12.398419843 / c_["energy_keV"], 0.20221, 2e-5))
check("CeO2 (111) at 61.31457 keV, 800.169 mm, 172 um: 301.6 px; radius scales with L and falls with E",
      close(cf.ring_radius_px(61.31457, 3.1244, 800.169, 172), 301.56, 0.1)
      and close(cf.ring_radius_px(61.31457, 3.1244, 2 * 800.169, 172) / cf.ring_radius_px(61.31457, 3.1244, 800.169, 172), 2.0, 0.01)
      and cf.ring_radius_px(80, 3.1244, 800, 172) < cf.ring_radius_px(60, 3.1244, 800, 172))
check("distance change 800.169 -> 765.894 mm moves the (111) ring by %.1f px" % (cf.ring_radius_px(61.31457, 3.1244, 800.169, 172) - cf.ring_radius_px(61.31457, 3.1244, 765.894, 172)),
      close(cf.ring_radius_px(61.31457, 3.1244, 800.169, 172) - cf.ring_radius_px(61.31457, 3.1244, 765.894, 172), 12.9, 0.3))
sl = [v["slope_um_per_mm"] for k, v in J["nf_bby_vs_detz"]["series"].items() if k.startswith(("2023", "2025"))]
check("NF bbY per DetZ: sessions %s um/mm, pooled %.2f; bbY(9 mm) = %.4f mm" % (sl, J["nf_bby_vs_detz"]["pooled_2023_2025"]["slope_um_per_mm"], cf.nf_bby_mm(9)),
      min(sl) > 2.5 and max(sl) < 5.5 and close(cf.nf_bby_mm(9), 0.0354, 0.002))

# ---- 9. as-found alignment spreads
for name, lo, hi in (("wedge_deg", 0.0005, 0.02), ("omega_zero_error_deg", 0.003, 0.2), ("camera_or_axis_tilt_deg", 0.02, 0.8)):
    med, gsd, vals = cf.startup_spread(name)
    check("startup spread %s: median %.4f, geometric sd x%.1f, n=%d" % (name, med, gsd, len(vals)), lo < med < hi and gsd > 1.5 and len(vals) >= 5)
draw = [cf.sample_startup("wedge_deg", np.random.default_rng(i)) for i in range(200)]
check("sample_startup draws are signed, finite", all(np.isfinite(draw)) and min(draw) < 0 < max(draw))

# ---- 10. provenance hygiene of the JSON (no image ids, user logs cited only as 'user log <year>')
txt = json.dumps(J)
srcs = set()


def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "src":
                for s_ in (v if isinstance(v, list) else [v]):
                    srcs.add(s_)
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)


walk(J)
STARTUP_DOCS = {"2022-AMsetup_nov22", "2022-mpe_jun22_explog", "2023-startup_jan23_explog", "2024-AMsetup_nov24_explog", "2025-startup1id_jun2025_explog",
                "2025-startup_jan25_explog", "2026-mpe_jan26", "2026-techcomm_jun26_explog", "2024-mpe_jul24_explog"}      # documents of kind startup/tables only
bad = [s_ for s_ in srcs if not (re.fullmatch(r"user log (2022|2023|2024|2025|2026)", s_) or (s_.rpartition(":")[0] in STARTUP_DOCS and s_.rpartition(":")[2].isdigit()))]
check("every src is 'user log <year>' or a startup doc:line (%d distinct)" % len(srcs), not bad, bad[:3])
check("no sha256/hex image ids in the JSON", not re.search(r"\b[0-9a-f]{16,}\b", txt))

print("camera fit " + ("OK" if not FAILS else "FAILED: %s" % FAILS))
sys.exit(1 if FAILS else 0)
