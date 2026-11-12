# Beamline twins

A *twin* is the machine-readable map of one beamline: what is on the beam path, in what order, what controls it, and how sure we are of each fact. It is the base for a simulator that BLADE routines run against before they touch hardware. One folder per beamline (`1-ID/` now; a new beamline copies the layout).

## How the information is stored (and why)

1. **One source of truth: JSON, one file per hutch.** Stdlib-readable (profiles are JSON too), diff-friendly, and a hutch file is small enough to edit by hand. A new dependency (YAML) was avoided on purpose. Everything human-readable is *generated* (`1-ID/layout.md`), never edited, so it cannot drift.
2. **Topology first, geometry second.** The beam path is the order of the `elements` list inside each hutch file, hutches in `hutch_order`. Distances (`z_m`, m from the source) are `null` unless a real source exists (drawings, surveys, or numbers already in `mpe_bluesky`), and each carries `z_conf` + `z_src`; nothing is guessed or interpolated. A simulator needs order and element behaviour first, distances later.
3. **Every fact carries provenance.** `conf` is one of `confirmed` (user/hardware-verified) > `seen` (visible in a photo/panel; needs `src`) > `code` (only in `mpe_bluesky`) > `inferred` (my reading, with the reasoning in `notes`) > `unseen`. `src` lists photo ids from `sources/photos.json`. A validator enforces this.
4. **Snapshots are labelled snapshots.** Slit sizes, IC counts, readbacks are stored under `state` with a date. They are the state at photo time, not defaults or targets.
5. **Controls link to the instrument by name, not by copy.** `dev` = device name in `mpe_bluesky` (read-only reference), `pv`/`controls` = EPICS names. The twin does not replace `profiles/<bl>/` (BLADE's runtime config: limits, signs, tolerances); later the profile should reference twin element ids instead of repeating PVs.
6. **Multi-part hardware is an assembly.** `assemblies/<id>.json` holds a stack (e.g. the hutch E sample stage, bottom to top with limits and roles) and is referenced from its element by `assembly`.
7. **Experiment logs stay local too.** The index of the users' experiment logs (`logs_index/`) is git-ignored for the same reason; only aggregate statistics and instrument-physics notes without names are tracked (`physics/`).
8. **Photos stay local.** `sources/photos/` is git-ignored (the repo is public; screens show hostnames, IPs, usernames). The tracked `sources/photos.json` indexes them (what each shows, which elements, caveats). Originals: `s1_data/pictures/`.

## Layout

```
beamline_twins/
  README.md                     this file
  tools/twin.py                 load / check / render / show (stdlib only)
  1-ID/
    beamline.json               frame conventions, hutch order, snapshot header, panel/tab coverage
    hutches/{SRC,A,B,C,E}.json  ordered elements per hutch
    assemblies/samE.json        hutch E sample stack
    sources/photos.json         photo index (photos/ itself is git-ignored)
    layout.md                   GENERATED human view (strips, tables, slits, detectors)
    README.md                   status, coverage, open questions
    physics/                    what happens physically when a setting changes (README + 01..08 notes + relations.json); 07 is generated
    logs_index/                 LOCAL, git-ignored: extracted text + SQLite/FTS index of the experiment logs, catalog.md, reading notes
```
Log tools (stdlib only): `tools/logextract.py` (docx/xlsx/ods -> text), `tools/logindex.py` (build/search/topic/params/show/outline/images), `tools/logstats.py` (aggregates -> `physics/07_typical_parameters.md`). The executable physics lives in `blade/physics/` (needs `xraydb`, extra `physics`).

## Element fields

`id` (unique across the beamline; use the `mpe_bluesky` device name when one exists), `name` (operator-panel label), `kind` (`source shutter fast_shutter slit ic crl lens mono foil attenuator stage sample_stage sample_holder detector beamstop unknown`), `conf`, `src`, optional `placement` (`in_line` default, `retractable` = moved into the beam, `alt` = alternative position), `side` (`above`/`below` the beam line when drawn; default above), `near` (id of the element whose position this one shares; used for drawing, takes no slot), `tomo: true` for tomo detectors, `dev`, `pv`, `controls` (named axes -> PV or {pv, limits, readback, ...}), `state` (dated snapshot), `assembly`, `z_m` (metres from the source along the beam, or null) with `z_conf` (`confirmed`/`code`/`inferred`/`definition`) and `z_src` (where the number comes from; both required when `z_m` is set), `notes`.

## Using it

```
python beamline_twins/tools/twin.py check  1-ID    # must report 0 errors
python beamline_twins/tools/twin.py render 1-ID    # regenerate layout.md after any edit
python beamline_twins/tools/twin.py show   1-ID --kind detector
```
From Python: `sys.path.insert(0, "beamline_twins/tools"); from twin import load; load("1-ID")["path"]` (elements in beam order).

## Updating from new evidence

New photo: copy it to `sources/photos/`, add an entry to `photos.json` first, then cite its id in the elements it informs, raise `conf` only as far as the evidence goes, run `check`, `render`. Conflicts between sources: keep both in `notes`, do not silently pick one.
