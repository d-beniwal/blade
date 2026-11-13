"""Tomo-camera image of the virtual beamline: what the scintillator + microscope camera shows for the current settings.

An image is  counts = bg + exposure x gain x [beam x pin x texture]  blurred by the camera PSF / defocus, times scintillator dust, plus noise:
  beam      separable Gaussian-in-angle beam (world.trace) times, for EVERY aperture upstream (WB, B/C/E Kohzu slits, fast shutters, lens windows),
            a projected box whose edges are (a) shifted to where the edge lands on the camera plane, (b) blurred by the geometric penumbra
            |E_cam - A_cam E_i/A_i| x source size (a slit far upstream of the camera gives a wide, soft edge; the slit right in front of it a crisp one),
            (c) rippled by the Fresnel knife-edge diffraction of that edge (fringes) before the blur. So an edge defined by a slit that sits IN the beam
            far upstream looks blurry, one defined by a nearby slit looks sharp, exactly as in the logbook images.
  texture   beam-fixed structure: hot irregular core + lopsided falloff, blobs/mottle/speckle, and discrete window faults (pits, scratches, streaks) as seen in
            the logbook images (moves with the beam) and camera-fixed dust/vignetting (moves with the camera).
  pin       hutch-E alignment pin: dark truncated cone at the position world.pin_state() gives, magnified by the ray map, with Fresnel edge ripple and the
            half-transparent flank seen at |omega| ~ 90 (same shape model as the original BLADE simulator, so `blade align` works on it).
Nothing is drawn that physics does not produce, except the textures (seeded, so a given seed always looks the same)."""
import math
import zlib
import struct
from functools import lru_cache
import numpy as np
from scipy.ndimage import gaussian_filter, gaussian_filter1d
from scipy.special import fresnel, expit
from ..physics import core as pcore
from .world import stable_seed

PIN_COLOR = None


# ---------------------------------------------------------------------------------------------------------------------------------- textures
@lru_cache(maxsize=24)
def _noise(seed, n, sx, sy):
    """Periodic smooth noise field (n x n, std 1); correlation lengths sx, sy in grid cells (anisotropic)."""
    rng = np.random.default_rng(seed)
    f = np.fft.fft2(rng.normal(size=(n, n)))
    kx = np.fft.fftfreq(n)[None, :]
    ky = np.fft.fftfreq(n)[:, None]
    filt = np.exp(-0.5 * ((kx * sx * 2 * np.pi) ** 2 + (ky * sy * 2 * np.pi) ** 2))
    a = np.fft.ifft2(f * filt).real
    return ((a - a.mean()) / a.std()).astype(np.float32)


def _resample(N, ry, rx):
    """Bilinear sample of the periodic field N at float indices ry (rows) x rx (cols) on an axis-aligned grid -> (len(ry), len(rx))."""
    n = N.shape[0]
    x0 = np.floor(rx).astype(np.int64)
    fx = (rx - x0).astype(np.float32)
    x0 %= n
    x1 = (x0 + 1) % n
    Nx = N[:, x0] * (1 - fx) + N[:, x1] * fx
    y0 = np.floor(ry).astype(np.int64)
    fy = (ry - y0).astype(np.float32)
    y0 %= n
    y1 = (y0 + 1) % n
    return Nx[y0, :] * (1 - fy)[:, None] + Nx[y1, :] * fy[:, None]


