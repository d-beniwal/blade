"""3-D model of the tomo alignment pin and the mount it sits on (SIMULATION; geometry from `stage_E.pin.mount` in beamline_twins/<bl>/sim.json).

What is modelled (top to bottom, see the photo description in the DECISIONS entry of 2026-11-15): a sharpened tungsten pin (truncated cone -> shaft) clamped in a brass
pin-vise chuck (tapered nose, body with a cross hole), which is screwed onto a threaded rod; the rod stands in a hex nut on two stacked black blocks that are magnetically
held on the Kohzu sample stage. The mount is FIXED, only the rod's exposed length (the screw) changes how high the pin tip is above the stage plate.

Method: exact ray casting. Each solid is a convex primitive (frustum / convex polyhedron = intersection of slabs); a ray through a primitive gives ONE interval, so
the chord length through a part is  sum(solid chords) - sum(chord of solid AND void)  with no sampling. The beam is a parallel bundle along the lab z axis; the
thickness map on a (u, v) grid is the path length of every ray through every material, and the transmission is exp(-sum mu_i t_i) (xraydb through `physics.core`).

Frames (mm):  lab  u = horizontal (increases to the image right), v = vertical (up), z = along the beam.
              mount  origin at the pin tip (centre of its flat top), y up the pin axis, so every part lies at y <= 0.
              lab = R_lean . R_y(omega + azimuth) . mount + tip       (R_y(w) maps (x,z) -> (x cos w + z sin w, -x sin w + z cos w): the BLADE convention
              x(w) = c + a cos w + b sin w for an off-axis point; R_lean tilts the whole body about the TIP in the image plane (tilt of the pin axis).)
Limits: orthographic projection (the ~um beam divergence over the few mm of depth is ignored); threads, knurling and the chuck's bore walls are not modelled (the
rod is a plain cylinder, the bore is filled by the pin); no refraction / phase contrast (the imaging module adds an edge ripple)."""
import math
from functools import lru_cache
import numpy as np
from . import core as pcore

_TINY = 1e-12
# material name -> (xraydb formula, density g/cm3). brass 60/40 Cu/Zn by weight ~ Cu3Zn2; steel ~ Fe; black blocks = anodised aluminium (all ASSUMED, see sim.json)
MATERIALS = {"W": ("W", 19.3), "brass": ("Cu3Zn2", 8.5), "steel": ("Fe", 7.87), "Al": ("Al", 2.70)}


@lru_cache(maxsize=256)
def mu_per_mm(material, energy_keV):
    f, rho = MATERIALS[material]
    return pcore.mu_per_cm(f, float(energy_keV), density=rho) / 10.0


# ------------------------------------------------------------------------------------------------------------------------------ rotations
def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def rot_z(rad):
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _lin(Rrow, Px, Py, Pz):
    return Rrow[0] * Px + Rrow[1] * Py + Rrow[2] * Pz


# ------------------------------------------------------------------------------------------------------------------------------ primitives
class Solid:
    """Convex solid. interval(P, D): P = (Px, Py, Pz) broadcastable arrays (ray origins in the mount frame), D = (3,) common ray direction.
    Returns (lo, hi) arrays; hi <= lo means the ray misses."""
    def interval(self, P, D):
        raise NotImplementedError


