# Detectors and image formation: fits from the knowledge base (2026-11-13)

Code `blade/physics/camera_fit.py`, numbers `camera.json` (per-frame tables, derived numbers only), test `tests/test_fit_camera.py`. Citations: startup/tables documents as doc_id:line, user logs as "user log <year>".

**Limit of the data.** Most KB images are 8-bit screenshots of ImageJ/areaDetector windows with a stretched display range and viewer scales of 33-150 %. Counts, noise and transmission are not recoverable; geometry (px/um widths, angles, spatial spectra) is. Scale and native frame size were recovered from the window width (canvas = native x scale + border 10/18/28 px; 13 windows whose title I read by eye were all reproduced), camera from native size/aspect, um/px from the logged value of that camera. Frames in one log are correlated, so independent n is smaller than the frame counts below.

## 1. Fitted / validated

| quantity | result | n, uncertainty | residual |
|---|---|---|---|
| pixel = sensor pitch / M | PG 5.86, GH1 3.45, Retiga 7.4 um reproduce every logged value: PG1 5X 1.172, **PG1 7.5X 0.7813 (logged 0.781, fitted 0.78125)**, GH1 5X 0.69, NF Retiga 5X 1.48, Retiga 7.5X 0.987 (logged 1.0) | 6 camera/objective rows, >60 logged mentions | <=1.3 % (the 1.0 is a rounded log value) |
| retiga2 (B) 1.0 vs NF 1.48 | **resolved**: same 7.4 um Retiga, 7.5X in B/radiography, 5X in the NF station | | |
| PG1 era | 1.172 (5X, 2022-2026 headers) and 0.781 (7.5X lens, Nov 2024: 2024-AMsetup_nov24_explog:56); one pixel size per camera is wrong for 2024 | | |
| Pilatus pitch | beam centre px vs mm in three CeO2 calibrations (2024-AMsetup_nov24_explog:93,315,317): 172.000 um | 6 ratios | 0.001 um |
| CeO2 ring check | (111) at 61.31 keV, 800.17 mm, 172 um = 301.6 px; the 800.17 -> 765.89 mm event moves it 12.9 px; wavelength 0.20221 A matches 12.39842/E | formula only (no logged radii to compare) | |
| phase-contrast distance z = (2 delta)^2/lambda | 79.8 mm (Tb), 62.9 mm (41 keV) reproduced exactly | 2 | 0 |
| **pin silhouette** | two families. B: half angle **7.8 +/- 0.06 deg**, top **105 um** (104-107); A: **14.8 +/- 0.25 deg**, top 135-220 um (mean 180) | B: 3 frames, 1 session; A: 8 frames, 3 sessions | angle scatter 0.06 / 0.25 deg |
| pin top width test | sim.json has 104.5 um **and** 15 deg: the 104.5 um (151.5 px x 0.69) is the B pin whose measured taper is 7.8 deg; 15 deg belongs to the wider A pins. One of the two sim numbers is wrong for any single pin | | |
| pin physics | W K edge 69.525 keV: mu 66/cm (62 keV) -> 200/cm (71.7 keV). A 104.5 um chord transmits 0.123 at 71.7 keV (sim 0.08 needs 126 um, test-frame 0.045 needs 155 um); round-pin edge 10-90 % = 0.661/(R mu^2): 12-21 um at 71.7 keV, 44-77 um at 52 keV for R = 80-140 um; measured thick-pin edges 24 um (IQR 20-26, 14 edges). Pin contrast therefore changes x2-3 across 69.5 keV | 14 edges, energy of the frames unknown | same order, not a fit |
| beam mottle (texture) | exponential ACF, 1/e length **26 um** by the screenshot estimator (IQR 16-50; PG 25 um n=32, GH1 26 um n=25); estimator bias -15..-30 % (checked on synthetic fields) so true ~32 um; relative rms 0.076 (PG) / 0.107 (GH1) (0.17 for strongly mottled frames); PSD slope -2.4 / -2.5 over 6-60 px periods | 57 frames | frame-to-frame IQR +/- 50 % |
| vs current `beam_texture` | same estimator gives 70 um, rms 0.34, slope -3.2: blobs ~2-2.5x too long, modulation ~3x too strong (and real frames are streaky from slit-edge/window fringes) | 8 sim seeds | |
| slit-edge 10-90 % width | PG median 38 um (horizontal edges 32, vertical 48; n=63), GH1 19 um (n=15); minimum 8-10 um. They are penumbra + Fresnel + PSF together; only the minimum bounds the PSF (sigma <~ 3 um) | 78 edges | |
| PSF bound | sharpest silhouette edge (B pin, viewer 75 %): 10-90 % = 2-4 um => GH1 sigma <~ 1.1 px; sim psf_px 1.8 is not contradicted, but a 50 um LuAG at NA 0.14 (assumed) would be 4.2 um FWHM, too soft; <= 20 um gives 2.7 um | 3 frames | bound only |
| dust | 29 spots/mm^2 (IQR 19-50, PG n=38), equivalent diameter 3.9 um (p90 9 um) at the scintillator; GH1 28/mm^2 n=7. sim `camera_maps`: right density, 5-21 um diameter: too large by ~3x | detection-limited | |
| NF bbY vs DetZ | beam-stop shadow moves 2.8, 2.8 (2023), 4.6 (2025), 5.0 (2022 two-point) um per mm of DetZ; pooled 3.3 um/mm, bbY = 0.0056 + 0.0033 DetZ mm; intercept +-15 um between sessions. The "5 um/mm" of the brief is the top of the range; physical meaning: 3-5 mrad between the NF stage axis and the beam | 4 sessions, 16 points | 3.4 um rms (pooled) |
| as-found alignment spreads (small sample) | wedge: median 0.004 deg, 10 of 11 values <= 0.015 (one 0.0675 in the 2023 first alignment); aero omega zero error: 0.001-0.028 deg (0.62 deg before the first correction of 2026-mpe_jan26:167), median 0.023; camera/axis tilt as found 0.008-0.47 deg, median 0.30 | n = 11 / 6 / 6 | lognormal gsd x4.7-8 |
| W / scintillator absorption | xraydb tables embedded (30-110 keV, K edges). LuAG 50 um: 0.064 (62 keV) -> 0.234 (64 keV, Lu K 63.314) so the camera gains x3.7 across 63.3 keV; energy-integrating counts 71.7 vs 52 keV x2.6 | model (material assumed) | |

