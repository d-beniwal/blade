"""The read -> sync -> estimate -> optimise -> propose loop, validated end to end on a STAND-IN 'real' beamline: a simulator whose hidden truth (energy offset, gap error,
Th2 detuning) differs from the model's. SIMULATION ONLY. Also: a read-only instrument can be proposed for but never commanded. Run: python -I tests/test_loop.py"""
import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
import numpy as np
from blade.instrument.sim import SimInstrument
from blade.instrument.base import ReadOnlyError, Instrument
from blade.loop import sync as S, estimate as ES, optimize as O, run as R
from blade import procedures as P


def ok(msg):
    print("PASS", msg)


from blade.loop.demo import stand_in as start, operator_scans as operator_data, score


# 1. sync: the model takes the stand-in's controls; what is not known stays as it was
real = start(21)
model = SimInstrument(seed=0, scenario="startup")
snap = S.take(real)
rep = S.apply(model, snap)
assert not rep["skipped"] and abs(model.ctl("und.gap") - real.ctl("und.gap")) < 1e-12 and model.ctl("hem.energy") == real.ctl("hem.energy")
cmp_ = S.compare(model, snap)
assert not cmp_["controls"]
ok(f"sync: {len(rep['assigned'])} controls copied, no disagreement; ICs compared up to one common factor")

# 2. estimate: hidden truth recovered from three scans the model never saw
truth = dict(real.world.s["truth"])
truth["th1_err_mdeg"] = (real.world.th1_true_offset() - real.sim["hem"]["th1_offset_deg"]) * 1e3      # the CURRENT effective offset: the model's clock is not the real one, so slow drift is part of the estimate
res = ES.fit(model, ["th1_err_mdeg", "gap_err_mm", "th2_err_deg"], operator_data(real))
for k, tol in (("th1_err_mdeg", 0.3), ("gap_err_mm", 0.003), ("th2_err_deg", 0.0003)):
    assert abs(res.values[k] - truth[k]) < tol and res.identified[k], (k, res.values[k], truth[k], res.sigma[k])
ok("estimate: Th1 %+.2f (true %+.2f) mdeg, gap %+.4f (true %+.4f) mm, Th2 %+.4f (true %+.4f) deg" % (res.values["th1_err_mdeg"], truth["th1_err_mdeg"],
   res.values["gap_err_mm"], truth["gap_err_mm"], res.values["th2_err_deg"], truth["th2_err_deg"]))

# 2b. steering from ONE camera frame (read-only): beam centroid vs footprint centre
real = SimInstrument(seed=8, scenario="startup")
P.select_edge(real, "Re"); real.set("und.gap", P.nominal_gap(real)["gap_mm"])
P.find_beam_on_camera(real, "gh1", 3.5); P.centre_camera_on_beam(real, "gh1", "footprint")
model = real.copy(); S.apply(model, S.take(real))
model.world.s["truth"]["steer_xp_urad"] = model.world.s["truth"]["steer_yp_urad"] = 0.0
feat = ES.beam_offset_px(real.frame("gh1", bin_=4))
rs = ES.fit(model, ["steer_xp_urad", "steer_yp_urad"], [ES.frame_observation("beam", "gh1", feat, 2.0)])
tr = real.world.s["truth"]
assert abs(rs.values["steer_xp_urad"] - tr["steer_xp_urad"]) < 1.5 and abs(rs.values["steer_yp_urad"] - tr["steer_yp_urad"]) < 1.5, (rs.values, tr["steer_xp_urad"], tr["steer_yp_urad"])
ok("estimate: steering (%+.2f, %+.2f) urad from one frame (true %+.2f, %+.2f)" % (rs.values["steer_xp_urad"], rs.values["steer_yp_urad"], tr["steer_xp_urad"], tr["steer_yp_urad"]))

# 3. closed loop on the stand-in: propose on the model, apply on the stand-in, the stand-in's TRUE state improves
real = start(21); model = SimInstrument(seed=0, scenario="startup")
before = score(real)
hist = R.closed_loop(real, model, P.tune_energy_flux, observe=operator_data, estimate_params=["th1_err_mdeg", "gap_err_mm", "th2_err_deg"], max_iter=2, score=score, tol=2.5)
after = hist[-1]["score_after"]
t = real.truth()
assert after < before / 3 and after < 4.0, (before, after, t)
assert hist[0]["result"].proposal.changes and all(c.control in real.controls() for c in hist[0]["result"].proposal.changes)
ok(f"closed loop on the stand-in: score {before:.1f} -> {after:.1f} (gap err {t['undulator_gap_error_mm']:+.4f} mm, mu_t err {t['energy_mu_t_error']:+.3f}, flux {t['source_flux_relative_to_best']:.3f} of best)")

# 4. the proposal is data; the model is untouched by 'propose'; a read-only instrument cannot be commanded
model2 = SimInstrument(seed=0, scenario="startup"); g_before = model2.ctl("und.gap")
prop = O.propose(model2, P.gap_scan, 11.0, 0.2, 21, "icB1", True)
assert model2.ctl("und.gap") == g_before and any(c.control == "und.gap" for c in prop.changes)
assert all(not c.mapped for c in prop.changes) and prop.notes                # nothing is verified in the shipped mapping: simulator coordinates only, said so
class Frozen(Instrument):
    name = "frozen"
    def ctl(self, n): return 0.0
try:
    prop.apply(Frozen()); raise SystemExit("FAIL: a read-only instrument accepted a proposal")
except ReadOnlyError:
    pass
hist = R.closed_loop(Frozen_ := SimInstrument(seed=3, scenario="startup"), SimInstrument(seed=0), P.gap_scan, (11.0, 0.2, 21, "icB1", True), max_iter=1)
assert hist[0]["result"].status == "ok"
ro = type("RO", (SimInstrument,), {"writable": False, "set": Instrument.set})(seed=3, scenario="startup")
hist = R.closed_loop(ro, SimInstrument(seed=0), P.gap_scan, (11.0, 0.2, 21, "icB1", True), max_iter=2)
assert len(hist) == 1 and hist[0]["result"].status == "proposal only", hist[0]["result"].status
ok("proposals are data; 'propose' never touches the model; applying to a read-only instrument stops the loop with 'proposal only'")
print("loop OK")
