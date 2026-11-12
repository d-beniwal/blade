# 1-ID beamline physics: what happens when you change a setting

Built 2026-11-11 from (a) the 1-ID startup/commissioning logs 2022-2026 (121 log documents indexed, 16 startup/setup logs read line by line), (b) the beamline's own code in `mpe_bluesky` (read-only), (c) first-principles formulas, and (d) literature (Crossref-verified citations). Everything that could be turned into numbers is implemented in **`blade.physics`** and **checked against numbers recorded in the logs** (`tests/test_physics.py`). The machine-readable form for the future simulator is `relations.json`.

| file | content |
|---|---|
| `01_source_and_monochromator.md` | undulator (SCU, PMU), harmonic/gap model, HEM mono geometry and energy calibration, drift, thermal load |
| `02_slits_and_beam_definition.md` | WB and Kohzu slits: flux, alignment, beam definition, failure modes |
| `03_lenses_and_focusing.md` | tilted saw-tooth lenses: model, validation, sensitivities |
| `04_flux_ion_chambers_attenuation.md` | IC rates, attenuators/foils (Beer-Lambert), shutters |
| `05_sample_stage_and_rotation_axis.md` | rotation axis, tilts, how the axis moves with the beam |
| `06_detectors_and_cameras.md` | tomo-camera pixel size/FOV, powder rings, calibration geometry, exposure |
| `07_typical_parameters.md` | GENERATED statistics over all logs: edges, detectors, slit sizes, gaps, mu*t, ... |
| `08_open_questions.md` | what the logs do not settle, what needs a survey or the beamline staff |
| `relations.json` | 29 cause->effect relations with sensitivities, evidence, function pointers |

## The 15 findings that matter most (all traced to logs; model-validated ones marked V)
1. **Energies are absorption edges**: the mono is calibrated on foil K-edges (Re 71.676 in 28 beamtimes, Au 80.725, Tb 51.996, Yb 61.332, Ho, Ta, Pr, Hf); xraydb reproduces every edge energy the logs quote (V).
2. **Th1 = Bragg angle of Si(111) + an offset** (0.4863-0.4963 deg), and **Z2 x tan(2 theta_B) = 32.9 mm is constant**: a fixed-exit double-crystal mono (V; derived here).
3. **1 mdeg of crystal angle = -45 eV at 71.7 keV**: a +0.00055 deg Th1 change gave exactly the -25 eV needed in 2025 (V).
4. **mu*t of the calibration foil resolves the energy scale to a few eV**; the readout sits 25-160 eV below the nominal edge and drifts with thermal state and after dumps: recalibrate every session.
5. **PMU: E rises with gap; a ~21.9 mm-period model fits five logged (gap, n, E) points to 0.17 %** and predicts the n=5 gap at 52 keV (10.143 vs 10.158 mm) (V, inferred device).
6. **Gap scans have hysteresis**: open to ~9.5 mm first, then `setundgap`, scan high to low.
7. **Steering matters as much as gap**: -11 urad restored a 2.5x flux shortfall (2026).
8. **WB slit size sets flux but not in proportion to area** (0.3->0.5 mm: x1.72 vs x2.78), heat load, and the best centre follows the beam (0.7 mm table yaw in 2026).
9. **The beam moves between cycles and after dumps (up to mm); slit zeros and the rotation axis follow it**: after APS-U the E-hutch axis moved -2.426 mm.
10. **Lenses are tilt-tunable saw-tooth lenses**: `f = h sin(tilt)/delta`; the model reproduces the beamline's four predicted tilts exactly and the measured optima to 0.002-0.010 deg (V); **1 mdeg = ~41 mm of focus shift**, so tilt resolution dominates over mono drift.
11. **Beer-Lambert attenuation is energy-dependent**: the same Cu wheel is 0.40 / 0.51 / 0.12 at 71.7 / 80.7 / 52 keV (V by the Pb-foil check).
12. **Camera pixel size = sensor pitch / magnification** (PG1 1.172, GH1 0.69, Retiga 1.48 um/px; all exact) (V); the profile's `retiga2` 1.0 um/px disagrees.
13. **Powder rings scale as L tan(2 theta)**: changing energy or distance requires recalibration (CeO2).
14. **Brightness mode**: vertical focus 17 vs 23 um, horizontal 30 vs 27 um, ~10 % fewer counts after steering.
15. **Many "physics" surprises are mechanical**: stuck slit blades, a driver switched off, lens supports in the beam, IC preamps off, IOC timing.

## How to cite and where the evidence lives
Citation `[S25b:L35]` = document key + line number in the extracted log text. Keys (only logs without personal names are cited here; user-experiment logs are used for statistics only):

| key | log document id | what it is |
|---|---|---|
| J22 / O22 / D22 | 2022-mpe_jun22_explog / 2022-mpe_oct22_explog / 2022-mpe_dec22_explog | MPE startup logs 2022 |
| S23 | 2023-startup_jan23_explog | startup Jan 2023 |
| L23 | 2023-lastlight_mpe_apr23 | last SCU light, Apr 2023 |
| M24 / A24 | 2024-mpe_jul24_explog / 2024-AMsetup_nov24_explog | Jul 2024 / Nov 2024 setups |
| S25a / S25b | 2025-startup_jan25_explog / 2025-startup1id_jun2025_explog | startups Jan, Jun 2025 |
| M26a / B26 / T26 / M26b | 2026-mpe_jan26 / 2026-Brightness_mode_feb26 / 2026-techcomm_jun26_explog / 2026-mpe_sep26 | 2026 logs |

The index and the full extracted text are **local only** (`beamline_twins/1-ID/logs_index/`, git-ignored: the logs are users' unpublished records and the repo is public). Rebuild and query with `beamline_twins/tools/logindex.py` (`build`, `search`, `topic`, `params`, `show`, `outline`, `images`); `logstats.py` regenerates file 07. The per-period reading notes written while building this (with more detail than these files) are in `logs_index/notes/` (local).

## Coverage (read this before trusting a gap)
- **Read line by line:** the 16 startup/commissioning/setup logs (2022-2026) plus the alignment-reference spreadsheet. **Screenshots were only partly examined** (roughly 12-28 images per log of 20-130 each; the ones carrying operator-panel values were prioritised), so settings that exist only in a picture may be missing.
- **Statistics only (not read line by line):** the 86 user-experiment logs and 19 spreadsheets, through their header blocks and regex-extracted parameters (`07_typical_parameters.md`). Their start-of-beamtime alignment sections are findable with `logindex.py topic alignment --kind user` but were not digested.
- **Not covered:** logs before 2022 and any year not in `mpe_logs/User_experiment_logs/1ID`.

## Confidence conventions
**observed**: stated in a log with numbers. **model validated**: a `blade.physics` function reproduces logged numbers (test in `tests/test_physics.py`). **inferred**: this project's reading; flagged INFERRED where the text allows. Where two logs disagree, both are kept in the notes. Do not use a number from here for hardware motion without checking the live PV limits: BLADE's protection rules (`AGENTS.md`) still apply.
