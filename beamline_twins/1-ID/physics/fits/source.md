# Source (undulator + ring) fits for the virtual beamline

Code `blade/physics/source_fit.py`, constants `source.json`, test `tests/test_fit_source.py`. Built 2026-11-13 from the knowledge base only (no hardware). Citations: startup/tables documents as `doc_id:line`, user logs as `user log <year>`.

## Fitted

**PMU gap <-> energy <-> harmonic (2024-2026).** 88 logged (gap, harmonic, energy) rows, mostly E-calibration rows (energy = foil edge), plus 11 operator-stated points, collapsed to 16 (E, n) clusters over n = 5, 7, 9, 11, 8.5-11.3 mm, 42-100 keV (13 were used before; the rest are new, e.g. Pr, Sm, Pt, Bi, Ta, n=11).
- Period and K coefficients: with the period free the harmonics stitch together and give **lambda_u = 20.95 +- 0.47 mm** (bootstrap 0.43), i.e. the **21 mm** of the device name "U21" [2026-techcomm_jun26_explog:316]. Shipped: lambda_u = 21 (fixed), **a = 2.670 +- 0.017, b = -3.297 +- 0.014** (c fixed 0; free c = -0.03 +- 0.39, unconstrained). ln a and b are strongly correlated (corr in json); the product K(g) is what is constrained: K = 1.38 / 1.27 / 1.09 / 0.89 at 8.5 / 9 / 10 / 11.3 mm. Only the **combination** is meaningful outside 8.5-11.3 mm.
- Quality: row residual 0.115 % rms (0.31 % max) in energy = 0.0096 mm rms (0.027 max) in gap; cluster-level 0.008 mm rms. Leave-one-cluster-out error 0.62 sigma (sigma = 0.01 mm). The beamline's own calculator outputs (65.351 keV at 9.277, 61.332 at 8.820, 92.294 at 10.03 n=9) are matched to 0.1 %.
- **The old period-only fit (21.9 mm, hybrid-Halbach coefficients) is worse**: chi2 36 vs 4 on the same clusters, up to 0.03 mm gap error, and LOO error 1.6 sigma. 21.9 mm was absorbing the coefficient error; it is not a period. Whether the true K(g) has a different shape (c) cannot be told from 8.5-11.3 mm.
- **Harmonic choice**: "highest odd n whose gap is >= the limit in force" reproduces 15 of 16 logged energies (also the max-flux choice: the central-cone factor Q_n rises with n at fixed energy). Exception: 81.26 keV (n=7 used at 11.25 mm although n=9 at 9.04 mm was allowed; that log notes the calculator failed at n=9 [user log 2025]); 78.395 keV in Jul 2026 (n=7 although n=9 at 8.79 mm was allowed with an 8.5 mm limit) is a possible second.
- **Gap-limit history** (json `gap_limits`): <= 8.82 mm Nov 2024 [2024-AMsetup_nov24_explog:88]; 8.75 on 2025-01-27 [2025-startup_jan25_explog:27]; hardware minimum 8.6 mm (staff, 2025-01-28, user log 2025); 8.80 from Jul 2025 after the ID vacuum tripped (user log 2025); gap closed to 8.5 mm Jun 2026 [2026-techcomm_jun26_explog:316]; 8.543 mm used Sep 2026; and in Oct 2026 n=11 at 90.5 keV (needs 8.41 mm) was "not reachable" (user log 2026): limit in (8.41, 8.54]. The sim's 8.5 is right for 2026 but not for 2025 (8.75-8.8).
- **Wander** (E-calibration rows, same edge): within a session 0.0009 mm sd (39 values); between sessions 0.0092 mm sd pooled (Re 0.011, Tb 0.009, Yb 0.008, Au 0.004), no monotonic drift. The sim's 0.004 mm is neither; use 0.001 within, 0.009 between sessions (0.12 % in energy at n=7).
- **Steering <-> gap-peak consistency** (not a fit): off-axis red shift dE/E = (gamma theta)^2/(1+K^2/2). The Au-edge peak sat at 9.080 instead of 8.995 mm and the flux was x2.5 low until -11 urad of steering restored both [2026-mpe_jan26:33-39]; the model puts 11 urad at +0.065 mm (logged +0.085, i.e. 12.6 urad). 1 urad = 0.025 mm at 25 m [2026-techcomm_jun26_explog:140] = 0.072 mm at 71.6 m.

