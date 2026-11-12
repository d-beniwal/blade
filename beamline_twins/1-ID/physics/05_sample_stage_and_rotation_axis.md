# 5. Sample stage and rotation axis (hutches E and C)

Twin: `assemblies/samE.json` (stack, limits), element `samE`; C: `samC`. BLADE's alignment model lives in `blade/alignment/` (`x(w) = c + a cos w + b sin w`). Citation keys: `README.md`.

## 5.1 What each motion does physically
- **Rotation (Aero Ry, `samE.ry`)** spins the sample about a vertical axis; a pin offset from the axis traces a sinusoid in the tomo image, `x(w) = c + a cos w + b sin w`: `c` = axis column, `(a, b)` = offset across / along the beam. samE.x cancels `a`, samE.z cancels `b`, **Aero X (`samE.aerox`) moves the whole axis, i.e. `c`** (-1431 px/mm on GH1, measured 2026-10-28 by BLADE). Residual `a`, `b` become sample wobble in tomography and wrong omega-dependent positions in HEDM.
- **samE.y** lifts the sample (find-pin only); it also moves the sample along a camera's focal plane: "inline camera focal plane at samY = -2.0 mm" [A22 AM-setup log].
- **Tilts** (samTh Rx, samChi Rz, Kohzu stack): tilt of the rotation axis ("wedge"). A pin tip that stays at the same image row for a full turn means no wedge: tip row changed ~2 px over 180 deg in BLADE test data and "wedge ~0 deg (0.5 px over 16 mm)" [M26a:L168]. A measured rx tilt of the C lab-motion axis: 3 px = 3.51 um over 16 mm -> **0.015 deg** [S25b:L169-188]. Estimate: `tilt = atan(delta / L)`.

## 5.2 Where the axis is relative to the beam, and why it moves
- After the APS-U start the beam moved ~1.7 mm inboard in E, so the rotation axis moved with it: **aeroXE -2.426 mm** (re-zeroed inside SPEC) [S25a:L594-600]. The tomo beam centre pixel changed from (1270, 700) to (1100, 850) once the tomo tilt was aligned [M26a:L145-151]. Rule: **after any steering change or beam dump, re-find the beam on the tomo camera, then re-bring the axis onto it** (BLADE `adaptive-align`).
- Axis position vs sample height: moving z by 16 mm shifted the pin only 2 px (956 -> 954) at ry = 0 and ry = 180 returned 956 [S25b:L169-171].
- A **thermal/beam-induced growth** of ~1 px (0.69 um) in 2-3 min on a heated-by-beam test sample shows the practical alignment floor for long scans [M26a:L170].
- Rotation geometry from the stage: "aero 0-angle with delta_samZ = -8 mm: arcsin((251 x 0.69)/16000) = 0.6202 deg" [M26a:L167]: pixels times pixel size over the lever arm give the angular zero error.
- Rotation-stage electronics: a rotation IOC that toggled torque at ~1 Hz blocked bluesky until restarted [S25a:L441-444]; the C lab-motion rotation did not fly for tomo until configured [S25b].

## 5.3 Detector distance depends on where the sample is
CeO2 calibration distance varied 613.2 / 612.8 / 611.8 mm for rotXC -65.85 / -26.05 / +14.00 (about 0.7 mm per 80 deg), so a sample that is not on the true rotation axis changes the effective distance [M26b:L47-58] (see `06_detectors_and_cameras.md`).
