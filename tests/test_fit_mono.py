#!/usr/bin/env python3
"""blade.physics.mono_fit vs the numbers it was fitted to / checked against (1-ID logs 2022-2026): edge offsets, Th1 model, foil steps, edge widths,
Emon<->energy relation, drift/dump statistics, Th2 prior, E_scan timing.  No hardware, numpy + json only (xraydb optional for the step check).
Run: ~/miniconda3/envs/blade/bin/python -I tests/test_fit_mono.py   (non-zero exit on failure, < 30 s)"""
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from blade.physics import mono_fit as mf  # noqa: E402

J = json.loads((ROOT / "beamline_twins/1-ID/physics/fits/mono.json").read_text())
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


close = lambda a, b, tol: abs(a - b) <= tol

# 0) constants came from the JSON and the JSON has the provenance everywhere (no user-log document ids in the public file)
check("constants loaded from mono.json", mf.PARAMS_SOURCE.endswith("mono.json"), mf.PARAMS_SOURCE)
txt = (ROOT / "beamline_twins/1-ID/physics/fits/mono.json").read_text()
import re
# structural check (no names listed here on purpose): a log document id looks like <year>-<words>_<mon><yy>... ; only startup/tables ids may appear
_ids = set(re.findall(r"\b20\d\d-[A-Za-z][A-Za-z0-9_]+", txt))
_ok = ("startup", "mpe_", "lastlight", "AM_setup", "AMsetup", "Brightness", "techcomm", "alignment")
bad = [d for d in _ids if not any(k in d for k in _ok)]
check("mono.json has no user-log names / ids", not bad, str(bad))
D = J["data"]["escan_fits"]
check("43 unique E_scan fits tabulated", len(D) == 43 and all(r["prov"] for r in D))

# 1) edge offsets: statistics recomputed from the table; sampler reproduces them
off = np.array([r["off_eV"] for r in D])
check("E_scan offsets: mean -44 eV, sd 44 eV (n=43)", close(off.mean(), -43.6, 0.3) and close(off.std(ddof=1), 43.6, 0.5), "%.1f %.1f" % (off.mean(), off.std(ddof=1)))
re = np.array([r["off_eV"] for r in D if r["element"] == "Re" and r["date"] >= "2025-01-01"])
check("Re 2025-26: -42 eV, session sd 17.5 eV (0.39 mdeg), n=12", len(re) == 12 and close(re.mean(), -41.9, 0.3) and close(re.std(ddof=1), 17.5, 0.3))
tr = J["fits"]["edge_offset"]["Re_trend_2025_26"]
check("Re offset trend +2.6 +- 0.9 eV/month, consistent with the Th1-offset trend", close(tr["slope_eV_per_month"], 2.6, 0.2) and
      close(tr["slope_eV_per_month"], -J["th1_offset"]["trend_2025_26_mdeg_per_month"] * mf.dE_dth1_eV_per_mdeg(71.676), 2 * tr["slope_se"]),
      "%.2f vs th1-offset-predicted %.2f" % (tr["slope_eV_per_month"], -J["th1_offset"]["trend_2025_26_mdeg_per_month"] * mf.dE_dth1_eV_per_mdeg(71.676)))
