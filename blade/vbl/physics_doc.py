"""Catalogue of the physics models built into the virtual beamline (served by the GUI at /physics).

SIMULATION ONLY. Every entry describes code that exists in blade/vbl/{world,imaging,procedures}.py or blade/physics/*; parameter VALUES are not copied here but read live
from beamline_twins/<bl>/sim.json (so the page cannot drift from the simulator), together with the provenance note stored next to each value. The curves are computed by
calling the real simulator functions on an 'aligned' world, not by re-implementing the formulas.

An entry: id, section, title, status, summary, equations (plain text), how (bullets), params [(label, sim.json path, unit)], code (where), evidence (tests / fit notes), limits.
status: fitted (constants fitted to logged numbers) | validated (checked against logged numbers) | textbook (standard physics / the beamline's own formula) |
        assumed (a chosen value or structure with no data behind it) | mixed (see the entry). Keep entries honest: if a model is known to disagree with the logs, say so in `limits`.
"""
import math
import threading
from functools import lru_cache
import numpy as np
from . import world as W
from ..physics import core as pcore, undulator as pund, lens as plens

SECTIONS = [
    ("overview", "How the simulator works", "State, hidden truth, clock and scenarios: what is common to every model below."),
    ("source", "Source: ring and undulator", "From the electron beam to the white-beam energy spectrum and its position."),
    ("beam", "Beam definition and ray optics", "Angular distribution, slits, lenses and the linear ray map that links them."),
    ("mono", "Monochromator and energy calibration", "HEM Si(111) Laue mono, the true energy, and the foil K-edge calibration."),
    ("flux", "Flux chain", "Attenuators, ion chambers, shutters."),
    ("image", "Tomo camera and image formation", "What the scintillator camera shows for a given beam, slits and pin."),
    ("stage", "Sample stage and alignment pin", "Rotation axis kinematics and the pin the alignment procedure looks at."),
    ("ops", "Operator procedures and scoring", "The scans an operator runs, executed against the same physics."),
]

