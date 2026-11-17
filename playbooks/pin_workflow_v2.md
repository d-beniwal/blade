# Pin alignment workflow v2 - region first (design, 2026-11-16)

Status (2026-11-17): **this is the ONLY pin workflow in BLADE.** All stages run on `blade/pinregion/` (region, geometry, `measure_frame`, `fit_axis`, `overlay_jpeg`, `axis_align`); the old global segmentation
(`analysis/pin/pinfit.py`, `measure.py`, `beam_center.py`, `method="legacy"`) was deleted (section 9). Nothing here commands the beamline: the workflow reads frames and PROPOSES moves (BLADE hard rule, `AGENTS.md`).

## 1. Principle

The retired recognition (`analysis/pin/pinfit.py` + its `measure_frame`, deleted 2026-11-17) segmented dark pixels globally and then fitted. It failed on 12 of 25 knowledge-base images (pin against a
margin, dim mottled beam, partial pins). The new first step is a **region detector** that cannot be fooled by margins: it looks for the pin's rigid shape (two long straight
edges leaning ~15 deg, converging upward, short flat top). **Every other pin property is then measured inside / along that region** - never by a new global search - so a wrong
object cannot enter the numbers.

```
frame --> [0 intake] --> [1 REGION] --> [2 GEOMETRY] --> [3 verdict] --> [4 run state/priors] --> [5 sweep + axis fit] --> proposed moves
                              |                              |
                              +-- no pin / partial ----------+--> [6 find / bring into view] (loops back to 1)
```

## 2. Stages and contracts

**0. Intake.** Input = a 2-D camera frame (live `inst.frame(cam)`, or a logged image). Snapshots of the ImageJ window (knowledge-base images only) first go through
`crop_camera`: removes window chrome, plot panel, pasted PV widgets, ROI marks and the snapshot's own white frame. Live frames skip this. Pixel size comes from the camera
profile (`gh1` 0.69, `pg*` 1.172 um/px), never from the image.

**1. Region** (`edgecone.find_pin_region_final`). Stage 1a: edge map of log-intensity -> Hough over slanted lines -> best flank pair (edge support along both flanks, interior
darker than the strips outside, flat top), or ONE flank + mirrored lean when the other is hidden/off the image; run on a 200-px copy (default). Stage 1b (full resolution):
both flank lines re-fitted to the actual edge pixels (coarse-to-fine window, robust line), visible extent = rows with edge evidence, top = topmost dark-below step along the axis.
Stage 1c: lit window ("field of view") measured per row beside the pin; polygon clipped to it. Output: polygon, flank lines `x = s*y + i`, `y_top`, `y_bottom`, fov box,
per-flank stats (inlier rows, rms), `one_sided`, score. ~80 ms per image (stage 1 at 200 px); ~180 ms for a 1940x1490 raw frame including stage 2.

**2. Geometry** (`geometry.pin_geometry`, prototype). Measured from the region only:

| property | how | use |
|---|---|---|
| top corners (virtual), top width px/um | flank lines meet the fitted top line | pin identity check, scale, one-flank rescue |
| **axis column** (`pin_col`) | midpoint of the two virtual top corners | the alignment observable x(w) |
| tip row | fitted top line at the pin axis | centring, pin height |
| half angle L / R / mean, axis tilt | from the flank slopes | identity check; tilt of the pin in the image |
| top-edge tilt, rms | line through per-column top-edge points | **bevel diagnostic** (flips with omega, see 5), not a wedge signal |
| visible rows / height | from stage 1 | how much pin is in the FoV |
| margins to the FoV, clipped flags | corners / top vs fov box | in_view / partial |
| axis offset from FoV centre (px, um), tip depth in FoV | axis col, tip row vs fov | centring moves, base move |
| per-flank rms, inlier rows | from the flank fits | quality gate |

