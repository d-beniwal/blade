# BLADE knowledge base (1-ID)

Structured, searchable record of everything in the 1-ID experiment logs (2022-2026), built to (a) train/evaluate agents on real beamline
images + procedures and (b) calibrate the virtual beamline (`blade/vbl`, `sim.json`). **Code + schema live here (committed); the data does not**:
it is unpublished user records, so it sits in the **knowledge tree** outside the repo (`<knowledge root>/1-ID/kb/`, resolved by `blade/paths.py`; see the repo README "Code vs knowledge" and `python -m blade.paths`; `$BLADE_KB` / legacy `$KB_ROOT` override just this folder). Never copy it into this repo.

```
<knowledge root>/1-ID/kb/
  kb.sqlite        # everything below, one file (schema.sql)
  images/ab/<sha256>.<ext>   # every embedded log image once, content-addressed
  review/          # contact sheets for visual labelling
```

## Pipeline

1. `beamline_twins/tools/logindex.py build` extracts text/tables/params from the docx/xlsx/ods logs (single extractor) -> `logs.sqlite`.
2. `kb.py ingest` copies that text into `kb.sqlite`, pulls out every image (sha256 dedup; ~3,900 citations -> ~3,800 unique), stores pixel
   statistics + dhash, records **every citation** (doc, line, section, date, caption text before/after) and writes **rule labels**.
3. Vision/human labelling refines labels (`kb.py sheet` -> look -> `kb.py label` / `labelfile`). Labels are append-only with
   `source` (rule < vision < human), confidence, time; `label_best` / `image_index` views give the trusted value.
4. `kb.py search|show|near|export` for retrieval (FTS over captions + headings, filtered by labels) and JSONL export for training.

## Label vocabulary (extend, don't rename; add keys freely)

| key | values | meaning |
|---|---|---|
| `class` | `tomo_view` (detector frame, raw or inside a viewer window), `panel_screenshot` (EPICS/MEDM: motors, slits, scalers, calc records), `plot_or_text` (plots, terminal, tables), `photo` (lab/hutch photo), `screenshot` (other), `icon`, `unknown`, `unreadable` | what kind of image |
| `subject` | for `tomo_view`: `beam_only` (no sample, no pin), `pin`, `radiograph` (sample), `dark`, `flat`, `scintillator_focus`, `hotspot_check`, `other`; for panels: `motors`, `slits`, `scalers`, `energy_calc`, ...; for photos: `setup`, `sample_mount`, ... | what it shows |
| `pin_visible` | `yes`/`no` (tomo_view only) | the alignment pin/needle silhouette is actually in the frame; `subject=pin` requires `yes` |
| `camera` | `pg1`, `pg5`, `gh1`, `retiga2`, `pilatus`, `eiger`, `ge1-5`, `dexela`, `lambda` | detector (rule: named in nearby text) |
| `hutch` | `A` `B` `C` `E` | station |
| any other | e.g. `energy_keV`, `sample`, `slit_state` | free-form facts about the image |

Rule labels are deliberately cheap and low-confidence (0.2-0.6); `subject` from rules is only a text-keyword hint (0.3). A rule `class` was spot-checked
2026-11-12: `tomo_view` precision looked high on 2 sample sheets (36 images each, from 2024 and 2025 logs); `subject` needs the vision pass.

**Re-verification 2026-11-13 (accuracy pass).** Problems found: (1) rule `subject` keywords (text near the image, e.g. "pin diode", "rotation axis") leaked onto photos/panels/plots (38 fake `pin`, ~1,200 wrong subjects) - rule subjects are now emitted only for `tomo_view`, "pin diode" no longer matches, and the stale rows were deleted; (2) the first vision pass used 36-image thumbnails and missed pins. Fix: 1,386 candidates (all `tomo_view` + grayscale plot/screenshot/unknown images) re-read at 12 per sheet (`kb.py sheet --cols 4 --thumb 440`), each with `true_class`, `subject`, `pin_visible`, confidence. Result: 15 `tomo_view` -> non-tomo, 8 non-tomo -> `tomo_view`, pins 26 -> 39 (all 26 old confirmed, 13 added, 3 added by agents rejected/downgraded after review). Residual uncertainty: `beam_only` vs `radiograph` for mottled fields and sample-edge frames (conf 0.5-0.6), a few hooked-wire pins (conf 0.5); filter on `confidence`. Beam-profile plots with a tiny beam thumbnail stay `plot_or_text`. Backup of the pre-change DB: `kb.sqlite.bak-2026-11-13`.

## Roadmap (what makes this a knowledge base, not just an image store)

