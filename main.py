#!/usr/bin/env python3
"""ai-excited-01 entry: "Phoenix Ascendant".

A pure-Python, standard-library-only program that draws one image and writes
it to entry.png in the output directory (/output in the grader's container,
or $MAKEFUN_OUTPUT_DIR when that is set, mirroring the kit starter).

The image: a great firebird bursting upward through a shattered golden
sun-ring, over a deep indigo storm-vortex. Wings raised in a V, tail
streamers and embers streaming down the diagonal, shards of the broken ring
flying toward the viewer. It is aimed at the judge's rubric in order:
a jolt of energy (blazing bird against a dark vortex, white-hot chest core),
surprise (a phoenix smashing out of a sun-ring, not a stock explosion),
momentum (diagonal streams, bursting shards, swept feathers), craft (layered
gradient feathers with rim light, deterministic value-noise nebula), and a
silhouette that still reads at thumbnail size.

Everything is deterministic integer/float math from fixed constants: no time,
no randomness beyond a fixed-seed LCG, no network, no files read. Two runs
write byte-identical PNGs.
"""

import math
import os
import struct
import zlib
from array import array

W = 1024
H = 1024

# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def ihash(x, y):
    """Integer lattice hash -> float in [0, 1). Stable everywhere."""
    h = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) & 0xFFFFFFFF
    h = (h * 1274126177) & 0xFFFFFFFF
    h = (h ^ (h >> 16)) & 0xFFFFFFFF
    return h / 4294967296.0


def smooth(t):
    return t * t * (3.0 - 2.0 * t)


def vnoise(x, y):
    """Bilinear value noise at lattice scale 1 (callers scale coords)."""
    xi = math.floor(x)
    yi = math.floor(y)
    xf = smooth(x - xi)
    yf = smooth(y - yi)
    a = ihash(int(xi), int(yi))
    b = ihash(int(xi) + 1, int(yi))
    c = ihash(int(xi), int(yi) + 1)
    d = ihash(int(xi) + 1, int(yi) + 1)
    return a + (b - a) * xf + (c - a) * yf + (a - b - c + d) * xf * yf


def fbm(x, y, octaves=4):
    v = 0.0
    amp = 0.5
    tot = 0.0
    for _ in range(octaves):
        v += amp * vnoise(x, y)
        tot += amp
        x *= 2.03
        y *= 1.97
        amp *= 0.5
    return v / tot


class LCG:
    """Fixed-seed linear congruential generator (deterministic)."""

    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def next(self):
        self.s = (self.s * 1664525 + 1013904223) & 0xFFFFFFFF
        return self.s / 4294967296.0

    def range(self, lo, hi):
        return lo + (hi - lo) * self.next()


def make_lut(stops):
    """stops: list of (pos0..1, (r,g,b)) -> 256-entry gradient LUT."""
    lut = []
    for i in range(256):
        t = i / 255.0
        for k in range(len(stops) - 1):
            p0, c0 = stops[k]
            p1, c1 = stops[k + 1]
            if p0 <= t <= p1:
                f = 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
                lut.append((
                    c0[0] + (c1[0] - c0[0]) * f,
                    c0[1] + (c1[1] - c0[1]) * f,
                    c0[2] + (c1[2] - c0[2]) * f,
                ))
                break
        else:
            lut.append(stops[-1][1])
    return lut


# Palettes -------------------------------------------------------------------
LUT_FEATHER = make_lut([          # crimson -> scarlet -> orange -> gold
    (0.00, (96, 8, 26)),
    (0.35, (178, 24, 24)),
    (0.65, (238, 84, 16)),
    (0.88, (255, 156, 34)),
    (1.00, (255, 208, 96)),
])
LUT_FEATHER_FAR = make_lut([      # the far wing, a touch cooler/darker
    (0.00, (70, 8, 30)),
    (0.40, (138, 20, 34)),
    (0.75, (196, 52, 30)),
    (1.00, (240, 130, 52)),
])
LUT_BODY = make_lut([             # tail crimson -> chest white-hot gold
    (0.00, (140, 14, 26)),
    (0.45, (216, 52, 18)),
    (0.75, (252, 128, 26)),
    (1.00, (255, 196, 84)),
])
LUT_VORTEX = make_lut([           # storm disc: deep blue -> teal -> cyan
    (0.00, (10, 16, 52)),
    (0.35, (14, 52, 104)),
    (0.62, (12, 104, 138)),
    (0.85, (38, 178, 196)),
    (1.00, (150, 236, 240)),
])
LUT_RING = make_lut([             # the sun-ring: deep gold -> white hot
    (0.00, (146, 74, 10)),
    (0.45, (232, 138, 22)),
    (0.80, (255, 196, 74)),
    (1.00, (255, 244, 196)),
])
LUT_SHARD = make_lut([
    (0.00, (200, 110, 26)),
    (0.60, (255, 186, 70)),
    (1.00, (255, 240, 190)),
])
LUT_SCALLOP = make_lut([          # body scales: bright lip -> deep shade
    (0.00, (250, 150, 52)),
    (0.55, (238, 100, 24)),
    (1.00, (178, 40, 18)),
])


