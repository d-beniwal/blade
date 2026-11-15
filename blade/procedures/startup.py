"""The start-of-beamtime sequence as one executable record of the logbook procedure (interface: blade/instrument/base.py).
Order (25 user logs; playbooks/virtual_beamline.md, beamline_twins/1-ID/physics/09_alignment_procedure.md):
  energy + flux: gap scan -> Th2 -> foil edge scan -> energy so that mu_t = b -> Th2/gap again; beam on the tomo camera -> steering vs the WB-slit image ->
  Kohzu slits centred on the hotspot (closed to 0.1 mm) -> camera focus."""
from ..physics import core as pcore
from ..vbl.world import SLIT_IDS, FS_IDS
from ._util import accepts_world
from .energy import open_gap, nominal_gap, gap_scan, th2_scan, calibrate_energy
from .camera import tune_exposure, find_beam_on_camera, centre_camera_on_beam, steering_check
from .optics import focus_camera
from .slits import align_fast_shutter, align_slit


@accepts_world
def startup_sequence(inst, element="Re", cam="gh1", log=None, align_slits=("slitEus", "slitEds")):
    """The start-of-beamtime sequence on the virtual beamline, as an executable record of the logbook procedure. Returns the list of step results.
    Uses only observables; the final score comes from readiness()."""
    steps = []
    say = lambda name, res: (steps.append({"step": name, **({"result": res} if res is not None else {})}), log and log(name))
    cc = inst.sim["cameras"][cam]
    st = cc["stage"]
    # 1 settings: open downstream slits, remove attenuators/foil
    for sid in SLIT_IDS[1:]:
        inst.set(f"{sid}.hsize", max(inst.ctl(f"{sid}.hsize"), 3.0))
        inst.set(f"{sid}.vsize", max(inst.ctl(f"{sid}.vsize"), 3.0))
    inst.set("foilB.pos", "out")
    inst.set("attenB.pos", 0)
    inst.set("attenC.pos", 0)
    say("open downstream slits 3x3 mm (the logs say 2x2 or wider), foil and attenuators out", None)
    for fs in FS_IDS:
        say(f"align fast shutter {fs} on the beam (IC plateau)", align_fast_shutter(inst, fs))
    # 2 energy readout at the edge, nominal gap
    e_edge = pcore.edge_keV(element)
    inst.set("hem.energy", float(round(e_edge, 3)))
    g = nominal_gap(inst)
    open_gap(inst, g["gap_mm"])
    inst.set("und.gap", g["gap_mm"])
    say("HEM at the foil edge energy, undulator at the nominal gap", g)
    # 3 gap scan
    say("gap scan (wide)", gap_scan(inst, inst.ctl("und.gap"), 0.30, 61, "icB1"))
    # 4 Th2 tweak, gap again
    say("Th2 scan", th2_scan(inst, 0.006, 31, "icB1"))
    say("gap scan (fine)", gap_scan(inst, inst.ctl("und.gap"), 0.10, 41, "icB1"))
    # 5 energy calibration on the foil edge
    cal = calibrate_energy(inst, element)
    say("energy calibration (E_scan, Th1 offset so that mu_t = b)", cal)
    say("Th2 scan after the energy change", th2_scan(inst, 0.004, 21, "icB1"))
    say("gap scan after Th2", gap_scan(inst, inst.ctl("und.gap"), 0.06, 31, "icB1"))
    cal = calibrate_energy(inst, element)
    say("energy re-check (mu_t)", cal)
    # 6 camera into the beam, then steering (hotspot vs WB-slit image) before the final flux optimisation
    fb = find_beam_on_camera(inst, cam, half_range_mm=3.5)
    say("bring the tomo camera into the beam", {k: v for k, v in fb.items() if k != "analysis"})
    if fb.get("found"):
        say("centre the camera on the beam", {k: v for k, v in centre_camera_on_beam(inst, cam, "footprint").items() if k != "analysis"})
        say("focus the camera", focus_camera(inst, cam))
        p_mm = inst.cams[cam]["pixel_um"] * 1e-3
        for it in range(8):
            sc = steering_check(inst, cam)
            if not sc.get("ok"):
                break
            off = max(abs(sc["hotspot_minus_footprint_px"]["h"]), abs(sc["hotspot_minus_footprint_px"]["v"]))
            if off < 12.0:
                break
            s = sc["suggested_steering_urad"]
            inst.set("steer.xp", inst.ctl("steer.xp") + 0.9 * s["xp"])
            inst.set("steer.yp", inst.ctl("steer.yp") + 0.9 * s["yp"])
            for fs in FS_IDS:                    # the beam moved: a fast shutter that was centred before may now clip it (the logs re-centre FS after steering)
                align_fast_shutter(inst, fs)
            centre_camera_on_beam(inst, cam, "footprint")
        for fs in FS_IDS:
            align_fast_shutter(inst, fs)
        say("steering vs the WB-slit image", steering_check(inst, cam))
        say("re-centre the camera on the hotspot", {k: v for k, v in centre_camera_on_beam(inst, cam, "hotspot").items() if k != "analysis"})
        say("exposure re-tuned", tune_exposure(inst, cam))
        say("gap scan after steering", gap_scan(inst, inst.ctl("und.gap"), 0.10, 41, "icB1"))
        say("Th2 scan after steering", th2_scan(inst, 0.004, 21, "icB1"))
        say("energy re-check", calibrate_energy(inst, element))
        say("exposure re-tuned (flux is now optimal)", tune_exposure(inst, cam))
        # 7 slits
        for sl in align_slits:
            say(f"align {sl} on the hotspot (closed to 0.1 mm, tomo image)", align_slit(inst, sl, cam))
    return steps
