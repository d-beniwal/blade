"""Operator-level procedures: the scans and image measurements the logbooks describe, plus the whole start-of-beamtime sequence and the rotation-axis (pin)
alignment. They act ONLY through the `Instrument` interface (blade/instrument/base.py) and use only what an operator can observe (IC counts, mu_t, camera
frames); the hidden truth of the simulator never enters (scoring: blade/vbl/readiness.py).

    energy.py    gap / Th2 / foil-edge energy calibration        camera.py   exposure, find + centre beam, steering check
    optics.py    camera focus, lens tilt scans                   slits.py    slit + fast-shutter alignment
    startup.py   the whole start-of-beamtime sequence            pin_alignment.py  rotation axis onto the beam (the former `blade align`)
    pin_find.py  bring the pin into view of the tomo camera (3-D mount model as a search aid)
    pin_fit.py   if the pin is recognised in the frame, fit it into the field of view (axis on the footprint centre, tip near the top)
Flat re-exports so `from blade import procedures as P; P.gap_scan(inst, ...)` works."""
from ..analysis.frame import analyze_frame, fit_peak
from .energy import open_gap, nominal_gap, gap_scan, th2_scan, select_edge, edge_scan, calibrate_energy, tune_energy_flux
from .camera import tune_exposure, find_beam_on_camera, centre_camera_on_beam, steering_check
from .optics import focus_camera, lens_scan
from .slits import slit_image_centre, align_slit, slit_ic_scan, align_fast_shutter, _ic_after
from .startup import startup_sequence
from .pin_find import find_pin, plan_pin_search
from .pin_fit import fit_pin_in_view
from ..vbl.readiness import readiness

_fit_peak = fit_peak          # old private name, kept for the callers that used it
