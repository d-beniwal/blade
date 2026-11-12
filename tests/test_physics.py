"""Physics-package test (no hardware): blade.physics reproduces numbers recorded in the 1-ID startup logs and the beamline's own calculators.
Run: python -I tests/test_physics.py   (needs xraydb for the material parts; they are skipped if it is missing)"""
import math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from blade.physics import core, detector, lens, undulator

try:
    import xraydb  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False
    print("SKIP: xraydb not installed (material/edge/delta checks)")

close = lambda a, b, tol: abs(a - b) <= tol
d111 = core.d_spacing_cubic(core.SI_A, (1, 1, 1))

# wavelength/energy round trip and the HEM Si(111) relation recorded in the logs (E = 6.199/(d sin th) -> coefficient 1.977)
assert close(core.energy_keV(core.wavelength_A(71.676)), 71.676, 1e-9)
assert close(d111, 3.1356, 5e-4) and close(core.HC_KEV_A / 2 / d111, 1.977, 1e-3)

# Th1 = theta_B + offset: the 2023 log's Th1 at 51.8 / 71.2 / 90.5 keV (2.684, 2.089, 1.748 deg) with the ~0.497 deg offset
for E, th1 in ((51.8, 2.684), (71.2, 2.089), (90.5, 1.748)):
    assert close(core.hem_th1_deg(E, 0.497), th1, 0.004), (E, core.hem_th1_deg(E, 0.497), th1)

# HEM second-crystal position: constant exit offset => Z2 = D / tan(2 theta_B); logged pairs 2022-2025 (mm)
for E, z in ((51.81, 428.5), (71.15, 591.8), (90.52, 755.3), (71.7, 595.9), (71.600, 595.616), (71.625, 595.827)):
    assert close(core.hem_z2_mm(E), z, 2.5), (E, core.hem_z2_mm(E), z)
assert close(core.hem_th1_deg(65.278, 0.4863), 2.222, 0.001)           # 2026 log, Hf edge

# energy shifts from crystal-angle changes (logs: +0.00055 deg Th1 <-> -25 eV at Re K; a 0.008 deg tweak is a big shift)
assert close(core.energy_shift_from_angle_keV(71.676, d111, 0.00055) * 1000, -25, 1.5)
assert 300 < abs(core.energy_shift_from_angle_keV(80.725, d111, 0.008)) * 1000 < 600

# camera pixel size = sensor pitch / magnification (logged: PG1 5X 1.172, GH1 5X 0.69, NF Retiga 5X 1.48 um/px)
assert close(detector.object_pixel_um(5.86, 5), 1.172, 1e-9) and close(detector.object_pixel_um(3.45, 5), 0.69, 1e-9) and close(detector.object_pixel_um(7.4, 5), 1.48, 1e-9)
assert close(detector.fov_mm(1940, 0.69), 1.3386, 1e-3)

# powder rings: radius grows with distance and shrinks with energy; CeO2 (111) d = 3.1244 A
r = detector.cubic_rings(detector.CEO2_A, 71.676, 1000, 200)
assert r[0][0] == (1, 1, 1) and close(r[0][1], 3.1244, 1e-3) and r[0][3] < r[1][3] < r[2][3]
assert close(detector.ring_radius_mm(71.676, 3.1244, 2000), 2 * detector.ring_radius_mm(71.676, 3.1244, 1000), 0.01)
assert detector.ring_radius_mm(80.0, 3.1244, 1000) < detector.ring_radius_mm(60.0, 3.1244, 1000)

# undulator: a period fitted to TWO logged points predicts the other logged (gap, n, E) points (2025/2026/2023 logs)
period, err = undulator.fit_period_mm([(8.995, 9, 80.725), (10.025, 7, 71.676)])
assert close(period, 21.9, 0.3) and err < 0.005, (period, err)
for gap, n, E in ((9.28, 7, 65.4), (8.84, 7, 61.3), (8.82, 7, 61.3)):
    assert abs(undulator.harmonic_energy_keV(gap, n, period) / E - 1) < 0.006, (gap, n, E)
assert close(undulator.gap_for_energy_mm(61.332, 7, period), 8.84, 0.03)
assert undulator.harmonic_energy_keV(9.0, 7, period) < undulator.harmonic_energy_keV(10.0, 7, period)     # E rises with gap

