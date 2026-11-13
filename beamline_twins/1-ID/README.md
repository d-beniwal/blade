# 1-ID twin: status and open questions

Built 2026-11-11 from the 18 photos of 2026-10-20 plus read-only `mpe_bluesky`; **2026-11-12: re-based on six CS-Studio screenshots (`cs01`-`cs06`)** (overview strip, B/C/E panels, IOC Control, HEM/WB-slit/ID-gap screens). They replace the phone photos p12-p14 as the *layout* source; those stay cited only for the 2026-10-20 readings (the screenshots have disconnected PVs, no values). Human view: `layout.md` (generated). Schema: `../README.md`.

## What is mapped

- Beam order SRC > A > B > C > E, **70 elements** (12 with a known distance, see below), with confidence per element (see top of `layout.md`).
- **B, C, E:** full order from the CS-Studio panels, IC counts, slit sizes/centres, device/PV names matched to `mpe_bluesky`.
- **Tomo detectors:** B-TOM (`tomoB`, hutch B), Tomo D1 (`tomoC`, hutch C), Tomo D1 (`tomoE`, hutch E, retractable, probably `tomoEus`). Other detectors: Varex D2 (C), NF D2 / D3 / Hydra D4 / VFF D5 / Radiograph / SAXS D6 (E).
- **Slits (6):** WB (A), B Kohzu, C US/DS, E US/DS.
- **Hutch E sample stage** (`assemblies/samE.json`): full stack top to bottom with motors, limits, readbacks.

- **Physics** (`physics/`): cause->effect notes for source, mono, slits, lenses, flux/attenuation, sample stage, detectors, built from the startup logs 2022-2026; `blade.physics` implements and validates the formulas against numbers in the logs.

## New with the 2026-11-12 screenshots

- Hutch A now seen: **Filter > WB slits > HEM** (white beam up to the HEM, mono beam after); HEM motors `1idHEM:m1/m4`, energy via transform record `1id:userTran3`; WB-slit panel is drawn *looking upstream*; undulator panel `S01ID:DSID:` (current/desired taper, gap, energy), so the unlabelled 10.012 mm is very probably the gap.
- Elements carry `panel_x` (pixel along the beam line on the screenshot) and `group` (the boxed groups of the panel, e.g. Beam Conditioning System); the viewer spaces elements "as on the operator panel" (schematic, not distance) and brackets the groups. Order of all B/C/E elements was re-checked: unchanged.
- Detector IOCs (`beamline.json` -> `detector_iocs`): gh1 and pg1 are both hutch-E tomo cameras; SAXS D6 = Pixirad2; Pilatus 2M, GE1-GE5, Eiger16M exist but are not yet assigned to elements.
- **User answers 2026-11-12:** A shutter is first in A (confirmed). B ends at the magenta circle. DBA = diffracted beam aperture on an inverted hexapod (`1mini2:hxp:c0:m1-6`, `1idc:m83`); BL3 = compound lens, BL4/BL5 = saw-tooth lenses (B hutch). Hydra D4 = GE1-GE4 (move together); GE5 separate; D3 is shared by GE5 / Pilatus / Eiger (one at a time). gh1 = Tomo D1 (E, `Tomo_E` motors m40/m38/m63/m62); pg1 = VFF D5 or Radiograph (unconfirmed); pg5 = C Tomo D1 (IOC list), retiga2 = `Tomo_in_B` (inferred).
- C motors: fourC table `1idc:m76` + `1idcAMCI:m2-m6`, circles `1idc:m40,m74,m75,m85,m86` (roles not named on screen); LabMotion_SMS panel order gives Rx m28, Rz m29, samX m27, samZ m25, samY m26, Labmotion `1idELMO:m1`, TransX m31 (inferred from panel order; disagrees with mpe_bluesky for x/z/y).
- All IOC Control tabs but Qserver captured (VME crates 1ida/1idb/1idc/1ide/1ide1, misc IOCs incl. HEM_Z2, PI518 (HRM), Zynq boards).
- Auxiliary panels (C, E), the four E lasers, IC readout PV families (`1id:S1:s...` B/C, `1ide2:` E), header PVs.

