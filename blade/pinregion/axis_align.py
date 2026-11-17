"""Rotation-axis maths of the pin alignment (stage 5 of the pin workflow: the decision logic that uses it is procedures/pin_alignment.py; nothing here touches hardware).

Geometry (user, 2026-10-27): the rotation axis is fixed by the base and does NOT move with samE.x/y/z; those move the pin
(sample) relative to the axis. Pin point at rotating-frame offset (a, b) from the axis, axis at image column c:
     x(w) = c + a cos w + b sin w          (pixels)
  =>  x(+t) - x(-t) = 2 b sin t            (a and c cancel)      -> b  (cancelled by z)
      x(+t) + x(-t) = 2 (c + a cos t),  x(0) = c + a  ->  a = (x(0) - s)/(1 - cos t)  (reliable only at large t) -> cancelled by x
After a, b -> 0 the pin sits on the axis and x(w) = c is constant; c is then moved onto the beam centre by the BASE motors
(not yet identified - base_move_mm() only reports the needed shift, it never moves anything).

Constants (pixel size, signs) live in the beamline profile (blade/config.py).
"""
import numpy as np
from .. import config as cfg

A_MIN_DEG = 30        # smallest angle whose 'a' estimate is trusted


def estimate_ab(x0, x_plus, x_minus, theta_deg):
    t = np.deg2rad(theta_deg)
    b = (x_plus - x_minus) / (2 * np.sin(t))
    s = 0.5 * (x_plus + x_minus)
    a = (x0 - s) / (1 - np.cos(t)) if theta_deg >= A_MIN_DEG else np.nan
    return a, b


def base_move_mm(c_px, beam_cx_px):
    """Shift of the rotation axis needed to bring it onto the beam centre, in image columns -> mm. Motor/sign TBD (base stage)."""
    return cfg.px_to_mm(beam_cx_px - c_px)
