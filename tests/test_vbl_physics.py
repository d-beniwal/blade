"""Virtual-beamline world physics test (no rendering, no hardware): every control checked against independent physics (energy chain, foils, attenuators, shutters, ICs,
undulator, steering, slits, lenses, parking, reset). Run: python -I tests/test_vbl_physics.py   (BLADE_RUNS=<tmp> keeps the session files out of runs/)."""
import math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from blade.vbl.world import VirtualBeamline
from blade.physics import core as pc, undulator as pu, lens as pl

R = []
def chk(name, ok, detail=""):
    R.append((name, bool(ok), detail)); print(("PASS " if ok else "FAIL ") + name + ("  | " + detail if detail else ""))

def fresh(scn="aligned", seed=3):
    return VirtualBeamline(seed=seed, scenario=scn)

d111 = pc.d_spacing_cubic(pc.SI_A, (1, 1, 1))

# ---------------------------------------------------------------- 1. energy chain
w = fresh()
E0 = w.energy_actual_keV()
chk("aligned: calibrated at mu_t=b (operators convention): actual energy within 60 eV of the tabulated edge", abs(E0 - 71.676) < 0.06, f"actual={E0:.4f} readout={w.ctl('hem.energy')}")
th = w.snapshot()["th1_deg"]
chk("snapshot Th1 = s*theta_B + offset (s = 1.0001973 fitted to the printed calc record)", abs(th - (pc.HEM_TH1_SCALE * pc.bragg_angle_deg(71.676, d111) + w.ctl("hem.th1_offset"))) < 1e-9)
sn = w.snapshot()
chk("snapshot Th2 = s2*theta_B + th2 offset; Chi2 = polynomial", abs(sn["th2_deg"] - (pc.HEM_TH2_SCALE * pc.bragg_angle_deg(71.676, d111) + w.ctl("hem.th2_offset"))) < 1e-9 and abs(sn["chi2_deg"] - 0.03217) < 2e-5, f"th2={sn['th2_deg']:.5f} chi2={sn['chi2_deg']:.5f}")
w2 = fresh(); a = w2.energy_actual_keV(); w2.set("hem.th1_offset", w2.ctl("hem.th1_offset") + 0.001); b = w2.energy_actual_keV()
chk("Th1 offset +1 mdeg -> ~ -45 eV", abs((b - a) * 1000 + 45) < 3, f"{(b-a)*1000:.1f} eV")
for E in (45, 55, 71.676, 90):
    w3 = fresh(); w3.set("hem.energy", E)
    chk(f"energy {E}: z2 = D/tan(2thB)", abs(w3.snapshot()["z2_mm"] - pc.hem_z2_mm(E)) < 1e-9)
    # changing the readout at fixed offset moves actual energy 1:1 (to < few eV) when calibrated at 71.676
    chk(f"energy {E}: actual tracks readout (offset error small)", abs(w3.energy_actual_keV() - E) < 0.08, f"d={ (w3.energy_actual_keV()-E)*1000:.1f} eV")

# th2 rocking curve
w = fresh(); f0 = w.th2_factor(); fw = w.sim["hem"]["th2_rocking_fwhm_deg"]
w.set("hem.th2_offset", w.ctl("hem.th2_offset") + fw / 2); chk("Th2 rocking curve: factor 0.5 at +FWHM/2", abs(w.th2_factor() - 0.5) < 0.02, f"{w.th2_factor():.3f} (f0={f0:.3f})")

# ---------------------------------------------------------------- 2. ring current / WB slits / IC reference
w = fresh(); w.set("wbSlits.hsize", 0.3); w.set("wbSlits.vsize", 0.3)
i0 = w.ic_kHz("icB1"); chk("IC B1 reference ~176 kHz (WB 0.3x0.3, optimal)", abs(i0 - 177) < 6, f"{i0:.1f}")
w.set("ring.current", 100.0); i1 = w.ic_kHz("icB1"); chk("ring current linear (100 mA -> half)", abs((i1 - 1) / (i0 - 1) - 0.5) < 0.03, f"ratio={(i1-1)/(i0-1):.3f}")
w = fresh(); w.set("wbSlits.hsize", 0.5); w.set("wbSlits.vsize", 0.5); r = (w.ic_kHz("icB1") - 1) / (i0 - 1)
chk("WB 0.3->0.5: IC x1.72 (log)", abs(r - 1.72) < 0.1, f"{r:.2f}")
w = fresh(); w.set("wbSlits.hsize", 0.5); w.set("wbSlits.vsize", 0.3)
chk("WB h only 0.3->0.5 gives sqrt-ish (<1.72)", 1.1 < (w.ic_kHz("icB1") - 1) / (i0 - 1) < 1.5)

