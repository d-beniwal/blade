# BLADE — Beamline Automation and Device Experiments

A **virtual beamline** for APS beamlines, built to close this loop: *read the real beamline (PVs + one image) -> sync the simulator to it -> optimise in the simulator -> propose
the changes -> a person applies them -> read again.* Everything specific to one beamline lives in a **profile** and a **beamline twin** (`profiles/<bl>/`, `beamline_twins/<bl>/`), so
the software moves between beamlines by adding those.

**BLADE never commands the real beamline** (user decision 2026-11-15): there is no write path in the code. The real beamline is only *read*, through one gate
(`blade/instrument/readonly.py`: allow-listed read fields, channel-access GETs, pyepics writes disabled); the loop *proposes*, a person applies.
**Current scope:** Sector 1 (profile `s1id`, 1-ID). Status of each stage of the loop is in `.context/STATE.md`.

## Layout

| Path | What |
|---|---|
| `blade/instrument/` | **the one interface** (`Instrument`) between procedures and a beamline: `SimInstrument` (the virtual beamline) and `EpicsReader` (the real one, READ-ONLY; PV mapping in `pvmap.py`) |
| `blade/vbl/` | the simulator itself: `world.py` (controls, hidden truth, optics, flux, mono/undulator, ICs), `imaging.py` (camera frames), `store.py` (shared session), `readiness.py` (truth scoring) |
| `blade/physics/` | runtime physics (Bragg/edges, undulator, lenses, detector) |
| `blade/procedures/` | operator procedures on any `Instrument`: energy/flux, camera, optics, slits, the start-of-beamtime sequence, and the rotation-axis (pin) alignment |
| `blade/analysis/` | image analysis: line/ROI profile fits (`fitting`, `profile`), frame analysis (`frame`), pin detection (`pin/`) |
| `blade/loop/` | **the loop**: `sync` (real -> simulator), `estimate` (fit hidden offsets), `optimize` (procedure on a copy -> proposal), `run`, `demo` (stand-in dry run), `mapcheck` |
| `blade/calibration/` | OFFLINE fits of the simulator's parameters from the logbooks (`*_fit.py`); not on the runtime path |
| `blade/gui.py`, `*.html`, `*_api.py`, `nav.py` | the web GUI: virtual beamline `/vbl`, sync & loop `/loop`, physics `/physics`, knowledge base `/kb`, beamline twin `/twin` |
| `blade/registry.py`, `mcp_server.py`, `*/tools.py` | the MCP server (`blade mcp`): every capability is a registered tool - this is how other agents use BLADE |
| `blade/config.py`, `session.py`, `paths.py`, `cli.py` | profile loader, run record (events/frames/outputs), path configuration, CLI (`gui`, `mcp`, `profiles`) |
| `beamline_twins/<bl>/` | the machine-readable model of a beamline (elements, PVs, `sim.json`, `control_pv_map.json`, physics notes) + `tools/` (twin check/render, CS-Studio extract, read-only probe) |
| `knowledge_base/` | OFFLINE tooling that builds the private knowledge base from the logbooks (data lives outside the repo) |
| `profiles/<name>/default_config.json` | cameras, pixel sizes, per-hutch stations, limits. See `profiles/README.md` |
| `playbooks/` | what an agent reads: `loop.md`, `virtual_beamline.md`, `alignment.md` (pin), `image_analysis.md` |
| `tests/` | `python tests/run_all.py` runs everything (simulation / offline only) |
| `AGENTS.md`, `.context/` | project context for agents (state, decisions, domain notes) |

## Setup (once per machine)

```
conda env create -f environment.yml
conda activate blade
pip install -e .          # gives the `blade` and `blade-gui` commands; `python -I launch.py ...` works without it
```

**Open the GUI with one command** (no environment activation, no URL to type):

```
./blade-gui            # from this folder: starts the GUI and opens the virtual beamline in your browser
blade-gui loop         # open the sync & loop page (also: twin, physics, kb)
blade-gui --port 8800  # any `blade gui` option works
```

