#!/usr/bin/env python3
"""Physics models vs numbers logged in the 1-ID experiment logs (procedure knowledge base, 2026-11-12). Independent of sim.json and of the pin alignment.
Reference values are plain numbers read from the logs (no names, no document ids); run: python tests/test_vbl_vs_logs.py"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from blade.physics import core as pcore, undulator as U  # noqa: E402


def ok(msg):
    print("PASS", msg)


_u = json.loads((Path(__file__).resolve().parent.parent / "beamline_twins/1-ID/sim.json").read_text())["undulator"]
P = _u["period_mm"]                                        # mm, sim.json undulator.period_mm (fitted 2026-11-13 together with k_coef)
COEF = tuple(_u["k_coef"])
EXP = _u["flux_model"]["exponent"]
# (label, energy keV, harmonic the operators used, logged peak gap mm [lo, hi])
PEAKS = [("Re K", 71.676, 7, 10.0255, 10.0355), ("Au K", 80.725, 9, 8.990, 9.000), ("Tb K", 51.996, 5, 10.158, 10.181), ("Yb K", 61.332, 7, 8.825, 8.825),
         ("Hf K", 65.351, 7, 9.2774, 9.2774), ("Sm K", 46.834, 5, 9.32, 9.32), ("Bi K", 90.526, 9, 9.863, 9.865), ("100 keV", 100.0, 11, 9.08, 9.10),
         ("96 keV", 96.0, 11, 8.815, 8.815), ("42 keV", 41.99, 5, 8.545, 8.545), ("55 keV", 55.0, 5, 10.678, 10.678), ("Ta K", 67.4, 7, 9.52, 9.52),
         ("65 keV", 65.0, 7, 9.2437, 9.2437)]

# 1) undulator model reproduces the logged peak gaps
res = [U.gap_for_energy_mm(E, n, P, coef=COEF) - 0.5 * (lo + hi) for _, E, n, lo, hi in PEAKS]
rms = math.sqrt(sum(r * r for r in res) / len(res))
assert rms < 0.015 and max(abs(r) for r in res) < 0.03, (rms, res)
ok(f"undulator gap model vs {len(PEAKS)} logged peak gaps: rms {rms * 1e3:.0f} um, max {max(abs(r) for r in res) * 1e3:.0f} um")

# 2) the harmonic the operators use = the one with the largest flux among those reachable above the gap limit (8.5 mm covers the 2022-24 limit of 8.6)
n_ok = 0
for lab, E, nlog, lo, hi in PEAKS:
    cand = []
    for n in (3, 5, 7, 9, 11, 13):
        try:
            g = U.gap_for_energy_mm(E, n, P, coef=COEF)
        except ValueError:
            continue
        if g >= 8.5:
            cand.append((U.harmonic_amplitude(n, g, P, EXP, coef=COEF), n))
    n_ok += max(cand)[1] == nlog
assert n_ok == len(PEAKS), n_ok
ok(f"harmonic choice (largest flux reachable above the gap limit) = the logged harmonic at {n_ok}/{len(PEAKS)} energies")

# 3) 7th harmonic is ~3x the 5th at ~61 keV (B1 360-390 vs 122 kHz)
r = (U.harmonic_amplitude(7, U.gap_for_energy_mm(61.332, 7, P, coef=COEF), P, EXP, coef=COEF)
     / U.harmonic_amplitude(5, U.gap_for_energy_mm(61.332, 5, P, coef=COEF), P, EXP, coef=COEF))
assert 2.5 < r < 3.5, r
ok(f"7th/5th harmonic flux at 61.3 keV = {r:.2f} (logged 2.95-3.2)")

# 4) foil edge width from the mono's angular acceptance: wid(E) = E * 23 urad / tan(theta_B)   (logged E_scan fits, keV)
d = pcore.d_spacing_cubic(pcore.SI_A, (1, 1, 1))
WID = {"Tb": (0.032, 0.036), "Yb": (0.048, 0.048), "Hf": (0.048, 0.048), "Re": (0.055, 0.061), "Au": (0.067, 0.077), "Sm": (0.0274, 0.0274), "Ir": (0.0617, 0.0617)}
worst = 0.0
for el, (lo, hi) in WID.items():
    E = pcore.edge_keV(el)
    w = E * 22.8e-6 / math.tan(math.radians(pcore.bragg_angle_deg(E, d)))
    err = 0.0 if lo * 0.95 <= w <= hi * 1.05 else min(abs(w - lo), abs(w - hi)) / (0.5 * (lo + hi))
    worst = max(worst, err)
    assert err < 0.12, (el, w, lo, hi)
ok(f"foil edge width formula vs {len(WID)} logged E_scan fits: worst miss {worst * 100:.0f} %")

# 5) mu*t slope at the edge midpoint ~14-20 per keV for Re (b 1.42, wid 0.058): slope = b / (wid sqrt(pi))
slope = 1.42 / (0.058 * math.sqrt(math.pi))
assert 13 < slope < 21, slope
ok(f"mu*t slope at the Re edge = {slope:.1f} per keV (logged 14-20)")
