# What it takes to see the alignment pin on the E-station tomo camera (2026-11-15)

Code `blade/calibration/pin_view_fit.py`, numbers `pin_view.json`, test `tests/test_fit_pin_view.py`. Input: the 25 knowledge-base frames the user curated to `tomopin` (tungsten pin visible), the tier-A panel facts logged before each frame, and hand-read log lines. Citation keys: `../README.md`; user-experiment logs appear only as statistics (public repo). The per-frame table with document ids is private (knowledge tree `scratch/pin_model/`).

## 1. Result in one paragraph
The logs support a **capture-range model, not an absolute predictor.** Seeing the pin needs (a) the camera in the beam, (b) a lit footprint wide enough to contain the pin, (c) the rotation axis (with the pin on it) within about half a footprint of the beam, and (d) the pin tip inside the lit vertical window. (a), (b) and the pin-on-axis part of (c) are the same from cycle to cycle. The beam-axis position (c) and the pin height (d) are **not** constants: they must be found each cycle, but the logs give the starting point and the size of the search.

## 2. The recipe, with what the data say about each value
| quantity | value at the pin frames | evidence | use |
|---|---|---|---|
| tomo camera | in the beam, stages zeroed on the hot spot; hot spot in frame (beam centre pixel (1270,700) -> (1100,850) after the tilt alignment [M26a:L145-151]) | stage values attached for 1 frame only (tomoX 0, tomoY 0, tomoZ 205 mm, chi 0.25 deg) | weak: treat as "zeroed on the hot spot", not as numbers |
| WB slit gap (defines the footprint) | 0.31-1.1 mm H (median 0.6, 6 values, 5 sessions); 0.47-0.5 mm V | tier A | WB 0.5-0.6 x 0.5 mm; footprint = 1.6-2.2 x the gap (820 um FWHM H and 1050 um V for 0.5 mm in one session; ~1.1 mm for 0.5-0.6 in the screenshots, n=2) |
| E Kohzu slits (US/DS) | 0.74-2.0 mm (median 1.0; 10 values, 5 sessions) | tier A + one log line (see 4) | open them; they sit ~at the camera (magnification 1) so any E slit narrower than the WB footprint becomes the footprint |
| C / B Kohzu slits | C 1.2-2.0 mm (3 sessions); B 1.0 mm (1 session) | tier A | open (no effect once wider than the WB footprint) |
| aeroRot | 0 deg (5 values, 3 sessions) | tier A | pin seen side-on at omega = 0 |
| samXE / samZE | -0.37...+1.0 mm / -0.52...0.0 mm (8 frames, 4 sessions; median -0.07 / -0.09); one frame at samZE +7.9 is the deliberate +8 mm wedge check | tier A | pin already near the axis; these are the pin-to-axis offsets |
| **samYE (pin height)** | **0.04-20 mm, median 9.3 (8 frames, 4 sessions)** | tier A | depends on how the pin was mounted; cannot be predicted: search |
| energy | 55.6, 71.6, 96 keV (3 frames with an energy; the other frames span 52-96 keV in the logs) | tier A | visible at any energy; contrast changes x2-3 across the W K edge (69.5 keV) [camera.md] |
| **aero X dial (axis on the beam)** | **-3.0 mm, +-0.3 (mean of the last four cycles: -2.88, -2.72, -3.09, -3.31; sd 0.25, half-range 0.29)**; -4.20 / -4.19 in Jan / Feb 2025 [S25a:L592-600] | tier A, 6 cycles | the one absolute number: start the aero X search at its dial value of the last cycle |

