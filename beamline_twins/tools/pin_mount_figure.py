"""Figure of the 3-D pin-mount model (blade/physics/pin_mount.py) and of the tomo views the simulator renders from it.  OFFLINE, simulation only.

    python beamline_twins/tools/pin_mount_figure.py [out.png]

Left: shaded 3-D model (dimensions are the photo estimates of sim.json - see its `mount._note`). Right: gh1 frames from the virtual beamline (noise off) at
omega = 0 / 45 / 90 deg with the tip on the beam, and with the stage raised so the chuck's nose edge crosses the beam."""
import math
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from blade.physics import pin_mount as pm                      # noqa: E402
from blade.vbl.world import VirtualBeamline                    # noqa: E402
from blade.vbl import imaging as im                            # noqa: E402

try:
    import cmcrameri.cm as cmc
    CMAP = cmc.lapaz
except Exception:
    CMAP = "viridis"
FONT = "Lato" if any(f.name == "Lato" for f in fm.fontManager.ttflist) else "DejaVu Sans"
plt.rcParams.update({"font.family": FONT, "font.size": 7, "axes.labelsize": 7, "axes.titlesize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
                     "axes.linewidth": 0.5, "xtick.major.width": 0.5, "ytick.major.width": 0.5})
COLORS = {"pin": "#c9d1d6", "chuck": "#c8a24a", "rod": "#8a8f94", "nut": "#6f7378", "block_upper": "#2b2b2b", "block_lower": "#3a3a3a"}


def _revolve(ax, y_top, y_bot, r_top, r_bot, color, n=40):
    th = np.linspace(0, 2 * np.pi, n)
    Y = np.array([y_top, y_bot])
    R = np.array([r_top, r_bot])
    X = R[:, None] * np.cos(th)[None, :]
    Z = R[:, None] * np.sin(th)[None, :]
    ax.plot_surface(X, Z, np.repeat(Y[:, None], n, 1), color=color, linewidth=0, shade=True, antialiased=False)


def _box(ax, w, d, y_top, h, color):
    x, z, y0, y1 = w / 2, d / 2, y_top - h, y_top
    v = np.array([[-x, -z, y0], [x, -z, y0], [x, z, y0], [-x, z, y0], [-x, -z, y1], [x, -z, y1], [x, z, y1], [-x, z, y1]])
    faces = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6], [1, 2, 6, 5], [0, 3, 7, 4]]
    ax.add_collection3d(Poly3DCollection([v[f] for f in faces], facecolor=color, edgecolor="#111", linewidth=0.3))


def draw_mount(ax, M):
    """Draw with plot axes (X, Z, Y) = (mount x, mount z, mount y up) so the vertical axis is the pin axis."""
    p = M.p
    r_sh = p["pin"]["shaft_diameter_mm"] / 2
    r_top = p["pin"]["top_width_um"] * 5e-4
    _revolve(ax, 0, -M.cone_depth_mm, r_top, r_sh, COLORS["pin"])
    ytop = -p["pin"]["protrusion_mm"]
    _revolve(ax, 0 - M.cone_depth_mm, ytop, r_sh, r_sh, COLORS["pin"])
    ch = p["chuck"]
    yn = ytop - ch["nose_len_mm"]
    yb = yn - ch["body_len_mm"]
    _revolve(ax, ytop, yn, ch["nose_top_dia_mm"] / 2, ch["body_dia_mm"] / 2, COLORS["chuck"])
    _revolve(ax, yn, yb, ch["body_dia_mm"] / 2, ch["body_dia_mm"] / 2, COLORS["chuck"])
    yrod = yb - p["rod"]["exposed_mm"]
    _revolve(ax, yb, yrod, p["rod"]["dia_mm"] / 2, p["rod"]["dia_mm"] / 2, COLORS["rod"])
    _revolve(ax, yrod, yrod - p["nut"]["thick_mm"], p["nut"]["af_mm"] / math.sqrt(3), p["nut"]["af_mm"] / math.sqrt(3), COLORS["nut"], n=7)
    y = yrod - p["nut"]["thick_mm"]
    for b in p["blocks"]:
        _box(ax, b["w_mm"], b["d_mm"], y, b["h_mm"], COLORS["block_" + b["name"]])
        y -= b["h_mm"]
    ax.set_xlim(-14, 14); ax.set_ylim(-14, 14); ax.set_zlim(-M.tip_height_mm, 2)
    ax.set_box_aspect((1, 1, M.tip_height_mm / 28))
    ax.view_init(elev=14, azim=-58)
    ax.set_axis_off()


def frames():
    out = []
    w = VirtualBeamline(seed=3, scenario="ready_for_pin")
    for n in ("slitEus", "slitEds"):
        w.set(n + ".hsize", 1.6); w.set(n + ".vsize", 1.3)
    w.set("wbSlits.hsize", 0.9); w.set("wbSlits.vsize", 0.9)
    w.s["truth"]["pin"]["c_axis_off_beam_mm"] = 0.0
    yref = w.sim["stage_E"]["y_ref_mm"]
    M = w.pin_mount()
    for om in (0, 45, 90):
        w.set("samE.ry", om)
        img = im.render(w, "gh1", bin_=2, with_noise=False)
        out.append((f"ω = {om}°\ntip on beam", img))
    w.set("samE.ry", 0)
    w.set("samE.y", yref + M.part_tip_offset_mm("chuck", "top") - 0.15)       # chuck nose edge just above the beam centre
    out.append(("stage +4.9 mm\nchuck edge", im.render(w, "gh1", bin_=2, with_noise=False)))
    w.set("samE.aerox", w.ctl("samE.aerox") + 0.9)
    out.append(("axis moved 0.9 mm\npin out of view", im.render(w, "gh1", bin_=2, with_noise=False)))
    return out


def main(out):
    w0 = VirtualBeamline(seed=3, scenario="ready_for_pin")
    M = w0.pin_mount()
    fr = frames()
    fig = plt.figure(figsize=(7.4, 3.1))
    ax = fig.add_axes([0.0, 0.0, 0.26, 1.0], projection="3d")
    draw_mount(ax, M)
    ax.text2D(0.02, 0.97, f"tip {M.tip_height_mm:.1f} mm above the stage plate (photo estimate)", transform=ax.transAxes, va="top")
    n = len(fr)
    for i, (title, img) in enumerate(fr):
        a = fig.add_axes([0.285 + i * 0.143, 0.12, 0.135, 0.72])
        a.imshow(img.astype(float), cmap=CMAP, vmin=float(np.percentile(img, 1)), vmax=float(np.percentile(img, 99.5)))
        a.set_title(title, fontsize=6, pad=2)
        a.set_xticks([]); a.set_yticks([])
    fig.text(0.285, 0.04, "gh1 frames from the virtual beamline (noise off); each panel 1.34 mm wide", fontsize=6)
    fig.savefig(out, dpi=300, facecolor="none", bbox_inches="tight", pad_inches=0.03)
    print("wrote", out, "font:", FONT)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "beamline_twins" / "1-ID" / "physics" / "fits" / "pin_mount.png"))
