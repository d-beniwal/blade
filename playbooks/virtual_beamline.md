# Virtual beamline playbook (simulation only)

The **virtual beamline** (`blade.vbl`, tools `vbl_*`, page `blade-gui vbl`) is the 1-ID twin turned into a simulator you can drive as if you were at the beamline: energy and flux, slits, the tomo camera, the pin and the rotation axis, with hidden misalignments you find the way the logbooks do. **Nothing here touches EPICS or hardware**; it is safe at any time. Never mix it up with the real run: `new_run(backend='epics')` is the only path to hardware.

## Start
1. `vbl_reset(scenario, seed)`: `startup` = everything misaligned (undulator gap, Th2, energy calibration, steering, slit zeros, camera position and focus; the pin is lifted out of the beam), `camera_in_beam` (beam on gh1, flux not optimised), `ready_for_pin` (beam + flux good, pin in view, for `blade align`), `aligned`. The seed fixes the hidden truth and textures.
2. `vbl_status` shows the operator panel (all controls, ion-chamber rates in kHz, mu_t, virtual time). `vbl_list_controls(prefix)` lists limits. The GUI page shows the same session live.
3. Move things with `vbl_set(control, value)` (refused outside limits). Look with `vbl_get_frame(camera)` (analysis + PNG path) or the GUI.

## The standard sequence (what the logs do; `vbl_startup_sequence` runs it end to end)
| step | tools | what you watch | done when |
|---|---|---|---|
| open downstream slits (3 mm), foil/attenuators out | `vbl_set` | IC counts | beam on the B ICs |
| nominal gap, gap scan (high -> low), set the peak | `vbl_nominal_gap`, `vbl_gap_scan` | icB1 | peak found (FWHM ~0.08 mm) |
| Th2 for flux, gap again | `vbl_th2_scan`, `vbl_gap_scan` | icB1 | icB1 ~ 176 kHz at WB 0.3x0.3, 200 mA |
| energy: foil in, edge scan, Th1 offset until mu_t = b | `vbl_edge_scan`, `vbl_calibrate_energy` | mu_t | mu_t within 0.05 of b (Re b = 1.4) |
| camera to the beam | `vbl_find_beam_on_camera`, `vbl_centre_camera`, `vbl_auto_exposure`, `vbl_focus_camera` | frame | footprint fully in view and sharp |
| steering: hotspot vs the WB-slit image | `vbl_steering_check`, then `vbl_set steer.xp/yp` (apply ~90 %, re-measure) | hotspot - footprint centre | < ~12 px |
| re-peak flux (gap, Th2), re-check energy | as above | icB1, mu_t | back at the reference |
| Kohzu slits on the hotspot | `vbl_align_slit` (E US, E DS; also C, B), `vbl_slit_ic_scan` for a coarse start | slit image on the frame centre | shifts < 10 um |
| lenses (hutch E): put one in (x = 0), tilt to focus | `vbl_lens_scan`, prediction in the result | footprint size | narrowest line |
| rotation axis with the pin | `new_run(backend='vbl', camera='gh1')`, then `align_adaptive` (see `playbooks/alignment.md`) | pin column vs omega | a, b < 1 px; c on the beam |
Re-peak after ANY change of WB size, gap, steering or after a long wait: the first mono crystal warms (Th2 optimum shifts, time constant ~7 min of virtual time).

## What the images tell you (rules the renderer follows)
- Footprint = the intersection of every aperture upstream; its brightness falls toward the edges (Gaussian beam) and has vertical-streak mottle; dust stays on the sensor when the beam moves; hot pixels and a dark floor are always present.
- **Sharp edge = a slit close to the camera (the E slits), blurry edge (60-100+ px) = a slit far upstream (WB, B).** `vbl_describe_view` names the aperture that defines each side and its blur in pixels; use it to understand why an edge looks the way it does and which slit to move. A slit in the beam also shows a thin bright rim (Fresnel).
- Closing a slit makes a smaller, equally bright window (the camera sees the slit image); if the closed slit shows nothing it is off the beam by more than the footprint: scan its centre with an IC (`vbl_slit_ic_scan`).
- The pin is a dark truncated cone, its column follows `c + a cos w + b sin w`; +x moves it left, aerox moves the axis (see `playbooks/alignment.md`). Camera defocus blurs the edges; a lens in the beam collapses the footprint into a line in its focusing direction.

## Rules and honesty
- The truth is hidden. `vbl_readiness` reveals it (scoring only, e.g. to judge a finished run); do not use it to steer.
- Distances not in the twin are ASSUMED (see `beamline_twins/1-ID/sim.json`); the Th2 rocking width, steering gain, source size and blade properties are assumptions too, tagged there. Real beamline behaviour wins over the simulator when they differ: update `sim.json`.
- Add a new simulated effect as a function in `blade/vbl/` plus a `vbl_*` tool in `tools.py` (the MCP rule in `AGENTS.md` applies).