class Frustum(Solid):
    """Circular frustum about the local y axis from y_bot to y_top with radii r_bot, r_top; placed by a local frame (rows of R = local axes in the parent frame,
    centre c). A cylinder is r_top = r_bot."""
    def __init__(self, y_top, y_bot, r_top, r_bot, R=None, c=(0.0, 0.0, 0.0)):
        assert y_top > y_bot and r_top >= 0 and r_bot >= 0
        self.yt, self.yb, self.rt, self.rb = float(y_top), float(y_bot), float(r_top), float(r_bot)
        self.R = np.eye(3) if R is None else np.asarray(R, float)
        self.c = np.asarray(c, float)
        self.k = (self.rb - self.rt) / (self.yt - self.yb)

    def interval(self, P, D):
        Px, Py, Pz = (P[0] - self.c[0], P[1] - self.c[1], P[2] - self.c[2])
        x = _lin(self.R[0], Px, Py, Pz)
        y = _lin(self.R[1], Px, Py, Pz)
        z = _lin(self.R[2], Px, Py, Pz)
        d = self.R @ np.asarray(D, float)
        a1, b1, c1 = d[0] ** 2 + d[2] ** 2, x * d[0] + z * d[2], x * x + z * z
        al = self.rt + self.k * (self.yt - y)
        be = self.k * d[1]
        a, b, c = a1 - be * be, b1 + al * be, c1 - al * al
        if a < -1e-9:
            raise ValueError("ray steeper than the cone's generator: tilt outside the model's range")
        if a > 1e-9:                                         # general case: between the two roots of  a t^2 + 2 b t + c <= 0
            disc = b * b - a * c
            ok = disc > 0
            sq = np.sqrt(np.where(ok, disc, 0.0))
            t0, t1 = (-b - sq) / a, (-b + sq) / a
        else:                                                # ray along the axis of a cylinder (a = 0): inside for all t when c <= 0 (b = 0), else a half line
            ok = np.ones(np.shape(c), bool) if np.ndim(c) else True
            bb = np.where(np.abs(b) > 1e-12, b, 1e-12)
            root = -c / (2.0 * bb)
            flat = np.abs(b) <= 1e-12
            t0 = np.where(flat, np.where(c <= 0, -np.inf, np.inf), np.where(b > 0, -np.inf, root))
            t1 = np.where(flat, np.where(c <= 0, np.inf, -np.inf), np.where(b > 0, root, np.inf))
        if abs(d[1]) > _TINY:
            ta, tb = (self.yb - y) / d[1], (self.yt - y) / d[1]
            lo_y, hi_y = np.minimum(ta, tb), np.maximum(ta, tb)
        else:
            inside = (y >= self.yb) & (y <= self.yt)
            lo_y, hi_y = np.where(inside, -np.inf, np.inf), np.where(inside, np.inf, -np.inf)
        lo, hi = np.maximum(t0, lo_y), np.minimum(t1, hi_y)
        return np.where(ok, lo, 0.0), np.where(ok, hi, 0.0)       # (a miss gives lo = hi = 0)


class Slabs(Solid):
    """Intersection of slabs  lo_i <= n_i . x <= hi_i  (box, hex prism, half-space cut). Normals are unit vectors in the parent frame."""
    def __init__(self, normals, lo, hi):
        self.n = [np.asarray(n, float) / np.linalg.norm(n) for n in normals]
        self.lo, self.hi = list(lo), list(hi)

    def interval(self, P, D):
        D = np.asarray(D, float)
        lo, hi = -np.inf, np.inf
        for n, l, h in zip(self.n, self.lo, self.hi):
            s, d = n[0] * P[0] + n[1] * P[1] + n[2] * P[2], float(n @ D)
            if abs(d) < _TINY:
                bad = (s < l) | (s > h)
                lo, hi = np.where(bad, np.inf, lo), np.where(bad, -np.inf, hi)
                continue
            t1, t2 = (l - s) / d, (h - s) / d
            lo, hi = np.maximum(lo, np.minimum(t1, t2)), np.minimum(hi, np.maximum(t1, t2))
        return lo, hi


class Both(Solid):
    """Intersection of convex solids (still convex)."""
    def __init__(self, *solids):
        self.s = solids

    def interval(self, P, D):
        lo, hi = None, None
        for s in self.s:
            l, h = s.interval(P, D)
            lo, hi = (l, h) if lo is None else (np.maximum(lo, l), np.minimum(hi, h))
        return lo, hi


def box(w, d, h, y_top, name=None):
    """Axis-aligned box centred on the pin axis: x in +-w/2, z in +-d/2, y in [y_top - h, y_top]."""
    return Slabs([(1, 0, 0), (0, 1, 0), (0, 0, 1)], [-w / 2, y_top - h, -d / 2], [w / 2, y_top, d / 2])


def hexprism(af, y_top, y_bot):
    ang = [0.0, 60.0, 120.0]
    n = [(math.cos(math.radians(a)), 0.0, math.sin(math.radians(a))) for a in ang] + [(0, 1, 0)]
    return Slabs(n, [-af / 2] * 3 + [y_bot], [af / 2] * 3 + [y_top])


def horizontal_cylinder(radius, y_c, azimuth_deg, half_len=100.0):
    """Cylinder whose axis is horizontal (in the mount x-z plane at `azimuth_deg` from mount x), through the pin axis at height y_c."""
    h = np.array([math.cos(math.radians(azimuth_deg)), 0.0, math.sin(math.radians(azimuth_deg))])
    e1 = np.array([0.0, 1.0, 0.0])
    e3 = np.cross(e1, h)
    return Frustum(half_len, -half_len, radius, radius, R=np.array([e1, h, e3]), c=(0.0, y_c, 0.0))


