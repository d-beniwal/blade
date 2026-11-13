# 11. Model inventory: what a virtual beamline needs, what exists, what was fitted, what is pending (2026-11-13)

Scope: every piece of physics the virtual beamline (`blade/vbl`) needs to behave like 1-ID, from the source to the image on the tomo camera. For each: status, where the code is,
what the knowledge base (KB: 109 logs, 80k text lines, 2.8k extracted numbers, 3.8k images) let us fit, and what is still missing.
Detail and provenance per domain: `fits/{source,mono,flux,optics,camera}.{md,json}`; code `blade/physics/{source,mono,flux,optics,camera}_fit.py`; tests `tests/test_fit_*.py`
(all pass; they read only the committed JSON, never the private KB). Numbers cite only startup/tables logs by id; user logs appear as "user log <year>".

Status codes: **V** validated against logged numbers earlier (`test_physics.py`) · **F** fitted from KB data in this pass · **A** assumed (value in `sim.json` with no data behind it) · **M** missing (no model).

## 11.1 Inventory

| # | physics | status | code | what we know now |
|---|---|---|---|---|
| 1 | undulator gap -> harmonic energy | **F** (was V) | `source_fit` | 88 logged (gap, n, E) rows, 16 energy clusters, n=5-11, 8.5-11.3 mm: period 20.95 +- 0.47 mm (device name U21), K(g) = a exp(b g/lambda_u): a=2.670, b=-3.297; 0.115 % rms in E (0.0096 mm in gap). The old 21.9 mm period was absorbing coefficient error. Only valid 8.5-11.3 mm. |
| 2 | harmonic choice rule, gap limit history | **F** | `source_fit` | "highest odd n with gap >= limit": 15/16 energies. Limits 8.82 (Nov 24) -> 8.75 (Jan 25) -> 8.80 (Jul 25) -> 8.5 (Jun 26). |
| 3 | gap wander / hysteresis | **F/A** | `source_fit` | wander 0.0009 mm within a session, 0.0092 mm between sessions; hysteresis SIZE still assumed (0.012 mm). |
| 4 | undulator flux vs harmonic and gap | **A** | `undulator.py` | exponent 0.74 fits ONE 5th/7th ratio only. |
| 5 | gap-scan lineshape (FWHM) | **A** | - | physics says relative width ~ 1/(nN) -> n-independent; sim scales with n (right only at n=7). |
| 6 | SCU (2022-23) current -> energy | **F** | `source_fit` | quadratic K(I), 180-825 A, 0.4 % rms (anchors); the log's harmonic labels are wrong (series called n=9 is n=11). |
| 7 | source size, divergence, emittance | **A** | `sim.json` | not derivable from logs (focused spots are lens/slit limited); 30x20 um in sim is an upper bound. Regular-mode V source 19.7-29.1 um. |
| 8 | ring current -> flux, top-up | **A** | - | linearity rests on one cross-check; no decay series. |
| 9 | steering <-> position | **F** | `optics_fit`, `flux_fit` | lever arm ~25 m (2 points); off-resonance steering profile sigma 31.9 urad (H), 61.4 urad (V); BPM gain 0.88/0.92 per urad. |
| 10 | WB slit -> flux (beam sigma at WB) | **F** (was A) | `flux_fit` | sigma 0.147 +- 0.009 mm isotropic (3 within-session ratios agree to 1 %). H and V not separable. |
| 11 | WB slit heat load -> Th2 detuning | **F/A** | `mono_fit` | ~18 K per mm^2 aperture (2 points). |
| 12 | HEM Bragg geometry, fixed exit, Th1 offset | **V** | `core` | unchanged. |
| 13 | edge readback offset, session spread | **F** | `mono_fit` | 43 E_scan fits: offset mean -44 eV, sd 44 eV (= +1.2 +- 1.15 mdeg Th1); Re drift +2.6 eV/month. The sim's startup Th1 error (0.5 mdeg) is too small: N(1.2, 1.0) legacy, N(0.19, 0.22) after the Jul-2026 re-reference. |
| 14 | Th zero re-reference (Jul 2026) | **F** | `mono_fit` | offset +0.04 -> -0.33 deg; first state 17 mdeg (775 eV) off. Only 71.676 keV is logged afterwards. |
| 15 | foil step b / effective thickness | **F** | `mono_fit` | Hf 1.152, Sm 0.913, Ir 1.591, Ho 0.828, Ta 0.967 (+Pt, Bi, Tm); sim's Ho/Ta/Hf wrong; operators' `ut` equals b to 1 %. |
| 16 | edge width vs energy | **F** | `mono_fit` | one-term 22.8 urad (rms 4.1 eV) or natural K width + 8.9 urad (3.7 eV); natural vs instrumental NOT separable. |
| 17 | in-session energy drift | **F** | `mono_fit` | random walk 1.1 eV/sqrt(h); dump shifts sd 9 eV (3 events). |
| 18 | thermal relaxation tau, Th2 rocking width | **A** | - | no time series / Th2 scan exists: tau=420 s and 2 mdeg are assumed; the logs bound the FWHM to 0.6-6 mdeg (Darwin prior 0.31 mdeg). |
| 19 | lens tilt -> focus (E stacks) | **F** | `optics_fit` | f = h sin(tilt)/(c delta), c = 2.11 +- 0.17; E focus plane z = 69.49 +- 0.15 m (NOT 71.5); optima reproduced to <0.6 mdeg; 15 mm focus per mdeg (not 41). Explains the Feb-2026 nonsense (formula + sample distance, not delta(E)). Source distance unconstrained; z_sample and c 99 % correlated. |
| 20 | focused spot size vs energy (B CRL) | **F** | `optics_fit` | FWHM^2 = s0^2 + (b(E^2-E_tuned^2))^2: s0 23.8 um V / 29.2 um H, b 0.096 um/keV^2, tuned 60.65 keV (chi2 3.3/6). Brightness mode 0.74x V, ~1.1x H. |
| 21 | slit penumbra (geometry) | **V** | `optics_fit` | same formula as `blade.vbl` on all 8 apertures. |
| 22 | slit edge width on camera, Fresnel rim | **F (image)** | `camera_fit` | 10-90 % width 38 um median on PG (63 edges), 19 um on GH1 (15). Penumbra-vs-distance validation still pending. |
| 23 | attenuator wheels | **F** | `flux_fit` | both sim tables wrong: attenB 11 positions incl. Pb 1.5/3/5 mm; attenC 8 positions ~2.35 mm Cu/step. Per-position transmission check has 1 point (x1.031). |
| 24 | ion chamber response | **F/A** | `flux_fit` | rate ~ gain^-0.955 (+-0.035): the sim's "all gains = 1" needs 50/gain; per-IC dark (IC4-E 0.93 kHz, not 0.35); gas and length NOT identifiable. |
| 25 | absolute flux vs energy | **F (rough)** | `flux_fit` | 7-knot correction vs 71.7 keV: 42 keV 1.04, 52 2.20, 61 2.13, 72 1.00, 81 0.99, 87 0.55, 90.5 0.34 (10-25 % unc). The sim pins 176 kHz at every energy. |
| 26 | fast shutter | **F/A** | `flux_fit` | leakage ~8e-5 of open beam; vertical opening 1.69 +- 0.16 mm; no timing numbers anywhere. |
| 27 | Kohzu (B/C/E) slit transmission | **A** | - | no flux-vs-size series. |
| 28 | tomo pixel size per camera and era | **V/F** | `camera_fit` | sensor pitch / magnification reproduces every logged value; retiga2 1.0 vs 1.48 resolved (same 7.4 um camera, 7.5X in B, 5X in the NF station); PG1 needs a per-era pixel size (7.5X = 0.7813 um/px). |
| 29 | alignment-pin geometry and contrast | **F** | `camera_fit` | TWO pin families the sim mixed: B (7.8 +- 0.06 deg half angle, 105 um top; 3 frames, 1 session), A (14.8 +- 0.25 deg, 135-220 um top; 8 frames, 3 sessions). W K edge at 69.5 keV (mu 66 -> 200 /cm): 104.5 um chord transmits 0.12 at 71.7 keV (sim 0.08). |
| 30 | beam texture (mottle) | **F (image)** | `camera_fit` | correlation length ~26-32 um, rel rms 0.08-0.11, PSD slope -2.45 (57 frames); the sim's is ~2x too long and ~3x too strong. |
| 31 | dust / window defects | **F (image)** | `camera_fit` | ~29 spots/mm^2 at ~4 um; sim density right, spot size ~3x too large. |
| 32 | camera noise, saturation, gain | **A** | `camera_fit.ptc_fit` | needs raw 16-bit frames (the KB has 8-bit screenshots). |
| 33 | scintillator + objective PSF, counts vs energy | **A** | `camera_fit` | LuAG, NA 0.14 assumed; LuAG K edge 63.3 keV predicts x3.7 step, untested. |
| 34 | diffraction detector geometry (rings) | **V** | `detector` | Pilatus pitch 172.000 um from three calibrations; NF beamstop drift 3.3 um per mm DetZ (2.8-5.0). |
| 35 | rotation-stage startup errors | **F (small n)** | `camera_fit` | wedge median 0.004 deg (n=11), omega zero 0.023 deg (n=6), tilt 0.30 deg (n=6). |