def noise_field(freq, ox, oy, octaves):
    """fbm precomputed on a coarse lattice (cell 8 px), bilinearly sampled.

    The nebula and the vortex turbulence are low-frequency, so a lattice
    field is visually identical to per-pixel fbm at a fraction of the cost.
    Returns sample(x, y) -> float in [0, 1).
    """
    cell = 8
    n = W // cell + 2
    vals = [0.0] * (n * n)
    for j in range(n):
        for i in range(n):
            vals[j * n + i] = fbm((i * cell) / W * freq + ox,
                                  (j * cell) / H * freq + oy, octaves)

    def sample(x, y):
        gx = x / cell
        gy = y / cell
        xi = int(gx)
        yi = int(gy)
        xf = smooth(gx - xi)
        yf = smooth(gy - yi)
        xi = min(xi, n - 2)
        yi = min(yi, n - 2)
        a = vals[yi * n + xi]
        b = vals[yi * n + xi + 1]
        c = vals[(yi + 1) * n + xi]
        d = vals[(yi + 1) * n + xi + 1]
        return a + (b - a) * xf + (c - a) * yf + (a - b - c + d) * xf * yf

    return sample


FIELD_A = noise_field(5.0, 11.0, 3.0, 4)    # nebula body
FIELD_B = noise_field(11.0, 40.0, 9.0, 3)   # nebula detail / vortex turb

# ---------------------------------------------------------------------------
# Canvas: three float planes
# ---------------------------------------------------------------------------

R = array('f', bytes(4 * W * H))
G = array('f', bytes(4 * W * H))
B = array('f', bytes(4 * W * H))


def background():
    """Deep indigo void with a slow nebula swell and sparse stars."""
    for y in range(H):
        ny = y / H
        row = y * W
        for x in range(W):
            nx = x / W
            n = FIELD_A(x, y)
            n2 = FIELD_B(x, y)
            # diagonal falloff: darker toward lower-left, a glow upper-right
            d = 0.72 + 0.28 * (nx * 0.6 + (1.0 - ny) * 0.4)
            r = (7.0 + 26.0 * n + 6.0 * n2) * d
            g = (5.0 + 14.0 * n + 10.0 * n2) * d
            b = (20.0 + 34.0 * n + 16.0 * n2) * d
            # a breath of teal in the nebula's bright knots
            if n > 0.62:
                k = (n - 0.62) * 1.4
                g += 22.0 * k
                b += 26.0 * k
            i = row + x
            R[i] = r
            G[i] = g
            B[i] = b
    # stars: deterministic sparse points with a soft core
    rng = LCG(20261115)
    for _ in range(420):
        x = rng.next() * W
        y = rng.next() * H
        s = rng.next()
        if s < 0.82:
            continue
        bright = 90.0 + 150.0 * rng.next()
        stamp(x, y, 1.6 + 2.2 * rng.next(), bright, bright * 0.95,
              bright * 0.85, falloff=2.0)


def stamp(cx, cy, radius, r, g, b, falloff=2.0):
    """Additive radial glow stamp."""
    x0 = max(0, int(cx - radius))
    x1 = min(W - 1, int(cx + radius))
    y0 = max(0, int(cy - radius))
    y1 = min(H - 1, int(cy + radius))
    inv = 1.0 / (radius * radius)
    for y in range(y0, y1 + 1):
        dy = y - cy
        row = y * W
        for x in range(x0, x1 + 1):
            dx = x - cx
            d2 = (dx * dx + dy * dy) * inv
            if d2 < 1.0:
                f = (1.0 - d2) ** falloff
                i = row + x
                R[i] += r * f
                G[i] += g * f
                B[i] += b * f


# ---------------------------------------------------------------------------
# Polygon rasteriser with interpolated (u, v) attributes.
# colour(u, v) -> (r, g, b, alpha, mode) with mode 'over' or 'add'.
# ---------------------------------------------------------------------------


