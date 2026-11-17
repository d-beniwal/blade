"""Pin REGION detector (stage 1 of the pin workflow, playbooks/pin_workflow_v2.md): where is the tomo pin in a camera frame?

The pin is the only thing in these frames bounded by two LONG STRAIGHT edges that lean ~15 deg from vertical and converge upward, with a short flat top between them. Dark
margins, window edges and beam mottle have vertical / horizontal / short edges, so they cannot vote for such a pair.
 1. stage 1 (on a 200-px copy): edge map of log-intensity -> Hough accumulation of slanted lines -> candidate left/right flank lines -> best pair (edge support along both flanks,
    interior darker than the strips outside, flat top) or ONE flank + mirrored lean when the other is hidden / off the image;
 2. refine (full resolution): both flanks re-fitted to the actual edge pixels (coarse-to-fine window, robust line), visible extent = rows with edge evidence, top = topmost
    dark-below step along the axis;
 3. field of view: the lit window measured per row beside the pin; the polygon is clipped to it.
Entry point `find_pin_region_final(g)`; pure numpy/scipy/PIL, no instrument imports. Validated on 25 knowledge-base images and 85 real raw frames (scratch/pin_region, 2026-11-16)."""
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

LONGEST = 200               # stage-1 working resolution (long side, px): 3.9x faster than 400 with the same result on all but one image (scratch/pin_region/bench2.out); refinement + FoV run at full resolution
HOUGH_TOL = 0.20         # orientation tolerance of a vote: |cos(angle between edge normal and line direction)| scale; 0.30 ~ 17 deg
SUPPORT_TOL = 0.30       # same, for counting support along a line
SLOPES = np.concatenate([np.linspace(-0.5, -0.09, 42), np.linspace(0.09, 0.5, 42)])     # dx per row; < 0: left flank (moves left going down), > 0: right flank


def _small(g, longest=None):
    longest = longest or LONGEST
    h, w = g.shape
    s = longest / max(h, w)
    if s >= 1:
        return g.astype(np.float64), 1.0
    im = Image.fromarray(g.astype(np.float32), mode="F").resize((max(8, round(w * s)), max(8, round(h * s))), Image.BOX)
    return np.asarray(im, np.float64), s


def edge_field(gs):
    p97 = max(np.percentile(gs, 97), 1e-6)
    L = np.log(ndi.gaussian_filter(gs, 1.2) + 0.03 * p97)
    gx, gy = ndi.sobel(L, axis=1) / 8.0, ndi.sobel(L, axis=0) / 8.0
    return gx, gy, np.hypot(gx, gy)


def hough(gx, gy, mag, thr):
    """acc[slope index, x0] for lines x = x0 + s * y; votes = edge magnitude * orientation agreement."""
    H, W = mag.shape
    ys, xs = np.nonzero(mag > thr)
    m = mag[ys, xs]
    gxs, gys = gx[ys, xs], gy[ys, xs]
    nb = W + 2 * H                                              # x0 range (lines may start far outside)
    acc = np.zeros((len(SLOPES), nb))
    for k, s in enumerate(SLOPES):
        # line direction (s, 1); gradient must be perpendicular: g . (s,1) = gx*s + gy ~ 0
        cosang = np.abs(gxs * s + gys) / (np.hypot(gxs, gys) * np.sqrt(1 + s * s) + 1e-12)
        w = np.sqrt(m) * np.exp(-(cosang / HOUGH_TOL) ** 2)             # sqrt: a long weak edge (dim pin) counts against a short strong one (window frame)
        x0 = np.round(xs - s * ys).astype(int) + H
        np.add.at(acc[k], np.clip(x0, 0, nb - 1), w)
    acc = ndi.gaussian_filter1d(acc, 1.0, axis=1)
    return acc, H


def peaks(acc, off, n=14, side=None):
    a = acc.copy()
    if side == "L":
        a[SLOPES > 0] = 0
    elif side == "R":
        a[SLOPES < 0] = 0
    out = []
    for _ in range(n):
        k, x = np.unravel_index(np.argmax(a), a.shape)
        v = a[k, x]
        if v <= 0:
            break
        out.append((float(v), float(SLOPES[k]), float(x - off)))
        a[max(k - 3, 0):k + 4, max(x - 6, 0):x + 7] = 0
    return out