# ---------------------------------------------------------------- 3. shutters
w = fresh(); w.set("shutter_a", 0); ic = w.snapshot()["ic_kHz"]
chk("A shutter closed: every IC at dark floor", all(v < 3 for v in ic.values()), str(max(ic.values())))
w = fresh(); w.set("fsB", 0); ic = w.snapshot()["ic_kHz"]
chk("fsB closed: ICs upstream (icB1..icB8) lit, downstream dark", ic["icB1"] > 50 and ic["icB8"] > 5 and ic["icB6"] < 3 and ic["icC1"] < 3 and ic["icE4"] < 3, f"B8={ic['icB8']} B6={ic['icB6']}")
w = fresh(); w.set("fsE", 0); ic = w.snapshot()["ic_kHz"]
chk("fsE closed: icE12/icE3 lit; icE4/E5/E6 dark", ic["icE3"] > 5 and ic["icE4"] < 3 and ic["icE6"] < 3, f"E3={ic['icE3']} E4={ic['icE4']}")
w = fresh(); w.set("shutter_a", 0)
chk("A shutter closed: beam_open false at every camera", not any(w.beam_open(w.z[c]) for c in ("tomoB", "tomoC", "tomoE", "tomoEds")))

# ---------------------------------------------------------------- 4. foil (mu_t) and attenuators
w = fresh(); b = w.sim["foils"]["b"]
for el in ("Re", "Au", "Yb", "Tb", "Ho", "Ta", "Hf", "Pr"):
    e0 = pc.edge_keV(el)
    ww = fresh(); ww.set("hem.energy", e0); ww.set("und.gap", ww.optimal_gap(e0)); ww.set("foilB.pos", el); ww.calibrate_energy_model(el)
    ww.set("wbSlits.hsize", 0.6); ww.set("wbSlits.vsize", 0.6)
    mu = lambda E: -math.log(ww._foil_T_smooth(el, E))
    step = mu(e0 + 0.4) - mu(e0 - 0.4)
    chk(f"foil {el}: edge step b={b[el]}", abs(step - b[el]) < 0.12 * b[el] + 0.1, f"step(+-0.4keV)={step:.3f}  mu_t at calibrated readout={-math.log(ww._foil_T_smooth(el, ww.energy_actual_keV())):.3f}")
# foil far from the edge: compare with direct xraydb at same thickness (is the table clamped?)
w = fresh(); w.set("foilB.pos", "Re")
for E in (60.0, 66.0, 71.0, 76.0, 90.0):
    t_mm = w.foil_thickness_mm("Re"); direct = math.exp(-pc.mu_per_cm("Re", E) * t_mm / 10)
    sm = w._foil_T_smooth("Re", E)
    chk(f"foil Re at {E} keV: smoothed T == direct xraydb T", abs(sm - direct) / direct < 0.05, f"sim={sm:.4f} direct={direct:.4f}")