- **Vision pass**: `tomo_view` DONE 2026-11-12 (all 1,340 candidates, 8 parallel sonnet agents on fixed id lists, contact sheets; `subject` + `class_check` + `feature`; 323 turned out not to be tomo frames and are now `class=non_tomo_detector`, mostly diffraction/SAXS patterns and reconstruction slices; ~135 labels are conf<=0.5, mainly beam_only vs radiograph for mottled square fields, filter with `confidence`). Pins spot-checked: 26/26 genuine. `panel_screenshot` DONE 2026-11-12 (all 1,559; 10 parallel sonnet agents on contact sheets only, no full-size views, so `legible` is a thumbnail judgement): subject + `device` (title as written) + `hutch` + `legible` + `value_rich`. motor_panel 656, scaler_ic 198, slit_panel 173, multi_panel 178, other 151 (mostly raw detector images / ring-status pages that the pixel rules mis-called panels), detector_ctrl 54, plot_viewer 50, energy_calc 48, terminal_text 29, undulator 18, shutter_pss 4. 873 panels are legible + value_rich in the device classes (slit/motor/scaler/energy/undulator/shutter): the candidate set for value transcription. `hutch` is only set where title/caption shows it (E 392, C 85, B 51). Still to do: value TRANSCRIPTION of those panels (full-size reads -> facts table), `camera`/`hutch` for tomo views (needs the log text), `photo` subject.
- **Facts layer** (next table, same pattern: append-only, source, confidence, `doc_id:line` provenance): device states per session (slit sizes/centres,
  motor positions, energy, gap, Th2, IC rates) from text `params` and, later, from panel screenshots (OCR); alignment-sequence events; calibration results.
- **VBL relevance**: tag facts/images that constrain the simulator (`vbl_param`: which `sim.json` field they inform, `vbl_use`: calibration | validation | texture reference),
  so `sim.json` ASSUMED values can be replaced by logged evidence and rendered frames compared with real `beam_only`/`pin` views.
- **Experiments table**: one row per log (user, dates, technique, sample class, energy, detectors) for filtering.
- Embeddings (image + caption) can be added as extra columns/tables without changing the rest; `export` already gives per-image records.

