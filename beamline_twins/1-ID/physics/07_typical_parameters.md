# Typical parameters across the 1-ID experiment logs (generated)

Generated 2026-11-11 by `beamline_twins/tools/logstats.py` from the local log index (121 documents, 2022-2026). Aggregates only; values are regex-extracted from free text, so use `logindex.py params <name>` to inspect sources. Header energies come from each beamtime's 'X-ray energy' field (62 of 86 user logs fill it in).

## Corpus

| year | startup/setup logs | user logs | spreadsheets |
|--:|--:|--:|--:|
| 2022 | 5 | 21 | 4 |
| 2023 | 2 | 10 | 6 |
| 2024 | 3 | 3 | 0 |
| 2025 | 2 | 27 | 5 |
| 2026 | 4 | 25 | 4 |

## Energies: the beamline runs ON absorption edges

Each beamtime's monochromator energy is calibrated on a foil K-edge (the `Emon`/`E_scan` procedure). Count = beamtimes whose header names that edge (or an energy within 0.35 keV of it); tabulated K-edge energy from xraydb.

| edge | K-edge (keV) | beamtimes | years seen |
|---|--:|--:|---|
| Re | 71.676 | 28 | 2022, 2023, 2024, 2025, 2026 |
| Au | 80.725 | 7 | 2025, 2026 |
| Tb | 51.996 | 7 | 2025, 2026 |
| Yb | 61.332 | 6 | 2022, 2024, 2025, 2026 |
| Tm | 59.39 | 3 | 2022 |
| Bi | 90.526 | 2 | 2023, 2025 |
| Ho | 55.618 | 2 | 2025, 2026 |
| Ta | 67.416 | 2 | 2026 |
| Pt | 78.395 | 1 | 2025 |
| Sm | 46.834 | 1 | 2025 |
| Pr | 41.991 | 1 | 2026 |

Other stated energies (no edge): 87, 95, 100 keV (HRM-based ~52 keV, ~100 keV and similar).

## Detectors and cameras mentioned in beamtime headers

| detector / camera | 2022 | 2023 | 2024 | 2025 | 2026 | total |
|---|--:|--:|--:|--:|--:|--:|
| GE | 10 | 3 | 1 | 8 | 10 | 32 |
| Hydra (4-panel GE) | 1 | 0 | 0 | 4 | 7 | 12 |
| Pixirad | 0 | 0 | 1 | 1 | 5 | 7 |
| Pilatus | 2 | 3 | 0 | 3 | 4 | 12 |
| Varex | 0 | 0 | 0 | 3 | 4 | 7 |
| Eiger | 0 | 0 | 0 | 0 | 1 | 1 |
| Retiga (NF) | 9 | 3 | 0 | 2 | 3 | 17 |
| PG1 tomo | 12 | 6 | 0 | 2 | 5 | 25 |
| GH1 tomo | 0 | 0 | 0 | 8 | 6 | 14 |
| PG5 tomo | 0 | 0 | 0 | 3 | 2 | 5 |
| tomo (any) | 12 | 7 | 1 | 12 | 13 | 45 |
| SAXS/WAXS | 1 | 0 | 0 | 1 | 0 | 2 |
| Spectrum Logic | 0 | 0 | 0 | 0 | 0 | 0 |
| BrillianSe | 0 | 0 | 0 | 0 | 0 | 0 |

Pixel sizes stated in headers (um/px: count): 0.69: 13, 1.172: 12, 1.48: 11, 200: 11, 172: 6, 1: 5, 1.17: 1

Detector/sample distances stated in the text, 100-10000 mm: 34 values, median 1063; most common 1063 (x3), 2278 (x1), 300 (x1), 2229 (x1), 6500 (x1), 359.7 (x1), 2082 (x1), 1814 (x1)

## White-beam (WB) slit sizes written in the logs (H x V mm)

44 occurrences; most common: 0.5 x 0.5 (x13), 0.3 x 0.3 (x13), 0.6 x 0.6 (x6), 0.4 x 0.4 (x3), 0.5 x 0.3 (x2), 0.5 x 0.4 (x2), 1.2 x 0.5 (x1), 1.1 x 0.5 (x1), 0.6 x 0.4 (x1), 0.3 x 0.5 (x1)

## Undulator gap / harmonic pairs recorded together (mm, n)

| gap (mm) | harmonic n | times |
|--:|--:|--:|
| 10.022 | 7 | 3 |
| 8.995 | 9 | 2 |
| 8.9955 | 9 | 2 |
| 10.025 | 7 | 2 |
| 8.83 | 7 | 1 |
| 8.985 | 9 | 1 |
| 10.158 | 5 | 1 |

All gap values <20 mm (42): min 8.815, median 10.025, max 11.348 mm.

## Calibration / flux numbers

- **mu*t at the calibration edge ('ut')**: 50 values; min 0.56, median 1.3665, max 1.7095 ; most common 1.4 (x5), 1.44 (x4), 1.37 (x4), 1.22 (x2), 1.35 (x2), 1.39 (x2)
- **HEM Th1 offset**: 5 values; min 0.4863, median 0.4871, max 0.495 deg; most common 0.487 (x3), 0.495 (x1), 0.486 (x1)
- **ring current quoted**: 65 values; min 25, median 199.826, max 200.45 mA; most common 200 (x23), 130 (x7), 102 (x4), 100 (x2), 50 (x2), 160 (x2)
- **ion-chamber rates quoted**: 25 values; min 47.8, median 195, max 639 kHz; most common 178.5 (x2), 180.7 (x2), 114 (x1), 450 (x1), 391 (x1), 235 (x1)
- **exposure times quoted**: 28 values; min 0.02, median 0.5, max 10 s; most common 0.5 (x10), 0.1 (x7), 1 (x3), 7 (x3), 3 (x1), 4.5 (x1)

Th1 offset history (deg, by document date): 2023-03: 0.495; 2025-01: 0.4873; 2025-06: 0.4871; 2025-06: 0.4871; 2026-02: 0.4863
