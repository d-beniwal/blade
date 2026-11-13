# 12. Numbers read from the logbook panel screenshots (built 2026-11-13)

All 1,182 legible, value-rich EPICS/MEDM panel screenshots of the experiment logs (2021-2026, 94 logs) were transcribed, number by number, from the
pixels (53 packs, sonnet agents, full-size reads), then gated for reliability, aggregated, and used to fit and check the physics. Code: `knowledge_base/`
`facts.py` (packs, strict loader, blind audit), `factnorm.py` (device parsing + reliability tiers), `factstats.py` (registry, limits, steps, baselines),
`factphysics.py` (fits). Raw per-image values stay in the private KB (`kb_1ID/`); this folder gets aggregates only
(`fits/facts_hem.json`, `fits/facts_gap.json`, `../panel_registry.json`, `../panel_baseline.json`). Tests: `tests/test_fit_facts_hem.py`, `tests/test_facts_reliability.py`.

## 12.1 Reliability: what is used, and how we know it is accurate

**Rule (user, 2026-11-13): a value that is not reliable is not used - at parsing and at analysis.** Every reading gets a tier:

| tier | meaning | used for |
|---|---|---|
| **A** (26,365 = 79.6 %) | conf >= 0.9, no doubt note, image legible, passed the cross-checks | every number reported here (fits, limits, offsets, steps, baselines) |
| B (5,577 = 16.8 %) | minor doubt: conf 0.8-0.9, "last digit cropped", partly cropped window, partial image | counted only |
| **C** (1,163 = 3.5 %) | null value, conf < 0.8, a note that says guessed / assumed / inferred / unclear / covered / cursor / tooltip / differs from the log text / truncated or cropped title / no printed label, illegible image, failed cross-check | never |

Objective cross-checks inside one window (they do not rely on the agent's own confidence): the dial-user relation must be one calibration (dial = user + c, or
dial = c - user with swapped limits for a reversed motor), the readback must sit inside its limits, hi > lo, slit size >= 0. On 1,281 checkable motor windows only
2 groups failed: one real digit transposition (HEM Th2 dial readback -3.2654375 for -3.2564375) and one Elmo readback above its limit. (A first version of the check
raised 3 false alarms on reversed-direction motors; fixed and covered by the test.)

**Blind audit.** One random image from each of the 53 packs (836 tier-A readings, labels only, two fresh agents that were forbidden to open the earlier
transcriptions) were re-read and compared automatically: **831 / 836 (99.4 %) identical.** The 5 misses: three are slit panels that show a setpoint box and a
small readback (e.g. 0.500 vs 0.499 - a 1 um ambiguity of *which* number, not a misread); one is a digit-count slip (0.000040 vs 0.00040 on a compact entry);
one is a tile whose title was cropped (device unknown - now excluded by label). **Consequence:** slit sizes/centres/blades carry +-0.001 mm setpoint-vs-readback
ambiguity (irrelevant at the 10 um scale of every use below); compact-motor entry boxes can have a digit slip (not used for physics).
**Independent confirmation:** 21 (E, Z2) pairs from different years and different agents fall on one two-parameter curve with 0.3 um rms - transcription noise cannot be larger than that on those fields.
Quality notes from the agents were stored and used: "entered from memory" (pack 053) was spot-checked on two images (55 values, all correct); inferred PV names (pack 004) and
unlabelled blade positions are tier C.

## 12.2 The HEM energy-transform record is now exactly known (`fits/facts_hem.json`)

The userTran3 calc record shows E, Th1, Th2, Chi2, Z2 and their offsets together; 38 screenshots (31 with Th1, 29 with Th2, 21 distinct Z2, 31 distinct Chi2), 51.9-100 keV, 2022-2026:

| output | relation (theta_B from d(Si111) = 3.1356 A) | residual |
|---|---|---|
| **Th1** | `1.0001973 * theta_B(E) + Th1 offset` (offset = the number printed in the record) | **2.5e-7 deg rms**, n = 31 |
| **Th2** | `1.0000100 * theta_B(E) + Th2 offset` | 2.8e-7 deg, n = 29 |
| **Z2** | `33.3417 / tan(2 theta_B) - 7.4407` mm | **0.3 um rms** (max 0.7 um), n = 21 |
| **Chi2** | quartic in (E - 70 keV): 0.0210 deg at 52 keV, 0.0322 at 71.7, 0.0485 at 100 (coefficients in `core.HEM_CHI2_COEF`) | 2.4e-7 deg, n = 31 |

* **The old Z2 model was wrong** (Z2 = 32.91 / tan 2 theta_B, "fixed exit"): it misses by up to **3.5 mm** (1.5 mm rms with the best constant). `core.hem_z2_mm` now uses the fit; the legacy form stays selectable with `offset_mm=`.
* **Th1 has its own angle scale** (+1.97e-4 relative; Th2 is exact Si(111)). With scale = 1 the Th1 readout is off by 0.43 / 0.32 / 0.25 mdeg at 52 / 71.7 / 90.5 keV (10-18 eV). The operators calibrate the offset near 71.7 keV, so
  the physical effect left after calibration is only the energy dependence (~3 eV at 52 keV): small, but it is a *systematic*, not noise. In the simulator the physical-offset reference is shifted by (s-1) theta_B(71.676 keV) so E_actual(71.676) stays exact.
