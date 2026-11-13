"""Virtual-beamline tools for the MCP server (SIMULATION ONLY - nothing here can reach hardware). They let an agent drive the 1-ID twin 'as if at the
beamline': set any control, read ion chambers / mu_t, take tomo-camera frames, run the operator scans, and run the whole start-of-beamtime sequence.
State lives in the shared session (runs/vbl/default.json) that the GUI page /vbl shows live. Read playbooks/virtual_beamline.md first (also the MCP
resource blade://playbook/vbl). Hidden truth is never returned except by vbl_readiness (scoring)."""
import numpy as np
from ..paths import ROOT, RUNS_DIR
from ..registry import tool, playbook
from . import store, procedures as P, imaging
from .world import control_specs, CAMERAS

playbook("vbl", ROOT / "playbooks" / "virtual_beamline.md")


def _w(session):
    return store.require(session)


def _done(w, session, res=None):
    store.save(w, session)
    return res


@tool("vbl", needs_run=False)
def vbl_reset(seed: int = 0, scenario: str = "startup", session: str = "default") -> dict:
    """Start a fresh virtual-beamline session. scenario: 'startup' (everything misaligned: gap, Th2, energy, steering, slits, camera, focus all off; pin lifted out of
    the beam), 'camera_in_beam' (beam on the gh1 camera, flux not yet optimised), 'ready_for_pin' (beam + flux good, pin in view: ready for `blade align`), 'aligned'.
    The seed fixes the hidden truth (and the textures) so a session is reproducible."""
    w = store.reset(seed, scenario, session)
    return {"ok": True, "session": session, "scenario": scenario, "seed": seed, "controls": len(w.s["ctl"]), "cameras": CAMERAS}


@tool("vbl", needs_run=False)
def vbl_status(session: str = "default") -> dict:
    """Operator panel: every control value, HEM readouts (Th1, Z2), all ion-chamber rates (kHz), mu_t (if a foil is in) and the virtual time."""
    w = _w(session)
    return w.snapshot()


@tool("vbl", needs_run=False)
def vbl_list_controls(prefix: str = "") -> dict:
    """List settable controls with limits, units and a description (optionally only names starting with `prefix`, e.g. 'slitEus', 'und', 'hem', 'tomoE', 'samE')."""
    sp = control_specs()
    return {k: {"lo": v[0], "hi": v[1], "unit": v[2], "doc": v[3]} for k, v in sp.items() if k.startswith(prefix)}


@tool("vbl", needs_run=False)
def vbl_set(control: str, value: float | str, session: str = "default") -> dict:
    """Move one control (simulated). Returns the readback. Refused outside the limits. Undulator gap has hysteresis (open to ~9.5 mm first, approach from large gap);
    slit sizes/centres have 1 um resolution; the virtual clock advances (mono thermal state relaxes)."""
    w = _w(session)
    rb = w.set(control, value)
    return _done(w, session, {"control": control, "readback": rb, "time_s": w.s["t_s"]})


@tool("vbl", needs_run=False)
def vbl_set_many(values: dict, session: str = "default") -> dict:
    """Set several controls at once: {name: value, ...}."""
    w = _w(session)
    out = {k: w.set(k, v) for k, v in values.items()}
    return _done(w, session, {"readback": out})


@tool("vbl", needs_run=False)
def vbl_read_ics(session: str = "default") -> dict:
    """Ion-chamber rates in kHz (dark floor ~1 kHz, scaler clips at 1000) and mu_t of the calibration foil if it is in."""
    w = _w(session)
    return _done(w, session, {"ic_kHz": {ic: round(w.ic_kHz(ic), 3) for ic in w.sim["ic"]["ids"]}, "mu_t": w.mu_t(), "time_s": w.s["t_s"]})


@tool("vbl", needs_run=False)
def vbl_get_frame(camera: str = "gh1", exposure: float | None = None, bin: int = 1, save: bool = True, session: str = "default") -> dict:
    """Acquire a tomo-camera frame (gh1, pg1 [hutch E], pg5 [C], retiga2 [B]) and analyse it: beam present, footprint box, hotspot, edge widths (10-90 %, px), saturation.
    Saves a PNG (auto-scaled) under runs/vbl/frames/ and returns its path; the GUI /vbl shows the live view too. Use bin=2/4 for a faster, coarser frame."""
    w = _w(session)
    img = imaging.render(w, camera, exposure=exposure, bin_=bin)
    p_um = w.cams[camera]["pixel_um"] * bin
    out = {"camera": camera, "shape": list(img.shape), "pixel_um": p_um, "analysis": P.analyze_frame(img, p_um)}
    if save:
        d = RUNS_DIR / "vbl" / "frames"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{camera}_{int(w.s['t_s'])}_{w.s['n_acq']}.png"
        f.write_bytes(imaging.png_gray8(imaging.to_u8(img)))
        out["png"] = str(f)
    return _done(w, session, out)