@lru_cache(maxsize=4)
def _defect_field(seed, n=1024):
    """Window-imperfection map (n x n, ~1 = clean) on the same 4 um grid as the noise fields: the transmission faults the beam picks up crossing the Be/diamond/
    kapton windows between hutches. Dark pits and a few bright ones (phase-contrast edge of a void), thin scratches / drawn-line marks, and wide soft
    streaks (window rolling marks). Periodic, seeded."""
    rng = np.random.default_rng(seed * 13 + 5)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    f = np.ones((n, n), np.float32)

    def wrap(a, c):
        return (a - c + n / 2) % n - n / 2
    for _ in range(26):                                   # pits / inclusions, 12-60 um
        cx, cy, r = rng.uniform(0, n), rng.uniform(0, n), rng.uniform(3, 15)
        a = rng.uniform(0.10, 0.45) * (1 if rng.random() < 0.75 else -0.5)
        sx, sy = r * rng.uniform(0.6, 1.6), r * rng.uniform(0.6, 1.6)
        win = (np.abs(wrap(xx, cx)) < 4 * sx) & (np.abs(wrap(yy, cy)) < 4 * sy)
        f[win] *= 1.0 - a * np.exp(-0.5 * ((wrap(xx, cx)[win] / sx) ** 2 + (wrap(yy, cy)[win] / sy) ** 2))
    for _ in range(5):                                    # scratches: 80-400 um long, 4-12 um wide
        cx, cy, L = rng.uniform(0, n), rng.uniform(0, n), rng.uniform(20, 100)
        ang = rng.choice([0.0, math.pi / 2, rng.uniform(0, math.pi)], p=[0.35, 0.25, 0.4]) + rng.normal(0, 0.05)
        w, a = rng.uniform(1.0, 3.0), rng.uniform(0.08, 0.25) * (1 if rng.random() < 0.7 else -0.6)
        dx, dy = wrap(xx, cx), wrap(yy, cy)
        al = dx * math.cos(ang) + dy * math.sin(ang)
        ac = -dx * math.sin(ang) + dy * math.cos(ang)
        win = (np.abs(al) < L) & (np.abs(ac) < 4 * w)
        f[win] *= 1.0 - a * np.exp(-0.5 * (ac[win] / w) ** 2) * np.clip(1.0 - (np.abs(al[win]) / L) ** 4, 0, 1)
    for _ in range(3):                                    # soft streaks, 25-60 um wide, running most of the field
        c, w, a = rng.uniform(0, n), rng.uniform(6, 15), rng.uniform(0.06, 0.16) * rng.choice([-1, 1])
        k = np.exp(-0.5 * (wrap(xx if rng.random() < 0.6 else yy, c) / w) ** 2)
        f *= 1.0 - a * k * (0.6 + 0.4 * _noise(seed * 7 + 9, n, 30.0, 30.0))
    return np.clip(f, 0.2, 1.6)


def beam_texture(seed, u, v, amp, u0=None, v0=None, wh=None, wv=None, core_amp=1.0):
    """Beam-fixed multiplicative texture at lab coordinates (u horizontal mm increasing to the image right, v vertical mm increasing up).
    Built like the real beam (logbook images): an irregular, hot core that falls off lopsidedly (centre at (u0, v0), width ~ footprint wh x wv, domain-warped so
    it is not a clean ellipse), large soft blobs ~150 um, mid-scale mottle, fine speckle, vertical fringe streaks, and the discrete window faults of
    `_defect_field`. `amp` is the camera's texture strength (0.15 = nominal); `core_amp` the strength of the hot core (0 = flat-topped, 1 = pg1-like, strongly peaked)."""
    pitch = 0.004                                  # mm per grid cell: the fields span 4 mm and repeat
    k = amp / 0.15
    ry, rx = -v / pitch, u / pitch
    R = lambda s_, sx, sy, oy=0.0, ox=0.0: _resample(_noise(seed * 7 + s_, 1024, sx, sy), ry + oy, rx + ox)
    t = (1.0 + 0.26 * k * R(1, 16.0, 17.0))                         # blobs
    t = t * (1.0 + 0.17 * k * R(2, 6.0, 6.0, 31.0, 17.0))            # mid mottle
    t = t * (1.0 + 0.07 * k * R(3, 1.4, 1.4, 11.0, 7.0))             # speckle
    t = t * (1.0 + 0.10 * k * R(4, 5.0, 22.0, 5.0, 3.0))             # vertical fringe streaks
    t = t * (1.0 + 0.12 * k * R(5, 45.0, 60.0, 77.0, 41.0))          # very large irregular modulation: lopsided falloff
    t = t * _resample(_defect_field(seed), ry, rx)                   # window faults
    if u0 is not None and wh and wv:
        # hot core: Gaussian lobe in domain-warped coordinates (warp ~ 7% of the footprint), plus a weaker off-centre shoulder
        wu = 0.07 * wh * R(6, 30.0, 30.0, 3.0, 9.0)
        wvv = 0.07 * wv * R(7, 30.0, 30.0, 19.0, 5.0)
        du, dv = (u - u0)[None, :] + wu, (v - v0)[:, None] + wvv
        sh, sv = 0.26 * wh, 0.30 * wv
        core = np.exp(-0.5 * ((du / sh) ** 2 + (dv / sv) ** 2))
        sh2, sv2 = 0.6 * wh, 0.6 * wv
        shoulder = np.exp(-0.5 * (((du - 0.12 * wh) / sh2) ** 2 + ((dv + 0.08 * wv) / sv2) ** 2))
        t = t * (0.75 + core_amp * (1.0 * core + 0.45 * shoulder)) / (0.75 + 1.45 * core_amp) * (2.2 / 2.4)
        # normalised so the core peak ~ 1 for any core_amp (camera 'full' = counts at the centre); rim ~ 0.75/(0.75+1.45 core_amp): 0.34 at 1.0, 0.51 at 0.5
    return np.clip(t, 0.05, None)


