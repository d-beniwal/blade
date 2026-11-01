"""Profile-driven constants: the ONLY place BLADE reads beamline-specific values (pixel sizes, PVs, signs, limits, tolerances).

`load(profile)` reads profiles/<profile>/default_config.json, deep-merges the optional git-ignored active_config.json on top, and publishes the
values as module attributes (UPPER_CASE). Always read them as `cfg.NAME` at call time - never `from .config import NAME` - because loading a
different profile (or `set_camera`) updates them in place. The profile is chosen by `blade align new-run --profile`, stored in the run, or
taken from BLADE_PROFILE; the default is paths.DEFAULT_PROFILE.

Motors and sign geometry belong to a *station* (a hutch's stage arrangement), not to the beamline: profile["stations"][<name>] holds
{description, motors, geometry}. The station is chosen by `--station`, stored in the run, or BLADE_STATION; default is profile["default_station"].
Cameras stay beamline-level (each lists its hutch). A profile without "stations" (legacy) uses its top-level motors/geometry as one station."""
import json
import os
from . import paths

# station-specific (motors + geometry); taken from profile["stations"][station], see load()
_GEOMETRY = [("IMAGE_COL_PER_X", "image_col_per_x"), ("ROT_SIGN", "rot_sign"), ("IMAGE_ROW_PER_Y", "image_row_per_y"),
             ("BASE_COL_PER_BASE", "base_col_per_base")]

# (attribute, section, key) - the flat names the rest of the code uses
_FLAT = [
    ("MAX_STEP_PIN_MM", "limits", "max_step_pin_mm"), ("MAX_STEP_BASE_MM", "limits", "max_step_base_mm"),
    ("MAX_ROT_DEG", "limits", "max_rot_deg"), ("OMEGA_TOL_DEG", "limits", "omega_tol_deg"), ("MOVE_TIMEOUT_S", "limits", "move_timeout_s"),
    ("SEARCH_RADIUS_X_MM", "limits", "search_radius_x_mm"), ("SEARCH_RADIUS_Y_MM", "limits", "search_radius_y_mm"),
    ("SEARCH_STEP_FRAC", "limits", "search_step_frac"),
    ("TOL_AB_PX", "tolerances", "tol_ab_px"), ("TOL_C_PX", "tolerances", "tol_c_px"), ("BEAM_FRAC", "tolerances", "beam_frac"),
    ("NOMINAL_HALF_ANGLE_DEG", "pin", "nominal_half_angle_deg"), ("HALF_ANGLE_TOL_DEG", "pin", "half_angle_tol_deg"),
    ("PIN_MIN_CONTRAST", "pin", "min_contrast"), ("TOP_WIDTH_TOL", "pin", "top_width_tol"), ("CLIP_MARGIN_PX", "pin", "clip_margin_px"),
    ("FAST_STEPS_DEG", "procedure", "fast_steps_deg"), ("DEFAULT_SWEEP_DEG", "procedure", "default_sweep_deg"), ("SAVE_RAW", "procedure", "save_raw"),
]

PROFILE = None
STATION = None          # hutch/station whose motors + geometry are active (profile["stations"])
STATIONS = {}           # station -> {description, motors, geometry}
BEAMLINE = ""
BACKENDS = ()
CAMERA_INFO = {}        # name -> {hutch, pixel_um, pv_prefix, ...}
CAMERAS = {}            # name -> PV prefix, only cameras that have one (real backend)
CAMERA_PVA_SUFFIX = "Pva1:Image"
DEFAULT_CAMERA = None
DEFAULT_PIXEL_UM = 1.0
PIXEL_UM = DEFAULT_PIXEL_UM   # the ACTIVE camera's pixel size (um/px); see set_camera
CAMERA = None
MOTORS = {}             # role -> {pv, name, role}
MOTOR_PVS = {}          # role -> EPICS record
MOTOR_NAMES = {}        # role -> display name (e.g. samE.aerox on 1-ID)
BASE_MOTOR = "base"     # logical role of the motor that moves the rotation axis


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def profile_dir(name):
    for base in paths.PROFILES_DIRS:
        if (base / name / "default_config.json").is_file():
            return base / name
    raise ValueError(f"unknown profile '{name}'; available: {profiles()}")