To run it from anywhere: `ln -s "$PWD/blade-gui" ~/.local/bin/blade-gui` (once). The script finds the `blade` conda env by itself (or set `BLADE_PYTHON=/path/to/python`; the GUI is stdlib-only, so plain `python3` also works). If a BLADE GUI is already running on that port it just opens it. Ctrl+C stops the server. Inside the activated env, `blade gui --open [--page twin]` and `blade-gui` do the same.

Commands: `blade gui` (virtual beamline on http://localhost:8765; also `/loop`, `/twin`, `/physics`, `/kb`), `blade mcp` (the MCP server for agents), `blade profiles` (list beamlines). Runs are written to `runs/<id>/` (override with `BLADE_RUNS`).

## The loop in practice

1. Verify the control<->PV mapping once (`beamline_twins/<bl>/control_pv_map.json`; evidence from `probe_readonly.py` + `blade.loop.mapcheck`). Only verified entries with a numeric transform are used.
2. On the beamline network, ask an agent: *"take a read-only snapshot and propose the energy/flux settings"* (`loop_real_snapshot`, `loop_propose` over MCP) - or do it from Python (`blade.loop`).
3. Apply the proposal yourself on the beamline; take the next snapshot.
No beamline at hand: `loop_dry_run` (or the button on `/loop`) runs the whole cycle on a stand-in simulator with a different hidden truth (the stand-in's score drops from ~17 to ~2).
See `playbooks/loop.md`.

## Try it without hardware

```
python tests/run_all.py                      # every test (simulation / offline), in parallel
python -I tests/test_loop.py                 # the loop: sync, estimate, closed loop on a stand-in, read-only enforcement
python -I tests/test_instrument_readonly.py  # the real-beamline reader cannot write (and only verified mappings are used)
python -I tests/test_pin_alignment.py        # rotation-axis alignment on synthetic frames
python -I tests/test_identity.py             # pin vs holder/other objects (needs real frames in the knowledge tree, data/)
```

## Code vs knowledge (two isolated trees)

This repo is the **code**: profiles, playbooks, twin descriptions, tools. It is meant to be shared with other people and beamlines, so nothing
sensitive or unpublished lives in it. Everything that may be - experiment logs and their index, the knowledge base built from them, raw beamline
data, reference photos/screenshots, alignment run folders, scratch work - lives in a separate **knowledge tree** whose location is configuration:

```
<knowledge root>/<beamline>/{kb, logs_index, logs_src, data, twin_photos, runs, scratch}      e.g. S1ID/blade_knowledge/1-ID/...
```

Point BLADE at it with `knowledge.json` (copy `knowledge.example.json`; git-ignored, or `~/.config/blade/knowledge.json`), or `$BLADE_KNOWLEDGE`.
Single folders can be re-pointed (`paths` in that file, or `$BLADE_KB`, `$BLADE_RUNS`, `$BLADE_DATA`, ...) - e.g. `cs_displays`, the folder with the
beamline's CS-Studio `.bob` displays (ground truth for PV names, read by `beamline_twins/tools/csdisplays.py`). `python -m blade.paths` prints
what resolves where. With nothing configured the fallback is an empty, git-ignored `knowledge_local/`, so a fresh clone never touches anyone else's data.
(`runs/<id>/` in this documentation means the `runs` folder of the knowledge tree.)

## Taking BLADE to another beamline

1. `cp -r profiles/demo profiles/<name>` and fill in `default_config.json` (cameras, a station per hutch, limits). Details: `profiles/README.md`.
2. Build the beamline twin (`beamline_twins/README.md`): elements, PVs, `sim.json`, and a `control_pv_map.json` whose entries you verify one by one.
3. Machine-specific overrides go in the git-ignored `profiles/<name>/active_config.json`; give the new beamline its own folder in the knowledge tree (`<root>/<twin id>/`).

## What a run produces

Everything for one run is in `runs/<id>/`: `events.jsonl`, `state.json`, `frames/`, `outputs/`, `raw/`, `figures/`, `logs/`, `report/`; the loop writes `runs/loop/{snapshots,frames,dryrun}/`.
Only `runs/CURRENT` (a pointer) lives directly in `runs/`.