@lru_cache(maxsize=16)
def camera_maps(cam, seed, rows, cols, dust_amp):
    """Camera-fixed maps: scintillator dust + vignetting, hot pixels (deterministic per camera and seed)."""
    rng = np.random.default_rng(stable_seed(cam, seed))
    yy, xx = np.mgrid[0:rows, 0:cols].astype(np.float32)
    r2 = ((xx - cols / 2) / (cols / 2)) ** 2 + ((yy - rows / 2) / (rows / 2)) ** 2
    maps = 1.0 - 0.12 * r2
    n = int(40 + 60 * dust_amp * 10)
    for _ in range(n):                              # dust / scintillator blobs
        cx, cy, r = rng.uniform(0, cols), rng.uniform(0, rows), rng.uniform(2.0, 9.0)
        a = rng.uniform(0.3, 1.0) * dust_amp * 4.0 * rng.choice([-1, 1], p=[0.7, 0.3])
        x0, x1, y0, y1 = int(max(cx - 4 * r, 0)), int(min(cx + 4 * r, cols)), int(max(cy - 4 * r, 0)), int(min(cy + 4 * r, rows))
        if x1 > x0 and y1 > y0:
            maps[y0:y1, x0:x1] *= 1.0 - a * np.exp(-((xx[y0:y1, x0:x1] - cx) ** 2 + (yy[y0:y1, x0:x1] - cy) ** 2) / (2 * r * r))
    hot = np.zeros((rows, cols), np.float32)
    k = int(rows * cols * 1.2e-4)
    hot[rng.integers(0, rows, k), rng.integers(0, cols, k)] = rng.uniform(1500, 20000, k)
    return np.clip(maps, 0.2, None), hot


# ---------------------------------------------------------------------------------------------------------------------------------- aperture profiles
def _box_fresnel(x, a, b, k):
    """Fresnel (knife-edge pair) intensity of a slit [a, b] seen at coordinates x (same units); k = (slit-plane scale) * sqrt(2/(lambda L_eff))."""
    wa, wb = (a - x) * k, (b - x) * k
    sa, ca = fresnel(wa)
    sb, cb = fresnel(wb)
    return 0.5 * ((cb - ca) ** 2 + (sb - sa) ** 2)


