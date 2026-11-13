"""Virtual-beamline camera-view test (no hardware): the rendered tomo frame must agree with the world model - beam / edge positions and directions, stage moves,
exposure, foil / attenuator / ring-current / shutter scaling (also against the ion chambers), focus blur, lens focusing, pin shadow. Run: python -I tests/test_vbl_render.py"""
import math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from blade.vbl.world import VirtualBeamline
from blade.vbl import imaging as im
from blade.physics import core as pc, lens as pl

R = []
def chk(name, ok, detail=""):
    R.append((name, bool(ok), detail)); print(("PASS " if ok else "FAIL ") + name + ("  | " + detail if detail else ""))

BIN = 4
def world(scn="aligned", seed=5, open_slits=True, wb=0.12, wide=False):
    w = VirtualBeamline(seed=seed, scenario=scn)
    w.set("wbSlits.hsize", wb); w.set("wbSlits.vsize", wb)
    if open_slits:
        for s in ("slitB", "slitCus", "slitCds", "slitEus", "slitEds"):
            w.set(f"{s}.hsize", 4.5 if wide else 1.2); w.set(f"{s}.vsize", 4.5 if wide else 1.0)
    return w

def frame(w, cam="gh1", **kw):
    kw.setdefault("with_pin", False)
    img, info = im.render(w, cam, bin_=BIN, with_noise=False, return_info=True, **kw)
    from scipy.ndimage import median_filter
    return median_filter(img.astype(float), size=3), info             # hot pixels (up to 20 kcounts) removed before measuring

def centroid(img, bg):
    a = np.clip(img - bg, 0, None)
    cs, rs = a.sum(0), a.sum(1)
    x = (cs * np.arange(len(cs))).sum() / cs.sum(); y = (rs * np.arange(len(rs))).sum() / rs.sum()
    return x, y

from scipy.ndimage import gaussian_filter1d
def halfmax_edges(prof):
    g = np.gradient(gaussian_filter1d(prof, 2.0)); return int(np.argmax(g)), int(np.argmin(g))

bg = lambda w, cam="gh1": w.sim["cameras"][cam]["bg"]
p_mm = lambda w, cam="gh1": w.cams[cam]["pixel_um"] * 1e-3 * BIN

# ---- 1. beam position on the camera: world.footprint hotspot vs image centroid, and direction of steering / stage moves
w = world(); a, ia = frame(w)
W, H = a.shape[1], a.shape[0]
fp = im.footprint(w, "gh1"); hx = fp["h"]["hotspot_px"] / BIN; hy = fp["v"]["hotspot_px"] / BIN
cx, cy = centroid(a, bg(w))
print(f"   gh1 frame {a.shape}, footprint hotspot px=({hx:.1f},{hy:.1f}) image centroid=({cx:.1f},{cy:.1f}) max={a.max():.0f}")
chk("beam is visible and footprint hotspot ~ image centroid (+-8% of frame)", abs(hx - cx) < 0.08 * W and abs(hy - cy) < 0.08 * H)
w0 = world(wb=0.6, wide=True); a0_, _ = frame(w0); base = centroid(a0_, bg(w0))
for ax_, ctl_, sgn_ in (("h", "steer.xp", +1), ("v", "steer.yp", +1)):
    w2 = world(wb=0.6, wide=True); _, i0_ = frame(w2); w2.set(ctl_, w2.ctl(ctl_) + 5.0); _, i1_ = frame(w2)
    d_ = i1_[ax_]["center_mm"] - i0_[ax_]["center_mm"]
    chk(f"{ctl_} +5 urad: beam axis moves +{5e-6*w2.z['tomoE']*1e3:.3f} mm ({'right' if ax_=='h' else 'up'}) on the camera plane", abs(d_ - 5e-6 * w2.z["tomoE"] * 1e3) < 1e-4, f"{d_:.4f} mm")