## 2. Assumed (not in the logs)
Scintillator material/thickness (LuAG 50/20 um), objective NA (0.14 at 5X, 0.21 at 7.5X), visible wavelength, X-ray blur 1 um, round-pin cross-section, sensor pitches (reproduce logs but not read from data sheets), PG5 = PG1 optics (logged "?1.172"), Eiger 75 / Pixirad 55 / Varex 150 um pitch (no number in the logs).

## 3. Failed or inconclusive
- **Interior profile of the pin** (chord model exp(-mu t(x)) with PSF and offset): relative rms 0.1-0.5, unphysical tau; display offset and beam gradient make it unusable. Not retained.
- **Noise vs mean from display images**: not justified (8-bit, unknown stretch); no (exposure, counts, gain) tuple with other variables fixed exists in the text (logged exposures: GH1 0.06-0.2 s, NF 0.5 s, saturation 65535 GH1, 4095 Retiga).
- **Footprint vs slit setting**: only one setting (1.7 x 0.03 mm Kohzu, 2 frames: footprint 1775 x 41 um at 50 %) has both caption and a measurable footprint; others are WB/upstream slits needing distances.
- Viewer scale could not be read for ~58 of 383 framed screenshots and for all unframed ones (unmeasured). One pin frame (scale assumed 50 %, window title not visible) gives an uncertain 321 um top width.

## 4. PENDING models (what, why, data needed, effort)
1. **Photon-transfer curve** (gain e-/ADU, read noise, full well, dark current) for GH1, PG1/5, Retiga. Why: shot-noise-correct noise in the VBL and saturation behaviour. Data: 12 exposures from dark to ~90 % saturation, 2 flats each + darks at 3 exposure times, raw 16-bit (`camera_fit.ptc_fit` ready). Effort: 1 h beam time per camera.
2. **Scintillator + objective identity and PSF**: LSF from a tilted-edge (knife edge or slit) raw image per camera/objective, scintillator type/thickness from the camera build sheet. Why: resolution and counts-vs-energy (LuAG edge at 63.3 keV). Effort: 30 min + a data sheet.
3. **Counts vs energy / exposure**: raw flat counts at fixed slits, attenuator and ring current for 52, 62, 66, 71.7, 80, 90 keV. Why: validate the LuAG x3.7 step and x2.6 factor. Effort: 20 min.
4. **Pin interior transmission and energy dependence**: raw (not display) pin frames at two energies across 69.5 keV, pin diameter and material from the pin drawing. Why: pin contrast and edge softness (round chord) in the simulator. Effort: 15 min.
5. **Texture amplitude in counts**: raw beam-only frames (not screenshots) at known slits, 2-3 energies. Why: calibrate texture amplitude and its fixed-pattern/dynamic split. Effort: raw frames only, 20 min; screenshots with OCR of the ImageJ line profiles (error-function fits) would give native-pixel edge widths for a further ~15 frames.
6. **Ring radii**: logged ring radii (px) with distance and energy to test `detector.cubic_rings` beyond the pixel-pitch and distance-event check. Effort: read MIDAS/GSAS output of the CeO2 files.
7. **NF bbY vs DetZ per session with the beam position**: at 3 DetZ in one session plus beam angle on the NF camera hot spot, to separate stage axis angle from beam drift. Effort: 10 min.
8. **Pixel size per camera/era** with a calibrated ruler/Cu grid (retiga2 1.0 vs 0.987, PG5, 20-ID camera 0.548 um/px, "10X" lens). Effort: 10 min per camera.