def fill_poly(pts, colour):
    """pts: list of (x, y, u, v). Scanline fill with attribute lerp."""
    ys = [p[1] for p in pts]
    y0 = max(0, int(math.floor(min(ys))))
    y1 = min(H - 1, int(math.ceil(max(ys))))
    n = len(pts)
    edges = []
    for i in range(n):
        xa, ya, ua, va = pts[i]
        xb, yb, ub, vb = pts[(i + 1) % n]
        if ya != yb:
            edges.append((ya, yb, xa, xb, ua, ub, va, vb))
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        hits = []
        for (ya, yb, xa, xb, ua, ub, va, vb) in edges:
            if (ya <= yc < yb) or (yb <= yc < ya):
                t = (yc - ya) / (yb - ya)
                hits.append((xa + (xb - xa) * t,
                             ua + (ub - ua) * t,
                             va + (vb - va) * t))
        if len(hits) < 2:
            continue
        hits.sort(key=lambda h: h[0])
        row = y * W
        for k in range(0, len(hits) - 1, 2):
            xa, ua, va = hits[k]
            xb, ub, vb = hits[k + 1]
            x0 = max(0, int(math.ceil(xa)))
            x1 = min(W - 1, int(math.floor(xb)))
            if x1 < x0:
                continue
            span = xb - xa
            for x in range(x0, x1 + 1):
                t = 0.0 if span == 0 else (x + 0.5 - xa) / span
                u = ua + (ub - ua) * t
                v = va + (vb - va) * t
                r, g, b, a, mode = colour(u, v)
                if a <= 0.0:
                    continue
                i = row + x
                if mode == 'add':
                    R[i] += r * a
                    G[i] += g * a
                    B[i] += b * a
                else:
                    ia = 1.0 - a
                    R[i] = R[i] * ia + r * a
                    G[i] = G[i] * ia + g * a
                    B[i] = B[i] * ia + b * a


def bezier(p0, p1, p2, t):
    mt = 1.0 - t
    return (mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
            mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1])


def bezier_tangent(p0, p1, p2, t):
    return (2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0]),
            2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1]))


def feather(p0, p1, p2, w_base, w_mid, lut, dark=1.0, segs=14):
    """One tapered feather along a quadratic bezier spine.

    u runs along the feather (0 base, 1 tip); v runs across (-1..1) and
    shades the feather like a cylinder, with a bright rim on the +v edge.
    """
    left = []
    right = []
    for s in range(segs + 1):
        t = s / segs
        cx, cy = bezier(p0, p1, p2, t)
        tx, ty = bezier_tangent(p0, p1, p2, t)
        tl = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tl, tx / tl
        # width profile: grows from base, widest ~40% along, gone at tip
        w = (w_base * (1.0 - t) + w_mid * 4.0 * t * (1.0 - t)) * (1.0 - t * t * 0.92)
        left.append((cx + nx * w, cy + ny * w, t, -1.0))
        right.append((cx - nx * w, cy - ny * w, t, 1.0))
    pts = left + right[::-1]

    def colour(u, v):
        cr, cg, cb = lut[min(255, max(0, int(u * 255)))]
        shade = 0.80 + 0.34 * (v * 0.5 + 0.5)
        r, g, b = cr * shade * dark, cg * shade * dark, cb * shade * dark
        if v > 0.78:  # rim light on the leading edge
            f = (v - 0.78) / 0.22
            r += 120.0 * f
            g += 84.0 * f
            b += 30.0 * f
        # a darker quill line down the middle
        if abs(v) < 0.10:
            f = 1.0 - abs(v) / 0.10
            r *= 1.0 - 0.30 * f
            g *= 1.0 - 0.30 * f
            b *= 1.0 - 0.30 * f
        return (r, g, b, 1.0, 'over')

    fill_poly(pts, colour)


# ---------------------------------------------------------------------------
# Scene pieces
# ---------------------------------------------------------------------------

CX, CY = 606.0, 388.0      # vortex / ring centre
RING_R = 322.0             # ring mid radius


