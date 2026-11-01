# Domain knowledge — 1-ID beamline

Condensed 2026-10-31: only facts still needed. Source: user statements, operator-screen photos (2026-10-26), `mpe_bluesky` (read-only), real frames in local `s1_data/`.

## Alignment goal and stage-1 facts (current work)

Aligned (user) = flux maximised at the edge + pin in view of the tomo camera + pin axis stationary under rotation −90..+90°. Automated now: the last part only (see ALIGNMENT_PLAYBOOK.md). Wedge (axis tilt vs APS Y) is deferred.

- Rotation = `samE.ry` (`1ide:m9`, omega). Pin translations `samE.x/y/z` (`1ide1:m34/35/36`); base motor `samE.aerox` (`1ide1:m101`) moves the rotation axis; `samE.aeroz` = `m102`. The axis is fixed by the base: x/y/z move only the pin.
- Axes: x horizontal, y vertical (+ up), z along the beam (+ downstream). **+x moves the pin (and its image) LEFT looking downstream**, so image column decreases as x increases (`IMAGE_COL_PER_X=-1`). The stage is left-handed (+omega clockwise from the top; `ROT_SIGN=+1`).
  Hardware-confirmed 2026-10-28: +x pin left, +y up, aerox moves the axis column ~−1431 px/mm (gh1).
- Cameras: tomo `gh1` (E, high-res table, `1idGH1:`), `pg1` (E, back wall, `1idPG1:`), `pg5` (C, `1idSP5:`), `retiga2` (B, PV prefix not recorded). Pixel sizes (um/px): retiga2 1.0, pg5 1.17, gh1 0.69 (user wrote "69 micron", assumed 0.69; consistent with calibration moves), pg1 1.17.
  Frames via pvAccess `<prefix>Pva1:Image` (NTNDArray, 16-bit; read like `midas-gui/midas_gui/live_sources.py`). All constants live in the profile `profiles/s1id/default_config.json` only (read via `blade/config.py`).
- `gh1` = Point Grey Grasshopper3 (Spinnaker), frames 1490x1940 uint16 in the test data, ~0.1 s exposure.

### What a tomo frame shows
- **Beam footprint:** a bright rectangle (ratio ≈ the E downstream slit 0.88x0.70 mm), soft vignetted edges, saturated structured core, dark outside (~5–6 kcounts; open beam ~25–30 kcounts), sparse hot pixels. The camera field of view is effectively this footprint.
- **Pin:** dark silhouette, upright truncated cone: flat top (virtual top width ~146 px on gh1 data), straight edges, half-angle ≈ 15.2° (width grows ~0.544 px/row), axis vertical, continues below the footprint. Extrapolated sharp apex would be above the footprint.
  The top is bevelled on one side, flipping with omega; at |omega| ~60–90 one flank is a grey half-transparent wedge. The measurable reference is the **virtual top corners / axis**, not a point.
- **Off-axis pin under rotation:** pin column follows `x(w) = c + a cos w + b sin w` (c = axis column, residual ~1 px on real scans; test data: c ≈ 816, offset ~132 px). Tip row changes only ~2 px over 180°.
- **Test-data HDF5** (`s1_data/tomo_alignment/`): `exchange/data`; `data_dark/white` often all zeros (use raw); omega per frame in `instrument/SMS/E/HR/samRy` (non-uniform steps, many repeats at the ends — always read per frame); rich metadata (slits, lens stacks, `HEM/Energy`, `InsertionDevice/IDGap`, `Scalers/*/IC*`, ring current).
  Fits on frames recorded while rotating need an omega lag of ~−0.5 frame-steps (readback timing, open question).

## Beamline layout (for later stages)

Beam travels left→right; hutch order downstream **A → B → C → E**. Schematics give order, **not distances**. "IC" = ion chamber; red numbers on the panels are IC counts (checked against file `Scalers/*`).