* The 2025-03-04 row at 54.998 keV that looked like an in-day "state change" is just a screenshot whose printed Th1 offset was 0.4959 (legacy); the fit through the printed offset needs no exclusion.
* **Printed offset history** (tier A): Th1 / Th2 = 0.4962 / 0.1475 (Jun 2022), 0.4944 / 0.1475, 0.4950 / 0.1475 (2023), **0.5051** / 0.1573 (Oct 2024), 0.4873 / 0.1573 (Feb-Apr 2025), 0.4871-0.4889 (Jun 2025), 0.4860 / 0.1552 (Nov-Dec 2025), 0.4863 / 0.1562 (Feb-Mar 2026).
  Th2 - Th1 = -0.347..-0.348 deg until 2024, -0.330..-0.331 deg from 2025. No screenshot after Mar 2026 has a full record, so the Jul-2026 re-reference (08 item 8) is still not in this data.

## 12.3 Other checks and what moves how much

* **Undulator gap model validated** on 69 independent (gap, E) pairs read from the same screenshot (ID Gap Control / Und2.1 / DS Und): residual vs `sim.json` (period 21.0 mm, fitted K) **0.011 mm rms, 0.029 mm max**; harmonics n = 5 (17 pairs), 7 (43), 9 (8), 11 (1). Between-session spread matches `gap_wander_mm`. No parameter change needed.
* **Sensitivities** (from the fitted relations): one keV of energy moves Th1 by -42 / -22 / -11 mdeg (52 / 71.7 / 100 keV), Z2 by **8.44 mm/keV** (almost constant), Chi2 by 0.52-0.59 mdeg/keV, the n = 7 gap by 120 um/keV at 71.7 keV (8.8 -> 14.6 mm over 61-100 keV). One mdeg of Th1 = 24 / 45 / 88 eV at 52 / 71.7 / 100 keV; the usual Th2 step (0.0002 deg) is worth 5-18 eV.
* **Operator step sizes (tweak boxes, tier A)**: HEM Th1 0.0001-0.0002 deg, Th2 0.0002 deg, Chi2 0.001 deg; E lens tilts 0.002 / 0.001 / 0.0006 deg; B lens tilts 0.00282 deg (every tier-A window, 14 + 13 - a fixed calibration step); lens Y 1 mm (in/out toggle); sample stage x/y/z 0.01-0.1 mm; aeroRot 90 deg (the usual 90-degree jog) with 10 / 45 / 1 deg for set-ups.
* **Lens Y motors show two states, 0 and +-1 mm** (`L1E y` 0 or +1.0, `L2E y` 0 or -1.0, `L4B y` 0 or -1, `L5B y` 0 or +1; tier A, 23-28 images each). **Which state is "in the beam" is NOT stated on the screenshots - not assigned.** The logs say lenses are put in with the `focusing_E_Vert_insert` macro (Feb 2025) and that the E lens *box* was moved out in X (out position -8.133 mm, Oct 2025); Y = 0 vs +-1 mm is plausibly that insert/withdraw pair, but that is an inference (candidate only).
  L1E / L2E tilt medians (tier A): L1E 0.112 deg (2022, n = 7) -> 0.088 (2023, 3) -> 0.093 (2024, 3) -> 0.168 (2025, 11); L2E -0.084 (2022, 7) -> -0.052 (2023, 3) -> -0.161 (2024, 3) -> -0.239 (2025, 8): the focus tilts moved by ~0.06 / ~0.15 deg between 2022 and 2025 (energy mix differs between years, so this is not a pure drift).
* **Lens tilt vs energy (small n, weak):** the strict energy rule (all energies in the 40 preceding log lines agree within 0.15 keV) leaves 17 of 78 lens images. L1E tilt vs the focus model (focus at 71.5 m): median +0.002 deg, rms 0.018 (n = 5, 52-90.5 keV); L2E median +0.075 deg (n = 4). Too few to refit the lens model; kept as a prior.
  Available for refit once more energy-labelled lens screenshots exist (the `lens_points.json` table is in the private KB).

## 12.4 Limits, offsets, PVs (the information model: `../panel_registry.json`)

186 devices (>= 3 images) with tier-A statistics: typical position (median, p10-p90, modal values, by year), modal soft limits (user and dial), dial-user offset, tweak steps, slit statistics.
**A PV is linked to a device only when its string was printed on a window title (tier A), seen on >= 3 images, carried by >= 90 % of the device's PV-bearing readings and not claimed by another device;**
otherwise the candidates stay listed (twin rule). Result: 123 linked, 31 ambiguous, 32 with no PV on screen. The ambiguous ones are real, e.g.:
HEM Th1 / Th2 appear as `1ida:m30` / `m32` (79 %) **and** `1ida:m11` / `m13` (21 %, another era); `1ide1:m9` is printed on both the aeroRot and the MTS X2E windows; `1ide1:m6` on both Det X (Newport) and NF TiltY;
`1ide1:m51` is "SAX attn X" in some windows and "SAX pin X" in others; HEM Z2 is `1idsft1:m1` (also seen as `20idHEM:m8`).