class Part:
    """One body: material, convex solids (their union must not overlap each other) minus convex voids; y_range (mount frame) and r_max for culling."""
    def __init__(self, name, material, solids, voids=(), y_range=(0.0, 0.0), r_max=0.0):
        self.name, self.material, self.solids, self.voids = name, material, list(solids), list(voids)
        self.y_range, self.r_max = y_range, r_max

    def chord(self, P, D):
        total = 0.0
        vi = [v.interval(P, D) for v in self.voids]
        for s in self.solids:
            lo, hi = s.interval(P, D)
            L = np.clip(hi - lo, 0.0, None)
            for vl, vh in vi:
                L = L - np.clip(np.minimum(hi, vh) - np.maximum(lo, vl), 0.0, None)
            total = total + np.clip(L, 0.0, None)
        return total


# ------------------------------------------------------------------------------------------------------------------------------ the mount
class Mount:
    """The pin + holder + stack. `params` = sim.json `stage_E.pin.mount` plus the pin's own `top_width_um` / `half_angle_deg` (see `from_sim`)."""
    def __init__(self, p):
        self.p = p
        pin, ch, rod, nut, blk = p["pin"], p["chuck"], p["rod"], p["nut"], p["blocks"]
        r_top, r_sh = pin["top_width_um"] * 5e-4, pin["shaft_diameter_mm"] / 2.0
        ta = math.tan(math.radians(pin["half_angle_deg"]))
        self.cone_depth_mm = max((r_sh - r_top) / ta, 0.0)
        y_nose_top = -pin["protrusion_mm"]
        y_nose_bot = y_nose_top - ch["nose_len_mm"]
        y_body_bot = y_nose_bot - ch["body_len_mm"]
        y_nut_top = y_body_bot - rod["exposed_mm"]
        y_nut_bot = y_nut_top - nut["thick_mm"]
        parts = []
        # pin: cone + shaft down into the chuck (a bevel plane cuts the top if bevel_deg > 0)
        cone = Frustum(0.0, -self.cone_depth_mm, r_top, r_sh) if self.cone_depth_mm > 0 else None
        shaft = Frustum(-self.cone_depth_mm, -(pin["protrusion_mm"] + pin["inside_chuck_mm"]), r_sh, r_sh)
        if pin.get("bevel_deg", 0.0) > 0:
            b, psi = math.radians(pin["bevel_deg"]), math.radians(pin.get("bevel_azimuth_deg", 0.0))
            cut = Slabs([(math.sin(b) * math.cos(psi), math.cos(b), math.sin(b) * math.sin(psi))], [-1e3], [0.0])
            cone = Both(cone, cut) if cone is not None else None
        parts.append(Part("pin", pin.get("material", "W"), ([cone] if cone is not None else []) + [shaft], y_range=(-(pin["protrusion_mm"] + pin["inside_chuck_mm"]), 0.0), r_max=r_sh))
        # chuck: tapered nose + body; the bore (filled by the pin) and the cross hole are voids
        rb = ch["body_dia_mm"] / 2.0
        nose = Frustum(y_nose_top, y_nose_bot, ch["nose_top_dia_mm"] / 2.0, rb)
        body = Frustum(y_nose_bot, y_body_bot, rb, rb)
        bore = Frustum(y_nose_top + 1e-3, -(pin["protrusion_mm"] + pin["inside_chuck_mm"]), r_sh, r_sh)
        hole = horizontal_cylinder(ch["cross_hole_dia_mm"] / 2.0, y_body_bot + ch["cross_hole_from_bottom_mm"], ch.get("cross_hole_azimuth_deg", 0.0))
        parts.append(Part("chuck", ch.get("material", "brass"), [nose, body], voids=[bore, hole], y_range=(y_body_bot, y_nose_top), r_max=rb))
        # rod (plain cylinder; it enters the chuck by `into_chuck_mm`, which is inside the opaque body anyway) and the nut
        parts.append(Part("rod", rod.get("material", "steel"), [Frustum(y_body_bot + rod["into_chuck_mm"], y_nut_top, rod["dia_mm"] / 2.0, rod["dia_mm"] / 2.0)],
                          y_range=(y_nut_top, y_body_bot + rod["into_chuck_mm"]), r_max=rod["dia_mm"] / 2.0))
        parts.append(Part("nut", nut.get("material", "steel"), [hexprism(nut["af_mm"], y_nut_top, y_nut_bot)], y_range=(y_nut_bot, y_nut_top), r_max=nut["af_mm"] / math.sqrt(3.0)))
        y = y_nut_bot
        for b_ in blk:                                                    # upper block first (listed top to bottom)
            parts.append(Part("block_" + b_["name"], b_.get("material", "Al"), [box(b_["w_mm"], b_["d_mm"], b_["h_mm"], y)], y_range=(y - b_["h_mm"], y),
                              r_max=math.hypot(b_["w_mm"], b_["d_mm"]) / 2.0))
            y -= b_["h_mm"]
        self.parts = parts
        self.tip_height_mm = -y                                          # tip height above the stage plate the lower block rests on
        self.layers_mm = {"pin_protrusion": pin["protrusion_mm"], "chuck": ch["nose_len_mm"] + ch["body_len_mm"], "rod_exposed": rod["exposed_mm"],
                          "nut": nut["thick_mm"], "blocks": sum(b_["h_mm"] for b_ in blk)}
        self.azimuth_deg = float(p.get("azimuth_deg", 0.0))

    # ------------------------------------------------------------------------------------------------------------------------ geometry helpers
    def part_tip_offset_mm(self, name, which="top"):
        """Distance below the pin tip (mm, >= 0) of a part's top / bottom surface (the chuck's top edge is `protrusion` below the tip)."""
        pr = next(q for q in self.parts if q.name == name)
        return -pr.y_range[1] if which == "top" else -pr.y_range[0]

    def chuck_radius_mm(self):
        return self.p["chuck"]["body_dia_mm"] / 2.0

    def with_rod_exposed(self, exposed_mm):
        """A copy with a different rod height (the screw): the one adjustable dimension of the mount."""
        import copy
        q = copy.deepcopy(self.p)
        q["rod"]["exposed_mm"] = float(exposed_mm)
        return Mount(q)

    # ------------------------------------------------------------------------------------------------------------------------ projection
    def thickness(self, u, v, tip_u, tip_v, omega_deg=0.0, lean_rad=0.0, parts=None, v_margin_mm=0.0):
        """Path length [mm] of every ray (grid: u (W,) columns, v (H,) rows, lab mm; the ray through (u, v) runs along z) through each material.
        Returns {material: (H, W) array} summed over parts, and {part: (H, W)} for the parts that overlap the window (others are skipped: cheap for a ~mm window
        far from the chuck)."""
        u, v = np.asarray(u, float), np.asarray(v, float)
        Rl = rot_z(lean_rad)
        Rm = Rl @ rot_y(omega_deg + self.azimuth_deg)                      # mount -> lab
        Rinv = Rm.T
        du, dv = (u - tip_u)[None, :], (v - tip_v)[:, None]
        P = tuple(Rinv[i, 0] * du + Rinv[i, 1] * dv for i in range(3))     # z = 0 row of the lab ray origin: only chord lengths matter
        D = Rinv @ np.array([0.0, 0.0, 1.0])
        vlo, vhi = float(v.min()) - tip_v - v_margin_mm, float(v.max()) - tip_v + v_margin_mm
        by_part, by_mat = {}, {}
        cl = math.cos(lean_rad)
        for pt in self.parts:
            if parts is not None and pt.name not in parts:
                continue
            lo_y, hi_y = pt.y_range
            if hi_y * cl + pt.r_max < vlo or lo_y * cl - pt.r_max > vhi:       # entirely above / below the window
                continue
            L = pt.chord(P, D)
            if np.ndim(L) == 0 or not np.any(L > 0):
                continue
            by_part[pt.name] = L
            by_mat[pt.material] = by_mat.get(pt.material, 0.0) + L
        return by_mat, by_part

    def transmission(self, u, v, tip_u, tip_v, energy_keV, omega_deg=0.0, lean_rad=0.0, **kw):
        """exp(-sum mu t) of every ray, (H, W); 1 = clear. Also the thickness dict."""
        by_mat, by_part = self.thickness(u, v, tip_u, tip_v, omega_deg, lean_rad, **kw)
        H, W = len(v), len(u)
        mut = np.zeros((H, W))
        for m, t in by_mat.items():
            mut = mut + mu_per_mm(m, round(float(energy_keV), 3)) * t
        return np.exp(-mut), by_part


def from_sim(sim):
    """Mount from the machine knowledge (`sim.json` -> stage_E.pin): the pin's own cone numbers + its `mount` block."""
    pin = sim["stage_E"]["pin"]
    p = {k: (dict(v) if isinstance(v, dict) else v) for k, v in pin["mount"].items() if not k.endswith("_src") and k != "_note"}
    p["pin"] = dict(p["pin"], top_width_um=pin["top_width_um"], half_angle_deg=pin["half_angle_deg"])
    p["blocks"] = [dict(b) for b in pin["mount"]["blocks"]]
    return Mount(p)
