"""HEM monochromator + energy-calibration models FITTED to the 1-ID logs (2022-2026).  numpy/math only; no hardware, no xraydb needed.

Constants are read from beamline_twins/1-ID/physics/fits/mono.json (override the path with $BLADE_MONO_FIT) and fall back to the embedded values
below, which are a copy of the same fit (so the module also works when the JSON is absent).  Everything is keV / eV / mdeg / deg unless a name says
otherwise.  Conventions:

  off_eV        HEM readback energy at which the foil K edge is found (E_scan 'pos') minus the tabulated edge; negative = readback low.
  th1_err_mdeg  (true Th1 offset) - (offset set in userTran3) = -off_eV / |dE/dTh1|; positive = readback low.

VALIDITY: 40-95 keV, Si(111) HEM, Th reference of Jan 2022 - Jun 2026 ('legacy' era); the Th zero was re-referenced in Jul 2026 (era 'reset').
What is fitted vs assumed vs pending is documented in beamline_twins/1-ID/physics/fits/mono.md.  Statistical models (samplers) take an explicit
numpy Generator so a simulator stays reproducible.
"""
import json
import math
import os
from pathlib import Path

import numpy as np

HC_KEV_A = 12.398419843320026
SI_A = 5.431020511
D111 = SI_A / math.sqrt(3.0)
_MDEG = math.radians(1e-3)

# ----------------------------------------------------------------------------------------------------------------------------------------------------
# embedded fallback = copy of fits/mono.json (kept deliberately small)
_FALLBACK = {
    "foils": {  # element: b (E_scan step), dif (pre-edge mu_t), wid (E_scan erf width, keV), t_eff (mm), n logs
        "Sm": (0.913, 0.569, 0.0274, 0.0726, 1), "Tb": (0.774, 0.486, 0.0335, 0.0675, 5), "Ho": (0.828, 0.512, 0.0418, 0.0752, 1),
        "Tm": (0.750, 0.481, 0.0458, 0.0703, 1), "Yb": (1.391, 0.840, 0.0478, 0.1894, 2), "Hf": (1.152, 0.678, 0.0492, 0.0903, 3),
        "Ta": (0.967, 0.619, 0.0513, 0.0635, 1), "Re": (1.425, 0.814, 0.0606, 0.0822, 18), "Ir": (1.591, 0.901, 0.0617, 0.0950, 1),
        "Pt": (1.439, 0.820, 0.0655, 0.0938, 1), "Au": (1.373, 0.786, 0.0742, 0.1054, 8), "Bi": (1.245, 0.672, 0.0816, 0.2311, 1),
        "Pr": (1.000, 0.600, None, None, 0)},
    "core_width_K_eV": {"Pr": 16.2, "Sm": 19.7, "Tb": 23.8, "Ho": 26.8, "Tm": 30.1, "Yb": 31.9, "Hf": 35.7, "Ta": 37.7, "Re": 42.1, "Ir": 46.8,
                        "Pt": 49.3, "Au": 52.0, "Bi": 63.4},
    "edge_keV": {"Pr": 41.991, "Sm": 46.834, "Tb": 51.996, "Ho": 55.618, "Tm": 59.390, "Yb": 61.332, "Hf": 65.351, "Ta": 67.416, "Re": 71.676,
                 "Ir": 76.111, "Pt": 78.395, "Au": 80.725, "Bi": 90.526},
    "natural_width_powerlaw": (0.0210987, 1.77829),            # Gamma_K[eV] = a * E[keV]^p (13 elements, 0.4 %)
    "dtheta_urad_M0": 22.815, "dtheta_urad_M1": 8.862,
    "emon_bias_eV": 7.59, "emon_sd_eV": 9.33,
    "th1_err_mdeg": {"legacy": (1.2, 1.0), "reset": (0.19, 0.22)},
    "offset_eV": {"legacy_2025_26": (-48.7, 23.5), "all": (-43.6, 43.6), "reset": (-5.8, 6.4)},
    "drift_sigma_eV_per_sqrt_h": 1.10, "dump_shift_sd_eV": 9.3, "heat_dT_K_per_mm2": 18.3,
    "th1_history": [("2022-06", 0.4944), ("2022-10", 0.4953), ("2022-12", 0.4963), ("2023-03", 0.4950), ("2025-01", 0.4873), ("2025-06", 0.4871),
                    ("2026-02", 0.4863), ("2026-07", -0.3329), ("2026-09", -0.3274)],
    "darwin_urad_x_keV": 275.2, "two_crystal_factor": 1.4,
    "escan_s": [("2022-01", 539.85), ("2024-09", 387.35), ("2025-07", 196.85)],
}


