"""Pin finder + 3-D mount model, simulation only. Run: python -I tests/test_pin_find.py
 1. mount model: analytic chords == brute-force integration (pin cone, chuck with cross hole, rotated/leaning); tip height; opacity of the chuck.
 2. simulator: with the full mount the pin is parked sideways, a raised stage puts the chuck (not the pin) in the beam.
 3. find_pin: from several random axis offsets and pin heights the search ends with the pin tip inside the lit window; far fewer frames than a 2-D raster.
 4. plan_pin_search is read-only; a read-only instrument cannot run find_pin (ReadOnlyError at the first move)."""
import json, math, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
import numpy as np
from blade.physics import pin_mount as pm
from blade.vbl.world import VirtualBeamline
from blade.vbl import imaging as im
from blade.instrument.sim import SimInstrument
from blade.instrument.base import Instrument, ReadOnlyError
from blade import procedures as P
from blade.procedures import pin_find as PF

sim = json.load(open(ROOT / "beamline_twins" / "1-ID" / "sim.json"))
M = pm.from_sim(sim)

# ------------------------------------------------------------------ 1. model vs brute force
def brute(inside, Rm, tip, u, v, step=0.004):
    Rinv, zs = Rm.T, np.arange(-12, 12, step)
    out = np.zeros((len(v), len(u)))
    for i, vv in enumerate(v):
        for j, uu in enumerate(u):
            m = Rinv @ np.stack([np.full_like(zs, uu - tip[0]), np.full_like(zs, vv - tip[1]), zs])
            out[i, j] = inside(m[0], m[1], m[2]).sum() * step
    return out
pin_c, ch = sim["stage_E"]["pin"], M.p["chuck"]
rt, ta, rsh = pin_c["top_width_um"] * 5e-4, math.tan(math.radians(pin_c["half_angle_deg"])), M.p["pin"]["shaft_diameter_mm"] / 2
prot = M.p["pin"]["protrusion_mm"]
def in_pin(x, y, z):
    r = np.hypot(x, z)
    return (y <= 0) & (y >= -(prot + M.p["pin"]["inside_chuck_mm"])) & (r <= np.where(-y < M.cone_depth_mm, rt - y * ta, rsh))
def in_chuck(x, y, z):
    yt, yn = -prot, -prot - ch["nose_len_mm"]
    yb = yn - ch["body_len_mm"]
    rb = ch["body_dia_mm"] / 2
    r = np.hypot(x, z)
    rr = np.where(y > yn, ch["nose_top_dia_mm"] / 2 + (rb - ch["nose_top_dia_mm"] / 2) * (yt - y) / ch["nose_len_mm"], rb)
    body = (y <= yt) & (y >= yb) & (r <= rr)
    bore = (r <= rsh) & (y <= yt) & (y >= -(prot + M.p["pin"]["inside_chuck_mm"]))
    hole = np.hypot(z, y - (yb + ch["cross_hole_from_bottom_mm"])) <= ch["cross_hole_dia_mm"] / 2
    return body & ~bore & ~hole
u, v = np.linspace(-3.2, 3.2, 13), np.array([-0.3, -0.8, -5.5, -6.5, -9.0, -14.0, -14.7, -18.0])
for om, lean in ((0, 0.0), (35, 0.03), (90, 0.0)):
    th, by = M.thickness(u, v, 0.05, 0.0, omega_deg=om, lean_rad=lean)
    Rm = pm.rot_z(lean) @ pm.rot_y(om)
    e1 = np.abs(by["pin"] - brute(in_pin, Rm, (0.05, 0.0), u, v)).max()
    e2 = np.abs(by["chuck"] - brute(in_chuck, Rm, (0.05, 0.0), u, v)).max()
    assert e1 < 0.01 and e2 < 0.01, (om, lean, e1, e2)
print("PASS mount model: analytic chords match brute-force integration (pin, chuck + cross hole; omega 0/35/90, lean)")
assert abs(M.tip_height_mm - sum(M.layers_mm.values())) < 1e-9
T70 = M.transmission(np.array([0.0]), np.array([-7.0]), 0.0, 0.0, 70.0)[0][0, 0]
T90 = M.transmission(np.array([0.0]), np.array([-7.0]), 0.0, 0.0, 90.0)[0][0, 0]
assert T70 < 0.02 and T90 > T70, (T70, T90)
print(f"PASS chuck is ~opaque at 70 keV (T={T70:.4f}) and less so at 90 keV (T={T90:.4f}); tip {M.tip_height_mm:.1f} mm above the plate")

# ------------------------------------------------------------------ 2. simulator parking and chuck in the beam
def prep(seed, axis_off, tip_shift):
    w = VirtualBeamline(seed=seed, scenario="ready_for_pin")
    for n in ("slitEus", "slitEds"):
        w.set(n + ".hsize", 1.6); w.set(n + ".vsize", 1.3)
    w.set("wbSlits.hsize", 0.8); w.set("wbSlits.vsize", 0.7)
    T = w.s["truth"]["pin"]
    T["c_axis_off_beam_mm"] = axis_off
    T["axis_u_mm"] = w.beam_centre(w.z["samE"])[0] + axis_off          # ready_for_pin pins the axis through axis_u_mm: move THAT
    T["pin_top_v_mm"] = T["pin_top_v_mm"] + tip_shift                 # the pin sits tip_shift mm higher on this mount
    w.set("samE.aerox", w.sim["stage_E"]["pin"]["park_aerox_mm"])
    return w