rng = np.random.default_rng(7)
x = mf.sample_th1_err_mdeg(rng, "legacy", 20000)
check("th1_err sampler legacy: mean 1.2, sd 1.0 mdeg", close(x.mean(), 1.2, 0.03) and close(x.std(), 1.0, 0.03))
x = mf.sample_th1_err_mdeg(rng, "reset", 20000)
check("th1_err sampler reset: mean 0.19, sd 0.22 mdeg", close(x.mean(), 0.19, 0.01) and close(x.std(), 0.22, 0.01))
e_ang = mf.sample_edge_offset_eV(rng, 71.676, "legacy", "angle", 20000)
check("edge offset sampler (angle) at Re: -53 eV +- 45", close(e_ang.mean(), -53, 3) and close(e_ang.std(), 45, 3), "%.1f %.1f" % (e_ang.mean(), e_ang.std()))
e_ev = mf.sample_edge_offset_eV(rng, None, "legacy", "eV", 20000)
check("edge offset sampler (eV) mean -49, sd 23.5", close(e_ev.mean(), -48.7, 0.8) and close(e_ev.std(), 23.5, 0.8))
check("sensitivity 24/45/72 eV per mdeg at 52/71.7/90.5 keV", all(close(mf.dE_dth1_eV_per_mdeg(E), v, 1.0) for E, v in ((51.996, 24), (71.7, 45), (90.5, 72))))
mc = J["fits"]["edge_offset"]["model_comparison_2025_26"]
check("constant-eV vs constant-angle offset models not separable (rms 23.5 vs 30.2 eV)", mc["const_eV"]["rms_eV"] < mc["const_angle"]["rms_eV"] < 1.4 * mc["const_eV"]["rms_eV"])

# 2) Th1 offset history and the Bragg model
for E, th1 in ((51.81, 2.684), (71.15, 2.089), (90.52, 1.748)):
    check("Th1(%.2f keV) = theta_B + 0.4968 within 0.0004 deg" % E, close(mf.th1_deg(E, 0.4968), th1, 0.0004), "%.4f vs %.3f" % (mf.th1_deg(E, 0.4968), th1))
check("Th1(Hf readback 65.278 keV, Feb 2026) = 2.222 deg", close(mf.th1_deg(65.278, date="2026-02"), 2.222, 0.001))
check("Th1 offset history: 0.4944 (Jun22), 0.4873 (Jan25), 0.4863 (Feb26), re-referenced -0.333 after Jul 2026",
      [mf.th1_offset_deg(d) for d in ("2022-06", "2025-02", "2026-03", "2026-08")] == [0.4944, 0.4873, 0.4863, -0.3329])
r = J["th1_offset"]["reset_2026"]
check("Jul-2026 re-reference: -0.82 deg vs Feb 2026; first state 17.1 mdeg (775 eV) off", close(r["jump_vs_feb2026_deg"], -0.819, 0.002) and close(r["th1_first_state_vs_calibrated_mdeg"], 17.1, 0.1)
      and close(r["energy_error_of_first_state_eV"], 775, 3))
check("Th1/Th2 offsets moved together 2025->26 (-1.0 / -1.1 mdeg)", close(J["th1_offset"]["th1_change_2025_to_2026_mdeg"], -1.0, 0.05) and close(J["th1_offset"]["th2_change_2025_to_2026_mdeg"], -1.1, 0.05))

# 3) foil steps: logged values and consistency with xraydb Delta-mu * t_eff
for el, b, tol in (("Re", 1.425, 0.03), ("Au", 1.373, 0.02), ("Yb", 1.391, 0.01), ("Tb", 0.774, 0.005), ("Hf", 1.152, 0.01), ("Sm", 0.913, 0.001), ("Ir", 1.591, 0.001),
                   ("Ta", 0.967, 0.001), ("Ho", 0.828, 0.001), ("Pt", 1.439, 0.001), ("Bi", 1.245, 0.001), ("Tm", 0.750, 0.001)):
    check("foil b(%s) = %.3f" % (el, b), close(mf.foil_b(el), b, tol))
