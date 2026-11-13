"""Virtual beamline: a simulator of the 1-ID beamline built on the beamline twin (beamline_twins/<bl>/sim.json + hutches). SIMULATION ONLY.

  world       VirtualBeamline: controls, hidden truth, ray optics, flux, mono/undulator, ICs   (what changes when a setting changes)
  imaging     tomo-camera frames: beam, slit edges (penumbra + Fresnel), pin, textures        (what the camera shows)
  procedures  operator scans/measurements + the start-of-beamtime sequence + truth scoring    (how the beamline is aligned)
  store       persistent session shared by the MCP tools, CLI and GUI (runs/vbl/state.json)
  tools       MCP tools (registered through blade.registry)
"""
from .world import VirtualBeamline, control_specs  # noqa: F401
