# Monochromator + energy-calibration fits (1-ID, built 2026-11-13)

Code `blade/physics/mono_fit.py`, parameters + data tables `fits/mono.json`, test `tests/test_fit_mono.py`. Data: 43 distinct E_scan fit blocks (2022-2026, 13 elements) and 129 Emon readings in the knowledge base (`lines` table; regex on `b/dif/pos/wid = x +/- err` and on the Emon printout). Startup logs are cited `doc_id:line`, experiment logs only as "user log <year>" (JSON `prov`).
Convention: `off_eV` = HEM readback at the true edge minus the xraydb edge (negative = readback low); `th1_err_mdeg = -off_eV/|dE/dTh1|` (true minus set Th1 offset). 1 mdeg = 24 / 45 / 72 eV at 52 / 71.7 / 90.5 keV.

## FITTED / VALIDATED
| item | result | residual / n |
|---|---|---|
| edge offset (all 43 scans) | mean -44 eV, sd 44 eV = **+1.2 +- 1.15 mdeg**; Re only (2025-26) -42 eV, **session sd 17.5 eV = 0.39 mdeg** | n 43 / 12 |
| offset time structure | stochastic with a trend: Re 2025-26 **+2.6 +- 0.85 eV/month** (detrended rms 12 eV); the Th1 offset itself moved 0.4873 -> 0.4863 (**-0.084 mdeg/month = +3.8 eV/month**): consistent. 2022 was wilder (-143 .. -20 eV); Mar 2023 and Oct 2024 Re were **+81 / +66 eV** (after the 2023 shutdown the offset jumped -7.7 mdeg: 0.4950 -> 0.4873) | |
| one angle offset vs one energy offset | constant-eV (-48.7 eV, rms 23.5) and constant-angle (1.03 mdeg, rms 30.2) models are **not separable** (F-test p~0.12); d-scale + angle fit: scale -2.0e-3 +- 0.5e-3 but rms only 22.9 -> not significant. Tb sits -60 +- 8 eV (2.5 mdeg) every time, Re -42, Au -28..-45 (one -120 outlier) | n 27 (2025-26, Pt excluded: +76 eV, scan inherited from a high-resolution-mono run, unverified) |
| Th1 = theta_B(Si 111) + offset | 2023 triple (51.8/71.2/90.5 keV) fits one offset 0.4968 to **<0.0004 deg**; free d-scale -6e-4 +- 6e-4 (3 values quoted to 0.001 deg): Si(111) at 3.1356 A holds to <0.1 %; Th1 and Th2 offsets moved together 2025->26 (-1.0 / -1.1 mdeg) | n 3 |
| **Jul-2026 anomaly (08 item 8)** | the Th **zero was re-referenced between Jul 7 and Jul 15 2026**: derived Th1 offset +0.037 (Jul 7, assumed 78.395 keV) -> **-0.333** (Jul 15 calibrated) -> -0.327 (Sep 11); Th2 offset +0.084 -> -0.271 -> -0.236 (Th2-Th1: +0.046, +0.062, +0.092 deg). The Bragg model still holds, but only one energy (71.676) is logged afterwards. First state on Jul 15 was **17.1 mdeg = 775 eV** off. Sep log: "should use a new reference for energy control". | startup logs |
| foil step b (E_scan) | Re 1.425 +- 0.025 (18), Au 1.373 +- 0.016 (8), Yb 1.391 (2), Tb 0.774 +- 0.003 (5), **Hf 1.152 +- 0.009 (3)**, **Sm 0.913**, **Ir 1.591**, Ta 0.967, **Ho 0.828**, Pt 1.439, Bi 1.245, Tm 0.750; Pr 1.0 = operator target only. Sim values to change: Ho 1.2 -> 0.83, Ta 1.3 -> 0.97, Hf 1.35 -> 1.15; add Sm, Ir, Pt, Bi, Tm | scatter between logs 0.3-2 % |
| b physics | b = (mu_above - mu_below) t_eff (xraydb, edge +-0.05 keV) reproduces every b to <0.1 % by construction; **t_eff = 0.063-0.23 mm** (Ta 0.0635, Tb 0.0675, Ho 0.075, Re 0.082, Hf 0.090, Ir 0.095, Pt 0.094, Au 0.105, Yb 0.19, Bi 0.23: plausible 2.5-9 mil foils; +-10 % absolute because it absorbs table error/harmonics). Pre-edge `dif` = 0.60 b (0.54-0.64): the calc record carries ~0.3 on top of mu_below t. **Operator target ut = b to 1 % (mean 0.993, sd 0.021, 8 logs)**. | |
| edge width | one-term law `wid = E cot(theta_B) * 22.8 urad` (sim: 23): rms 4.1 eV, worst well-measured element 9 %; two-term (xraydb K-hole width as Lorentzian x Gaussian `E cot(theta) * 8.86 urad`): rms 3.7 eV, worst 7 %; Ho (1 scan) is 12-15 % off in both. Re wid repeats to 1.3 eV (n=17); no dependence on WB slit 0.3-0.6 mm | n 43 |
| Emon <-> energy | `mu_t = b + (b/2) erf((E - pos - 7.6 eV)/wid)`; inverse recovers the E_scan `pos` of the same session to **sd 9.3 eV** (n 42); valid |mu_t-b| < 0.4 b. A 0.0001 deg step of Th1+Th2 moves Re mu_t by 0.06 (logged 0.071); one Th2 tweak = +2.7 eV = 0.3 x 0.2 mdeg (one 0.0002 deg step): sim coupling 0.3 and step size are consistent | |
| startup truth spread | **th1_err_mdeg ~ N(1.2, 1.0)** legacy (rms about zero 1.65; the 0.5 assumed is too small, 1.2 of the reconciliation note equals the same data's rms scale); Re-only 0.39; **post-reset (Sep-Nov 2026): N(0.19, 0.22)** (12 Emon, operators calibrating to nominal); first state after a reference change 17 mdeg | |
| in-session drift | consecutive Emon at fixed E_hem: zero mean, **random walk 1.10 eV/sqrt(h)** (rms 4.1 eV over 3-60 h, 22 pairs) | |
| dump shifts | -5.7 (Yb 2024), +11.8 (Re 2025), -2.2 eV (Pr 2026); flux -7 % on return, -3 % after E+Th2 retune (2025): **sd 9 eV, n=3 (weak)** | |
| heat load | dT = 18.3 K/mm^2 x WB area: 3 K at 0.4x0.4, 10 K at 0.8x0.7 (2 points, 1 parameter). INFERRED: Si lattice expansion at 85 K (~-0.4e-6/K) gives <0.5 eV, far below the 5-12 eV dump shifts, so those come from slope error/bending/mount, not lattice | |
| E_scan time | 539.85 s (2022-03..2024-08), 387.35 s (2024-10..2025-06), 196.85 s (2025-07..2026); boundaries are bracketed by the dates in `mono.json` | |

## ASSUMED (unchanged in sim.json)
Thermal tau = 420 s and th2_shift 0.004 deg/kW (see P1); Th2 rocking FWHM 2 mdeg (P2); Th2-to-energy coupling 0.3 (consistent with one logged point); Emon duration per call.

## Th2 rocking curve, bounds only
Physical prior: Si(111) Darwin FWHM = **3.84 urad = 0.22 mdeg at 71.7 keV (275.2/E[keV] urad)**, two parallel crystals ~1.4x = 0.31 mdeg. Log evidence is only: flux 520 -> 562 kHz (x1.08) after a retune (offset = 0.169 FWHM for a Gaussian), cold-start flux 225 -> 430 kHz (offset 0.486 FWHM, includes the gap), one Th2 tweak = 0.2 mdeg. Conditional log-based range **0.6-6 mdeg**; sim's 2 mdeg is inside it and 7x the Darwin prior. Not identifiable.

## HEM bandwidth (task e): what is separable
Not separable. The natural K-hole width (xraydb 16-63 eV, Lorentzian FWHM, ~E^1.78) and the angular term (~E^2) rise together over 42-91 keV, so rms stays 3.5-4.1 eV for every split from "0 natural, 16 urad angular" to "1.5x natural, 3 urad" (profile in `fits.edge_width.profile_natural_width_scale`); the free-scale fit degenerates. With natural widths at face value the Gaussian instrument term is sigma_E = 23 eV at Re (FWHM 54 eV, 8.9 urad) vs Si(111) Darwin ~10 eV, so the optic/divergence term, not the reflection, dominates; slit independence points to bending/mosaic or source divergence, not the WB aperture.

## PENDING models (what, why, data needed, effort)
| id | model | why it matters in the VBL | data/measurement that fixes it | effort |
|---|---|---|---|---|
| P1 | thermal relaxation (tau, amplitude, dependence on WB area/power) after beam on or a dump | post-dump retune loop (mu_t, flux -3..-7 %) and the cold-start flux halving | repeated Emon at the slope point every 1-2 min for 1 h after a dump, with IC_B1 logged in parallel; at two WB sizes | ~2 h of beam time, 2 dumps |
| P2 | Th2 rocking FWHM and its energy coupling | Th2 tweaking is the flux optimisation step | one Th2 scan +-5 mdeg, 21 points, IC_B1 and Emon at each point, at 52 / 72 / 90 keV | 20 min |
| P3 | instrument vs natural width; HEM bandwidth | foil edge sharpness, resolution claims | E_scan of one foil at WB 0.1 / 0.3 / 1.0 mm and with a different HEM crystal/order; or the narrower HRM | 30 min |
| P4 | Th1 offset vs energy (d-scale vs angle offset) | which error model the simulator draws | Emon/E_scan at 4+ energies (Tb, Hf, Re, Au, Bi) within one session without re-tuning, in both eras | 1 h |
| P5 | Th1/Th2 relation of the re-referenced HEM (post Jul 2026) | all Th numbers after Jul 2026 | Th1/Th2 at 3+ calibrated energies (only 71.676 keV is logged) | 30 min |
| P6 | drift/dump statistics with independent events | currently n=22 pairs, n=3 dumps | log every Emon with timestamp and note dumps; ~10 more dumps | passive |

## Suggested sim.json changes (not made)
`hem.edge_wid_rad` 2.28e-5 (or the voigt model), `foils.b` as above plus Sm/Ir/Pt/Bi/Tm, startup `th1_err_mdeg` sd 1.0 (mean +1.2) or 0.22 for a post-Jul-2026 scenario, calibrate-procedure time by era, reduce `thermal.th2_shift_deg_per_kW` (observed dump shifts 2-12 eV = 0.05-0.3 mdeg vs 3.8 mdeg per kW assumed times coupling 0.3), Th2 rocking inside 0.6-6 mdeg.
