"""Flux-chain models FITTED to the 1-ID logs (2022-2026): white-beam slits -> flux, ion-chamber (IC) response, attenuator wheels, flux vs energy, fast shutter,
steering/BPM.  numpy/math only; no hardware, no xraydb needed.

Constants are read from beamline_twins/1-ID/physics/fits/flux.json (override the path with $BLADE_FLUX_FIT) and fall back to the embedded values below
(a copy of the same fit), so the module also works when the JSON is absent.  Units: mm, keV, kHz (scaler rate), nA/V (preamp sensitivity), mA, urad.

WHAT IS FITTED vs ASSUMED vs PENDING is in beamline_twins/1-ID/physics/fits/flux.md; the data tables and provenance are in flux.json.  Short version:
  fitted   wb sigma (isotropic 0.147 mm, 3 within-session ratios), off-resonance steering profile, rate ~ 1/gain (exponent 0.955 +- 0.035), attenuator
           thickness tables (read from the control system's own printout), flux-vs-energy table, per-IC dark floors, BPM-angle/steering gain.
  assumed  IC gas and length (identifiable only as a product with the photon flux), 100 kHz/V converter gain, H/V split of sigma, FS timing.
VALIDITY: 40-95 keV; undulator on a resonant harmonic (n = 5..11) with the HEM tuned; WB aperture 0.2-0.8 mm; ring 50-200 mA (rate linear in current is an
assumption backed by one 114/200 mA cross-check, see flux.md); Cu/Pb attenuators 40-100 keV (xraydb tables embedded).
"""
import json
import math
import os
from pathlib import Path

import numpy as np

_erf = np.vectorize(math.erf, otypes=[float])

