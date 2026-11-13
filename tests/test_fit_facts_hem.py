"""Regression for the HEM energy-transform fit built from tier-A panel transcriptions (physics/fits/facts_hem.json, facts_gap.json).

The fit data are committed aggregates (energy with the outputs printed in the same screenshot), so this test needs no private knowledge base.
Run: python -I tests/test_fit_facts_hem.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from blade.physics import core, undulator  # noqa: E402

FITS = ROOT / "beamline_twins" / "1-ID" / "physics" / "fits"
H = json.loads((FITS / "facts_hem.json").read_text())
G = json.loads((FITS / "facts_gap.json").read_text())
fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not ok:
        fails.append(name)


# Z2: every logged (E, Z2) pair on the fitted curve to < 2 um; the old constant-exit form misses by > 1 mm somewhere
z = H["z2"]["points"]
worst = max(abs(core.hem_z2_mm(e) - zz) for e, zz in z)
check(f"Z2 = {core.HEM_Z2_C_MM}/tan(2 thB) {core.HEM_Z2_D_MM:+} reproduces {len(z)} logged pairs", worst < 2e-3, f"worst {worst*1000:.2f} um")
old = max(abs(core.hem_z2_mm(e, offset_mm=core.HEM_EXIT_OFFSET_MM) - zz) for e, zz in z)
check("legacy constant-exit form is off by > 1 mm (why it was replaced)", old > 1.0, f"{old:.2f} mm")
check("constants in core.py = the committed fit", abs(core.HEM_Z2_C_MM - H["z2"]["c"]) < 1e-3 and abs(core.HEM_Z2_D_MM - H["z2"]["d"]) < 1e-3)

# Chi2 polynomial
c = H["chi2"]["points"]
worst = max(abs(core.hem_chi2_deg(e) - v) for e, v in c)
check(f"Chi2(E) polynomial reproduces {len(c)} logged outputs to < 2e-6 deg", worst < 2e-6, f"worst {worst:.1e}")

# Th1/Th2 calc-record scales (fitted through the printed offsets)
for k, const in (("th1_scale", core.HEM_TH1_SCALE), ("th2_scale", core.HEM_TH2_SCALE)):
    f = H[k]
    check(f"{k}: core constant {const} = fit {f['s']:.7f}", abs(const - f["s"]) < 2e-7, f"n={f['n']}, rms {f['rms_deg']:.1e} deg")
    check(f"{k}: fit residual < 1e-6 deg (the print precision)", f["max_abs_deg"] < 1e-6)
check("Th1 scale differs from Si(111) exactly (1.0001973 vs Th2 1.00001)", H["th1_scale"]["s"] - H["th2_scale"]["s"] > 1.5e-4)
check("Th1(E) at 71.676 keV, offset 0.4863 -> 2.0672 deg", abs(core.hem_th1_deg(71.676, 0.4863) - 2.0672) < 2e-4)

# printed-offset history is monotone in the way the logs say (Th2 - Th1 constant per era)
t = H["th2_minus_th1_by_year"]
check("Th2 - Th1 = -0.347..-0.348 deg until 2024, -0.330..-0.331 from 2025 (printed offsets)",
      all(-0.3485 < t[y]["median"] < -0.3470 for y in ("2022", "2023", "2024")) and all(-0.3315 < t[y]["median"] < -0.3300 for y in ("2025", "2026")))

# gap model validation against the same-screenshot (gap, E) pairs
r = G["resid_mm"]
check(f"undulator gap model (period 21.0, fitted K) reproduces {G['n']} (gap, E) pairs to 0.02 mm rms", r["rms"] < 0.02 and r["max_abs"] < 0.05, f"rms {r['rms']:.4f} max {r['max_abs']:.4f}")
sim = json.loads((ROOT / "beamline_twins" / "1-ID" / "sim.json").read_text())["undulator"]
worst = 0.0
for row in G["rows"]:
    gm = undulator.gap_for_energy_mm(row["E"], row["n"], sim["period_mm"], coef=tuple(sim["k_coef"]))
    worst = max(worst, abs(gm - row["gap_model"]))
check("committed gap_model column = current sim.json undulator parameters", worst < 2e-3, f"{worst:.4f} mm")

print("facts_hem OK" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
