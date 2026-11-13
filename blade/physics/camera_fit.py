"""Fitted detector / image-formation models for the 1-ID virtual beamline (numpy + stdlib only).

Constants come from beamline_twins/1-ID/physics/fits/camera.json when that file is found, else from the embedded `_FALLBACK` (identical subset, checked by tests).
Every fit is documented in that JSON and in camera.md with its sample size and residuals; assumptions are marked ASSUMED.  Units: um, mm, keV, degrees unless stated.

VALIDITY (read before using)
  * pixel sizes: logged 2022-2026; PG1 has TWO eras (5X 1.172 um/px, 7.5X 0.781 um/px from Nov 2024).
  * pin geometry: two pin families (B: 104.5 um top / 7.8 deg, A: ~180 um top / 14.8 deg); n=11 frames.
  * texture / edge / dust: measured on 8-bit viewer screenshots (display-stretched, viewer scale 0.5-1.5): lengths and widths trustworthy to ~30 %, amplitudes are upper bounds.
  * scintillator, lens NA, PSF blur: ASSUMED (no data in the logs).
"""
import json
import math
from pathlib import Path
import numpy as np

_JSON = Path(__file__).resolve().parent.parent.parent / "beamline_twins" / "1-ID" / "physics" / "fits" / "camera.json"

