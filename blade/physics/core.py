"""Energy, wavelength, absorption edges, crystal Bragg geometry, and X-ray attenuation.  keV / Angstrom / mm / degrees unless stated."""
import math

HC_KEV_A = 12.398419843320026      # h*c in keV*Angstrom (CODATA 2018)
SI_A = 5.431020511                 # Si lattice parameter, Angstrom (room temperature)


def _xdb():
    try:
        import xraydb
        return xraydb
    except ImportError as e:        # pragma: no cover
        raise ImportError("this function needs xraydb: pip install xraydb==4.5.8 (matches the beamline's mpe_bluesky env; keeps numpy 1.26)") from e


def wavelength_A(energy_keV):
    """lambda[A] = 12.3984 / E[keV]."""
    return HC_KEV_A / energy_keV


def energy_keV(wavelength_A_):
    return HC_KEV_A / wavelength_A_


def edge_keV(element, line="K"):
    """Absorption-edge energy from xraydb (Elam tables). The 1-ID logs calibrate the monochromator on these: Re K 71.676, Au K 80.725, Yb K 61.332,
    Tb K 51.996, Ho K 55.618, Ta K 67.416, Pr K 41.991 keV (all reproduced exactly by this function)."""
    return _xdb().xray_edge(element, line).energy / 1000.0


def edge_jump_ratio(element, line="K"):
    return _xdb().xray_edge(element, line).jump_ratio


def d_spacing_cubic(a_A, hkl):
    h, k, l = hkl
    return a_A / math.sqrt(h * h + k * k + l * l)


def bragg_angle_deg(energy_keV_, d_A, order=1):
    """Bragg angle theta: n*lambda = 2 d sin(theta)  (textbook). For the 1-ID HEM the logs show E = 6.199/(d sin(theta)) for Si(111), i.e. n=1,
    with 6.199 = hc/2 (see the 2022 startup notes)."""
    s = order * wavelength_A(energy_keV_) / (2.0 * d_A)
    if not 0 < s <= 1:
        raise ValueError("no Bragg reflection for this energy/d-spacing")
    return math.degrees(math.asin(s))


def energy_from_bragg_keV(theta_deg, d_A, order=1):
    return order * HC_KEV_A / (2.0 * d_A * math.sin(math.radians(theta_deg)))


def energy_shift_from_angle_keV(energy_keV_, d_A, dtheta_deg, order=1):
    """Energy change when the crystal angle changes by dtheta at fixed d (exact, from E ~ 1/sin(theta)).  dE/E ~ -dtheta*cot(theta): a few
    thousandths of a degree move the energy by tens/hundreds of eV at ~70 keV - which is why a 0.0003 deg Th1-offset drift moves the Re edge by ~35 eV
    and a 0.008 deg crystal tweak is a visible energy shift (see logs)."""
    th = bragg_angle_deg(energy_keV_, d_A, order)
    return energy_from_bragg_keV(th + dtheta_deg, d_A, order) - energy_keV_


def hem_th1_deg(energy_keV_, th1_offset_deg=0.4963, d_A=None):
    """HEM (Si(111) Laue) crystal-angle readout 'Th1' for an energy: Th1 = theta_Bragg(Si 111) + offset. The offset is a calibration constant the
    operators re-tune at startup (logs: 0.4944 Jun-22, 0.4953 Oct-22, 0.4963 Nov/Dec-22, ~0.487 in 2025, 0.4863 in 2026). Verified against the
    2023 log: Th1 = 2.684, 2.089, 1.748 deg at 51.8, 71.2, 90.5 keV are theta_B(111) = 2.187, 1.591, 1.252 deg plus 0.497 deg."""
    d = d_A if d_A is not None else d_spacing_cubic(SI_A, (1, 1, 1))
    return bragg_angle_deg(energy_keV_, d) + th1_offset_deg


HEM_EXIT_OFFSET_MM = 32.91     # fitted constant (see hem_z2_mm)


def hem_z2_mm(energy_keV_, offset_mm=HEM_EXIT_OFFSET_MM, d_A=None):
    """HEM second-crystal position Z2 [mm]. FOUND IN THE LOGS: Z2 * tan(2 theta_B) is constant (32.77..33.02 mm, mean 32.91) for the logged
    (E, Z2) pairs 51.81/71.15/90.52 keV -> 428.5/591.8/755.3 mm (2023), 71.7 keV -> 595.7-596.1 mm (2022), 71.600/71.625 keV -> 595.616/595.827 mm
    (2025). I.e. the mono is a fixed-exit double-crystal design: the second crystal slides along the beam so the exit beam stays a constant `offset`
    (~32.9 mm) from the incident beam: Z2 = offset / tan(2 theta_B). (Derived by this project from the logs; not from a drawing.)"""
    d = d_A if d_A is not None else d_spacing_cubic(SI_A, (1, 1, 1))
    return offset_mm / math.tan(2.0 * math.radians(bragg_angle_deg(energy_keV_, d)))


def material_density(material):
    return _xdb().get_material(material)[1]


def mu_per_cm(material, energy_keV_, density=None):
    """Linear attenuation coefficient [1/cm] (xraydb, total cross section; same call the beamline's calculator_atten.py uses)."""
    return float(_xdb().material_mu(material, energy_keV_ * 1000.0, density=density))


def transmission(material, thickness_mm, energy_keV_, density=None):
    """I/I0 = exp(-mu*t) (Beer-Lambert). Same law as mpe_bluesky.calculator_atten.atten_calc (sum of mu_i t_i over wheels/foils)."""
    return math.exp(-mu_per_cm(material, energy_keV_, density) * thickness_mm / 10.0)


def attenuation_length_mm(material, energy_keV_, density=None):
    return 10.0 / mu_per_cm(material, energy_keV_, density)


def thickness_for_mu_t(material, mu_t, energy_keV_, density=None):
    """Thickness [mm] giving a measured mu*t (the 'ut' of the energy-calibration scans, e.g. ut=1.35-1.4)."""
    return 10.0 * mu_t / mu_per_cm(material, energy_keV_, density)


def delta_beta(material, energy_keV_, density=None):
    """Refractive-index decrement delta and absorption index beta (n = 1 - delta + i beta); xraydb, as in mpe_bluesky.calculator_tilt.calculate_delta.
    Valid away from absorption edges: delta ~ r_e lambda^2 rho_e / (2 pi)."""
    d = density if density is not None else material_density(material)
    delta, beta, _ = _xdb().xray_delta_beta(material, d, energy_keV_ * 1000.0)
    return float(delta), float(beta)


def darwin_width_bragg(energy_keV_, crystal="Si", hkl=(1, 1, 1)):
    """Symmetric-BRAGG Darwin width from xraydb: (theta_fwhm_urad, energy_fwhm_eV). Indicative only: the 1-ID HEM is a LAUE (transmission) design,
    whose bandwidth differs; use for order-of-magnitude comparison."""
    dw = _xdb().darwin_width(energy_keV_ * 1000.0, crystal, hkl)
    return dw.theta_fwhm * 1e6, dw.energy_fwhm