def _load():
    p = os.environ.get("BLADE_MONO_FIT")
    path = Path(p) if p else Path(__file__).resolve().parents[2] / "beamline_twins" / "1-ID" / "physics" / "fits" / "mono.json"
    P = {k: v for k, v in _FALLBACK.items()}
    src = "embedded fallback"
    try:
        J = json.loads(path.read_text())
        f = J["fits"]
        per = f["foils"]["per_element"]
        foils = dict(P["foils"])
        for el, v in per.items():
            old = foils.get(el, (None, None, None, None, 0))
            foils[el] = (v["b"], v["dif"], v.get("edge_wid_keV", old[2]), v.get("t_eff_mm"), v.get("n", 0))
        P["foils"] = foils
        P["core_width_K_eV"] = f["edge_width"]["natural_width_K_eV"]
        P["dtheta_urad_M0"] = f["edge_width"]["M0_single_term"]["dtheta_urad"]
        P["dtheta_urad_M1"] = f["edge_width"]["M1_natural_plus_theta"]["dtheta_urad"]
        P["emon_bias_eV"] = f["emon_inversion"]["bias_eV"]
        P["emon_sd_eV"] = f["emon_inversion"]["sd_eV"]
        P["drift_sigma_eV_per_sqrt_h"] = f["drift_fixed_energy"]["sigma_eV_per_sqrt_h"]
        P["dump_shift_sd_eV"] = f["dump_events"]["dpos_eV_sd"]
        P["heat_dT_K_per_mm2"] = f["heat_load"]["dT_K_per_mm2"]
        P["darwin_urad_x_keV"] = f["th2_rocking"]["darwin_theta_fwhm_urad_times_E_keV"]
        ts = f["truth_spread"]["th1_err_mdeg"]
        P["th1_err_mdeg"] = {"legacy": (ts["recommended"]["mean"], ts["recommended"]["sd"]),
                             "reset": (ts["post_reset_emon_2026_09_plus"]["mean"], ts["post_reset_emon_2026_09_plus"]["sd"])}
        eo = f["edge_offset"]
        P["offset_eV"] = {"legacy_2025_26": (eo["y2025_26_excl_Pt"]["eV"]["mean"], eo["y2025_26_excl_Pt"]["eV"]["sd"]),
                          "all": (eo["all"]["eV"]["mean"], eo["all"]["eV"]["sd"]),
                          "reset": (f["emon_offsets"]["post_reset_2026_09_plus"]["eV"]["mean"], f["emon_offsets"]["post_reset_2026_09_plus"]["eV"]["sd"])}
        P["offset_eV_const_model_2025_26"] = (eo["model_comparison_2025_26"]["const_eV"]["params"][0], eo["model_comparison_2025_26"]["const_eV"]["rms_eV"])
        hist = sorted((h["date"], h["th1_offset_deg"]) for h in J["th1_offset"]["table"])      # chronological; lookups use year-month
        P["th1_history"] = [(d[:7], v) for d, v in hist]
        P["escan_s"] = [("2022-01", 539.85), ("2024-09", 387.35), ("2025-07", 196.85)]
        src = str(path)
    except Exception:  # noqa: BLE001 - any problem -> embedded constants
        pass
    return P, src


PARAMS, PARAMS_SOURCE = _load()


# ---------------------------------------------------------------- Bragg geometry and Th1 offset
def bragg_deg(energy_keV):
    return math.degrees(math.asin(HC_KEV_A / (2.0 * D111 * energy_keV)))


def dE_dth1_eV_per_mdeg(energy_keV):
    """|dE/dTh1| [eV per mdeg] = E*cot(theta_B)*1 mdeg  (24 / 45 / 72 eV at 52 / 71.7 / 90.5 keV)."""
    return energy_keV * 1e3 / math.tan(math.radians(bragg_deg(energy_keV))) * _MDEG


