"""THE read-only gate to the real beamline's control system (EPICS channel access). Everything BLADE reads from the real machine goes through `Reader` here.

WHY IT CANNOT CHANGE ANYTHING (four independent layers; tests/test_probe_readonly.py checks each):
  1. Only ONE function (`Reader._read`) touches the network, and it only ever issues a channel-access GET (pyepics `caget`, or the EPICS `caget` command).
     There is no put, no monitor, no process request and no PVA put anywhere in this file.
  2. Every PV name must pass `validate_pv` BEFORE any read: either it is on the explicit allow-list (EXPLICIT_PVS) or it is `<record>.<FIELD>` with FIELD in
     READ_FIELDS (descriptions, readbacks, units, limits, link and calc strings, scaler counts/time). Anything else (.VAL, .PROC, .SPMG, .STOP, .TWF ... or any
     malformed name) raises ReadOnlyViolation before the device is contacted. Names are restricted to [A-Za-z0-9_:-] so nothing can be smuggled into a command line.
  3. The pyepics backend replaces every write entry point of the `epics` package with a function that raises (the TRIPWIRE block), so even a coding mistake later
     cannot write. The command-line backend runs only an executable whose file name is exactly `caget`, with a fixed argument list (no shell).
  4. Reading is not processing: a CA get never makes an EPICS record process. Image arrays are not read here (see blade/instrument/epics.py for the camera GET).
User decision 2026-11-15: BLADE does not command the real beamline - there is deliberately no write path anywhere in the package."""
import os
import re
import shutil
import subprocess
from .base import ReadOnlyError

# ---- what may be read -------------------------------------------------------------------------------------------------------------------------------------
# Fields that exist to be looked at: text description, readback (user and dial), units, soft limits, resolution, and the transform/calc record's own
# link and expression strings (INP*, CLC*, OUT*) and values (A..P).
_LETTERS = "ABCDEFGHIJKLMNOP"
READ_FIELDS = frozenset(
    ["DESC", "RBV", "DRBV", "EGU", "HLM", "LLM", "PREC", "OFF", "DIR", "NAME"]
    + [f"INP{c}" for c in _LETTERS] + [f"CLC{c}" for c in _LETTERS] + [f"OUT{c}" for c in _LETTERS] + list(_LETTERS)
    + [f"S{i}" for i in range(1, 33)] + [f"NM{i}" for i in range(1, 33)]          # scaler channel counts and names (read only)
    + ["T", "TP"])                                                                 # scaler elapsed / preset count time (read only: needed to turn counts into a rate)
# Explicit single names that are not <record>.<FIELD> (status PV, camera identity strings). Nothing else is allowed.
EXPLICIT_PVS = frozenset([
    "S01ID-PSS:SES:BeamBlockingM",
    "1idSP5:cam1:Model_RBV", "1idSP5:cam1:Manufacturer_RBV",
    "1idPG5:cam1:Model_RBV", "1idPG5:cam1:Manufacturer_RBV",
    "1idGH1:cam1:Model_RBV", "1idGH1:cam1:Manufacturer_RBV",
    "1idPG1:cam1:Model_RBV", "1idPG1:cam1:Manufacturer_RBV",
    "QIMAGE2:cam1:Model_RBV", "QIMAGE2:cam1:Manufacturer_RBV",
])
_NAME_RE = re.compile(r"^[A-Za-z0-9_:\-]+$")
_FIELD_RE = re.compile(r"^([A-Za-z0-9_:\-]+)\.([A-Z0-9]+)$")


class ReadOnlyViolation(ReadOnlyError):
    """Raised for any PV name that is not strictly a permitted read (or any attempted write)."""


class ReaderUnavailable(RuntimeError):
    """Neither pyepics nor the EPICS `caget` command could be found."""


def validate_pv(pv):
    """Return pv if it may be read, else raise ReadOnlyViolation. Called for every name before any network access."""
    if not isinstance(pv, str) or not pv or len(pv) > 80:
        raise ReadOnlyViolation(f"bad PV name {pv!r}")
    if pv in EXPLICIT_PVS:
        return pv
    m = _FIELD_RE.match(pv)
    if not m or not _NAME_RE.match(m.group(1)):
        raise ReadOnlyViolation(f"PV {pv!r} is not <record>.<FIELD> nor on the explicit allow-list")
    if m.group(2) not in READ_FIELDS:
        raise ReadOnlyViolation(f"field .{m.group(2)} of {pv!r} is not in the read-only field list")
    return pv


# ---- TRIPWIRE: disable every write entry point of the pyepics package (belt and braces; the read path below never calls any of these) ---------------------
def _disable_writes(epics_mod):
    def _refuse(*a, **k):
        raise ReadOnlyViolation("a write was attempted; this reader is read-only")
    for owner, names in ((epics_mod, ("caput", "caput_many")),
                         (getattr(epics_mod, "ca", None), ("put", "put_complete", "sg_put")),
                         (getattr(epics_mod, "PV", None), ("put",))):
        for n in names:
            if owner is not None and hasattr(owner, n):
                setattr(owner, n, _refuse)
# ---- end TRIPWIRE ------------------------------------------------------------------------------------------------------------------------------------


# ---- the ONLY place that reads from the network --------------------------------------------------------------------------------------------------------
class Reader:
    """backend 'pyepics' (epics.caget) or 'caget' (EPICS base command). Both issue a channel-access GET only."""

    def __init__(self, backend="auto", timeout=2.0):
        self.timeout = float(timeout)
        self.backend = backend
        self._epics = None
        self._exe = None
        if backend in ("auto", "pyepics"):
            try:
                import epics  # noqa: WPS433
                _disable_writes(epics)
                self._epics = epics
                self.backend = "pyepics"
            except ImportError:
                if backend == "pyepics":
                    raise ReaderUnavailable("pyepics is not installed (pip install pyepics) - or use backend caget")
        if self._epics is None:
            exe = shutil.which("caget")
            if not exe or os.path.basename(exe) != "caget":
                raise ReaderUnavailable("neither pyepics nor the EPICS 'caget' command was found")
            self._exe = exe
            self.backend = "caget"

    def _read(self, pv):
        validate_pv(pv)                                          # re-checked right at the network boundary
        if self._epics is not None:
            v = self._epics.caget(pv, as_string=True, timeout=self.timeout, use_monitor=False)
            return None if v is None else str(v)
        r = subprocess.run([self._exe, "-t", "-w", str(self.timeout), pv], capture_output=True, text=True, timeout=self.timeout + 3, shell=False)
        out = (r.stdout or "").strip()
        return out if r.returncode == 0 and out else None

    def read(self, pv):
        try:
            v = self._read(pv)
        except ReadOnlyViolation:
            raise
        except Exception as e:                                    # a timeout or a missing PV is a result, not a failure of the run
            return "error", f"{type(e).__name__}: {e}"
        return ("ok", v) if v is not None else ("no_response", "")
# ---- end of network access ---------------------------------------------------------------------------------------------------------------------------