def line_support(gx, gy, mag, thr, s, x0, y0, y1):
    """Fraction of rows in [y0, y1] where an edge pixel with the line's orientation lies within 1.5 px of the line (and its mean magnitude)."""
    H, W = mag.shape
    ys = np.arange(int(max(y0, 0)), int(min(y1, H - 1)) + 1)
    if len(ys) == 0:
        return 0.0, 0.0
    xl = x0 + s * ys
    ok = (xl >= 2) & (xl <= W - 3)
    hit = np.zeros(len(ys), bool)
    mm = np.zeros(len(ys))
    for dx in (-1, 0, 1):
        xi = np.clip(np.round(xl + dx).astype(int), 0, W - 1)
        c = np.abs(gx[ys, xi] * s + gy[ys, xi]) / (np.hypot(gx[ys, xi], gy[ys, xi]) * np.sqrt(1 + s * s) + 1e-12)
        good = (mag[ys, xi] > thr) & (c < SUPPORT_TOL) & ok
        hit |= good
        mm = np.maximum(mm, np.where(good, mag[ys, xi], 0))
    n = ok.sum()
    return (hit.sum() / max(n, 1)), float(mm.sum() / max(n, 1))


def _strip_contrast(gs, s_l, x0l, s_r, x0r, y0, y1, bw=4, eps=None):
    """Mean contrast (outside - inside)/(outside + inside) of 4-px strips either side of both flanks over rows y0..y1; a strip is skipped if it leaves the image."""
    H, W = gs.shape
    ys = np.arange(int(max(y0, 0)), int(min(y1, H - 1)) + 1)
    if len(ys) == 0:
        return 0.0
    if eps is None:
        eps = 0.03 * max(np.percentile(gs, 97), 1e-6)
    xl, xr = x0l + s_l * ys, x0r + s_r * ys
    out = []
    for xe, inner in ((xl, +1), (xr, -1)):
        xin = np.clip(np.round(xe + inner * (2 + bw / 2)).astype(int), 0, W - 1)
        xot = np.clip(np.round(xe - inner * (2 + bw / 2)).astype(int), 0, W - 1)
        ok = (xe - inner * (2 + bw) >= 0) & (xe - inner * (2 + bw) <= W - 1) & (xe + inner * (2 + bw) >= 0) & (xe + inner * (2 + bw) <= W - 1)
        a, b = gs[ys, xin], gs[ys, xot]
        c = (b - a) / (a + b + eps)
        out.append(np.where(ok, c, np.nan))
    both = np.nanmean(np.vstack(out), axis=0) if len(out) else np.array([0.0])
    return float(np.nanmean(both)) if np.isfinite(both).any() else 0.0