# ----------------------------------------------------------------------------------------------------------------------------------------------------
# embedded fallback = copy of fits/flux.json "params"
_FALLBACK = {
    "wb_sigma_mm": 0.147,                 # Gaussian beam sigma at the WB slits (z = 27 m), both axes (only the geometric mean is constrained)
    "wb_sigma_unc_mm": 0.009,
    "offres_sigma_urad": (31.9, 61.4),    # beam angular sigma (H, V) at undulator gap 30 mm (non-resonant, 'phantom-like'); NOT the resonant beam
    "offres_centre_urad": (15.6, -0.14),  # steering (Xp, Yp) total that centres that beam on the WB slits
    "gain_exponent": 0.955,               # rate ~ (50/gain)^p ; p = 1 expected, 0.955 +- 0.035 fitted
    "kHz_per_V": 100.0,                   # V-to-F converter (assumed: 10 V full scale = 1 MHz clip)
    "clip_kHz": 999.988,
    "dark_kHz": {"icE1": 0.835, "icE2": 0.875, "icE3": 0.474, "icE4": 0.928, "icE5": 0.218, "icE6": 1.846, "icE7": 0.321, "icE8": 1.824,
                 "icB3": 0.70, "scaler_ic1b": 0.596},
    "dark_default_kHz": 1.0,
    "attenB": {0: ("Cu", 0.0), 1: ("Cu", 0.1016), 2: ("Cu", 1.016), 3: ("Cu", 1.52), 4: ("Cu", 2.13), 5: ("Pb", 1.5), 6: ("Pb", 3.0), 7: ("Pb", 5.0),
               8: ("Cu", 6.20), 9: ("Cu", 2.0), 10: ("Cu", 9.0)},                                  # mm (log prints cm)
    "attenC": {0: ("Cu", 0.0), 1: ("Cu", 2.32), 2: ("Cu", 4.65), 3: ("Cu", 7.07), 4: ("Cu", 9.45), 5: ("Cu", 11.78), 6: ("Cu", 14.13), 7: ("Cu", 16.45)},
    "cu_t_eff_ratio": 1.031,              # measured/nominal Cu thickness from the ONE clean B-wheel transmission (n = 1; not applied by default)
    "flux_E_keV": (41.99, 52.0, 61.33, 71.68, 80.73, 86.75, 90.53),
    "flux_rel": (1.04, 2.20, 2.13, 1.00, 0.99, 0.55, 0.34),   # IC-rate factor relative to 71.7 keV, same WB / current / gain
    "flux_rel_unc": (0.15, 0.25, 0.15, 0.0, 0.10, 0.12, 0.10),
    "fs_leak_aligned": 8e-5,              # leakage / open-beam rate for an aligned fast shutter (upper estimate, floor-limited)
    "fs_x_edge_mm": 1.5,                  # B FS X where the closed blades first uncover the beam (Jun 2025); operating X = 3.0 mm
    "fs_window_y_mm": (1.69, 0.16),       # mean, sd of the measured vertical opening (n = 3)
    "bpm_gain": (0.88, 0.92),             # BPM angle (urad) per urad of steering total: H, V (n = 3)
    "mu_t_foilout_offset": (0.0195, 0.040),   # logged mu_t minus ln(Emon/Etr): mean, sd (n = 71)
    "z_wb_m": 27.0,
}
_CU_MU = np.array([[40, 4.8612], [42, 4.2407], [44, 3.7242], [46, 3.2909], [48, 2.9246], [50, 2.613], [52, 2.3461], [54, 2.1162], [56, 1.9172], [58, 1.744], [60, 1.5926], [62, 1.4596], [64, 1.3424], [66, 1.2386], [68, 1.1464], [70, 1.0642], [72, 0.9906], [74, 0.9246], [76, 0.8652], [78, 0.8115], [80, 0.763], [82, 0.7189], [84, 0.6789], [86, 0.6423], [88, 0.6089], [90, 0.5783], [92, 0.5503], [94, 0.5245], [96, 0.5007], [98, 0.4788], [100, 0.4585]], float)           # E keV, mu/rho cm2/g (xraydb)
_PB_LO = np.array([[40, 14.3583], [42, 12.6425], [44, 11.2006], [46, 9.9793], [48, 8.9371], [50, 8.042], [52, 7.2627], [54, 6.5859], [56, 5.995], [58, 5.4766], [60, 5.0197], [62, 4.6135], [64, 4.2526], [66, 3.9309], [68, 3.6429], [70, 3.3844], [72, 3.1515], [74, 2.9411], [76, 2.7504], [78, 2.5773], [80, 2.4195], [82, 2.275], [84, 2.1427], [86, 2.0214], [87.9, 1.9153]], float)         # below the Pb K edge (88.0045 keV)
_PB_HI = np.array([[88.1, 7.6617], [90, 7.2552], [92, 6.8594], [94, 6.4935], [96, 6.1547], [98, 5.8405], [100, 5.5488]], float)         # above the edge
_RHO = {"Cu": 8.96, "Pb": 11.34}
_GAS_E = np.array([30.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0, 95.0, 100.0], float)
_GAS = {"N2": [[0.30665, 0.22875, 0.2105, 0.19796, 0.18879, 0.18174, 0.17609, 0.1714, 0.1674, 0.16389, 0.16076, 0.15793, 0.15534, 0.15295], [0.10947, 0.05002, 0.03851, 0.03173, 0.02761, 0.02508, 0.02353, 0.02259, 0.02206, 0.0218, 0.02172, 0.02176, 0.02188, 0.02206]], "Ar": [[2.69647, 1.228, 0.9071, 0.70122, 0.56292, 0.46642, 0.39687, 0.34535, 0.30626, 0.27598, 0.25208, 0.23289, 0.21724, 0.2043], [2.41014, 0.9998, 0.69717, 0.50561, 0.3789, 0.29201, 0.23059, 0.18607, 0.15311, 0.12823, 0.10915, 0.09432, 0.08262, 0.07331]], "He": [[0.18385, 0.17631, 0.17318, 0.1703, 0.16763, 0.16512, 0.16273, 0.16046, 0.15828, 0.15619, 0.15418, 0.15225, 0.15039, 0.1486], [0.00979, 0.01172, 0.01268, 0.01361, 0.01449, 0.01532, 0.0161, 0.01684, 0.01753, 0.01818, 0.01879, 0.01936, 0.0199, 0.02041]]}                              # mu_tot, mu_en (cm2/g): photo + incoherent*KN energy transfer (approximate)
_GAS_RHO = {"N2": 1.165e-3, "Ar": 1.66e-3, "He": 1.66e-4}      # g/cm3 at 1 atm, 20 C


