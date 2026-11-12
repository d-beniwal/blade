# 3. Lenses: what changes when you tilt a lens or change the energy

Twin elements: `lens1E..lens4E`, `lens1C..lens4C`, `stackB1/stackB2` (lens4B/5B). Code: `blade.physics.lens` (`LENSES_1ID`, `focus_motor_target`, `prism_*`). Citation keys: `README.md`.

## 3.1 The lenses are tilt-tunable saw-tooth (prism-array) lenses
Each stack is a silicon (aluminium in B) saw-tooth lens, a 1D prism array, so one lens focuses in one direction. The beamline's own focusing code (`mpe_bluesky/.../calculator_tilt.py`) and its device definitions encode the model, which this project re-implemented and validated:
- thin lens `1/f = 1/p + 1/q` with `p` = source-to-lens and `q` = lens-to-focus (focus defaults to the E-hutch sample stage, 71.5 m from the source);
- `r = f * delta` (equivalent radius), `tilt = asin(r / h)`, i.e. **`f = h sin(tilt) / delta`**, with `h` the tooth height (200 um for the Si lenses in C and E, 100 um for the Al lenses in B);
- `delta` from xraydb (Si at 71.676 keV: 9.376e-8; Al: x1.12 larger); `delta` scales as 1/E^2;
- orientation sets the sign and **which motor focuses**: `th` for `upr/up/inv/down`, `phi` for `out/ob/inb/in` (so lens1E, lens2E use `th`; lens3E, lens4E use `phi`), plus a recorded motor zero (lens1E -0.011 deg, lens2E -0.0627 deg).
Literature on the lens type: Cederstrom et al., J. Synchrotron Rad. 12 (2005), doi:10.1107/s0909049504034181; for conventional parabolic CRLs f = R/(2 N delta), Lengeler et al., J. Synchrotron Rad. 9 (2002), doi:10.1107/s0909049502003436. (The tilt formula is the beamline's; it was not re-derived from the paper.)

**Validation against the logs.** At the Hf edge (65.351 keV), focus at 71.5 m, the model returns lens1E +0.105 deg and lens2E -0.173 deg, and at +205 mm +0.111 / -0.179 deg: **all four numbers equal the beamline's logged "BS prediction"**. The measured optima were +0.107 / -0.168 and +0.121 / -0.181 deg, so the prediction is good to 0.002-0.010 deg [M26a:L611-615]. (An attempt in the same log to solve for the source distance p from the measurements gave nonsensical values, an assumption is wrong; a survey was requested [M26a:L606-609].)

## 3.2 What changes, and by how much
| change | effect | size (model, lens1E, Si, focus 71.5 m) |
|---|---|---|
| tilt +1 mdeg | focus moves downstream | **~41 mm per mdeg**; f = 3.6 m at 0.0966 deg (71.676 keV) |
| energy up | delta falls ~1/E^2, focus moves downstream unless re-tilted | needed tilt 0.1727 / 0.1053 / 0.0856 / 0.0652 deg at 52.0 / 65.4 / 71.7 / 80.7 keV |
| energy +/-76 eV at 71.7 keV (a mono drift) | focus shifts | ~8.5 mm (negligible next to lens tilt) |
| focus requested closer | needs a larger tilt | `|sin tilt| <= 1` limits the shortest focal length (tooth height) |
Because a milli-degree moves the focus by centimetres, **the lens-tilt motor resolution and zero matter far more than the mono energy**. Typical tilts are 0.05-0.2 deg, the same scale as the recorded zero offsets.

## 3.3 Focus quality actually achieved
- B vertical focusing lens: beam ~20 px FWHM ~ 22 um at the tomo camera [S23:L166,L453]. Brightness mode: vertical ~17 um vs ~23 um regular, horizontal ~30 vs ~27 um [B26]. Focus FWHM (px) vs energy at n=7/5 in Nov 2024: 18.6/17.1 (62.3 keV), 16.6/13.7 (61.29), 16.0/13.0 (60.7), 16.4/12.8 (60.3, n=5) [A24:L222-237].
- Lens tuning scans: `dscan l3phiB -0.2 0.2 40 1` and `l3thB` on the IC7-B/IC8-B ratio; a phi scan loses 3 % of flux within ~0.4 deg [B26:L41-43]. After tuning the B lens stage moved Phi -0.39 -> -0.41, Theta 0.0136 -> 0.0036 [B26:L39,L43]. L4B Th changed -0.6745 -> -0.68296 deg between the WAXS-B-focus and B->E-focus settings (2022 AM-setup log).
- **The focus drifts:** the focused spot moved ~18 um over an overnight-stable ring [A24:L248-253] and off the 100 x 100 um box after beam dumps [A24:L210-219]; after the APS-U start the beam moved 1-2 mm inboard in E so lens supports were in the beam (lens-3 re-set from -2.2 to -4.2 mm) [M24:L266-268].

## 3.4 Things that look like lens problems but are not
- **CRL box / support clipping** reduces flux (check list item in [S25a]); weak B-hutch beam (B3 ~420 kHz vs 650 kHz) recovered when the CRL stack was translated out and B2 re-zeroed [T26:L466-471].
- **Lens-aperture truncation:** the OB edge of the focused beam was cut and moved with the WB slits (not with C/E/B lenses), so a WB-slit blade was suspected [A24:L64].
- **Surface/thermal effects:** open-beam image growth of ~1 px (0.69 um) in 2-3 min on a test sample, recovering without beam [M26a:L170].