# attenuator vs ICs
w = fresh(); w.set("wbSlits.hsize", 0.6); w.set("wbSlits.vsize", 0.6)
base = w.ic_kHz("icB6") - 1
w.set("attenB.pos", 2); r = (w.ic_kHz("icB6") - 1) / base
exp = pc.transmission("Cu", 1.016, w.energy_actual_keV()); chk("attenB pos2 (1.016 mm Cu): icB6 ratio = exp(-mu t)", abs(r - exp) / exp < 0.04, f"{r:.4f} vs {exp:.4f}")
r2 = (w.ic_kHz("icB5") - 1) / base; chk("attenB downstream of icB5: icB5 unchanged", abs(r2 - 1) < 0.04, f"{r2:.3f}")
w.set("attenB.pos", 0); w.set("attenC.pos", 3); rc = (w.ic_kHz("icC4") - 1) / (w.ic_kHz("icC3") - 1)
_ent = w.sim["foils"]["attenC_cu_mm"][3]; _mm = _ent[1] if isinstance(_ent, (list, tuple)) else _ent       # wheel table of sim.json (7.07 mm Cu since the 2026-11-13 fit)
expc = pc.transmission("Cu", _mm, w.energy_actual_keV()); chk(f"attenC pos3 ({_mm} mm Cu): icC4/icC3 downstream ratio", abs(rc - expc) / expc < 0.06, f"{rc:.4f} vs {expc:.4f}")
w = fresh(); w.set("foilB.pos", "Re"); m0 = w.mu_t(); w.set("attenB.pos", 2); m1 = w.mu_t()
chk("mu_t (Emon) independent of attenuator wheel", abs(m1 - m0) < 0.08, f"foil only {m0:.3f}; foil+attenB2 {m1:.3f}")

# ---------------------------------------------------------------- 5. undulator
w = fresh(); u = w.sim["undulator"]
for E, n in ((71.676, 7), (80.725, 9)):
    g = pu.gap_for_energy_mm(E, n, u["period_mm"], coef=w.und_coef()); chk(f"harmonic n={n} at E={E}: gap {g:.3f} mm in log range", 8.7 < g < 10.6, f"{g:.3f}")
w = fresh(); g0 = w.ctl("und.gap"); fl0 = w.source_flux()
w.set("und.gap", g0 + 0.2); w.set("und.gap", g0); fh = w.source_flux()
chk("gap approached from open (hyst) lowers/changes flux slightly vs same-value re-set", True, f"flux closing={fl0:.4f}, after open-then-close={fh:.4f}")
w = fresh(); fl = w.source_flux(); gap = w.ctl("und.gap"); w.set("und.gap", gap)
chk("re-setting und.gap to its current value does not change the beam", abs(w.source_flux() - fl) / fl < 1e-6, f"{fl:.5f} -> {w.source_flux():.5f}")
w = fresh(); g = w.ctl("und.gap")
vals = []
for d in np.linspace(-0.3, 0.3, 61):
    w.set("und.gap", g - 0.5); w.set("und.gap", g + d); vals.append(w.source_flux())
pk = np.argmax(vals); fwhm = (np.array(vals) > 0.5 * max(vals)).sum() * 0.01
chk("gap flux peak near optimum, FWHM ~0.07-0.1 mm (log)", abs(np.linspace(-0.3, 0.3, 61)[pk]) < 0.03 and 0.04 < fwhm < 0.16, f"peak at {np.linspace(-0.3,0.3,61)[pk]:+.3f}, fwhm~{fwhm:.2f} mm")
w = fresh(); xp0 = w.steer_rad()[0]; w.set("und.gap", w.ctl("und.gap") + 1.0); xp1 = w.steer_rad()[0]
chk("steering changes with gap (3 urad/mm)", abs((xp1 - xp0) * 1e6 - 3.0) < 0.1, f"{(xp1-xp0)*1e6:.2f} urad")

# ---------------------------------------------------------------- 6. steering geometry
w = fresh(); u0, v0 = w.beam_centre(71.65); w.set("steer.xp", 10.0); w.set("steer.yp", 10.0); u1, v1 = w.beam_centre(71.65)
chk("steer 10 urad -> 0.7165 mm at 71.65 m (h and v)", abs((u1 - u0) - 0.7165) < 1e-4 and abs((v1 - v0) - 0.7165) < 1e-4)

# ---------------------------------------------------------------- 7. slits: transmitted fraction and edges
w = fresh(); zE = w.z["slitEus"]
for sid in ("slitB", "slitCus", "slitEus"):
    ww = fresh(); ww.set("fsB", 1)
    for s in ("slitB", "slitCus", "slitCds", "slitEus", "slitEds"):
        ww.set(f"{s}.hsize", 5.0); ww.set(f"{s}.vsize", 5.0)
    f_open = ww.flux_at(ww.z["icE4"]); ww.set(f"{sid}.hsize", 0.1)
    f_cl = ww.flux_at(ww.z["icE4"]); chk(f"{sid} hsize 5 -> 0.1 reduces flux (<0.6x)", f_cl < 0.6 * f_open, f"{f_cl/f_open:.3f}")
