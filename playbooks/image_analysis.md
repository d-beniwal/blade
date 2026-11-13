# Image / profile analysis (module `imganalysis`)

Read-only tools (MCP: `analysis_*`, resource `blade://playbook/imganalysis`). Ported from the areaDetector ADViewers ImageJ plugins
(`Gaussian_Profiler`: live Gaussian fit for focusing/beam diagnostics; `LiveFitter_EPICSUserCalc`: any fit + slit aperture fit). Code: `blade/imganalysis/`.

1. `analysis_list_models` - catalogue (parameter names and formulas).
2. From a saved frame: `analysis_fit_roi` (rectangle, mean over the other axis, like ImageJ) or `analysis_fit_line` (line, interpolated, `width` px averaged).
   From numbers (motor/slit scan vs IC): `analysis_fit_profile`. `model='auto'` picks gaussian / erf_edge / slit_positive / slit_negative by BIC.
3. Which model: beam spot or focus -> `gaussian` (FWHM, peak, background, contrast%). One knife edge / slit blade -> `erf_edge` (centre, sigma, 10-90 width).
   Slit seen as a bright window -> `slit_positive`; dark blocker/pin in bright field -> `slit_negative` (centre, aperture width, edge sigma, optional tilt `slope`).
4. Trust the fit only if `r2` is high (>~0.95) and the parameter `errors` are small; compare with the model-free `moments` (centroid, rms width, half-max FWHM).
   A big disagreement means the model is wrong (saturation, clipped beam, structured core) - do not move hardware on it.
5. `absolute=True` (default) puts x in detector coordinates, so centres from different ROIs are comparable. Pixel size comes from the active profile unless `pixel_um` is given.

Differences from the ImageJ originals: Gaussian parameters are offset/amp/centre/sigma (ImageJ's `b` is the peak = offset+amp; reported as `derived.peak`);
slit bounds are relative to the data (the Java code hard-codes pixel limits and forbids a negative offset); fits use scipy `least_squares` with several starts
instead of ImageJ's simplex and its 4-try retry loop. EPICS userCalc output, ImageJ GUI and NTNDArray decoding were NOT ported (BLADE has its own backends).