MODELS = [
    # ------------------------------------------------------------------------------------------------------------------------------ overview
    dict(id="state", section="overview", title="State, hidden truth and seeds", status="assumed",
         summary="The simulator keeps the settings an operator can see (controls) separate from a hidden truth that the operator has to find by scanning, as at the beamline. "
                 "Everything is a plain JSON state, so a session can be saved, shared with the GUI and replayed from a seed.",
         equations=["truth ~ N(0, sigma_k) per seed for: steering error, slit zeros, camera-stage zeros, undulator gap error, Th1/Th2 error, lens tilt optima, camera focus, pin offsets",
                    "Th1 drift ~ N(0, 0.15 mdeg/h) ; steering drift ~ N(0, 0.3 urad/h)"],
         how=["Controls (und.gap, hem.energy, hem.th1_offset, slit sizes/centres, lens x/y/th/phi, tomo stage x/y, samE.*, attenuator and foil positions, shutters, camera exposure/focus) are validated against limits on every move.",
              "The hidden truth is drawn once per seed from the spreads in truth_scales; it is never exposed unless 'show answers' is ticked.",
              "Scenarios: startup (everything misaligned, beam already on gh1), camera_in_beam, ready_for_pin (beam + flux good, pin in view), aligned (truth follows settings)."],
         params=[("steering error", "truth_scales.steer_err_urad", "urad"), ("undulator gap error", "truth_scales.gap_err_mm", "mm"), ("Th1 error", "truth_scales.th1_err_mdeg", "mdeg"),
                 ("Th2 error", "truth_scales.th2_err_deg", "deg"), ("camera stage zero", "truth_scales.camera_zero_mm", "mm"), ("camera focus error", "truth_scales.focus_err_mm", "mm"),
                 ("lens tilt error", "lenses.truth_tilt_error_deg", "deg"), ("slit zero spread (WB)", "slits.truth_zero_spread_mm.wbSlits", "mm"), ("slit zero spread (others)", "slits.truth_zero_spread_mm.default", "mm")],
         code=["blade/vbl/world.py: VirtualBeamline._new_state, _make_aligned"], evidence=["tests/test_vbl_physics.py", "physics/fits/mono.md (Th1 spread), fits/source.md (gap spread)"],
         limits=["Spreads for slit zeros, camera zeros, focus and lens zeros are assumed; the Th1 and gap spreads come from logged calibrations."]),
    dict(id="clock", section="overview", title="Virtual clock, drift and move time", status="assumed",
         summary="Every move advances a virtual clock by an assumed duration; the clock drives the mono thermal state, Th1 drift and steering drift.",
         equations=["dt = 1 s + |move|/2 mm/s (tomo and sample stages)  |  + |move|/30 deg/s (rotations, lens tilts)  |  + 0.2 s (other controls), capped at 600 s",
                    "thermal shift relaxes: s <- s + (target - s)(1 - exp(-dt/tau))"],
         how=["Scans therefore take simulated time, and a retune after a long wait sees the drifted state."],
         params=[("thermal relaxation time", "hem.thermal.tau_s", "s")], code=["blade/vbl/world.py: advance, set"], evidence=["tests/test_vbl_physics.py"],
         limits=["tau is assumed: the logs contain no relaxation time series. Move speeds are round numbers, not motor data."]),
    # ------------------------------------------------------------------------------------------------------------------------------ source
    dict(id="ring", section="source", title="Ring current", status="assumed",
         summary="Flux scales linearly with the stored current relative to the reference current.",
         equations=["flux ~ I / I_ref"], how=["The ring.current control (mA) rescales the source flux and the thermal load."],
         params=[("reference current", "source.ring_current_mA", "mA")], code=["blade/vbl/world.py: ring_scale"], evidence=["fits/source.md (standard top-up current 200.08 +- 0.22 mA)"],
         limits=["Linearity is not tested against a logged decay series. No top-up or decay dynamics."]),
    dict(id="und_energy", section="source", title="Undulator gap to harmonic energy", status="fitted",
         summary="The permanent-magnet undulator radiates harmonics whose energy falls as the gap closes. The field-versus-gap law and the period were refitted on 88 logged (gap, harmonic, energy) rows.",
         equations=["E_n(g) = n * 0.9496 * E_ring^2 / ( lambda_u[cm] * (1 + K^2/2) )   [keV, GeV]",
                    "K = 0.0934 * B0[T] * lambda_u[mm] ;  B0 = a * exp( b g/lambda_u + c (g/lambda_u)^2 )"],
         how=["True gap = set gap + hysteresis step - hidden gap error.", "Gap limits and the odd harmonics available are in the parameters below; the operators use the highest harmonic whose gap is at or above the limit."],
         params=[("period", "undulator.period_mm", "mm"), ("(a, b, c)", "undulator.k_coef", ""), ("gap limits", "undulator.gap_limits_mm", "mm"), ("harmonics", "undulator.flux_model.harmonics", ""), ("hysteresis step", "undulator.hysteresis_mm", "mm"), ("gap wander", "undulator.gap_wander_mm", "mm")],
         curve="und_energy", code=["blade/physics/undulator.py: k_from_gap, harmonic_energy_keV, gap_for_energy_mm", "blade/vbl/world.py: harmonic_peaks, gap_actual, und_coef"],
         evidence=["tests/test_vbl_vs_logs.py: 13 logged peak gaps, rms 7 um; harmonic choice 13/13", "tests/test_fit_source.py", "physics/fits/source.md"],
         limits=["Valid only for gaps 8.5-11.3 mm (where the logged points lie); c is unconstrained and fixed at 0.", "Ring energy 6.0 GeV is assumed (APS-U), not fitted.", "The earlier superconducting undulator (2022-23) is not modelled."]),
    dict(id="und_flux", section="source", title="Undulator flux, peak width and harmonic choice", status="mixed",
         summary="The beam energy the mono selects sees a sum of narrow harmonic peaks. Each peak's height is the Kim flux factor of that harmonic at its own gap, raised to a fitted exponent; the width is a fixed relative bandwidth.",
         equations=["flux(E) = sum_n A_n(g) * exp( -(E_n - E)^2 / (2 w_n^2) ) ,  w_n = rel_fwhm * E_n / 2.3548",
                    "A_n(g) = Q_n(K)^p * norm   (Q_n = Bessel-function factor of the central cone)",
                    "reference IC level is normalised by the best reachable harmonic, so a well-tuned chain reads the same at every energy before the flux-vs-energy factor"],
         how=["Gap scans therefore show a peak ~1 % wide in energy; operators open the gap first, then scan closing (hysteresis).", "optimal_gap(E) picks the harmonic with the largest amplitude above the gap limit."],
         params=[("exponent p", "undulator.flux_model.exponent", ""), ("relative FWHM", "undulator.rel_fwhm", "")],
         curve="und_peak", code=["blade/vbl/world.py: id_flux, harm_amp, optimal_gap, best_amp", "blade/physics/undulator.py: harmonic_flux_factor, harmonic_amplitude"],
         evidence=["tests/test_vbl_vs_logs.py: 7th/5th flux ratio 3.08 at 61.3 keV (logged 2.95-3.2)", "physics/fits/source.md"],
         limits=["The exponent rests on ONE logged 5th/7th ratio; the peak width on one logged number (0.07-0.1 mm in gap at n=7).", "Relative width is the same for every harmonic (physics says ~1/(nN))."]),
    dict(id="steer", section="source", title="Beam steering and beam centre", status="mixed",
         summary="The beam leaves the source at an angle (hidden error + the operator's steering + a gap-dependent term + drift). Its centre at any distance is angle times distance.",
         equations=["theta = ( truth_err + steer + k_gap (gap - 10 mm) + drift t ) * 1e-6   [rad]", "u(z) = theta_x z ,  v(z) = theta_y z  (v gets half the gap term)"],
         how=["1 urad moves the beam 0.07 mm at 71.6 m. The white-beam slit centre that maximises flux follows the beam, so slit zeros and the rotation axis follow it too."],
         params=[("steering per gap", "undulator.steering_per_gap_urad_per_mm", "urad/mm"), ("lever at E (1 urad)", "source.steering_urad_to_mm_at_E", "")],
         code=["blade/vbl/world.py: steer_rad, beam_centre"], evidence=["physics/fits/source.md (lever ~25 m from two points)", "tests/test_vbl_physics.py"],
         limits=["The gap-to-steering coupling (3 urad/mm) is assumed; the logs only give session-to-session scatter."]),
    dict(id="src_size", section="source", title="Source size and divergence", status="assumed",
         summary="Finite source size sets the geometric penumbra of every slit edge and the size of the focused spot.",
         equations=["source sigma = FWHM / 2.3548 (h, v)"], how=["Used in the ray map as the second input variable s, next to the emission angle theta."],
         params=[("source FWHM (h, v)", "source.size_um_fwhm", "um")], code=["blade/vbl/imaging.py: axis_profile"], evidence=["physics/fits/optics.md (only an upper bound can be derived)"],
         limits=["Not derivable from the logs: the logged focused spots are lens- or slit-limited. 30 x 20 um is an upper bound. Brightness-mode source is not separate."]),
    # ------------------------------------------------------------------------------------------------------------------------------ beam
    dict(id="angle", section="beam", title="Beam angular distribution and white-beam slit flux", status="fitted",
         summary="The beam is a Gaussian in emission angle. The fraction of flux that gets through a set of apertures is the Gaussian integral over the angle interval they allow, per axis.",
         equations=["sigma_theta = sigma_WB / z_WB", "fraction(axis) = Phi( (theta_hi - theta_0)/sigma_theta ) - Phi( (theta_lo - theta_0)/sigma_theta )", "flux(z) = source * fraction_h * fraction_v * transmission(foil, attenuators) * shutters"],
         how=["Opening the white-beam slits from 0.3 to 0.5 mm raises the first IC by 1.72, not by the area ratio 2.78, because the beam is not flat across the aperture."],
         params=[("beam sigma at WB slits", "source.beam_sigma_at_wb_mm", "mm"), ("WB slit distance", "z_m.wbSlits", "m")],
         code=["blade/vbl/world.py: sigma_theta, angle_fraction, flux_at"], evidence=["tests/test_vbl_vs_logs.py (IC_B1 176 kHz, x1.72 flux ratio)", "tests/test_fit_flux.py", "physics/fits/flux.md"],
         limits=["H and V sigma are not separable from the logs (isotropic). Heat-load flux loss is not visible up to 0.8 x 0.7 mm."]),
    dict(id="ray", section="beam", title="Linear ray optics (one mechanism for slits, lenses and focus)", status="textbook",
         summary="Each ray is described by its emission angle theta and source point s. Between elements it drifts; at a lens its angle changes; at a slit it is kept or blocked. One map gives slit cutoffs, penumbra, magnification and focus.",
         equations=["u(z) = A theta + E s + B   (per axis, mm and rad)", "drift dz:  A += dz C ,  E += dz F ,  B += dz D", "thin lens f at centre c:  C -= A/f ,  F -= E/f ,  D -= (B - c)/f", "slit [lo, hi]: allowed theta in [ (lo - B)/A , (hi - B)/A ] ; an aperture at a focus (A = 0) passes iff lo <= B <= hi"],
         how=["Apertures include the white-beam slits, B/C/E Kohzu slits, fast shutters and the clear window of every lens stack that is in the beam.", "Slit edges are the opening (centre +/- size/2) plus a hidden zero offset; horizontal motion uses a sign convention recorded in the twin."],
         params=[("slit distances (WB, E us)", "z_m.wbSlits", "m"), ("hsign (slit centre sign)", "slits.hsign", ""), ("lens clear aperture", "lenses.aperture_mm", "mm")],
         code=["blade/vbl/world.py: trace, slit_edges, lens_geom"], evidence=["tests/test_vbl_physics.py", "physics/fits/optics.md (penumbra formula identical on all 8 apertures)"],
         limits=["Distances other than the lens stacks and the E sample are interpolated along the panel order (z_m._note) - not surveyed.", "Second-order optics (aberrations, figure error) are not included."]),
    dict(id="lens", section="beam", title="Tilted saw-tooth lens stacks", status="textbook",
         summary="The lens stacks are prism arrays; a small tilt sets the focal length. Because delta scales as 1/E^2, the focus moves when the energy changes.",
         equations=["f = h sin(tilt) / delta(E) ,  delta ~ 1/E^2 (Si)", "tilt = motor - zero - hidden optimum error", "1/f = 1/p + 1/q   (p source-to-lens, q lens-to-focus)"],
         how=["Whether a stack acts on the beam depends on its window overlapping the beam within +/-4 sigma in both directions (parked stacks do nothing).", "The tilt motor decides which axis focuses; the tilt sign convention follows the beamline's calculator."],
         params=[("tilt optimum error (hidden)", "lenses.truth_tilt_error_deg", "deg"), ("clear aperture", "lenses.aperture_mm", "mm"), ("parked x", "lenses.x_out_mm", "mm")],
         curve="lens", code=["blade/physics/lens.py: prism_focal_length_m, prism_focus_position_m", "blade/vbl/world.py: lens_geom"],
         evidence=["tests/test_physics.py (the beamline's four predicted tilts reproduced)", "tests/test_fit_optics.py"],
         limits=["Fits to the logs (physics/fits/optics.md) put the E focus plane at 69.49 m and give f = h sin(tilt)/(2.11 delta), 15 mm of focus per mdeg: the simulator still uses the beamline's own formula and the interpolated distances. Not adopted yet."]),
    # ------------------------------------------------------------------------------------------------------------------------------ mono
    dict(id="hem", section="mono", title="HEM Si(111) monochromator: angles and true energy", status="validated",
         summary="The mono angle is set from the requested energy plus an offset; the energy that really leaves is set by the true offset, which differs from the one the operator entered by a hidden error.",
         equations=["Th1 = 1.0001973 theta_B(E) + offset ,  Th2 = 1.00001 theta_B(E) + offset2 ,  theta_B = asin( hc / (2 d E) ) ,  d(Si 111) = 3.1356 A   (fit to the printed calc record: 2.5e-7 deg rms)", "Z2 = 33.3417 / tan(2 theta_B) - 7.4407 mm   (0.3 um rms over 51.9-100 keV; the old constant-exit form missed by up to 3.5 mm) ;  Chi2 = quartic in (E - 70 keV)", "E_actual = E(theta_motor - true offset - (s-1) theta_B(71.676)) + k_c dE/dTh2 * Th2_error", "dE/dTh1 = -45 eV per mdeg at 71.7 keV ;  dZ2/dE = 8.44 mm/keV"],
         how=["The true offset = nominal + hidden error + slow drift; the operator fixes the energy error by calibrating on a foil edge (below).", "A Th2 detuning drags the energy readout by about 0.3 x the Th1 sensitivity."],
         params=[("Th1 offset", "hem.th1_offset_deg", "deg"), ("Th2 offset", "hem.th2_offset_deg", "deg"), ("Th2-energy coupling", "hem.th2_energy_coupling", ""), ("energy range", "hem.energy_range_keV", "keV")],
         code=["blade/physics/core.py: bragg_angle_deg, hem_th1_deg, hem_th2_deg, hem_chi2_deg, hem_z2_mm, energy_shift_from_angle_keV", "blade/vbl/world.py: energy_actual_keV, th1_true_offset"],
         evidence=["tests/test_fit_facts_hem.py (Th1/Th2/Z2/Chi2 against 38 transcribed calc-record screenshots)", "tests/test_physics.py (Th1 offset, -45 eV/mdeg)", "tests/test_fit_mono.py", "physics/fits/mono.md, physics/12_panel_facts.md"],
         limits=["After the July 2026 re-reference of the Th zero only one energy (71.676 keV) is logged, so Th numbers after that date are not modelled separately.", "Si(111) Laue bandwidth is not modelled separately from the edge width.", "The Th1 angle scale (+1.97e-4) leaves a ~3 eV energy-dependent systematic after calibration at 71.7 keV; operators' foil-edge offsets (mono.md) were fitted with scale 1 and not refitted."]),
    dict(id="th2", section="mono", title="Second-crystal rocking curve and thermal detuning", status="assumed",
         summary="Flux through the mono is a Gaussian in the Th2 detuning; the heat load of the white beam shifts the Th2 optimum, which relaxes with a time constant.",
         equations=["flux factor = exp( -1/2 (dTh2 / w)^2 ) ,  w = FWHM / 2.3548", "thermal target = shift_per_kW * power_per_mm2 * (WB h x v) * (I / I_ref)"],
         how=["After a beam dump or an aperture change the optimum drifts and the operator re-tweaks Th2 in steps of 0.0002 deg."],
         params=[("rocking FWHM", "hem.th2_rocking_fwhm_deg", "deg"), ("thermal shift", "hem.thermal.th2_shift_deg_per_kW", "deg/kW"), ("power density", "hem.thermal.power_kW_per_mm2", "kW/mm2")],
         curve="th2", code=["blade/vbl/world.py: th2_factor, th2_error_deg, _thermal_target"], evidence=["physics/fits/mono.md (the logs bound the FWHM to 0.6-6 mdeg; Darwin prior 0.31 mdeg)"],
         limits=["No Th2 rocking scan exists in the logs: the width is a chosen value inside the allowed range.", "The thermal shift is derived from the logged ~7 eV dump shifts; the simulated flux loss after a dump is still larger than the logged 3-7 %."]),
    dict(id="foil", section="mono", title="Foil K edge, mu*t and energy calibration", status="fitted",
         summary="A calibration foil in hutch B has a K edge at a tabulated energy. The measured mu*t steps up across it by a logged amount b, and the edge position tells the operator the real energy.",
         equations=["mu_t(E) = ln( I_before / I_after ) = dif + b (1 + erf( (E - pos)/wid )) / 2   (the beamline's E_scan form)", "foil thickness t = b / [mu(E_edge + 0.3 keV) - mu(E_edge - 0.3 keV)]   (mu from xraydb)", "edge width: wid(E) = E * dtheta / tan(theta_B) ,  dtheta = 22.8 urad"],
         how=["The foil transmission at the mono energy is smoothed by the edge width (erf) so a scan across the edge gives the logged shape.", "Calibrating = adjust the Th1 offset until mu*t equals b at the readout energy (45 eV per mdeg at 71.7 keV)."],
         params=[("edge width", "hem.edge_wid_rad", "rad"), ("step b per foil", "foils.b", ""), ("foil list", "foils.elements", ""), ("default ut", "foils.ut_default", "")],
         curve="foil", code=["blade/vbl/world.py: _foil_T_smooth, foil_thickness_mm, edge_wid_keV, mu_t, calibrate_energy_model", "blade/vbl/procedures.py: edge_scan, calibrate_energy"],
         evidence=["tests/test_vbl_vs_logs.py (width on 7 logged fits, mu*t slope)", "tests/test_fit_mono.py", "physics/fits/mono.md"],
         limits=["Natural K-edge width and instrumental width are not separable in the data, so wid is one number.", "mu*t in the simulator uses ion-chamber counts, so noise and the attenuator wheel enter as in Emon."]),
    # ------------------------------------------------------------------------------------------------------------------------------ flux
    dict(id="atten", section="flux", title="Attenuators", status="fitted",
         summary="Two attenuator wheels (hutches B and C) put Beer-Lambert absorbers in the beam. Position tables are the logged thicknesses; transmission uses tabulated absorption.",
         equations=["T = exp( -mu(material, E) * t )   with mu from xraydb", "an entry is mm of Cu, or [material, mm] (Pb positions exist on wheel B)"],
         how=["Wheel B sits between two chambers used for mu*t: Emon divides its transmission back out, as the operators' calc record does."],
         params=[("wheel B table", "foils.attenB_cu_mm", "mm"), ("wheel C table", "foils.attenC_cu_mm", "mm")],
         curve="atten", code=["blade/vbl/world.py: _atten_T, transmission_to", "blade/physics/core.py: transmission"], evidence=["tests/test_vbl_physics.py", "physics/fits/flux.md (tables from the macro help; Pb foil check)"],
         limits=["Only one logged transmission point per wheel (x1.031 thickness on one position, not applied).", "Positions 5-7 of wheel B are Pb; their calibration is from the macro text, not a measurement."]),
    dict(id="ic", section="flux", title="Ion chambers", status="mixed",
         summary="An ion-chamber reading is the flux at its position, scaled so the first chamber reads the logged reference in the reference state, times a flux-vs-energy factor, plus a dark floor and noise.",
         equations=["rate = ref * flux(z) / flux_ref * f(E) + dark_ic ,  clipped at max", "noise: relative N(0, 0.4 %) on the signal, N(0, 5 %) on the dark"],
         how=["f(E) is interpolated from fitted knots of the tuned-chain flux relative to 71.7 keV; with steering re-tuned the simulator reproduces them to 3 %."],
         params=[("reference (icB1)", "ic.ref_kHz_at_icB1", "kHz"), ("dark floor (default)", "ic.dark_kHz", "kHz"), ("dark floors per IC", "ic.dark_kHz_by_ic", "kHz"), ("clip", "ic.max_kHz", "kHz"), ("flux-vs-energy knots", "ic.flux_vs_energy_knots", "[keV, rel]")],
         curve="flux_energy", code=["blade/vbl/world.py: ic_kHz, flux_energy_factor, ref_flux"], evidence=["tests/test_vbl_vs_logs.py", "tests/test_fit_flux.py", "physics/fits/flux.md"],
         limits=["Preamp gain is NOT modelled (the logs give rate ~ gain^-0.955; the simulator treats every gain as 1).", "Gas, length and absolute flux calibration are not identifiable from the logs.", "Knot uncertainty 10-25 %; session-to-session scatter 20-30 %."]),
    dict(id="shutter", section="flux", title="Shutters and fast shutters", status="mixed",
         summary="Closed shutters block everything downstream; each fast shutter is also a rectangular aperture whose centre has a hidden zero.",
         equations=["flux(z) = 0 if a shutter upstream of z is closed ; fast shutter = aperture 3.0 mm (h) x 1.69 mm (v)"],
         how=["Aligning a fast shutter means finding the centre from the ion-chamber plateau."],
         params=[("fast shutter B", "fast_shutters.fsB", "mm"), ("fast shutter E", "fast_shutters.fsE", "mm"), ("hidden zero", "truth_scales.fs_zero_mm", "mm")],
         code=["blade/vbl/world.py: beam_open", "blade/vbl/procedures.py: align_fast_shutter"], evidence=["physics/fits/flux.md"],
         limits=["Leakage (~8e-5 of the open beam) and opening/closing timing are not modelled; there are no millisecond numbers in the logs."]),
    # ------------------------------------------------------------------------------------------------------------------------------ image
    dict(id="cam_geom", section="image", title="Camera geometry, pixel size and focus", status="validated",
         summary="Each tomo camera sits on a stage at a known distance; its pixel size is the sensor pitch divided by the objective magnification. Defocus blurs the image.",
         equations=["pixel = sensor pitch / magnification (gh1 0.69 um, pg1/pg5 1.172 um)", "blur sigma = sqrt( psf^2 + (70 um * |focus error| / pixel)^2 )   [px]"],
         how=["The beam centre on the sensor is stage position + a hidden stage zero; moving the stage within its limits scans the field of view across the beam."],
         params=[("gh1 psf", "cameras.gh1.psf_px", "px"), ("pg1 psf", "cameras.pg1.psf_px", "px"), ("gh1 sensor", "cameras.gh1.cols", "cols"), ("focus error (hidden)", "truth_scales.focus_err_mm", "mm"),
                 ("tomoE stage x limits", "tomo_stages.tomoE.x_limits_mm", "mm"), ("tomoC stage x limits", "tomo_stages.tomoC.x_limits_mm", "mm"), ("stage sign (x)", "tomo_stages.xsign", "")],
         curve="blur", code=["blade/vbl/world.py: camera_view, camera_focus_error_mm", "blade/vbl/imaging.py: render"], evidence=["tests/test_physics.py (pixel sizes exact)", "tests/test_fit_camera.py"],
         limits=["The 70 um/mm defocus coefficient and the base PSF are assumed (no knife-edge PSF measurement)."]),
    dict(id="img_form", section="image", title="Image formation and noise", status="mixed",
         summary="A frame is the product of the beam profile, every aperture's projected edge, the beam texture and the pin, blurred by the camera, times the scintillator dust map, plus noise.",
         equations=["counts = bg + exposure * gain * [ profile_h x profile_v x texture x pin ] (*) PSF  x dust + hot pixels", "profile per axis = Gaussian(angle, source) x prod over apertures of a projected box (shifted, blurred, Fresnel-rippled)", "noise: N(0, sqrt(0.6 (N - bg) + 40)) + N(0, 6)   (shot-like + read)"],
         how=["A slit far upstream gives a wide soft edge; one right in front of the camera gives a crisp one, as in the logbook images.", "Brightness is scaled so the reference beam gives 'full' counts at 0.1 s."],
         params=[("background (gh1)", "cameras.gh1.bg", "counts"), ("full scale (gh1)", "cameras.gh1.full", "counts"), ("full scale (pg1)", "cameras.pg1.full", "counts")],
         code=["blade/vbl/imaging.py: render, axis_profile"], evidence=["tests/test_vbl_render.py"],
         limits=["The noise law is a plausible structure, not a photon-transfer fit (the KB images are 8-bit screenshots).", "Scintillator absorption versus energy (LuAG K edge at 63.3 keV) is not modelled: counts do not change with energy beyond the flux."]),
    dict(id="edges", section="image", title="Slit penumbra and Fresnel edge diffraction", status="validated",
         summary="Each aperture edge lands on the camera plane shifted and blurred by the geometric penumbra of the finite source, with Fresnel ripple on top.",
         equations=["penumbra sigma = | E_cam - A_cam E_i / A_i | * sigma_source", "Fresnel knife-edge pair: I = 1/2 [ (C_b - C_a)^2 + (S_b - S_a)^2 ] ,  scale = (z_i/z_cam) sqrt( 2 / (lambda L_eff) ) ,  L_eff = z_i (z_cam - z_i)/z_cam", "visibility damped by partial coherence: vis = max(0.45, exp(-1/2 (pen / (fresnel scale / 2))^2))"],
         how=["The innermost edge on each side of the beam centre defines the visible footprint; its penumbra width is reported with the frame."],
         params=[("source FWHM (h, v)", "source.size_um_fwhm", "um")], code=["blade/vbl/imaging.py: _box_fresnel, axis_profile"], evidence=["physics/fits/optics.md (penumbra formula matches)", "tests/test_vbl_render.py"],
         limits=["The ripple damping is empirical (the logs show 1-2 rim lines). Logged 10-90 % edge widths (38 um on PG, 19 um on GH1) are not yet compared with simulated edges."]),
    dict(id="texture", section="image", title="Beam texture, window faults and camera dust", status="assumed",
         summary="The beam picks up structure from the windows it crosses (moves with the beam); the camera adds fixed dust and vignetting (moves with the camera). Both are seeded, so a seed always looks the same.",
         equations=["texture = (1 + blobs)(1 + mottle)(1 + speckle)(1 + vertical streaks)(1 + large modulation) x window faults x hot core", "camera map = (1 - 0.12 r^2) x dust blobs ; plus hot pixels"],
         how=["The hot irregular core sits on the beam axis; apertures only clip it."],
         params=[("texture strength gh1", "cameras.gh1.texture", ""), ("texture strength pg1", "cameras.pg1.texture", ""), ("texture strength pg5", "cameras.pg5.texture", ""), ("hot-core strength gh1", "cameras.gh1.core", ""), ("dust gh1", "cameras.gh1.dust", "")],
         code=["blade/vbl/imaging.py: beam_texture, _defect_field, camera_maps"], evidence=["physics/fits/camera.md"],
         limits=["Measured on the logged frames (correlation length ~26-32 um, relative rms 0.08-0.11, dust ~4 um spots), the simulated texture is about 2x too long, 3x too strong and its dust spots 3x too large. Not recalibrated yet."]),
    # ------------------------------------------------------------------------------------------------------------------------------ stage
    dict(id="axis", section="stage", title="Rotation axis and sample-stage kinematics", status="validated",
         summary="The sample is on a rotation stage; the pin's apparent position follows a sinusoid in the rotation angle, and the stage motors move it linearly.",
         equations=["x(omega) = c + a cos(omega) + b sin(omega)   (BLADE convention)", "a = a0 + k_x (samE.x - x_ref) ;  b = b0 + k_z (samE.z - z_ref) + L tan(tilt_rx + samE.rx)", "c = axis position + k_base (samE.aerox - aerox_ref)"],
         how=["Aligning the rotation axis onto the beam means making c equal the beam centre; the wedge and tilt show up as drift of the pin top with rotation."],
         params=[("column per x", "stage_E.col_per_x", ""), ("k_z", "stage_E.k_z", ""), ("column per base", "stage_E.col_per_base", ""), ("rotation sign", "stage_E.rot_sign", ""), ("x_ref", "stage_E.x_ref_mm", "mm"), ("pin_z_ref", "stage_E.pin_z_ref_mm", "mm")],
         code=["blade/vbl/world.py: pin_state"], evidence=["hardware test 2026-10-28 (signs, links, corrections)", "tests/test_vbl_physics.py"],
         limits=["Signs and couplings are the hardware-confirmed ones of the profile; hidden truth values come from the one set of test frames used when BLADE was built."]),
    dict(id="pin", section="stage", title="Alignment pin shadow", status="assumed",
         summary="The pin is a dark truncated cone seen against the beam: its top width, taper and transmission set what the detector sees, magnified by the ray map, with Fresnel ripple at its edges.",
         equations=["half-width(row) = top_width/2 + (row - top) tan(half angle)", "transmission inside = T ; magnified by M = A_cam / A_pin ; Fresnel edge ripple damped by 0.55", "half-transparent flank at |omega| ~ 90 deg"],
         how=["The pin appears only for cameras in hutch E downstream of the sample."],
         params=[("top width", "stage_E.pin.top_width_um", "um"), ("half angle", "stage_E.pin.half_angle_deg", "deg"), ("transmission", "stage_E.pin.transmission", ""), ("length", "stage_E.pin.length_mm", "mm")],
         code=["blade/vbl/imaging.py: _pin_shadow"], evidence=["tests/test_vbl_render.py", "physics/fits/camera.md"],
         limits=["The logged pins fall in two families (7.8 deg half angle / 105 um top, and 14.8 deg / 135-220 um); the simulator mixes them (104.5 um with 15 deg). Tungsten K edge at 69.5 keV changes the transmission (0.12 at 71.7 keV measured-model vs 0.08 here). Held back deliberately until the pin work."]),
    # ------------------------------------------------------------------------------------------------------------------------------ ops
    dict(id="procs", section="ops", title="Operator procedures run on the physics", status="validated",
         summary="Every scan an operator runs at the start of a beamtime is implemented against the same model, using only observables (ion-chamber counts, camera frames).",
         equations=["gap scan, Th2 scan: scan -> fit a Gaussian peak -> apply", "E_scan / calibrate: erf fit of mu*t -> Th1 offset -> repeat until mu*t = b", "slit alignment: close, find edge centres, step open; lens scan: tilt vs spot size"],
         how=["Procedures: open gap, nominal gap, gap scan, Th2 scan, select edge, E scan, calibrate energy, tune exposure, find beam on camera, centre camera, steering check, align slit, slit IC scan, align fast shutter, focus camera, lens scan, startup sequence.",
              "readiness() scores the final state against the hidden truth (for tests and agent evaluation only)."],
         params=[], code=["blade/vbl/procedures.py", "blade/vbl/tools.py (23 MCP tools)"], evidence=["startup sequence converges from random truths (gap error ~4 um, Th2 ~0, flux 0.997 of the best)", "tests/test_vbl_physics.py"],
         limits=["The pin alignment procedure (blade align) runs on this simulator but is being reworked; test_vbl currently stops at align_adaptive."]),
]

