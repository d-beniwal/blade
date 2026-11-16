"""Compare real tomo-alignment pin frames (HDF5 from the beamline) with the virtual beamline, and fit the pin / camera / footprint parameters of the simulator.  OFFLINE (never imported at runtime).

Same measurement code for a real and a simulated frame (`measure_frame`), so differences are model differences, not analysis differences:
  footprint  box of the lit area (edges at 50 % between the dark floor and the lit level, 10-90 % edge widths), lit level, dark floor
  pin        dark silhouette inside the footprint: tip row, top width, width growth per row (-> half angle), centre column vs row (axis lean), interior transmission, 10-90 % edge width
Per file `load` returns the kept frames, the stage angle of each and the device read-backs of the file mapped to simulator controls through the explicit table
`beamline_twins/<bl>/file_control_map.json` (by device name; nothing is guessed - unmapped devices are listed, not used).

PRIVACY: the repo is public; the files are user data. Only aggregates and fitted parameters are written to the repo; per-frame tables go to the knowledge tree (scratch)."""
import json
from pathlib import Path
import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent.parent


# ----------------------------------------------------------------------------------------------------------------------------------- measuring
def _half_cross(profile, lo, hi, level, pix=1.0):
    """Sub-pixel position where `profile` (1-D) first crosses `level` going from index lo to hi (inclusive, either direction)."""
    step = 1 if hi >= lo else -1
    prev = profile[lo]
    for i in range(lo + step, hi + step, step):
        cur = profile[i]
        if (prev - level) * (cur - level) <= 0 and prev != cur:
            return i - step + step * (level - prev) / (cur - prev)
        prev = cur
    return None