def _load():
    p = Path(os.environ.get("BLADE_FLUX_FIT", Path(__file__).resolve().parents[2] / "beamline_twins" / "1-ID" / "physics" / "fits" / "flux.json"))
    try:
        d = json.loads(p.read_text())["params"]
    except (OSError, ValueError, KeyError):
        return dict(_FALLBACK)
    out = dict(_FALLBACK)
    for k in ("wb_sigma_mm", "gain_exponent", "kHz_per_V", "clip_kHz", "cu_t_eff_ratio", "fs_leak_aligned", "fs_x_edge_mm"):
        if isinstance(d.get(k), dict) and "value" in d[k]:
            out[k] = d[k]["value"]
    return out


P = _load()


# ---------------------------------------------------------------------------------------------------------------------------------- WB slits -> flux
def _frac(width, centre, beam_centre, sigma):
    """Fraction of a 1-D Gaussian (sigma) inside an opening of `width` centred at `centre` (beam centre at `beam_centre`)."""
    d = np.asarray(centre, float) - np.asarray(beam_centre, float)
    w = np.asarray(width, float)
    s = math.sqrt(2.0) * sigma
    return 0.5 * (_erf((w / 2.0 - d) / s) + _erf((w / 2.0 + d) / s))


def wb_flux_factor(h, v, cx=0.0, cy=0.0, x0=0.0, y0=0.0, sigma_h=None, sigma_v=None):
    """Fraction of the (resonant-undulator) beam passing a WB aperture h x v mm centred at (cx, cy) when the beam centre at the slits is (x0, y0).
    Gaussian beam, sigma_h = sigma_v = P['wb_sigma_mm'] (0.147 +- 0.009 mm) fitted on three within-session flux ratios; H and V are NOT separately
    identifiable (every logged change scaled both).  The flux through any slit is this factor times the un-slitted flux; ratios of it reproduce
    0.3^2 -> 0.5^2 (x1.73), 0.4^2 -> 0.8x0.7 (x1.43).  Valid 0.2-0.8 mm apertures; no heat-load loss is visible up to 0.8x0.7 after a Th2 re-peak."""
    sh = P["wb_sigma_mm"] if sigma_h is None else sigma_h
    sv = P["wb_sigma_mm"] if sigma_v is None else sigma_v
    return _frac(h, cx, x0, sh) * _frac(v, cy, y0, sv)


def wb_flux_ratio(h2, v2, h1=0.3, v1=0.3, **kw):
    """Flux(h2 x v2) / Flux(h1 x v1), both centred on the beam."""
    return float(wb_flux_factor(h2, v2, **kw) / wb_flux_factor(h1, v1, **kw))


def wb_position_sensitivity(h, v, axis="h", dx=0.0, sigma=None):
    """d ln(flux) / d(slit-centre offset) in 1/mm at offset dx from the beam centre (negative of the beam-motion sensitivity); 0 at the peak."""
    s = P["wb_sigma_mm"] if sigma is None else sigma
    w = h if axis == "h" else v
    f = lambda d: float(_frac(w, d, 0.0, s))
    e = 1e-4
    return (math.log(f(dx + e)) - math.log(f(dx - e))) / (2 * e)