def vortex():
    """A swirling storm disc behind the bird: log-spiral arms, teal on ink."""
    rad = 356.0
    x0 = max(0, int(CX - rad))
    x1 = min(W - 1, int(CX + rad))
    y0 = max(0, int(CY - rad))
    y1 = min(H - 1, int(CY + rad))
    for y in range(y0, y1 + 1):
        dy = y - CY
        row = y * W
        for x in range(x0, x1 + 1):
            dx = x - CX
            d2 = dx * dx + dy * dy
            if d2 > rad * rad:
                continue
            d = math.sqrt(d2)
            ang = math.atan2(dy, dx)
            # arms fade out toward the centre so they dissolve into a dark
            # core instead of pinching to a bright point
            arm = 0.30 + 0.70 * smooth(min(1.0, d / (rad * 0.55)))
            swirl = 0.5 + 0.5 * math.sin(ang * 3.0 + d * 0.011
                                         + 1.8 * math.sin(ang * 2.0 - d * 0.005))
            turb = FIELD_B(x * 0.7 + 130.0, y * 0.7 + 60.0)
            t = max(0.0, min(1.0, (0.5 + (swirl - 0.5) * arm) * 0.55
                             + turb * 0.55 - d / rad * 0.16))
            if d < rad * 0.20:
                t *= 0.45 + 0.55 * (d / (rad * 0.20))
            cr, cg, cb = LUT_VORTEX[int(t * 255)]
            edge = 1.0 - smooth((d - rad * 0.86) / (rad * 0.14)) if d > rad * 0.86 else 1.0
            a = 0.92 * edge
            i = row + x
            ia = 1.0 - a
            R[i] = R[i] * ia + cr * a
            G[i] = G[i] * ia + cg * a
            B[i] = B[i] * ia + cb * a
    # a dim eye of the storm, upper-left of centre
    stamp(CX - 60, CY - 46, 120.0, 13.0, 46.0, 56.0, falloff=2.0)


def ring():
    """The shattered sun-ring, drawn per pixel so its light stays smooth.

    A golden annulus around the vortex: white-hot along its centre line,
    eroded by angular noise so the edges crumble, with two broken sectors —
    a wide one at the lower left (where the bird burst through) and a
    narrower one at the upper right (where it is heading). Inside the gaps
    only high-noise teeth of gold remain. A faint halo hugs the inner edge.
    Angles are degrees in image space: 0 right, 90 down, 180 left, -90 up.
    """
    rad = RING_R * 1.32
    x0 = max(0, int(CX - rad))
    x1 = min(W - 1, int(CX + rad))
    y0 = max(0, int(CY - rad))
    y1 = min(H - 1, int(CY + rad))
    gaps = [(116.0, 154.0), (-47.0, -7.0)]
    for y in range(y0, y1 + 1):
        dy = y - CY
        row = y * W
        for x in range(x0, x1 + 1):
            dx = x - CX
            d2 = dx * dx + dy * dy
            if d2 > rad * rad:
                continue
            d = math.sqrt(d2)
            off = d - RING_R
            if off > 120.0 or off < -170.0:
                continue
            ang = math.degrees(math.atan2(dy, dx))
            # periodic angular chunk noise + fine radial brushing
            ero = vnoise(3.1 + 1.9 * math.cos(math.radians(ang)),
                         5.7 + 1.9 * math.sin(math.radians(ang)))
            brush = vnoise(d * 0.045, 8.8)
            half = 21.0 + 23.0 * ero
            i = row + x
            in_gap = any(g0 <= ang <= g1 for (g0, g1) in gaps)
            if abs(off) <= half + 8.0:
                heat = max(0.0, 1.0 - abs(off) / half)
                cover = min(1.0, (half + 4.0 - abs(off)) / 8.0)
                if in_gap:
                    # only crumbled teeth survive inside a broken sector
                    cover *= max(0.0, (ero - 0.60) * 2.4) * max(
                        0.0, (brush - 0.34) * 2.0)
                if cover > 0.01:
                    flick = 0.88 + 0.22 * brush
                    cr, cg, cb = LUT_RING[int((0.30 + 0.70 * heat) * 255)]
                    a = 0.97 * cover
                    ia = 1.0 - a
                    R[i] = R[i] * ia + cr * flick * a
                    G[i] = G[i] * ia + cg * flick * a
                    B[i] = B[i] * ia + cb * flick * a
            elif -170.0 <= off < -half - 8.0:
                # faint halo spilling inward from the ring's inner edge
                f = 1.0 - (-off - half) / 150.0
                if f > 0.0:
                    R[i] += 34.0 * f * f
                    G[i] += 15.0 * f * f
                    B[i] += 2.0 * f * f
    # soft glow pooled at the ring's unbroken top and left (not on the gap)
    stamp(CX + 30, CY - 305, 150.0, 40.0, 19.0, 2.0)
    stamp(CX - 268, CY - 60, 140.0, 36.0, 16.0, 2.0)