def axis_profile(world, axis, cam, coords, bin_=1):
    """Intensity profile along one axis at the camera plane (per mm), the apertures' projected edges, and which aperture defines each side.
    Returns (profile array over `coords`, info dict). `coords` are lab coordinates (mm) of the pixel centres."""
    zc = world.camera_view(cam)[0]
    tr = world.trace(axis, zc)
    sim = world.sim
    S = sim["source"]["size_um_fwhm"][axis] / 2.3548 * 1e-3             # mm (sigma)
    sg = world.sigma_theta()
    th0 = world.steer_rad()[0 if axis == "h" else 1]
    A, E, B = tr["A"], tr["E"], tr["B"]
    su = math.hypot(A * sg, E * S)
    u0 = B + A * th0
    g = np.exp(-0.5 * ((coords - u0) / su) ** 2) / (math.sqrt(2 * math.pi) * su)
    info = {"center_mm": u0, "sigma_mm": su, "edges": [], "blocked": tr["th"] is None}
    if tr["th"] is None:
        return np.zeros_like(coords), info
    lam = pcore.wavelength_A(max(world.energy_actual_keV(), 5.0)) * 1e-7      # mm
    p = abs(coords[1] - coords[0]) if len(coords) > 1 else 1e-3
    prof = g.copy()
    for (zi, Ai, Ei, Bi, lo, hi, name) in tr["aps"]:
        if abs(Ai) < 1e-6 or zi >= zc:
            continue
        e1, e2 = A * (lo - Bi) / Ai + B, A * (hi - Bi) / Ai + B
        a, b = min(e1, e2), max(e1, e2)
        pen = abs(E - A * Ei / Ai) * S                                      # geometric penumbra (sigma, mm) of THIS aperture's edges
        leff = zi * (zc - zi) / zc * 1e3                                    # mm
        k = (zi / zc) * math.sqrt(2.0 / (lam * leff)) if leff > 0 else 1e9
        I = _box_fresnel(coords, a, b, k)
        # partial coherence: the source size washes the fringes out, and the ripple of a real edge decays within a few fringes (log images show 1-2 rim lines)
        fres_px = (math.sqrt(lam * leff / 2.0) * zi / zc) / p                       # Fresnel scale in camera pixels
        vis = max(0.45, math.exp(-0.5 * (pen / p / max(0.5 * fres_px, 1e-6)) ** 2))
        geo = ((coords >= a) & (coords <= b)).astype(float)
        dist = np.minimum(np.abs(coords - a), np.abs(coords - b)) / p
        env = np.exp(-dist / max(4.0 * fres_px, 1.0))
        I = geo + vis * env * (I - geo)
        if pen / p > 0.05:
            I = gaussian_filter1d(I, pen / p, mode="nearest")
        prof = prof * I
        info["edges"].append({"id": name, "lo_mm": a, "hi_mm": b, "penumbra_sigma_mm": pen, "penumbra_px": pen / p,
                              "fresnel_scale_um": 1e3 * math.sqrt(lam * leff / 2.0) * zi / zc * (zc / zi)})
    # which aperture defines each side of the visible footprint: the innermost edge on that side of the beam centre
    if info["edges"]:
        left = max((e for e in info["edges"] if e["lo_mm"] <= u0 + 1e-9), key=lambda e: e["lo_mm"], default=None)
        right = min((e for e in info["edges"] if e["hi_mm"] >= u0 - 1e-9), key=lambda e: e["hi_mm"], default=None)
        info["low_side"] = {"id": left["id"], "edge_mm": left["lo_mm"], "penumbra_px": left["penumbra_px"]} if left else None
        info["high_side"] = {"id": right["id"], "edge_mm": right["hi_mm"], "penumbra_px": right["penumbra_px"]} if right else None
    return prof, info


# ---------------------------------------------------------------------------------------------------------------------------------- pin
def _pin_shadow(world, cam, shape, p, uc, vc, rows_idx, cols_idx):
    """Pin transmission image (1 = clear) and a Fresnel-ripple factor, or None if the pin is not in this hutch."""
    if world.sim["cameras"][cam]["hutch"] != "E":
        return None
    H, W = shape
    sE = world.sim["stage_E"]
    zc = world.z[world.sim["cameras"][cam]["z_key"]]
    zp = world.z["samE"]
    if zc <= zp:
        return None
    ph, pv = world.trace("h", zp), world.trace("v", zp)
    ch, cv = world.trace("h", zc), world.trace("v", zc)
    ps = world.pin_state()
    if abs(ph["A"]) < 1e-6 or abs(pv["A"]) < 1e-6:
        return None
    Mh, Mv = ch["A"] / ph["A"], cv["A"] / pv["A"]
    u_cam = ch["A"] * (ps["u"] - ph["B"]) / ph["A"] + ch["B"]
    v_cam = cv["A"] * (ps["v_top"] - pv["B"]) / pv["A"] + cv["B"]
    xc = (u_cam - uc) / p + (W - 1) / 2.0
    top = (vc - v_cam) / p + (H - 1) / 2.0
    pin = sE["pin"]
    top_w = pin["top_width_um"] * 1e-3 * abs(Mh) / p                         # px
    tan_a = math.tan(math.radians(pin["half_angle_deg"])) * abs(Mh / Mv)
    rows = rows_idx[:, None].astype(np.float32)
    cols = cols_idx[None, :].astype(np.float32)
    dr = np.clip(rows - top, 0, None)
    half = top_w / 2.0 + dr * tan_a
    xcr = xc + (rows - top) * math.tan(ps["tilt_img"])
    edge = 1.2
    base = top + pin["length_mm"] / p * abs(Mv)                              # the cone ends at the pin shaft
    inside = expit((half - np.abs(cols - xcr)) / edge) * expit((rows - top) / edge) * expit((base - rows) / edge)
    T = pin["transmission"]
    trans = 1.0 - (1.0 - T) * inside
    w = ps["omega"]
    if abs(math.sin(math.radians(w))) > 0.8:                                    # half-transparent flank seen at about +-90 deg
        sgn = -1.0 if w < 0 else 1.0
        dist = sgn * (cols - xcr) - half
        wid = dr * 0.28
        wedge = expit(dist / edge) * expit((wid - dist) / edge) * expit((rows - top) / edge)
        trans = 1.0 - (1.0 - trans) * (1.0 - 0.5 * wedge)
    # Fresnel edge ripple (propagation phase contrast): knife edges at the pin sides, only in a band around each edge
    lam = pcore.wavelength_A(max(world.energy_actual_keV(), 5.0)) * 1e-7
    d_pc = (zc - zp) * 1e3
    leff = zp * (zc - zp) / zc * 1e3
    kf = math.sqrt(2.0 / (lam * leff)) * p / abs(Mh) if leff > 0 else 0.0
    ripple = np.zeros((H, W), np.float32)
    r0 = int(max(math.floor(top), 0))
    if r0 < H and kf > 0:
        rr = np.arange(r0, H)
        for side in (-1.0, 1.0):
            xe = xcr[rr, 0] + side * half[rr, 0]
            offs = np.arange(-14, 15)
            cc = np.round(xe)[:, None].astype(int) + offs[None, :]
            ok = (cc >= 0) & (cc < W)
            wv = (cc - xe[:, None]) * kf * (-side)
            s_, c_ = fresnel(wv)
            I = 0.5 * ((c_ + 0.5) ** 2 + (s_ + 0.5) ** 2)                       # opaque half-plane intensity (0 in the shadow, ->1 far out, 1.37 overshoot)
            geom = (wv > 0).astype(float)
            ripple_vals = (I - geom) * 0.55                                    # damped (partial coherence; the thin pin is not fully opaque at its rim)
            rows_b = np.broadcast_to(rr[:, None], cc.shape)
            ripple[rows_b[ok], cc[ok]] += ripple_vals[ok].astype(np.float32)
    return trans, ripple


