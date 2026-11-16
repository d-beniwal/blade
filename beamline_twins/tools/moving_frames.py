"""Keep only the frames of a tomo-alignment HDF5 file during which the rotation stage was moving.  OFFLINE data tool; never touches the original.

    python moving_frames.py SRC.h5 [SRC2.h5 ...] --out-dir DIR [--ry-path instrument/SMS/E/HR/samRy] [--eps 0.01]

Rule (stated so it can be challenged): a frame is MOVING if the stage readback differs from the previous frame's by more than `eps` degrees (default 0.01: the dwell
jitter of this stage is ~1e-4 deg, the sweep steps are >= 0.9 deg). The kept frames are the contiguous range from the first to the last moving frame, so frames inside the
sweep whose readback was merely stale (the same PV value twice while the stage was still moving) stay; the dwell frames before and after the sweep are dropped.

The output has the same structure as the input: every group, dataset, attribute, dtype, chunking, maxshape, fill value and compression is copied; every per-frame
dataset (first axis == number of frames: the images, timestamps, unique ids, all PV monitors, misc/*, performance/timestamp) is sliced to the kept frames; everything else
(one-per-file scalars, the single dark and white frame) is copied unchanged. Values are NOT edited (frame ids and timestamps keep their original numbers, so the kept frames
can be traced back; the detector's absolute counter `DetArrayCounter` is not changed either). Three root attributes record the provenance."""
import argparse
import json
import sys
from pathlib import Path
import h5py
import numpy as np

DEFAULT_RY = "instrument/SMS/E/HR/samRy"        # hutch E rotation stage readback, PV 1ide:m9.RBV in the files' NDAttrSource (checked in the file attributes below)


def moving_range(ry, eps):
    """(first, last, mask) of the moving frames; mask is per frame (True where the readback changed by > eps from the previous frame)."""
    ry = np.asarray(ry, float)
    mask = np.zeros(ry.size, bool)
    mask[1:] = np.abs(np.diff(ry)) > eps
    if not mask.any():
        raise ValueError("the rotation stage did not move in this file")
    idx = np.nonzero(mask)[0]
    return int(idx[0]), int(idx[-1]), mask


def _attrs(src, dst):
    for k in src.attrs.keys():
        aid = src.attrs.get_id(k)
        dst.attrs.create(k, src.attrs[k], shape=aid.shape, dtype=aid.dtype)


def _copy_dataset(src, parent, name, keep, n_frames):
    per_frame = src.ndim >= 1 and src.shape[0] == n_frames
    shape = ((len(keep),) + src.shape[1:]) if per_frame else src.shape
    maxshape = src.maxshape
    if per_frame and maxshape[0] is not None:
        maxshape = (len(keep) if maxshape[0] == src.shape[0] else maxshape[0],) + maxshape[1:]
    kw = {"dtype": src.dtype, "fillvalue": src.fillvalue}
    if src.chunks is not None:
        kw.update(chunks=src.chunks, maxshape=maxshape, compression=src.compression, compression_opts=src.compression_opts, shuffle=src.shuffle)
    d = parent.create_dataset(name, shape=shape, **kw)
    if per_frame:
        if src.ndim >= 3:                                         # images: one frame at a time (memory)
            for j, i in enumerate(keep):
                d[j] = src[i]
        else:
            d[...] = src[keep[0]:keep[-1] + 1]
    elif src.shape == ():
        d[()] = src[()]
    else:
        d[...] = src[...]
    _attrs(src, d)
    return per_frame


def convert(src_path, out_path, ry_path=DEFAULT_RY, eps=0.01):
    src_path, out_path = Path(src_path), Path(out_path)
    if out_path.exists():
        raise FileExistsError(f"refusing to overwrite {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(src_path, "r") as f:
        n = f["exchange/data"].shape[0]
        ry = f[ry_path][:]
        if ry.shape != (n,):
            raise ValueError(f"{ry_path} has shape {ry.shape}, expected ({n},)")
        first, last, mask = moving_range(ry, eps)
        keep = list(range(first, last + 1))
        sliced = []
        with h5py.File(out_path, "w") as g:
            def walk(sg, dg):
                _attrs(sg, dg)
                for k in sg.keys():
                    o = sg[k]
                    if isinstance(o, h5py.Dataset):
                        if _copy_dataset(o, dg, k, keep, n):
                            sliced.append(o.name)
                    else:
                        walk(o, dg.create_group(k))
            walk(f, g)
            g.attrs["blade_source_file"] = src_path.name
            g.attrs["blade_kept_frames"] = np.array(keep, dtype=np.int32)
            g.attrs["blade_selection_rule"] = f"frames from the first to the last whose {ry_path} differs from the previous frame by > {eps} deg (contiguous)"
        info = {"source": src_path.name, "n_source_frames": n, "n_kept": len(keep), "kept_index_first": first, "kept_index_last": last, "eps_deg": eps, "ry_path": ry_path,
                "ry_pv": f[ry_path].attrs.get("NDAttrSource", b"").decode() if isinstance(f[ry_path].attrs.get("NDAttrSource", b""), bytes) else str(f[ry_path].attrs.get("NDAttrSource")),
                "ry_kept_deg": [round(float(x), 4) for x in ry[keep]], "dropped_before": first, "dropped_after": n - 1 - last, "sliced_datasets": len(sliced)}
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src", nargs="+")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--ry-path", default=DEFAULT_RY)
    ap.add_argument("--eps", type=float, default=0.01)
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    res = []
    for s in a.src:
        s = Path(s)
        info = convert(s, out / s.parent.name / s.name, a.ry_path, a.eps)
        res.append(info)
        print(f"{s.name}: kept {info['n_kept']}/{info['n_source_frames']} frames (index {info['kept_index_first']}..{info['kept_index_last']}), dropped {info['dropped_before']} before + {info['dropped_after']} after; Ry {info['ry_kept_deg'][0]} -> {info['ry_kept_deg'][-1]} deg")
    (out / "moving_frames_report.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main()