_FALLBACK = {'pixel_rows': [{'id': 'pg1_5x', 'sensor_pitch_um': 5.86, 'magnification': 5, 'pixel_um_model': 1.172, 'pixel_um_logged': [1.172]},
                {'id': 'pg1_7p5x', 'sensor_pitch_um': 5.86, 'magnification': 7.5, 'pixel_um_model': 0.78133, 'pixel_um_logged': [0.781, 0.78125]},
                {'id': 'pg5_5x', 'sensor_pitch_um': 5.86, 'magnification': 5, 'pixel_um_model': 1.172, 'pixel_um_logged': [1.17, '?1.172']},
                {'id': 'gh1_5x', 'sensor_pitch_um': 3.45, 'magnification': 5, 'pixel_um_model': 0.69, 'pixel_um_logged': [0.69, 0.7]},
                {'id': 'retiga_5x_E', 'sensor_pitch_um': 7.4, 'magnification': 5, 'pixel_um_model': 1.48, 'pixel_um_logged': [1.48, 1.5]},
                {'id': 'retiga_7p5x_B', 'sensor_pitch_um': 7.4, 'magnification': 7.5, 'pixel_um_model': 0.9867, 'pixel_um_logged': [1.0]}],
 'pin': {'top_width_um': 104.5, 'half_angle_deg': 7.8, 'alt_wide_pin': {'top_width_um': 180.0, 'half_angle_deg': 14.8}},
 'pin_A': {'half_angle_deg': {'mean': 14.77, 'sd': 0.25, 'min': 14.25, 'max': 15.13, 'n': 8},
           'top_width_um': {'mean': 179.86, 'sd': 37.84, 'min': 135.2, 'max': 220.2, 'n': 7},
           'n_frames': 8,
           'n_logs': 3},
 'pin_B': {'half_angle_deg': {'mean': 7.79, 'sd': 0.06, 'min': 7.75, 'max': 7.86, 'n': 3},
           'top_width_um': {'mean': 105.97, 'sd': 1.45, 'min': 104.3, 'max': 106.9, 'n': 3},
           'n_frames': 3,
           'n_logs': 1},
 'texture': {'corr_len_um': 26,
             'corr_len_um_iqr': [16, 50],
             'rms_rel': 0.09,
             'rms_rel_mottled': 0.17,
             'psd_slope': -2.45,
             'acf_form': 'exponential (A~0.8)',
             'action': 'VBL texture: correlation lengths ~0.37x and rms ~0.27x of the current beam_texture; real frames are streakier (slit-edge / '
                       'window fringes), not blobby',
             'corr_len_um_bias_corrected': 32,
             'bias_note': 'the radial-ACF estimator (windowed, boxes 0.3-0.9 mm = 12-35 l) underestimates the true 1/e length by 15-30 % (tested on '
                          'synthetic fields, camera_fit.fit_acf_length_um): true length probably ~32 um; the sim estimate (2 mm field) is biased by '
                          '~10 %, so the sim blobs are ~2-2.5x too long'},
 'edges': {'pg_all': {'n': 63, 'median': 38.3, 'q25': 19.6, 'q75': 54.2, 'min': 9.9},
           'pg_LR': {'n': 20, 'median': 31.9, 'q25': 22.9, 'q75': 42.2, 'min': 11.5},
           'pg_TB': {'n': 43, 'median': 47.7, 'q25': 16.9, 'q75': 56.2, 'min': 9.9},
           'gh1_all': {'n': 15, 'median': 19.1, 'q25': 15.3, 'q75': 29.9, 'min': 8.2}},
 'dust': {'pg': {'n_frames': 38,
                 'density_per_mm2': {'median': 28.7, 'q25': 18.5, 'q75': 49.8},
                 'equiv_diameter_um_median': 3.9,
                 'equiv_diameter_um_p90': 8.9},
          'gh1': {'n_frames': 7,
                  'density_per_mm2': {'median': 28.5, 'q25': 7.5, 'q75': 70.8},
                  'equiv_diameter_um_median': 3.7,
                  'equiv_diameter_um_p90': 5.1}},
 'nf': {'2022 (user log) step table': {'points': [[5, 0.03], [6, 0.03], [7, 0.03], [8, 0.03], [9, 0.03], [10, 0.04]],
                                       'slope_um_per_mm': 1.43,
                                       'intercept_mm': 0.021,
                                       'rms_resid_um': 2.82},
        '2022 (user log) commands': {'points': [[9, 0.04], [10, 0.045]], 'slope_um_per_mm': 5.0, 'intercept_mm': None, 'rms_resid_um': 0.0},
        '2023 table a (user log)': {'points': [[5, 0.023], [7, 0.027], [9, 0.033], [11, 0.039], [13, 0.045]],
                                    'slope_um_per_mm': 2.8,
                                    'intercept_mm': 0.0082,
                                    'rms_resid_um': 0.57},
        '2023 table b (user log)': {'points': [[5, 0.025], [8, 0.03], [11, 0.04], [14, 0.05]],
                                    'slope_um_per_mm': 2.83,
                                    'intercept_mm': 0.0093,
                                    'rms_resid_um': 1.37},
        '2025 (user log)': {'points': [[6, 0.025], [7.5, 0.03], [9, 0.035], [11, 0.05], [13, 0.055]],
                            'slope_um_per_mm': 4.59,
                            'intercept_mm': -0.0037,
                            'rms_resid_um': 2.0}},
 'nf_pooled': {'slope_um_per_mm': 3.31,
               'intercept_mm': 0.0056,
               'rms_resid_um': 3.35,
               'n_points': 14,
               'note': 'per-session slopes 1.4 (quantised 2022 step table), 2.8, 2.8 (2023), 4.6 (2025), 5.0 (2022 two-point): the beam-stop shadow '
                       'moves 3-5 um per mm of DetZ (3-5 mrad between the NF stage axis and the beam); BBY is quoted to 5 um so a slope is good to '
                       '~0.5 um/mm; intercepts differ by 10-20 um between sessions. The ~5 um/mm of the task brief is the top of the range.'},
 'scint': {'LuAG': {'rho': 6.73,
                    'E': [30,
                          35,
                          40,
                          45,
                          50,
                          52,
                          55,
                          58,
                          60,
                          62,
                          63,
                          63.4,
                          64,
                          66,
                          68,
                          69.4,
                          69.6,
                          70,
                          71.676,
                          75,
                          78,
                          80,
                          85,
                          90,
                          95,
                          100,
                          105,
                          110],
                    'mu_per_cm': [85.7,
                                  57.081,
                                  40.28,
                                  29.643,
                                  22.61,
                                  20.45,
                                  17.734,
                                  15.515,
                                  14.256,
                                  13.141,
                                  12.632,
                                  54.51,
                                  53.215,
                                  49.199,
                                  45.596,
                                  43.292,
                                  42.976,
                                  42.354,
                                  39.881,
                                  35.541,
                                  32.172,
                                  30.169,
                                  25.866,
                                  22.375,
                                  19.512,
                                  17.139,
                                  15.155,
                                  13.484]},
           'YAG': {'rho': 4.55,
                   'E': [30, 35, 40, 45, 50, 52, 55, 58, 60, 62, 63, 63.4, 64, 66, 68, 69.4, 69.6, 70, 71.676, 75, 78, 80, 85, 90, 95, 100, 105, 110],
                   'mu_per_cm': [49.375,
                                 32.579,
                                 22.728,
                                 16.55,
                                 12.478,
                                 11.239,
                                 9.686,
                                 8.422,
                                 7.708,
                                 7.079,
                                 6.792,
                                 6.682,
                                 6.522,
                                 6.028,
                                 5.588,
                                 5.307,
                                 5.269,
                                 5.194,
                                 4.895,
                                 4.376,
                                 3.977,
                                 3.742,
                                 3.242,
                                 2.842,
                                 2.519,
                                 2.254,
                                 2.035,
                                 1.852]},
           'LSO': {'rho': 7.4,
                   'E': [30, 35, 40, 45, 50, 52, 55, 58, 60, 62, 63, 63.4, 64, 66, 68, 69.4, 69.6, 70, 71.676, 75, 78, 80, 85, 90, 95, 100, 105, 110],
                   'mu_per_cm': [115.552,
                                 76.903,
                                 54.204,
                                 39.829,
                                 30.323,
                                 27.403,
                                 23.731,
                                 20.731,
                                 19.029,
                                 17.521,
                                 16.833,
                                 73.927,
                                 72.165,
                                 66.7,
                                 61.797,
                                 58.661,
                                 58.232,
                                 57.385,
                                 54.02,
                                 48.116,
                                 43.531,
                                 40.806,
                                 34.951,
                                 30.203,
                                 26.307,
                                 23.08,
                                 20.383,
                                 18.11]},
           'CsI': {'rho': 4.51,
                   'E': [30, 35, 40, 45, 50, 52, 55, 58, 60, 62, 63, 63.4, 64, 66, 68, 69.4, 69.6, 70, 71.676, 75, 78, 80, 85, 90, 95, 100, 105, 110],
                   'mu_per_cm': [40.8,
                                 83.277,
                                 103.593,
                                 76.385,
                                 58.054,
                                 52.343,
                                 45.087,
                                 39.118,
                                 35.725,
                                 32.725,
                                 31.355,
                                 30.83,
                                 30.064,
                                 27.692,
                                 25.572,
                                 24.219,
                                 24.034,
                                 23.669,
                                 22.223,
                                 19.694,
                                 17.74,
                                 16.584,
                                 14.112,
                                 12.124,
                                 10.508,
                                 9.179,
                                 8.078,
                                 7.158]},
           'GOS': {'rho': 7.32,
                   'E': [30, 35, 40, 45, 50, 52, 55, 58, 60, 62, 63, 63.4, 64, 66, 68, 69.4, 69.6, 70, 71.676, 75, 78, 80, 85, 90, 95, 100, 105, 110],
                   'mu_per_cm': [91.797,
                                 60.91,
                                 42.851,
                                 31.47,
                                 23.967,
                                 104.07,
                                 89.981,
                                 78.421,
                                 71.84,
                                 66.004,
                                 63.333,
                                 62.307,
                                 60.81,
                                 56.167,
                                 52.002,
                                 49.337,
                                 48.972,
                                 48.253,
                                 45.392,
                                 40.373,
                                 36.476,
                                 34.159,
                                 29.181,
                                 25.15,
                                 21.852,
                                 19.129,
                                 16.862,
                                 14.958]},
           'W': {'rho': 19.3,
                 'E': [30, 35, 40, 45, 50, 52, 55, 58, 60, 62, 63, 63.4, 64, 66, 68, 69.4, 69.6, 70, 71.676, 75, 78, 80, 85, 90, 95, 100, 105, 110],
                 'mu_per_cm': [438.719,
                               292.161,
                               205.89,
                               151.12,
                               114.844,
                               103.684,
                               89.643,
                               78.167,
                               71.654,
                               65.874,
                               63.233,
                               62.22,
                               60.743,
                               56.17,
                               52.081,
                               49.471,
                               216.182,
                               212.977,
                               200.246,
                               178.0,
                               160.847,
                               150.718,
                               129.134,
                               111.744,
                               97.488,
                               85.627,
                               75.647,
                               67.186]}},
 'spreads': {'omega_zero_error_deg': [0.028, 0.001, 0.009, 0.0277, 0.019, 0.6202],
             'wedge_deg': [0.0675, 0.00056, 0.0003, 0.00124, 0.01, 0.00197, 0.00667, 0.002, 0.01, 0.004, 0.015],
             'camera_or_axis_tilt_deg': [0.473, 0.1427, 0.0079, 0.263, 0.346, 0.43]},
 'pin_edge_A': {'median': 23.9, 'q25': 19.9, 'q75': 25.6, 'n': 14},
 'ceo2': [{'src': '2024-AMsetup_nov24_explog:93',
           'energy_keV': 61.31418,
           'distance_mm': 800.169,
           'beam_centre_px': [733.268, 856.272],
           'beam_centre_mm': [126.122, 147.279],
           'tilt_deg': -0.12},
          {'src': '2024-AMsetup_nov24_explog:315',
           'energy_keV': 61.31457,
           'distance_mm': 765.894,
           'beam_centre_px': [731.091, 854.494],
           'beam_centre_mm': [125.748, 146.973],
           'tilt_deg': 0.463},
          {'src': '2024-AMsetup_nov24_explog:317',
           'energy_keV': 61.31457,
           'distance_mm': 765.93,
           'beam_centre_px': [731.317, 854.648],
           'beam_centre_mm': [125.786, 146.999],
           'tilt_deg': 0.354}]}