**3. Verdict per frame.** `quality` = `both_flanks` | `one_sided_left/right` | none; `usable`; `state` = in_view / partial / absent; `reasons`; move hint.
A flank counts as *measured* only with >= 30 inlier rows and rms <= 2.5 px. One-flank frames get `pin_col` only if a top width has been learned in this run
(corner +- width/2, same rescue as the old code); otherwise `pin_col = None` (never guessed).

**4. Run state** (as `_update_prior`, but fed by stage 2): median top width and half angle from two-flank frames (rescue + identity check), FoV box (it does not change within a
run), last tip row. A frame whose top width or half angle disagrees with the learned pin by more than ~15 % is flagged `other_object` and excluded from fits.

**5. Sweep and axis fit** (unchanged maths, `axis_align`): `pin_col` at several omega -> `x(w) = c + a cos w + b sin w`; z move from b, x move from a, base shift from
`c - FoV centre` (FoV centre replaces the old pin-excluded footprint centre; keep the old as a cross-check until parity is shown). Tolerances stay in the profile.

**6. Find / bring into view.** Run stage 1 at every search step (80 ms). `partial` frames carry a direction: the visible flank + top row say which way the pin must move to
bring both corners inside the FoV with margin. The shadow search with the chuck (`pin_find.py`) stays as the fallback when stage 1 sees nothing.

## 3. Interfaces

- Analysis code (pure, array in / dict out): `blade/pinregion/region.py` (stage 1), `blade/pinregion/geometry.py` (stage 2 + the shared `pin_like` acceptance gate). No instrument imports.
  (Placed outside `blade/analysis/` on purpose: `.gitignore` line `analysis/` would leave new files there untracked - open item 6.)
- Procedures use only the Instrument interface (`procedures/pin_alignment.py`: `do_measure` calls `pinregion.measure_frame` (region + geometry); everything downstream kept its
  keys: `pin_col`, `usable`, `quality`, `top_row`, `top_width`, `half_angle_deg`, `beam`, `view`).
- MCP (mandatory for a new capability): `vbl_pin_geometry` (exists: now returns region + geometry), plus an `analysis_pin_region` tool for offline images; both covered in
  `tests/test_mcp.py`. The page's live "tomo-pin fit" button only analyses and overlays.
- Read-only on the real beamline: only frame reads; moves are proposals.

## 4. Failure handling

| situation | stage-1/2 result | action |
|---|---|---|
| no beam / no pin | `absent`, reason | stage 6 search (or find the beam first) |
| pin partly in view, one flank hidden | `one_sided_*`, partial | rescue with learned width; else hint move |
| pin clipped by the FoV edge / top | `partial` + clipped flags | hint move; frame excluded from the axis fit |
| wrong object (holder, wire) | width / angle disagree with run prior | `other_object`, excluded |
| flank fit poor (rms, few rows) | flank not measured | frame not usable (or one-sided) |

## 5. Evidence so far

- 25 knowledge-base tomo-pin images (screenshots, 3 cameras, dim/mottled/vignetted/partial): pin region found on all 25, checked by eye; at the 200-px default every image is
  within IoU >= 0.975 of the 400-px result.
- **85 real raw GH1 frames, omega -89..180 deg** (`tomo_alignment_moving_only`, same frames as the earlier sim calibration): both flanks measured on 85/85, in view 85/85.
  `pin_col` vs omega fits `c = 815.7, a = -130.0, b = -14.0` px (earlier analysis 815.9 / -130.0 / -16.0), rms about the fit 3.95 px (earlier 3.71 px; part is real drift between
  the three acquisition files: per-file mean residual +2.6 / -3.0 / 0.0 px). Top width 148.1 px = 102.2 um (earlier 99.75 um), half angle 14.83 deg (earlier 14.96),
  tip row 477.0 +- 0.84 px (earlier convention 479.3).
- **Top-edge tilt follows omega** (-4.3 deg at -90, +4.9 deg at +90): the bevel flip noted in DOMAIN.md. It is a diagnostic, not the wedge.
- Speed: see section 2 (stage 1) and `scratch/pin_region/bench*.out`.

