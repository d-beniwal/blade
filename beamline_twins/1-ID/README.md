# 1-ID twin: status and open questions

Built 2026-11-11 from the 18 photos of 2026-10-20 plus read-only `mpe_bluesky`. Human view: `layout.md` (generated). Schema: `../README.md`.

## What is mapped

- Beam order SRC > A > B > C > E, **70 elements** (12 with a known distance, see below), with confidence per element (see top of `layout.md`).
- **B, C, E:** full order from the CS-Studio panels, IC counts, slit sizes/centres, device/PV names matched to `mpe_bluesky`.
- **Tomo detectors:** B-TOM (`tomoB`, hutch B), Tomo D1 (`tomoC`, hutch C), Tomo D1 (`tomoE`, hutch E, retractable, probably `tomoEus`). Other detectors: Varex D2 (C), NF D2 / D3 / Hydra D4 / VFF D5 / Radiograph / SAXS D6 (E).
- **Slits (6):** WB (A), B Kohzu, C US/DS, E US/DS.
- **Hutch E sample stage** (`assemblies/samE.json`): full stack top to bottom with motors, limits, readbacks.

## What is NOT known (needs the user, drawings or more photos)

1. **Most distances.** Known (m from the source, all from `mpe_bluesky`): source 0, lens stacks B 38.8/38.9 (stack-to-lens4B/5B mapping is a guess), C 59.2-59.7, E 67.7-68.5, default sample position in E 71.5. Missing: every IC, slit, shutter, foil/attenuator, mono (HEM, HRM), detector, hutch wall, and the C sample stage - source-to-element distances from drawings or a survey, hutch entry/exit positions at least.
2. **Hutch A / SRC.** Not photographed (1-ID-Main panel): order of WB slits, A shutter and HEM; where the HEM actually sits; undulator gap value (the unlabelled `10.012 mm` on the panels is probably it).
3. **Which camera is on which detector.** gh1 / pg1 (E) and pg5 (C), retiga2 (B) vs `tomoE`/`tomoC`/`tomoB`; which of `tomoEus` / `tomoEds` carries gh1.
4. **Tomo D1 / NF D2 geometry.** Are they alternative positions (retracted/inserted into the beam) as the panel layout suggests? Travel ranges and in-beam positions.
5. **Unknown items on the panels:** B `Cork` (112 mm, On/Off), `BL3/BL4/BL5`, the magenta end marker; C `fourC`, `DBA`, `Lens7`, `L5/L6 (RD)`, the green markers on L1-L4 and detectors; E `HL-SMS`, `D3`; the orange `0.004` above the B foil.
6. **IC to scaler channel mapping** (which ICs form mu*t; photon-count calibration) and the exact IC reading/IC assignment (done by proximity on the panel).
7. **Stack order of Aero Z vs Aero X** in the sample stage, and the E-hutch Aero base geometry.
8. **Sticky notes in p11** ('MICRO X -40 mm', 'Microscope in beam ... PIN 90'): what the microscope is and how it is brought into the beam.
9. **Slit centre sign convention** and what Sync H/V does (already open in `DOMAIN.md`).