check("foil b for an unlogged element falls back to 1.15; dif = 0.6 b", mf.foil_b("Xx") == 1.15 and close(mf.foil_dif("Xx"), 0.69, 1e-9))
check("sim's Ho/Ta/Hf b (1.2/1.3/1.35) are far from the fits (0.83/0.97/1.15)", all(abs(a - b) > 0.1 for a, b in ((1.2, mf.foil_b("Ho")), (1.3, mf.foil_b("Ta")), (1.35, mf.foil_b("Hf")))))
u = J["fits"]["foils"]["ut_over_b"]
check("operator target ut equals fitted b to 1 % (8 logs, sd 2 %)", close(u["mean"], 0.993, 0.002) and u["sd"] < 0.03 and u["n"] == 8, str(u))
try:
    from blade.physics import core
    core.edge_keV("Re")
    dev = []
    for el, v in J["fits"]["foils"]["per_element"].items():
        if el == "Pr":
            continue
        nom = core.edge_keV(el)
        dmu = core.mu_per_cm(el, nom + 0.05) - core.mu_per_cm(el, nom - 0.05)
        dev.append(mf.foil_b_from_thickness(dmu, v["t_eff_mm"]) / mf.foil_b(el) - 1)
        assert 0.05 < v["t_eff_mm"] < 0.3, (el, v["t_eff_mm"])
    check("b = xraydb Delta-mu * t_eff reproduces every fitted b to <1 % (12 elements, t_eff 0.06-0.23 mm)", max(abs(d) for d in dev) < 0.01, "max %.4f" % max(abs(d) for d in dev))
except ImportError:
    print("SKIP: xraydb not installed (Delta-mu * t check)")

# 4) edge widths
LOG = {"Tb": 0.0335, "Yb": 0.0478, "Re": 0.0606, "Au": 0.0742, "Hf": 0.0492, "Sm": 0.0274, "Ir": 0.0617, "Ho": 0.0418, "Ta": 0.0513}   # medians of the logged fits (keV)
WELL = ("Tb", "Yb", "Hf", "Re", "Au")                                     # elements with n >= 2 logged scans
for model, tol_well, tol_all in (("voigt", 0.08, 0.13), ("theta", 0.10, 0.16)):
    rel = {el: abs(mf.edge_wid_keV(mf.foil_edge_keV(el), el, model) / w - 1) for el, w in LOG.items()}
    check("edge width model '%s': n>=2 elements within %d %%, all 9 within %d %%" % (model, round(tol_well * 100), round(tol_all * 100)),
          max(rel[e] for e in WELL) < tol_well and max(rel.values()) < tol_all, "worst well-measured %.3f, worst overall %.3f (%s)" % (max(rel[e] for e in WELL), max(rel.values()), max(rel, key=rel.get)))
rms = lambda m: math.sqrt(np.mean([(mf.edge_wid_keV(r["nominal_keV"], r["element"], m) * 1e3 - r["wid_keV"] * 1e3) ** 2 for r in D]))
check("edge width rms over 43 scans: voigt 3.7 eV < theta 4.1 eV", close(rms("voigt"), 3.73, 0.1) and close(rms("theta"), 4.13, 0.1), "%.2f %.2f" % (rms("voigt"), rms("theta")))
prof = J["fits"]["edge_width"]["profile_natural_width_scale"]
check("natural vs instrument width NOT separable: rms flat to 15 % while dtheta runs 16 -> 3 urad", max(p["rms_eV"] for p in prof[:6]) / min(p["rms_eV"] for p in prof[:6]) < 1.2
      and prof[0]["dtheta_urad"] > 15 and prof[5]["dtheta_urad"] < 4)
check("natural K width power law 0.4 % over the 13 elements", all(close(mf.PARAMS["natural_width_powerlaw"][0] * mf.foil_edge_keV(el) ** mf.PARAMS["natural_width_powerlaw"][1] / mf.PARAMS["core_width_K_eV"][el], 1, 0.01)
                                                                    for el in mf.PARAMS["core_width_K_eV"] if el in mf.PARAMS["edge_keV"]))

