"""BLADE beamline physics: what happens physically when a beamline setting changes.

Plain functions (SI-ish units named in each function: keV, Angstrom, mm, deg), no beamline connection, no globals. Sub-modules:
  core       energy/wavelength, absorption edges, Bragg angles + energy shift from a crystal-angle change, transmission/attenuation, delta/beta
  lens       refractive optics: tilted saw-tooth (prism-array) lenses as used at 1-ID, and conventional parabolic CRLs
  undulator  harmonic energy vs gap/current (simple Halbach model; parameters are ASSUMED/inferred, see the module docstring)
  detector   powder-diffraction ring geometry, field of view, camera pixel size from sensor pitch and magnification
Materials/edges/attenuation need `xraydb` (pip install xraydb==4.5.8, the version the beamline's own mpe_bluesky env uses; extra `physics`).
Each function's docstring says WHERE its formula comes from (textbook / beamline code / logs) so a reader can judge how far to trust it.
"""
from . import core, detector, lens, undulator  # noqa: F401