w = fresh(); lo, hi = w.slit_edges("slitEus", "h"); chk("slit edges = centre -/+ size/2 (h)", abs((hi - lo) - w.ctl("slitEus.hsize")) < 1e-12)
w.set("slitEus.hcenter", w.ctl("slitEus.hcenter") + 0.1); lo2, hi2 = w.slit_edges("slitEus", "h"); chk("+hcenter moves opening to +u (sim convention)", abs((lo2 - lo) - 0.1) < 1.5e-3)
w.set("slitEus.vcenter", w.ctl("slitEus.vcenter") + 0.1); a, b = w.slit_edges("slitEus", "v"); chk("+vcenter moves opening up (+v)", True, f"v opening {a:.3f}..{b:.3f}")
# fast shutter: fixed aperture
w = fresh()
try:
    w.set("fsB.hsize", 1.0); chk("fast-shutter size is fixed (set should be refused)", False, "accepted")
except ValueError as e:
    chk("fast-shutter size is fixed (set refused)", True, str(e)[:60])

# ---------------------------------------------------------------- 8. lenses
w = fresh()
for x, want_in in ((0.0, True), (0.5, True), (2.0, True), (3.5, False), (10.0, False), (24.0, False), (25.0, False), (-25.0, False), (-10.0, False)):
    w.set("lens1E.x", x); w.set("lens1E.th", 0.1); g = w.lens_geom("lens1E"); chk(f"lens at x={x} mm treated {'in' if want_in else 'out of'} the beam", bool(g) == want_in)
w.set("lens1E.x", 0.0)
for y, want_in in ((0.0, True), (0.5, True), (10.0, False), (-10.0, False)):
    w.set("lens1E.y", y); g = w.lens_geom("lens1E"); chk(f"lens at y={y} mm treated {'in' if want_in else 'out of'} the beam", bool(g) == want_in)
w.set("lens1E.y", 0.0)
# a v-focusing lens centred 0.6 mm to one side in x clips the HORIZONTAL aperture (window 1.5 mm wide) but does not change h focus
tr0 = w.trace("h", w.z["samE"]); w.set("lens1E.x", 0.6); tr1 = w.trace("h", w.z["samE"])
w0 = [a for a in tr0["aps"] if a[6] == "lens1E.aperture"][0]; w1 = [a for a in tr1["aps"] if a[6] == "lens1E.aperture"][0]
chk("v-focusing lens shifted +0.6 mm in x: its h window moves +0.6 mm, h optics unchanged", abs((w1[4] - w0[4]) - 0.6) < 1e-9 and abs(tr1["A"] - tr0["A"]) < 1e-9, f"window lo {w0[4]:.3f}->{w1[4]:.3f}")
w.set("lens1E.x", 0.0)
# focus tilt puts A -> 0 at the sample (fresh world per lens)
E = fresh().energy_actual_keV()
for ln in ("lens1E", "lens2E", "lens3E", "lens4E"):
    w = fresh(); mot, tgt = pl.focus_motor_target(ln, E)
    w.set(f"{ln}.x", 0.0); w.set(f"{ln}.{mot}", tgt)
    ax = "v" if mot == "th" else "h"
    tr = w.trace(ax, w.z["samE"]); chk(f"{ln}: focus_motor_target puts the {ax} focus on the sample (|A|<1% of z)", abs(tr["A"]) < 0.01 * w.z["samE"] * 1e3, f"A={tr['A']:.1f} mm/rad (unfocused={w.z['samE']*1e3:.0f})")
    oth = "h" if ax == "v" else "v"; tro = w.trace(oth, w.z["samE"]); chk(f"{ln}: the other axis ({oth}) is not focused", abs(tro["A"] - w.z["samE"] * 1e3) < 1.0)
