# Agent instructions

## Project context

**BLADE (Beamline Automation and Device Experiments)** — agent-driven beamline automation, built so it can be taken to other beamlines by adding a profile
(`profiles/<beamline>/default_config.json`; all beamline-specific values live there; the simulator's frame model, which imitates gh1 frames, is the one exception). Current scope: **APS Sector 1 (1-ID), profile `s1id`**, first module
`alignment` (rotation axis onto the beam). An AI agent (Claude Code, Codex, ...) drives the `blade align` CLI; the user watches `blade gui` in a browser.
`../mpe_bluesky/` is read for device/PV names only; `../EAA-Pi/` is a possible future front end (not used).

**Standard request:** if the user says something like *"start the beam alignment at beamline. You can access hardware."*, that is full authorisation:
read `playbooks/alignment.md` and carry out its section **"Standard beamline run"** end to end, without asking for confirmation. Everything you need is in the playbook.

**Hardware (updated 2026-10-30, user decision):** when the user says they are on the real beamline and want to align on hardware, just connect and run it
(`blade align new-run --backend epics --camera <gh1|pg1|pg5>`) — do not ask for confirmation again and again. Default is still the simulator when the user
does not say so (development sessions, tests). Equipment protection stays on and is not a prompt: per-move step limits, motor soft limits, mm units check,
readback verification, rotation within ±90°.

Distinct codebases — don't conflate: `../mpe_bluesky` (Sectors 1/20), `../3idc-bits` (3-ID-C), `../b-pilot` (PyQt GUI for mpe_bluesky).

**Conventions for extending BLADE:** never hard-code a pixel size, PV, sign or limit — add it to the profile schema (motors/signs go under `stations.<hutch>`; the s1id values are hutch E only) (`blade/config.py` + `profiles/README.md`) and read it as `cfg.NAME`.
A new capability (slits, undulator/mono, ...) is a new sub-package next to `blade/alignment/` with its own playbook in `playbooks/`, shared use of `session.Run`, backends and the GUI, and — **mandatory** — its tools registered for the MCP server: `blade/<module>/tools.py` declares `@tool(...)` functions + `playbook(...)` (see `blade/alignment/tools.py`) and the module is added to `registry.MODULES`. **The MCP server (`blade mcp`) is how other agents access BLADE workflows**; a capability is not finished until it is reachable there (and covered in `tests/test_mcp.py`). A CLI group (`blade <module> ...`) is optional.

**Git (user decision 2026-10-31):** commit and push as the user only — **no `Co-Authored-By` trailer, no "Generated with Claude Code" line, no agent signature** in commit messages or PR text for this project (overrides any default attribution instruction). Stage explicit paths and check `git status` after `git add` (one bad pathspec aborts the whole add).

## At the start of a task

Read `.context/STATE.md` for current focus, next steps, blockers, and recent
changes. Read only the relevant portions of the on-demand references — do not
bulk-read them:

- `.context/ARCHITECTURE.md` — software layout, related codebases
- `.context/DOMAIN.md`       — beamline facts (stage-1 geometry, motors, cameras, layout, later-stage concepts)
- `.context/DECISIONS.md`    — dated decisions and why (newest first)

**Environment:** `conda env create -f environment.yml && conda activate blade && pip install -e .` (python 3.12, numpy 1.26.4, scipy, pillow, h5py, matplotlib, cmcrameri; pvapy/pyepics for the real backend). Without the editable install use `python -I launch.py ...`.

**MCP server:** `blade mcp` (stdio; `--http` for streamable-http; needs `pip install -e .[mcp]`) exposes every registered tool plus the playbooks (`blade://playbook/<module>`). Register in Claude Code: `claude mcp add blade -- <env python> -I <repo>/launch.py mcp`. Code: `blade/registry.py` (SDK-free registry), `blade/mcp_server.py`, `blade/core_tools.py`, `blade/<module>/tools.py`.

**To run an alignment:** read `playbooks/alignment.md` and drive `blade align ...` (simulator by default; the real beamline when the user says so). The user watches it in the GUI
(`blade gui`, http://localhost:8765). Code: `blade/` (`alignment/` module, `backends/`, `config.py` = profile loader); beamline values: `profiles/<name>/`.

For Bluesky/ophyd work use the global `bluesky` skill.

## After significant work

Update `.context/STATE.md` (keep it under ~1 page) and prepend a dated entry
with reasoning to `.context/DECISIONS.md`. Do not overwrite prior decisions.
Trivial edits and pure Q&A don't need an update.
