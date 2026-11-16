"""Tomo-camera datasheet info (no hardware): profiles/s1id cameras.<name>.spec is internally consistent (pitch / lens = pixel size, pixels x pixel = FOV),
every twin element with a `camera` link points at a profile camera that has a spec, the payload and the info panel carry it, and the GH1 model conflict
(user: GS3-U3-89S6M vs CS-Studio panel: 123S6M) stays an open verify item.  Run: python -I tests/test_camera_specs.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(detail)) if detail != "" else ""))
    if not cond:
        FAILS.append(name)


prof = json.loads((ROOT / "profiles/s1id/default_config.json").read_text())
cams = prof["cameras"]
for k in ("gh1", "pg1", "pg5"):
    s = cams[k]["spec"]
    pix = s["sensor_pitch_um"] / s["lens_mag"]
    check(f"{k}: pitch/lens = datasheet pixel ({pix:.4f} vs {s['pixel_um_datasheet']})", abs(pix / s["pixel_um_datasheet"] - 1) < 0.005)
    check(f"{k}: profile pixel_um within 1 % of datasheet", abs(cams[k]["pixel_um"] / s["pixel_um_datasheet"] - 1) < 0.01, cams[k]["pixel_um"])
    fov = [n * s["pixel_um_datasheet"] / 1000 for n in s["native_px"]]
    check(f"{k}: native px x pixel = FOV {fov[0]:.3f} x {fov[1]:.3f} mm", all(abs(a / b - 1) < 0.01 for a, b in zip(fov, s["fov_mm"])), s["fov_mm"])
check("slide values: gh1 89S6M 4096x2160 5x 43 fps; pg1/pg5 23S6M 1920x1200 5x 82 fps",
      cams["gh1"]["spec"]["model"].endswith("89S6M") and cams["gh1"]["spec"]["native_px"] == [4096, 2160] and cams["gh1"]["spec"]["fps_16bit"] == 43
      and all(cams[k]["spec"]["model"].endswith("23S6M") and cams[k]["spec"]["native_px"] == [1920, 1200] and cams[k]["spec"]["fps_16bit"] == 82 for k in ("pg1", "pg5")))
check("gh1 conflict with the CS-Studio panel title is recorded", "123S6M" in cams["gh1"]["spec"]["conflict"])

links = {}
for h in ("C", "E"):
    for e in json.loads((ROOT / f"beamline_twins/1-ID/hutches/{h}.json").read_text())["elements"]:
        if e.get("camera"):
            links[e["id"]] = e["camera"]
check("tomoE -> gh1, tomoC -> pg5, radiograph -> pg1", links == {"tomoE": "gh1", "tomoC": "pg5", "radiograph": "pg1"}, links)
check("every linked camera exists in the profile and has a spec", all(c in cams and cams[c].get("spec") for c in links.values()))

from blade import twin_api
pay = twin_api.twin_payload("s1id")
check("twin payload exposes the spec", pay["profile"]["cameras"]["gh1"]["spec"]["sensor"] == "Sony IMX255")
html = (ROOT / "blade/twin.html").read_text()
check("info panel has a Camera section placed after Controls", "camSec" in html and "${ctlSec}${camSec}" in html)

v = {i["id"]: i for i in json.loads((ROOT / "beamline_twins/1-ID/verify.json").read_text())["items"]}
check("gh1-pixel verified with a note (user 2026-11-15)", v["gh1-pixel"]["status"] == "verified" and "2026-11-15" in v["gh1-pixel"]["note"])
check("gh1-model stays an open item while the conflict stands", v["gh1-model"]["status"] == "unverified" and "123S6M" in v["gh1-model"]["why"])

print("camera specs " + ("OK" if not FAILS else "FAILED: %s" % FAILS))
sys.exit(1 if FAILS else 0)