def measure_frame(img, pixel_um=0.69, smooth=3.0):
    """Footprint and pin measurements of one frame (uint16/float 2-D). Returns a dict (pixels unless a name says mm/um); `pin` is None when no pin silhouette is found."""
    a = np.asarray(img, float)
    sm = ndimage.gaussian_filter(a, smooth)
    bg = float(np.percentile(sm, 8))
    top = float(np.percentile(sm, 96))
    m = sm > bg + 0.30 * (top - bg)
    lab, n = ndimage.label(m)
    if n == 0:
        return {"footprint": None, "pin": None, "bg": bg}
    big = lab == (1 + int(np.argmax(ndimage.sum(m, lab, range(1, n + 1)))))
    filled = ndimage.binary_fill_holes(big)
    ys, xs = np.nonzero(filled)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    fp = {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "w_px": x1 - x0 + 1, "h_px": y1 - y0 + 1, "w_mm": (x1 - x0 + 1) * pixel_um * 1e-3, "h_mm": (y1 - y0 + 1) * pixel_um * 1e-3}
    # shadow = filled footprint but dark; the pin = the component touching the bottom edge
    inner = np.zeros_like(filled)
    MARG = 28                                                          # stay clear of the soft edge skirt of the footprint, which would otherwise join the pin's silhouette
    inner[y0 + MARG:y1 - MARG, x0 + MARG:x1 - MARG] = True
    lit_ref = float(np.percentile(sm[filled & ~ndimage.binary_dilation(~big & filled, iterations=1)], 60))
    dark = inner & (sm < bg + 0.40 * (lit_ref - bg))
    lab2, n2 = ndimage.label(dark)
    pin = None
    for k in range(1, n2 + 1):
        comp = lab2 == k
        yy, xx = np.nonzero(comp)
        if yy.size > 2000 and yy.max() >= y1 - MARG - 8:               # a big dark piece reaching the bottom of the analysed interior
            pin = comp
            break
    out = {"footprint": fp, "bg": bg, "lit_p60": lit_ref, "lit_p95": float(np.percentile(sm[filled], 95)), "pin": None}
    # footprint edge widths (10-90 %) from mean profiles across the middle, away from the pin columns
    cols_ok = np.ones(a.shape[1], bool)
    if pin is not None:
        yy, xx = np.nonzero(pin)
        cols_ok[max(xx.min() - 30, 0):xx.max() + 30] = False
    def edge_w(prof, i_out, i_in, lo_f=0.1, hi_f=0.9):
        lvl = prof[i_in - 40:i_in + 40].mean() if i_in > i_out else prof[i_in - 40:i_in + 40].mean()
        base = prof[i_out]
        a10 = _half_cross(prof, i_out, i_in, base + lo_f * (lvl - base))
        a90 = _half_cross(prof, i_out, i_in, base + hi_f * (lvl - base))
        return None if a10 is None or a90 is None else abs(a90 - a10)
    rm = (y0 + y1) // 2
    rowp = ndimage.gaussian_filter1d(a[rm - 40:rm + 40].mean(0), 1.0)
    if pin is not None and yy.min() < rm:
        rowp = ndimage.gaussian_filter1d(a[y0 + 20:y0 + 20 + 40].mean(0), 1.0)          # a row band above the pin tip
    colp = ndimage.gaussian_filter1d(a[:, x1 - 250:x1 - 150].mean(1), 1.0)
    try:
        fp["edge_left_10_90_px"] = edge_w(rowp, max(x0 - 60, 0), x0 + 120)
        fp["edge_right_10_90_px"] = edge_w(rowp, min(x1 + 60, a.shape[1] - 1), x1 - 120)
        fp["edge_top_10_90_px"] = edge_w(colp, max(y0 - 60, 0), y0 + 120)
        fp["edge_bottom_10_90_px"] = edge_w(colp, min(y1 + 60, a.shape[0] - 1), y1 - 120)
    except Exception:
        pass
    if pin is None:
        return out
    yy, xx = np.nonzero(pin)
    r_top, r_bot = int(yy.min()), min(int(yy.max()), y1 - MARG - 2)
    rows = np.arange(r_top, r_bot + 1)
    left, right, cen, wid, T = [], [], [], [], []
    for r in rows:
        line = sm[r]
        cx = np.nonzero(pin[r])[0]
        if cx.size == 0:
            left.append(np.nan); right.append(np.nan); continue
        l0, r0 = cx.min(), cx.max()
        # edges at 50 % between the dark floor inside the pin and the lit level just outside, sub-pixel
        out_l = line[max(l0 - 45, x0 + 5):max(l0 - 15, x0 + 6)]
        out_r = line[min(r0 + 15, x1 - 6):min(r0 + 45, x1 - 5)]
        if out_l.size < 5 or out_r.size < 5:
            left.append(np.nan); right.append(np.nan); continue
        inner_dark = np.median(line[l0 + 15:r0 - 14]) if r0 - l0 > 40 else line[(l0 + r0) // 2]
        lvl_l, lvl_r = np.median(out_l), np.median(out_r)
        xl = _half_cross(line, l0 - 30, l0 + 20, inner_dark + 0.5 * (lvl_l - inner_dark))
        xr = _half_cross(line, r0 + 30, r0 - 20, inner_dark + 0.5 * (lvl_r - inner_dark))
        left.append(np.nan if xl is None else xl); right.append(np.nan if xr is None else xr)
        wid.append((r, inner_dark, 0.5 * (lvl_l + lvl_r)))
    left, right = np.array(left), np.array(right)
    ok = np.isfinite(left) & np.isfinite(right)
    if ok.sum() < 60:
        return out
    r_ok = rows[ok]
    w = right[ok] - left[ok]
    cen = 0.5 * (right[ok] + left[ok])
    sel = (r_ok > r_top + 20) & (r_ok < r_bot - 15)
    p_w = np.polyfit(r_ok[sel], w[sel], 1)                    # width(row) = p_w[0] row + p_w[1]
    p_c = np.polyfit(r_ok[sel], cen[sel], 1)                  # centre(row)
    tip_row = float(r_top)                                    # first dark row of the 40 % mask
    # sub-pixel tip: row where the fitted width extrapolates to the flat-top width seen at the first reliable rows
    top_w = float(np.polyval(p_w, tip_row))
    inner = np.array([x[1] for x in wid]); ref = np.array([x[2] for x in wid])
    rr = np.array([x[0] for x in wid])
    sel2 = (rr > r_top + 60) & (rr < r_bot - 15)
    bgv = out["bg"]
    trans = float(np.median((inner[sel2] - bgv) / np.maximum(ref[sel2] - bgv, 1.0))) if sel2.any() else None
    out["pin"] = {"tip_row": tip_row, "tip_col": float(np.polyval(p_c, tip_row)), "width_slope": float(p_w[0]), "half_angle_deg": float(np.degrees(np.arctan(p_w[0] / 2.0))),
                  "top_width_px": top_w, "top_width_um": top_w * pixel_um, "axis_lean_px_per_row": float(p_c[0]), "centre_col_at_tip": float(np.polyval(p_c, tip_row)),
                  "interior_transmission": trans, "bottom_row": r_bot, "n_rows": int(ok.sum())}
    # 10-90 % width of the pin's two side edges at ~300 rows below the tip (lit level just outside, dark floor inside), mean of left and right
    ew = []
    rr_ = int(min(tip_row + 300, r_bot - 20))
    line_ = ndimage.gaussian_filter1d(a[rr_ - 4:rr_ + 5].mean(0), 0.7)
    if rr_ in r_ok:
        k_ = int(np.nonzero(r_ok == rr_)[0][0])
        xl_, xr_ = left[ok][k_], right[ok][k_]
        dark_ = float(np.median(line_[int(xl_) + 25:int(xr_) - 24]))
        for xe, sgn in ((xl_, -1), (xr_, 1)):
            lit_ = float(np.median(line_[int(xe + sgn * 60):int(xe + sgn * 100)] if sgn > 0 else line_[int(xe - 100):int(xe - 60)]))
            lo_ = _half_cross(line_, int(xe + sgn * -40), int(xe + sgn * 60), dark_ + 0.1 * (lit_ - dark_)) if sgn > 0 else _half_cross(line_, int(xe + 40), int(xe - 60), dark_ + 0.1 * (lit_ - dark_))
            hi_ = _half_cross(line_, int(xe + sgn * -40), int(xe + sgn * 60), dark_ + 0.9 * (lit_ - dark_)) if sgn > 0 else _half_cross(line_, int(xe + 40), int(xe - 60), dark_ + 0.9 * (lit_ - dark_))
            if lo_ is not None and hi_ is not None:
                ew.append(abs(hi_ - lo_))
    out["pin"]["edge_10_90_px"] = float(np.mean(ew)) if ew else None
    out["pin"]["tip_from_footprint_top_px"] = tip_row - y0
    out["pin"]["tip_col_from_footprint_centre_px"] = out["pin"]["tip_col"] - 0.5 * (x0 + x1)
    return out


# ----------------------------------------------------------------------------------------------------------------------------------- the files
def load(path, ry_path=None, mapping=None):
    """-> dict(frames (n,H,W) uint16 ROI, ry (n,), controls {sim control: value}, unmapped [(dataset, value, pv)], meta). `mapping` = file_control_map.json (loaded from the twin)."""
    import h5py
    mapping = mapping or json.loads((ROOT / "beamline_twins" / "1-ID" / "file_control_map.json").read_text())
    with h5py.File(path, "r") as f:
        ry = f[mapping["rotation"]["dataset"]][:]
        frames = f["exchange/data"][:]
        controls, used = {}, set()
        for e in mapping["controls"]:
            if e["dataset"] in f:
                v = float(np.asarray(f[e["dataset"]][()]).ravel()[0])
                controls[e["control"]] = v * e.get("scale", 1.0) + e.get("offset", 0.0)
                used.add(e["dataset"])
        meta = {"roi_offset": [int(x) for x in f["exchange/data"].attrs["NDArrayDimOffset"]], "exposure_s": float(f["instrument/Detector/DetAcqTime"][0]),
                "pixel_um_assumed": 0.69}
    return {"frames": frames, "ry": ry, "controls": controls, "meta": meta}


def mapping():
    return json.loads((ROOT / "beamline_twins" / "1-ID" / "file_control_map.json").read_text())


# ----------------------------------------------------------------------------------------------------------------------------------- the simulator at the file's settings
def sim_world(controls, seed=3):
    """A virtual beamline with every mapped control of the file applied (clipped to the simulator's limits; clipping is reported), lenses parked, camera/pin still at defaults."""
    from blade.vbl.world import VirtualBeamline, control_specs
    w = VirtualBeamline(seed=seed, scenario="aligned")
    sp = control_specs(w.twin)
    clipped = {}
    for k, v in controls.items():
        lo, hi = sp[k][0], sp[k][1]
        vv = v if lo is None else min(max(v, lo), hi)
        if vv != v:
            clipped[k] = (v, vv)
        w.set(k, vv)
    sg = w.sim["slits"]["hsign"]
    for k, v in controls.items():                      # replay assumption: each slit opening is centred on the beam (zero = beam centre - readback)
        sid, what = k.split(".")[0], k.split(".")[-1]
        if what in ("hcenter", "vcenter") and sid in w.s["truth"]["slit_zero"]:
            bu, bv = w.beam_centre(w.z[sid])
            w.s["truth"]["slit_zero"][sid][0 if what == "hcenter" else 1] = (bu - sg * w.ctl(k)) if what == "hcenter" else (bv - w.ctl(k))
    return w, clipped


def _px_to_cam_mm(w, cam, col=None, row=None):
    zc, uc, vc, p, rows, cols = w.camera_view(cam)
    u = None if col is None else uc + (col - (cols - 1) / 2.0) * p
    v = None if row is None else vc - (row - (rows - 1) / 2.0) * p
    return u, v


def place_camera(w, cam, target_cx, target_cy, pixel_um=0.69, iters=4):
    """Move the camera stage (a free parameter: the file does not record it) until the measured footprint centre sits at (target_cx, target_cy) px of the ROI."""
    from blade.vbl import imaging
    sg = w.sim["tomo_stages"]
    st = w.sim["cameras"][cam]["stage"]
    p = pixel_um * 1e-3
    for _ in range(iters):
        img = imaging.render(w, cam, with_noise=False, with_pin=False, bin_=2)
        m = measure_frame(img, pixel_um * 2)
        fp = m["footprint"]
        cx, cy = 0.5 * (fp["x0"] + fp["x1"]) * 2, 0.5 * (fp["y0"] + fp["y1"]) * 2
        du, dv = (cx - target_cx) * p, (cy - target_cy) * p
        w.set(f"{st}.x", w.ctl(f"{st}.x") + du / sg["xsign"])
        w.set(f"{st}.y", w.ctl(f"{st}.y") - dv / sg["ysign"])
    return {"stage_x_mm": w.ctl(f"{st}.x"), "stage_y_mm": w.ctl(f"{st}.y"), "last_shift_px": [cx - target_cx, cy - target_cy]}


def sim_measure(w, cam="gh1", omegas=(0.0,), with_noise=False):
    from blade.vbl import imaging
    out = []
    for om in omegas:
        w.set("samE.ry", float(om))
        img = imaging.render(w, cam, with_noise=with_noise)
        out.append((float(om), measure_frame(img, w.cams[cam]["pixel_um"]), img))
    return out


# ----------------------------------------------------------------------------------------------------------------------------------- pin position: closed loop on the measurements
def fit_sinusoid(om_deg, y):
    """y = c + a cos(w) + b sin(w) (the BLADE convention); returns (c, a, b, rms)."""
    om = np.radians(np.asarray(om_deg, float))
    A = np.stack([np.ones_like(om), np.cos(om), np.sin(om)], 1)
    coef, *_ = np.linalg.lstsq(A, np.asarray(y, float), rcond=None)
    return float(coef[0]), float(coef[1]), float(coef[2]), float(np.sqrt(np.mean((A @ coef - y) ** 2)))


def _scales(w, cam="gh1"):
    """mm at the sample plane per camera pixel (h, v) through the ray map."""
    zc = w.camera_view(cam)[0]
    zp = w.z["samE"]
    ph, pv, ch, cv = w.trace("h", zp), w.trace("v", zp), w.trace("h", zc), w.trace("v", zc)
    p = w.cams[cam]["pixel_um"] * 1e-3
    return (ph["A"] / ch["A"]) * p, (pv["A"] / cv["A"]) * p


def match_pin_position(w, cam, real_cab_px, real_tip_row, omegas=(-90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 180.0), iters=3):
    """Move the simulator's hidden pin truth (axis position c, off-axis offsets a, b, tip height) until the SIMULATED tip column follows the real c + a cos w + b sin w and the
    tip sits on the real row, both measured with `measure_frame` on both sides. Truth parameters only; no beamline control changes. Returns the history."""
    T = w.s["truth"]["pin"]
    hist = []
    sh, sv = _scales(w, cam)
    for it in range(iters + 1):
        rows, cols = [], []
        for om, m, _ in sim_measure(w, cam, omegas):
            if m["pin"] is None:
                continue
            rows.append(m["pin"]["tip_row"]); cols.append((om, m["pin"]["tip_col"]))
        if len(cols) < 4:
            hist.append({"iter": it, "error": "pin not seen in the simulated frames"})
            return hist
        c, a, b, rms = fit_sinusoid([x[0] for x in cols], [x[1] for x in cols])
        row = float(np.mean(rows))
        hist.append({"iter": it, "sim_cab_px": [c, a, b], "sim_tip_row": row, "rms_px": rms})
        if it == iters:
            break
        T["axis_u_mm"] = (T.get("axis_u_mm") if T.get("axis_u_mm") is not None else w.beam_centre(w.z["samE"])[0]) + sh * (real_cab_px[0] - c)
        T["a_mm"] += sh * (real_cab_px[1] - a)
        T["b_mm"] += sh * (real_cab_px[2] - b)
        T["pin_top_v_mm"] += -sv * (real_tip_row - row)
    return hist


def open_loop_pin(w, cam, real_cab_px, real_tip_row):
    """First guess of the pin truth from the real tip position through the ray map (so the pin is in the frame at all before the closed loop refines it)."""
    zc, uc, vc, p, rows, cols = w.camera_view(cam)
    sE = w.sim["stage_E"]
    c = w.s["ctl"]
    zp = w.z["samE"]
    ph, pv, ch, cv = w.trace("h", zp), w.trace("v", zp), w.trace("h", zc), w.trace("v", zc)
    sh, sv = _scales(w, cam)
    T = w.s["truth"]["pin"]
    u0 = ph["B"] + ph["A"] * ((uc + (0 - (cols - 1) / 2.0) * p) - ch["B"]) / ch["A"]            # sample-plane u of column 0
    v0 = pv["B"] + pv["A"] * ((vc - (0 - (rows - 1) / 2.0) * p) - cv["B"]) / cv["A"]
    c_s, a_s, b_s = u0 + sh * real_cab_px[0], sh * real_cab_px[1], sh * real_cab_px[2]
    T["a_mm"] = a_s - sE["col_per_x"] * (c["samE.x"] - sE["x_ref_mm"])
    T["b_mm"] = b_s - sE["k_z"] * (c["samE.z"] - sE["pin_z_ref_mm"])
    T["axis_u_mm"] = c_s - sE["col_per_base"] * (c["samE.aerox"] - sE["aerox_ref_mm"])
    v_target = v0 - sv * real_tip_row
    T["pin_top_v_mm"] = v_target - (-sE["row_per_y"]) * (c["samE.y"] - sE["y_ref_mm"])


# ----------------------------------------------------------------------------------------------------------------------------------- the comparison report
FITS = ROOT / "beamline_twins" / "1-ID" / "physics" / "fits"
PIN_KEYS = ("tip_col", "tip_row", "top_width_um", "half_angle_deg", "interior_transmission", "edge_10_90_px")


def compare_all(data_dir=None, cam="gh1", seed=3):
    """Measure every real frame, render the simulator at the SAME read-backs and the SAME stage angle, and compare. Returns (aggregates [public], per-frame rows [private],
    real frames/sim frames of a few angles [private, for the figure])."""
    from blade import paths
    data_dir = Path(data_dir) if data_dir else paths.knowledge_dir("data") / "tomo_alignment_moving_only"
    files = sorted(data_dir.glob("*/*.h5"))
    if not files:
        raise FileNotFoundError(f"no HDF5 files under {data_dir}")
    real, rows, show = [], [], []
    ctl0 = None
    for fn in files:
        L = load(fn)
        ctl0 = ctl0 or L["controls"]
        for fr, ry in zip(L["frames"], L["ry"]):
            real.append((fn.name, float(ry), measure_frame(fr), fr))
    # real pin geometry: tip column c + a cos w + b sin w, tip row
    pins = [r for r in real if r[2]["pin"]]
    cab = fit_sinusoid([r[1] for r in pins], [r[2]["pin"]["tip_col"] for r in pins])
    row = float(np.mean([r[2]["pin"]["tip_row"] for r in pins]))
    fp = [r[2]["footprint"] for r in real]
    w, clipped = sim_world(ctl0, seed)
    place_camera(w, cam, float(np.mean([0.5 * (f["x0"] + f["x1"]) for f in fp])), float(np.mean([0.5 * (f["y0"] + f["y1"]) for f in fp])))
    open_loop_pin(w, cam, cab[:3], row)
    match_pin_position(w, cam, cab[:3], row)
    for name, ry, mr, fr in real:
        (_, ms, img), = sim_measure(w, cam, (ry,))
        rows.append({"file": name, "omega": ry, "real": mr, "sim": ms})
        if abs(ry - round(ry / 45.0) * 45.0) < 4 and len(show) < 8 and all(abs(ry - s[0]) > 20 for s in show):
            show.append((ry, fr, img))

    def stat(k, kind):
        d = [r["sim"][kind][k] - r["real"][kind][k] for r in rows if r["real"][kind] and r["sim"][kind] and r["real"][kind].get(k) is not None and r["sim"][kind].get(k) is not None]
        return {"n": len(d), "mean": round(float(np.mean(d)), 4), "rms": round(float(np.sqrt(np.mean(np.square(d)))), 4)}
    med = lambda f, kind, k: float(np.median([f(r)[kind][k] for r in rows if f(r)[kind] and f(r)[kind].get(k) is not None]))
    agg = {"built": "2026-11-15", "n_frames": len(rows), "n_files": len(files), "camera": cam, "ray_map_note": "frames: 1940 x 1490 ROI of GH1 at 0.69 um/px, 71.676 keV, 0.1 s",
           "real_pin_tip_column_px": {"c": round(cab[0], 2), "a": round(cab[1], 2), "b": round(cab[2], 2), "rms_about_fit_px": round(cab[3], 2)}, "real_tip_row_px": round(row, 2),
           "sim_minus_real_pin": {k: stat(k, "pin") for k in PIN_KEYS},
           "footprint_median": {k: {"real": round(med(lambda r: r["real"], "footprint", k), 2), "sim": round(med(lambda r: r["sim"], "footprint", k), 2)}
                                for k in ("w_px", "h_px", "edge_left_10_90_px", "edge_right_10_90_px", "edge_top_10_90_px", "edge_bottom_10_90_px")},
           "levels_median": {k: {"real": round(float(np.median([r["real"][k] for r in rows])), 1), "sim": round(float(np.median([r["sim"][k] for r in rows])), 1)} for k in ("bg", "lit_p60", "lit_p95")},
           "pin_median": {k: {"real": round(med(lambda r: r["real"], "pin", k), 3), "sim": round(med(lambda r: r["sim"], "pin", k), 3)} for k in ("top_width_um", "half_angle_deg", "interior_transmission", "edge_10_90_px", "tip_from_footprint_top_px")},
           "clipped_controls": clipped,
           "controls_used": {k: round(float(v), 6) for k, v in ctl0.items()},
           "footprint_centre_px": [round(float(np.mean([0.5 * (f["x0"] + f["x1"]) for f in fp])), 1), round(float(np.mean([0.5 * (f["y0"] + f["y1"]) for f in fp])), 1)]}
    return agg, rows, show


def write_report(agg, rows, show, scratch):
    """Aggregates -> repo (fits/pin_frames.json); per-frame table + figure -> the knowledge tree (user data)."""
    FITS.mkdir(parents=True, exist_ok=True)
    (FITS / "pin_frames.json").write_text(json.dumps(agg, indent=1))
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "pin_frames_rows.json").write_text(json.dumps(rows, default=float))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(2, len(show), figsize=(2.6 * len(show), 4.6))
    for j, (om, fr, img) in enumerate(sorted(show, key=lambda s: s[0])):
        lo, hi = np.percentile(fr, 1), np.percentile(fr, 99.7)
        for i, im_ in enumerate((fr, img)):
            ax[i, j].imshow(np.asarray(im_, float), cmap="gray", vmin=lo, vmax=hi)
            ax[i, j].set_xticks([]); ax[i, j].set_yticks([])
        ax[0, j].set_title(f"omega = {om:.0f}", fontsize=7)
    ax[0, 0].set_ylabel("real", fontsize=8); ax[1, 0].set_ylabel("simulated", fontsize=8)
    fig.savefig(scratch / "real_vs_sim_frames.png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return scratch


if __name__ == "__main__":
    from blade import paths
    agg, rows, show = compare_all()
    out = write_report(agg, rows, show, paths.knowledge_dir("scratch") / "pin_compare")
    print(json.dumps(agg, indent=1))
    print("private outputs:", out)
