# 4. Flux, ion chambers, attenuators and foils

Twin elements: ion chambers `icB1..icE8`, `foilB`, `attenB`, `attenC`, shutters (`shutter_a`, `fsB`, `fsE`). Code: `blade.physics.core` (`transmission`, `mu_per_cm`, `thickness_for_mu_t`, `delta_beta`). Citation keys: `README.md`.

## 4.1 What the ion chambers read
Ion chambers (IC1..IC8, per hutch) feed current preamplifiers whose output is counted by scalers as a rate. **Rate scales linearly with ring current** (150 -> 200 mA: x1.33 [S25a:L37-41]) and with preamp gain; the scaler clips near 1e6 counts/s (IC6-E read 999977 when saturated) [S25b:L518-526]. With the beam off the channels read a **dark floor of 0.8-2.1 kHz** [O22:L164-171], [S25b:L239-249]; subtract it before comparing.
Reference levels at 200 mA, 50 nA/V (Re/Au edge, WB 0.3 x 0.3 mm): **IC_B1 = 174-178.5 kHz** [S25b:L21-35], [M26a:L42]; IC_B3 ~361 kHz at 150 mA (477 kHz at 200 mA) [S25a:L37-41]; IC8-B 230 kHz at gap 8.97 mm / 80.7 keV [M24:L192]. A drop of >10-20 % at fixed settings points to steering, thermal or alignment drift (see files 01-02), not to the detector. Gap/energy tuning is done on the IC1-B..IC8-B signals (peaks of ~310 000 -> ~626 000 counts after mono tweaks in Jan 2026 [M26a:L113]).

## 4.2 Attenuators and foils: Beer-Lambert
`I/I0 = exp(-sum_i mu_i t_i)` over the wheels in the beam (`attenB`, `foilB`, `attenC`); this is exactly how `mpe_bluesky.calculator_atten.atten_calc` picks wheel positions (xraydb `material_mu`). `core.transmission(material, mm, keV)` implements it. Numbers:
- **B attenuator position 2 = 1.016 mm Cu** [S25b:L273-292]: transmission 0.40 at 71.7 keV, 0.51 at 80.7 keV, 0.12 at 52 keV, so an attenuator tuned at one edge gives a very different factor at another: **re-check the wheel when the energy changes**.
- Energy-dependent exposure rule seen repeatedly: Varex 0.1 s at attenC = 1.0 saturated, position 2 and 0.32 s used [S25a:L346-348]; B attenuator position 4 allows 0.1 s tomo exposures without saturation [S25b:L281-286,L716]; "Atten 0 0 2" gave an acceptable powder pattern where 0 0 0 saturated and 2 0 0 / 1 0 0 under-exposed [D22:L336-350].
- Test: attenuator 2 0 0 reduced IC1-E 999988 -> 564726, IC2-E 999987 -> 667900, IC3-E 151460 -> 59448 (0.2 x 0.2 mm slits) [S25b:L206-237].
- **Foil `mu_t`:** `mu_t = ln(I_out/I_in)`; check from the logs: Pb foil 441 / 252 kHz gives ln = 0.559 and the log reads `ut = 0.56` [T26:L431-433]. `core.thickness_for_mu_t` converts: for example a gold foil with ut = 1.4 just above the Au edge (80.73 keV) is ~81 um thick (assumption: ut is the above-edge value).
- **Silicon lenses absorb little** at these energies: 1/e length of Si at 71.7 keV is 17 mm.

## 4.3 Shutters
A/B/C PSS shutters and the E hutch fast shutter gate the beam. The B and E fast shutters must be positioned so the blades clear the beam: B-FS aligned with IC6 (X 2.749887 -> 2.399887 mm, Y -0.600 -> -0.425 mm gave IC6 +0.3 %) [S25a:L46-53]; in June the leakage signal first appeared at X = 1.5 mm and the final X was 3.0 mm (1.5 mm clearance) [S25b:L74-79]. Fast-shutter timing: with a camera-controlled shutter, pulses per frame were unstable (1 frame -> 0, 1 or 2 pulses) and the shutter opened late relative to the scaler read at fast frame rates (0.1 s) [M26a:L439-471]: **at short exposures the shutter timing, not the beam, sets the delivered dose.**

## 4.4 The off-axis "phantom" beam
With the undulator gap opened (30-100 mm) a residual signal remained that steering did not move (B3 = 68 kHz at gap 100 mm, 10 uA/V) [T26:L66,L98,L138-154]. For white-beam/closed-gap tests, subtract it or distinguish it from undulator beam by closing the gap (gap 30 -> 20 mm raised B3 145 -> 612 kHz at 0.25 x 0.25 mm WB).