## 3. Geometry model (`pin_view_fit.py`)
- Lit window = footprint ∩ camera FOV, centred on the beam; footprint H = min(1.9 x WB gap, E slit opening). FOV (full sensor): GH1 = GS3-U3-89S6M, 4096 px x 0.69 um = 2.83 mm (user 2026-11-15; the logged 1940 / 1570 / 850 px frames are ROI crops, i.e. 1.34 / 1.08 / 0.59 mm); PG1 1920 px x 1.172 um = 2.25 mm.
- Pin position = axis + pin offset (samXE/ZE). Pin **seen** if its silhouette (flat top 104.5 um / 7.8 deg for pin B, 180 um / 14.8 deg for pin A, [camera.md]) overlaps the window; **usable** if the flat top fits entirely inside.
- Vertical: the cone enters from below, apex up; the tip is on screen while it is inside the lit vertical window, i.e. a samYE window as wide as the vertical footprint (about 0.8-1.1 mm for WB V 0.5 mm; geometry, not fitted).
- **Capture across cycles.** The on-beam dial moved by 0.014, 1.31, 0.16, 0.37 and 0.22 mm between consecutive cycles. A pin on an axis left at the previous cycle's dial is already on screen for these fractions of the 5 shifts: footprint 0.6 mm 3/5, **1.0 mm 4/5, 1.3 mm 4/5, 2.0 mm 4/5**: the 1.31 mm shift (Feb -> Oct 2025) is only caught by a footprint of about 2.5 mm or more, which needs the full GH1 sensor (5/5 at 3 mm); it exceeds half of even the PG1 field of view, and an ROI crop shrinks the window further. At the usual WB-defined 1.0-1.3 mm footprint that shift needs the axis or the camera (tomo X) moved.
- As-found axis moves written in the logs: coarse 0.18, 0.85 [S23:L182], 1.02 (start position not stated), 2.43 [S25a:L599] mm (n=4); fine re-zeros 0.008, 0.02, 0.04 mm. Too few to turn into a distribution.

## 4. What does NOT work (kept so nobody retries it)
- **E-slit centre does not give the axis position.** dial - slit centre = -2.46 mm (Jan and Feb 2025, the same cycle) but -3.46 mm (Nov 2026): the slit zero is re-set whenever the beam moves ([02_slits_and_beam_definition.md]), so the slit centre is a per-cycle reference, not an absolute one. Aero X dial is the stable coordinate.
- **Nearest panel is the wrong rule.** The Oct 2024 frame's nearest slit panel (0.22 mm) is the setting before the operator changed it (0.74 x 0.84 mm, a log line 4-6 lines before the frame); the model attaches the last value logged *before* the frame (<= 30 lines) and replaces that panel by the log line. One more frame carries a 0.1 mm slit panel although it is lit across >1 mm (slits reopened without a log entry); its slit values are dropped. 13 tier-B/C panel rows inside the windows were not used.
- **No absolute stage regression.** Slit centres, aero user zero and pin mount height change every cycle, and only 8 of the 25 frames have sample-stage values, 13 have slit/WB values, and 10 have no attachable value at all (their numbers, if logged, sit in a panel more than 30 lines earlier or only in prose).

## 5. Limits (read before using a number)
1. All 25 frames are **positives** (pin seen). There is no frame where the pin was missed, so the model cannot be validated on false positives; its thresholds come from physics and the logged sizes, not from a fit that separates seen from not seen.
2. 25 frames come from 15 documents; frames in one session are correlated, so the independent n is the session count (given per row above: 1-6).
3. Footprint = 1.6-2.2 x WB gap is two measurements; the distances needed to derive it are not in the twin.
4. Several frames are screenshots of the viewer; only geometry, never counts, is used.

## 6. What would make it an absolute predictor (all read-only)
Read, in the current cycle and without moving anything: aero X dial and user value, E-slit centres and sizes, WB gap and centre, tomo X/Y/Z, samX/Y/ZE (`loop_real_snapshot` / `probe_readonly.py` once the PV mapping is verified). With the dial of the last aligned cycle (-3.0 +- 0.3 mm) the model then says whether the axis is inside the window and by how much; a single logged "pin not seen" frame with those values would be the first negative example.