## 6. Not yet done / risks

1. **False positives**: DONE 2026-11-17 on 277 `beam_only` KB views (section 9: 20 regions, 0 usable, 0 hints). Still not run on frames with only the chuck / holder.
2. **Tip-row convention**: new tip row (steepest-step line) is 2.3 px above the old one; `sim.json stage_E` refs and the simulator calibration use the old convention. Either
   re-reference the simulator or add a fixed offset; decide before mixing the two.
3. **Top width 2.5 % larger** than the earlier value (edge definition: steepest gradient vs 50 % level). Fine for identity checks; matters if um widths are used as a scale -
   pick one definition.
4. One-flank frames depend on a learned width; a run that starts on a one-flank frame has no `pin_col` until a two-flank frame arrives.
5. Simulator: `do_measure` / `do_sweep` / `do_find_pin` on a `vbl` run work with the new measure (2026-11-17 smoke: in_view, a -131 / b -17 px, found in 0 steps); the full adaptive align on the vbl is still the old open problem.
6. Code location: `blade/analysis/` is currently matched by `.gitignore` line `analysis/` (unanchored), so new files there would be untracked. Anchor it (`/analysis/`)
   or place the new modules elsewhere before promoting.

## 7. Switch-over plan for the rest of the workflow (order)

1. Decide items 2, 3, 6 above. 2. (done) region + geometry promoted to `blade/pinregion/`; `crop.py` (screenshots only) still in `scratch/pin_region/`, to go to `knowledge_base/`.
3. Tests (`tests/test_pinregion.py` exists: synthetic truth, simulator frames, stage-move following; still to add): synthetic-pin fixture (`tests/synthetic_pin.py`) + the 25 images' reference polygons (private, knowledge tree) + the 85-frame sinusoid fit (rms < 5 px, c within 2 px).
4. `do_measure` -> region+geometry, keep `measure_frame` behind a flag for one release; compare on the simulator and the 85 frames.
5. False-positive run on `beam_only`; then retire `pinfit.py`'s global segmentation.
6. Update `vbl_pin_geometry`, GUI overlay, MCP test, playbooks/alignment.md, `.context/`.

## 8. GUI integration (done 2026-11-16)

The "tomo-pin fit" button (live toggle, analysis only, no motor moves) calls MCP `vbl_pin_geometry` after every frame load; that tool is now `procedures/pin_fit.analyse_pin`
-> `blade.pinregion` (region + geometry + `pin_like` gate), ~290 ms per 1940x1490 frame (the simulator's own frame render, ~480 ms, comes on top). The page draws: region (filled polygon), virtual top corners + top edge, both flank lines (a flank that was not measured is dashed
orange), the pin axis, and the lit window (dashed cyan); the text line shows quality, region score, top width, tip row, axis column, half angles, visible height, axis offset from the
window centre. A run-level top-width prior (`pin_fit._PRIOR`, per camera) rescues one-flank frames.

Findings that shaped it (all three test sets: 25 knowledge-base crops, 85 real raw frames, 28 simulator frames incl. 14 without a pin):
- The simulator's frames are large and mostly black (lit window ~0.38 of the frame) and its pin sits against the window's left edge. At the 200-px working size the pin was ~15 px
  wide and the window's near-vertical edge outvoted the real flank (0/14 pin frames correct). Fix: measure the lit window first (pin-independent), run stage 1 also on the window
  crop (+5 % margin) and keep the crop result only if its stage-1 score is higher by `CROP_MARGIN` = 0.12 (sim pin frames +0.16..0.17, real frames +-0.01, the cases where the crop is
  slightly worse <= +0.09). Hough orientation tolerance tightened 0.30 -> 0.20 (support 0.45 -> 0.30), neutral on real data, fewer false regions.
- Result: KB 25/25 within IoU 0.968 of the verified polygons; real frames unchanged (85/85 both flanks, c 815.7, a -130.0, b -14.0, rms 3.95 px); simulator 14/14 pin frames with
  plausible geometry (top width ~144 px, half angle ~14.8 deg), 0/14 false positives on startup / camera_in_beam frames.