def _load():
    try:
        d = json.loads(_JSON.read_text())
        return {
            "pixel_rows": d["pixel_size"]["rows"],
            "pin": d["pin"]["recommended"], "pin_A": d["pin"]["group_A"], "pin_B": d["pin"]["group_B"],
            "texture": d["texture"]["recommended"], "edges": {k: d["slit_edges"][k] for k in ("pg_all", "pg_LR", "pg_TB", "gh1_all")},
            "dust": d["dust"]["by_camera"], "nf": d["nf_bby_vs_detz"]["series"], "nf_pooled": d["nf_bby_vs_detz"]["pooled_2023_2025"],
            "scint": d["scintillator"]["tables"], "spreads": {k: v["values"] for k, v in d["startup_spreads"].items()},
            "pin_edge_A": d["pin"]["edge_1090_um_groupA"], "ceo2": d["diffraction"]["ceo2_calibrations"],
        }
    except (OSError, KeyError, ValueError):
        return _FALLBACK


P = _load()

# ------------------------------------------------------------------------------------------------------------------ pixel size / FOV
SENSOR_PITCH_UM = {"pg": 5.86, "gh1": 3.45, "retiga": 7.4}      # inferred from logs (reproduce every logged um/px); not read from data sheets
_CAM_SENSOR = {"pg1": "pg", "pg5": "pg", "pg": "pg", "gh1": "gh1", "retiga": "retiga", "retiga2": "retiga", "nf": "retiga"}
LOGGED_MAG = {"pg1": (5.0, 7.5), "pg5": (5.0,), "gh1": (5.0,), "retiga": (5.0, 7.5), "retiga2": (7.5,), "nf": (5.0,)}