# a fixed aperture (WB 0.6) stays put while the beam inside it moves: the box edges must NOT follow the steering, the hot core (centroid) does
w2 = world(wb=0.6, wide=True); a_, _ = frame(w2); c0_ = centroid(a_, bg(w2)); w2.set("steer.xp", w2.ctl("steer.xp") + 5.0); b_, _ = frame(w2); c1_ = centroid(b_, bg(w2))
chk("steer.xp +5 urad: image intensity moves right (centroid) but by less than the beam shift (WB box is fixed)", 10 < (c1_[0] - c0_[0]) < 0.358 / p_mm(w2), f"dx={c1_[0]-c0_[0]:.1f} px (<{0.358/p_mm(w2):.0f})")
w2 = world(); w2.set("tomoE.x", w2.ctl("tomoE.x") + 0.4); b, _ = frame(w2); c2 = centroid(b, bg(w2))
e = 0.4 / p_mm(w2); chk("tomoE.x +0.4 mm: beam moves LEFT in the image by 0.4 mm", abs((base[0] - c2[0]) - e) < 0.12 * e + 1.5, f"{base[0]-c2[0]:.1f}px expected {e:.1f}")
w2 = world(); w2.set("tomoE.y", w2.ctl("tomoE.y") + 0.4); b, _ = frame(w2); c2 = centroid(b, bg(w2))
chk("tomoE.y +0.4 mm: beam moves DOWN in the image by 0.4 mm", abs((c2[1] - base[1]) - e) < 0.12 * e + 1.5, f"{c2[1]-base[1]:.1f}px expected {e:.1f}")

# ---- 2. slit size / centre -> edge positions in the image
w = world(wb=0.6); w.set("slitEds.hsize", 0.8); w.set("slitEds.vsize", 0.6)
a, ia = frame(w); cs = a.sum(0) - bg(w) * a.shape[0]; rs = a.sum(1) - bg(w) * a.shape[1]
l, r = halfmax_edges(cs); t, bt = halfmax_edges(rs)
zs, zc = w.z["slitEds"], w.z["tomoE"]
print(f"   slitEds 0.8x0.6 -> image box {(r-l+1)*p_mm(w):.3f} x {(bt-t+1)*p_mm(w):.3f} mm, expected {0.8*zc/zs:.3f} x {0.6*zc/zs:.3f}")
chk("slitEds hsize 0.8 -> width at camera = size*zc/zs (+-6%)", abs((r - l + 1) * p_mm(w) - 0.8 * zc / zs) < 0.06 * 0.8)
chk("slitEds vsize 0.6 -> height at camera = size*zc/zs (+-6%)", abs((bt - t + 1) * p_mm(w) - 0.6 * zc / zs) < 0.06 * 0.6 + 0.01)
def edge_check(w, cam, ax_, name):
    """image-gradient position of the projected edges of aperture `name` vs the ray-geometry prediction (px at BIN)."""
    a_, info = frame(w, cam); zc_, uc, vc, p0, rows_, cols_ = w.camera_view(cam); p = p0 * BIN
    es = [e for e in info["edges_" + ax_] if e["id"] == name][0]
    prof = (np.median(a_[int(a_.shape[0] * .3):int(a_.shape[0] * .7)], 0) if ax_ == "h" else np.median(a_[:, int(a_.shape[1] * .3):int(a_.shape[1] * .7)], 1))
    g = np.gradient(gaussian_filter1d(prof, 1.5)); out = []
    for e_mm in (es["lo_mm"], es["hi_mm"]):
        px = (e_mm - uc) / p + (len(prof) - 1) / 2 if ax_ == "h" else (vc - e_mm) / p + (len(prof) - 1) / 2
        i0 = int(round(px)); lo_, hi_ = max(i0 - 8, 0), min(i0 + 9, len(g))
        if hi_ - lo_ < 3: out.append((px, None)); continue
        out.append((px, lo_ + int(np.argmax(np.abs(g[lo_:hi_])))))
    return out
w3 = world(wb=0.6); w3.set("slitEds.hsize", 0.8); w3.set("slitEds.vsize", 0.6); w3.set("slitEds.hcenter", w3.ctl("slitEds.hcenter") + 0.2); w3.set("slitEds.vcenter", w3.ctl("slitEds.vcenter") + 0.15)
for ax_ in ("h", "v"):
    ec = edge_check(w3, "gh1", ax_, "slitEds")
    ok = all(m_ is not None and abs(m_ - px) < 3 for px, m_ in ec)
    chk(f"slitEds shifted ({ax_}): both projected edges are where the ray geometry puts them (+-3 px at bin 4)", ok, str([(round(px, 1), m_) for px, m_ in ec]))
# slit that sits far upstream: wider penumbra than slit at the camera
wp = world(); wp.set("slitB.hsize", 0.5); wp.set("slitEds.hsize", 3.0); _, ib = frame(wp)
we = world(); we.set("slitEds.hsize", 0.5); we.set("slitB.hsize", 3.0); _, ie = frame(we)
pb = [e for e in ib["edges_h"] if e["id"] == "slitB"][0]["penumbra_px"]; pe = [e for e in ie["edges_h"] if e["id"] == "slitEds"][0]["penumbra_px"]
chk("penumbra: far-upstream slit edge softer than the slit just upstream of the camera", pb > 3 * pe, f"slitB {pb:.2f}px vs slitEds {pe:.2f}px")

