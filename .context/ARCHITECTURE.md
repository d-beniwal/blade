# Architecture

## BLADE (agent-driven CLI + passive web GUI + per-beamline profiles)

An agent (Claude Code, Codex, ...) reads a playbook (`playbooks/alignment.md`) and drives `blade align <cmd>`; each command prints JSON and appends to `runs/<id>/events.jsonl`.
`blade gui` is a read-only web server tailing that log (file-based, so CLI calls stay independent processes and the GUI/agent can restart). Install: `pip install -e .`; without it `python -I launch.py ...`.

- `blade/config.py` + `profiles/<name>/default_config.json` (+ git-ignored `active_config.json`): the ONLY source of beamline-specific values (cameras/pixel sizes/PV prefixes, motor roles -> PVs, signs, limits, tolerances, pin priors, procedure defaults); read as `cfg.NAME`. Profiles: `s1id`, `demo` (sim-only template). `blade/paths.py`: ROOT, RUNS_DIR (`BLADE_RUNS`), profile search path (`BLADE_PROFILES_DIR`).
- `blade/cli.py`: `blade align ...` | `gui` | `profiles`. `blade/session.py` (`Run`: one self-contained `runs/<id>/` folder: events, state incl. profile, frames, outputs, raw, figures, logs, report). `blade/gui.py` + `gui.html`.
- `blade/backends/`: `sim.py` (simulated instrument with hidden truth, default; frame model imitates gh1) and `epics.py` (real beamline: pvapy camera frames read-only, pyepics motor records; unit/soft-limit/readback checks); `get_backend` refuses backends the profile does not enable.
- `blade/alignment/` (first module): `cli.py` (primitives: measure, sweep, step-pm, adaptive-align, find-pin, move, note, finish, ...; only `move` and the explicit helpers move stages), `measure.py` (frame -> pin column, view state, beam footprint),
  `pinfit.py` (classical pin segmentation + cone geometry), `beam_center.py` (half-max footprint centre), `axis_align.py` (x(omega) model/fit helpers).
- Model: pin column `x(w) = c + a cos w + b sin w`; role `z` cancels b, `x` cancels a, `base` moves c to the beam centre (1-ID: samE.z, samE.x, samE.aerox). Details in the playbook.
- Adding a beamline: copy `profiles/demo`, edit (see `profiles/README.md`). Adding a capability: new sub-package beside `alignment/` + CLI group in `blade/cli.py` + playbook in `playbooks/`.

## Related codebases (read-only references)

- `../mpe_bluesky` (Sector 1/20 Bluesky/queueserver instrument): s1id device/PV names (`instrument/devices/s1id_devices/`: motors, slits, shutters, scalers, area detectors) and plans (`plans/s1id_plans/s1id_beam_delivery.py`, `scans_alignment.py`).
  Caution: Python files in its project root run at QS start.
- `../EAA-Pi` (TypeScript host for the Pi agent: MCP servers, skills, workflows, WebUI; Linux only). Evaluated 2026-10-31, not adopted; possible later front end (DECISIONS).
