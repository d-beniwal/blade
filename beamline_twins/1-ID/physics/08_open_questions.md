# 8. Open questions (what the logs and code do not settle)

## Needs the beamline staff, a survey or a drawing
1. **Source-to-element distances.** Only the lens stacks (B 38.8/38.9 m, C 59.2-59.7 m, E 67.7-68.5 m) and the E sample (71.5 m default) exist, from `mpe_bluesky`. In Feb 2026 an attempt to solve for the source-lens distance from measured lens optima gave nonsensical values, so one of the assumptions (delta, the formula, the distances) is wrong at the ~0.01 deg level [M26a:L606-609]. The twin cannot model slit angular acceptance, beam size growth or focus geometry without surveyed distances.
2. **Undulator specification.** Period, magnet type, and ring energy are inferred (21.9 mm, hybrid-Halbach, 6 GeV). SCU (2022-2023) parameters are not modelled. Whether n=9 at 86.5 keV is right is inferred.
3. **Fill pattern of "brightness mode"**: the logs say 162-bunch high coupling [S25a:L22] and "216 bunches - high coupling / swap-out" [B26]; the emittance numbers needed to model the source size are not given.
4. **What `ut` is exactly** (the target mu_t at the calibrated position, inferred equal to the E_scan fit step `b` ~1.43) and why the Re readout is 25-75 eV below 71.676 keV while Au reads 80.725 exactly. Th1 offset / Th2 / thermal state are all candidates.
5. **HEM bandwidth** (Laue, bent): the edge scans give 48-58 eV width; the intrinsic and divergence contributions are not separable from the logs. HRM crystals, reflections and bandwidth are not described.
6. **Lens details**: tooth angle, number of teeth, aperture, why `lens2C` is defined twice (upr and inv) in `mpe_bluesky`, and whether the B stacks labelled "Stack1" are lens4B/lens5B.
7. **Camera identity**: profile `retiga2` (B, 1.0 um/px) vs the NF Retiga (E, 1.48 um/px); sensor pitches used here (5.86, 3.45, 7.4 um) reproduce the logged pixel sizes but were not read from data sheets; PG5 (C) 1.17 um/px is assumed.
8. **Th-to-energy mapping in the Jul 2026 techcomm log** contradicts Si(111) Bragg angles: the Th zero seems redefined between Jul 7 and Jul 15 [T26].
9. **Phantom beam**: what produces the off-axis beam seen at 30-100 mm gap.
10. **IC6-E preamp change** reduced counts far more than the gain change implies [S25b:L518,L606].

## Things this project could do next with the physics already in hand
- Wire `relations.json` and `blade.physics` into a beamline simulator that reads the twin (element positions, slits, lens stacks, camera pixel sizes) and predicts IC counts, focus position, ring radii and tomo FOV for a requested setting.
- Use the lens model to propose lens tilts for a new edge and the PMU model to propose gap and harmonic for a new energy (validate on the next startup).
- Add an energy-calibration routine that predicts the Th1 offset change needed from a measured mu_t (45 eV per mdeg at 71.7 keV).
- Collect the missing survey distances, then add slit acceptance and divergence models.