def steering_flux_factor(xp, yp, h=0.25, v=0.25, z_m=None):
    """Relative flux (1 = peak) vs total steering (Xp, Yp urad) through a WB slit h x v, for the OFF-RESONANCE beam (undulator gap 30 mm, 71 keV mono) logged
    in the steering scans of Jun 2026: Gaussian in angle with sigma 31.9 (H) / 61.4 (V) urad, centred at Xp = 15.6, Yp = -0.14 urad.  Not valid for a
    resonant harmonic (sigma ~5 urad there, see wb_flux_factor)."""
    z = P["z_wb_m"] if z_m is None else z_m
    (sx, sy), (x0, y0) = P["offres_sigma_urad"], P["offres_centre_urad"]
    gx = _frac(h, 0.0, (np.asarray(xp, float) - x0) * z * 1e-3, sx * z * 1e-3)
    gy = _frac(v, 0.0, (np.asarray(yp, float) - y0) * z * 1e-3, sy * z * 1e-3)
    ref = _frac(h, 0.0, 0.0, sx * z * 1e-3) * _frac(v, 0.0, 0.0, sy * z * 1e-3)
    return gx * gy / ref


# ---------------------------------------------------------------------------------------------------------------------------------- ion chambers
IC_CLIP_KHZ = P["clip_kHz"]


def ic_gain_factor(gain_nA_per_V, ref_nA_per_V=50.0, exponent=None):
    """Rate scaling with the preamp sensitivity setting: rate ~ (ref/gain)^p.  Physically p = 1 (V = I / sensitivity, rate = 100 kHz/V * V).
    Fitted p = 0.955 +- 0.035 from three gain pairs (see flux.md); the default here is the fitted value."""
    p = P["gain_exponent"] if exponent is None else exponent
    return (ref_nA_per_V / np.asarray(gain_nA_per_V, float)) ** p


def ic_dark_kHz(ic=None, gain_nA_per_V=None, input_offset_nA=None):
    """Dark (beam-off) rate of a channel.  Measured per-channel floors (PSS shutter closed): icE1 0.835 ... icE8 1.82 kHz.  They do NOT scale with the
    sensitivity setting; they follow the preamp input-offset current: dark ~ (kHz/V) * I_offset / sensitivity (logged offsets 0.01-0.1 V, 0.5-2 kHz).
    Give input_offset_nA and gain_nA_per_V to use that relation instead of the table (assumed 100 kHz/V; observed ratio 0.2-0.9 of it)."""
    if input_offset_nA is not None and gain_nA_per_V is not None:
        return P["kHz_per_V"] * input_offset_nA / gain_nA_per_V
    return P["dark_kHz"].get(ic, P["dark_default_kHz"])


def ic_rate_scaled(rate_ref_kHz, gain_nA_per_V=50.0, I_mA=200.0, ic=None, ref_gain=50.0, ref_I_mA=200.0, dark_kHz=None, clip=True):
    """Re-scale an IC reading known at (ref_gain, ref_I) to another gain / ring current: dark + (rate - dark) * gain factor * current ratio, clipped at the
    scaler limit.  Rate is linear in ring current (assumption; 114 vs 200 mA cross-check agrees to 2 %)."""
    d = ic_dark_kHz(ic) if dark_kHz is None else dark_kHz
    r = d + (np.asarray(rate_ref_kHz, float) - d) * ic_gain_factor(gain_nA_per_V, ref_gain) * (I_mA / ref_I_mA)
    return np.minimum(r, IC_CLIP_KHZ) if clip else r


def _interp_ll(E, x, y):
    return np.exp(np.interp(np.log(E), np.log(x), np.log(y)))