```
SOURCE (undulator) ─ A: WB slits ─ A shutter ─ (HEM mono in or upstream of A)
 B: Al-CRL · IC1 · IC2 · CRL · IC3 · HRM · IC5 · Foil · Atten · IC8 · Stack · B-FS · Cork · B-Kohzu slit · IC6 · B-TOM · BL3/4/5 · IC7
 C: IC1 · IC2 · Slit1 (C_Kuz_US) · fourC · BCS: IC3 · L1..L6 · AttenC · Slit2 (C_Kuz_DS) · IC4 | LabMotion SMS · DBA · Tomo D1 · Stop · Varex D2
 E: BCS: IC1+2 · Slit US (Kohzu_E_up) · IC3 · FS · Lens1..4 · Slit DS (Kohzu_E_dn) · IC4 | Aero SMS · Tomo D1 · NF D2 · IC5 · D3 · IC6 · Hydra D4 · VFF D5 · IC8 · SAXS D6
```

Slits (size H×V mm; operator snapshot, not targets): WB 0.3×0.3 (read-only in code); B_Kohzu 2×2 `slitB` (`1idb:Slit`); C_Kuz_US 0.7×0.7 `slitCus` (`1idc:Kslitus`); C_Kuz_DS 0.8×0.8 `slitCds` (`1idc:Kslitds`);
Kohzu_E_up 0.59×0.54 `slitEus` (`1ide1:Kohzu_E_up`); Kohzu_E_dn 0.88×0.70 `slitEds` (`1ide1:Kohzu_E_dn`).

Other `mpe_bluesky` devices: B `foilB` (1idb:m18), `attenB` (m50), `cork` (m41), `tomoB`; C `attenC` (1idc:m82), `lens1C`–`4C`; E `lens1E`–`4E`, `samE`, `tomoEus/Eds`, `d2E`, `ff` (Hydra), `vff`, `saxs`; shutters `shutter_a/b/c` (`S01ID-PSS:{FES,SBS,SCS}:`), fast shutters;
scalers `scaler1` (`1id:S1:scaler1`), `scaler1E`/`scaler2E`. Not found in code yet: HRM, CRL, DBA, Varex/Hydra detector PVs.

## Concepts for later stages (taught by the user)

- **Undulator:** electrons emit x-rays; maximise intensity (IC) by the **gap** (`pmu.gap.setpoint`; plans `undsetgap`, `undscangap`).
- **Monochromator:** HEM (`hem_energy.a`, keV) selects the energy; optimise transmission near an absorption edge from the **μ·t vs energy** plot (IC after the mono, with a foil). `foilB` is the energy reference (its K-edge calibrates; panel energy 71.676 keV likely Re K-edge — unverified).
  The old recipe (`E_scan`/`emon`: foilB in, attenB out, scan `hem_energy.a` over the edge, fit an error function, move HEM; muT = `1id:S1:scaler1_calc8.VAL`; refuses > 200 eV from current) is commented out/deprecated in `mpe_bluesky` — a template only.
  Which ICs form the μ·t ratio is unknown (guess ln(IC5/IC8)).
- **Slits (Kohzu, 4 blades):** *size* = opening (blades move opposite, centre fixed) = trims/defines the beam; *center* = position of the opening (blades move together) = aligns the slit to the beam. Aligning a slit = scanning its H/V centre (small size) against an IC.
  In `mpe_bluesky` (`generic_slits.py`, `MPE4Slits`): blade motors `ib, ob, bot, top`; soft axes `hsize, hcenter, vsize, vcenter`; `get_size()`, `set_size(w,h)`, `set_center(xc,yc)`, `sync_*()` (the panel's "Sync H/V" = `…Hsync.PROC`). `set_slit(h, v)` with 2 args raises — use `set_size`/`set_center`. Units mm.
  Open: slit centre sign/zero convention, what Sync does and when to call it, which slits are for definition vs alignment.
- **Detector into the beam:** move the tomo detector's translation stages until the beam is visible (candidates `tomoEds/Eus/B`; which moves `gh1` unconfirmed).
