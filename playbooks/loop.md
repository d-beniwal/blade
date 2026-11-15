# BLADE loop playbook - read the beamline, simulate, propose (no commanding)

**Safety first.** BLADE does not command the real beamline: there is no write path in the code (`blade/instrument/readonly.py` is the only gate to EPICS; `EpicsReader.set` always raises;
tests scan the source for any put/monitor/process). The loop *proposes*; a person applies. Everything below is a read, a file operation or a simulation.

## The cycle
1. **Read** - `loop_status` shows what BLADE can see. `loop_real_snapshot` (only when the user is on the beamline network and wants a read) does channel-access GETs of every mapped PV and
   ion chamber (+ optionally one camera frame) and saves a snapshot. Controls enter the simulator **only** through `beamline_twins/<bl>/control_pv_map.json` entries with
   `status: "verified"` and numeric `scale`/`offset` (sim = scale*raw + offset). Everything else is listed with the reason - never guessed (user rule: no guessed assignments).
2. **Sync** - the simulator takes the usable control values as state. Assumption (reported): the mono is thermally settled.
3. **Estimate** - hidden quantities (energy offset Th1, gap error, Th2 detuning, steering) are fitted so the simulator reproduces observations: an operator's E scan / gap scan / Th2 scan,
   or a camera frame (beam centroid vs footprint). `loop_propose(..., scans=[...], estimate=[...])`. A parameter the data do not identify is reported and not applied.
   Identifiability: gap + Th1 are degenerate in a gap scan alone (the peak depends on the real energy) - give the E scan too.
4. **Propose** - a procedure (`tune_energy_flux`, `gap_scan`, ...) runs on a copy of the synced model; the control changes it made are the proposal (with `real_display` where the mapping is verified;
   `und.gap` must be approached from the open side - the proposal says so).
5. A person applies the proposal on the beamline; go to 1.

## Try it without touching anything
`loop_dry_run` runs the whole cycle on a stand-in beamline (a simulator with its own hidden truth): typically the stand-in's score drops from ~17 to ~2 (flux 0.997 of best).

## Verifying the mapping (the step that unlocks real syncing)
Run `beamline_twins/tools/probe_readonly.py --run --group samc,...` (reads descriptions/readbacks/limits), then `loop_mapping_evidence <csv>`: it compares motor soft limits with the simulator's
and proposes `scale/offset`. Confirm with ONE live readback against the panel, then edit `control_pv_map.json` (status, scale, offset, note) and update `verify.json`.
