"""Image-analysis tools for the MCP server (read-only: they analyse numbers or image files, never move or connect to anything). Ported from the areaDetector
ADViewers ImageJ plugins (Gaussian_Profiler, LiveFitter_EPICSUserCalc). Read playbooks/image_analysis.md (resource blade://playbook/imganalysis)."""
from .. import config as cfg
from ..paths import ROOT
from ..registry import tool, playbook
from . import fitting, profile

playbook("imganalysis", ROOT / "playbooks" / "image_analysis.md")


def _fit(prof, model):
    f = fitting.auto(prof["x"], prof["y"]) if model == "auto" else fitting.fit(prof["x"], prof["y"], model)
    return {"profile": {k: prof[k] for k in ("unit", "pixel_um", "roi")}, "n_points": len(prof["y"]), "fit": f, "moments": fitting.moments(prof["x"], prof["y"])}


@tool("imganalysis", needs_run=False)
def analysis_list_models() -> dict:
    """List the fit models (name, parameter names, formula, ImageJ equivalent): gaussian, gaussian_nooffset, erf_edge (knife-edge/step), slit_positive / slit_negative
    (aperture = pair of erf edges, bright or dark, with tilt), polynomials line/poly2..poly8, exponentials, power, log, rodbard, gamma_variate, chapman_richards."""
    return {"models": fitting.list_models()}


@tool("imganalysis", needs_run=False)
def analysis_fit_profile(x: list[float], y: list[float], model: str = "auto") -> dict:
    """Fit a 1-D profile (e.g. a slit/motor scan against an ion chamber, or a line profile you already extracted). model: a name from analysis_list_models, or 'auto'
    (best of gaussian / erf_edge / slit_positive / slit_negative by BIC). Returns params with errors, r2, rms, derived values (FWHM, peak, background, contrast,
    slit edges/aperture/edge width) and the fitted curve; plus model-free moments. ok=False with a message if it cannot fit."""
    return {"fit": fitting.auto(x, y) if model == "auto" else fitting.fit(x, y, model), "moments": fitting.moments(x, y)}


@tool("imganalysis", needs_run=False)
def analysis_fit_roi(image_path: str, x0: float, y0: float, x1: float, y1: float, direction: str = "horizontal", model: str = "auto",
                     pixel_um: float | None = None, absolute: bool = True) -> dict:
    """Profile of a rectangular ROI of a saved frame (.npy/.npz/.h5/.png/.tif; pixel columns x, rows y, end exclusive) and its fit. direction='horizontal' averages the
    rows and runs along x (e.g. the vertical beam edges of a slit); 'vertical' averages the columns. pixel_um defaults to the active profile's PIXEL_UM; with
    absolute=True the x axis is in detector coordinates (um from the image edge), as in LiveFitter's 'Absolute Pixel Scale'. model as in analysis_fit_profile."""
    img = profile.load_image(image_path)
    return _fit(profile.rect_profile(img, x0, y0, x1, y1, direction, cfg.PIXEL_UM if pixel_um is None else pixel_um, absolute), model)


@tool("imganalysis", needs_run=False)
def analysis_fit_line(image_path: str, x0: float, y0: float, x1: float, y1: float, model: str = "auto", pixel_um: float | None = None,
                      width: int = 1, interpolate: bool = True, absolute: bool = True) -> dict:
    """Profile along a line (pixel coordinates) of a saved frame, averaged over `width` px, and its fit (see analysis_fit_roi for image formats and units)."""
    img = profile.load_image(image_path)
    return _fit(profile.line_profile(img, x0, y0, x1, y1, cfg.PIXEL_UM if pixel_um is None else pixel_um, interpolate, width, absolute), model)
