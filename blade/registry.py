"""Capability registry: the ONE place a BLADE capability is declared so that agents can reach it through the MCP server (`blade mcp`).

Every module (blade/<module>/tools.py) declares its tools with `@tool(...)` and its playbook with `playbook(...)`; `blade/mcp_server.py` turns whatever is
registered here into MCP tools/resources, so a new capability is available to agents as soon as its tools.py is listed in MODULES. This file has no MCP
dependency (tests and the CLI can call `invoke` directly).

A tool is a plain function `fn(run, **args) -> dict` (or `fn(**args)` with needs_run=False). `run` is the Run selected by the optional `run_id` argument
(default: the current run). The docstring is what the agent reads as the tool description, so state what it does, what it returns, and any safety rule.
`moves=True` marks tools that can move hardware (exposed as such to the MCP client). Results are JSON-normalised and saved in the run's outputs/ folder."""
import importlib
import json
import threading
from dataclasses import dataclass
from typing import Callable

MODULES = ["core", "alignment", "vbl"]     # blade.<name>.tools (core: blade/core_tools.py) - add a new capability module here

TOOLS = {}          # name -> Tool
PLAYBOOKS = {}      # module -> Path of its playbook (markdown)
_LOCK = threading.RLock()   # one hardware/run operation at a time; cfg is process-global


@dataclass
class Tool:
    name: str
    module: str
    fn: Callable
    moves: bool
    needs_run: bool

    @property
    def doc(self):
        return (self.fn.__doc__ or self.name).strip()


def tool(module, name=None, moves=False, needs_run=True):
    def deco(fn):
        n = name or fn.__name__
        if n in TOOLS:
            raise ValueError(f"duplicate BLADE tool '{n}'")
        TOOLS[n] = Tool(n, module, fn, moves, needs_run)
        return fn
    return deco


def playbook(module, path):
    PLAYBOOKS[module] = path


def load_modules():
    for m in MODULES:
        importlib.import_module("blade.core_tools" if m == "core" else f"blade.{m}.tools")
    return TOOLS


def invoke(name, run_id=None, **kw):
    """Run a registered tool and return its JSON-safe result (saved to the run's outputs/ when the tool uses a run)."""
    load_modules()
    t = TOOLS[name]
    with _LOCK:
        if not t.needs_run:
            return _json(t.fn(**kw))
        from .session import Run
        run = Run.current(run_id)
        res = _json(t.fn(run, **kw))
        run.save_output(name, res)
        return res


def _json(obj):
    return json.loads(json.dumps(obj, default=float))
