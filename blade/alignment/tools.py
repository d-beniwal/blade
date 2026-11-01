"""Alignment module tools for the MCP server (rotation axis onto the beam). Thin wrappers over the do_* functions in alignment/cli.py - the same logic
the `blade align` CLI runs. Read playbooks/alignment.md (also served as the MCP resource blade://playbook/alignment) before driving them."""
from ..paths import ROOT
from ..registry import tool, playbook
from . import cli as C

playbook("alignment", ROOT / "playbooks" / "alignment.md")


@tool("alignment", moves=True)
def align_goto_omega(run, deg: float) -> dict:
    """Rotate the stage to omega=deg (refused beyond the profile's max rotation, normally +-90)."""
    C.goto_omega(run, deg)
    return {"omega": deg}


@tool("alignment", moves=True)
def align_measure(run, omega: float | None = None) -> dict:
    """Acquire one frame (optionally after rotating to `omega`) and measure the pin and beam centre. Returns pin column, view state and quality."""
    return C.do_measure(run, omega)


@tool("alignment", moves=True)
def align_sweep(run, angles: list[float] | None = None) -> dict:
    """Measure at several omega angles (default: the profile's sweep) and fit the pin trajectory: a, b, c and the beam centre, in pixels."""
    from .. import config as cfg
    return C.do_sweep(run, angles or list(cfg.DEFAULT_SWEEP_DEG))


@tool("alignment")
def align_propose(run) -> dict:
    """From the last sweep fit, propose the z, x and base moves (mm) that would align the axis. Moves nothing."""
    return C.do_propose(run)


@tool("alignment", moves=True)
def align_adaptive(run, step: float = 15.0, max_passes: int = 6) -> dict:
    """STANDARD alignment routine: rotate until the pin leaves the view on each side, fit, correct (z, x, base), repeat until within tolerance. Moves motors."""
    return C.do_adaptive_align(run, step, max_passes)


@tool("alignment", moves=True)
def align_fast(run, verify: bool = True) -> dict:
    """Quick alignment using the profile's fast steps (e.g. 30/90 deg) with an optional verification sweep. Moves motors."""
    return C.do_fast_align(run, verify)


@tool("alignment", moves=True)
def align_step_pm(run, theta: float, apply: bool = False, base: bool = False, force: bool = False) -> dict:
    """Estimate a, b from the pin at 0 and +-theta; with apply=True also move z and x (and the base motor if base=True, sensible for theta>=60)."""
    return C.do_step_pm(run, theta, apply, base, force)


@tool("alignment", moves=True)
def align_find_pin(run, max_steps: int = 60, use_y: bool = True) -> dict:
    """Spiral-search with x (and y) until the pin is found in view. Moves motors within the profile's search radius."""
    return C.do_find_pin(run, max_steps, use_y)


@tool("alignment", moves=True)
def align_move(run, motor: str, mm: float, reason: str = "") -> dict:
    """Move one motor role (x, y, z or base) by `mm`. Refused above the profile's per-step limit; verified against the readback."""
    return C.do_move(run, motor, mm, reason)


@tool("alignment", moves=True)
def align_calibrate(run, motor: str, mm: float, undo: bool = True) -> dict:
    """Measure the image response of a motor to a small move of `mm` (and move it back when undo=True) to check sign and scale."""
    return C.do_calibrate(run, motor, mm, undo)
