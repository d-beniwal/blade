# 6. Detectors and cameras: what changes when energy, distance or optics change

Twin elements: `tomoB`, `tomoC`, `tomoE`, `d2C` (Varex D2), `d2E` (NF D2), `hydra`, `vff`, `saxs`, etc. Code: `blade.physics.detector`. Citation keys: `README.md`.

## 6.1 Tomography cameras: pixel size = sensor pitch / magnification
| camera (as logged) | pixel size at the scintillator | = sensor pitch / M | notes |
|---|---|---|---|
| PG1, 5X (E, back wall) | 1.172 um/px | 5.86 um / 5 | headers 2022-2026 |
| GH1, 5X (E, high-res table) | **0.69 um/px** | 3.45 um / 5 | FLIR Grasshopper3; 0.069 mm = 100 px [M26a:L127] |
| PG5 (C) | 1.17 um/px | 5.86 um / 5 (assumed) | rx tilt measurement [S25b] |
| NF Retiga, 5X (E) | 1.48 um/px | 7.4 um / 5 | headers 2022-2023 |
`detector.object_pixel_um` reproduces all three logged values exactly. **Discrepancy to resolve:** `profiles/s1id` has `retiga2` (hutch B) at 1.0 um/px; the logs give 1.48 um/px for the NF Retiga 5X in E. They may be different cameras.
Field of view = pixels x pixel size (`detector.fov_mm`): GH1 (1490 x 1940 px frames) sees 1.03 x 1.34 mm; a 200 x 200 um beam is ~300 px wide [B26:L37]. Beam footprint on the tomo camera = the WB/Kohzu slit image, which is why the slit images are used to align everything.
Magnification choice trades pixel size against field of view and light yield; changing the objective changes pixel size by `1/M` and BLADE's `pixel_um` for that camera must change with it.

## 6.2 Area detectors and calibration geometry
- Pixel sizes: GE panels 200 um/px, Pilatus 3X CdTe 172 um/px, Pixirad, Varex 4343 [headers]; far-field Hydra (4 GE panels) at ~2200-3578 mm, GH1 at 70-150 mm from the sample [headers].
- **Rings:** a powder ring of spacing d sits at `R = L tan(2 theta)`, `2 theta = 2 asin(lambda / 2d)` (`detector.ring_radius_mm`). Ring radius **grows linearly with distance and shrinks with energy**: at 71.676 keV, 1 m, 200 um/px the CeO2 (111) ring is 277 px, (200) 320 px, (220) 453 px (`detector.cubic_rings`). Changing the energy to another edge or moving the detector therefore needs a re-calibration (CeO2/LaB6 and MIDAS) of distance, centre and tilts.
- Calibration facts: distance 800.2 -> 765.9 mm after a Nov 2024 event and constant afterwards [A24:L308-319]; Varex ceria at 880 mm, 71.676 keV, 2 s [S25b:L337-343]; detz recalibrated 1200 -> 1167 mm [S25a:L202-217]; in Jan 2023 CeO2 patterns were taken at Dsam 453, 553 and 653 mm (the detector moved 100 mm downstream twice, 69 keV) so that ring radius versus distance fixes the distance and tilts: the log says 'move Dsam to get at least up to the 3rd peak' and 'get more patterns' [S23:L198-217]. Ring radii grow with L, so a short distance puts more rings on the detector and a long one gives finer angular resolution.
- **Exposure/dose:** peak intensity scales with exposure time and attenuator; saturation limits (Varex at 0.1 s, attenC = 1.0) are given in file 04. Exposure 1 -> 4 s on one detector lost frames (missing packets) [M24:L916-930]; Pixirad vs GE at the same exposure differed in sensitivity [M24:L979]; BrillianSe 1, 2, 3 s exposures were indistinguishable [M24:L668].
- Dark/white: tomo data files often carry all-zero `data_dark/data_white`, so use the raw frames (BLADE `DOMAIN.md`).

## 6.3 Beam-position monitors in the data
Hot-spot drift on a tomo camera is the beam-position monitor: a jump of 3-15 px (up to ~15 px, centre 933 vs 950) every ~20 min in Jul 2024 was matched to ring RF/booster voltage sag [M24:L248-458]; "beam seems moved ~1 mm in X and ~0.3 mm in Y" between cycles [S25a:L190]. At 0.69 um/px a 15 px drift is ~10 um: a rotation-axis alignment is only as good as the beam stability during the sweep.