@tool("vbl", needs_run=False)
def vbl_describe_view(camera: str = "gh1", session: str = "default") -> dict:
    """Twin introspection (not a measurement): which aperture defines each side of the footprint on this camera, its edge blur in pixels and the beam size/position;
    explains why an edge is sharp (a slit near the camera) or blurry (a slit far upstream, e.g. the WB slits)."""
    w = _w(session)
    _, info = imaging.render(w, camera, bin_=4, return_info=True)
    return {k: info[k] for k in info if k in ("camera", "state", "h", "v", "edges_h", "edges_v", "blur_sigma_px", "focus_error_mm")}


@tool("vbl", needs_run=False)
def vbl_scan(control: str, start: float, stop: float, n: int = 21, detector: str = "icB1", session: str = "default") -> dict:
    """Generic 1-D scan: step `control` from start to stop in n points and read `detector` = an IC name (icB1, ...), 'mu_t', or 'cam_sum:<camera>' (summed counts, binned).
    Returns the curve and a Gaussian-fit peak; the control is left at the END value (use vbl_set to move it to the peak, e.g. approach a gap from the open side)."""
    w = _w(session)
    xs = np.linspace(start, stop, n)
    ys = []
    for x in xs:
        w.set(control, float(x))
        if detector == "mu_t":
            ys.append(w.mu_t())
        elif detector.startswith("cam_sum:"):
            ys.append(float(imaging.render(w, detector.split(":")[1], bin_=4).astype(np.float64).sum()))
        else:
            ys.append(w.ic_kHz(detector))
    pk, fwhm = P._fit_peak(xs, ys)
    return _done(w, session, {"control": control, "x": xs.tolist(), "y": [round(float(v), 4) for v in ys], "peak": pk, "fwhm": fwhm, "detector": detector})


@tool("vbl", needs_run=False)
def vbl_gap_scan(centre: float, half_range: float = 0.2, n: int = 40, ic: str = "icB1", apply: bool = True, session: str = "default") -> dict:
    """undscangap: scan the gap high -> low about `centre` against an IC at the current mono energy and (apply=True) set the fitted peak (approached from the open side)."""
    w = _w(session)
    return _done(w, session, P.gap_scan(w, centre, half_range, n, ic, apply))


@tool("vbl", needs_run=False)
def vbl_nominal_gap(apply: bool = False, session: str = "default") -> dict:
    """Starting gap for the best harmonic at the current HEM energy (from the fitted ~21.9 mm period; accurate to ~0.05 mm: follow with a gap scan). apply=True also sets und.gap to it."""
    w = _w(session)
    return _done(w, session, P.nominal_gap(w, apply=apply))


@tool("vbl", needs_run=False)
def vbl_select_edge(element: str = "Re", session: str = "default") -> dict:
    """Set the HEM energy to the tabulated K-edge energy of this foil element (Re 71.676, Au 80.725, ... keV): the energy to work at before E scan / gap scan."""
    w = _w(session)
    return _done(w, session, P.select_edge(w, element))


@tool("vbl", needs_run=False)
def vbl_th2_scan(half_range: float = 0.004, n: int = 21, ic: str = "icB1", apply: bool = True, session: str = "default") -> dict:
    """Tweak Th2 across +-half_range deg and set the flux maximum (operators tweak by hand in 0.0002 deg steps; re-peak after every gap/energy/slit/steering change)."""
    w = _w(session)
    return _done(w, session, P.th2_scan(w, half_range, n, ic, apply))


@tool("vbl", needs_run=False)
def vbl_edge_scan(element: str = "Re", half_range_keV: float = 0.12, n: int = 49, apply: bool = False, session: str = "default") -> dict:
    """E_scan: foil in, step the HEM energy across the foil K edge, return mu_t(E), the erf fit (dif, b, pos, wid) and the energy where mu_t = b."""
    w = _w(session)
    return _done(w, session, P.edge_scan(w, element, half_range_keV, n, apply))


@tool("vbl", needs_run=False)
def vbl_calibrate_energy(element: str = "Re", session: str = "default") -> dict:
    """Energy calibration as the operators do it: E_scan fit, then the Th1 offset is adjusted until mu_t = b at the HEM readout energy; checked with mu_t."""
    w = _w(session)
    return _done(w, session, P.calibrate_energy(w, element))


@tool("vbl", needs_run=False)
def vbl_find_beam_on_camera(camera: str = "gh1", half_range_mm: float = 3.0, session: str = "default") -> dict:
    """Bring the tomo camera to the beam: raster the stage about x=0 (the logs zero the stage on the hotspot, so the beam is near 0 +-1 mm) until the beam is seen."""
    w = _w(session)
    return _done(w, session, P.find_beam_on_camera(w, camera, half_range_mm))


