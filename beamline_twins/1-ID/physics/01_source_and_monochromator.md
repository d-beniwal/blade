# 1. Source and monochromator: what changes when you change the energy

Code: `blade.physics.undulator`, `blade.physics.core` (`hem_th1_deg`, `hem_z2_mm`, `energy_shift_from_angle_keV`, `edge_keV`). Citation keys: see `README.md`.

## 1.1 Undulator (SCU until spring 2023, PMU after)

Two different devices appear in the logs. **Superconducting undulator (SCU)** in 2022 to April 2023, tuned by *current* in amperes; **permanent-magnet undulator (PMU)** from the APS-U era (logs from Jul 2024 on), tuned by *gap* in mm. The physics is the same: harmonic *n* peaks at `E_n = n * 0.9496 * E_ring^2 / (lambda_u (1 + K^2/2))`, with K set by the field (gap or current). **Lower field (larger gap, lower current) gives smaller K and a higher photon energy**, so the operators pick the harmonic and tune the device until the flux peak sits on the mono energy.

| device | harmonic | setting | mono energy | cite |
|---|---|---|---|---|
| SCU | 5 | 353.9 A / 302.27 A / 267.9 A | 65.38 / 71.70 / 76.32 keV | [O22:L24,L60], [D22:L58] |
| SCU | 7 | 425.2 A (B = 0.926 T, 2.89 kW) | 80.8 keV | [J22:L38] |
| SCU | 7 / 9 | 406.5 A / 587 A | 71.635 keV (n=7) / 71.676 keV (n=9) | [L23:L191-232] |
| PMU | 9 | gap 8.995 mm (8.985 mm + taper +0.010 in 2026) | 80.725 keV (Au K) | [S25b:L25], [M26a:L44] |
| PMU | 7 | gap 8.82-8.84 / 9.28 / 10.02-10.025 mm | 61.3 / 65.4 / 71.7 keV | [B26], [M26a:L59-63], [S25b:L34], [A24:L210-253] |
| PMU | 5 | gap 10.158 mm | ~52 keV | log line in `logindex.py params gap_mm` |

*SCU:* energy falls ~0.12-0.13 keV per ampere at h=5 (inferred from the three points above). Harmonic scale factor for the SCU18-3 calculator had to be 0.88 (not 0.865) to land n=9 at 587 A [L23:L222-232]. Tracking n=9 upward gave mono peaks 61.67 / 57.94 / 56.16 / 54.34 / 52.71 keV at 700 / 750 / 775 / 800 / 825 A [L23:L236-278]. Quenches near 815 and 826 A; ramp slowed to 0.5 A/s above 700 A [L23:L262-271]. The best WB-slit centre moved with SCU current (spread ~0.8 mm horizontally): beam steering varies with the device setting [L23:L218-278].