`kb.py addimage FILE... key=value ... --note TEXT` registers a standalone reference image (no log citation, human labels), e.g. the CS-Studio screenshots cs01-cs06 of 2026-11-12 (class `panel_screenshot`, label `origin=reference:<file>`; same files are the twin's `sources/photos/cs0*.png`).

## Quick use

```
PY=~/miniconda3/envs/blade/bin/python
$PY knowledge_base/kb.py ingest                       # idempotent; re-run after logindex.py build
$PY knowledge_base/kb.py stats
$PY knowledge_base/kb.py search "pin AND pg5" --class tomo_view
$PY knowledge_base/kb.py sheet --class tomo_view --start 0 -n 36   # then open the printed JPEG; label with kb.py label
```

## Procedures (how things are calibrated) - added 2026-11-12

`procpack.py` ranks log sections per procedure (14 procedures: energy calibration, undulator gap, mono tuning, WB slits/steering, tomo-camera optical axis,
Kohzu slits, fast shutters, IC/preamp/flux, rotation axis, lens focusing, NF detector/beamstop, FF calibration, tomo setup/scan, beam-size/mode changes) into
~150 kB source packs; one agent per pack wrote `<KB_ROOT>/procedures/<id>.json` (goal, ordered steps with tool/signal/done_when + log|inferred evidence,
logged numbers with unit/context/era, variants, pitfalls, success criteria, open questions, vbl_relevance). `procload.py` validates (EVERY citation must
resolve to a real doc:line; steps numbered; log-evidence steps need cites) and loads into SQLite (`procedures`, `procedure_steps`, `procedure_numbers`,
`procedure_notes`, `procedure_cites`, FTS `proc_fts`). Readable copies: `<KB_ROOT>/procedures/md/<id>.md`.

```
procload.py list | show ID --md | search "undscangap" | number hotspot      # query
procpack.py build ID ; (agent writes JSON per procedures/BRIEF.md) ; procload.py check/load FILE.json   # add or refresh a procedure
```
First run: 155 steps, 743 numbers, 165 pitfalls, 81 variants, 93 distinct logs cited. Citation validity is mechanical (the line exists); content support was
spot-checked on 14 random numbers (12 clearly matched the cited line, the rest not contradicted). Known limits: packs cap sections at 6 kB and total at 150 kB
(some setup text truncated); agents viewed few images (image descriptions may come from labels only); evidence=`inferred` steps are synthesis, not logs.
Gaps the logs leave open are in each record's `open_questions` (e.g. no numeric tolerances for hotspot centring, Th2 step size, FS leakage; target pixels differ by camera/crop).

### Reconciliation with the virtual beamline (2026-11-12, partial)
Findings in `beamline_twins/1-ID/physics/10_procedure_reconciliation.md`; prepared sim.json changes in `beamline_twins/1-ID/sim_proposed_2026-11-12.json` (NOT adopted); physics-vs-logs test `tests/test_vbl_vs_logs.py`.
Headline: the undulator gap model reproduces 13 logged peak gaps (rms 16 um); the sim chose the wrong harmonic at 61/81/91 keV (fixed in the proposal: 13/13); Hf step b was 1.35 vs logged 1.15.

## Viewer in the BLADE GUI (`/kb`)

`./blade-gui kb` (or `blade gui --open --page kb`, then http://localhost:8765/kb) searches and browses everything above, read-only. Code: `blade/kb_api.py` (queries; opens
`kb.sqlite` read-only, serves images only through the `images` table), `blade/kb.html` (page), routes in `blade/gui.py`; test `tests/test_kb_gui.py` (synthetic KB, no private data).
- **Procedures:** list + full record (steps with log/inferred badge, tool, signal, done-when, logged values, variants, pitfalls, open questions, simulator relevance); search over steps/numbers/tools; "numbers only" search.
- **Images:** grid of thumbnails filtered by class / subject / camera / hutch / label source / device name / caption text; the modal shows the full image, the best label per key and the whole label history, and every log citation with its caption context.
- **Log text:** all words must appear on a line (substring match, so "hot spot" also finds "hotspot"); filter by year and kind (startup / user / tables).
- **Documents:** per-document outline.
- Every citation (`doc:L12`) anywhere opens a source drawer with the surrounding log lines, their headings and the images embedded there ("more above / below").
- Links are shareable: `/kb#tab=images&cls=tomo_view&subject=pin`, `#tab=logs&lq=hot%20spot`, `#tab=procs&id=energy_calibration&cite=<doc>:L97-99`, `#img=<sha>`.
- Data location: the `kb` folder of the knowledge tree (`python -m blade.paths`); the GUI only listens on 127.0.0.1. If the folder is missing the page says how to build it.

## Facts layer: numbers read from the panel screenshots (2026-11-13)

All 1,182 legible, value-rich `panel_screenshot` images were transcribed (53 packs of <= 25 images, one agent per pack, full-size reads, strict JSON): **33,105 readings, 94 logs, 2021-2026.**
```
PY=~/miniconda3/envs/blade/bin/python
$PY knowledge_base/facts.py build [--per 25]      # packs + BRIEF.md  -> <KB_ROOT>/facts/{packs,results}   (private, never in the repo)
$PY knowledge_base/facts.py check|load [FILE]     # strict validation (schema, value == text, conf, every image present) and load into table `facts`
$PY knowledge_base/facts.py audit-build / audit-score   # BLIND re-read of a random image per pack (labels only) and automatic scoring
$PY knowledge_base/factnorm.py build|reliability|devices|show DEV   # device parsing + TIERS A/B/C -> fact_obs, fact_dev, fact_pvmap
$PY knowledge_base/factstats.py devices|registry|baseline           # aggregated stats (tier A only) -> <KB_ROOT>/facts/analysis/
$PY knowledge_base/factphysics.py hem|gap|lens                      # fits and model checks (tier A only)
```
**Reliability rule (user 2026-11-13): a value that is not reliable is not used - not when parsing, not when analysing.** `factnorm.py` assigns every reading a tier: **A** clean (conf >= 0.9, no doubt note, legible, passed the cross-checks), **B** minor doubt (counted, never used for numbers), **C** excluded
(null, conf < 0.8, note saying guessed/assumed/inferred/unclear/covered/cursor/tooltip/differs-from-log/truncated or cropped title/no printed label, illegible image, failed cross-check). Cross-checks use the redundancy inside a window (dial-user offset agrees across readback/drive/limits, direction-aware;
readback inside limits; hi > lo; size >= 0). Every analysis function filters `tier='A'`; image-level notes and reading notes are stored in `facts` (`note`, `image_note`) and drive the flags.
First run: A 79.6 %, B 16.8 %, C 3.5 %; **blind audit 831/836 readings (99.4 %) identical**; the 5 misses are slit setpoint-vs-readback ambiguity (1 um), one digit-count slip, one cropped-title tile.
Lessons: (1) agents that stall (3 of 53 packs, all with several dense 1100x1000 multi-window screenshots) succeed when the pack is split in halves (packs 049-053 are such halves); (2) some agents wrote the JSON with a script - values were still typed from the images, and the audit found no pack-level problem; (3) agents sometimes inferred PV names / labels for cropped tiles - the brief now says "(title cropped, column N)" and those are tier C; (4) a "reversed-direction" motor has dial = c - user with swapped limits - the offset check must test both.
Results and use: `beamline_twins/1-ID/physics/12_panel_facts.md`.
