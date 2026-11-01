# Decisions

Add new decisions at the top using `## YYYY-MM-DD — Short title`. Only decisions that still hold are kept here; superseded approaches were removed on 2026-10-31 (history is in git).

## 2026-10-31 — MCP server is the front door for agents; capabilities register once (user)

Other agents access BLADE through an MCP server (`blade mcp`), not by learning the CLI. `blade/registry.py` (no MCP dependency) is the single declaration point: each module's `tools.py` registers `@tool` functions (`fn(run, **args)->dict`, docstring = agent-facing description, `moves=True` for motor-moving tools) and its playbook;
`blade/mcp_server.py` exposes whatever is registered (tools with read-only/moves annotations, playbooks as `blade://playbook/<module>`, server instructions). Core tools (`core_tools.py`): list_profiles, new_run, run_status, list_runs, add_note, finish_run; alignment: align_* wrapping the same `do_*` functions as the CLI, so CLI and MCP cannot diverge.
Rule: a new capability is not done until registered here (added to `registry.MODULES`) and covered in `tests/test_mcp.py`. Safety unchanged: simulator default, hardware only via `new_run(backend='epics')` when the user authorised it, equipment limits inside the tools. Calls are serialised with a lock (cfg is process-global); each tool takes an optional `run_id`.
Supports mcp 1.x (`FastMCP`) and 2.x (`MCPServer`); `mcp` is an optional dependency (`blade[mcp]`). Not done: MCP progress/streaming for long routines, estimate-pm/live-feed tools, authentication for `--http`.

## 2026-10-31 — Motors + geometry are per station (hutch), not per beamline (user)

The s1id motors (`samE.*`, aerox base) and sign geometry were measured for **hutch E** only; other hutches may have different stages/geometry. Profile now has `stations.<hutch> = {description, motors, geometry}` + `default_station` (s1id: `E`; demo: `sim`).
`config.load(profile, station)` publishes the chosen station's motors/geometry (`cfg.STATION`, `cfg.STATIONS`); station comes from `new-run --station`, stored in run `state.json`, else `$BLADE_STATION`, else `default_station`. Cameras stay beamline-level (each names its hutch);
limits/tolerances/pin remain profile-wide (move under a station if a hutch needs different ones). A profile without `stations` (legacy flat motors/geometry) still loads as one station. Adding a hutch = add a sibling entry; nothing else changes.

## 2026-10-31 — Renamed to BLADE; profile-driven, packaged for other beamlines (user)

Project renamed **BLADE (Beamline Automation and Device Experiments)**, repo/dir `blade` (was `beam_alignment_s1`), to grow into general beamline automation; current scope stays Sector 1, alignment is the first module.
Structure mirrors the B-PILOT idea of per-beamline profiles: all beamline-specific values (cameras + pixel sizes + PV prefixes, motor roles -> PVs/names, signs, limits, tolerances, pin shape, procedure defaults) moved out of code into
`profiles/<name>/default_config.json` (+ git-ignored `active_config.json` override, extra dirs via `BLADE_PROFILES_DIR`); `blade/config.py` loads a profile into `cfg.*` (the old `align_config.py`). Profiles: `s1id` (real) and `demo` (simulator-only template).
The profile is chosen at `new-run --profile` (default `$BLADE_PROFILE` or `s1id`), stored in the run's `state.json`, and re-loaded by every later command and by the GUI.
Motors are addressed by role (`omega,x,y,z,base`); the 1-ID base motor `samE.aerox` is the profile's `base` (display name from the profile). Package: `blade/{config,paths,session,cli,gui}.py`, `blade/backends/{sim,epics}.py`,
`blade/alignment/*` (module); CLI `blade align|gui|profiles` (`pip install -e .`, or `python -I launch.py ...` without install); `pyproject.toml`, env `blade`. Playbooks live in `playbooks/` (one per module).
Backends not enabled in a profile are refused (`demo` is sim-only). New modules (slits, undulator/mono, ...) = new sub-package + CLI group + playbook, sharing runs, backends and GUI.
Removed `make_report.py` (a one-off script hard-wired to the 2026-10-28 run files). Verified after the restructure: identical sim result (a 0.009, b 0.008, c−beam −0.008 px), all tests, demo profile, refusal paths, GUI config endpoint, wheel build.
Not done: GitHub remote push (rename only), a real second-beamline profile, `blade <module>` registry (modules are wired by hand in `blade/cli.py`).

