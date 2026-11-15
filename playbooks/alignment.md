# BLADE rotation-axis (pin) alignment (for the agent: Claude Code, Codex, ...)

**Status (2026-11-15).** This is the former `blade align` module, consolidated into the procedure library (`blade/procedures/pin_alignment.py`; image analysis `blade/analysis/pin/`).
The old CLI, the "Alignment Monitor" GUI page and the hardware backend were **retired**: BLADE does not command the real beamline. It runs on the SIMULATOR only (MCP tools `new_run`, `align_*`)
and its decision logic is tested on synthetic frames (`tests/test_pin_alignment.py`) and real frames (`tests/test_identity.py`, `tests/test_partial.py`, need the knowledge tree).
**KNOWN OPEN:** on the virtual beamline's textured frames `align_adaptive` does not converge (the realistic footprint clips the pin; see `.context/STATE.md`).
What follows is the knowledge worth keeping: the model, what detection tells you, and the procedure the operators/hardware tests validated (2026-10-28/30).

Goal: put the **pin on the rotation axis** (a, b → 0) and the **rotation axis on the beam centre** (c → beam centre). Assumes the beam is already on the tomo detector.
Everything beamline-specific (cameras, pixel sizes, motor names, signs, limits, tolerances) comes from the **profile**; motors are addressed by role: `x`, `y`, `z` (pin), `base` (moves the rotation axis), `omega`.
Equipment-style limits remain in the procedure as sanity checks: per-step move limits (`MAX_STEP_PIN_MM`, `MAX_STEP_BASE_MM`; moves are split), rotation within ±`MAX_ROT_DEG` (90°).

## Tools (MCP; each acts on the run's simulated instrument)
`new_run`, `align_goto_omega`, `align_measure`, `align_sweep`, `align_propose` (moves nothing), `align_adaptive` (the standard routine), `align_fast`, `align_step_pm`, `align_find_pin`, `align_move`, `align_calibrate`,
`run_status`, `add_note`, `finish_run`. On a read-only instrument every move raises `ReadOnlyError`.

## Model (what the numbers mean)
Pin column vs rotation angle: `x(ω) = c + a·cos ω + b·sin ω` (px). `c` = rotation-axis column (fixed by the base; **samE.x/y/z do not change it**),
`a` = pin offset along image-x at ω=0 (cancelled by **samE.x**), `b` = pin offset along the beam (cancelled by **samE.z**). The base motor
(role `base`; `samE.aerox` on 1-ID, sign from the profile) moves `c` (and the pin with it). Tolerances: |a|,|b| < `TOL_AB_PX`, |c − beam centre| < `TOL_C_PX`.
Beam centre = midpoint of the half-maximum footprint (median over the sweep frames).

## Detection (what `measure` tells you)
Every measurement has `view.state`: **in_view** (usable), **partial** (pin seen but cut off / edges unreliable; `view.hint` = the x/y move that centres it, `view.locate` = estimated axis column and top row from the visible part),
**absent** (no dark pin-sized object inside the lit footprint), **other_object** (a dark object is in view but it is not cone-shaped like the pin — e.g. the holder; treated like absent by `find-pin`), **no_beam** (no lit footprint). The *field of view is the lit footprint*, not the sensor.
`pin_col` is only set for **usable** frames (`quality`: `both_flanks`, or `one_sided_left/right` when one flank was the grey bevel wedge at large |ω| and the other
flank + the learned top width were used). Rejected frames carry `reasons`; never use their `pin_col_raw`. The beam centre ignores the pin shadow.
The pin's top width is learned from the first both-flank frames (so measure ω=0 first, or let `step-pm` do it). Raw frames are in `runs/<id>/raw/*.npz`.

## Procedure (no calibration — signs/scales are confirmed constants)
1. `new_run(backend='sim'|'vbl', camera=...)`; `add_note` the plan.
2. `align_adaptive`. It does, by itself: ω→0 · bring the pin into view (`align_find_pin` / hint moves) · centre the pin axis on the beam centre (x) · pass 1: rotate +15° steps until the pin cannot
   be measured (if not even at 15°: retry with 7.5°, then 3.75°), then − likewise (a half-visible pin is located from its visible part and counts with weight 0.3) · fit x(ω)=c+a·cosω+b·sinω to every measurement · correct (z←b; x←a, only a fraction
   if the range is < 30°; base←c−beam only if the range ≥ 30°) · repeat. Done when |a|,|b| < `TOL_AB_PX` and |c−beam| < `TOL_C_PX`. It stops with a reason if a/b fail to shrink after a correction
   (sign suspect; the check allows for only part of a having been applied), if the pin leaves the view within the smallest step (3.75°), or after `--max-passes`. When the pin is measurable over only a few degrees the pass corrects z from b alone (small-angle mode) and the next pass has a larger range.
3. Result JSON: `passes` (limits ±, n points, a, b, c−beam, applied moves). If `ok` is false read `reason`, narrate it, `finish_run(status='failed')`. Otherwise `finish_run(status='ok', summary='<final a, b, c−beam>')`.
Manual / diagnostic building blocks: `align_step_pm`, `align_fast`, `align_sweep`, `align_calibrate`, `align_propose`, `align_move`. `align_calibrate` is not part of a normal run.
Narrate with `add_note` before each decision.

## Reference
`tests/test_pin_alignment.py` (synthetic frames, full adaptive alignment), `tests/test_detection.py` (detection logic), `tests/test_identity.py` / `tests/test_partial.py` (real frames; knowledge tree).