def th1_offset_deg(date="2026-02"):
    """Th1 offset set in userTran3 (Th1 = theta_B + offset): step-wise history (fits/mono.json 'th1_offset'); 'YYYY-MM'.  Legacy reference 0.4944-0.4963
    (2022), 0.4950 (Mar 2023), 0.4873/0.4871/0.4863 (2025-26); NEW reference after Jul 2026: -0.333/-0.327 (Th zero re-referenced, see mono.md).
    Within 2025-26 the offset drifts -0.084 +- 0.03 mdeg/month (the Re readback moves +2.6 +- 0.85 eV/month in step)."""
    h = PARAMS["th1_history"]
    d = date[:7]
    val = h[0][1]
    for dd, v in h:
        if dd <= d:
            val = v
    return val


def th1_deg(energy_keV, offset_deg=None, date="2026-02"):
    """Th1 readback for an energy: theta_B(Si 111) + offset (validated to <0.0004 deg at 51.8/71.2/90.5 keV in 2023, with offset 0.4968)."""
    return bragg_deg(energy_keV) + (th1_offset_deg(date) if offset_deg is None else offset_deg)


def edge_offset_eV_from_th1_err(energy_keV, th1_err_mdeg):
    """Readback-minus-true energy at the foil edge for a Th1-offset error (positive th1_err = readback low)."""
    return -th1_err_mdeg * dE_dth1_eV_per_mdeg(energy_keV)


def th1_err_mdeg_from_edge_offset(energy_keV, off_eV):
    return -off_eV / dE_dth1_eV_per_mdeg(energy_keV)


# ---------------------------------------------------------------- startup 'truth spread'
def sample_th1_err_mdeg(rng, era="legacy", size=None):
    """Signed true-minus-set Th1 offset at the start of a session [mdeg].  era 'legacy' N(1.2, 1.0) (43 E_scans 2022-26, all elements; Re-only
    2025-26 sd is 0.39); 'reset' N(0.19, 0.22) (Emon, Sep-Nov 2026 after the re-referencing: operators calibrate to nominal).  The ASSUMED 0.5 mdeg
    of sim.json is below all of these."""
    m, s = PARAMS["th1_err_mdeg"][era]
    return rng.normal(m, s, size)


def sample_edge_offset_eV(rng, energy_keV=None, era="legacy", model="angle", size=None):
    """Readback offset of the calibration edge [eV].  model 'angle': Th1 error from sample_th1_err_mdeg times dE/dTh1(E) (needs energy_keV);
    model 'eV': constant-energy Gaussian (mean -48.7, sd 23.5 eV, 2025-26 E_scans).  The two models are statistically indistinguishable in the
    logs (rms 30.2 vs 23.5 eV, F-test p~0.12); 'angle' is the physical one (offset errors are angles)."""
    if model == "eV":
        m, s = PARAMS["offset_eV"]["legacy_2025_26" if era == "legacy" else era]
        return rng.normal(m, s, size)
    if energy_keV is None:
        raise ValueError("model='angle' needs energy_keV")
    return edge_offset_eV_from_th1_err(energy_keV, sample_th1_err_mdeg(rng, era, size))


def drift_eV(rng, dt_h, size=None):
    """In-session readback drift at fixed E_hem over dt_h hours (3-60 h): random walk, sigma = 1.10 eV/sqrt(h), zero mean (22 consecutive Emon pairs;
    rms 4.1 eV).  Slow trend of the legacy reference: +2.6 eV/month (Re, 2025-26)."""
    return rng.normal(0.0, PARAMS["drift_sigma_eV_per_sqrt_h"] * math.sqrt(dt_h), size)


def dump_shift_eV(rng, size=None):
    """Energy-readback shift caused by a beam dump: zero-mean, sd 9.3 eV (n=3 events: -5.7, +11.8, -2.2 eV; 2-12 eV, 3-7 % flux loss) -- WEAK."""
    return rng.normal(0.0, PARAMS["dump_shift_sd_eV"], size)


# ---------------------------------------------------------------- foil edge: step, width, Emon / E_scan relations
def foil(el):
    """dict(b, dif, wid_keV, t_eff_mm, n) for element el (Re, Au, Yb, Tb, Ho, Ta, Hf, Pr, Sm, Ir, Pt, Bi, Tm); n = number of logged E_scan fits
    (Pr: operator target only).  b = step of mu_t across the K edge = (mu_above - mu_below)[xraydb] * t_eff."""
    t = PARAMS["foils"][el]
    return {"b": t[0], "dif": t[1], "wid_keV": t[2], "t_eff_mm": t[3], "n": t[4]}