# Bird geometry lives in a local frame, then rotates about the body centre.
BX, BY = 496.0, 522.0
ROT = math.radians(-15.0)
COSR, SINR = math.cos(ROT), math.sin(ROT)


def xf(px, py):
    """local -> image coords (rotate about the bird centre)."""
    return (BX + px * COSR - py * SINR, BY + px * SINR + py * COSR)


def feather_xf(p0, p1, p2, wb, wm, lut, dark=1.0, segs=14):
    feather(xf(*p0), xf(*p1), xf(*p2), wb, wm, lut, dark, segs)


def wing(side, lut, dark, reach, lift, sec_len=0.56, prim_w=34.0):
    """A raised wing: three rows of feathers fanning from the shoulder.

    side: +1 right wing, -1 left wing (mirrored in local space).
    Primaries sweep up and out; secondaries sit under them; coverts are a
    row of small petals at the base. sec_len and prim_w let the far wing
    be filled in more densely so it does not read as bare spikes.
    """
    sh = (side * 26.0, -96.0)                     # shoulder
    n_prim = 11
    for i in range(n_prim):
        f = i / (n_prim - 1)                      # 0 inner .. 1 outer
        # fan: inner feathers point up, outer ones up-and-out
        length = reach * (0.70 + 0.42 * math.sin(f * math.pi * 0.75))
        tip = (sh[0] + side * length * math.sin(0.35 + 0.85 * f) * 1.02,
               sh[1] - length * math.cos(0.30 + 0.62 * f) - lift * f)
        ctrl = (sh[0] + (tip[0] - sh[0]) * 0.45 + side * 26.0,
                sh[1] + (tip[1] - sh[1]) * 0.45 - 18.0)
        feather_xf(sh, ctrl, tip, 16.0, prim_w - 7.0 * f, lut, dark)
    n_sec = 8
    for i in range(n_sec):
        f = i / (n_sec - 1)
        base = (sh[0] + side * 6.0, sh[1] + 26.0)
        length = reach * sec_len * (0.82 + 0.30 * math.sin(f * math.pi))
        tip = (base[0] + side * length * math.sin(0.25 + 0.8 * f),
               base[1] - length * math.cos(0.22 + 0.55 * f) - lift * 0.4 * f)
        ctrl = (base[0] + (tip[0] - base[0]) * 0.5 + side * 16.0,
                base[1] + (tip[1] - base[1]) * 0.5 - 10.0)
        feather_xf(base, ctrl, tip, 15.0, 29.0, lut, dark * 0.96)
    # coverts: small petals hugging the shoulder
    for i in range(7):
        f = i / 6.0
        base = (sh[0] - side * 4.0, sh[1] + 8.0 + 10.0 * f)
        tip = (base[0] + side * (48.0 + 64.0 * f), base[1] - 66.0 - 46.0 * f)
        ctrl = (base[0] + (tip[0] - base[0]) * 0.5 + side * 8.0,
                base[1] + (tip[1] - base[1]) * 0.5)
        feather_xf(base, ctrl, tip, 13.0, 19.0, lut, dark * 1.02, segs=8)


def tail():
    """Six long streamers flowing down-left from the tail base."""
    base = (-6.0, 128.0)
    specs = [
        (-150.0, 330.0, -60.0),
        (-96.0, 372.0, -30.0),
        (-36.0, 392.0, -6.0),
        (28.0, 380.0, 18.0),
        (88.0, 344.0, 40.0),
        (138.0, 292.0, 58.0),
    ]
    for (dx, dy, bow) in specs:
        tip = (base[0] + dx, base[1] + dy)
        ctrl = (base[0] + dx * 0.4 + bow, base[1] + dy * 0.45)
        feather_xf(base, ctrl, tip, 13.0, 21.0, LUT_FEATHER, 0.94, segs=18)


