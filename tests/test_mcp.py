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
