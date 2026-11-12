"""Refractive focusing optics at 1-ID.

TILTED SAW-TOOTH (PRISM-ARRAY) LENSES (the 1-ID 'lens stacks': lens1E..lens4E, lens1C..lens4C, lens4B/5B in mpe_bluesky). The relation used here is the
beamline's own (mpe_bluesky/instrument/plans/calculator_tilt.py, calculate_tilt): thin lens  1/f = 1/p + 1/q  (p = source-to-lens, q = lens-to-focus),
an 'equivalent radius' r = f*delta, and tilt = asin(r / tooth_height). Equivalently f = h*sin(tilt)/delta: the focal length is set by a small tilt
(~0.1 deg, comparable to the lens `_zero` offsets of -0.011..-0.063 deg recorded in the device definitions). Literature on prism-array lenses:
Cederstrom et al., J. Synchrotron Rad. 12 (2005), doi:10.1107/s0909049504034181 - the formula above is the beamline's, not re-derived from that paper.

CONVENTIONAL PARABOLIC CRL: f = R / (2 N delta) (thin lens; Lengeler et al., J. Synchrotron Rad. 9 (2002), doi:10.1107/s0909049502003436).
"""
import math
from .core import delta_beta


def thin_lens_f_m(p_m, q_m):
    """1/f = 1/p + 1/q."""
    return 1.0 / (1.0 / p_m + 1.0 / q_m)


def image_distance_m(f_m, p_m):
    """q = 1/(1/f - 1/p): where a lens of focal length f focuses a source at distance p."""
    return 1.0 / (1.0 / f_m - 1.0 / p_m)


def prism_tilt_for_focus_deg(p_m, focus_at_m, delta, tooth_height_um):
    """Tilt [deg] to focus at `focus_at_m` (distance from the SOURCE) for a lens at p_m, exactly as mpe_bluesky.calculate_tilt:
    q = focus_at - p; f = (1/p+1/q)^-1; r = f*delta; tilt = asin(r/h). (Sign/zero conventions of the real motors are NOT included.)"""
    q = focus_at_m - p_m
    if q <= 0:
        raise ValueError("lens is at or beyond the requested focus position")
    f = thin_lens_f_m(p_m, q)
    s = f * delta / (tooth_height_um * 1e-6)
    if abs(s) > 1:
        raise ValueError("requested focal length unreachable with this tooth height (|sin tilt| > 1)")
    return math.degrees(math.asin(s))


def prism_focal_length_m(tilt_deg, delta, tooth_height_um):
    """f = h sin(tilt) / delta (inverse of prism_tilt_for_focus_deg)."""
    return tooth_height_um * 1e-6 * math.sin(math.radians(tilt_deg)) / delta


def prism_focus_position_m(tilt_deg, p_m, delta, tooth_height_um):
    """Distance from the SOURCE at which a lens at p_m with this tilt focuses."""
    f = prism_focal_length_m(tilt_deg, delta, tooth_height_um)
    return p_m + image_distance_m(f, p_m)


def focus_shift_per_tilt_m_per_mdeg(tilt_deg, p_m, delta, tooth_height_um, step_mdeg=1.0):
    """How far the focus moves [m] for a `step_mdeg` (milli-degree) tilt change: the sensitivity that sets the needed motor resolution."""
    a = prism_focus_position_m(tilt_deg, p_m, delta, tooth_height_um)
    b = prism_focus_position_m(tilt_deg + step_mdeg * 1e-3, p_m, delta, tooth_height_um)
    return b - a


def lens_delta(material, energy_keV):
    """delta of the lens material (Si for the 1-ID stacks) at this energy; scales as 1/E^2, so the focus moves when the energy changes."""
    return delta_beta(material, energy_keV)[0]


def crl_focal_length_m(radius_um, n_lenses, delta):
    """Thin parabolic CRL: f = R/(2 N delta)."""
    return radius_um * 1e-6 / (2.0 * n_lenses * delta)


# ---- the real 1-ID lens stacks -------------------------------------------------------------------------------------------------
# Source: mpe_bluesky/instrument/devices/s1id_devices/s1i{db,dc,de}_motors.py (LensDevice _about_kwargs). `from_source_m` = source-to-lens distance, `tooth_um` =
# saw-tooth height, `orientation` decides the sign and which tilt motor focuses (th for upr/up/inv/down, phi for out/ob/inb/in), `zero_deg` = recorded motor zero.
# NOTE lens2C is defined twice in s1idc_motors.py (upr, then inv, both 59.3 m); the later definition (inv) is the one that exists at runtime.
LENSES_1ID = {
    "lens4B": dict(hutch="B", material="Al", orientation="upr", from_source_m=38.8, tooth_um=100, zero_deg=0.0),
    "lens5B": dict(hutch="B", material="Al", orientation="inv", from_source_m=38.9, tooth_um=100, zero_deg=0.0),
    "lens1C": dict(hutch="C", material="Si", orientation="upr", from_source_m=59.2, tooth_um=200, zero_deg=0.0),
    "lens2C": dict(hutch="C", material="Si", orientation="inv", from_source_m=59.3, tooth_um=200, zero_deg=0.0),
    "lens3C": dict(hutch="C", material="Si", orientation="out", from_source_m=59.6, tooth_um=200, zero_deg=0.0),
    "lens4C": dict(hutch="C", material="Si", orientation="inb", from_source_m=59.7, tooth_um=200, zero_deg=0.0),
    "lens1E": dict(hutch="E", material="Si", orientation="inv", from_source_m=67.7, tooth_um=200, zero_deg=-0.011),
    "lens2E": dict(hutch="E", material="Si", orientation="upr", from_source_m=67.9, tooth_um=200, zero_deg=-0.0627),
    "lens3E": dict(hutch="E", material="Si", orientation="inb", from_source_m=68.1, tooth_um=200, zero_deg=0.0),
    "lens4E": dict(hutch="E", material="Si", orientation="out", from_source_m=68.5, tooth_um=200, zero_deg=0.0),
}
DEFAULT_FOCUS_E_M = 71.5     # mpe_bluesky default focus position = the E-hutch sample stage (distance from the source)


def focus_motor_target(name, energy_keV, focus_at_m=DEFAULT_FOCUS_E_M):
    """What mpe_bluesky.focus_calc recommends for lens `name`: (motor, degrees). Reproduces the logged 'BS prediction' at the Hf edge (65.35 keV,
    focus 71.5 m): lens1E +0.105 deg, lens2E -0.173 deg (2026 startup log, measured optima +0.107 / -0.168: prediction good to ~0.002-0.01 deg)."""
    L = LENSES_1ID[name]
    tilt = prism_tilt_for_focus_deg(L["from_source_m"], focus_at_m, lens_delta(L["material"], energy_keV), L["tooth_um"])
    if L["orientation"] in ("upr", "up", "out", "ob"):
        tilt = -tilt
    motor = "th" if L["orientation"] in ("upr", "up", "inv", "down") else "phi"
    return motor, tilt + L["zero_deg"]