def find_pin_region_edges(g, verbose=False, longest=None):
    gs, sc = _small(g, longest or LONGEST)
    H, W = gs.shape
    gx, gy, mag = edge_field(gs)
    m2 = mag.copy()
    m2[:3], m2[-3:], m2[:, :3], m2[:, -3:] = 0, 0, 0, 0
    thr = max(np.percentile(m2, 82), 0.015)
    acc, off = hough(gx, gy, m2, thr)
    Ls, Rs = peaks(acc, off, 20, "L"), peaks(acc, off, 20, "R")
    best = (0.0, None)
    eps = 0.03 * max(np.percentile(gs, 97), 1e-6)                    # constant per image (was recomputed for every candidate)
    rows = np.arange(H)
    y1 = H - 1
    yts = np.arange(0, 0.75 * H, 3.0)                                 # candidate top rows
    P = np.concatenate([np.zeros((H, 1)), np.cumsum(np.abs(gy), axis=1)], axis=1)     # row-wise prefix sums of |gy| (flat-top edge energy)
    line_cache = {}

    def line_cum(s_, x0_):
        """cumulative (over rows) counts of in-image rows and of rows with a matching edge pixel for the line x = x0 + s*y, so line_support over any row range is O(1)"""
        key = (s_, x0_)
        if key not in line_cache:
            xl_ = x0_ + s_ * rows
            ok = (xl_ >= 2) & (xl_ <= W - 3)
            hit = np.zeros(H, bool)
            for dx in (-1, 0, 1):
                xi = np.clip(np.round(xl_ + dx).astype(int), 0, W - 1)
                c = np.abs(gx[rows, xi] * s_ + gy[rows, xi]) / (np.hypot(gx[rows, xi], gy[rows, xi]) * np.sqrt(1 + s_ * s_) + 1e-12)
                hit |= (m2[rows, xi] > thr) & (c < SUPPORT_TOL) & ok
            line_cache[key] = (np.concatenate([[0], np.cumsum(ok)]), np.concatenate([[0], np.cumsum(hit)]))
        return line_cache[key]

    def row_contrast(sl_, xl0_, sr_, xr0_, bw=4):
        """per-row mean of the left/right strip contrasts (nan where neither strip is inside the image): the per-row part of _strip_contrast"""
        out = []
        for xe, inner in ((xl0_ + sl_ * rows, +1), (xr0_ + sr_ * rows, -1)):
            xin = np.clip(np.round(xe + inner * (2 + bw / 2)).astype(int), 0, W - 1)
            xot = np.clip(np.round(xe - inner * (2 + bw / 2)).astype(int), 0, W - 1)
            ok = (xe - inner * (2 + bw) >= 0) & (xe - inner * (2 + bw) <= W - 1) & (xe + inner * (2 + bw) >= 0) & (xe + inner * (2 + bw) <= W - 1)
            a_, b_ = gs[rows, xin], gs[rows, xot]
            out.append(np.where(ok, (b_ - a_) / (a_ + b_ + eps), np.nan))
        v = np.nanmean(np.vstack(out), axis=0)
        fin = np.isfinite(v)
        return np.concatenate([[0.0], np.cumsum(np.where(fin, v, 0.0))]), np.concatenate([[0], np.cumsum(fin)])

    for vl, sl, xl0 in Ls:
        for vr, sr, xr0 in Rs:
            if abs(sl + sr) > 0.08 or min(abs(sl), abs(sr)) < 0.115:        # a pin's flanks mirror each other and lean >= ~6.5 deg
                continue
            w = (xr0 + sr * yts) - (xl0 + sl * yts)
            valid = (w >= 0.02 * W) & (w <= 0.3 * W)
            if not valid.any():
                continue
            yv = yts[valid]
            a0 = np.floor(yv + 0.1 * (y1 - yv)).astype(int)                 # first row of the support range
            # both flanks inside the image on >= 80 % of the rows below the top (a clipped pin takes the one-flank path)
            inb = np.concatenate([[0], np.cumsum(((xl0 + sl * rows) >= 2) & ((xr0 + sr * rows) <= W - 3))])
            keep = (inb[H] - inb[a0]) / (H - a0) >= 0.8
            if not keep.any():
                continue
            yv, a0 = yv[keep], a0[keep]
            okL, hitL = line_cum(sl, xl0)
            okR, hitR = line_cum(sr, xr0)
            fl = (hitL[H] - hitL[a0]) / np.maximum(okL[H] - okL[a0], 1)
            fr = (hitR[H] - hitR[a0]) / np.maximum(okR[H] - okR[a0], 1)
            # flat top: horizontal edge energy along the top segment (mean over 5 rows)
            lo_ = np.maximum(np.trunc(xl0 + sl * yv).astype(int) + 2, 0)
            hi_ = np.minimum(np.trunc(xr0 + sr * yv).astype(int) - 1, W)
            n_ = hi_ - lo_
            r0 = np.round(yv).astype(int)
            e_ = np.zeros(len(yv))
            for d in (-2, -1, 0, 1, 2):
                rr = np.clip(r0 + d, 0, H - 1)
                e_ += (P[rr, np.maximum(hi_, lo_)] - P[rr, lo_]) / np.maximum(n_, 1)
            topE = np.where(n_ >= 4, e_ / 5.0 / max(thr, 1e-6), 0.0)
            # strip contrast below the top: suffix mean of the per-row contrasts from row int(yt + 6)
            cs, cn = row_contrast(sl, xl0, sr, xr0)
            c0 = np.floor(yv + 6).astype(int)
            inr = c0 <= H - 1
            c0c = np.minimum(c0, H)
            cnt = cn[H] - cn[c0c]
            con = np.where(inr & (cnt > 0), (cs[H] - cs[c0c]) / np.maximum(cnt, 1), 0.0)
            score = 0.3 * fl + 0.3 * fr + 0.15 * np.minimum(topE / 2.0, 1.0) + 0.25 * np.minimum(np.maximum(con, 0) / 0.3, 1.0)
            score = score * np.minimum(1.0, (y1 - yv) / (0.25 * H))
            k = int(np.argmax(score))
            if score[k] > best[0]:
                best = (float(score[k]), dict(sl=sl, xl0=xl0, sr=sr, xr0=xr0, y_top=float(yv[k]), fl=float(fl[k]), fr=float(fr[k]), topE=float(topE[k]), con=float(con[k])))

    # one visible flank (the other is hidden against a margin, or off the image): corner row from where the flank's edge support starts, top width from the flat top's edge run,
    # other flank = mirrored lean
    for side, peaklist in (("L", Ls), ("R", Rs)):
        for v, s_, x0_ in peaklist[:10]:
            ys_all = np.arange(0, H - 1)
            xl_ = x0_ + s_ * ys_all
            inb = (xl_ >= 3) & (xl_ <= W - 4)
            hit = np.zeros(len(ys_all), bool)
            for dx in (-1, 0, 1):
                xi = np.clip(np.round(xl_ + dx).astype(int), 0, W - 1)
                c = np.abs(gx[ys_all, xi] * s_ + gy[ys_all, xi]) / (np.hypot(gx[ys_all, xi], gy[ys_all, xi]) * np.sqrt(1 + s_ * s_) + 1e-12)
                hit |= (m2[ys_all, xi] > thr) & (c < SUPPORT_TOL) & inb
            hit = ndi.binary_closing(hit, np.ones(7))
            lab, n = ndi.label(hit)
            if n == 0:
                continue
            sizes = ndi.sum(hit, lab, range(1, n + 1))
            run = np.flatnonzero(lab == 1 + int(np.argmax(sizes)))
            y_top, y_end = float(run[0]), float(run[-1])
            if y_end - y_top < SINGLE_MIN_RUN * H or y_end < 0.55 * H:
                continue
            xc = x0_ + s_ * y_top                                   # corner column
            r = int(round(y_top))
            rowE = np.mean([np.abs(gy[min(max(r + d, 0), H - 1)]) for d in (-2, -1, 0, 1, 2)], axis=0)
            step = 1 if side == "L" else -1
            run_len = 0
            x = int(round(xc)) + 3 * step
            lowc = 0
            while 3 <= x <= W - 4 and run_len < 0.32 * W:
                if rowE[x] > 0.6 * thr:
                    lowc = 0
                else:
                    lowc += 1
                    if lowc > 4:
                        break
                run_len += 1
                x += step
            run_len = max(run_len - lowc, 0) + 3
            clipped = not (3 <= x <= W - 4)                          # the top runs off the image: top width unknown
            wtop = max(run_len, 0.03 * W)
            if side == "L":
                xl0, sl, xr0, sr = x0_, s_, x0_ + wtop + (s_ - (-s_)) * 0 - (-s_) * 0, -s_
                xr0 = (xc + wtop) - sr * y_top
            else:
                xr0, sr = x0_, s_
                sl = -s_
                xl0 = (xc - wtop) - sl * y_top
            ya = y_top + 0.1 * (H - 1 - y_top)
            f1, _ = line_support(gx, gy, m2, thr, s_, x0_, ya, H - 1)
            con = _strip_contrast(gs, sl, xl0, sr, xr0, y_top + 6, H - 1, eps=eps)
            topE = float(rowE[int(max(min(xc + step * run_len / 2, W - 1), 0))] / max(thr, 1e-6))
            score = 0.85 * (0.45 * f1 + 0.2 * min(topE / 2.0, 1.0) + 0.35 * min(max(con, 0) / 0.3, 1.0)) * min(1.0, (H - 1 - y_top) / (0.25 * H))
            if score > best[0]:
                best = (score, dict(sl=sl, xl0=xl0, sr=sr, xr0=xr0, y_top=y_top, fl=f1 if side == "L" else -1, fr=f1 if side == "R" else -1, topE=topE, con=con, one_sided=side, top_clipped=clipped))
    score, b = best
    out = {"score": score, "params": b, "scale": sc, "gs_shape": (H, W)}
    if b is None:
        out["found"] = False
        out["polygon"] = None
        return out
    inv = 1 / sc
    yt, y1 = b["y_top"], H - 1
    xl_t, xr_t = b["xl0"] + b["sl"] * yt, b["xr0"] + b["sr"] * yt
    xl_b, xr_b = b["xl0"] + b["sl"] * y1, b["xr0"] + b["sr"] * y1
    out["polygon"] = [(xl_t * inv, yt * inv), (xr_t * inv, yt * inv), (xr_b * inv, y1 * inv), (xl_b * inv, y1 * inv)]
    out["found"] = score >= 0.45
    return out