def profiles():
    names = set()
    for base in paths.PROFILES_DIRS:
        if base.is_dir():
            names |= {p.name for p in base.iterdir() if (p / "default_config.json").is_file()}
    return sorted(names)


def load(profile=None, station=None):
    """Load a profile into this module's attributes. Returns the merged profile dict."""
    global PROFILE, STATION, STATIONS, BEAMLINE, BACKENDS, CAMERA_INFO, CAMERAS, CAMERA_PVA_SUFFIX, DEFAULT_CAMERA, DEFAULT_PIXEL_UM, MOTORS, MOTOR_PVS, MOTOR_NAMES
    name = profile or os.environ.get("BLADE_PROFILE") or paths.DEFAULT_PROFILE
    d = profile_dir(name)
    prof = json.loads((d / "default_config.json").read_text())
    if (d / "active_config.json").is_file():
        _merge(prof, json.loads((d / "active_config.json").read_text()))
    if prof.get("stations") and ("motors" in prof or "geometry" in prof):
        raise ValueError(f"profile '{name}': top-level motors/geometry are ignored when 'stations' exists; move them under stations.<hutch> "
                         f"(check active_config.json)")
    stations = prof.get("stations") or {"default": {"motors": prof["motors"], "geometry": prof["geometry"]}}
    sname = station or os.environ.get("BLADE_STATION") or prof.get("default_station") or next(iter(stations))
    if sname not in stations:
        raise ValueError(f"unknown station '{sname}' in profile '{name}'; available: {sorted(stations)}")
    g = globals()
    for attr, key in _GEOMETRY:
        g[attr] = stations[sname]["geometry"][key]
    STATION, STATIONS = sname, stations
    for attr, sec, key in _FLAT:
        g[attr] = tuple(prof[sec][key]) if isinstance(prof[sec][key], list) else prof[sec][key]
    PROFILE, BEAMLINE, BACKENDS = name, prof.get("beamline", name), tuple(prof.get("backends", ("sim",)))
    CAMERA_INFO = prof["cameras"]
    CAMERAS = {k: v["pv_prefix"] for k, v in CAMERA_INFO.items() if v.get("pv_prefix")}
    CAMERA_PVA_SUFFIX = prof.get("camera_pva_suffix", "Pva1:Image")
    DEFAULT_CAMERA, DEFAULT_PIXEL_UM = prof.get("default_camera"), prof.get("default_pixel_um", 1.0)
    MOTORS = stations[sname]["motors"]
    MOTOR_PVS = {k: v["pv"] for k, v in MOTORS.items() if v.get("pv")}
    MOTOR_NAMES = {k: v.get("name", k) for k, v in MOTORS.items()}
    set_camera(None)
    return prof


def set_camera(name):
    """Select the active camera: sets PIXEL_UM (always read it as cfg.PIXEL_UM). None -> DEFAULT_PIXEL_UM."""
    global PIXEL_UM, CAMERA
    if name is None:
        CAMERA, PIXEL_UM = None, DEFAULT_PIXEL_UM
        return PIXEL_UM
    if name not in CAMERA_INFO:
        raise ValueError(f"unknown camera '{name}' in profile '{PROFILE}'; choose from {sorted(CAMERA_INFO)}")
    CAMERA, PIXEL_UM = name, CAMERA_INFO[name]["pixel_um"]
    return PIXEL_UM


def px_to_mm(px, pixel_um=None):
    return px * (PIXEL_UM if pixel_um is None else pixel_um) * 1e-3


def mm_to_px(mm, pixel_um=None):
    return mm * 1e3 / (PIXEL_UM if pixel_um is None else pixel_um)


load()