## 11.2 Physics the VBL needs that nothing models yet (and why it would matter)

| aspect | what it adds to the VBL | data that would build it | status of data |
|---|---|---|---|
| **Motor/stage mechanics**: limits, resolution, velocity, backlash, soft-limit trips, slit blade stuck (B inboard blade, 2025) | realistic failures and move times; agents must handle limits/stuck blades | the 873 legible, value-rich panel screenshots (motor/slit/scaler) already classified in the KB: transcribing them gives limits, velocities, positions, IC rates in bulk | classified, **not transcribed** (largest single unlock) |
| **Time dynamics**: ring current decay and top-up, beam dumps, thermal transients, session drift as ONE clock | long-run behaviour, "wait for thermalisation", when to re-tune | timestamped Emon/IC series after dumps (mono P1/P6, flux #4) | no series in logs; needs ~2 h of logging |
| **Sample interaction**: absorption contrast, phase contrast / propagation (Fresnel number at tomoE), edge enhancement | radiographs of real samples, exposure choice, pin contrast vs energy | one raw pin/sample frame at 2 energies across 69.5 keV (camera pending 4) | pending beam time |
| **Tomography and rotation-axis reconstruction**: sinogram of pin/sample under rotation, axis offset/tilt in reconstructed slices | closes the loop between alignment and recon quality (the real goal of the axis alignment) | the vbl already has axis kinematics; reconstruction check needs only code (astra/tomopy), not data | **buildable now**, not built |
| **Far-field / powder diffraction signals** (CeO2 rings with polarisation, Debye-Scherrer intensity, detector response) | simulated calibration frames for MIDAS/GSAS-II loops | ring radii logs (camera pending 6), detector counts per energy | partly buildable now (geometry done) |
| **FF-HEDM spots from grains** (omega/eta, structure factors) | end-to-end diffraction experiments in the VBL | a few real indexed datasets for validation | outside the alignment scope; MIDAS already simulates |
| **Control-system behaviour**: PV latency, scaler counting time, IOC hiccups, wrong-channel readings (`ic1b` reads dark-like) | agent robustness to the real EPICS layer | scaler channel map; IOC logs | pending (flux #13) |
| **Failure-mode library**: stuck blade, lens support in beam, preamp off, FS misalignment, mu*t calc-record unzeroed, driver switched off | realistic faults to train/evaluate agents | the 165 pitfalls already extracted into the procedure KB | **buildable now** as injectable faults |
| **Survey distances** (E lenses, sample, tomoE, slits) | pins down z for all geometry; resolves the c vs z_sample degeneracy | 8 positions in E (staff, one shift) | needs staff |

## 11.3 Pending fitted-model list, with how each would improve the VBL

| pending model | VBL benefit | unlocked by | effort |
|---|---|---|---|
| thermal relaxation (tau, amplitude vs WB power) | post-dump retune loop and cold-start flux become real | Emon every 1-2 min for 1 h after a dump, IC_B1 in parallel, two WB sizes | ~2 h beam |
| Th2 rocking curve and its energy coupling | Th2 tweak step becomes calibrated; flux optimisation realistic | one +-5 mdeg scan at 52/72/90 keV | 20 min |
| H/V beam sigma, WB centre offset | steering/centre-hunt order of axes | WB centre scans in H and V at one energy | 10 min |
| IC gas/length, absolute flux | counts from real undulator flux; energy response of ICs | IC drawing, or one calibrated diode reading | 1 h |
| flux vs energy, one session | replaces the rough 7-knot correction | B1 and B3 together at ~9 energies | 30 min |
| harmonic flux exponent, gap-scan lineshape per harmonic, hysteresis size | gap peaking and harmonic choice realistic | raw `undscangap` files at n=5,7,9,11; up/down scan | 0.5 day + 20 min |
| ring-current linearity | flux normalisation | scaler logging through a decay | passive |
| Kohzu slit transmission (B/C/E) | slit-size vs flux for all downstream slits | IC vs slit size series | 20 min |
| attenuator per-position check; FS timing and leakage vs X | exposure planning, shutter dose | wheel scan; scope trace | 10-30 min |
| survey of E distances; tilt-vs-energy for C and B lens stacks | focus model for every hutch | staff survey; one logged (E, tilt) per energy | small |
| C/B stack tilt histories | extends lens fit beyond E | motor-panel screenshots (transcription) | 1 h |
| source size and divergence (H/V, both modes) | spot floor, penumbra | spot vs WB size at fixed lens position + emittance from the accelerator group | 1 shift |
| photon-transfer curve, knife-edge PSF, counts vs energy per camera | shot-noise-correct frames, resolution, saturation | raw 16-bit frames (not screenshots) | 1 h per camera |
| pin interior transmission across 69.5 keV | pin contrast and edge softness | raw pin frames at two energies | 15 min |
| pixel size for retiga2, PG5, 20-ID camera | exact FOV | calibrated grid per camera | 10 min each |

## 11.4 What was adopted in `sim.json` (2026-11-13) and what was deliberately not

**Adopted** (each changed field carries a `*_src` note pointing at `fits/*.md`; code hooks in `blade/vbl/world.py` are backward compatible: an old sim.json still loads):
- Source: `undulator.period_mm` 21.0 + new `k_coef` (2.6701, -3.2966, 0) passed to every `blade.physics.undulator` call (gap model 7 um rms on the 13 logged peaks, was 16); `flux_model` exponent **0.67** (refit inside the sim's own amplitude function so the 7th/5th ratio at 61.3 keV = 3.08, logged 2.95-3.2; the 0.74 in `fits/source.json` belongs to a different normalisation); n-independent `rel_fwhm` 0.0098 (replaces `rel_fwhm_per_harmonic`); `gap_wander_mm` 0.0092; `truth_scales.gap_err_mm` 0.01. Harmonic choice stays 13/13.
- Mono: `hem.edge_wid_rad` 22.8 urad; `foils.b` refit and `foils.elements` extended to Sm, Ir, Pt, Bi, Tm (13 foils, each reproduces its `b`, thickness 0.06-0.23 mm); `truth_scales.th1_err_mdeg` 1.5; `thermal.th2_shift_deg_per_kW` 0.004 -> 0.0009 (derived so a cold->hot detuning gives the ~7 eV dump shifts logged; `tau` and the 2 mdeg Th2 width remain assumed, the latter is inside the 0.6-6 mdeg the logs allow).
- Flux: `source.beam_sigma_at_wb_mm` 0.147; attenuator wheels (B: 11 positions with Pb entries, C: 8 positions at ~2.35 mm Cu/step; entries are mm of Cu or `[material, mm]`); per-IC dark floors; `ic.flux_vs_energy_knots` (IC readings now follow the fitted flux-vs-energy curve instead of a constant 176 kHz; with steering re-tuned the sim reproduces the 7 knots to 3 %); fast-shutter vertical opening 1.69 mm.

**Not adopted, with reasons** (all still listed above as fitted):
- Pin geometry (`stage_E.pin`: half angle 7.8 deg / transmission 0.12) and the beam-texture / dust scales (`cameras.*`): they change the pin frames that the pin-alignment work will study; adopt them together with that work (the texture is the likely cause of the old `align_adaptive` failure).
- IC preamp gain (rate ~ gain^-0.955): needs a per-IC gain control in the simulator; IC gas/length are unidentified.
- Lens model (E focus plane z = 69.49 m, c = 2.11, 15 mm/mdeg): the sim's lens code and `focus_motor_target` use the old geometry; changing it is a code change in `blade.physics.lens` and `world.trace`, not a number.
- B-CRL spot model, source size, SCU, pixel-size-per-era (profile data), hysteresis size, Kohzu-slit transmission, FS leakage and timing.

**Checks run after the change (no pin alignment): ** `test_physics`, `test_fit_{source,mono,flux,optics,camera}`, `test_vbl_vs_logs` (updated to read sim.json: gap rms 7 um, harmonic 13/13, 7th/5th 3.08), `test_vbl_physics` (86 checks; two stale expectations updated: attenC position 3 is now 7.07 mm Cu, harmonic gap check passes the fitted coefficients), `test_vbl_render` (24), `test_analysis`, `test_twin_gui`, `test_kb_gui`, `test_gui_launch`, `twin.py check` (0 errors); startup sequence from 4 random truths converges as before (gap error 4 um, Th2 error ~0, flux 0.997 of best) and all 13 foils calibrate. NOT run: `test_vbl`, `test_mcp`, `scripted_agent` (they run `align_adaptive`).
`sim_proposed_2026-11-12.json` is superseded by this adoption.

## 11.5 How good is the evidence
Most fits rest on a handful of logged numbers; only the undulator (88 rows) and edge offsets (43 fits) are well sampled. Frames from one session are correlated, so independent n for image fits is smaller than the frame counts. The KB images are 8-bit viewer screenshots: geometry is measurable, absolute counts are not. Treat every `F (small n)` row as a prior to be updated by the next beamtime.