def gas_signal_per_photon(E_keV, gas="N2", length_cm=10.0):
    """IC current per incident photon, in units of electrons: (E/W) * (mu_en/mu) * (1 - exp(-mu rho L)); W = 34.8 (N2) / 26.4 (Ar) / 41.3 (He) eV.
    mu_en is approximate (photo + incoherent x Klein-Nishina energy transfer; no fluorescence escape).  GAS AND LENGTH ARE NOT IN THE LOGS: assumed."""
    W = {"N2": 34.8, "Ar": 26.4, "He": 41.3}[gas]
    mt = np.exp(np.interp(np.log(E_keV), np.log(_GAS_E), np.log(_GAS[gas][0])))
    me = np.exp(np.interp(np.log(E_keV), np.log(_GAS_E), np.log(_GAS[gas][1])))
    mu = mt * _GAS_RHO[gas]
    return (np.asarray(E_keV, float) * 1e3 / W) * (me / mt) * (1.0 - np.exp(-mu * length_cm))


def ic_gas_energy_response(E_keV, gas="N2", length_cm=10.0, ref_keV=71.7):
    """Relative IC signal per photon vs energy: nearly flat (+-10 %) for N2 over 50-80 keV; falls as ~E^-1.8 for Ar.  Photon-flux trend and gas response are
    degenerate in the logs, so use it only for what-if studies."""
    return gas_signal_per_photon(E_keV, gas, length_cm) / gas_signal_per_photon(ref_keV, gas, length_cm)


def ic_rate_from_flux(flux_ph_s, E_keV, gain_nA_per_V=50.0, gas="N2", length_cm=10.0, dark_kHz=0.0, clip=True):
    """Physical IC model: I = flux * e * gas_signal_per_photon ; rate = kHz_per_V * I / sensitivity + dark.  The absolute scale (gas, length, 100 kHz/V) is
    ASSUMED: only the product (gas length x converter gain) is constrained by the logs, via ic_flux_from_rate's use with a known flux (none logged)."""
    I_nA = np.asarray(flux_ph_s, float) * 1.602176634e-19 * gas_signal_per_photon(E_keV, gas, length_cm) * 1e9
    r = P["kHz_per_V"] * (I_nA / np.asarray(gain_nA_per_V, float)) + dark_kHz
    return np.minimum(r, IC_CLIP_KHZ) if clip else r


def ic_flux_from_rate(rate_kHz, E_keV, gain_nA_per_V=50.0, gas="N2", length_cm=10.0, dark_kHz=0.0):
    """Inverse of ic_rate_from_flux (photons/s)."""
    I_nA = (np.asarray(rate_kHz, float) - dark_kHz) / P["kHz_per_V"] * np.asarray(gain_nA_per_V, float)
    return I_nA * 1e-9 / (1.602176634e-19 * gas_signal_per_photon(E_keV, gas, length_cm))


# ---------------------------------------------------------------------------------------------------------------------------------- attenuators
def attenuator_layers(wheel, pos):
    """(material, thickness mm) of attenuator wheel 'attenB' (11 positions, Cu and Pb) or 'attenC' (8 positions, Cu) at integer position pos.
    Read from the wheels' own printouts (attenB.about / attenC.about) and the plan log lines 'B attenuator set to position 2, 0.1016 cm of Cu'.
    UNITS: the control system prints cm; this returns mm."""
    t = P[wheel]
    return t[int(pos)]


def attenuator_thickness_mm(wheel, pos):
    return attenuator_layers(wheel, pos)[1]


def _mu_rho(material, E_keV):
    E = np.asarray(E_keV, float)
    if material == "Cu":
        return np.exp(np.interp(np.log(E), np.log(_CU_MU[:, 0]), np.log(_CU_MU[:, 1])))
    lo, hi = _PB_LO, _PB_HI
    below = np.exp(np.interp(np.log(E), np.log(lo[:, 0]), np.log(lo[:, 1])))
    above = np.exp(np.interp(np.log(E), np.log(hi[:, 0]), np.log(hi[:, 1])))
    return np.where(E < 88.0045, below, above)