# 5) Emon <-> energy relation
pairs = J["fits"]["emon_inversion"]
check("Emon vs E_scan pos: bias +7.6 eV, sd 9.3 eV (n=42)", close(pairs["bias_eV"], 7.6, 0.1) and close(pairs["sd_eV"], 9.3, 0.1) and pairs["n"] == 42)
check("mu_t = b at E = pos + bias (Re)", close(mf.mu_t_emon(71.6235 + 0.00759, "Re", 71.6235), mf.foil_b("Re"), 1e-6))
E_back = mf.edge_pos_from_emon(71.640, mf.mu_t_emon(71.640, "Re", 71.625), "Re")
check("Emon inverse round-trips", E_back is not None and close(E_back, 71.625, 1e-6))
check("Emon inverse refuses saturated readings (mu_t=2.1)", mf.edge_pos_from_emon(71.600, 2.10, "Re") is None)
pos = mf.edge_pos_from_emon(71.660, 1.888, "Re")                         # Jun 2025: Emon 1.888 at 71.660; the scan 2 min later gave pos 71.6235
check("logged Emon 1.888 at 71.660 keV -> edge at 71.612 (E_scan: 71.6235; within the 9 eV sd)", close(pos, 71.6235, 0.02), "%.4f" % pos)
dmu = mf.mu_t_slope_per_mdeg(71.676, "Re") * 0.1                           # one 0.0001 deg step of Th1+Th2 (2026 log: mu_t 1.53 -> 1.459)
check("0.0001 deg step moves Re mu_t by 0.06 (logged 0.071)", close(dmu, 0.06, 0.012) and abs(0.071 - dmu) < 0.02, "%.3f" % dmu)
check("logged 2.7 eV from one Th2 tweak = coupling 0.3 x 0.2 mdeg", close(mf.th2_energy_shift_eV(71.676, 0.2), 2.7, 0.2))

# 6) drift / dump / heat load / timing
rng = np.random.default_rng(3)
d = mf.drift_eV(rng, 16.0, 20000)
check("fixed-E drift over 16 h: zero mean, sd 4.4 eV", close(d.mean(), 0, 0.15) and close(d.std(), 4.4, 0.2))
check("drift table: 22 pairs, rms 4.1 eV", J["fits"]["drift_fixed_energy"]["n_pairs"] == 22 and close(J["fits"]["drift_fixed_energy"]["rms_delta_eV"], 4.11, 0.02))
check("dump shift sd 9.3 eV (n=3)", close(mf.dump_shift_eV(rng, 20000).std(), 9.3, 0.3) and J["fits"]["dump_events"]["n"] == 3)
check("heat load: 3 K at 0.4x0.4 mm and 10 K at 0.8x0.7 mm within 0.3 K", close(mf.heat_load_dT_K(0.4, 0.4), 3.0, 0.3) and close(mf.heat_load_dT_K(0.8, 0.7), 10.0, 0.3))
check("thermal_relax is the ASSUMED tau=420 s exponential (pending model)", close(mf.thermal_relax(420.0), 1 - math.exp(-1), 1e-12) and mf.thermal_relax(-1) == 0.0)
check("E_scan duration by era 539.85 / 387.35 / 196.85 s", [mf.escan_duration_s(d) for d in ("2022-10", "2025-02", "2025-12")] == [539.85, 387.35, 196.85])

# 7) Th2 rocking prior
p = mf.th2_rocking_prior(71.7)
check("Darwin FWHM Si(111) at 71.7 keV = 3.84 urad = 0.22 mdeg", close(mf.darwin_fwhm_urad(71.7), 3.84, 0.05) and close(p["darwin_mdeg"], 0.22, 0.01))
check("Th2 prior ordering: Darwin < 2-crystal < log lower < sim 2 mdeg < log upper", p["darwin_mdeg"] < p["two_crystal_mdeg"] < p["log_lower_mdeg"] < p["sim_assumed_mdeg"] < p["log_upper_mdeg"])
check("flux fractions: 0.925 at 0.169 FWHM, 0.52 at 0.486 FWHM", close(mf.th2_flux_fraction(0.169, 1.0), 0.925, 0.005) and close(mf.th2_flux_fraction(0.486, 1.0), 0.52, 0.01))
try:
    from blade.physics import core
    th, _ = core.darwin_width_bragg(71.7)
    check("Darwin parametrisation matches xraydb (1 %)", close(mf.darwin_fwhm_urad(71.7) / th, 1.0, 0.01))
except ImportError:
    pass

if FAILS:
    print("FAILED:", FAILS)
    sys.exit(1)
print("mono_fit OK")
