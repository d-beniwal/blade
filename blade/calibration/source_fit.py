"""Fitted SOURCE models (undulator + ring) for the 1-ID virtual beamline. Pure functions (stdlib/numpy-free math + blade.physics.undulator).

Constants come from beamline_twins/1-ID/physics/fits/source.json (written by the fit; see source.md) with the same numbers embedded as DEFAULTS so the
module works without the file. Every function states its validity range; outside it the result is an extrapolation.

What is FITTED (88 logged gap/energy rows, 16 (E, n) clusters, PMU 2024-2026): the PMU gap <-> energy relation at harmonics 5, 7, 9, 11, gaps 8.5-11.3 mm,
energies 42-100 keV; the SCU18 current <-> K relation (180-825 A). What is ASSUMED: ring energy (6 GeV PMU; 7 GeV/6 GeV SCU), the gap-scan width (one
number), flux ~ ring current (untested). PENDING: harmonic flux exponent (one ratio), hysteresis, steering-gap coupling, source size.
"""
import json
import math
from pathlib import Path

from blade.physics import undulator as _u

_JSON = Path(__file__).resolve().parents[2] / "beamline_twins" / "1-ID" / "physics" / "fits" / "source.json"

DEFAULTS = {
    "ring_GeV": 6.0,
    "period_mm": 21.0,
    "coef": (2.6702, -3.2966, 0.0),                    # (a, b, c): B0[T] = a exp(b g/lam + c (g/lam)^2); lam = 21 mm
    "scu_period_mm": 18.0,
    "scu_k": (0.4444, 0.0029144, -6.2246e-07),         # K(I) = k0 + k1 I + k2 I^2, I in A
    "gap_limits": [("2024-11-14", 8.82), ("2025-01-27", 8.75), ("2025-07-01", 8.80), ("2026-06-01", 8.5)],
    "rel_fwhm": 0.0098,                                # ASSUMED, n-independent (one logged width at n=7)
    "wander_within_mm": 0.0009, "wander_between_mm": 0.0092,
    "flux_exponent": 0.74,                             # ONE ratio (5th/7th at ~61 keV); PENDING
    "steer_mm_per_urad_at_25m": 0.025,
}


def _load():
    c = dict(DEFAULTS)
    try:
        j = json.loads(_JSON.read_text())
        p = j["pmu"]
        c["ring_GeV"] = p["ring_GeV"]["value"]
        c["period_mm"] = p["period_mm"]["value"]
        c["coef"] = (p["coef_a"]["value"], p["coef_b"]["value"], p["coef_c"]["value"])
        s = j["scu"]
        c["scu_k"] = (s["k0"]["value"], s["k1"]["value"], s["k2"]["value"])
        c["gap_limits"] = [(g["from"], g["limit_mm"]) for g in j["gap_limits"] if g.get("use")]
        c["rel_fwhm"] = j["gap_scan"]["rel_fwhm"]
        c["wander_within_mm"] = j["wander"]["within_session_sd_mm"]
        c["wander_between_mm"] = j["wander"]["between_session_pooled_sd_mm"]
        c["flux_exponent"] = j["flux"]["exponent_fit_single_point"]
    except (OSError, KeyError, ValueError):
        pass
    return c


CONST = _load()


# ------------------------------------------------------------------ PMU gap <-> energy <-> harmonic
def k_pmu(gap_mm):
    """Deflection parameter K of the PMU at this gap. Fitted for 8.5-11.3 mm (extrapolation outside)."""
    return _u.k_from_gap(gap_mm, CONST["period_mm"], CONST["coef"])


def energy_pmu_keV(gap_mm, n):
    """Peak energy [keV] of harmonic n at this gap. Residual vs 88 logged points: 0.12 % rms (0.31 % max), i.e. 0.01 mm in gap. Valid n=5-11, gap 8.5-11.3 mm."""
    return _u.harmonic_energy_keV(gap_mm, n, CONST["period_mm"], CONST["ring_GeV"], CONST["coef"])


def gap_pmu_mm(energy_keV, n, lo=5.0, hi=60.0):
    """Gap [mm] that puts harmonic n at energy_keV (bisection; ValueError if unreachable). Accuracy ~0.01 mm for 42-100 keV with the harmonic the operators use."""
    return _u.gap_for_energy_mm(energy_keV, n, CONST["period_mm"], CONST["ring_GeV"], CONST["coef"], lo=lo, hi=hi)


def gap_limit_mm(date="2026-10-28"):
    """Minimum allowed gap in force on an ISO date (YYYY-MM-DD). Piecewise from the logs (8.82 -> 8.75 -> 8.80 -> 8.5); before 2024-11 the first value is used."""
    lim = CONST["gap_limits"][0][1]
    for start, val in CONST["gap_limits"]:
        if date >= start:
            lim = val
    return lim


def candidate_harmonics(energy_keV, gap_min, gap_max=25.0, nmax=19):
    """[(n, gap_mm)] odd harmonics that can deliver energy_keV with gap_min <= gap <= gap_max, ascending n."""
    out = []
    for n in range(3, nmax + 1, 2):
        try:
            g = gap_pmu_mm(energy_keV, n)
        except ValueError:
            continue
        if gap_min <= g <= gap_max:
            out.append((n, g))
    return out