- End to end in headless Chrome (`scratch/gui_e2e/gui_e2e.py`, hook injected by a front server, repo page untouched): button toggles, overlay drawn, follows a 0.25 mm stage move
  (tip row 473 -> 836 px), clean "no pin recognised" text on the no-pin scenario, toggling off clears the overlay, no JS errors.

Known limits: a pin whose top is above the lit window (stage raised) is not recognised (reported as no pin, not as 'top clipped, move down'); a pin pushed mostly out of the window
gives a one-flank result without an axis column until a top width is learned.

## 9. Switch-over done (2026-11-17, user request: one workflow only)

Replaced / deleted: `blade/analysis/pin/` (pinfit, measure, beam_center, axis_align) - the directory was **git-ignored and never committed** (`.gitignore` line `analysis/`), so git cannot restore it; a local copy is in
`scratch/retired_pin_detection_2026-11-17/` (also the two old tests and the pre-change `pin_fit.py` / `pin_alignment.py`). `do_measure`, `fit_pin_in_view` (`vbl_centre_pin`), the button path and `fit_axis` / `overlay_jpeg` now use
`blade/pinregion`; `analyse_pin(method=...)` and `pin_geometry_legacy` are gone; dead profile keys `pin.min_contrast` / `pin.clip_margin_px` removed. Tests `test_identity.py` / `test_partial.py` (they tested the deleted API and
skipped here: their `tomo_alignment` data dir does not exist) were removed; `test_detection.py` was ported; `test_pinregion.py` gained `measure_frame` checks and the 85-real-frame regression.

Decisions made while doing it (all measured, see DECISIONS.md):
1. **The beam target stays the half-maximum footprint, not `fov`.** On real GH1 frames the `fov` window (4 % level, includes the dim halo) differs from the footprint by ~208 px in centre, so the planned "FoV centre replaces the
   footprint centre" fails its own parity condition. `pinregion/footprint.py` is the old footprint code, unchanged, now told which columns to ignore by the pin REGION: new vs retired centre on real frames mean 0.0, max 0.2 px.
   `fov` is only what the geometry judges clipping against.
2. **Top rim rule** (`geometry.TOP_RIM_FRAC` = 0.05 of the window height): a pin top cut by the window top had the window's soft rim fitted as 'top' (width 150 -> 210-290 px) and was called `in_view`; now `partial` + y hint. Nearest real
   tip is 0.155 of the window height from the top (85 frames), so legitimate frames are unaffected.
3. **No hint from a one-flank region without a learned width.** False-positive run on the KB's 277 pin-free `beam_only` tomo views (cropped screenshots): 20 (7 %) were accepted as a pin REGION - all one-flank, 0 usable, and (after this rule) 0 move
   hints. Residual risk: with a learned width such a region would be `usable` (axis = corner +- width/2); the procedures only trust it once the pin was in view at omega 0.
4. Identity check uses the profile tolerances (`pin.top_width_tol`, `pin.half_angle_tol_deg`), not the design's "~15 %".
5. A pin whose top is above the window with only ONE flank measured is no longer given a y hint (`do_find_pin` searches instead).

Results after the switch: 85 real GH1 frames all usable, c 815.7 / a -130.0 / b -14.0 / rms 3.95 px (unchanged); tip row 477.0, top width 148.1 px; synthetic closed-loop alignment converges; suite 36/36 (`blade` env).

NOT switched (on purpose): `calibration/pin_frames_fit.py::measure_frame` - an offline calibration measurement (silhouette + transmission + 10-90 % edge widths) whose tip-row / width conventions underlie the recorded simulator fits
(`pin_frames.json`); moving it needs the convention decision of section 6 items 2-3 and a re-fit. `procedures/pin_find.py` (chuck-shadow search) stays as stage 6's fallback, as designed.