## Checked against the CS-Studio displays (2026-11-13)

`tools/csdisplays.py extract` parses the layout displays (`1id/1ID_top_panel`, `1idb/1idc/1ide_layout`, shutter, HEM screens) into `cs_registry.json`; `csdisplays.py check` and `tests/test_cs_registry.py` compare the twin and the s1id profile with it (0 errors). What the displays settled or corrected:
- Element order along the beam in B, C, E matches the displays exactly (HRM = one button for both crystals; HL-SMS is an alternative to the Aero SMS).
- Profile `s1id` station E motors (omega `1ide:m9`, x `m34`, y `m35`, z `m36`, base `1ide1:m101`) and the camera prefixes gh1/pg1/pg5 are on the displays (names samX/samY/samZ/Aero Rot/Aero_X).
- New: IC read-out (scaler channel + preamp) for every IC, station shutters FES/SBS/SCS/SES, filter bank `1ida:fltr1-4:select`, full HEM motor set `1idHEM:m1,m4,m5,m6,m7,m8`, NF D2 and D3 stages, the slit-blade motors of all six slits, the cameras opened from each detector button.
- Corrected: `d2E` (mpe_bluesky) pointed at the D3 stage (GE_X/GE_Z in E) and the Tomo D1 shielding motor; samC y is `1idc:m26` (not `1idGalil1:m1`); Hydra z follows the display (`1idc:m7`).
- Conflicts kept open (registry `conflicts`): FS x/y (m75/m77) and samC x/z (m25/m27) are labelled opposite on the display versus the log-panel motor descriptions + code; `1idc:m31` TransX vs rotXC; Hydra z display vs code; the B slit lists m32 on one panel and m59 on another.

## What is NOT known (needs the user, drawings or more photos)

1. **Most distances.** Known (m from the source, all from `mpe_bluesky`): source 0, lens stacks B 38.8/38.9 (stack-to-lens4B/5B mapping is a guess), C 59.2-59.7, E 67.7-68.5, default sample position in E 71.5. Missing: every IC, slit, shutter, foil/attenuator, mono (HEM, HRM), detector, hutch wall, and the C sample stage - source-to-element distances from drawings or a survey, hutch entry/exit positions at least.
2. **Hutch A / SRC.** Overview strip + WB/HEM/gap screens captured; still open: where the A (FES) shutter sits (not drawn on the overview), HEM crystal/offset plane, truncated PV names, the full 1-ID-Main panel.
3. **Which camera is on which detector.** SETTLED 2026-11-13 from the CS-Studio displays: gh1 (`1idGH1:`) = hutch E Tomo D1, pg1 (`1idPG1:`) = Radiograph, pg5 (`1idSP5:`) = hutch C Tomo D1. Still open: `retiga2` (B) - the IOC list has one B camera `Tomo_in_B` = `QIMAGE2:` (Windows QImage IOC), not adopted in the profile until its image PV and identity are confirmed.
4. **Tomo D1 / NF D2 geometry.** Are they alternative positions (retracted/inserted into the beam) as the panel layout suggests? Travel ranges and in-beam positions.
5. **Unknown items on the panels:** B `Cork` (112 mm, On/Off), `BL3/BL4/BL5`, the magenta end marker; C `fourC`, `DBA`, `Lens7`, `L5/L6 (RD)`, the green markers on L1-L4 and detectors; E `HL-SMS`, `D3`; the orange `0.004` above the B foil.
6. **IC to scaler channel mapping** - SETTLED 2026-11-13 from the displays (`beamline.json` -> `ic_readout`, per element in `cs_registry.json`). Still open: which ICs form mu*t (analysis choice) and the photon-count calibration.
7. **Stack order of Aero Z vs Aero X** in the sample stage, and the E-hutch Aero base geometry.
8. **Sticky notes in p11** ('MICRO X -40 mm', 'Microscope in beam ... PIN 90'): what the microscope is and how it is brought into the beam.
9. **Slit centre sign convention** and what Sync H/V does (already open in `DOMAIN.md`).
