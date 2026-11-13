"""Fitted focusing-optics / beam-propagation models for the 1-ID virtual beamline.  numpy-only (no xraydb, no scipy).  Lengths m / um, energy keV, angles deg.

Constants come from beamline_twins/1-ID/physics/fits/optics.json (key "params") when that file is found, else from the embedded fallbacks below
(identical values).  Provenance, residuals and the data tables are in that JSON and in optics.md next to it.

WHAT IS FITTED (all from the 1-ID logs, see optics.md)                       validity
  * tilt-lens focal length  f = h sin(tilt) / (c delta(E)),  c = 2.11 +- 0.17   E-hutch Si stacks, 52-91 keV, tilt 0.05-0.2 deg
    (the code in mpe_bluesky / blade.physics.lens has c = 1: that is the factor that made the Feb-2026 attempt to solve for the source distance give
    nonsense).  Only h/c (about 95 um for the 200 um stacks) is identified, not h and c separately.
  * E-hutch focus ("sample") plane at z = 69.49 +- 0.15 m from the source (the code's default is 71.5 m); matches the 69.5 m quoted in a 2025 user log.
  * B-hutch CRL (2-D) focal spot: FWHM^2 = s0^2 + (b (E^2 - E_tuned^2))^2 (defocus blur), s0 = 23.8 (V) / 29.2 (H) um, b = 0.096 um/keV^2, B->E focus.
  * regular vs brightness mode: measured spot sizes at 61.26 keV (the source size itself is only bounded, see source_fwhm_bounds_um).
ASSUMED (not fitted): source-lens distance p = nominal lens z (not identifiable, see optics.md), beam sigma at WB slits, lens aperture, stack absorption
thickness, Fresnel visibility.  Nothing here talks to hardware."""
import json
import math
from pathlib import Path

_JSON = Path(__file__).resolve().parents[2] / "beamline_twins/1-ID/physics/fits/optics.json"

_DEFAULT = {
    "delta_si_65351": 1.12796e-7,       # Si delta at the Hf edge, logged in the 2026 startup log; delta ~ 1/E^2 (xraydb: 1.12845e-7)
    "al_over_si_delta": 1.12,           # (rho Z/A)_Al / (rho Z/A)_Si
    "tilt_c": 2.11,                     # f = h sin(tilt) / (c delta)           (fit, +-0.17, strongly anti-correlated with z_sample)
    "z_sample_E_m": 69.49,              # focus plane of 'tomo at sample' for the E lens stacks (fit, +-0.15)
    "crl_B_z_m": 38.9,                  # B-hutch CRL / lens4B position used for the B->E focus (nominal, mpe_bluesky)
    "crl_s0_um": {"v": 23.8, "h": 29.2},  # best-focus FWHM of the B CRL focus, Nov 2024, 61 keV, WB 0.3 mm (fit +-0.5)
    "crl_defocus_b_um_per_keV2": 0.0956,  # +-0.0125
    "crl_E_tuned_keV_nov24": 60.65,     # energy at which the CRL setting of Nov 2024 was best (+-0.19)
    "spot_fwhm_um_61p26keV": {          # measured B->E focus, Feb 2026 (2026-Brightness_mode_feb26:L39-65), tuned
        "regular": {"v": 22.9, "h": 27.5}, "brightness": {"v": 16.9, "h": 30.1}},
    "steer_lever_arm_m": 25.0,          # mm of hotspot motion at the WB slits per urad of steering = lever_arm*1e-3 (tuple: -6 urad -> 150 um; 10 urad -> 0.25 mm)
    "psf_px": 1.8,                      # camera blur (sigma, px), same as sim.json cameras.*.psf_px
}


def _load():
    p = dict(_DEFAULT)
    try:
        with open(_JSON) as f:
            p.update(json.load(f)["params"])
    except (OSError, ValueError, KeyError):
        pass
    return p


P = _load()
FWHM_PER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))      # 2.3548
HC_KEV_A = 12.398419843320026

