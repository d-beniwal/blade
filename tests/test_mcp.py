"""MCP server test (simulator only): every registered tool is exposed, a measurement can be driven through the MCP protocol, and the real beamline is refused.
Run: python -I tests/test_mcp.py   (needs `mcp`; the registry part runs without it)"""
import asyncio, json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()      # keep test runs out of the repo's runs/
from blade import registry

tools = registry.load_modules()
assert {"new_run", "run_status", "align_adaptive", "align_measure", "align_move"} <= set(tools), set(tools)
r = registry.invoke("new_run", backend="sim")
res = registry.invoke("align_measure", omega=0)
assert "view" in res and "beam" in res, res
try:
    registry.invoke("new_run", backend="epics")
    raise SystemExit("FAIL: the real-beamline backend must be refused (read-only phase)")
except PermissionError:
    pass
print("PASS registry: new_run + align_measure on the simulator; backend 'epics' refused")
registry.invoke("vbl_reset", scenario="ready_for_pin", seed=3)
pl = registry.invoke("vbl_pin_plan")
assert pl["moves_anything"] is False and pl["frames_with_chuck"] < pl["frames_tip_only_raster"], pl
mt = registry.invoke("vbl_pin_mount")
assert 40 < mt["tip_height_above_plate_mm"] < 80 and {p["name"] for p in mt["parts"]} >= {"pin", "chuck", "rod", "nut"}, mt
fp = registry.invoke("vbl_find_pin")
assert fp["found"] and abs(fp["tip_offset_from_window_centre_mm"]) < 0.3, fp
print("PASS registry: vbl_pin_plan (read-only), vbl_pin_mount, vbl_find_pin found the pin in %d frames" % fp["frames"])
registry.invoke("vbl_reset", scenario="ready_for_pin", seed=0)                       # tomo-pin fit button: analysis only, no motor moves
from blade.vbl import store as _store
_ctl0 = dict(_store.require("default").snapshot()["controls"])
pg = registry.invoke("vbl_pin_geometry")
assert dict(_store.require("default").snapshot()["controls"]) == _ctl0, "vbl_pin_geometry must not move any control"
assert pg["recognised"] and pg["usable"] and {"top", "left_flank", "right_flank", "axis", "footprint"} <= set(pg["overlay"]), pg
assert all(0 <= v <= 1 for seg in (pg["overlay"]["top"], pg["overlay"]["axis"]) for pt in seg for v in pt), pg["overlay"]
registry.invoke("vbl_reset", scenario="startup", seed=0)
pg0 = registry.invoke("vbl_pin_geometry")
assert pg0["recognised"] is False and pg0["reasons"] or pg0["why"], pg0
print("PASS registry: vbl_pin_geometry returns the recognised pin geometry as an overlay (and a reason when no pin is recognised)")
registry.invoke("vbl_reset", scenario="ready_for_pin", seed=0)
fz = registry.invoke("vbl_centre_pin", apply=False)
assert fz["found"] and fz["moved"] is False and "proposed" in fz, fz
fz = registry.invoke("vbl_centre_pin")
assert fz["found"] and fz["converged"] and all(abs(v) <= 4.5 for v in fz["offsets_px"]["to_move_px"]), fz
registry.invoke("vbl_reset", scenario="ready_for_pin", seed=3)                       # pin only partly visible here: either fitted or refused with a reason, never guessed
registry.invoke("vbl_find_pin")
fz3 = registry.invoke("vbl_centre_pin")
assert fz3["found"] and fz3["converged"], fz3
registry.invoke("vbl_reset", scenario="startup", seed=0)                              # no beam / pin parked: nothing recognised, nothing moves
fz0 = registry.invoke("vbl_centre_pin")
assert fz0["found"] is False and fz0["moved"] is False and fz0["reason"], fz0
print("PASS registry: vbl_centre_pin (proposes with apply=False, centres a recognised pin in %d frames, refuses with a reason when no pin is recognised)" % fz["frames"])

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print("SKIP protocol test (mcp not installed)"); sys.exit(0)


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-I", str(ROOT / "launch.py"), "mcp"], env={**os.environ})
    async with stdio_client(params) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert names == set(tools), names ^ set(tools)
            pb = await s.read_resource("blade://playbook/alignment")
            assert "alignment" in str(pb).lower()
            out = await s.call_tool("new_run", {"backend": "sim"})
            assert not (getattr(out, "is_error", None) or getattr(out, "isError", None)), out
            out = await s.call_tool("align_measure", {"omega": 0})
            assert not (getattr(out, "is_error", None) or getattr(out, "isError", None)), out
            out = await s.call_tool("new_run", {"backend": "epics"})
            assert getattr(out, "is_error", None) or getattr(out, "isError", None), "epics backend must be refused"
            print("PASS protocol: %d tools, playbook resource, measurement over MCP, epics refused" % len(names))
asyncio.run(main())
print("ALL OK")