def pixel_um(camera, magnification=None):
    """Object-plane pixel size [um/px] = sensor pitch / magnification (validated against 25+ logged values). `magnification` defaults to the camera's usual one
    (pg1/pg5/gh1/nf: 5X; retiga2 = hutch-B Retiga: 7.5X). PG1 7.5X (Nov 2024) -> 0.7813 (logged 0.781, fitted 0.78125)."""
    cam = camera.lower()
    m = float(magnification) if magnification else LOGGED_MAG[cam][0]
    return SENSOR_PITCH_UM[_CAM_SENSOR[cam]] / m


def fov_mm(n_pixels, pixel_um_):
    return n_pixels * pixel_um_ / 1000.0


def phase_contrast_distance_mm(wavelength_A, resolution_um):
    """Propagation distance for edge-enhanced tomography, z = (2 delta)^2 / lambda (rule used in the 2025 log): 0.69 um at 0.2385 A -> 79.8 mm."""
    return (2.0 * resolution_um * 1e-6) ** 2 / (wavelength_A * 1e-10) * 1e3


# ------------------------------------------------------------------------------------------------------------------ tungsten / scintillator absorption
def _interp_mu(E, tab_E, tab_mu):
    """log-log interpolation of mu(E) inside segments that do not straddle an absorption edge (tab_E is given with points on both sides of each edge, the jump is the
    pair of adjacent points: an edge is assumed wherever mu rises by >40 % between neighbours)."""
    E = float(E)
    tab_E, tab_mu = list(tab_E), list(tab_mu)
    if E <= tab_E[0]:
        return tab_mu[0] * (E / tab_E[0]) ** -2.7
    if E >= tab_E[-1]:
        return tab_mu[-1] * (E / tab_E[-1]) ** -2.7
    j = max(i for i in range(len(tab_E)) if tab_E[i] <= E)
    if tab_E[j] == E or j == len(tab_E) - 1:
        return tab_mu[j]
    e0, e1, m0, m1 = tab_E[j], tab_E[j + 1], tab_mu[j], tab_mu[j + 1]
    if m1 / m0 > 1.4:                                   # edge between the two points: stay on the low-energy side until the upper point
        return m0 * (E / e0) ** -2.7
    return math.exp(math.log(m0) + (math.log(E) - math.log(e0)) / (math.log(e1) - math.log(e0)) * (math.log(m1) - math.log(m0)))