# lens: tilt <-> focal length round trip and the scale recorded in the device definitions (~0.1 deg, lens _zero offsets -0.011..-0.063 deg)
delta = 9.4e-8
t = lens.prism_tilt_for_focus_deg(67.7, 71.5, delta, 200)
assert 0.05 < t < 0.2 and close(lens.prism_focus_position_m(t, 67.7, delta, 200), 71.5, 1e-9)
assert close(lens.thin_lens_f_m(67.7, 3.8), 3.60, 0.01)
assert close(lens.crl_focal_length_m(50, 10, 1e-6), 2.5, 1e-9)       # f = R/(2 N delta) = 50e-6/(2*10*1e-6)
try:
    lens.prism_tilt_for_focus_deg(70, 69, delta, 200); raise AssertionError
except ValueError:
    pass

if HAVE:
    # edges used for the logged energy calibrations (xraydb must reproduce them)
    for el, E in (("Re", 71.676), ("Au", 80.725), ("Yb", 61.332), ("Tb", 51.996), ("Ho", 55.618), ("Ta", 67.416), ("Pr", 41.991)):
        assert close(core.edge_keV(el), E, 0.0015), (el, core.edge_keV(el), E)
    d, b = core.delta_beta("Si", 71.676)
    assert close(d, 9.4e-8, 0.1e-8)                                         # delta ~ r_e lambda^2 rho_e / 2pi
    assert close(core.delta_beta("Si", 35.838)[0] / d, 4.0, 0.05)            # delta ~ 1/E^2
    assert core.transmission("Si", 17.06, 71.676) < 0.4 and close(core.transmission("Al", 0.0, 71.676), 1.0, 1e-12)
    assert close(core.transmission("Cu", 2.0, 71.676), core.transmission("Cu", 1.0, 71.676) ** 2, 1e-9)    # Beer-Lambert
    tl = lens.prism_tilt_for_focus_deg(67.7, 71.5, lens.lens_delta("Si", 71.676), 200)
    assert close(tl, 0.0966, 0.002)
    assert core.thickness_for_mu_t("Au", 1.4, 80.73) > 0
    # the beamline's own recommended lens tilts at the Hf edge (2026 startup log: BS prediction 0.105 / -0.173 at 71.5 m, 0.111 / -0.179 at +205 mm)
    for name, focus, want in (("lens1E", 71.5, 0.105), ("lens2E", 71.5, -0.173), ("lens1E", 71.705, 0.111), ("lens2E", 71.705, -0.179)):
        motor, deg = lens.focus_motor_target(name, 65.351, focus)
        assert motor == "th" and close(deg, want, 0.0015), (name, focus, deg, want)
    assert lens.focus_motor_target("lens4E", 71.676)[0] == "phi"
print("physics OK")

# ---- the machine-readable relations file: schema, evidence keys, twin elements and every referenced function exist ------------------------
import glob, importlib, json
ROOT = Path(__file__).resolve().parent.parent
rel = json.loads((ROOT / "beamline_twins/1-ID/physics/relations.json").read_text())["relations"]
KEYS = {"J22", "O22", "D22", "S23", "L23", "M24", "A24", "S25a", "S25b", "M26a", "B26", "T26", "M26b", "headers"}
NEED = {"id", "control", "twin_elements", "physical_effect", "formula", "function", "sensitivity", "typical", "evidence", "confidence", "caveats"}
el_ids = {e["id"] for f in glob.glob(str(ROOT / "beamline_twins/1-ID/hutches/*.json")) for e in json.load(open(f))["elements"]}
ids = [x["id"] for x in rel]
assert len(ids) == len(set(ids)) >= 25
for x in rel:
    assert NEED <= set(x), (x["id"], NEED - set(x))
    assert x["evidence"] and all(e.split(":")[0].split(" ")[0] in KEYS for e in x["evidence"]), (x["id"], x["evidence"])
    assert set(x["twin_elements"]) <= el_ids, (x["id"], set(x["twin_elements"]) - el_ids)      # relations only point at real twin elements
    if x["function"]:
        if (ROOT / (x["function"].replace(".", "/") + ".py")).is_file():                        # a module (e.g. blade.alignment.axis_align): file exists
            continue
        mod, _, fn = x["function"].rpartition(".")
        assert hasattr(importlib.import_module(mod), fn), x["function"]                          # otherwise a function inside a (numpy-free) module
print("relations OK:", len(rel))