def select_harmonic(energy_keV, gap_min=None, date="2026-10-28"):
    """Operators' rule: the highest odd n whose gap is still >= the gap limit (this is also the maximum-flux choice: Q_n grows with n at fixed energy).
    Returns (n, gap_mm) or None. Reproduces 15 of 16 logged energies with the date-dependent limit (exception 81.26 keV; 78.395 keV in Jul 2026 is a possible second)."""
    if gap_min is None:
        gap_min = gap_limit_mm(date)
    c = candidate_harmonics(energy_keV, gap_min)
    return c[-1] if c else None


def harmonic_amplitude_fit(n, gap_mm, norm=0.02):
    """Relative peak flux of harmonic n at this gap (existing amplitude form with the refitted K(g) and exponent 0.74 from ONE logged 5th/7th ratio: PENDING)."""
    return _u.harmonic_amplitude(n, gap_mm, CONST["period_mm"], CONST["flux_exponent"], CONST["coef"], norm)


# ------------------------------------------------------------------ gap-scan lineshape, wander
def rel_fwhm(n=7):
    """Relative FWHM of the harmonic peak in photon energy seen in a gap scan (mono fixed). ASSUMED ~0.98 % and n-independent (one logged width, n=7)."""
    return CONST["rel_fwhm"]


def gap_fwhm_mm(energy_keV, n):
    """FWHM of the flux-vs-gap peak [mm] = rel_fwhm * E / (dE/dgap). ~0.09 mm at n=7, 71.7 keV (assumed width)."""
    g = gap_pmu_mm(energy_keV, n)
    d = (energy_pmu_keV(g + 0.005, n) - energy_pmu_keV(g - 0.005, n)) / 0.01
    return rel_fwhm(n) * energy_keV / d


def gap_scan_profile(gaps_mm, energy_keV, n, gap_offset_mm=0.0):
    """Relative IC flux (peak = 1) vs gap for a fixed mono energy: Gaussian in photon energy of relative FWHM rel_fwhm, mapped through the fitted E_n(gap).
    gap_offset_mm shifts the peak (session wander / hysteresis). ASSUMED width; the peak position is fitted (0.01 mm)."""
    sig = rel_fwhm(n) * energy_keV / 2.3548
    return [math.exp(-0.5 * ((energy_pmu_keV(g - gap_offset_mm, n) - energy_keV) / sig) ** 2) for g in gaps_mm]


def gap_session_offset_sd_mm(same_session=False):
    """Standard deviation [mm] of the optimum gap about the model: 0.0009 within a session, 0.0092 between sessions (2024-2026 E-calibration rows, 39 / 52 values)."""
    return CONST["wander_within_mm"] if same_session else CONST["wander_between_mm"]


# ------------------------------------------------------------------ steering / source position
def steering_mm(urad, z_m=71.6):
    """Beam displacement [mm] at distance z_m from a steering change of urad (small angle; 0.025 mm/urad at 25 m logged)."""
    return urad * z_m * 1e-3


def offaxis_energy_rel(theta_urad, k, ring_GeV=None):
    """Relative red shift dE/E = (gamma theta)^2 / (1 + K^2/2) of the radiation seen theta off the undulator axis."""
    g = (ring_GeV or CONST["ring_GeV"]) * 1000.0 / 0.51099895
    return (g * theta_urad * 1e-6) ** 2 / (1.0 + k * k / 2.0)


def offaxis_gap_shift_mm(theta_urad, energy_keV, n):
    """Gap by which the flux maximum moves up when the accepted beam is theta_urad off axis (logged: 11 urad -> +0.085 mm at Au n=9; model 0.065 mm)."""
    g = gap_pmu_mm(energy_keV, n)
    d = (energy_pmu_keV(g + 0.005, n) - energy_pmu_keV(g - 0.005, n)) / 0.01
    return offaxis_energy_rel(theta_urad, k_pmu(g)) * energy_keV / d


def flux_vs_ring_current(current_mA, ref_mA=200.0):
    """Flux scale factor. ASSUMED linear in current (the logs only contain the operators' own linear extrapolation); top-up holds ~200.0 +- 0.2 mA."""
    return current_mA / ref_mA


# ------------------------------------------------------------------ SCU (2022 - Apr 2023), tuned by current
def k_scu(current_A):
    """K of SCU18-3 at this current. Fitted 180-825 A (0.4 % rms on the 19 anchor points, 1.2 % rms on all 24 incl. inferred harmonics)."""
    k0, k1, k2 = CONST["scu_k"]
    return k0 + k1 * current_A + k2 * current_A ** 2


def energy_scu_keV(current_A, n, ring_GeV=7.0):
    """Harmonic-n energy of the SCU at this current. ring_GeV 7 (to Mar 2023) or 6 (23 Apr 2023 test). Harmonic numbers here are the INFERRED physical ones
    (n=5 for the 2022 series, 7 for Au/Bi/Ir edges, 11 for the 587-825 A 6 GeV series), not always the labels written in the logs."""
    k = k_scu(current_A)
    return n * 0.9496 * ring_GeV ** 2 / (CONST["scu_period_mm"] / 10.0) / (1.0 + k * k / 2.0)
