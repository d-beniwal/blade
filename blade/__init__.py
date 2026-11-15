"""BLADE - Beamline Automation and Device Experiments.

Agent-driven beamline automation built around a virtual beamline: sync a simulator to the real beamline's state (READ-ONLY), optimise in the simulator,
propose the changes. Layers: `instrument` (one interface; simulator + read-only EPICS reader) -> `procedures` (operator scans, pin alignment) -> `loop`
(sync / estimate / optimise / propose); supporting: `vbl` (simulator), `physics`, `analysis`, `calibration` (offline fits), GUI (`blade gui`), MCP (`blade mcp`).
NOTHING in BLADE commands the real beamline (user decision 2026-11-15)."""
__version__ = "0.1.0"