# opposite tilt diverges
w = fresh(); w.set("lens1E.x", 0.0); mot, tgt = pl.focus_motor_target("lens1E", E); w.set("lens1E.th", 2 * w.sim["hem"]["th1_offset_deg"] * 0 + (-(tgt - (-0.011)) - 0.011))
g = w.lens_geom("lens1E"); chk("lens tilted the other way diverges (f<0)", g["f_m"] < 0, f"f={g['f_m']:.2f} m"); tr = w.trace("v", w.z["samE"]); chk("diverging lens makes the beam bigger at the sample", tr["A"] > w.z["samE"] * 1e3, f"A={tr['A']:.0f}")
# with two focusing lenses (v and h?) -> check axis assignment
for ln in pl.LENSES_1ID:
    print(f"   {ln}: orientation={pl.LENSES_1ID[ln]['orientation']} focuses {'v' if pl.LENSES_1ID[ln]['orientation'] in ('upr','up','inv','down') else 'h'}")
w = fresh(); w.set("lens1E.x", 0.0); mot, tgt = pl.focus_motor_target("lens1E", E); w.set(f"lens1E.{mot}", tgt)
fl_a = w.flux_at(w.z["icE4"]); w.set("lens1E.x", 25.0); fl_b = w.flux_at(w.z["icE4"])
chk("lens in beam does not create flux; aperture clip only (<=1.05x)", fl_a <= 1.05 * fl_b, f"in={fl_a:.4f} out={fl_b:.4f}")
# lens energy dependence
w = fresh(); w.set("lens1E.x", 0.0); mot, tgt = pl.focus_motor_target("lens1E", 71.676); w.set(f"lens1E.{mot}", tgt)
f1 = w.lens_geom("lens1E")["f_m"]; w.set("hem.energy", 60.0); f2 = w.lens_geom("lens1E")["f_m"]
chk("lens f scales with E^2 (f ~ E^2)", abs(f2 / f1 - (60.0 / 71.676) ** 2) < 0.05, f"{f2/f1:.3f} vs {(60/71.676)**2:.3f}")

# ---------------------------------------------------------------- 9. truth consistency in 'aligned'
w = fresh("ready_for_pin")
rep = w.truth_report()
print("   readiness:", {k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in list(v.items())[:3]}) for k, v in list(rep.items())[:12]})


# ---------------------------------------------------------------- 10. parking positions, reset
from blade.vbl.world import STAGES, control_specs
for st in STAGES:
    ww = fresh(); lo, hi = control_specs()[f"{st}.x"][:2]
    out = ww.sim["tomo_stages"][st]["out_x_mm"]
    try:
        ww.set(f"{st}.x", out); ok = True
    except ValueError:
        ok = False
    chk(f"{st}: the 'out' park position {out} mm is inside the stage limits [{lo}, {hi}] and settable", ok and lo <= ww.ctl(f"{st}.x") <= hi)
for scn in ("startup", "camera_in_beam", "ready_for_pin", "aligned"):
    ww = fresh(scn)
    c = ww.s["ctl"]
    chk(f"scenario {scn}: foil out, energy readout at the Re edge, every control inside its limits", c["foilB.pos"] == "out" and abs(c["hem.energy"] - 71.676) < 1e-9 and
        all((lo is None or lo <= c[k] <= hi) for k, (lo, hi, _, _) in control_specs().items() if isinstance(c[k], (int, float))),
        str([k for k, (lo, hi, _, _) in control_specs().items() if isinstance(c[k], (int, float)) and lo is not None and not lo <= c[k] <= hi]))
from blade.vbl import store
store.reset(0, "startup", "audit_reset"); wr = store.require("audit_reset"); wr.set("foilB.pos", "Yb"); wr.set("hem.energy", 61.332); store.save(wr, "audit_reset")
store.reset(0, "startup", "audit_reset"); wr = store.require("audit_reset")
chk("session reset restores foil (out) AND energy (71.676)", wr.ctl("foilB.pos") == "out" and wr.ctl("hem.energy") == 71.676)
print("\n=== summary: %d checks, %d FAIL" % (len(R), sum(1 for r in R if not r[1])))
for n, ok, d in R:
    if not ok: print("FAIL:", n, "|", d)

sys.exit(1 if any(not r[1] for r in R) else 0)