# ----------------------------------------------------------------------------------------------------------------------------------------------- full-resolution refinement
from scipy.stats import theilslopes


def _flank_points(dx, strength_floor, xline, rows, w):
    """Per row: position of the strongest horizontal intensity step within +-w px of the predicted flank (sub-pixel), and its strength."""
    H, W = dx.shape
    pos = np.full(len(rows), np.nan)
    st = np.zeros(len(rows))
    for k, y in enumerate(rows):
        xc = xline(y)
        a, b = int(round(xc - w)), int(round(xc + w)) + 1
        if a < 2 or b > W - 2:
            continue
        seg = np.abs(dx[int(y), a:b])
        j = int(np.argmax(seg))
        if 0 < j < len(seg) - 1:                                   # parabola through the peak for sub-pixel position
            d = seg[j - 1] - 2 * seg[j] + seg[j + 1]
            off = 0.5 * (seg[j - 1] - seg[j + 1]) / d if abs(d) > 1e-12 else 0.0
        else:
            off = 0.0
        pos[k], st[k] = a + j + off, seg[j]
    return pos, st


def _fit_line(rows, pos, trim=2.5):
    """Robust line pos = sl * row + ic: repeated-median (Siegel) start, then inliers re-selected with a shrinking band (wide -> `trim`) so a first estimate that is off by a few
    percent in slope cannot strand the true edge outside the inlier band."""
    from scipy.stats import siegelslopes
    ok = np.isfinite(pos)
    for band in (4 * trim, 2 * trim, trim, trim):
        if ok.sum() < 12:
            return None
        sl, ic = siegelslopes(pos[ok], rows[ok])
        res = pos - (sl * rows + ic)
        ok = np.isfinite(pos) & (np.abs(res) < band)
    return float(sl), float(ic), ok


