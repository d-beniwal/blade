"""Offline calibration of the simulator's parameters from the 1-ID logbooks (fits -> `beamline_twins/1-ID/physics/fits/*.json` -> `sim.json`).

These are analysis scripts with their own tests (`tests/test_fit_*.py`); nothing in the runtime path (instrument, procedures, loop, GUI) imports them. The runtime
counterpart - estimating the *current* hidden state of the real beamline from live PV/image data - is `blade/loop/estimate.py`."""
