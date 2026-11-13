# 10. Procedure knowledge base vs the virtual beamline (reconciliation, 2026-11-12)

Source: the 14 procedure records built from the logs (`knowledge_base/`, data in `kb_1ID/procedures/`; 743 logged numbers, each with a log citation). Each record has `vbl_relevance`
notes; this page checks them against `sim.json` / `blade.vbl` / `blade.physics`. **Status: partial.** Checks and one test are done; the sim.json changes are prepared but NOT adopted
(file `sim_proposed_2026-11-12.json` next to `sim.json`), because the end-to-end pin alignment (`align_adaptive`) fails in `tests/test_vbl.py` (see 10.4) and I did not want to
change the sim while that is unexplained.

## 10.1 Already consistent with the logs (no change needed)
| item | logged | sim |
|---|---|---|
| IC_B1 at 200 mA, 50 nA/V, WB 0.3x0.3 | 174-178 kHz; 0.5x0.5 gives ~300 kHz (x1.72) | 176 kHz; x1.66 |
| IC dark / clip | 0.3-2 kHz; counter clips at 999988 | 1 kHz; 1000 kHz |
| undulator period / gap model | 13 logged peak gaps (2024-26), n=5..11, 42-100 keV | period 21.9 mm; rms 16 um, max 33 um (refit 21.899) |
| gap scan | +-0.2 mm, 40 pts x 1 s; FWHM ~0.1 mm | FWHM 0.084 mm (mild; rel_fwhm 0.0014 -> 0.0017 would give 0.10) |
| foil edge width | wid = E*23urad/tan(theta_B): 9 % worst over Tb, Yb, Hf, Re, Au, Sm, Ir | same formula |
| mu*t slope at edge | 14-20 per keV (Re) | 13.8 |
| fast shutter | 3.0 mm wide, Y span 1.5-1.82 mm, centres vary ~0.6 mm between beamtimes | 3.0 x 1.7; fs_zero 0.4 mm |
| tomo pixel sizes | 1.17 um (pg1/pg5), 0.69 um (gh1) | profile s1id identical |
| lens tilt optimum vs prediction | within 0.002-0.010 deg | truth 0.004 deg |
| WB-slit centre tweaks | 10-50 um | truth 0.04 mm |

Test: `tests/test_vbl_vs_logs.py` (physics only; passes).

## 10.2 Discrepancies found (fixes prepared in `sim_proposed_2026-11-12.json`)
| item | sim had | logs say | proposed |
|---|---|---|---|
| harmonic chosen at an energy | largest ASSUMED amplitude (prefers low n): n=5 at 61 keV, n=7 at 81 and 91 keV | operators use the highest harmonic whose gap >= the gap limit (n=7 at 61, 9 at 81-91, 11 at 96-100) and the 7th gives ~3x the 5th at 61 keV | `undulator.flux_model` = Kim flux factor of the harmonic at its own gap, exponent 0.55: 13/13 choices, ratio 3.07 (code: `harmonic_amplitude` in `blade/physics/undulator.py`, `World.harm_amp`; inert while sim.json has no `flux_model`) |
| gap limit | 8.75 mm | 8.6 -> 8.75 (Jan 2025) -> 8.80 after a vacuum trip | 8.80 |
| foil step b | Hf 1.35 (assumed), Re 1.40, Tb 0.78; no Sm/Ir | Hf 1.14-1.16, Re 1.40-1.45, Tb 0.768-0.777, Sm 0.913, Ir 1.591 | update; add Sm, Ir |
| attenC thickness | 4 positions [0, 0.5, 1, 2] mm (assumed) | 0.232 cm Cu per step, 1.645 cm at position 7 | 8 positions |
| IC dark baselines | all 1 kHz | IC1-E 0.835, IC3-E 0.474, IC4-E ~0.35, IC6-E ~1.9 kHz | `ic.dark_kHz_by_ic` (code ready in `World.ic_kHz`) |
| startup truth spreads (assumed) | gap 0.04 mm, Th1 0.5 mdeg, steering 2.5 urad | gap rms 0.016 mm; mono readback 6-115 eV off the edge = 0.1-2.8 mdeg; steering requests 2.5-5 urad | 0.02 mm, 1.2 mdeg, 3.5 urad |

## 10.3 Logged behaviour the simulator does not model yet
- Slit blade stuck / reported gap larger than commanded (B inboard blade, 2025); slit blade soft limits.
- Fast-shutter leakage: aligned FS reads the same as PSS-closed within ~20-60 counts on IC4-E / IC6-E; a misaligned one leaks.
- mu*t calc-record zeroing failure (J, K, L offsets not zeroed give nonzero or negative mu*t).
- Beam-dump recovery: mu*t drifts +0.1-0.3 and flux drops 3-7 % until Th2 / energy are re-tweaked; E_scan lasts 540 -> 387 -> 197 s over the years (sim time per action).
- Hotspot vs energy: ~0.3 mm at 100 keV and up to 1.4 mm for Au in E (the sim's gap-steering coupling gives ~0.2 mm), hotspot reference pixels differ by camera crop (960,600 on 1920x1200; 1290-1605 on gh1).
- Th2 rocking width is still UNCONSTRAINED (assumed 2 mdeg): logs only say flux can fall to ~50 % when Th2 is off, an 8 % gain (520 -> 562 kHz) after a retweak, and that 0.0001-0.0002 deg steps visibly move mu*t.
- Absolute flux vs energy is anchored (176 kHz at every energy), so the real energy dependence of IC counts is not simulated.
- Initial rotation-axis errors in the startup scenario: omega zero 0.0156-0.82 deg, wedge 0.0005-0.01 deg, tilt 0.02-0.59 deg (logged); attenB positions 5-8 (position 8 = 6.20 mm Cu logged).
- NF camera / beamstop (2048x2048, 1.48 um pixel, bbY ~5 um per mm of DetZ) and the FF detectors are outside the vbl scope.

## 10.4 Open problem (not caused by the above)
`tests/test_vbl.py` passes 9 checks, then `registry.invoke("align_adaptive")` on `vbl_reset(seed=11, scenario="ready_for_pin")` returns "pin not found within the search radius / step budget".
The same failure occurs with the ORIGINAL sim.json (re-checked 2026-11-12), so it is independent of the proposed values; the code edits made today are inert without `flux_model`. To be investigated separately.