# ---------------------------------------------------------------------------------------------------------------------------------- render
def render(world, cam, exposure=None, bin_=1, with_noise=True, with_pin=True, return_info=False):
    """Camera frame (uint16) for the current state. bin_ renders a coarser grid (faster previews; pixel size x bin)."""
    sim = world.sim
    cc = sim["cameras"][cam]
    zc, uc, vc, p0, rows, cols = world.camera_view(cam)
    exp = world.ctl(f"{cam}.exposure") if exposure is None else exposure
    H, W = rows // bin_, cols // bin_
    p = p0 * bin_
    u = uc + (np.arange(W) - (W - 1) / 2.0) * p
    v = vc - (np.arange(H) - (H - 1) / 2.0) * p
    s = world.s
    seed = int(s["truth"]["texture_seed"])
    rng = np.random.default_rng(stable_seed(s["seed"], s["n_acq"], cam))
    bg = cc["bg"]
    info = {"camera": cam, "pixel_um": p0 * 1e3, "shape": [rows, cols], "bin": bin_}
    if not world.beam_open(zc):
        img = np.full((H, W), float(bg), np.float32)
        info["state"] = "no beam (shutter closed)"
    else:
        pu, iu = axis_profile(world, "h", cam, u, bin_)
        pv_, iv = axis_profile(world, "v", cam, v, bin_)
        info.update({"h": {k: v_ for k, v_ in iu.items() if k != "edges"}, "v": {k: v_ for k, v_ in iv.items() if k != "edges"},
                     "edges_h": iu["edges"], "edges_v": iv["edges"]})
        # brightness: counts at the centre of the reference beam (WB only, optimal, 200 mA) are cc['full'] at 0.1 s
        sg = world.sigma_theta()
        rho_ref = 1.0 / (2 * math.pi * (zc * 1e3 * sg) ** 2)
        scale = cc["full"] * (exp / 0.1) * world.source_flux() * world.transmission_to(zc) / rho_ref
        sig = (pv_[:, None].astype(np.float32) * pu[None, :].astype(np.float32)) * scale
        def _span(prof, x):                          # full width (mm) over which the aperture-limited profile is above half its maximum
            m = prof > 0.5 * prof.max()
            return float(x[m].max() - x[m].min()) + abs(x[1] - x[0]) if m.any() else None
        wh, wv = _span(pu, u), _span(pv_, v)
        u0, v0 = iu["center_mm"], iv["center_mm"]    # the hot lobe sits on the beam axis (where steering puts it); the apertures only clip it
        sig *= beam_texture(seed, u, v, cc["texture"], u0, v0, wh, wv, cc.get("core", 1.0)).astype(np.float32)
        ripple = None
        if with_pin:
            pin = _pin_shadow(world, cam, (H, W), p, uc, vc, np.arange(H), np.arange(W))
            if pin is not None:
                trans, ripple = pin
                sig *= trans.astype(np.float32)
                sig *= (1.0 + ripple)
        # camera PSF + scintillator-objective defocus (um at the scintillator)
        dfe = abs(world.camera_focus_error_mm(cam))
        sig_px = math.hypot(cc["psf_px"], 70.0 * dfe / (p0 * 1e3)) / bin_
        info["blur_sigma_px"] = sig_px * bin_
        info["focus_error_mm"] = world.camera_focus_error_mm(cam)
        img = gaussian_filter(sig, sig_px, mode="nearest") if sig_px > 0.3 else sig
        dust, hot = camera_maps(cam, seed, rows, cols, cc["dust"])
        if bin_ > 1:
            dust, hot = dust[: H * bin_, : W * bin_].reshape(H, bin_, W, bin_).mean((1, 3)), hot[: H * bin_, : W * bin_].reshape(H, bin_, W, bin_).max((1, 3))
        img = bg + img * dust + hot * (img > 0.0).any()
        info["state"] = "beam" if float(img.max()) > bg * 1.5 else "dark"
    if with_noise:
        img = img + rng.normal(0, 1.0, img.shape) * np.sqrt(np.maximum(img - bg, 0) * 0.6 + 40.0) + rng.normal(0, 6.0, img.shape)
    img = np.clip(img, 0, 65535).astype(np.uint16)
    s["n_acq"] += 1
    return (img, info) if return_info else img