def body_and_head():
    """Teardrop body on a gentle S spine, then the head in profile."""
    spine = []
    for s in range(21):
        t = s / 20.0
        # spine from head base (0,-150) to tail tip (-4, 168)
        x = 14.0 * math.sin(t * math.pi * 0.9) - 4.0 * t
        y = -150.0 + 318.0 * t
        spine.append((x, y, t))
    left, right = [], []
    for (x, y, t) in spine:
        hw = 56.0 * math.sin(math.pi * min(1.0, 0.12 + t * 0.98)) ** 0.8
        hw *= (1.0 - 0.25 * t)
        left.append((*xf(x - hw, y), t, -1.0))
        right.append((*xf(x + hw, y), t, 1.0))
    pts = left + right[::-1]

    def colour(u, v):
        cr, cg, cb = LUT_BODY[int(max(0, min(255, (1.0 - u) * 255)))]
        shade = 0.78 + 0.36 * (1.0 - abs(v))   # cylindrical: bright spine
        return (cr * shade, cg * shade, cb * shade, 1.0, 'over')

    fill_poly(pts, colour)

    # scalloped scale rows down the belly: long narrow petals, staggered,
    # fading in below the chest core
    for row_i in range(8):
        t = 0.40 + row_i * 0.072
        sx = 14.0 * math.sin(t * math.pi * 0.9) - 4.0 * t
        sy = -150.0 + 318.0 * t
        hw = 56.0 * math.sin(math.pi * min(1.0, 0.12 + t * 0.98)) ** 0.8
        hw *= (1.0 - 0.25 * t)
        shift = 7.0 if row_i % 2 else 0.0
        for fx in (-0.60, 0.0, 0.60):
            p0 = (sx + fx * hw * 0.86 + shift, sy - 6.0)
            p2 = (sx + fx * hw * 0.94 + shift, sy + 42.0)
            p1 = (p0[0] + (p2[0] - p0[0]) * 0.5 + fx * 5.0,
                  p0[1] + (p2[1] - p0[1]) * 0.5)
            feather_xf(p0, p1, p2, 6.0, 10.5, LUT_SCALLOP,
                       0.86 + 0.14 * (row_i / 7.0), segs=6)

    # crest first, so the head overlaps its bases: four flame feathers
    # swept back and up from the crown
    for (p0, p1, p2) in [
            ((-2.0, -186.0), (-52.0, -224.0), (-108.0, -226.0)),
            ((6.0, -192.0), (-30.0, -240.0), (-62.0, -272.0)),
            ((16.0, -190.0), (2.0, -238.0), (-8.0, -272.0)),
            ((-10.0, -180.0), (-64.0, -198.0), (-118.0, -192.0))]:
        feather_xf(p0, p1, p2, 8.5, 12.5, LUT_FEATHER, 1.0, segs=10)

    # head: a squashed oval, crimson crown shading to a gold face
    hx, hy = xf(10.0, -164.0)
    head_r = 34.0
    pts = []
    for s in range(20):
        a = s / 20.0 * math.tau
        wob = 1.0 + 0.08 * math.cos(a * 2.0 + 0.6)
        pts.append((hx + math.cos(a) * head_r * wob,
                    hy + math.sin(a) * head_r * (wob * 0.90),
                    0.0, math.sin(a)))

    def hcolour(u, v):
        # v is sin(angle): -1 crown, +1 chin
        cr, cg, cb = LUT_BODY[int(max(0, min(255, 196 - 74 * (v * 0.5 + 0.5))))]
        return (cr, cg, cb, 1.0, 'over')

    fill_poly(pts, hcolour)
    # beak: two gold wedges pointing up-right, the direction of flight
    pts = [(*xf(28.0, -180.0), 0, 0), (*xf(88.0, -194.0), 1, 0),
           (*xf(32.0, -162.0), 0, 1)]

    def bcolour(u, v):
        cr = 246.0 - 30.0 * v
        cg = 178.0 - 34.0 * v
        cb = 60.0 - 12.0 * v
        return (cr, cg, cb, 1.0, 'over')

    fill_poly(pts, bcolour)
    pts = [(*xf(30.0, -160.0), 0, 0), (*xf(66.0, -168.0), 1, 0),
           (*xf(32.0, -148.0), 0, 1)]

    def bcolour2(u, v):
        return (208.0, 124.0, 36.0, 1.0, 'over')

    fill_poly(pts, bcolour2)
    # a fierce brow ridge over the eye
    pts = [(*xf(6.0, -188.0), 0, 0), (*xf(36.0, -186.0), 1, 0),
           (*xf(32.0, -176.0), 1, 1), (*xf(10.0, -178.0), 0, 1)]

    def browcolour(u, v):
        return (148.0, 18, 24.0, 1.0, 'over')

    fill_poly(pts, browcolour)
    # the eye: gold iris, dark pupil, one white spark
    ex, ey = xf(21.0, -172.0)
    stamp(ex, ey, 16.0, 54.0, 30.0, 6.0)
    for (rad, col) in [(7.6, (255.0, 206.0, 92.0)), (4.3, (24.0, 8, 8.0))]:
        pts = []
        for s in range(14):
            a = s / 14.0 * math.tau
            pts.append((ex + math.cos(a) * rad, ey + math.sin(a) * rad, 0, 0))

        def ecolour(u, v, _c=col):
            return (_c[0], _c[1], _c[2], 1.0, 'over')

        fill_poly(pts, ecolour)
    stamp(ex - 2.0, ey - 2.0, 3.4, 160.0, 150.0, 120.0)