NOT_MODELLED = [
    ("Ion-chamber preamp gain, gas and length", "rate ~ gain^-0.955 is fitted but needs a per-IC gain control; absolute flux and gas energy response are not identifiable yet.", "fits/flux.md"),
    ("Thermal relaxation time and the real Th2 rocking curve", "needs repeated Emon after a dump and one Th2 scan; the simulator uses assumed values.", "fits/mono.md"),
    ("Source size and divergence, brightness mode", "needs spot size versus slit size at fixed lens position, plus emittance from the accelerator group.", "fits/source.md, fits/optics.md"),
    ("Refitted lens geometry (E focus plane 69.49 m)", "a code change in the lens model and surveyed distances; not a number in sim.json.", "fits/optics.md"),
    ("Surveyed distances", "everything except the lens stacks and the E sample is interpolated along the panel order.", "physics/08_open_questions.md"),
    ("Camera photon transfer, scintillator PSF and counts versus energy", "needs raw 16-bit frames; the knowledge-base images are 8-bit screenshots.", "fits/camera.md"),
    ("Motor mechanics", "limits, velocities, backlash, soft-limit trips, stuck slit blades; the 873 legible panel screenshots would supply them once transcribed.", "physics/11_model_inventory_and_gaps.md"),
    ("Ring decay and top-up, beam dumps as events", "no time series in the logs; the clock only drifts Th1 and steering.", "physics/11_model_inventory_and_gaps.md"),
    ("Fast-shutter leakage and timing, Kohzu-slit transmission", "no logged series.", "fits/flux.md"),
    ("Sample interaction and reconstruction", "absorption and phase contrast of real samples, sinogram and axis check in reconstructed slices; far-field/powder detector signals.", "physics/11_model_inventory_and_gaps.md"),
    ("Failure-mode library", "stuck blade, lens support in the beam, preamp off, unzeroed mu*t record: the pitfalls are extracted in the procedure KB but not injectable yet.", "knowledge_base/README.md"),
]