def mu_per_cm(material, energy_keV):
    """Total linear attenuation [1/cm] of 'W' (pin), 'LuAG', 'YAG', 'LSO', 'CsI', 'GOS' from the embedded xraydb table (30-110 keV; K edges handled)."""
    t = P["scint"][material]
    return _interp_mu(energy_keV, t["E"], t["mu_per_cm"])


def scintillator_absorption(material, thickness_um, energy_keV):
    """Fraction of photons absorbed in a scintillator layer (K-fluorescence escape ignored). LuAG has the Lu K edge at 63.314 keV: absorption x3-4 between 62 and 64 keV."""
    return 1.0 - math.exp(-mu_per_cm(material, energy_keV) * thickness_um * 1e-4)


def relative_light(material, thickness_um, energy_keV, energy_weighted=True):
    """Light yield per incident photon, arbitrary units: absorbed fraction x E (energy-integrating camera) or x1 (counting). Ratio of two energies gives the counts factor
    when the energy is changed at fixed flux: e.g. LuAG 50 um: 71.7 keV vs 52 keV gives x1.8 x (71.7/52)."""
    return scintillator_absorption(material, thickness_um, energy_keV) * (energy_keV if energy_weighted else 1.0)


def resolution_fwhm_um(pixel_um_, NA=0.14, scint_um=20.0, lam_vis_um=0.55, xray_blur_um=1.0):
    """System FWHM in the scintillator plane [um] (ASSUMED structure; NA, thickness and blur are not in the logs): quadrature of the pixel, the Airy core 0.51 lam/NA,
    the defocus blur 0.5 NA t and the X-ray spread. Measured bound: sharpest pin edge 2-4 um (10-90 %) => FWHM <~ 2-4 um (consistent with t <~ 20 um)."""
    return math.sqrt(pixel_um_ ** 2 + (0.51 * lam_vis_um / NA) ** 2 + (0.5 * NA * scint_um) ** 2 + xray_blur_um ** 2)


# ------------------------------------------------------------------------------------------------------------------ alignment pin
def pin_params(group="B"):
    """Pin silhouette (flat-topped cone seen from the side). Group B (recommended, = sim top 104.5 um): top 104.5 um, half angle 7.8 deg (n=3 frames, 1 session);
    group A (wider pins): top ~180 um (135-220), half angle 14.8 +/- 0.25 deg (n=8 frames)."""
    if group == "B":
        return {"top_width_um": P["pin"]["top_width_um"], "half_angle_deg": P["pin"]["half_angle_deg"]}
    return dict(P["pin"]["alt_wide_pin"])


def pin_width_um(depth_um, top_width_um=None, half_angle_deg=None):
    """Silhouette width at `depth_um` below the tip (flat top width + 2 depth tan(half angle))."""
    pp = pin_params("B")
    top = pp["top_width_um"] if top_width_um is None else top_width_um
    ha = pp["half_angle_deg"] if half_angle_deg is None else half_angle_deg
    return top + 2.0 * depth_um * math.tan(math.radians(ha))


def pin_chord_um(x_um, half_width_um):
    """Material path through a round pin at lateral offset x from the axis: 2 sqrt(R^2 - x^2) (round cross-section ASSUMED; the interior profile could not be fitted)."""
    u = abs(x_um) / half_width_um
    return 0.0 if u >= 1.0 else 2.0 * half_width_um * math.sqrt(1.0 - u * u)


