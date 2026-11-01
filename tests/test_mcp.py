"""MCP server test (simulator only): every registered tool is exposed, and a full alignment can be driven through the MCP protocol.
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
res = registry.invoke("align_adaptive")
assert res.get("ok") is not False, res
print("PASS registry: adaptive alignment via invoke -> ok, converged:", res["final"]["converged"])

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
            out = await s.call_tool("align_adaptive", {})
            assert not (getattr(out, "is_error", None) or getattr(out, "isError", None)), out
            print("PASS protocol: %d tools, playbook resource, adaptive alignment over MCP" % len(names))
asyncio.run(main())
print("ALL OK")