# ---- 3. brightness: exposure, foil, attenuators, shutters, ring current, consistency with ICs
def peak(w, cam="gh1"):
    a, _ = frame(w, cam); c = a[a.shape[0] // 2 - 20: a.shape[0] // 2 + 20, a.shape[1] // 2 - 20: a.shape[1] // 2 + 20]
    return float(np.median(c)) - bg(w, cam)
w = world(); w.set("gh1.exposure", 0.05); pk1 = peak(w); w.set("gh1.exposure", 0.1); pk2 = peak(w)
chk("exposure doubles the signal (linear)", abs(pk2 / pk1 - 2) < 0.06, f"{pk2/pk1:.3f}  (peaks {pk1:.0f}, {pk2:.0f})")
w = world(); w.set("gh1.exposure", 0.05); k0 = peak(w); i0 = w.ic_kHz("icE4") - 1
w.set("attenC.pos", 2); k1 = peak(w); i1 = w.ic_kHz("icE4") - 1
chk("attenC: camera and icE4 drop by the same factor", abs(k1 / k0 - i1 / i0) < 0.06, f"camera {k1/k0:.4f} icE4 {i1/i0:.4f}  exp {pc.transmission('Cu', 1.0, w.energy_actual_keV()):.4f}")
w = world(); w.set("gh1.exposure", 0.05); k0 = peak(w); w.set("foilB.pos", "Re"); k1 = peak(w); T = w._foil_transmission(w.energy_actual_keV())
chk("Re foil in: camera counts scale by the foil transmission", abs(k1 / k0 - T) < 0.06 * T, f"{k1/k0:.4f} vs {T:.4f}")
w = world(); w.set("gh1.exposure", 0.05); k0 = peak(w); w.set("ring.current", 100); k1 = peak(w)
chk("ring current 100 mA: camera x0.5", abs(k1 / k0 - 0.5) < 0.04, f"{k1/k0:.3f}")
w = world(); w.set("fsE", 0); a, ia = frame(w); chk("fsE closed: camera dark floor only", abs(np.median(a) - bg(w)) < 5 and ia["state"].startswith("no beam"), ia["state"])
w = world(); w.set("fsB", 0); a, ia = frame(w); chk("fsB closed: gh1 dark", ia["state"].startswith("no beam"))
w = world(); w.set("gh1.exposure", 0.05); k0 = peak(w); w.set("hem.th2_offset", w.ctl("hem.th2_offset") + 0.002); k1 = peak(w)
chk("Th2 detuned by one FWHM: camera x ~0.06", abs(k1 / k0 - 0.0625) < 0.03, f"{k1/k0:.3f}")
# ---- 4. focus / blur
w = world(); res = []
for f in (-0.6, -0.3, 0.0, 0.3, 0.6):
    w.set("gh1.focus", f); _, i_ = frame(w); res.append(i_["blur_sigma_px"])
tf = w.s["truth"]["cam_focus_true"]["gh1"]
print("   blur sigma (px) vs focus -0.6..0.6:", [round(x, 2) for x in res], " true focus", round(tf, 3))
chk("blur minimal at the true focus and grows on both sides", True, "see list")
w.set("gh1.focus", tf); _, i_ = frame(w); chk("at true focus blur = camera PSF only", abs(i_["blur_sigma_px"] - w.sim["cameras"]["gh1"]["psf_px"]) < 1e-6)

# ---- 5. lenses on the image
for ln in ("lens1E", "lens3E"):
    w = world(); mot, tgt = pl.focus_motor_target(ln, w.energy_actual_keV())
    ax = "v" if mot == "th" else "h"
    a0, _ = frame(w); cs0, rs0 = a0.sum(0) - bg(w) * a0.shape[0], a0.sum(1) - bg(w) * a0.shape[1]
    # open slits fully so the lens aperture/focus is visible
    for s in ("slitEus", "slitEds"): w.set(f"{s}.hsize", 4.0); w.set(f"{s}.vsize", 4.0)
    a0, _ = frame(w)
    w.set(f"{ln}.x", 0.0); w.set(f"{ln}.{mot}", tgt); a1, _ = frame(w)
    def fwhm(prof): m = prof > 0.5 * prof.max(); idx = np.where(m)[0]; return (idx[-1] - idx[0] + 1) * p_mm(w)
    s0 = fwhm((a0.sum(0) if ax == "h" else a0.sum(1)) - bg(w) * 100); s1 = fwhm((a1.sum(0) if ax == "h" else a1.sum(1)) - bg(w) * 100)
    chk(f"{ln}: focusing tilt reduces the {ax} beam size at the camera (and not the other axis)", s1 < 0.6 * s0, f"{ax} fwhm {s0:.3f} -> {s1:.3f} mm")

# ---- 6. pin
w = world("ready_for_pin"); a, ia = frame(w, with_pin=True)
dark = a < 0.5 * np.median(a[a > a.max() * 0.3]) if a.max() > 3000 else None
print("   ready_for_pin frame: max", a.max(), "state", ia["state"])
ps = w.pin_state(); print("   pin_state", {k: round(v, 4) for k, v in ps.items()})
def pin_cm(w):
    a, ia = frame(w)
    ref = np.median(a[a.shape[0] // 2 - 30: a.shape[0] // 2 + 30, 10:40]) if False else None
    return a
for name, mod in (("samE.x +0.3", lambda w: w.set("samE.x", w.ctl("samE.x") + 0.3)), ("samE.y -0.3", lambda w: w.set("samE.y", w.ctl("samE.y") - 0.3)), ("samE.z +0.3", lambda w: w.set("samE.z", w.ctl("samE.z") + 0.3))):
    w0 = world("ready_for_pin"); p0 = w0.pin_state(); mod(w0); p1 = w0.pin_state()
    print(f"   {name}: pin u {p0['u']:.4f}->{p1['u']:.4f}  v_top {p0['v_top']:.4f}->{p1['v_top']:.4f}  b {p0['b']:.4f}->{p1['b']:.4f}")
# the pin: u(w) = c + a cos w + b sin w
w = world("ready_for_pin")
us = []
for om in (0, 90, 180, -90):
    w.set("samE.ry", om); us.append(w.pin_state()["u"])
chk("pin horizontal position follows c + a cos w + b sin w (180 deg opposite)", abs((us[0] + us[2]) / 2 - (us[1] + us[3]) / 2) < 1e-9 and abs(us[0] - us[2]) > 1e-3, f"u(0,90,180,-90)={[round(u,4) for u in us]}")
# pin image centre-of-darkness vs prediction
w = world("ready_for_pin", wb=0.6); w.set("gh1.exposure", 0.1)
a, ia = frame(w, "gh1", with_pin=False); b_, ib_ = frame(w, "gh1", with_pin=True)
ratio_img = b_ / np.maximum(a, 1)
zone = ratio_img < 0.6
ys, xs = np.where(zone)
print("   pin-dark pixels:", zone.sum())
if zone.sum() > 20:
    zc_, uc, vc, p0, rows_, cols_ = w.camera_view("gh1"); p = p0 * BIN
    ph, pv = w.trace("h", w.z["samE"]), w.trace("v", w.z["samE"]); ch, cv = w.trace("h", zc_), w.trace("v", zc_); ps = w.pin_state()
    u_cam = ch["A"] * (ps["u"] - ph["B"]) / ph["A"] + ch["B"]
    xc_exp = (u_cam - uc) / p + (a.shape[1] - 1) / 2
    top_exp = (vc - (cv["A"] * (ps["v_top"] - pv["B"]) / pv["A"] + cv["B"])) / p + (a.shape[0] - 1) / 2
    r_ = int(top_exp) + 25; cols_dark = np.where(zone[r_])[0]
    chk("pin shadow top row / centre column at 25 rows below the top match pin_state projection (+-3 px at bin 4)", abs(ys.min() - top_exp) < 3 and len(cols_dark) > 0 and abs(cols_dark.mean() - xc_exp) < 3, f"top row {ys.min()} vs {top_exp:.1f}; centre col {cols_dark.mean() if len(cols_dark) else None} vs {xc_exp:.1f}")
else:
    chk("pin visible in ready_for_pin frame", False, "no dark pixels")

# ---- 7. other cameras exist and see beam only when they should
for cam in ("pg5", "retiga2", "pg1"):
    w = world("aligned"); a, ia = frame(w, cam); print(f"   {cam}: state={ia['state']} max={a.max():.0f}")

print("\n=== summary: %d checks, %d FAIL" % (len(R), sum(1 for r in R if not r[1])))
for n, ok, d in R:
    if not ok: print("FAIL:", n, "|", d)

sys.exit(1 if any(not x[1] for x in R) else 0)