def attenuator_transmission(wheel, pos, E_keV, cu_scale=1.0):
    """Beer-Lambert transmission of one wheel position (embedded xraydb mu tables, 40-100 keV, within 0.5 % of blade.physics.core.transmission).
    cu_scale multiplies the Cu thickness (measured/nominal = 1.031 +- ~0.02 from one B-wheel transmission; default 1 = nominal)."""
    mat, t = attenuator_layers(wheel, pos)
    if t == 0.0:
        return 1.0 + 0.0 * np.asarray(E_keV, float)
    scale = cu_scale if mat == "Cu" else 1.0
    return np.exp(-_mu_rho(mat, E_keV) * _RHO[mat] * t * scale / 10.0)


# ---------------------------------------------------------------------------------------------------------------------------------- flux vs energy
def flux_vs_energy_correction(E_keV):
    """Multiplicative correction to an IC rate that is pinned at the 71.7 keV reference (176 kHz at WB 0.3x0.3, 200 mA, 50 nA/V), from logged rates at
    7 energies (log-linear interpolation of flux_rel).  Includes IC gas response AND undulator/mono photon flux (inseparable).  Anchored on IC_B1 at
    52-80.7 keV and IC_B3 (2026 series) at 42 and 86-91 keV; uncertainty in flux.json 'flux_rel_unc' (10-25 %).  Valid 42-90.5 keV only; clamped outside.
    NOTE the 42 keV point (n=5 at the minimum gap) and the 52 keV point (n=5) are not on one smooth curve with the n=7 points: operator harmonic/gap
    choice matters (see undulator model)."""
    E = np.asarray(E_keV, float)
    x = np.array(P["flux_E_keV"])
    y = np.log(np.array(P["flux_rel"]))
    return np.exp(np.interp(E, x, y))


# ---------------------------------------------------------------------------------------------------------------------------------- fast shutter
def fs_leakage_fraction(x_mm=None, beam_w_mm=0.44):
    """Leakage / open-beam rate of a CLOSED fast shutter.  Aligned (x_mm=None or >= edge + beam width): 8e-5 (IC6-E 1940 vs 1880 counts with the PSS
    shutter closed; open-beam IC6-E 7.7e5): floor-limited upper estimate.  When the closed blades' X (B FS, Jun 2025: first signal at X = 1.5 mm, operated
    at 3.0 mm) sits inside the beam, the uncovered fraction rises linearly over the beam width at the shutter (0.3 mm WB at 39.6 m -> 0.44 mm; assumed)."""
    base = P["fs_leak_aligned"]
    if x_mm is None:
        return base
    frac = float(np.clip((P["fs_x_edge_mm"] + beam_w_mm - float(x_mm)) / beam_w_mm, 0.0, 1.0))
    return max(base, frac)


def fs_window_y(rng=None):
    """Vertical FS opening in mm: (mean, sd) = (1.69, 0.16) from three camera measurements (1.50, 1.74, 1.82); pass a numpy Generator to sample."""
    m, s = P["fs_window_y_mm"]
    return (m, s) if rng is None else float(rng.normal(m, s))


# ---------------------------------------------------------------------------------------------------------------------------------- steering / BPM
def bpm_angle_urad(xp_total, yp_total, ha0=-7.1, va0=-18.5, xp0=15.0, yp0=2.0):
    """BPM angle readback (HA, VA, urad) vs the steering totals: HA = ha0 + 0.88 (Xp - xp0), VA = va0 + 0.92 (Yp - yp0).  Three logged states (Jul 2026,
    steering totals (15, 2) -> (10, -3) -> (11, -3)) agree to 0.4 urad; the offsets (ha0, va0) drift between sessions (-9.6/-25.1 in Sep 2026)."""
    g = P["bpm_gain"]
    return ha0 + g[0] * (np.asarray(xp_total, float) - xp0), va0 + g[1] * (np.asarray(yp_total, float) - yp0)


def mu_t_from_counts(emon, etr, offset=None):
    """Logged 'mu_t' of the energy-calibration macro: ln(Emon/Etr) + offset, offset = +0.0195 +- 0.040 (mean +- sd of the foil-out ratio over 71 logged rows)."""
    return math.log(emon / etr) + (P["mu_t_foilout_offset"][0] if offset is None else offset)
