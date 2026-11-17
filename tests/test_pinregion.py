"""Pin REGION method (blade/pinregion, used by the page's tomo-pin fit button): synthetic frame with known truth, the simulator's own frames (pin present / absent), live following of a
stage move. No hardware, no knowledge tree needed. Run: python -I tests/test_pinregion.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import warnings
warnings.filterwarnings("ignore")
import numpy as np
from scipy import ndimage as ndi
from blade import registry
from blade.vbl import store
from blade.pinregion import find_pin_region_final, pin_geometry, pin_like
from blade.procedures import pin_fit
from blade import pinregion, paths

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(detail)) if detail != "" else ""))
    if not cond:
        FAILS.append(name)


# ---- 1. synthetic frame with exact truth: lit window, dark truncated cone (top row 477, top width 151.5 px, half angle 15 deg, axis column 818)
H, W = 1490, 1940
yy, xx = np.mgrid[0:H, 0:W]
img = np.full((H, W), 5400.0)
img[(yy >= 347) & (yy <= 1157) & (xx >= 457) & (xx <= 1488)] = 12000.0
t = np.tan(np.radians(15.0))
hw = 0.5 * 151.5 + t * (yy - 477)
pin = (yy >= 477) & (np.abs(xx - 818) <= hw)
img[pin] = 5400.0 + 0.045 * (12000.0 - 5400.0)
img = ndi.gaussian_filter(img, 2.0) + np.random.default_rng(0).normal(0, 60, img.shape)
res = find_pin_region_final(img.astype(np.float32))
geo = pin_geometry(img, res, pixel_um=0.69)
p = geo["pin"]
check("synthetic: pin found with both flanks", geo["found"] and geo["quality"] == "both_flanks", geo.get("quality"))
check("synthetic: axis column within 3 px of 818", abs(p["axis_col_px"] - 818) < 3, round(p["axis_col_px"], 2))
check("synthetic: top width within 6 px of 151.5", abs(p["top_width_px"] - 151.5) < 6, round(p["top_width_px"], 1))
check("synthetic: half angle within 1 deg of 15", abs(p["half_angle_deg"] - 15) < 1.0, round(p["half_angle_deg"], 2))
check("synthetic: tip row within 4 px of 477", abs(p["tip_row_px"] - 477) < 4, round(p["tip_row_px"], 1))
check("synthetic: accepted as pin-like", pin_like(res, geo, img.shape)[0])

# ---- 2. the simulator's frames through the same path the button uses (vbl_pin_geometry)
for scn, seed in (("ready_for_pin", 0), ("ready_for_pin", 3), ("aligned", 0)):
    registry.invoke("vbl_reset", scenario=scn, seed=seed)
    pin_fit.reset_pin_prior()
    g = registry.invoke("vbl_pin_geometry")
    n = g["numbers"]
    check(f"sim {scn}-{seed}: recognised, usable, both flanks", g["recognised"] and g["usable"] and g["quality"] == "both_flanks", (g["recognised"], g["quality"]))
    check(f"sim {scn}-{seed}: top width ~144 px, half angle ~14.8 deg", 130 < n["top_width_px"] < 160 and 13.5 < n["half_angle_deg"] < 16.5, (round(n["top_width_px"]), round(n["half_angle_deg"], 2)))
    ov = g["overlay"]
    check(f"sim {scn}-{seed}: overlay has region, window, flanks, axis, all points inside the frame", {"polygon", "fov", "top", "left_flank", "right_flank", "axis"} <= set(ov)
          and all(-0.01 <= v <= 1.01 for pt in ov["polygon"] for v in pt))
for scn in ("startup", "camera_in_beam"):
    registry.invoke("vbl_reset", scenario=scn, seed=0)
    g = registry.invoke("vbl_pin_geometry")
    check(f"sim {scn}: no pin recognised, plain verdict, nothing drawn, technical reason kept", g["recognised"] is False and g["why"] == "No pin visible in this frame." and g["overlay"] == {} and bool(g["reasons"]), (g["why"] or "")[:60])

# ---- 2b. pin cut by the window edge (one flank visible): the visible REGION only - no corners, axis, hidden flank or numbers
registry.invoke("vbl_reset", scenario="ready_for_pin", seed=0)
w = store.require("default")
w.set("samE.aerox", w.ctl("samE.aerox") + 0.2)
store.save(w, "default")
pin_fit.reset_pin_prior()
g = registry.invoke("vbl_pin_geometry")
ov = g["overlay"]
check("one flank visible: region identified, quality region_only, geometry not fitted", g["recognised"] and g["quality"] == "region_only" and g["geometry"] is False, (g["recognised"], g["quality"]))
check("one flank visible: overlay = region + the measured flank only (no top, axis, corners, hidden flank)", "polygon" in ov and not ({"top", "axis"} & set(ov)) and ov["hidden_flank"] == []
      and sum(k in ov for k in ("left_flank", "right_flank")) == 1, sorted(ov))
check("one flank visible: no geometry numbers", all(k not in g["numbers"] for k in ("axis_col_px", "tip_row_px", "top_width_px", "half_angle_deg")))
check("one flank visible: region stays inside the lit window", all(ov["fov"]["box"][0] - 0.01 <= x <= ov["fov"]["box"][2] + 0.01 and ov["fov"]["box"][1] - 0.01 <= y <= ov["fov"]["box"][3] + 0.01 for x, y in ov["polygon"]))

_wm = store.require("default")
from blade.procedures._util import as_instrument
mm1 = pinregion.measure_frame(as_instrument(_wm).frame("gh1", bin_=1).astype(float), 0.0)
check("measure_frame: a one-flank region with no learned width has no pin_col, is not usable and gives no move hint (7 % of pin-free KB frames yield such regions)",
      mm1["quality"] == "both_flanks" or (mm1["pin_col"] is None and not mm1["usable"] and not mm1["view"].get("hint")), (mm1["quality"], mm1["view"]["state"], mm1["view"].get("hint")))

# ---- 3. live following: lowering the pin by 0.25 mm moves the tip row down by hundreds of px and shrinks the visible height; the button never moves a motor
registry.invoke("vbl_reset", scenario="ready_for_pin", seed=0)
pin_fit.reset_pin_prior()
w = store.require("default")
c0 = dict(w.snapshot()["controls"])
a = registry.invoke("vbl_pin_geometry")["numbers"]
w = store.require("default")
w.set("samE.y", w.ctl("samE.y") - 0.25)
store.save(w, "default")
c1 = dict(store.require("default").snapshot()["controls"])
b = registry.invoke("vbl_pin_geometry")["numbers"]
check("move: tip row follows the stage (down by > 200 px), visible height shrinks", b["tip_row_px"] - a["tip_row_px"] > 200 and b["visible_height_px"] < a["visible_height_px"] - 200,
      (round(a["tip_row_px"]), round(b["tip_row_px"])))
check("move: axis column unchanged by a vertical move (within 3 px)", abs(b["axis_col_px"] - a["axis_col_px"]) < 3)
registry.invoke("vbl_pin_geometry")
check("analysis moved no control", dict(store.require("default").snapshot()["controls"]) == c1)


# ---- 4. measure_frame: the one per-frame measurement the alignment procedures use (blade/pinregion/measure.py)
m = pinregion.measure_frame(img, 0.0, pixel_um=0.69)
check("measure_frame (synthetic): usable, both flanks, axis within 3 px, window centre = lit area centre", m["usable"] and m["quality"] == "both_flanks" and abs(m["pin_col"] - 818) < 3
      and abs(m["beam"]["cx"] - 0.5 * (457 + 1488)) < 3 and abs(m["beam"]["cy"] - 0.5 * (347 + 1157)) < 3, (m["quality"], m["pin_col"], m["beam"]["cx"]))
mo = pinregion.measure_frame(img, 0.0, prior={"top_width": 90.0, "half_angle_deg": 15.0}, pixel_um=0.69)
check("measure_frame: a pin-like object whose width disagrees with the learned pin is 'other_object', not used", mo["identity"] == "other" and not mo["usable"] and mo["pin_col"] is None
      and mo["view"]["state"] == "other_object", (mo["identity"], mo["view"]["state"]))
mn = pinregion.measure_frame(np.zeros((1490, 1940)), 0.0)
check("measure_frame: an empty (all-zero) frame is 'no_beam', nothing usable", mn["view"]["state"] == "no_beam" and not mn["usable"] and mn["pin_col"] is None, mn["view"]["state"])
img_c = img.copy()
img_c[:457] = 5400.0                                        # window top moved down to 20 rows above the pin top (row 477): the window's soft rim, not the pin top, is what the edge fit would see
mt = pinregion.measure_frame(img_c, 0.0)
check("measure_frame: a pin top within the window's top rim is never 'in_view' / usable (it is partial, or not recognised)", mt["view"]["state"] in ("partial", "absent") and not mt["usable"],
      (mt["view"]["state"], mt["top_width"], mt["view"].get("hint")))
fa = pinregion.fit_axis([-90, -30, 0, 30, 90], [818 + 5 * np.sin(np.radians(o)) - 130 * np.cos(np.radians(o)) for o in (-90, -30, 0, 30, 90)])
check("fit_axis recovers x(w) = c + a cos w + b sin w", fa["ok"] and abs(fa["a"] + 130) < 1e-6 and abs(fa["b"] - 5) < 1e-6 and abs(fa["c"] - 818) < 1e-6, fa.get("a"))

# ---- 5. the 85 real GH1 raw frames (knowledge tree, skipped when absent): every frame usable; x(w) = c + a cos w + b sin w as validated (c 815.7, a -130.0, b -14.0, rms 3.95 px); the window
# footprint is the beam target and must not move with the pin
D = paths.knowledge_dir("data") / "tomo_alignment_moving_only"
files = sorted(D.glob("*/*.h5")) if D.exists() else []
if not files:
    print("SKIP real-frame check: knowledge tree data not available")
else:
    from blade.calibration import pin_frames_fit as PFF
    ms = []
    for f in files:
        d = PFF.load(f)
        ms += [pinregion.measure_frame(fr.astype(float), ry, pixel_um=0.69) for fr, ry in zip(d["frames"], d["ry"])]
    ok = [x for x in ms if x["usable"]]
    fit = pinregion.fit_axis([x["omega"] for x in ok], [x["pin_col"] for x in ok])
    check("real frames: all %d usable and in view" % len(ms), len(ok) == len(ms) and all(x["view"]["state"] == "in_view" for x in ms), (len(ok), len(ms)))
    check("real frames: axis fit c within 2 px of 815.7, a -130 +- 2, b -14 +- 3, rms < 5 px", abs(fit["c"] - 815.7) < 2 and abs(fit["a"] + 130) < 2 and abs(fit["b"] + 14) < 3 and fit["rms"] < 5,
          (round(fit["c"], 1), round(fit["a"], 1), round(fit["b"], 1), round(fit["rms"], 2)))
    cx = np.array([x["beam"]["cx"] for x in ms])
    check("real frames: every beam footprint is pin-excluded and its centre stays within 15 px over all angles and files (9.2 px measured, = the retired code's values to 0.2 px; includes the real drift between the 3 files)",
          np.ptp(cx) < 15 and all(x["beam"]["method"] == "pin-excluded" for x in ms), round(float(np.ptp(cx)), 2))

print("ALL OK" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
