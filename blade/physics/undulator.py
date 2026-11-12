"""Undulator harmonic energy vs magnetic gap (permanent-magnet undulator, PMU) - a SIMPLE MODEL whose parameters are assumptions/inferences.

    E_n = n * 0.9496 * E_ring[GeV]^2 / (lambda_u[cm] * (1 + K^2/2))   [keV]  (textbook, on-axis; harmonic n, K = deflection parameter)
    K   = 0.0934 * B0[T] * lambda_u[mm];   B0 = a * exp(b*(g/lambda_u) + c*(g/lambda_u)^2)   (Halbach-type fit; (a,b,c) below are the commonly quoted
    Nd-Fe-B hybrid values, NOT measured for this device)

ASSUMED: ring energy 6.0 GeV (APS-U), the Halbach coefficients, and a ~22 mm period INFERRED by fitting logged (gap, harmonic, energy) pairs, e.g. gap 8.995 mm
at n=9 for 80.725 keV and 10.025 mm at n=7 for 71.676 keV (2025 startup logs). The device specification was not available: treat `fit_period_mm` as a
consistency result, not a datasheet value. The 2022-2023 superconducting undulator (SCU, tuned by CURRENT in A, harmonic 5/7/9) is NOT modelled.
Higher harmonics have a bandwidth ~1/(n N); the mono energy need not equal the harmonic peak exactly (operators peak the flux with IC counts).
"""
import math

RING_GEV = 6.0
HALBACH_HYBRID_NDFEB = (3.694, -5.068, 1.520)      # (a, b, c): B0[T] = a exp(b g/lam + c (g/lam)^2)


def k_from_gap(gap_mm, period_mm, coef=HALBACH_HYBRID_NDFEB):
    x = gap_mm / period_mm
    a, b, c = coef
    return 0.0934 * a * math.exp(b * x + c * x * x) * period_mm


def harmonic_energy_keV(gap_mm, n, period_mm, ring_GeV=RING_GEV, coef=HALBACH_HYBRID_NDFEB):
    k = k_from_gap(gap_mm, period_mm, coef)
    return n * 0.9496 * ring_GeV ** 2 / ((period_mm / 10.0) * (1.0 + k * k / 2.0))


def gap_for_energy_mm(energy_keV, n, period_mm, ring_GeV=RING_GEV, coef=HALBACH_HYBRID_NDFEB, lo=5.0, hi=60.0):
    """Gap [mm] whose n-th harmonic sits at energy_keV (E rises monotonically with gap, so bisection)."""
    f = lambda g: harmonic_energy_keV(g, n, period_mm, ring_GeV, coef) - energy_keV
    if f(lo) > 0 or f(hi) < 0:
        raise ValueError("energy not reachable with this harmonic inside the gap range")
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return 0.5 * (lo + hi)


def fit_period_mm(points, ring_GeV=RING_GEV, coef=HALBACH_HYBRID_NDFEB, lo=14.0, hi=40.0):
    """Least-squares period [mm] from [(gap_mm, n, energy_keV), ...] by a coarse-to-fine scan (stdlib only). Returns (period_mm, rms_relative_error)."""
    def cost(p):
        return math.sqrt(sum((harmonic_energy_keV(g, n, p, ring_GeV, coef) / e - 1.0) ** 2 for g, n, e in points) / len(points))
    best = None
    steps = 1000
    a, b = lo, hi
    for _ in range(4):
        grid = [a + (b - a) * i / steps for i in range(steps + 1)]
        best = min(grid, key=cost)
        w = (b - a) / steps * 5
        a, b = best - w, best + w
    return best, cost(best)