def foil_b(el, default=1.15):
    """E_scan step b of the foil; default = median over logged foils for an unknown element (spread 0.75-1.6)."""
    return PARAMS["foils"][el][0] if el in PARAMS["foils"] else default


def foil_dif(el):
    """Pre-edge mu_t of the E_scan fit: 0.60 * b for unknown elements (0.54-0.64 over 12 foils)."""
    return PARAMS["foils"][el][1] if el in PARAMS["foils"] else 0.60 * foil_b(el)


def foil_b_from_thickness(delta_mu_per_cm, t_mm):
    """b = Delta-mu * t (use blade.physics.core.mu_per_cm at edge +-0.05 keV for Delta-mu)."""
    return delta_mu_per_cm * t_mm / 10.0


def _natural_width_eV(energy_keV, element=None):
    cw = PARAMS["core_width_K_eV"]
    if element in cw:
        return cw[element]
    a, p = PARAMS["natural_width_powerlaw"]
    return a * energy_keV ** p


def _erfcx(a):
    return math.exp(a * a) * math.erfc(a) if a < 5 else (1 / (a * math.sqrt(math.pi))) * (1 - 1 / (2 * a * a) + 3 / (4 * a ** 4))


def _voigt_peak(sig, gam):
    if sig <= 1e-12:
        return 1.0 / (math.pi * gam)
    return _erfcx(gam / (sig * math.sqrt(2.0))) / (sig * math.sqrt(2.0 * math.pi))


def edge_wid_keV(energy_keV, element=None, model="voigt"):
    """E_scan erf width 'wid' [keV] at the foil edge energy.
    model 'theta' : wid = E*cot(theta_B)*22.8 urad  (1 parameter, rms 4.1 eV over 43 scans; the sim's 23 urad is the same law).
    model 'voigt' : natural K-hole Lorentzian (xraydb core width, power law E^1.78 if element unknown) x Gaussian E*cot(theta_B)*8.86 urad; wid =
                    1/(sqrt(pi) V(0)); rms 3.7 eV.  The split natural/instrument is NOT identifiable from the logs (see mono.md); both models describe the
                    42-91 keV data equally; extrapolate neither beyond 40-95 keV."""
    s = energy_keV * 1e3 / math.tan(math.radians(bragg_deg(energy_keV)))      # eV per rad
    if model == "theta":
        return s * PARAMS["dtheta_urad_M0"] * 1e-6 * 1e-3
    gam = _natural_width_eV(energy_keV, element)
    sig = s * PARAMS["dtheta_urad_M1"] * 1e-6
    return 1.0 / (math.sqrt(math.pi) * _voigt_peak(sig, gam / 2.0)) * 1e-3


def mu_t_escan(energy_keV, el, pos_keV, wid_keV=None):
    """E_scan model mu_t(E) = dif + b (1 + erf((E-pos)/wid)) / 2 (the beamline's E_scan.gpl form)."""
    f = foil(el)
    w = wid_keV if wid_keV else (f["wid_keV"] or edge_wid_keV(pos_keV, el))
    return f["dif"] + 0.5 * f["b"] * (1.0 + math.erf((energy_keV - pos_keV) / w))


def mu_t_emon(energy_keV, el, pos_keV, wid_keV=None):
    """What the Emon macro prints at HEM readback energy E when the foil edge sits at readback 'pos':  mu_t = b + (b/2) erf((E - pos - bias)/wid), bias
    7.6 eV (so mu_t = b, the operators' target 'ut', at E = pos + 7.6 eV; checked against 42 E_scan/Emon pairs: sd 9.3 eV).  Valid for |mu_t-b| < 0.4 b
    (i.e. within about +-0.5 wid of the edge); the Emon record has a different zero from E_scan's dif."""
    f = foil(el)
    w = wid_keV if wid_keV else (f["wid_keV"] or edge_wid_keV(pos_keV, el))
    return f["b"] + 0.5 * f["b"] * math.erf((energy_keV - pos_keV - PARAMS["emon_bias_eV"] * 1e-3) / w)


def _erfinv(y):
    x = 0.0
    for _ in range(80):
        x -= (math.erf(x) - y) / (2.0 / math.sqrt(math.pi) * math.exp(-x * x))
    return x


