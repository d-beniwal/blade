"""Detector / camera geometry: what a detector or tomo camera sees when energy, distance, or optics change.  mm / Angstrom / keV / degrees."""
import math
from .core import wavelength_A, d_spacing_cubic

CEO2_A = 5.411651          # CeO2 (NIST SRM 674b) lattice parameter, Angstrom; the usual detector-calibration powder
LAB6_A = 4.156826          # LaB6 (NIST SRM 660c)


def two_theta_deg(energy_keV, d_A):
    """Scattering angle of a reflection: 2 theta = 2 asin(lambda / 2d)."""
    return 2.0 * math.degrees(math.asin(wavelength_A(energy_keV) / (2.0 * d_A)))


def ring_radius_mm(energy_keV, d_A, distance_mm):
    """Powder ring radius on a flat detector perpendicular to the beam: R = L tan(2 theta). Rings grow with detector distance and shrink with energy."""
    return distance_mm * math.tan(math.radians(two_theta_deg(energy_keV, d_A)))


def ring_radius_px(energy_keV, d_A, distance_mm, pixel_um):
    return ring_radius_mm(energy_keV, d_A, distance_mm) * 1000.0 / pixel_um


def cubic_rings(a_A, energy_keV, distance_mm, pixel_um, hmax=3, allowed=None):
    """[(hkl, d_A, two_theta_deg, radius_px)] for a cubic powder, sorted by radius. `allowed(h,k,l)` filters (default: fcc-type all-odd/all-even: CeO2, Si)."""
    allowed = allowed or (lambda h, k, l: len({h % 2, k % 2, l % 2}) == 1)
    seen, out = set(), []
    for h in range(hmax + 1):
        for k in range(h + 1):
            for l in range(k + 1):
                if (h, k, l) == (0, 0, 0) or not allowed(h, k, l):
                    continue
                d = d_spacing_cubic(a_A, (h, k, l))
                if round(d, 6) in seen or wavelength_A(energy_keV) / (2 * d) >= 1:
                    continue
                seen.add(round(d, 6))
                out.append(((h, k, l), d, two_theta_deg(energy_keV, d), ring_radius_px(energy_keV, d, distance_mm, pixel_um)))
    return sorted(out, key=lambda r: r[3])


def q_inv_A(energy_keV, two_theta_deg_):
    return 4.0 * math.pi * math.sin(math.radians(two_theta_deg_ / 2.0)) / wavelength_A(energy_keV)


def object_pixel_um(sensor_pitch_um, magnification):
    """Camera pixel size at the scintillator (object plane) = sensor pitch / optical magnification. Reproduces the logged 1-ID values:
    5.86 um / 5 = 1.172 (PG1 5X), 3.45 um / 5 = 0.69 (GH1 5X), 7.4 um / 5 = 1.48 (NF Retiga 5X)."""
    return sensor_pitch_um / magnification


def fov_mm(n_pixels, pixel_um):
    """Field of view along one sensor axis [mm]."""
    return n_pixels * pixel_um / 1000.0


def pixel_angle_mrad(pixel_um, distance_mm):
    """Angle subtended by one pixel (sets the angular resolution of a far-field detector)."""
    return pixel_um * 1e-3 / distance_mm * 1e3