def refine_region(g, res):
    """Re-fit both flanks to the edge pixels at full resolution, take the visible extent from where edge evidence exists (the pin is not drawn into the dark beyond the field of view
    or above where its edges start), and place the top on the steepest dark-below step along the axis."""
    if res.get("polygon") is None:
        return res
    (xlt, yt), (xrt, _), (xrb, y1), (xlb, _) = res["polygon"]
    H0, W0 = g.shape
    p97 = max(np.percentile(g, 97), 1e-6)
    sig = max(1.5, 0.0012 * max(H0, W0))
    Lg = np.log(ndi.gaussian_filter(g.astype(np.float64), sig) + 0.03 * p97)
    dx = np.gradient(Lg, axis=1)
    rows = np.arange(int(max(yt - 0.03 * H0, 0)), int(min(y1, H0 - 1)) + 1, 2)
    L0 = lambda y: xlt + (xlb - xlt) * (y - yt) / max(y1 - yt, 1)
    R0 = lambda y: xrt + (xrb - xrt) * (y - yt) / max(y1 - yt, 1)
    w = max(8.0, 0.012 * W0)
    fits, strong, stats = {}, {}, {}

    def search(line, schedule):
        """iterated flank search (window re-centred on the improved line each time); returns (slope, intercept, inlier mask, rms, n points) of the last successful fit, or None"""
        packed = None
        for wf in schedule:
            pos, st = _flank_points(dx, 0, line, rows, max(8.0, wf * w))
            good = np.isfinite(pos)
            if good.sum() < 12:
                return packed
            floor = 0.5 * np.percentile(st[good], 70)
            pos2 = np.where(st > floor, pos, np.nan)
            f = _fit_line(rows.astype(float), pos2, trim=max(3.0, 0.004 * W0))     # edge blur / lean make the position wobble by a few px at full resolution
            if f is None:
                return packed
            sl_, ic_, okf = f
            resid = (pos2 - (sl_ * rows + ic_))[okf]
            packed = (sl_, ic_, okf, float(np.sqrt(np.mean(resid ** 2))) if resid.size else 99.0, int(good.sum()))
            line = (lambda y, sl_=sl_, ic_=ic_: sl_ * y + ic_)
        return packed

    for name, line in (("L", L0), ("R", R0)):
        f = search(line, (1.0, 1.0, 1.0))                           # narrow window: right whenever stage 1 sits on the edge
        if not (res.get("params") or {}).get("one_sided"):          # two real flanks: also try coarse-to-fine - a downscaled stage-1 line can be tens of px off at the top -
            fw = search(line, (4.0, 2.0, 1.0))                      # and keep it only if it collects clearly more consistent edge points (a one-flank pin's wide window latches onto margins)
            if fw is not None and (f is None or fw[2].sum() > 1.15 * f[2].sum()):
                f = fw
        if f is None:
            continue
        sl, ic, ok = f[:3]
        if abs(sl) < MIN_FLANK_LEAN:                                 # drifted onto a near-vertical edge (the lit window's own side): not a pin flank
            continue
        fits[name] = (sl, ic)
        strong[name] = ok
        stats[name] = dict(n_inliers=int(ok.sum()), n_rows=int(len(rows)), rms_px=f[3], rows=(float(rows[np.flatnonzero(ok)[0]]), float(rows[np.flatnonzero(ok)[-1]])) if ok.any() else None)
    if not fits:
        return res
    # rows with edge evidence on at least one flank: the longest run (gaps <= 14 rows) is the visible pin
    ev = np.zeros(len(rows), bool)
    for ok in strong.values():
        ev |= ok
    ev = ndi.binary_closing(np.concatenate([[False], ev, [False]]), np.ones(8))[1:-1]
    lab, n = ndi.label(ev)
    if n == 0:
        return res
    sizes = ndi.sum(ev, lab, range(1, n + 1))
    idx = np.flatnonzero(lab == 1 + int(np.argmax(sizes)))
    y_top, y_bot = float(rows[idx[0]]), float(rows[idx[-1]])
    # a flank that has no usable edge keeps the mirrored/previous line
    if "L" not in fits:
        fits["L"] = ((xlb - xlt) / max(y1 - yt, 1), xlt - (xlb - xlt) / max(y1 - yt, 1) * yt)
    if "R" not in fits:
        fits["R"] = ((xrb - xrt) / max(y1 - yt, 1), xrt - (xrb - xrt) / max(y1 - yt, 1) * yt)
    (sl, il), (sr, ir) = fits["L"], fits["R"]
    # top: the topmost clear dark-below step along the axis columns (middle 50 % of the pin width) from 6 % of the height above the first evidence row to a few px below it.
    # The pin may carry a darker cap above where its flank edges start; the lit window's own top edge is bright-below and is never a candidate.
    yy = np.arange(int(max(y_top - 0.06 * H0, 1)), int(min(y_top + 6, H0 - 2)))
    if len(yy) > 6:
        def cols(y):
            a_, b_ = sl * y + il, sr * y + ir
            return slice(int(max(a_ + 0.25 * (b_ - a_), 0)), int(min(a_ + 0.75 * (b_ - a_), W0 - 1)) + 1)
        prof = np.array([Lg[y, cols(y)].mean() if cols(y).stop > cols(y).start else np.nan for y in yy])
        if np.isfinite(prof).all():
            d = np.gradient(ndi.gaussian_filter1d(prof, 1.5))
            strong_ = np.flatnonzero(d < -0.5 * np.abs(d).max())
            if len(strong_) and d.min() < 0:
                y_top = float(yy[strong_[0]])
    out = dict(res)
    out["polygon"] = [(sl * y_top + il, y_top), (sr * y_top + ir, y_top), (sr * y_bot + ir, y_bot), (sl * y_bot + il, y_bot)]
    out["refined"] = dict(flanks=list(fits), y_top=y_top, y_bottom=y_bot, lines={"L": (sl, il), "R": (sr, ir)}, stats=stats, found_by_data={k: (k in strong) for k in ("L", "R")})
    return out


