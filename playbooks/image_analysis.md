# Image / profile analysis (module `imganalysis`)

Read-only tools (MCP: `analysis_*`, resource `blade://playbook/imganalysis`). Ported from the areaDetector ADViewers ImageJ plugins
(`Gaussian_Profiler`: live Gaussian fit for focusing/beam diagnostics; `LiveFitter_EPICSUserCalc`: any fit + slit aperture fit). Code: `blade/imganalysis/`.

1. `analysis_list_models` - catalogue (parameter names and formulas).
2. From a saved frame: `analysis_fit_roi` (rectangle, mean over the other axis, like ImageJ) or `analysis_fit_line` (line, interpolated, `width` px averaged).
   From numbers (motor/slit scan vs IC): `analysis_fit_profile`. `model='auto'` picks gaussian / erf_edge / slit_positive / slit_negative by BIC.
3. Which model: beam spot or focus -> `gaussian` (FWHM, peak, background, contrast%). One knife edge / slit blade -> `erf_edge` (centre, sigma, 10-90 width).
   Slit seen as a bright window -> `slit_positive_bowed`; dark blocker/pin in bright field -> `slit_negative_bowed` (centre, aperture width, edge sigma, plateau bow k1/k2).
   Prefer the **bowed** slit models on real frames: the beam has a hot core, so the plateau is not flat. `slit_positive` / `slit_negative` are the ADViewers
   LiveFitter models (straight tilt `slope` only). Real gh1 check (2026-11-13, `s1_data/tomo_alignment/alignment_pin/..._000044.h5`, dark-subtracted, 0.69 um/px):
   window along x, flat model R2 0.970, edge sigma 93 um (wrong); bowed R2 0.998, sigma 6.7 um, edges 308 / 1038 um (what the image shows). Vertical window: edges
   235 / 801 um, sigma 4.8 um. Pin shadow (rows 900-940, `slit_negative_bowed`): aperture 261 um, R2 0.989 (a cone, so the edge sigma of an averaged band is an upper bound).
   `erf_edge` on one window edge with a halo in the ROI gave sigma 30 um (R2 0.977): keep ROIs tight around an edge and compare with the slit fit.
4. Trust the fit only if `r2` is high (>~0.95) and the parameter `errors` are small; compare with the model-free `moments` (centroid, rms width, half-max FWHM).
   A big disagreement means the model is wrong (saturation, clipped beam, structured core) - do not move hardware on it.
5. `absolute=True` (default) puts x in detector coordinates, so centres from different ROIs are comparable. Pixel size comes from the active profile unless `pixel_um` is given.

Differences from the ImageJ originals: Gaussian parameters are offset/amp/centre/sigma (ImageJ's `b` is the peak = offset+amp; reported as `derived.peak`);
slit bounds are relative to the data (the Java code hard-codes pixel limits and forbids a negative offset); fits use scipy `least_squares` with several starts
instead of ImageJ's simplex and its 4-try retry loop. EPICS userCalc output, ImageJ GUI and NTNDArray decoding were NOT ported (BLADE has its own backends).

**Tomo-camera view of the virtual beamline (`/vbl`), redesigned 2026-11-13:** *intensity axes* shows column/row sums of the whole image with an automatic Gaussian fit
(centre, FWHM, R^2). *Draw box* (drag on the image) puts the box profile in the graph below the image instead (mean over the box rows = "horizontal", or columns =
"vertical"; switch with the two buttons in that card), with a *fit* menu (default auto = BIC over Gaussian, S-curve, slit window/blocker bowed). A slit fit reports both
edges, aperture, edge 10-90 % width and plateau bow, marks the edges on the plot and as circles on the image. Positions are um from the frame's left/top edge. One *live*
checkbox refreshes the frame, the axes and the box profile together. Backend: `vbl_api.profile` (box + direction + fit) and `vbl_api.fit_profile`, which calls
`blade.imganalysis.fitting`; the old line-profile tool (lines, width, "profile" and "follow live" buttons) was removed.
