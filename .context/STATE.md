# Project state

Last updated: 2026-10-31 (BLADE rename)

## Now

Stage 1 only (user, 2026-10-27): beam assumed on the tomo camera; put the `samE.ry` rotation axis on the beam (pin axis stationary under rotation, axis column = beam centre).
Implemented and sim-tested; hardware-tested 2026-10-28 (links, signs, corrections OK; detection needed fixes, since applied).
Project is **BLADE** (renamed 2026-10-31; profile-driven, `profiles/s1id`). Standard entry: `blade align adaptive-align` (see `playbooks/alignment.md`); GUI `blade gui` (http://localhost:8765). Env `blade` (`pip install -e .`; or `python -I launch.py ...`).

Tests (all pass 2026-10-31): `tests/scripted_agent.py` (full sim alignment), `test_detection.py`, `test_identity.py` and `test_partial.py` (the last two need local `s1_data/`).

## Next steps

1. **Run `adaptive-align` on the real beamline** (`new-run --backend epics --camera gh1|pg1|pg5`); keep `runs/<id>/raw/`. Verify the one-sided (grey-wedge) rescue and thresholds on real raw frames — so far validated on simulated wedge only.
2. Hardware-confirm gh1 pixel size 0.69 um/px (user wrote "69 micron"); add the retiga2 (B hutch) PV prefix to `profiles/s1id/default_config.json` — until then it works in the simulator only.
3. BLADE growth: second beamline = new profile (copy `profiles/demo`); later modules (not started; need user input): wedge (axis tilt vs APS Y); slits (centre scans against an IC); undulator gap and monochromator edge/flux optimisation. Domain notes for these are in `DOMAIN.md`.
4. MCP: register `blade mcp` in the agents' clients; consider progress notifications for long routines, tools for estimate-pm/live-feed, `--http` auth. Every new module must register its tools (AGENTS.md).
5. Optional: an EAA-Pi front end (skill first, thin MCP wrapper over `blade` only if the beamline host is Linux and operators want a chat UI). Not now — see DECISIONS 2026-10-31.

## Open questions

- Beamline workstation OS (matters only for EAA-Pi, Linux-only) and whether an Argo vision model is available.
- Which of 1-ID-A/B/C/E stations are in scope for later stages; source-to-element distances; IC to PV mapping.
- Is the omega readback taken at exposure start/end rather than mid-exposure? (fits on frames recorded while rotating needed a ~-0.5 frame-step lag).

## Recent changes

- 2026-10-31 (later): **MCP server** `blade mcp` (registry + core/alignment tools + playbook resources); `tests/test_mcp.py` passes (16 tools, adaptive alignment over MCP, sim). Installed `mcp` 2.3.0 in env `beam-align-s1`. Not yet registered in any agent client.
- 2026-10-31 (later): motors + geometry moved under `profiles/<p>/stations/<hutch>` (s1id = hutch E only); `--station` / `BLADE_STATION`, stored in the run. Sim tests pass (env is still named `beam-align-s1` on this machine, not `blade`).
- 2026-10-31: **renamed to BLADE** and repackaged: `blade/` package (config, session, cli, gui, backends/, alignment/), `profiles/{s1id,demo}`, `playbooks/`, `pyproject.toml`, `launch.py`; motors by role (`base` = samE.aerox on 1-ID). Sim/tests identical to before; GitHub remote renamed, nothing pushed.
- 2026-10-31 (earlier): streamlined the project — removed superseded exploration scripts, analysis figures, scratch, prior-work notes and unused code; condensed context files.
- 2026-10-30: `adaptive-align` (user procedure), hardware gate removed (`--backend epics --camera X` connects when the user says so), one-line beamline prompt in the playbook.
- 2026-10-28: post-hardware-test overhaul: pin-excluded beam centre, flank validity, view states, raw frame saving, `step-pm`/`fast-align`, `find-pin`, per-run folders, per-camera pixel size, `aerox` confirmed as base motor, sign constants confirmed.