# E-hutch / B-hutch stacks (copy of blade.physics.lens.LENSES_1ID, the parts used here; test_fit_optics.py checks they agree)
STACKS = {
    "lens4B": dict(material="Al", orientation="upr", z_m=38.8, tooth_um=100, zero_deg=0.0),
    "lens5B": dict(material="Al", orientation="inv", z_m=38.9, tooth_um=100, zero_deg=0.0),
    "lens1C": dict(material="Si", orientation="upr", z_m=59.2, tooth_um=200, zero_deg=0.0),
    "lens2C": dict(material="Si", orientation="inv", z_m=59.3, tooth_um=200, zero_deg=0.0),
    "lens3C": dict(material="Si", orientation="out", z_m=59.6, tooth_um=200, zero_deg=0.0),
    "lens4C": dict(material="Si", orientation="inb", z_m=59.7, tooth_um=200, zero_deg=0.0),
    "lens1E": dict(material="Si", orientation="inv", z_m=67.7, tooth_um=200, zero_deg=-0.011),
    "lens2E": dict(material="Si", orientation="upr", z_m=67.9, tooth_um=200, zero_deg=-0.0627),
    "lens3E": dict(material="Si", orientation="inb", z_m=68.1, tooth_um=200, zero_deg=0.0),
    "lens4E": dict(material="Si", orientation="out", z_m=68.5, tooth_um=200, zero_deg=0.0),
}


# ------------------------------------------------------------------------------------------------------------------------ tilt lenses
def delta(energy_keV, material="Si"):
    """Refractive-index decrement of the lens material, delta ~ 1/E^2 anchored on the logged Si value at 65.351 keV (valid 20-120 keV, away from edges)."""
    d = P["delta_si_65351"] * (65.351 / energy_keV) ** 2
    return d * (P["al_over_si_delta"] if material == "Al" else 1.0)


def tilt_focal_length_m(tilt_deg, energy_keV, material="Si", tooth_um=200.0, c=None):
    """Fitted focal length of a tilted saw-tooth stack: f = h sin(tilt) / (c delta).  `tilt` is relative to the lens zero (magnitude gives f>0)."""
    c = P["tilt_c"] if c is None else c
    return tooth_um * 1e-6 * math.sin(math.radians(tilt_deg)) / (c * delta(energy_keV, material))


def tilt_for_focus_deg(lens, energy_keV, focus_z_m=None, c=None):
    """Tilt magnitude [deg, relative to the lens zero] that focuses a source at the nominal source-lens distance onto z = focus_z_m (from the source).
    Default focus plane for hutch E stacks is the fitted E sample plane (69.49 m), NOT 71.5 m.  Add sign/zero with lens_motor_target()."""
    L = STACKS[lens]
    c = P["tilt_c"] if c is None else c
    if focus_z_m is None:
        focus_z_m = P["z_sample_E_m"]
    p, q = L["z_m"], focus_z_m - L["z_m"]
    if q <= 0:
        raise ValueError("lens is at or beyond the requested focus plane")
    f = 1.0 / (1.0 / p + 1.0 / q)
    s = c * f * delta(energy_keV, L["material"]) / (L["tooth_um"] * 1e-6)
    if abs(s) > 1:
        raise ValueError("focal length unreachable with this tooth height")
    return math.degrees(math.asin(s))


def lens_motor_target(lens, energy_keV, focus_z_m=None, c=None):
    """(motor, degrees) with the sign/zero convention of blade.physics.lens.focus_motor_target but the fitted c and focus plane."""
    L = STACKS[lens]
    t = tilt_for_focus_deg(lens, energy_keV, focus_z_m, c)
    if L["orientation"] in ("upr", "up", "out", "ob"):
        t = -t
    motor = "th" if L["orientation"] in ("upr", "up", "inv", "down") else "phi"
    return motor, t + L["zero_deg"]


def focus_z_for_tilt_m(lens, tilt_deg, energy_keV, c=None):
    """Distance from the source at which the stack focuses for a given (zero-relative) tilt magnitude."""
    L = STACKS[lens]
    f = tilt_focal_length_m(tilt_deg, energy_keV, L["material"], L["tooth_um"], c)
    p = L["z_m"]
    if f >= p:
        return float("inf")
    return p + 1.0 / (1.0 / f - 1.0 / p)


def focus_shift_mm_per_mdeg(lens, tilt_deg, energy_keV, c=None):
    """How far the focus moves [mm] per milli-degree of tilt (fitted model; the old c=1 / 71.5 m model gave ~41 mm/mdeg, this gives ~15)."""
    a = focus_z_for_tilt_m(lens, tilt_deg, energy_keV, c)
    b = focus_z_for_tilt_m(lens, tilt_deg + 1e-3, energy_keV, c)
    return (b - a) * 1e3


