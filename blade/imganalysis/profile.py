"""ROI line profiles of a camera frame, ported from ImageJ ProfilePlot as used in Gaussian_Profiler / LiveFitter_EPICSUserCalc.

ImageJ semantics kept: a rectangle ROI gives the MEAN over the rows (horizontal profile) or over the columns (vertical profile); a line ROI is sampled with
optional interpolation. The x axis is calibrated (pixel size) and, with `absolute=True` ("Absolute Pixel Scale" in LiveFitter), starts at the ROI's position
in the image instead of 0, so fitted centres are in detector coordinates and can be compared across ROIs. Pure numpy/scipy; no ImageJ.
"""
import numpy as np
from scipy.ndimage import map_coordinates


def load_image(path):
    """Load a frame from .npy, .npz (first array), .h5/.hdf5 (first 2-D dataset) or any PIL image (.png/.tif/.jpg); returns a float 2-D array (grey)."""
    p = str(path)
    low = p.lower()
    if low.endswith(".npy"):
        a = np.load(p)
    elif low.endswith(".npz"):
        z = np.load(p)
        a = z[z.files[0]]
    elif low.endswith((".h5", ".hdf5")):
        import h5py
        out = []
        with h5py.File(p, "r") as f:
            f.visititems(lambda n, o: out.append(n) if hasattr(o, "shape") and len(o.shape) >= 2 and not out else None)
            if not out:
                raise ValueError("no 2-D dataset in file")
            a = f[out[0]][...]
    else:
        from PIL import Image
        a = np.asarray(Image.open(p))
    a = np.asarray(a, float)
    while a.ndim > 2:
        a = a.mean(axis=0) if a.shape[0] <= 4 or a.ndim > 3 else a.mean(axis=-1)
    return a


def rect_profile(img, x0, y0, x1, y1, direction="horizontal", pixel_um=1.0, absolute=True):
    """Mean profile of the rectangle [x0,x1) x [y0,y1) (pixel indices, columns x, rows y). direction 'horizontal' averages over rows and runs along x;
    'vertical' averages over columns and runs along y. Returns {x (um if pixel_um given else px, pixel centres), y, unit, roi}."""
    H, W = img.shape
    x0, x1 = sorted((int(round(x0)), int(round(x1))))
    y0, y1 = sorted((int(round(y0)), int(round(y1))))
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, W), min(y1, H)
    if x1 - x0 < 2 or y1 - y0 < 1:
        raise ValueError("ROI too small or outside the image")
    box = img[y0:y1, x0:x1]
    if direction == "vertical":
        y = box.mean(axis=1)
        start = y0
    else:
        y = box.mean(axis=0)
        start = x0
    n = len(y)
    idx = (start if absolute else 0) + np.arange(n)
    return {"x": (idx * pixel_um).tolist(), "y": y.tolist(), "unit": "um" if pixel_um != 1.0 else "px", "pixel_um": pixel_um,
            "roi": {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "direction": direction, "absolute": absolute}}


def line_profile(img, x0, y0, x1, y1, pixel_um=1.0, interpolate=True, width=1, absolute=True):
    """Profile along the line (x0,y0)->(x1,y1) in pixel coordinates, one sample per pixel of length, linear interpolation (ImageJ 'interpolate line'), averaged over
    `width` pixels perpendicular to the line. With absolute=True and a purely horizontal/vertical line the distance axis starts at the line's x (resp. y), as in
    LiveFitter; otherwise it starts at 0."""
    L = float(np.hypot(x1 - x0, y1 - y0))
    if L < 2:
        raise ValueError("line too short")
    n = int(round(L)) + 1
    t = np.linspace(0, 1, n)
    xs, ys = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
    nx, ny = -(y1 - y0) / L, (x1 - x0) / L
    offs = np.arange(width) - (width - 1) / 2.0
    acc = np.zeros(n)
    for o in offs:
        acc += map_coordinates(img, [ys + o * ny, xs + o * nx], order=1 if interpolate else 0, mode="nearest")
    y = acc / len(offs)
    d = np.linspace(0, L, n) * pixel_um
    if absolute and y1 == y0:
        d = d + min(x0, x1) * pixel_um
    elif absolute and x1 == x0:
        d = d + min(y0, y1) * pixel_um
    return {"x": d.tolist(), "y": y.tolist(), "unit": "um" if pixel_um != 1.0 else "px", "pixel_um": pixel_um,
            "roi": {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "width": width}}
