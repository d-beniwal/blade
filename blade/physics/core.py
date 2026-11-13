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


# --- HEM energy-transform calc record (userTran3), FITTED 2026-11-13 to tier-A panel transcriptions (physics/fits/facts_hem.json, test_fit_facts_hem.py).
# The printed outputs are reproduced to 3e-7 deg (Th1, Th2, Chi2) and 0.7 um (Z2) over 51.9-100 keV, 2022-2026:
#   Th1  = HEM_TH1_SCALE * theta_B(E) + Th1 offset      (offset = the operator-set number printed in the same record, e.g. 0.4863)
#   Th2  = HEM_TH2_SCALE * theta_B(E) + Th2 offset      (scale 1.00001 = Si(111) exactly; Th1's calc uses a 1.97e-4 larger angle scale)
#   Z2   = HEM_Z2_C / tan(2 theta_B) + HEM_Z2_D         (the old constant-exit form c/tan(2 theta_B) was off by up to 3.5 mm)
#   Chi2 = polynomial in (E - 70 keV)
# theta_B uses d(Si 111) = 3.1356 A (blade.physics.core.SI_A); the scales therefore also absorb the calc record's own constants.
HEM_TH1_SCALE = 1.0001973
HEM_TH2_SCALE = 1.0000100
HEM_Z2_C_MM = 33.3417
HEM_Z2_D_MM = -7.4407
HEM_CHI2_COEF = (-1.5593442896709143e-09, 2.0277840711167556e-08, 1.0461166114915513e-06, 0.0005689130881709239, 0.03121166148470255)   # high -> low
HEM_CAL_E_KEV = 71.676         # operators calibrate the Th1 offset on foil edges near the 71.676 keV working energy


def hem_th1_deg(energy_keV_, th1_offset_deg=0.4963, d_A=None, scale=HEM_TH1_SCALE):
    """HEM (Si(111) Laue) crystal-angle readout 'Th1' for an energy: Th1 = scale * theta_Bragg(Si 111) + offset. The offset is the calibration constant the
    operators re-tune at startup (printed in the transform record: 0.4944 Jun-22, 0.4950 Mar-23, 0.5051 Oct-24, 0.4873 Feb-25, 0.4860 Nov-25, 0.4863 Feb-26).
    scale = 1.0001973 (fit, 31 screenshots, 2.5e-7 deg rms); with scale = 1 the readout is off by up to 0.43 mdeg (24 eV per mdeg at 52 keV)."""
    d = d_A if d_A is not None else d_spacing_cubic(SI_A, (1, 1, 1))
    return scale * bragg_angle_deg(energy_keV_, d) + th1_offset_deg


def hem_th2_deg(energy_keV_, th2_offset_deg=0.1562, d_A=None, scale=HEM_TH2_SCALE):
    """HEM second-crystal angle 'Th2' = scale * theta_Bragg + offset (printed offset 0.1475 2022-23, 0.1573 2024-25, 0.1552 Nov-25, 0.1562 2026; 29 screenshots, 2.8e-7 deg rms)."""
    d = d_A if d_A is not None else d_spacing_cubic(SI_A, (1, 1, 1))
    return scale * bragg_angle_deg(energy_keV_, d) + th2_offset_deg


def hem_chi2_deg(energy_keV_):
    """HEM Chi2 output [deg]: polynomial in (E - 70 keV), 31 screenshots 51.9-100 keV, 2.4e-7 deg rms (0.0210 at 52 keV, 0.0322 at 71.7, 0.0485 at 100)."""
    x = energy_keV_ - 70.0
    v = 0.0
    for c in HEM_CHI2_COEF:
        v = v * x + c
    return v


HEM_EXIT_OFFSET_MM = 32.91     # LEGACY constant of the old form Z2 = offset / tan(2 theta_B) (kept for callers that pass offset_mm explicitly)


def hem_z2_mm(energy_keV_, offset_mm=None, d_A=None):
    """HEM second-crystal position Z2 [mm] = 33.3417 / tan(2 theta_B) - 7.4407 (fit: 21 distinct (E, Z2) pairs 51.9-100 keV from 2022-2026, 0.29 um rms, 0.66 um max;
    fits/facts_hem.json). The earlier derivation from the logs, Z2 = 32.91 / tan(2 theta_B) (fixed exit), is only approximate: 1.5 mm rms (best-fit constant), 3.5 mm max with the 32.91 constant. Passing
    offset_mm selects that legacy form."""
    d = d_A if d_A is not None else d_spacing_cubic(SI_A, (1, 1, 1))
    t = 1.0 / math.tan(2.0 * math.radians(bragg_angle_deg(energy_keV_, d)))
    if offset_mm is not None:
        return offset_mm * t
    return HEM_Z2_C_MM * t + HEM_Z2_D_MM


def material_density(material):
    """Density [g/cm3]: the xraydb materials table when the name is there (Re, Au, Ta, Cu, Si, ...), else the elemental density (Yb, Tb, Ho, Hf, Pr are
    not in that table - get_material() returns None for them)."""
    m = _xdb().get_material(material)
    return m[1] if m else _xdb().atomic_density(material)


def mu_per_cm(material, energy_keV_, density=None):
    """Linear attenuation coefficient [1/cm] (xraydb, total cross section; same call the beamline's calculator_atten.py uses)."""
    return float(_xdb().material_mu(material, energy_keV_ * 1000.0, density=material_density(material) if density is None else density))


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