TESTS = ["tests/test_vbl_physics.py", "tests/test_vbl_render.py", "tests/test_vbl_vs_logs.py", "tests/test_physics.py", "tests/test_fit_source.py", "tests/test_fit_mono.py",
         "tests/test_fit_flux.py", "tests/test_fit_optics.py", "tests/test_fit_camera.py"]


# ---------------------------------------------------------------------------------------------------------------------------------- live values
def _get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None, False
        d = d[k]
    return d, True


def _src(sim, path):
    """Provenance note stored next to a value: <key>_src beside it, else `src` / `_src` in the parent, else the parent's `_note`."""
    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        parent, ok = _get(sim, ".".join(parts[:i - 1])) if i > 1 else (sim, True)
        if not ok or not isinstance(parent, dict):
            continue
        key = parts[i - 1]
        for cand in (key + "_src", "src", "_src"):
            if isinstance(parent.get(cand), str):
                return parent[cand]
    return None


def payload(twin=W.TWIN):
    sim = W.load_sim(twin)
    models = []
    for m in MODELS:
        e = {k: v for k, v in m.items() if k != "params"}
        e["params"] = []
        for label, path, unit in m["params"]:
            v, ok = _get(sim, path)
            e["params"].append({"label": label, "path": path, "unit": unit, "value": v if ok else None, "found": ok, "src": _src(sim, path) if ok else None})
        models.append(e)
    return {"twin": twin, "z_m": {k: v for k, v in sim["z_m"].items() if not k.startswith("_")}, "sections": [{"id": a, "title": b, "text": c} for a, b, c in SECTIONS], "models": models,
            "not_modelled": [{"what": a, "why": b, "doc": c} for a, b, c in NOT_MODELLED], "tests": TESTS}