def footprint(world, cam):
    """Where the beam lands in the camera frame: visible fraction of the beam centre, footprint box in px (from the aperture edges), centre px.
    A measurement helper for tools/tests that does NOT render: uses the same ray map. Pixel coordinates (col, row) of the camera frame."""
    zc, uc, vc, p, rows, cols = world.camera_view(cam)
    out = {"camera": cam, "pixel_um": p * 1e3}
    for axis, c0, n, sgn in (("h", uc, cols, +1.0), ("v", vc, rows, -1.0)):
        tr = world.trace(axis, zc)
        if tr["th"] is None:
            return {**out, "visible": False, "reason": "beam blocked by an aperture"}
        th0 = world.steer_rad()[0 if axis == "h" else 1]
        lo, hi = tr["th"]
        e = sorted([tr["A"] * lo + tr["B"], tr["A"] * hi + tr["B"]])
        cen = tr["B"] + tr["A"] * min(max(th0, lo), hi)
        out[axis] = {"lo_px": (e[0] - c0) / p * sgn + (n - 1) / 2.0, "hi_px": (e[1] - c0) / p * sgn + (n - 1) / 2.0,
                     "hotspot_px": (tr["B"] + tr["A"] * th0 - c0) / p * sgn + (n - 1) / 2.0, "n": n}
        out[axis]["lo_px"], out[axis]["hi_px"] = sorted([out[axis]["lo_px"], out[axis]["hi_px"]])
    return out


# ---------------------------------------------------------------------------------------------------------------------------------- PNG output (stdlib)
def png_gray8(a):
    """8-bit grayscale PNG bytes from a 2-D uint8 array (no PIL needed: the GUI stays stdlib + numpy)."""
    h, w = a.shape
    raw = b"".join(b"\x00" + a[i].tobytes() for i in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 4)) + chunk(b"IEND", b"")


def to_u8(img, lo=None, hi=None, gamma=1.0):
    """Display scaling: default window = 1st .. 99.8th percentile of the frame (ImageJ-style auto-contrast). NOT the maximum: a few hot pixels (up to 20 kcounts)
    would set the top of the window and the real beam (a few kcounts above the dark floor) would look dim grey."""
    a = img.astype(np.float32)
    lo = float(np.percentile(a, 1)) if lo is None else lo
    hi = float(np.percentile(a, 99.8)) if hi is None else hi
    hi = max(hi, lo + 600.0)            # never stretch noise: an empty frame stays dark
    return (255 * np.clip((a - lo) / max(hi - lo, 1.0), 0, 1) ** (1.0 / gamma)).astype(np.uint8)