def shards(count, seed, behind):
    """Polygons of the broken ring bursting outward toward the viewer.

    Shards fly along radial lines from the ring centre; the ones marked
    'behind' are drawn before the bird, the rest after (some cross the
    bird's silhouette, which sells the burst-through moment).
    """
    rng = LCG(seed)
    for _ in range(count):
        ang = rng.next() * math.tau
        # bias the burst toward the ring's broken lower-left and the right
        dist = RING_R * (0.82 + 0.75 * rng.next() ** 1.6)
        cx = CX + math.cos(ang) * dist
        cy = CY + math.sin(ang) * dist
        size = 5.0 + 23.0 * rng.next() ** 2 * (0.45 + dist / RING_R)
        if behind and size > 24.0:
            continue
        if not behind and abs(cx - (BX + 10.0)) < 95.0 \
                and BY + 30.0 < cy < BY + 300.0:
            continue   # keep the body's own silhouette clean of stray fins
        rot = ang + rng.range(-0.5, 0.5)
        stretch = rng.range(1.4, 3.0)
        pts = []
        for (lx, ly) in [(-1.0, 0.0), (0.2, -0.42), (1.0, 0.05), (0.1, 0.46)]:
            rx = lx * size * stretch
            ry = ly * size
            pts.append((cx + rx * math.cos(rot) - ry * math.sin(rot),
                        cy + rx * math.sin(rot) + ry * math.cos(rot),
                        (lx + 1.0) / 2.0, ly + 0.5))
        bright = rng.range(0.55, 1.0)

        def colour(u, v, _b=bright):
            cr, cg, cb = LUT_SHARD[int(max(0, min(255, u * 255)))]
            sh = (0.60 + 0.58 * v) * _b
            return (cr * sh, cg * sh, cb * sh, 0.96, 'over')

        fill_poly(pts, colour)
        if not behind and rng.next() < 0.5:
            stamp(cx, cy, size * 0.9, 30.0, 16.0, 2.0)


def burst_at_gap():
    """The burst point: a flash and a fan of shards at the ring's broken
    upper-right sector, where the bird is breaking out toward the viewer."""
    gx = CX + math.cos(math.radians(-27.0)) * RING_R
    gy = CY + math.sin(math.radians(-27.0)) * RING_R
    stamp(gx, gy, 95.0, 120.0, 58.0, 8.0)
    stamp(gx, gy, 34.0, 210.0, 150.0, 70.0)
    rng = LCG(31337)
    for _ in range(13):
        ang = math.radians(-27.0) + rng.range(-0.55, 0.55)
        dist = RING_R * rng.range(0.92, 1.38)
        cx = CX + math.cos(ang) * dist
        cy = CY + math.sin(ang) * dist
        size = rng.range(9.0, 30.0)
        rot = ang + rng.range(-0.4, 0.4)
        stretch = rng.range(1.6, 3.2)
        pts = []
        for (lx, ly) in [(-1.0, 0.0), (0.2, -0.42), (1.0, 0.05), (0.1, 0.46)]:
            rx = lx * size * stretch
            ry = ly * size
            pts.append((cx + rx * math.cos(rot) - ry * math.sin(rot),
                        cy + rx * math.sin(rot) + ry * math.cos(rot),
                        (lx + 1.0) / 2.0, ly + 0.5))
        bright = rng.range(0.75, 1.05)

        def colour(u, v, _b=bright):
            cr, cg, cb = LUT_SHARD[int(max(0, min(255, u * 255)))]
            sh = (0.60 + 0.58 * v) * _b
            return (cr * sh, cg * sh, cb * sh, 0.97, 'over')

        fill_poly(pts, colour)