# ----------------------------------------------------------------------------------------------------------------------------------------------------- field of view
def fov_box(g, poly=None, level=None):
    """Lit window of the camera (what the camera can actually see) as a box (x0, y0, x1, y1, crop px).
    Lit = clearly above the dark floor (floor = median of the darkest 5 %; threshold a few noise widths / 4 % of the beam above it, far below any dim beam, so vignetted or dim windows
    stay whole and only the true black surround is excluded). Outer border residue of the snapshot is ignored.
    The pin is dark and covers part of the window, so sides are measured PER ROW on the parts of the row next to the pin: left of the pin the first lit pixel is the window's left edge,
    right of the pin the last lit pixel is its right edge. A row where nothing lit lies on that side of the pin (the pin crosses or hides the window edge there) says nothing; if no row
    measures a side, that side is not clipped (an image whose beam fills the frame, or a pin against the frame edge, has no measurable margin)."""
    gs, s = _small(g, 320)
    sm = ndi.gaussian_filter(gs, 1.5)
    lo = sm[sm <= np.percentile(sm, 5)]
    floor = float(np.median(lo))
    noise = 1.4826 * float(np.median(np.abs(lo - floor)))
    beam = float(np.percentile(sm, 97))
    thr = floor + max(6 * noise, (FOV_LEVEL if level is None else level) * (beam - floor), 1e-6)
    lit = ndi.binary_closing(sm > thr, np.ones((5, 5)))
    H, W = lit.shape
    m = max(3, int(0.012 * max(H, W)))
    lit[:m], lit[-m:], lit[:, :m], lit[:, -m:] = False, False, False, False
    inv = 1.0 / s

    def peel(cov):
        lo_, hi_ = 0, len(cov)
        while lo_ < 6 and cov[lo_] == 0:
            lo_ += 1
        while hi_ > len(cov) - 6 and cov[hi_ - 1] == 0:
            hi_ -= 1
        while lo_ < 20 and cov[lo_] >= 0.9 and (cov[lo_ + 1:lo_ + 14] < 0.5 * cov[lo_]).any():
            lo_ += 1
        while hi_ > len(cov) - 20 and cov[hi_ - 1] >= 0.9 and (cov[hi_ - 14:hi_ - 1] < 0.5 * cov[hi_ - 1]).any():
            hi_ -= 1
        out = cov.copy()
        out[:lo_], out[hi_:] = 0, 0
        return out

    def main_run(cov):
        ok = ndi.binary_closing(np.concatenate([[False], cov >= max(0.4 * cov.max(), 0.05), [False]]), np.ones(9))[1:-1]
        lab, n = ndi.label(ok)
        if n == 0:
            return np.array([], int)
        sizes = ndi.sum(ok, lab, range(1, n + 1))
        return np.flatnonzero(lab == 1 + int(np.argmax(sizes)))

    # --- left / right: per row, next to the pin
    x0, x1 = 0.0, float(W)
    if poly is not None:
        (xlt, yt), (xrt, _), (xrb, yb), (xlb, _) = [(p[0] * s, p[1] * s) for p in poly[:4]] if len(poly) == 4 else [(p[0] * s, p[1] * s) for p in poly[:4]]
        lefts, rights = [], []
        cov_r = lit.mean(1)
        rr_ = np.flatnonzero(cov_r >= 0.3 * cov_r.max())
        r0, r1 = (int(rr_[0]), int(rr_[-1])) if len(rr_) else (m, H - m)
        hh = max(r1 - r0, 1)
        for y in range(max(m, r0 + int(RIM_FRAC * hh)), min(H - m, r1 - int(RIM_FRAC * hh)), 2):     # clean rows only: the window's top / bottom rim rows fade and scatter their extents
            row = lit[y]
            if yt <= y <= yb:                                          # rows crossed by the pin: only the parts of the row BESIDE the pin say where the window ends
                f = (y - yt) / max(yb - yt, 1)
                xl, xr = xlt + (xlb - xlt) * f, xrt + (xrb - xrt) * f
                if xl > 0.04 * W:
                    seg = row[m:int(xl) - 3]
                    if seg.any():
                        lefts.append(m + int(np.argmax(seg)))
                if xr < 0.96 * W:
                    seg = row[int(xr) + 3:W - m]
                    if seg.any():
                        rights.append(int(xr) + 3 + int(len(seg) - 1 - np.argmax(seg[::-1])))
            else:                                                     # rows above / below the pin: the whole row is clean, so a pin sitting AT a window edge still leaves that edge measurable
                seg = row[m:W - m]
                if seg.any():
                    lefts.append(m + int(np.argmax(seg)))
                    rights.append(m + int(len(seg) - 1 - np.argmax(seg[::-1])))
        if len(lefts) >= MIN_EDGE_ROWS:
            x0 = float(np.percentile(lefts, 25))                      # extents only shrink on fading rows: favour the outer edge
        if len(rights) >= MIN_EDGE_ROWS:
            x1 = float(np.percentile(rights, 75)) + 1
    else:
        cols = main_run(peel(lit.mean(0)))
        if len(cols) >= 4:
            x0, x1 = float(cols[0]), float(cols[-1] + 1)
    # a side that is measured as 'window starts at the very edge' is simply no clip
    x0 = 0.0 if x0 <= m + 1 else x0
    x1 = float(W) if x1 >= W - m - 1 else x1
    # --- top / bottom: columns beside the pin
    csel = np.ones(W, bool)
    if poly is not None:
        px = [p[0] * s for p in poly]
        csel[int(max(min(px) - 0.05 * W, 0)):int(min(max(px) + 0.05 * W, W))] = False
        if csel.sum() < 0.15 * W:
            csel[:] = True
    rows_ = main_run(peel(lit[:, csel].mean(1)))
    y0, y1 = (float(rows_[0]), float(rows_[-1] + 1)) if len(rows_) >= 4 else (0.0, float(H))
    y0 = 0.0 if y0 <= m + 1 else y0
    y1 = float(H) if y1 >= H - m - 1 else y1
    return (x0 * inv, y0 * inv, x1 * inv, y1 * inv)