*PMU model (this project's inference).* `undulator.fit_period_mm` fits a hybrid-Halbach, 6 GeV model to the logged (gap, n, E) points and returns **period 21.9 mm, 0.17 % rms over five points**; fitting only the first two (8.995 mm/n=9/80.725 keV and 10.025 mm/n=7/71.676 keV) already predicts the other three within 0.6 %, and predicts 10.143 mm for 51.996 keV at n=5 where the log has 10.158 mm. The device spec, ring energy (6.0 GeV assumed) and magnet-model coefficients are not documented in the logs, so treat the period as a consistency result. Sensitivity from the model: **dE/dgap = +8.3 keV/mm (n=7, 71.7 keV)** and +12 keV/mm (n=9, 80.7 keV); the flux peak is only ~0.07-0.1 mm wide in gap at n=7 [M26a:L60,L113].

Operating rules seen in the logs:
- **Hysteresis.** Scans started from the end of the previous scan did not overlay; re-starting from an open gap (~9.5 mm) did. "Always open the gap before scanning or setting it; use `setundgap`; scan from high to low gap" [M24:L56-69].
- **Peak gap wanders by ~0.004 mm** between scans/days [M24:L70,L102,L251]; the gap used for the 61.3 keV Emon drifted 8.8367 to 8.8233 mm over Nov 2024 [A24], and 8.8169 to 8.8184 mm in 12 h in Feb 2026 [B26:L33,L64].
- **Steering matters as much as gap.** At the start of 2026 the Au-edge flux was low by 2.5x with the flux maximum at gap 9.080 mm instead of 8.995 mm; a steering change of -11 urad (IB) restored the expected flux at the expected gap (with taper +0.010) [M26a:L33-44]. In June 2026 steering Xp 15 -> 5 urad did not change the off-axis "phantom" beam seen at large gap [T26:L98,L138-146].
- Gap limit 8.75 mm (Jan 2025); GUI fields locked then, gap set with `caput S01ID:DSID:ScanGapC` [S25a:L26-27].
- **Flux scales linearly with ring current**: IC_B1 132 -> 175 kHz and IC_B3 361 -> 477 kHz from 150 to 200 mA (x1.33) [S25a:L37-41].
- **Brightness mode** (Feb 2026): vertical beam FWHM ~17 um vs ~23 um in regular mode (-26 %), horizontal ~30 vs ~27 um (+9 %); ion-chamber counts ~10 % lower after a steering adjustment (before/after assignment inferred) [B26:L44,L55,L65; L30,L33,L64]. The logs give both "162-bunch high coupling" [S25a:L22] and "216 bunches - high coupling / swap-out" for the fill pattern.

## 1.2 HEM monochromator (the energy)

Energy is set by an EPICS userTransform record (`userTran3`, "HEM energy") that converts E into crystal angles and positions. Verified by this project against the logs:
- **Th1 = theta_B(Si 111) + Th1_offset**, where `theta_B = asin(hc/(2 d E))`, d = 3.1356 A, hc/2d = 1.977. Logged 2023 values Th1 = 2.684 / 2.089 / 1.748 deg at 51.81 / 71.15 / 90.52 keV are theta_B = 2.187 / 1.592 / 1.252 deg plus ~0.497 deg [S23 screenshots]; 2026: Hf edge 65.278 keV gives 2.222 deg with offset 0.4863 [M26a]. (`core.hem_th1_deg`)
- **Z2 * tan(2 theta_B) = 32.9 mm, constant** over 51-90 keV and 2022-2025 (428.5 / 591.8 / 755.3 mm at 51.81 / 71.15 / 90.52 keV; 595.6-596.1 mm at 71.7 keV): the second crystal slides along the beam to hold a **constant exit offset (fixed-exit design)**. (`core.hem_z2_mm`; derived here, not from a drawing.) Chi2 follows a polynomial in E (0.0263 / 0.0285 / 0.0321 / 0.0347 deg at 61.3 / 65 / 71.7 / 76.3 keV, 2022).
- **Th1 offset is the operators' fine-tuning knob and drifts slowly:** 0.4944 (Jun 2022), 0.4953 (Oct 2022), 0.4963 (Nov-Dec 2022), 0.495 (Mar 2023), 0.4873 (Jan 2025), 0.4871 (Jun 2025), 0.4863 (Feb 2026); Th2 offset 0.1573 (2025), 0.1562 (2026).

**Sensitivity (core.energy_shift_from_angle_keV):** 1 mdeg of Th1 = -24 eV at 52 keV, **-45 eV at 71.7 keV**, -72 eV at 90.5 keV. Checks: a +0.00055 deg Th1 change gave exactly the -25 eV shift needed in Jun 2025 [S25b screenshots]; the 2022 offset change 0.4953 -> 0.4963 deg explains the +35 eV shift of the Re readout between Oct and Dec 2022 [O22, D22]; a 0.008 deg crystal tweak is ~460 eV, "a larger than usual energy shift" after mono warm-ups [S25a:L23].

### Calibrating the energy on a foil edge
`Emon` (foil in -> prints `mu_t, Emon, Etr, E_HEM, UGap, foil, foilpos, attenpos`, then restores foil/attenuator) and `E_scan` (~6.5 min; error-function fit giving edge position `pos`, width `wid`, step `b`). Edge energies are the xraydb K edges (Re 71.676, Au 80.725, Yb 61.332, Tb 51.996, Ho 55.618, Ta 67.416, Hf 65.351, Pr 41.991 keV; all reproduced by `core.edge_keV`). The operators hold the measured `mu_t` at a target `ut` (**~1.35-1.45, median 1.37**): `mu_t` is the log-ratio of foil-out to foil-in transmission and is a steep function of energy across the edge (Re jump ratio 5.06, ln = 1.62).
- **Sensitivity of the procedure:** Re at HEM 71.580 keV gave mu_t 0.946; after moving +35 eV to 71.615 keV, mu_t 1.402 [O22:L34,L65]; in Jun 2025 mu_t 1.888 at 71.660 keV (36 eV too high), 1.54 after an overnight drift, 1.45 after an 11 eV re-tweak [S25b:L96,L323-326]. So **mu_t resolves the energy scale to a few eV**.
- **The readout is not the edge energy.** Au reads the tabulated 80.725 keV, but Re reads 71.60-71.65 keV, Yb 61.26-61.28, Hf 65.28 and Ir 76.04 keV (offsets of 25-160 eV low, differing by day) [O22, D22, S25b, M26a]. The offset is set by the Th1/Th2 offsets and the thermal state; always recalibrate at the start of a beamtime and after a dump.
- **Drift:** Re readout 71.625 -> 71.600 keV over Jun 3-7, 2025, each time caught by mu_t rising to ~1.54 and restored by tweaking HEM and Th2 (Th1 +0.00055 deg, Z2 -0.21 mm for -25 eV) [S25b]; after beam dumps in Nov 2024 mu_t went 1.4 -> 1.5 -> 1.7 and was re-tuned each time [A24:L84-90,L188-191]; Re mu_t 1.4 (Jul 2026) -> 1.34 -> 1.3 (Sep 2026) [T26, M26b]; Th2 moved +0.036 deg Jul -> Sep 2026 against +0.005 deg for Th1 [T26:L554-556,L885-887].
- **Bandwidth:** fitted edge widths 0.048-0.058 keV (~7e-4 relative). The symmetric-Bragg Si(111) Darwin width at 71.7 keV is only ~10 eV (`core.darwin_width_bragg`), so the measured width is dominated by the Laue/bent-crystal and divergence terms of the real optic, not by the intrinsic reflection. (A high-resolution monochromator, HRM, in hutch B is used for ~52 keV work, with IC4 between its two crystals.)

### Thermal load
First HEM crystal heats ~+3 K at 0.4 x 0.4 mm WB and ~+10 K at 0.8 x 0.7 mm; closing the undulator gap from 35 to 8.5 mm with C1 in the beam raised C1 Si from 83.4 to 86.4 K [T26:L318,L323,L472-480]. After a cold start the flux recovers only after thermalisation and a Th2 + undulator tweak (B3 225 -> 430 kHz) [T26:L421-424]. Practical rule: **change WB slit size or gap, then wait/re-peak Th2 and the gap, then re-check mu_t.**