## 2026-10-31 — Streamline; keep the CLI + playbook approach; EAA-Pi not adopted now (user)

Evaluated integrating with EAA-Pi (skill / MCP wrapper / workflow). Decision: stay with the agent-driven CLI. Reasons: stage 1 is deterministic (`adaptive-align` is one command), EAA-Pi is Linux-only (this Mac and the beamline OS unknown),
it would duplicate our GUI/event log, and the safety limits must stay in `blade/` regardless. Revisit for later stages (slits/edge/flux), preferably as skill + thin MCP wrapper over `balign`.
Removed: exploration scripts (h5_tree, make_*_figures, pin_segment, test_segmentation, test_pinfit_*, test_axis_align_scan), `grab_frame`/`save_beam_figure`, unused `_footprint_steps`, `analysis/`, `scratch/` (incl. prior-work clone), `NOTES.md`,
loose files in `runs/`, `REFERENCE_prior_work.md`. Kept: working software, tests, hardware runs `runs/20261028-*`, local `s1_data/`.

## 2026-10-30 — One-line beamline prompt; hardware gate removed (user)

"Start the beam alignment at beamline. You can access hardware." is full authorisation: `AGENTS.md` maps it to the playbook's "Standard beamline run" (camera named else `DEFAULT_CAMERA` = gh1 and announced; start GUI; `new-run --backend epics`; `adaptive-align`;
one remedy attempt; finish + report). The repeated-confirmation / `BALIGN_ENABLE_HARDWARE` gate was an obstacle on the beamline and is gone; default stays the simulator. Equipment protection is kept (not prompts): per-step move limits (moves split),
soft limits, mm-units check, readback check, rotation within ±90° (`MAX_ROT_DEG`).

## 2026-10-30 — `adaptive-align` procedure (user)

omega -> 0; pin axis to the beam centre (x); rotate + in 15° steps until the pin can no longer be measured, rotate − likewise (retry 7.5° then 3.75° if not even one step works); fit x(w)=c+a cos w+b sin w (weighted LSQ) to all points of the pass;
correct z<-b, x<-a, aerox<-c−beam; repeat. If a pass reaches ±90° on both sides, later passes use 0, +90, −90 only. A half-visible pin is located from its visible part and counts with weight 0.3; `a` is applied only partly and aerox not at all while
the range is < 30° (ill-conditioned); with < 3 points the pass corrects z from b alone (small-angle mode). Converged = |a|,|b| < `TOL_AB_PX`, |c−beam| < `TOL_C_PX` with range ≥ 30°. Sign-suspect stop if a/b fail to shrink after a correction.

## 2026-10-28 — Detection guards, partial/absent pin handling (after first hardware runs)

Problems seen live: the beam centre was dragged by an off-centre pin shadow (up to ~150 px); at |omega| ~60–90 the pin has a grey half-transparent flank (bevel) that was fitted as an edge; an "empty" frame was a pin out of view.
Fixes: pin-excluded beam footprint (`measure.beam_footprint`); a frame is accepted only if both flanks have the nominal half-angle (15.2° ± 3°) and corners are ≥ 30 px inside the footprint, else the axis comes from the good flank ± half the learned top width
(`one_sided_*`), else the frame is rejected with reasons (never guessed). `view.state` = in_view | partial (+hint) | absent | other_object | no_beam; the field of view is the lit footprint. `locate_partial` finds a partly visible pin from per-row extents and the cone model.
`find-pin` follows the hint or searches x then y outward within `SEARCH_RADIUS_*` and returns to the start if not found. Pin identity: the cone-like dark object (width vs row slope ≈ 2 tan 15.2° = 0.544) is picked, not the biggest; holders/other objects are never the pin.
Raw frames are saved per measurement (`runs/<id>/raw/*.npz`). Not yet validated on real raw wedge frames.