# ---------------------------------------------------------------------------------------------------------------------------------- curves (computed with the real simulator)
@lru_cache(maxsize=1)
def _world():
    return W.VirtualBeamline(seed=0, scenario="aligned")


def _lin(a, b, n):
    return [float(x) for x in np.linspace(a, b, n)]


_LOCK = threading.Lock()


def curve(name):
    """Curve `name` computed by the real simulator. Curves temporarily move controls on ONE shared world and restore them, so requests (the page fires them
    all at once from separate server threads) are serialised."""
    with _LOCK:
        return _curve(name)


def _curve(name):
    w = _world()
    sim = w.sim
    if name == "und_energy":
        u = sim["undulator"]
        g = np.arange(8.5, 11.31, 0.05)
        series = []
        for n in w.harmonics():
            E = [pund.harmonic_energy_keV(float(x), n, u["period_mm"], coef=w.und_coef()) for x in g]
            keep = [i for i, e in enumerate(E) if 30 <= e <= 110]
            if keep:
                series.append({"name": f"n={n}", "x": [float(g[i]) for i in keep], "y": [E[i] for i in keep]})
        return {"title": "Harmonic energy versus gap", "xlabel": "gap [mm]", "ylabel": "photon energy [keV]", "series": series,
                "note": "fitted period and field coefficients; the fit's data lie between 8.5 and 11.3 mm"}
    if name == "und_peak":
        s0 = dict(w.s["ctl"]), w.s["gap_hyst"]
        series = []
        try:
            for E in (52.0, 71.676, 90.526):
                w.s["ctl"]["hem.energy"] = E
                g0 = w.optimal_gap(E)
                xs = np.linspace(g0 - 0.25, g0 + 0.25, 101)
                ys = []
                for g in xs:
                    w.s["ctl"]["und.gap"] = float(g)
                    w.s["gap_hyst"] = 0.0
                    ys.append(w.id_flux())
                m = max(ys)
                series.append({"name": f"{E:g} keV", "x": [float(x - g0) * 1e3 for x in xs], "y": [float(y / m) for y in ys]})
        finally:
            w.s["ctl"].update(s0[0]); w.s["gap_hyst"] = s0[1]
        return {"title": "Flux versus gap around the best gap (a gap scan)", "xlabel": "gap - best gap [um]", "ylabel": "relative flux", "series": series,
                "note": "relative width is the same for every harmonic; the scan peak is ~1 % of E wide"}
    if name == "th2":
        base = w.ctl("hem.th2_offset")
        xs = np.linspace(-6e-3, 6e-3, 121)
        ys = []
        try:
            for d in xs:
                w.s["ctl"]["hem.th2_offset"] = base + float(d)
                ys.append(w.th2_factor())
        finally:
            w.s["ctl"]["hem.th2_offset"] = base
        return {"title": "Second-crystal rocking curve", "xlabel": "Th2 - optimum [mdeg]", "ylabel": "relative flux", "series": [{"name": "rocking", "x": [float(x) * 1e3 for x in xs], "y": [float(y) for y in ys]}],
                "note": "width is assumed inside the 0.6-6 mdeg the logs allow"}
    if name == "foil":
        series = []
        for el in ("Tb", "Re", "Au"):
            e0 = float(pcore.edge_keV(el))
            xs = np.linspace(-0.25, 0.25, 101)
            series.append({"name": el, "x": [float(x) * 1e3 for x in xs], "y": [float(-math.log(w._foil_T_smooth(el, e0 + float(x)))) for x in xs]})
        return {"title": "Foil mu*t across the K edge (edge-scan shape)", "xlabel": "E - tabulated edge [eV]", "ylabel": "mu*t", "series": series,
                "note": "step b per element from the logs; erf width = E * 22.8 urad / tan(theta_B)"}
    if name == "atten":
        series = []
        for key, pos in (("attenB_cu_mm", 1), ("attenB_cu_mm", 2), ("attenB_cu_mm", 3), ("attenB_cu_mm", 5), ("attenC_cu_mm", 1), ("attenC_cu_mm", 3), ("attenC_cu_mm", 7)):
            ent = sim["foils"][key][pos]
            mat, mm = ("Cu", ent) if not isinstance(ent, (list, tuple)) else (ent[0], ent[1])
            Es = _lin(40, 95, 56)
            series.append({"name": f"{'B' if 'B' in key else 'C'}{pos}: {mm:g} mm {mat}", "x": Es, "y": [float(pcore.transmission(mat, mm, E)) for E in Es]})
        return {"title": "Attenuator transmission versus energy", "xlabel": "energy [keV]", "ylabel": "transmission", "ylog": True, "series": series, "note": "Beer-Lambert with xraydb absorption"}
    if name == "flux_energy":
        kn = sim["ic"].get("flux_vs_energy_knots") or []
        Es = _lin(40, 95, 56)
        out = [{"name": "interpolation used", "x": Es, "y": [float(np.interp(E, [k[0] for k in kn], [k[1] for k in kn])) for E in Es]}] if kn else []
        if kn:
            out.append({"name": "fitted knots", "x": [k[0] for k in kn], "y": [k[1] for k in kn], "points": True})
        return {"title": "Tuned-chain ion-chamber flux relative to 71.7 keV", "xlabel": "energy [keV]", "ylabel": "relative flux", "series": out, "note": "knots fitted from logged IC rates (10-25 % uncertainty)"}
    if name == "lens":
        L = plens.LENSES_1ID["lens1E"]
        zl = w.lens_z("lens1E")
        series = []
        for E in (52.0, 71.676, 90.526):
            d = plens.lens_delta(L["material"], E)
            xs = np.linspace(0.04, 0.25, 85)
            ys = []
            for t in xs:
                f = plens.prism_focal_length_m(float(t), d, L["tooth_um"])
                q = 1.0 / (1.0 / f - 1.0 / zl) if abs(1.0 / f - 1.0 / zl) > 1e-9 else 1e9
                ys.append(min(zl + q, 140.0) if q > 0 else 140.0)
            series.append({"name": f"{E:g} keV", "x": [float(x) for x in xs], "y": [float(y) for y in ys]})
        return {"title": f"lens1E focus position versus tilt (lens at {zl:g} m)", "xlabel": "tilt [deg]", "ylabel": "focus distance from source [m]", "series": series,
                "note": "thin-lens, f = h sin(tilt)/delta(E); clipped at 140 m. Fits in physics/fits/optics.md refine this geometry (not adopted)"}
    if name == "blur":
        xs = np.linspace(-1.0, 1.0, 81)
        series = []
        for cam in ("gh1", "pg1"):
            cc = sim["cameras"][cam]
            p_um = w.cams[cam]["pixel_um"]
            series.append({"name": cam, "x": [float(x) for x in xs], "y": [float(math.hypot(cc["psf_px"], 70.0 * abs(x) / p_um)) for x in xs]})
        return {"title": "Image blur versus camera focus error", "xlabel": "focus error [mm]", "ylabel": "blur sigma [px]", "series": series, "note": "defocus coefficient 70 um/mm is assumed"}
    raise ValueError(f"unknown curve '{name}'")