w = prep(1, 0.0, 8.0)                  # pin sits 8 mm higher on this mount so that raising the stage stays inside samE.y's limits (default tip-on-beam is at y = 25.6)
clear = im.render(w, "gh1", bin_=4, with_noise=False).astype(float)
w.set("samE.aerox", 0.0)
w.set("samE.y", w.sim["stage_E"]["y_ref_mm"] + 0.3 + M.part_tip_offset_mm("chuck", "top") - w.s["truth"]["pin"]["pin_top_v_mm"])      # stage so that the chuck top edge is 0.3 mm above the beam centre: the chuck fills the window
raised = im.render(w, "gh1", bin_=4, with_noise=False).astype(float)
assert raised.mean() < 0.65 * clear.mean(), (raised.mean(), clear.mean())
print("PASS raised stage puts the opaque chuck (not the pin) in the beam; parked sideways the beam is clear")

# ------------------------------------------------------------------ 3. the search
cases = [(1, 0.0, 0.0), (2, 1.1, 4.0), (3, -1.2, 1.5), (4, 0.7, 5.5), (5, -0.4, 0.0)]      # tip shifts relative to the default mount (tip on the beam at samE.y = 25.6; limit 29.8)
frames = []
for seed, off, shift in cases:
    w = prep(seed, off, shift)
    inst = SimInstrument(w)
    r = PF.find_pin(inst, "gh1")
    assert r["found"], (seed, off, shift, r)
    img = im.render(w, "gh1", bin_=2, with_noise=False).astype(np.float32)
    ref = im.render(prep(seed, off, shift), "gh1", bin_=2, with_noise=False).astype(np.float32)
    lit = ref > 0.15 * np.percentile(ref, 99.5)
    sh = lit & (img < 0.5 * (ref))
    assert sh.sum() > 50, "no pin shadow in the final frame"
    ys, xs = np.nonzero(sh)
    assert ys.min() > np.nonzero(lit)[0].min() + 3, "tip touches the top of the window"
    top_w = sh[ys.min():ys.min() + 6].sum(1).mean()
    assert top_w < 0.4 * lit.sum(1).max(), top_w                  # a narrow tip, not the chuck
    # the true tip must be inside the window: from the hidden truth (scoring only)
    # hidden truth (scoring only): where the true tip lands in the camera frame (through the ray map), versus the window
    zc, uc, vc, pix, rows_, cols_ = w.camera_view("gh1")
    ps = w.pin_state()
    ph, pv, ch, cv = w.trace("h", w.z["samE"]), w.trace("v", w.z["samE"]), w.trace("h", zc), w.trace("v", zc)
    du = ch["A"] * (ps["u"] - ph["B"]) / ph["A"] + ch["B"] - uc
    dv = cv["A"] * (ps["v_top"] - pv["B"]) / pv["A"] + cv["B"] - vc
    win_h, win_v = r["log"][0]["lit_window_mm"]
    assert abs(du) < 0.35 * win_h and abs(dv) < 0.5 * win_v, f"TRUE tip is outside the window: du={du:.2f} dv={dv:.2f} mm (window {win_h:.2f} x {win_v:.2f})"
    print(f"     true tip in frame: du={du:+.2f} mm, dv={dv:+.2f} mm (window {win_h:.2f} x {win_v:.2f})")
    frames.append(r["frames"])
    print(f"  seed {seed}: axis off {off:+.1f} mm, tip {shift:+.1f} mm -> found with {r['frames']} frames, samE.y={r['controls']['samE.y']:.2f}, aero X={r['controls']['samE.aerox']:.2f}, tip {r['tip_offset_from_window_centre_mm']:+.2f} mm off centre")
plan = PF.plan_pin_search(SimInstrument(prep(1, 0.0, 0.0)), "gh1")
assert max(frames) < plan["frames_tip_only_raster"], (frames, plan["frames_tip_only_raster"])
print(f"PASS find_pin: tip in view in all {len(cases)} cases with {min(frames)}-{max(frames)} frames (a 2-D tip raster would need {plan['frames_tip_only_raster']})")

# ------------------------------------------------------------------ 4. read-only
class Frozen(SimInstrument):
    writable = False
    def set(self, name, value):
        raise ReadOnlyError("read-only")
fz = Frozen(prep(1, 0.0, 0.0))
before = dict(fz.world.s["ctl"])
pl = PF.plan_pin_search(fz, "gh1")
assert pl["moves_anything"] is False and fz.world.s["ctl"] == before and pl["frames_with_chuck"] > 0
try:
    PF.find_pin(fz, "gh1")
    raise AssertionError("find_pin ran on a read-only instrument")
except ReadOnlyError:
    pass
src = (ROOT / "blade" / "procedures" / "pin_find.py").read_text()
assert "epics" not in src.lower() and "caput" not in src and "pyepics" not in src
print("PASS plan_pin_search is read-only; find_pin refuses to move a read-only instrument; no EPICS vocabulary in the module")
print("ALL OK")