def pin_transmission(x_um, half_width_um, energy_keV, material="W"):
    """exp(-mu chord) of a round tungsten pin. W K edge 69.525 keV: mu 66/cm (62 keV) -> 200/cm (71.7 keV); a 104.5 um chord transmits 0.12 at 71.7 keV."""
    return math.exp(-mu_per_cm(material, energy_keV) * pin_chord_um(x_um, half_width_um) * 1e-4)


def pin_edge_width_1090_um(half_width_um, energy_keV, material="W"):
    """10-90 % width of the silhouette edge of a round absorbing pin: ((ln10)^2 - (ln(1/0.9))^2) / (8 R mu^2). Frames of the A pins: measured median 24 um (IQR 20-26), model
    12-21 um at 71.7 keV / 44-77 um at 52 keV for R = 80-140 um: the chord geometry, not the detector PSF, makes a thick pin edge soft."""
    mu_um = mu_per_cm(material, energy_keV) * 1e-4
    return (math.log(10.0) ** 2 - math.log(1.0 / 0.9) ** 2) / (8.0 * half_width_um * mu_um ** 2)


# ------------------------------------------------------------------------------------------------------------------ beam mottle texture
def texture_params(camera=None):
    """Recommended beam-mottle statistics (measured on beam-only frames: PG n=32, GH1 n=25, similar): exponential ACF, 1/e length ~26 um (IQR 16-50),
    relative rms 0.09 (0.17 for the strongly mottled frames; display-contrast upper bound), PSD slope -2.45 over periods 6-60 screen px. The current vbl beam_texture has
    ~70 um and 0.34 by the same estimator: about 2.7x too long and 3.7x too strong."""
    t = dict(P["texture"])
    return t


def texture_psd(f_cyc_per_um, corr_len_um=None):
    """Isotropic 2D power spectrum of an exponential-ACF field, ~ (1 + (2 pi f l)^2)^-3/2 (unit-less shape)."""
    l = texture_params()["corr_len_um_bias_corrected"] if corr_len_um is None else corr_len_um
    return (1.0 + (2.0 * math.pi * np.asarray(f_cyc_per_um, float) * l) ** 2) ** -1.5


def texture_field(n, pixel_um_, corr_len_um=None, rms=None, seed=0):
    """Synthetic multiplicative texture (1 + t), n x n, periodic, exponential ACF of TRUE 1/e length `corr_len_um` (default: the estimator value 26 um x1.2 bias correction = 32 um)
    and relative rms `rms` (FFT filtering, numpy only)."""
    p = texture_params()
    l = p["corr_len_um_bias_corrected"] if corr_len_um is None else corr_len_um
    s = p["rms_rel"] if rms is None else rms
    rng = np.random.default_rng(seed)
    k = np.fft.fftfreq(n, d=pixel_um_)
    f = np.hypot(k[:, None], k[None, :])
    filt = (1.0 + (2.0 * np.pi * f * l) ** 2) ** -0.75
    a = np.fft.ifft2(np.fft.fft2(rng.normal(size=(n, n))) * filt).real
    a = (a - a.mean()) / a.std()
    return 1.0 + s * a