**SCU 2022 - Apr 2023** (current-tuned, lambda_u = 18 mm [2023-lastlight_mpe_apr23:223], ring 7 GeV, 6 GeV on 2023-04-23 [:191,:212]). K(I) = 0.444 + 2.914e-3 I - 6.22e-7 I^2 (bootstrap sd 0.05, 2.1e-4, 1.9e-7), 180-825 A, rms 0.4 % on 19 anchor points (n=5 for the 2022 series, 7 for Au/Bi/Ir edges, 11 for the 6 GeV 587-825 A tracking series) and 1.2 % on all 24. **The logs' harmonic labels do not match physics**: "n=9" at 587 A is n=11, "n=7" at 406.5 A is n=8, "6th" at 358 A is n=7; even harmonics occur. One point (621 A, Apr 2023) is 4.8 % off (n=8) or +6 % (n=9): unresolved. Harmonic numbers for 5 points are inferred, flagged in the json.

## Only assumed

- Ring energy 6 GeV (PMU), 7/6 GeV (SCU): not fitted.
- **Gap-scan width**: 0.98 % relative, n-independent, from one quoted number (0.07-0.1 mm at n=7). I could not find that number in the log text (2026-mpe_jan26 lines 59-65, 108-113 have none: it is in a plot). Physics says the width is nearly n-independent (2 sigma_eps, n-free, plus a natural 0.9/(nN) that falls with n), so the sim's `rel_fwhm * n` is right at n=7 only. Scan practice bounds it to 0.02-0.2 mm.
- **Flux vs ring current** is NOT tested: "132 -> 175 kHz at 200 mA" is the operators' own extrapolation [2025-startup_jan25_explog:37-41]. Top-up holds 200.1 +- 0.2 mA at beamtime start (Oct 2026 values); modes: 200 standard, 180 brightness 162-bunch [2025-startup_jan25_explog:20], 100-140 timing 48-bunch [2024-AMsetup_nov24_explog:25].
- **Source size**: not derivable. 17-23 um (V) / 27-30 um (H) spots [2026-Brightness_mode_feb26:44,65] over a 0.056 demagnification (3.8 m / 67.7 m) would mean a 300-540 um source: the spot is aperture/lens-limited, so the sim's 30/20 um is a focal-spot size, not a source size. No literature values used.

## PENDING (physics, why, what unlocks it, effort)

| model | why it matters | data needed | effort |
|---|---|---|---|
| harmonic flux exponent / amplitude (now 0.74 from ONE 5th/7th ratio [2024-AMsetup_nov24_explog:227-234]; old 0.55 gives 0.43 vs logged 0.33) | n choice, IC counts vs energy | one fixed-setup flux (IC_B1, same slits/gain/current) at 3+ harmonics, plus the IC gas/path so response can be divided out (04_flux_ion_chambers) | 1 beam shift; 1 day of fitting |
| gap-scan lineshape per harmonic (FWHM, skew, N) | peaking procedure realism | raw IC-vs-gap files (`undscangap` outputs) for n=5,7,9,11, or digitised plots | 0.5 day if files exist |
| hysteresis size | open-first rule, scan direction | gap scan up and down, same setting, peak gap each way | 20 min beam time |
| steering vs gap coupling (urad/mm) and hotspot vs energy | WB-centre moves with gap | xBPM/WB centre at 3 gaps with fixed steering (the logs give only session scatter: 0.09 mm V, 0.035 mm H) | 30 min beam time |
| flux vs ring current | normalisation | IC_B1 while current decays or in a lower-current mode, same setup | 1 hour |
| source size / divergence (effective) | penumbra, focus | focal spot vs WB-slit size at fixed lens position; surveyed distances | 1 shift |
| K(g) shape (c) and period beyond 8.5-11.3 mm | extrapolation (phantom-beam 20-100 mm studies) | peak positions at gaps > 11.3 mm (n=3, 5 at 12-25 mm) | 0.5 shift |
| SCU harmonic labels | only if the 2022-23 era is simulated | the IDL calculator K(I) table | low |