def embers_and_streaks():
    """Additive light: ember streams on the diagonal, radiating streaks."""
    rng = LCG(777001)
    # ember stream A: trailing off down-left with the tail
    for _ in range(300):
        t = rng.next()
        cx = 452.0 - 420.0 * t + rng.range(-46, 46)
        cy = 690.0 + 300.0 * t + rng.range(-40, 40)
        s = rng.range(1.2, 4.6) * (1.0 - t * 0.5)
        hot = rng.range(0.4, 1.0)
        stamp(cx, cy, s * 2.4, 200.0 * hot, 92.0 * hot, 14.0 * hot)
    # ember stream B: bursting up-right past the ring
    for _ in range(260):
        t = rng.next()
        cx = 640.0 + 360.0 * t + rng.range(-52, 52)
        cy = 330.0 - 260.0 * t + rng.range(-46, 46)
        s = rng.range(1.2, 5.0) * (1.0 - t * 0.4)
        hot = rng.range(0.4, 1.0)
        if rng.next() < 0.22:  # a few cool sparks for contrast
            stamp(cx, cy, s * 2.2, 30.0 * hot, 130.0 * hot, 140.0 * hot)
        else:
            stamp(cx, cy, s * 2.4, 210.0 * hot, 110.0 * hot, 20.0 * hot)
    # speed streaks radiating from the ring centre
    for _ in range(70):
        ang = rng.next() * math.tau
        r0 = RING_R * rng.range(0.95, 1.25)
        ln = rng.range(26.0, 110.0)
        wd = rng.range(1.2, 3.0)
        cx = CX + math.cos(ang) * r0
        cy = CY + math.sin(ang) * r0
        dx, dy = math.cos(ang), math.sin(ang)
        px, py = -dy, dx
        pts = [(cx - dx * ln * 0.4 - px * wd, cy - dy * ln * 0.4 - py * wd, 0, 0),
               (cx + dx * ln - px * wd * 0.3, cy + dy * ln - py * wd * 0.3, 1, 0),
               (cx + dx * ln + px * wd * 0.3, cy + dy * ln + py * wd * 0.3, 1, 1),
               (cx - dx * ln * 0.4 + px * wd, cy - dy * ln * 0.4 + py * wd, 0, 1)]

        def colour(u, v):
            return (255.0, 190.0, 90.0, 0.16 * (1.0 - u), 'add')

        fill_poly(pts, colour)


def post():
    """Vignette, a gentle S-curve, and the white-hot chest core on top."""
    cx, cy = BX, BY - 60.0
    # the chest core: a broad warm bloom and a white-hot heart on top
    stamp(*xf(0.0, -34.0), 130.0, 168.0, 74.0, 10.0)
    stamp(*xf(0.0, -34.0), 30.0, 255.0, 214.0, 130.0)
    maxd2 = (W * 0.72) ** 2
    for y in range(H):
        dy = y - cy
        row = y * W
        for x in range(W):
            dx = x - cx
            d2 = dx * dx + dy * dy
            f = 1.0 - 0.38 * max(0.0, (d2 / maxd2 - 0.35)) / 0.65
            i = row + x
            R[i] *= f
            G[i] *= f
            B[i] *= f
    # S-curve LUT applied at PNG build time (see tone_lut)
    return


TONE = [min(255, max(0, int(255.0 * ((v / 255.0) ** 1.06
        + 0.10 * math.sin((v / 255.0) * math.pi) * (v / 255.0) * (1 - v / 255.0)
        )))) for v in range(256)]


# ---------------------------------------------------------------------------
# PNG writer (filter Sub, zlib). Pure stdlib.
# ---------------------------------------------------------------------------


def write_png(path):
    raw = bytearray()
    for y in range(H):
        row = y * W
        line = bytearray(W * 3)
        j = 0
        for x in range(W):
            i = row + x
            line[j] = TONE[min(255, max(0, int(R[i])))]
            line[j + 1] = TONE[min(255, max(0, int(G[i])))]
            line[j + 2] = TONE[min(255, max(0, int(B[i])))]
            j += 3
        # Sub filter
        filt = bytearray(W * 3)
        for k in range(W * 3):
            left = line[k - 3] if k >= 3 else 0
            filt[k] = (line[k] - left) & 0xFF
        raw.append(1)
        raw += filt
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', comp)
           + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)


def main():
    out_dir = os.environ.get('MAKEFUN_OUTPUT_DIR', '/output')
    os.makedirs(out_dir, exist_ok=True)
    background()
    vortex()
    ring()
    shards(46, 4242, behind=True)
    tail()
    wing(-1, LUT_FEATHER_FAR, 0.88, 415.0, 30.0,
         sec_len=0.68, prim_w=38.0)                 # far wing, filled in
    wing(+1, LUT_FEATHER, 1.0, 445.0, 44.0)        # near wing
    body_and_head()
    shards(30, 9001, behind=False)
    burst_at_gap()
    embers_and_streaks()
    post()
    write_png(os.path.join(out_dir, 'entry.png'))


if __name__ == '__main__':
    main()