def fit_acf_length_um(field, pixel_um_, lag_min=2, lag_max=60):
    """The estimator used on the screenshots: relative residual of the field, windowed 2D autocorrelation, radial average, exponential fit at lags lag_min..lag_max px
    (skips the white-noise spike). Returns (length_um, amplitude)."""
    t = field / field.mean() - 1.0
    H, W = t.shape
    t = (t - t.mean()) * np.outer(np.hanning(H), np.hanning(W))
    F = np.fft.fft2(t, s=(2 * H, 2 * W))
    ac = np.fft.fftshift(np.fft.ifft2(np.abs(F) ** 2).real)
    ac /= ac[H, W]
    yy, xx = np.indices(ac.shape)
    r = np.hypot(yy - H, xx - W).astype(int)
    rad = np.bincount(r.ravel(), ac.ravel()) / np.maximum(np.bincount(r.ravel()), 1)
    lags = np.arange(lag_min, min(lag_max, min(H, W) // 4) + 1)
    y = np.clip(rad[lags], 1e-6, None)
    best = None
    for l in np.linspace(1.0, 0.25 * min(H, W), 400):
        e = np.exp(-lags / l)
        A = float(e @ y / (e @ e))
        res = float(np.sum((A * e - y) ** 2))
        if best is None or res < best[0]:
            best = (res, l, A)
    return best[1] * pixel_um_, best[2]


# ------------------------------------------------------------------------------------------------------------------ edges, dust
def slit_edge_width_um(camera="gh1"):
    """Measured 10-90 % width of slit-defined beam edges [um]: dict(median, q25, q75, min, n). PG median 38 (horizontal edges 32, vertical 48), GH1 19. They are penumbra +
    Fresnel + PSF together; only the minimum (8-10 um) bounds the PSF."""
    return dict(P["edges"]["gh1_all" if camera.lower().startswith("gh") else "pg_all"])


def edge_profile(x_um, w1090_um):
    """Normalised edge (0 -> 1) of 10-90 % width w: Gaussian-blurred step, sigma = w / 2.563."""
    s = w1090_um / 2.5631
    return 0.5 * (1.0 + np.vectorize(math.erf)(np.asarray(x_um, float) / (s * math.sqrt(2.0))))


def dust_params(camera="pg"):
    """Scintillator dust/defect statistics: density per mm^2 and equivalent diameter (median, p90) [um]; detection-limited (4-sigma dark spots)."""
    d = P["dust"]["gh1" if camera.lower().startswith("gh") else "pg"]
    return {"density_per_mm2": d["density_per_mm2"]["median"], "diameter_um_median": d["equiv_diameter_um_median"], "diameter_um_p90": d["equiv_diameter_um_p90"]}


# ------------------------------------------------------------------------------------------------------------------ noise (protocol; no fit possible from the KB)
def ptc_fit(mean_adu, var_adu):
    """Photon-transfer fit on flat-field pairs (PENDING measurement): var = mean/K + var0, K = e-/ADU (shot-noise gain), read noise = sqrt(var0)*K [e-].
    Inputs: per-exposure mean (dark-subtracted) and temporal variance (from the difference of two frames / 2). Returns (K, read_noise_e, full_well_ADU_hint)."""
    m = np.asarray(mean_adu, float)
    v = np.asarray(var_adu, float)
    A = np.vstack([m, np.ones_like(m)]).T
    slope, var0 = np.linalg.lstsq(A, v, rcond=None)[0]
    K = 1.0 / slope
    return float(K), float(math.sqrt(max(var0, 0.0)) * K), float(m.max())


# ------------------------------------------------------------------------------------------------------------------ diffraction detector geometry
def ring_radius_px(energy_keV, d_A, distance_mm, pixel_um_):
    """Powder ring radius L tan(2 theta) / pixel for a detector perpendicular to the beam (same formula as blade.physics.detector, self-contained)."""
    lam = 12.398419843320026 / energy_keV
    tt = 2.0 * math.asin(lam / (2.0 * d_A))
    return distance_mm * math.tan(tt) * 1000.0 / pixel_um_


def pixel_pitch_from_calibration(centre_px, centre_mm):
    """Pixel pitch [um] from a calibration's beam centre in pixels and mm (both axes): the three logged Pilatus calibrations give 172.000 um."""
    return [1000.0 * m / p for p, m in zip(centre_px, centre_mm)]


def nf_bby_mm(detz_mm, slope_um_per_mm=None, intercept_mm=None):
    """NF beam-stop Y vs detector Z. Pooled 2023-2025 fit: bbY = 0.0056 + 0.0033 DetZ [mm] (sessions: slope 2.8-5.0 um/mm, intercept varies +-15 um)."""
    s = P["nf_pooled"]["slope_um_per_mm"] if slope_um_per_mm is None else slope_um_per_mm
    b = P["nf_pooled"]["intercept_mm"] if intercept_mm is None else intercept_mm
    return b + s * 1e-3 * detz_mm


# ------------------------------------------------------------------------------------------------------------------ session-start spreads
def startup_spread(name):
    """(median, geometric sd, values) of an as-found alignment quantity: 'omega_zero_error_deg', 'wedge_deg', 'camera_or_axis_tilt_deg' (logs 2023-2026, n=6-11; small sample)."""
    v = np.array(P["spreads"][name], float)
    v = v[v > 0]
    lg = np.log(v)
    return float(np.exp(np.median(lg))), float(np.exp(lg.std(ddof=1))), v.tolist()


def sample_startup(name, rng):
    """Draw an as-found value: lognormal with the logged median and geometric sd (sign random for angles)."""
    med, gsd, _ = startup_spread(name)
    return float(med * math.exp(math.log(gsd) * rng.normal()) * (1 if rng.random() < 0.5 else -1))