def edge_pos_from_emon(energy_keV, mu_t, el, wid_keV=None):
    """Inverse of mu_t_emon: readback energy of the edge (E_scan 'pos' equivalent) from one Emon reading; None outside the valid range."""
    f = foil(el)
    w = wid_keV if wid_keV else (f["wid_keV"] or edge_wid_keV(foil_edge_keV(el), el))
    y = (mu_t - f["b"]) / (0.5 * f["b"])
    if abs(y) > 0.8:
        return None
    return energy_keV - w * _erfinv(y) - PARAMS["emon_bias_eV"] * 1e-3


def foil_edge_keV(el):
    return PARAMS["edge_keV"][el]


def mu_t_slope_per_mdeg(energy_keV, el):
    """d mu_t / d(Th1 and Th2 moved together) per mdeg at the edge centre [1/mdeg]: b/(sqrt(pi) wid) * dE/dTh (0.59 per mdeg for Re; a 0.0001 deg
    step moves Re mu_t by 0.06, the 2026 log has -0.071)."""
    f = foil(el)
    w = f["wid_keV"] or edge_wid_keV(energy_keV, el)
    return f["b"] / (math.sqrt(math.pi) * w) * dE_dth1_eV_per_mdeg(energy_keV) * 1e-3


# ---------------------------------------------------------------- thermal (mostly PENDING)
def heat_load_dT_K(width_mm, height_mm):
    """First-crystal temperature rise [K] ~ 18.3 K/mm^2 x WB aperture (2 logged points: +3 K at 0.4x0.4, +10 K at 0.8x0.7; 200 mA)."""
    return PARAMS["heat_dT_K_per_mm2"] * width_mm * height_mm


def thermal_relax(t_s, tau_s=420.0, amp=1.0):
    """amp * (1 - exp(-t/tau)).  tau is ASSUMED (420 s): NO time series exists in the logs to fit it (see mono.md, pending model P1)."""
    return amp * (1.0 - math.exp(-max(t_s, 0.0) / tau_s))


# ---------------------------------------------------------------- Th2 rocking prior
def darwin_fwhm_urad(energy_keV):
    """Si(111) symmetric-Bragg Darwin width FWHM [urad] = 275.2/E[keV] (xraydb, 42-91 keV, <0.5 %); Laue of the same order."""
    return PARAMS["darwin_urad_x_keV"] / energy_keV


def th2_rocking_prior(energy_keV):
    """Th2 rocking FWHM bounds [mdeg]: physical two-crystal prior 1.4 x Darwin (0.31 mdeg at 71.7 keV) vs log-based, conditional range 0.6-6 mdeg; the
    sim assumes 2 mdeg.  NOT identifiable from logs (no Th2 scan exists)."""
    d = darwin_fwhm_urad(energy_keV) * 1e-6 * 180 / math.pi * 1e3
    return {"darwin_mdeg": d, "two_crystal_mdeg": PARAMS["two_crystal_factor"] * d, "log_lower_mdeg": 0.6, "log_upper_mdeg": 6.0, "sim_assumed_mdeg": 2.0}


def th2_flux_fraction(delta_mdeg, fwhm_mdeg):
    """Gaussian rocking curve I/Ipk = exp(-4 ln2 (d/FWHM)^2).  Logs: 0.925 (520->562 kHz) => d = 0.169 FWHM; 0.52 (cold start) => d = 0.486 FWHM."""
    return math.exp(-4.0 * math.log(2.0) * (delta_mdeg / fwhm_mdeg) ** 2)


def th2_energy_shift_eV(energy_keV, delta_mdeg, coupling=0.3):
    """Energy shift of the transmitted beam when Th2 is moved alone by delta [mdeg]: coupling * dE/dTh1.  coupling=0.3 is the sim value; the logs give
    +2.7 eV for one 'tweak up' (0.2 mdeg) at Re => consistent (one 0.0002 deg step)."""
    return coupling * dE_dth1_eV_per_mdeg(energy_keV) * delta_mdeg


# ---------------------------------------------------------------- procedure timing
def escan_duration_s(date):
    """Printed 'Estimated duration' of E_scan by era: 539.85 s (2022-03..2024-08), 387.35 s (2024-10..2025-06), 196.85 s (2025-07..2026)."""
    d = date[:7]
    val = PARAMS["escan_s"][0][1]
    for dd, v in PARAMS["escan_s"]:
        if dd <= d:
            val = v
    return val

