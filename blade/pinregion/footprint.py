"""Beam footprint of a frame = the BEAM measurement of the alignment (not pin detection): the half-maximum footprint of the lit area, centre = midpoint (user decision 2026-10-27), measured so that the pin
shadow cannot drag it. The pin is excluded using the pin REGION of pin workflow v2 (measure.measure_frame passes its extents); with no pin, plain means. Moved here unchanged from the retired
analysis/pin/measure.py when that package was deleted 2026-11-17. Note: this is NOT the same as `region.fov_box` (the 4 %-level lit window incl. the dim halo, used for clipping): on real GH1 frames the two
differ by ~200 px in centre, so the footprint stays the alignment target."""
import numpy as np
from scipy import ndimage as ndi


def _cross(profile, sigma=5.0, frac=0.5):
    """Sub-pixel half-maximum edges (lo, hi) of a lit-area profile."""
    p = ndi.gaussian_filter1d(np.asarray(profile, float), sigma)
    base, top = np.percentile(p, 5), np.percentile(p, 90)
    lvl = base + frac * (top - base)
    idx = np.where(p > lvl)[0]
    if len(idx) < 2:
        return None
    i0, i1 = idx[0], idx[-1]
    lo = i0 - 1 + (lvl - p[i0 - 1]) / (p[i0] - p[i0 - 1]) if i0 > 0 else float(i0)
    hi = i1 + (p[i1] - lvl) / (p[i1] - p[i1 + 1]) if i1 < len(p) - 1 else float(i1)
    return lo, hi


def beam_footprint(img, pin=None, margin=15, pin_present=True, geom=None):
    """Half-maximum footprint of the lit area (centre = midpoint, user decision 2026-10-27) that IGNORES the pin shadow.

    The old estimate averaged whole rows/columns, so a pin sitting off-centre darkened one side and dragged the 'beam centre'
    by up to ~150 px. Here the column profile is taken only over rows ABOVE the pin top, the row profile only over columns
    OUTSIDE the pin. A coarse 90th-percentile pass (insensitive to a shadow covering < 90 % of a row/column) fixes the search window.
    `pin` = the PinFit (optional); `pin_present=False` (empty frame) allows plain means. With a pin present but its geometry unavailable the
    result stays on the coarse percentile pass (method 'p90-coarse', a few px less consistent with the half-max definition).
    Returns cx, cy, box (x0, x1, y0, y1), width, height, method."""
    f = 4
    H, W = img.shape
    h, w = H // f * f, W // f * f
    im4 = img[:h, :w].astype(np.float32).reshape(h // f, f, w // f, f).mean(axis=(1, 3))
    rr = _cross(np.percentile(im4, 90, axis=1), 1.5)
    if rr is None:
        return None
    m = int(0.1 * (rr[1] - rr[0]))
    cc = _cross(np.percentile(im4[int(rr[0]) + m:int(rr[1]) - m], 90, axis=0), 1.5)
    if cc is None:
        return None
    c0, c1 = cc[0] * f + (f - 1) / 2, cc[1] * f + (f - 1) / 2
    r0, r1 = rr[0] * f + (f - 1) / 2, rr[1] * f + (f - 1) / 2
    method = "p90-coarse"
    # refinement at full resolution, excluding the pin
    xl = xr = top = None
    if geom is not None:                                    # (x_left, x_right, top_row) of the pin's dark object, e.g. from its mask
        xl, xr, top = geom
    elif pin is not None and getattr(pin, "left_line", None) is not None and getattr(pin, "right_line", None) is not None \
            and np.isfinite(getattr(pin, "top_row", np.nan)):
        top = float(pin.top_row)
        ys = (top, r1)
        xl = min(pin.left_line[0] * y + pin.left_line[1] for y in ys)
        xr = max(pin.right_line[0] * y + pin.right_line[1] for y in ys)
    pad = 100
    xa, xb = max(0, int(c0) - pad), min(W, int(c1) + pad)
    ya, yb = max(0, int(r0) - pad), min(H, int(r1) + pad)
    out_c = out_r = None
    if top is not None and top - r0 > 60:                        # pin-free band above the pin top
        band = img[int(r0) + margin:int(top) - margin, xa:xb].astype(np.float32).mean(axis=0)
        e = _cross(band)
        if e:
            out_c = (e[0] + xa, e[1] + xa)
    elif top is None and not pin_present:
        e = _cross(img[int(r0) + int(m * f):int(r1) - int(m * f), xa:xb].astype(np.float32).mean(axis=0))
        if e:
            out_c = (e[0] + xa, e[1] + xa)
    cols = np.arange(int(c0) + margin, int(c1) - margin)
    if xl is not None:
        cols = cols[(cols < xl - 30) | (cols > xr + 30)]
    if (xl is not None or not pin_present) and len(cols) >= 80:
        e = _cross(img[ya:yb][:, cols].astype(np.float32).mean(axis=1))
        if e:
            out_r = (e[0] + ya, e[1] + ya)
    if out_c:
        c0, c1, method = out_c[0], out_c[1], "pin-excluded"
    if out_r:
        r0, r1 = out_r
    return {"cx": float((c0 + c1) / 2), "cy": float((r0 + r1) / 2), "box": [int(round(c0)), int(round(c1)), int(round(r0)), int(round(r1))],
            "width": float(c1 - c0), "height": float(r1 - r0), "method": method}
