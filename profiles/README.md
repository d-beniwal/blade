# BLADE beamline profiles

A profile holds **everything that is specific to one beamline**; the BLADE code contains none of it.
`profiles/<name>/default_config.json` is committed. An optional `profiles/<name>/active_config.json` (git-ignored) is deep-merged on top
for per-workstation overrides (same idea as B-PILOT). Extra profile folders outside the repo can be put on `BLADE_PROFILES_DIR`.

**Stations.** Motors and sign geometry describe one hutch's stage arrangement, so they live under `stations.<hutch>`, not at beamline level. `s1id` currently has only
station `E` (samE stage); another hutch with different motors/geometry is added as a sibling entry (`stations.C = {...}`) without touching `E`. Select with
`--station <S>` on `new-run` (stored in the run), or `BLADE_STATION`; default `default_station`. Cameras stay beamline-level and name their `hutch`.
Limits, tolerances and pin shape are still shared by all stations of a profile; move them under a station if a hutch needs different values.

Select a profile with `--profile <name>` on `new_run` (stored in the run afterwards), or `BLADE_PROFILE=<name>`; default `s1id`.
`blade profiles` lists what is available.

| Section | Meaning |
|---|---|
| `beamline`, `description` | labels shown in the GUI |
| `backends` | `sim` (private simulator per run) and/or `vbl` (the shared virtual-beamline session: needs `twin` and a `beamline_twins/<bl>/sim.json`). There is no hardware backend: BLADE does not command the beamline; the read-only reader is `blade/instrument/epics.py` |
| `twin` | optional: id of the beamline twin (`beamline_twins/<id>/`) the GUI's twin viewer (`/twin`) shows for this profile; omit if there is none |
| `cameras` | per camera: `pixel_um`, `pv_prefix` (pvAccess `<prefix><camera_pva_suffix>`; `null` = simulator only), `hutch`; `default_camera` |
| `stations` | **per hutch/station** (key = hutch, e.g. `E`): `description`, `motors`, `geometry` (below). `default_station` picks one |
| `stations.<S>.motors` | logical roles `omega, x, y, z, base` -> EPICS motor `pv` + display `name` (units must read back as mm) |
| `stations.<S>.geometry` | sign links: image column per +x, rotation sense, image row per +y, axis column per +base (px per mm sign) |
| `limits` | per-move step limits, rotation limit, find-pin search radius, timeouts (equipment protection) |
| `tolerances` | `tol_ab_px`, `tol_c_px`, `beam_frac` |
| `pin` | alignment-pin shape priors used by detection (cone half-angle, contrast, top width) |
| `procedure` | fast-align steps, default sweep angles, whether to save raw frames |

## Adding a beamline
1. `cp -r profiles/demo profiles/<name>`, edit `default_config.json` (rename/edit the one station).
2. Build its twin and `control_pv_map.json` (`beamline_twins/README.md`); a sign in `geometry` is only a sign - confirm it against the real stage when someone is at the beamline.
3. Run on the simulator (`new_run(profile=<name>)`).
The pin-alignment procedure assumes the *rotation stage + cone-shaped pin on a tomo camera* arrangement; other arrangements need a new procedure under `blade/procedures/` (see `AGENTS.md`).