@tool("vbl", needs_run=False)
def vbl_auto_exposure(camera: str = "gh1", target: float = 0.35, session: str = "default") -> dict:
    """Set the camera exposure so the brightest part of the beam reaches `target` of full scale (lengthen it to find a dim beam, shorten it if the core saturates)."""
    w = _w(session)
    return _done(w, session, P.tune_exposure(w, camera, target))


@tool("vbl", needs_run=False)
def vbl_centre_camera(camera: str = "gh1", on: str = "footprint", session: str = "default") -> dict:
    """Move the tomo stage so the beam 'footprint' (or the 'hotspot') is at the middle of the frame."""
    w = _w(session)
    return _done(w, session, P.centre_camera_on_beam(w, camera, on))


@tool("vbl", needs_run=False)
def vbl_steering_check(camera: str = "gh1", session: str = "default") -> dict:
    """Hotspot vs the centre of the WB-slit image on the tomo, and the steering change (urad) that would remove the difference. Moves nothing: apply with
    vbl_set steer.xp/steer.yp (partly; re-measure). The footprint must be fully inside the frame."""
    return P.steering_check(_w(session), camera)


@tool("vbl", needs_run=False)
def vbl_align_slit(slit: str, camera: str = "gh1", session: str = "default") -> dict:
    """Kohzu slit alignment as in the logs: close the slit stepwise to 0.1 mm, centre its image on the camera's target pixel (frame centre), reopen. Falls back to an ion-chamber
    centre scan when the closed slit is off the beam by more than the footprint. slit: slitB, slitCus, slitCds, slitEus, slitEds."""
    w = _w(session)
    return _done(w, session, P.align_slit(w, slit, camera))


@tool("vbl", needs_run=False)
def vbl_slit_ic_scan(slit: str, axis: str = "h", ic: str = "", half_range: float = 1.0, n: int = 41, size: float = 0.1, apply: bool = False, session: str = "default") -> dict:
    """Scan a slit's centre (axis 'h' or 'v') with the slit closed to `size` against a downstream ion chamber (default: the nearest IC after it); the peak marks the beam."""
    w = _w(session)
    return _done(w, session, P.slit_ic_scan(w, slit, axis, ic or P._ic_after(w, slit), half_range, n, size, apply))


@tool("vbl", needs_run=False)
def vbl_align_fast_shutter(fs: str, ic: str = "", half_range: float = 2.5, n: int = 51, apply: bool = True, session: str = "default") -> dict:
    """Centre a fast shutter ('fsB' or 'fsE', window 3.0 x 1.7 mm) on the beam: scan its blade centre in H and V against the nearest IC downstream (other slits open) and set
    the middle of the IC plateau. A misaligned shutter clips the beam and shows up on the camera as a sharp cut edge."""
    w = _w(session)
    return _done(w, session, P.align_fast_shutter(w, fs, ic or None, half_range, n, apply))


@tool("vbl", needs_run=False)
def vbl_focus_camera(camera: str = "gh1", half_range_mm: float = 0.4, n: int = 17, session: str = "default") -> dict:
    """Scan the camera objective focus and set the sharpest position (edge-gradient metric)."""
    w = _w(session)
    return _done(w, session, P.focus_camera(w, camera, half_range_mm, n))


@tool("vbl", needs_run=False)
def vbl_lens_scan(lens: str, camera: str = "gh1", half_range_deg: float = 0.05, n: int = 21, session: str = "default") -> dict:
    """Tilt scan of a lens that is in the beam (x near 0): the focused footprint is narrowest at the best tilt; also returns the beamline's predicted tilt (focus_calc)."""
    w = _w(session)
    return _done(w, session, P.lens_scan(w, lens, camera, half_range_deg, n))


@tool("vbl", needs_run=False)
def vbl_startup_sequence(element: str = "Re", camera: str = "gh1", session: str = "default") -> dict:
    """Run the whole start-of-beamtime sequence (energy/flux: gap scan, Th2, foil edge; camera: find, centre, focus; steering; E slits) and return the list of steps.
    Use it as a reference run or to reach a well-aligned state quickly; vbl_readiness then scores it."""
    w = _w(session)
    steps = P.startup_sequence(w, element, camera)
    return _done(w, session, {"steps": [{"step": s["step"]} for s in steps], "time_s": w.s["t_s"]})


@tool("vbl", needs_run=False)
def vbl_readiness(session: str = "default") -> dict:
    """SCORING ONLY (reveals the hidden truth): errors of gap, Th2, energy (mu_t vs b), steering, slit centres, camera, pin/axis versus the truth, with pass flags."""
    return _w(session).truth_report()