def focus_spot_fwhm_um(source_fwhm_um, p_m, q_m, floor_um=0.0):
    """Demagnified source (+ floor in quadrature): sqrt((q/p s)^2 + floor^2).  p, q = source-lens and lens-focus distances."""
    return math.hypot(q_m / p_m * source_fwhm_um, floor_um)


# ------------------------------------------------------------------------------------------------------------------------ spot size vs energy
def spot_size_um(energy_keV, mode="regular", axis="v", e_tuned_keV=None):
    """FWHM [um] of the B-CRL -> E focus on the tomo camera.
    At the tuned energy: the measured value of the requested `mode` ('regular' | 'brightness') and `axis` ('v' | 'h') (Feb 2026, 61.26 keV).
    Off the tuned energy the CRL (f ~ E^2) defocuses: FWHM^2 = s0^2 + (b (E^2 - E_tuned^2))^2 with b fitted on Nov-2024 data (E_tuned default = 61.26).
    Valid 60-63 keV (fit range); beyond ~65 keV it is an extrapolation.  Camera PSF is included in the logged values."""
    s0 = P["spot_fwhm_um_61p26keV"][mode][axis]
    et = 61.26 if e_tuned_keV is None else e_tuned_keV
    d = P["crl_defocus_b_um_per_keV2"] * (energy_keV ** 2 - et ** 2)
    return math.hypot(s0, d)


def crl_spot_nov24_um(energy_keV, axis="v"):
    """The Nov-2024 fit itself (CRL last tuned near 60.65 keV, regular mode, tomo 7.5x): reproduces the logged 60.3-62.3 keV series."""
    d = P["crl_defocus_b_um_per_keV2"] * (energy_keV ** 2 - P["crl_E_tuned_keV_nov24"] ** 2)
    return math.hypot(P["crl_s0_um"][axis], d)


def source_fwhm_bounds_um(mode="regular", axis="v", q_over_p=None):
    """(lo, hi) bounds [um FWHM] on the electron-beam source size implied by the logged B->E spots, assuming the same optical floor in both modes.
    hi = spot/M (zero floor); lo (regular V only) from the regular-minus-brightness difference with a zero-size brightness-mode source.
    Only bounds are constrained by the logs: the logged 'focused beam size' is NOT the source size."""
    M = (P["z_sample_E_m"] - P["crl_B_z_m"]) / P["crl_B_z_m"] if q_over_p is None else q_over_p
    S = P["spot_fwhm_um_61p26keV"]
    hi = S[mode][axis] / M
    d2 = S["regular"][axis] ** 2 - S["brightness"][axis] ** 2          # = M^2 (s_reg^2 - s_bri^2) for equal floors
    lo = 0.0
    if (d2 > 0 and mode == "regular") or (d2 < 0 and mode == "brightness"):
        lo = math.sqrt(abs(d2)) / M                                      # the larger-source mode exceeds sqrt(|d2|)/M even if the other source were a point
    return lo, hi


# ------------------------------------------------------------------------------------------------------------------------ slit-edge blur
def edge_penumbra_sigma_um(z_aperture_m, z_camera_m, source_sigma_um):
    """Geometric penumbra of a slit edge for a finite source in free propagation: sigma = s (z_cam - z_ap) / z_ap  (what blade.vbl uses; checked equal to
    its ray map in test_fit_optics.py).  Lenses between slit and camera change the factor (use the ray map then)."""
    return source_sigma_um * (z_camera_m - z_aperture_m) / z_aperture_m


def fresnel_scale_um(energy_keV, z_aperture_m, z_camera_m):
    """sqrt(lambda L_eff / 2) in um (the scale of the first Fresnel rim), L_eff = z_ap (z_cam - z_ap)/z_cam, as blade.vbl.imaging reports it.
    At 71.7 keV: 12 um for the WB slits, 4 um for the E-DS slits, i.e. 6-17 px on the 0.69 um/px camera: rims are resolvable."""
    lam_m = HC_KEV_A / energy_keV * 1e-10
    leff = z_aperture_m * (z_camera_m - z_aperture_m) / z_camera_m
    return math.sqrt(lam_m * leff / 2.0) * 1e6


def fringe_visibility(sigma_pen_um, period_um):
    """Visibility of fringes of period `period_um` after convolution with the geometric penumbra (Gaussian, sigma): exp(-2 pi^2 (sigma/period)^2).
    Rims survive only where sigma_pen < ~0.2 x the Fresnel scale (E slits yes, WB/B slits no)."""
    return math.exp(-2.0 * math.pi ** 2 * (sigma_pen_um / period_um) ** 2)


