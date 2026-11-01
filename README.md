# BLADE — Beamline Automation and Device Experiments

Agent-driven beamline automation for APS beamlines. An AI agent (Claude Code, Codex, ...) drives small JSON command-line tools while you watch a live local web GUI.
Everything specific to one beamline lives in a **profile** (`profiles/<beamline>/`), so the same software moves between beamlines by adding a profile.

**Current scope:** Sector 1 (profile `s1id`, 1-ID). Implemented module: **alignment** — put the rotation axis (`samE.ry`) of the sample stage on the X-ray beam by imaging an
alignment pin on a tomo camera, rotating it, and correcting the stage motors until the pin axis stays fixed in the image at the beam centre. Later modules (slits, undulator / mono edge and flux, ...) plug in beside it.

## Layout

| Path | What |
|---|---|
| `blade/` | the Python package: `config.py` (profile loader), `session.py` (runs), `cli.py`, `gui.py`/`gui.html`, `paths.py` |
| `blade/backends/` | `sim` (simulator, default) and `epics` (real beamline: pvapy camera frames + pyepics motors) |
| `blade/alignment/` | the alignment module: `cli.py` (commands), `measure.py`, `pinfit.py` (pin detection), `beam_center.py`, `axis_align.py` |
| `blade/registry.py`, `blade/mcp_server.py`, `blade/*/tools.py` | the MCP server (`blade mcp`): every capability is registered as a tool here; this is how other agents use BLADE |
| `profiles/<name>/default_config.json` | cameras, pixel sizes, per-hutch `stations` (motor PVs/names, signs), limits, tolerances, pin shape. See `profiles/README.md` |
| `playbooks/alignment.md` | the agent's instructions for the alignment module — **the agent reads this** |
| `AGENTS.md`, `.context/` | project context for agents (state, decisions, domain notes) |
| `tests/` | simulator end-to-end test and detection tests |
| `launch.py` | run from a checkout without installing: `python -I launch.py align ...` |

## Setup (once per machine)

```
conda env create -f environment.yml
conda activate blade
pip install -e .          # gives the `blade` command; `python -I launch.py ...` works without it
```

Commands: `blade align <cmd>` (alignment), `blade gui` (monitor on http://localhost:8765), `blade profiles` (list beamlines). Runs are written to `runs/<id>/` (override with `BLADE_RUNS`).

## Running on the Sector 1 beamline

1. On the beamline workstation: `conda activate blade`, then start Claude Code in this folder (`claude`). The camera must already be acquiring.
2. Open http://localhost:8765 in a browser (the agent starts the GUI if it is not running).
3. Tell the agent (this is the whole prompt):

```
Start the beam alignment at beamline. You can access hardware.
```

   Optionally add the camera (`... Use pg1.`; default is `gh1`) or a variation (`... First move the pin 1 mm down.`). That sentence authorises connecting to the hardware; everything else
   (read the playbook, start the GUI, run `adaptive-align`, retry once on failure, report the result) is in `AGENTS.md` / `playbooks/alignment.md` ("Standard beamline run").

Notes:
- The camera sets the pixel size (s1id: retiga2 1.0 µm/px, pg5 1.17, gh1 0.69, pg1 1.17). `retiga2` (B hutch) has no PV prefix yet, so it only works in the simulator until one is added to the profile.
- Equipment protection is always on and is not a confirmation prompt: per-move step limits (larger moves are split), motor soft limits, mm-units check, readback check after every move, rotation limited to ±90°.
- If the pin is not in the beam, `adaptive-align` calls `find-pin` (searches x then y within ±3 mm / ±2 mm of the start; returns to the start if nothing is found).
- Every frame is saved in `runs/<id>/raw/` — keep them: they are how detection problems are debugged afterwards.
- Without the words "at beamline" / "hardware" the agent uses the simulator.

## Try it without hardware

```
python -I tests/scripted_agent.py            # full alignment on the simulator, ~20 s
python -I tests/test_detection.py            # detection logic on simulated frames
python -I tests/test_identity.py             # pin vs holder/other objects (needs the local s1_data/ folder)
python -I tests/test_partial.py              # partly visible pin (needs s1_data/)
blade align new-run --profile demo           # the generic simulator-only profile
```

## Taking BLADE to another beamline

1. `cp -r profiles/demo profiles/<name>` and fill in `default_config.json` (cameras and PVs, a station per hutch with motors and signs, limits). Details and the checklist: `profiles/README.md`.
2. Machine-specific overrides go in the git-ignored `profiles/<name>/active_config.json`; a profile folder can also live outside the repo (`BLADE_PROFILES_DIR`).
3. Prove it on the simulator (`--profile <name>`), then on hardware with `--backend epics --camera <name>`.

## What a run produces

Everything for one run is in `runs/<id>/`: `events.jsonl`, `state.json` (includes the profile), `frames/` (overlay JPEGs the GUI shows), `outputs/` (the JSON each command printed), `raw/`, `figures/`, `logs/`, `report/`.
Only `runs/CURRENT` (a pointer) lives directly in `runs/`.
