"""Real tomo-alignment pin frames vs the virtual beamline (offline; the private HDF5 files are NOT needed).
 1. measure_frame recovers the geometry of a synthetic frame (box footprint + dark truncated cone) with known truth.
 2. The file->control map (beamline_twins/1-ID/file_control_map.json) only names controls the simulator has; the rotation stage is the 1ide:m9 one.
 3. The simulator, put at the read-backs of the real files (stored in fits/pin_frames.json), still reproduces the recorded real measurements of 85 frames
    (3 files, 71.7 keV): footprint size, dark floor, brightness, pin width / half angle / tip row / edge width / interior transmission, tip column vs omega.
 If the private files exist, also re-measures the real frames and checks the stored aggregates are current (skipped otherwise).
Run: python -I tests/test_fit_pin_frames.py"""
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
import numpy as np
from scipy import ndimage
from blade.calibration import pin_frames_fit as PFF
from blade.vbl.world import VirtualBeamline, control_specs

# 1 ---------------------------------------------------------------------------------------------------------- synthetic frame, known truth
H, W = 1490, 1940
yy, xx = np.mgrid[0:H, 0:W].astype(float)
box = ((xx > 450) & (xx < 1500) & (yy > 340) & (yy < 1170)).astype(float)
lit = 15000.0 * box
tip_row, tip_col, top_px, tan_a = 480.0, 800.0, 150.0, np.tan(np.radians(15.0))
half = top_px / 2 + np.clip(yy - tip_row, 0, None) * tan_a
pin = (np.abs(xx - tip_col) < half) & (yy >= tip_row)
img = 5500.0 + ndimage.gaussian_filter(lit * np.where(pin, 0.06, 1.0), 6.0)
m = PFF.measure_frame(img, 0.69)
assert abs(m["footprint"]["w_px"] - 1049) < 12 and abs(m["footprint"]["h_px"] - 829) < 12, m["footprint"]       # true box 1049 x 829 px; the 30 % threshold reads a few px wider on a blurred edge
p = m["pin"]
assert p is not None and abs(p["tip_row"] - tip_row) < 4 and abs(p["tip_col"] - tip_col) < 3, p
assert abs(p["half_angle_deg"] - 15.0) < 0.3 and abs(p["top_width_um"] - top_px * 0.69) < 6, p
print(f"PASS measure_frame on a synthetic frame: tip ({p['tip_col']:.1f}, {p['tip_row']:.1f}) true ({tip_col}, {tip_row}); half angle {p['half_angle_deg']:.2f} (15); top {p['top_width_um']:.1f} um ({top_px * 0.69:.1f})")

# 2 ---------------------------------------------------------------------------------------------------------- the map
mp = PFF.mapping()
sp = control_specs("1-ID")
names = [e["control"] for e in mp["controls"]]
assert all(n in sp for n in names), [n for n in names if n not in sp]
assert len(set(names)) == len(names)
assert mp["rotation"]["control"] == "samE.ry" and mp["rotation"]["pv"].startswith("1ide:m9")
assert not any(("scale" in e or "offset" in e) for e in mp["controls"]), "the replay map must not learn scales/offsets"
print(f"PASS file->control map: {len(names)} controls, all exist in the simulator; no scale/offset invented; rotation = {mp['rotation']['pv']}")

# 3 ---------------------------------------------------------------------------------------------------------- simulator vs the recorded real aggregates
agg = json.loads((PFF.FITS / "pin_frames.json").read_text())
w, clipped = PFF.sim_world(agg["controls_used"])
assert not clipped, clipped
PFF.place_camera(w, "gh1", *agg["footprint_centre_px"])
cab = agg["real_pin_tip_column_px"]
PFF.open_loop_pin(w, "gh1", (cab["c"], cab["a"], cab["b"]), agg["real_tip_row_px"])
PFF.match_pin_position(w, "gh1", (cab["c"], cab["a"], cab["b"]), agg["real_tip_row_px"])
oms = (0.9, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0, -90.0, -45.0)
res = PFF.sim_measure(w, "gh1", oms)
ms = [r[1] for r in res]
assert all(x["pin"] for x in ms), "pin lost in a simulated frame"
med = lambda f: float(np.median([f(x) for x in ms]))
chk = lambda name, got, ref, tol: (_ for _ in ()).throw(AssertionError(f"{name}: sim {got:.3f} vs real {ref:.3f} (tol {tol})")) if abs(got - ref) > tol else print(f"  ok {name:<30s} sim {got:9.2f}  real {ref:9.2f}  (tol {tol})")
fm = agg["footprint_median"]
chk("footprint width px", med(lambda x: x["footprint"]["w_px"]), fm["w_px"]["real"], 0.01 * fm["w_px"]["real"])
chk("footprint height px", med(lambda x: x["footprint"]["h_px"]), fm["h_px"]["real"], 0.01 * fm["h_px"]["real"])
for k, tol in (("edge_left_10_90_px", 14.0), ("edge_right_10_90_px", 14.0), ("edge_top_10_90_px", 14.0), ("edge_bottom_10_90_px", 14.0)):
    chk(k, med(lambda x: x["footprint"][k]), fm[k]["real"], tol)
lv = agg["levels_median"]
chk("dark floor (8th pct)", med(lambda x: x["bg"]), lv["bg"]["real"], 30.0)
chk("lit level p60", med(lambda x: x["lit_p60"]), lv["lit_p60"]["real"], 0.06 * lv["lit_p60"]["real"])
chk("lit level p95", med(lambda x: x["lit_p95"]), lv["lit_p95"]["real"], 0.06 * lv["lit_p95"]["real"])
pm = agg["pin_median"]
chk("pin top width um", med(lambda x: x["pin"]["top_width_um"]), pm["top_width_um"]["real"], 2.0)
chk("pin half angle deg", med(lambda x: x["pin"]["half_angle_deg"]), pm["half_angle_deg"]["real"], 0.15)
chk("pin interior transmission", med(lambda x: x["pin"]["interior_transmission"]), pm["interior_transmission"]["real"], 0.02)
chk("pin edge 10-90 px", med(lambda x: x["pin"]["edge_10_90_px"]), pm["edge_10_90_px"]["real"], 3.0)
chk("pin tip below footprint top px", med(lambda x: x["pin"]["tip_from_footprint_top_px"]), pm["tip_from_footprint_top_px"]["real"], 6.0)
chk("pin tip row px", med(lambda x: x["pin"]["tip_row"]), agg["real_tip_row_px"], 3.0)
c, a, b, rms = PFF.fit_sinusoid(oms, [x["pin"]["tip_col"] for x in ms])
for nm, got, ref in (("c", c, cab["c"]), ("a", a, cab["a"]), ("b", b, cab["b"])):
    chk(f"tip column {nm} (px)", got, ref, 3.0)
print("PASS the simulator at the real read-backs reproduces the recorded real frames")

# 4 ---------------------------------------------------------------------------------------------------------- the stored aggregates are current (needs the private files)
from blade import paths
d = paths.knowledge_dir("data") / "tomo_alignment_moving_only"
if list(d.glob("*/*.h5")):
    fr = PFF.load(sorted(d.glob("*/*.h5"))[0])
    mr = PFF.measure_frame(fr["frames"][len(fr["frames"]) // 2])
    assert mr["pin"] and abs(mr["footprint"]["w_px"] - fm["w_px"]["real"]) < 8, mr["footprint"]
    print("PASS private real frames re-measured: consistent with the stored aggregates")
else:
    print("SKIP private real frames not present")
print("ALL OK")