def edge_blur_sigma_px(z_aperture_m, z_camera_m, source_sigma_um, pixel_um, psf_px=None):
    """Total edge-spread sigma [px]: geometric penumbra and camera PSF in quadrature (diffraction rim not included, see fresnel_scale_um)."""
    psf = P["psf_px"] if psf_px is None else psf_px
    return math.hypot(edge_penumbra_sigma_um(z_aperture_m, z_camera_m, source_sigma_um) / pixel_um, psf)


def edge_10_90_um(sigma_px, pixel_um):
    """10-90 % edge width [um] of an error-function edge: 2.563 sigma."""
    return 2.5631 * sigma_px * pixel_um


def slit_image_size_mm(opening_mm, z_slit_m, z_plane_m):
    """Geometric footprint of a slit opening on a plane z (point source), mm: opening z_plane / z_slit."""
    return opening_mm * z_plane_m / z_slit_m


# ------------------------------------------------------------------------------------------------------------------------ hotspot / steering
def steering_shift_mm(dxp_urad, z_m=27.0):
    """Hotspot shift [mm] at distance z for a steering change dxp [urad]: dxp z.  The fit-tuple uses the WB slits (27 m): 6 urad -> 150 um (lever 25 m),
    10 urad -> 0.25 mm at 25 m.  1 urad = 0.0695 mm at the E sample plane (69.49 m)."""
    return dxp_urad * 1e-3 * z_m


def hotspot_shift_mm_vs_energy(energy_keV, e_ref_keV=71.676):
    """Hotspot (WB-slit centre) shift vs energy for the present undulator: the logs bound it, they do not resolve a slope.  Returns 0.0 with
    half-width 0.03 mm (+-1 urad at 27 m) over 52-81 keV.  Returns (shift_mm, half_width_mm)."""
    return 0.0, 0.03


# ------------------------------------------------------------------------------------------------------------------------ stack absorption / clipping
_MU_E = [30, 40, 50, 60, 70, 80, 90, 100]
_MU_CM = {  # linear attenuation [1/cm], xraydb 4.5.8, rho = 2.70 (Al) / 2.33 (Si)
    "Al": [3.0466, 1.5346, 0.994, 0.7501, 0.6213, 0.5448, 0.495, 0.4601],
    "Si": [3.347, 1.6332, 1.0217, 0.7471, 0.6034, 0.5191, 0.465, 0.4276],
}


def mu_per_cm(energy_keV, material="Si"):
    """Linear attenuation coefficient [1/cm], log-log interpolation of the embedded xraydb table (30-100 keV; error < 2 %)."""
    xs, ys = _MU_E, _MU_CM[material]
    e = min(max(energy_keV, xs[0]), xs[-1])
    for i in range(len(xs) - 1):
        if xs[i] <= e <= xs[i + 1]:
            t = (math.log(e) - math.log(xs[i])) / (math.log(xs[i + 1]) - math.log(xs[i]))
            return math.exp(math.log(ys[i]) + t * (math.log(ys[i + 1]) - math.log(ys[i])))
    return ys[-1]


def stack_transmission(energy_keV, material="Si", mean_thickness_um=400.0):
    """exp(-mu t) through a lens stack of effective mean thickness t.  t is ASSUMED (tooth count / web thickness unknown, PENDING a transmission
    measurement); at 61 keV 1 mm of Al absorbs 7 %."""
    return math.exp(-mu_per_cm(energy_keV, material) * mean_thickness_um * 1e-4)


def aperture_transmission(beam_sigma_mm, aperture_mm):
    """Fraction of a 1-D Gaussian beam (sigma) passing a centred slot of full width `aperture_mm`: erf(a / (2 sqrt2 sigma))."""
    return math.erf(aperture_mm / (2.0 * math.sqrt(2.0) * beam_sigma_mm))


def beam_sigma_mm_at(z_m, sigma_at_wb_mm=0.14, z_wb_m=27.0):
    """Gaussian beam sigma [mm] at distance z (divergence set by the logged WB-slit flux ratio, blade.vbl sim.json source.beam_sigma_at_wb_mm)."""
    return sigma_at_wb_mm * z_m / z_wb_m