def clip_polygon(poly, box):
    """Sutherland-Hodgman clip of a polygon to an axis-aligned box."""
    x0, y0, x1, y1 = box
    def clip(pts, inside, inter):
        out = []
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            ip, iq = inside(p), inside(q)
            if ip and iq:
                out.append(q)
            elif ip and not iq:
                out.append(inter(p, q))
            elif not ip and iq:
                out.append(inter(p, q)); out.append(q)
        return out
    def ix(xc):
        return lambda p, q: (xc, p[1] + (q[1] - p[1]) * (xc - p[0]) / (q[0] - p[0]))
    def iy(yc):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (yc - p[1]) / (q[1] - p[1]), yc)
    pts = list(poly)
    for inside, inter in ((lambda p: p[0] >= x0, ix(x0)), (lambda p: p[0] <= x1, ix(x1)), (lambda p: p[1] >= y0, iy(y0)), (lambda p: p[1] <= y1, iy(y1))):
        if not pts:
            break
        pts = clip(pts, inside, inter)
    return pts


def _shift_result(res, ox, oy):
    """Convert a result computed on a crop (origin ox, oy in the full frame) to full-frame coordinates (polygon, fov, flank lines x = s*y + i, rows)."""
    if res.get("polygon") is None:
        return res
    mv = lambda pts: [(x + ox, y + oy) for x, y in pts]
    out = dict(res)
    out["polygon"] = mv(res["polygon"])
    if res.get("polygon_unclipped"):
        out["polygon_unclipped"] = mv(res["polygon_unclipped"])
    if res.get("fov"):
        x0, y0, x1, y1 = res["fov"]
        out["fov"] = (x0 + ox, y0 + oy, x1 + ox, y1 + oy)
    ref = res.get("refined")
    if ref:
        r2 = dict(ref)
        r2["y_top"], r2["y_bottom"] = ref["y_top"] + oy, ref["y_bottom"] + oy
        r2["lines"] = {k: (s_, i_ + ox - s_ * oy) for k, (s_, i_) in ref["lines"].items()}      # x_full = s*(y_full - oy) + i + ox
        out["refined"] = r2
    return out