Selected rows (user-coordinate soft limits; offsets move when a motor is re-homed, so several modal values are kept in the JSON):

| device | PV (on screen) | soft limits (user) | dial - user | tweak step(s) | typical position |
|---|---|---|---|---|---|
| aeroRot (E) | `1ide:m9` (ambiguous with MTS X2E) | +-186 deg (also +-190, +-195 in other eras) | 0 | 90 / 10 / 45 deg | 0 (+-90) |
| samXE / samYE / samZE (E) | `1ide1:m34` / `m35` / `m36` | -10.65..9.35 / -9.3..20.6 / -9.21..10.79 mm | +0.65 / +9.21 / -0.79 | 0.1 / 0.01 / 0.01 mm | x 0.03, y 13.4, z 0.18 mm |
| samChi (Rz) / samTh (Rx) (E) | `1ide1:m86` / `m87` | +-8.1 / +-4.6 deg | 0 | 0.1 deg | 0 |
| L1E / L2E th | `1ide1:m30` / `m32` | -1.0..0.3 / -0.3..0.2 deg | +0.046 / +0.145 | 0.002 / 0.001 / 0.0006 deg | +0.12 / -0.15 deg |
| L4B / L5B th (B) | `1idb:m24` / (m29, ambiguous) | +-2 deg | -0.04 / +0.04 | 0.00282 deg | -0.45 / +0.42 deg |
| HEM Th1 / Th2 (A) | ambiguous (m30/m11, m32/m13) | -0.0066..10.09 / -0.0051..10.99 deg | -3.393 / -4.995 | 0.0001-0.0002 deg | 2.07 / 1.74 deg (71.7 keV) |
| HEM Chi2 (A) | `1ida:m17` | +-0.5 deg | -0.0001 | 0.001 deg | 0.032 deg |
| HEM Z2 (B) | `1idsft1:m1` | 336..1143 mm | -203.19 | 0.1 / 1 mm | 595 mm (430-752) |
| samXC / samYC / samZC (C) | `1idc:m25` / `m26` / `m27` | -10.04..8.93 / -15..8.35 / -9.5..9.5 mm | +34.07 / +59.91 / +33.75 | 0.75 / 0.01 / 0.1 mm | +0.05 / -4.1 / 0.46 mm |

Limits are not hardware limits in general: they are the EPICS soft limits at the time of the screenshot and move with the dial-user offset (e.g. samXE -10.647 / -11.018 and samYE 20.6 / 29.81 in different eras).

## 12.5 Baseline states (`../panel_baseline.json`, aggregated; per-image values private)

Only energy-labelled screenshots (strict text rule) with tier-A slit readings, bins of 0.5 keV with >= 3 images. What is stable: **WB slit centre** (H +0.015 mm, V -0.135 mm at 71.5 keV, n = 8, p10-p90 +-0.1; V -0.135 at 52 keV, n = 5; +0.083 / -0.168 at 80.5 keV, n = 4). WB size is an operator choice that follows the energy:
H x V = 0.60 x 0.30 mm (52 keV, n = 5), 0.55 x 0.475 (71.5 keV, n = 8, range 0.44-0.75), **0.30 x 0.30 (80.5 keV, n = 4)**, 0.5 x 0.5 (61.5 keV). **Not a baseline:** the Kohzu/CK slits (sizes 0.1-2 mm, centres -1.5..+0.9 mm at the same energy) follow the experiment.
There is not enough energy-labelled data to give lens or sample-stage baselines per energy.

## 12.6 What changed in the code
`blade/physics/core.py`: `hem_th1_deg` (scale), new `hem_th2_deg`, `hem_chi2_deg`, `hem_z2_mm` (fit; `offset_mm=` = legacy), constants `HEM_TH1_SCALE`, `HEM_TH2_SCALE`, `HEM_Z2_C_MM`, `HEM_Z2_D_MM`, `HEM_CHI2_COEF`, `HEM_CAL_E_KEV`.
`blade/vbl/world.py`: `energy_actual_keV` uses the Th1 relation with the calibration-energy reference; `snapshot()` adds `th2_deg`, `chi2_deg`. `tests/test_vbl_physics.py` expects the new Th1/Th2/Chi2. `mono_fit.py` keeps its documented scale-1 convention (its offset tables were fitted that way).

## 12.7 Not done / limits of this evidence
* Scaler / ion-chamber tiles (1,762 readings) and preamp gains (435) are transcribed and tiered but not yet analysed (IC gain exponent, Kohzu slit transmission, flux vs energy per session need paired slit+IC screenshots with a known energy).
* Slit-panel limits (the tiny blue numbers) were never transcribed; slit blade positions are by screen layout.
* Lens refit needs more energy-labelled screenshots (17 usable); the log text rarely states the energy near the lens windows.
* Ambiguous PVs (12.4) need a person who knows the IOC naming; none was attached to a twin element.
* Screenshots after Mar 2026 with a full HEM record are missing, so the Jul-2026 Th re-reference is not tested here.
