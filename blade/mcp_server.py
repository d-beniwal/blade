"""BLADE MCP server (`blade mcp`): the way other agents reach BLADE workflows. Everything registered in blade.registry becomes an MCP tool; each module's
playbook is served as the resource blade://playbook/<module>. Transport: stdio (default) or streamable-http. Needs the optional dependency `mcp` (pip install -e .[mcp]).

Safety: there is no way to reach hardware: `new_run(backend='epics')` is refused and the real-beamline reader is read-only."""
import inspect
from . import registry

INSTRUCTIONS = """BLADE - Beamline Automation and Device Experiments (APS). BLADE builds a virtual beamline (simulator) of the real one; everything it does is SIMULATION or READ-ONLY:
it never commands the real beamline (user decision 2026-11-15). Workflow: 1) read the playbook resource for the module you are using (blade://playbook/<module>);
2) the vbl_* tools drive the simulated beamline (set controls, read ICs, take frames, run the operator scans); new_run + align_* tools run the rotation-axis
alignment on the simulator; analysis_* tools fit profiles/images; loop_* tools compare the simulator with a read-only snapshot of the real beamline and propose
changes (they never apply them to the real machine). Explain your steps with add_note; finish_run when done. The user can watch in `blade gui`."""


def _wrap(t):
    """Expose a registry tool to MCP: same signature minus `run`, plus an optional run_id."""
    params = [p for p in inspect.signature(t.fn).parameters.values() if p.name != "run"]
    if t.needs_run:
        params.append(inspect.Parameter("run_id", inspect.Parameter.KEYWORD_ONLY, default=None, annotation="str | None"))
    sig = inspect.Signature(params, return_annotation=dict)

    def call(**kw):
        return registry.invoke(t.name, **kw)
    call.__name__, call.__doc__, call.__signature__ = t.name, t.doc, sig
    call.__annotations__ = {p.name: p.annotation for p in params} | {"return": dict}
    return call


def build():
    try:
        from mcp.server.mcpserver import MCPServer as Server          # mcp >= 2
        v2 = True
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server               # mcp 1.x
        v2 = False
    from mcp.types import ToolAnnotations
    server = Server("blade", instructions=INSTRUCTIONS)
    for t in registry.load_modules().values():
        ann = ToolAnnotations(readOnlyHint=not t.moves, destructiveHint=False, openWorldHint=t.moves)
        server.tool(name=t.name, description=f"[{t.module}{', MOVES MOTORS' if t.moves else ''}] {t.doc}", annotations=ann)(_wrap(t))
    for module, path in registry.PLAYBOOKS.items():
        read = (lambda p: (lambda: p.read_text()))(path)   # no parameters: the URI has no template variables
        read.__name__ = f"playbook_{module}"
        server.resource(f"blade://playbook/{module}", name=f"{module} playbook", mime_type="text/markdown",
                        description=f"Step-by-step procedure for the {module} module; read before using its tools.")(read)
    return server


def serve(transport="stdio", **kw):
    build().run(transport=transport, **kw)