## 2026-10-28 — Fast workflow, no calibration; constants confirmed (user)

Signs/scales are confirmed constants, not learned per run: `IMAGE_COL_PER_X=-1` (+x moves the pin left), `ROT_SIGN=+1` (stage is left-handed: +omega clockwise from the top), `IMAGE_ROW_PER_Y=-1` (+y moves the pin up; hardware-confirmed), base motor `samE.aerox`
(~−1431 px/mm on gh1, hardware-measured), z +1456, x −1458 px/mm. `calibrate` remains only as a diagnostic. Per-camera pixel size via `set_camera` (retiga2 1.0, pg5 1.17, gh1 0.69, pg1 1.17 um/px; `PIXEL_UM` is the active camera's).

## 2026-10-28 — One self-contained folder per run (user)

Everything for a run lives in `runs/<id>/` (`events.jsonl`, `state.json`, `frames/`, `outputs/` (every CLI JSON), `raw/`, `figures/`, `logs/`, `report/`); only `runs/CURRENT` is at the top level. Agents must never write into `runs/` itself, `/tmp` or the repo root.

## 2026-10-28 — Only the alignment software is tracked

Git-ignored: `s1_data/`, `analysis/`, `runs/`, `scratch/`, caches. Tracked: software, tests, `environment.yml`, `AGENTS.md`, `playbooks/alignment.md`, `.context/`.

## 2026-10-27 — Architecture: agent-driven CLI + passive web GUI + simulated backend

The user starts the alignment from an agent; the agent makes every decision, tools never loop or move on their own (except explicit helpers). `blade align` = JSON CLI of primitives (agent-neutral, no MCP needed); every command appends to `runs/<id>/events.jsonl`;
`blade gui` tails it read-only. Default backend is the simulator (`blade/backends/sim.py`, hidden ground truth). Real backend (`blade/backends/epics.py`) uses pvapy for camera frames (read-only) and pyepics motor records (omega `1ide:m9`, x/y/z `1ide1:m34/35/36`, aerox `m101`).
GUI shows answers, not raw events: progress tracker, "Agent says", verdict tiles (a, b, c−beam with tolerance and sparklines), stale-data warning, camera tab, pin-position plot, moves table, notes, collapsed raw log.

## 2026-10-27 — Stage-1 scope, "aligned", axis fixed by the base, wedge deferred (user)

Stage 1 assumes the beam is already on the tomo detector: no slits, edge or flux; wedge (axis tilt) ignored. Aligned = flux maximised at the edge + pin in view + pin axis stationary over −90..+90° (only the last part is automated now). Rotation motor = `samE.ry`.
The axis is fixed by the base: `samE.x/y/z` move only the pin (cancel a, b); `samE.aerox` moves the axis column c onto the beam centre. Why staged: de-risk by adding automation one stage at a time.

## 2026-10-27 — Beam centre = midpoint of the half-maximum footprint (user)

Per axis: smoothed mean profile, plateau = 90th percentile, base = 5th percentile, edges at base + 0.5(plateau − base), centre = midpoint (box found iteratively). Robust to the saturated, lopsided core; core peak or the 10 % footprint shifted the centre by tens of px. Code: `blade/alignment/beam_center.py`.

## 2026-10-27 — Classical pin segmentation, not a learned model

Pin is a high-contrast dark silhouette: lit-area box -> subtract outside dark level -> divide by a polynomial beam model -> threshold at the midpoint of beam and pin levels -> opening, largest component, hole fill. Naive global/box Otsu failed with gradients; a step-edge lit-area finder regressed under noise and was removed.
Virtual top corners (side line meets top line) define the axis because the real tip is bevelled on one side. Validated: IoU ≥ 0.99 vs the clean mask under brightness, offset, noise, vignette, hot pixels, blur, crop. SAM-type models were skipped.

## 2026-10-26 — Agent-neutral context; `mpe_bluesky` as device reference

`AGENTS.md` + `.context/` (no `CLAUDE.md`). `mpe_bluesky` s1id devices/plans are read only to pick the relevant devices/PVs.
