"""Source-fit test (no hardware): blade.physics.source_fit reproduces the logged gap/energy/current points stored in
beamline_twins/1-ID/physics/fits/source.json within the residuals stated there.
Run: ~/miniconda3/envs/blade/bin/python -I tests/test_fit_source.py"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from blade.physics import source_fit as S   # noqa: E402

J = json.loads((ROOT / "beamline_twins/1-ID/physics/fits/source.json").read_text())
fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok:
        fails.append(name)


# constants loaded from the JSON equal the stated fit
p = J["pmu"]
check("constants loaded from json", S.CONST["coef"] == (p["coef_a"]["value"], p["coef_b"]["value"], 0.0) and S.CONST["period_mm"] == 21.0)

# --- PMU: every logged fit row, in energy and in gap
st = p["fit"]["resid_rows"]
rows = [d for d in J["data"] if d["role"] == "fit"]
worst_e = worst_g = 0.0
for d in rows:
    worst_e = max(worst_e, abs(S.energy_pmu_keV(d["gap_mm"], d["n"]) / d["energy_keV"] - 1))
    worst_g = max(worst_g, abs(S.gap_pmu_mm(d["energy_keV"], d["n"]) - d["gap_mm"]))
check("PMU energy residual <= stated max (%d rows)" % len(rows), worst_e <= st["rel_E_max"] * 1.02, "worst %.3f %%" % (100 * worst_e))
check("PMU gap residual <= stated max", worst_g <= st["gap_max_mm"] * 1.02, "worst %.4f mm" % worst_g)
rms = (sum((S.energy_pmu_keV(d["gap_mm"], d["n"]) / d["energy_keV"] - 1) ** 2 for d in rows) / len(rows)) ** 0.5
check("PMU energy rms <= stated", rms <= st["rel_E_rms"] * 1.02, "rms %.3f %%" % (100 * rms))

# nominal-energy rows (mono setting, not an edge) are looser by their own stated uncertainty
for d in rows:
    u = d.get("E_rel_unc", 0.0)
    if u:
        check("nominal-energy row %.2f keV n=%d" % (d["energy_keV"], d["n"]), abs(S.energy_pmu_keV(d["gap_mm"], d["n"]) / d["energy_keV"] - 1) <= u + 0.0025)

# the beamline's own undulator-control calculator outputs agree with the fitted model (0.1 %)
for d in [d for d in J["data"] if d["role"] == "calc"]:
    check("calculator row %.3f keV n=%d gap %.3f" % (d["energy_keV"], d["n"], d["gap_mm"]), abs(S.energy_pmu_keV(d["gap_mm"], d["n"]) / d["energy_keV"] - 1) < 0.003)

# physics sanity: E rises with gap and with n; K falls with gap; inverse round trip
check("E rises with gap", S.energy_pmu_keV(9.0, 7) < S.energy_pmu_keV(10.0, 7))
check("K falls with gap", S.k_pmu(9.0) > S.k_pmu(10.0) > S.k_pmu(11.0))
check("gap round trip", abs(S.gap_pmu_mm(S.energy_pmu_keV(9.9, 9), 9) - 9.9) < 1e-6)

# --- harmonic choice and gap-limit history
check("gap limit history", S.gap_limit_mm("2025-02-01") == 8.75 and S.gap_limit_mm("2025-08-01") == 8.8 and S.gap_limit_mm("2026-10-28") == 8.5)
clusters = {}
for d in rows:
    clusters.setdefault((d["energy_keV"], d["n"]), d["date"])
agree = 0
exceptions = []
for (E, n), date in sorted(clusters.items()):
    if len(date) < 10:
        date = date + "-15"
    sel = S.select_harmonic(E, date=date)
    if sel and sel[0] == n:
        agree += 1
    else:
        exceptions.append((E, n, sel[0] if sel else None))
hr = J["harmonic_rule"]
check("harmonic rule agrees with logs (%d of %d clusters, exceptions %s)" % (agree, len(clusters), exceptions), agree >= hr["agree"] - 1, "stated %d of %d" % (hr["agree"], hr["tested_energies"]))
check("n=11 unreachable at 90.5 keV with the 8.5 mm limit (logged: 'cannot close gap enough')", all(n != 11 for n, g in S.candidate_harmonics(90.526, S.gap_limit_mm("2026-10-28"))))

# --- gap-scan lineshape (assumed width, fitted peak position) and wander
g0 = S.gap_pmu_mm(71.676, 7)
prof = S.gap_scan_profile([g0 - 0.2 + 0.01 * i for i in range(41)], 71.676, 7)
check("scan peak at the model gap", abs((g0 - 0.2 + 0.01 * prof.index(max(prof))) - g0) <= 0.011)
half = [g0 - 0.2 + 0.01 * i for i, v in enumerate(prof) if v >= 0.5]
check("scan FWHM 0.05-0.2 mm (assumed rel width)", 0.05 <= half[-1] - half[0] <= 0.2, "%.3f mm" % (half[-1] - half[0]))
check("wander: between-session > within-session", S.gap_session_offset_sd_mm() > 5 * S.gap_session_offset_sd_mm(True))

# --- steering
check("steering 0.025 mm/urad at 25 m", abs(S.steering_mm(1.0, 25.0) - 0.025) < 1e-9)
shift = S.offaxis_gap_shift_mm(11.0, 80.725, 9)
check("11 urad off axis moves the Au n=9 flux maximum by +0.04..0.10 mm (logged +0.085)", 0.04 < shift < 0.10, "%.3f mm" % shift)

# --- SCU: stored points, in relative energy
sc = J["scu"]
w = 0.0
for q in sc["points"]:
    w = max(w, abs(S.energy_scu_keV(q["I_A"], q["n"], q["ring_GeV"]) / q["energy_keV"] - 1))
check("SCU energy residual <= stated max (%d points)" % len(sc["points"]), w <= sc["all_points"]["max_rel"] * 1.02 + 1e-9, "worst %.2f %%" % (100 * w))
anch = [q for q in sc["points"] if not q["n_inferred"]]
ra = (sum((S.energy_scu_keV(q["I_A"], q["n"], q["ring_GeV"]) / q["energy_keV"] - 1) ** 2 for q in anch) / len(anch)) ** 0.5
check("SCU rms on the non-inferred points < 1.5 %", ra < 0.015, "%.2f %%" % (100 * ra))
check("SCU energy falls with current (n=5, 7 GeV)", S.energy_scu_keV(300, 5) > S.energy_scu_keV(400, 5) > S.energy_scu_keV(446, 5))

# --- provenance hygiene: only startup/tables 'doc_id:line' or 'user log <year>' appear
ok = True
for d in J["data"] + sc["points"]:
    s = d["source"]
    if not (re.fullmatch(r"user log 20\d\d", s) or re.fullmatch(r"20\d\d-[\w.\-]+:\d+", s)):
        ok = False
        print("   bad source:", s)
check("provenance strings", ok)

print("\n%d failures" % len(fails))
sys.exit(1 if fails else 0)
