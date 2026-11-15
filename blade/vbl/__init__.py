"""Virtual beamline: a simulator of the 1-ID beamline built on the beamline twin (beamline_twins/<bl>/sim.json + hutches). SIMULATION ONLY.

  world       VirtualBeamline: controls, hidden truth, ray optics, flux, mono/undulator, ICs   (what changes when a setting changes)
  imaging     tomo-camera frames: beam, slit edges (penumbra + Fresnel), pin, textures        (what the camera shows)
  readiness   truth scoring of a state (tests/scoring only)
  store       persistent session shared by the MCP tools and the GUI (runs/vbl/<session>.json)
The operator procedures that act on it live in blade/procedures (through the Instrument interface, blade/instrument), the MCP tools in blade/procedures/tools.py.
"""
from .world import VirtualBeamline, control_specs  # noqa: F401