RIM_FRAC = 0.05          # window top / bottom rim (fraction of the window height) excluded when measuring its side edges
MIN_EDGE_ROWS = 3        # rows needed to trust a measured window side
SINGLE_MIN_RUN = 0.25    # one-flank path: shortest visible flank run, as a fraction of the (crop) height
MIN_FLANK_LEAN = 0.09    # a refined flank leaning less than this (dx per row, ~5 deg) is a window edge, not a pin flank
CLIP_LEVEL = 0.04        # same, for the lit window the FINAL polygon is clipped to (the crop for stage 1 keeps the generous FOV_LEVEL)
FOV_LEVEL = 0.04         # a pixel is 'lit' (inside the field of view) above floor + this fraction of the beam plateau
CROP_MARGIN = 0.12       # "auto": the window-crop result replaces the full-frame one only if its stage-1 score is higher by this much (sim pin frames: +0.16..0.17; real frames: +-0.01; the cases where the crop is slightly worse: <= +0.09)
CROP_PAD = 0.05          # margin added around the lit window before stage 1, as a fraction of the window size


def _final_on(gc):
    """stage 1 + refinement + field of view on one array (its own coordinates)"""
    res = refine_region(gc, find_pin_region_edges(gc))
    if res.get("polygon") is None:
        return res
    box = fov_box(gc, res["polygon"], level=CLIP_LEVEL)
    res["fov"] = box
    res["polygon_unclipped"] = res["polygon"]
    res["polygon"] = clip_polygon(res["polygon"], box) or res["polygon"]
    return res


def find_pin_region_final(g, longest=None, crop_to_window="auto"):
    """Pin region in the 2-D frame `g` (full-frame px).
    crop_to_window: False = whole frame; True = stage 1 on the lit-window crop; "auto" (default) = both when the window is clearly smaller than the frame, keep the window-crop one only if its
    stage-1 score is clearly (CROP_MARGIN) higher. The window (field of view) is measured first, without the pin. The crop makes the pin larger in the working image, removes the black surround and the window's own
    edges (which a small pin against the window edge is otherwise outvoted by); it can cut a pin whose base is wider than the window, which the full-frame run handles."""
    global LONGEST
    old = LONGEST
    if longest is not None:
        LONGEST = longest
    try:
        H0, W0 = g.shape
        full = lambda: _shift_result(_final_on(g), 0, 0)
        if crop_to_window is False:
            return full()
        x0, y0, x1, y1 = fov_box(g)
        if not ((x1 - x0) * (y1 - y0) < 0.85 * W0 * H0 and (x1 - x0) > 0.2 * W0 and (y1 - y0) > 0.2 * H0):
            r = full(); r["variant"] = "full frame"
            return r
        padx, pady = CROP_PAD * (x1 - x0), CROP_PAD * (y1 - y0)
        ox, oy = int(max(x0 - padx, 0)), int(max(y0 - pady, 0))
        rc = _shift_result(_final_on(g[oy:int(min(y1 + pady, H0)), ox:int(min(x1 + padx, W0))]), ox, oy)
        rc["crop_origin"] = (ox, oy); rc["variant"] = "window crop"
        if crop_to_window is True:
            return rc
        rf = full(); rf["variant"] = "full frame"
        return rc if rc.get("polygon") is not None and rc.get("score", 0) >= rf.get("score", 0) + CROP_MARGIN else rf
    finally:
        LONGEST = old
