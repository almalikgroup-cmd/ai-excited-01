"""Koi Ascendant -- a deterministic generative artwork in pure Python.

Two luminous koi carp spiral upward through deep indigo water toward a
bright moon-disc, trailing bubbles and a stream of glowing motes.  The
picture is drawn entirely with the Python standard library: a fixed-seed
splitmix64 PRNG, integer-hash value noise, analytic distance fields and
a hand-rolled PNG encoder, so two runs always produce the same bytes.

Running this file writes ``entry.png`` into ``/output`` (or into the
directory named by the ``MAKEFUN_OUTPUT_DIR`` environment variable).
"""

import math
import os
import struct
import zlib
from array import array

W = 1024
H = 1024

MOON_X = 512.0
MOON_Y = 205.0
MOON_R = 118.0


# --------------------------------------------------------------------------
# Deterministic PRNG (splitmix64) and integer-hash value noise.
# Nothing in this file reads the clock, the network or any other file,
# so the output depends only on the constants below.
# --------------------------------------------------------------------------

class Rng:
    """A tiny splitmix64 generator with an explicit fixed seed."""

    def __init__(self, seed):
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def next_u64(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def random(self):
        """Next float in [0, 1)."""
        return (self.next_u64() >> 11) * (1.0 / 9007199254740992.0)

    def uniform(self, a, b):
        return a + (b - a) * self.random()


def hash2(ix, iy):
    """Hash a pair of integers to a float in [0, 1)."""
    z = ((ix * 0x9E3779B97F4A7C15) ^ (iy * 0xC2B2AE3D27D4EB4F)
         ^ 0x165667B19E3779F9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    z = z ^ (z >> 31)
    return (z >> 11) * (1.0 / 9007199254740992.0)


def value_noise(x, y):
    """Smooth value noise built on hash2, in [0, 1)."""
    ix = math.floor(x)
    iy = math.floor(y)
    fx = x - ix
    fy = y - iy
    sx = fx * fx * (3.0 - 2.0 * fx)
    sy = fy * fy * (3.0 - 2.0 * fy)
    v00 = hash2(ix, iy)
    v10 = hash2(ix + 1, iy)
    v01 = hash2(ix, iy + 1)
    v11 = hash2(ix + 1, iy + 1)
    top = v00 + (v10 - v00) * sx
    bot = v01 + (v11 - v01) * sx
    return top + (bot - top) * sy


def fbm(x, y, octaves):
    """Fractal sum of value_noise octaves, roughly in [0, 1)."""
    total = 0.0
    amp = 0.5
    freq = 1.0
    norm = 0.0
    for _ in range(octaves):
        total += amp * value_noise(x * freq, y * freq)
        norm += amp
        amp *= 0.5
        freq *= 2.03
    return total / norm


def clamp01(v):
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def smoothstep(a, b, v):
    t = clamp01((v - a) / (b - a))
    return t * t * (3.0 - 2.0 * t)


def mix3(c0, c1, t):
    return (c0[0] + (c1[0] - c0[0]) * t,
            c0[1] + (c1[1] - c0[1]) * t,
            c0[2] + (c1[2] - c0[2]) * t)


# --------------------------------------------------------------------------
# PNG encoder.  Each row picks the better of the Sub and Up filters by a
# signed-byte score, which keeps the smooth gradients small; zlib does
# the rest.  Fixed inputs and a fixed zlib level give identical bytes.
# --------------------------------------------------------------------------

def write_png(path, w, h, rgb):
    stride = w * 3
    raw = bytearray()
    prev = bytearray(stride)
    for y in range(h):
        row = rgb[y * stride:(y + 1) * stride]
        filt_sub = bytearray(stride)
        filt_up = bytearray(stride)
        score_sub = 0
        score_up = 0
        for i in range(stride):
            v = row[i]
            left = row[i - 3] if i >= 3 else 0
            up = prev[i]
            fs = (v - left) & 0xFF
            fu = (v - up) & 0xFF
            filt_sub[i] = fs
            filt_up[i] = fu
            score_sub += fs if fs < 128 else 256 - fs
            score_up += fu if fu < 128 else 256 - fu
        if score_sub <= score_up:
            raw.append(1)
            raw += filt_sub
        else:
            raw.append(2)
            raw += filt_up
        prev = row

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


# --------------------------------------------------------------------------
# Background: deep indigo water, a pool of teal light mid-frame, god rays
# falling from the moon, expanding ripple rings and the moon itself.
# A low-resolution fbm grid is precomputed once and bilinearly sampled so
# the per-pixel loop stays cheap.
# --------------------------------------------------------------------------

GRID = 256


def make_shimmer_grid():
    g = array("f", bytes(4 * GRID * GRID))
    for gy in range(GRID):
        for gx in range(GRID):
            g[gy * GRID + gx] = fbm(gx * 0.055, gy * 0.055, 3)
    return g


def grid_sample(g, fx, fy):
    """Bilinear sample of the GRID x GRID float grid at float coords."""
    if fx < 0.0:
        fx = 0.0
    if fy < 0.0:
        fy = 0.0
    if fx > GRID - 1.001:
        fx = GRID - 1.001
    if fy > GRID - 1.001:
        fy = GRID - 1.001
    ix = int(fx)
    iy = int(fy)
    tx = fx - ix
    ty = fy - iy
    i00 = iy * GRID + ix
    top = g[i00] + (g[i00 + 1] - g[i00]) * tx
    bot = g[i00 + GRID] + (g[i00 + GRID + 1] - g[i00 + GRID]) * tx
    return top + (bot - top) * ty


TOP_COL = (0.034, 0.068, 0.185)
BOT_COL = (0.003, 0.008, 0.034)
POOL_COL = (0.030, 0.135, 0.165)
MOON_COL = (1.38, 1.29, 1.10)
HALO_COL = (0.95, 0.82, 0.58)
RAY_COL = (0.50, 0.64, 0.86)
RIPPLE_COL = (0.55, 0.75, 0.90)

RIPPLES = ((MOON_X, MOON_Y, 0.105, 0.050),
           (428.0, 648.0, 0.135, 0.030),
           (655.0, 762.0, 0.155, 0.022))


def paint_background(buf_r, buf_g, buf_b, shimmer):
    scale = (GRID - 1) / float(W)
    for y in range(H):
        v = y / (H - 1)
        grad = mix3(TOP_COL, BOT_COL, v ** 1.12)
        base_r, base_g, base_b = grad
        fy = y * scale
        row = y * W
        for x in range(W):
            dxm = x - MOON_X
            dym = y - MOON_Y
            dm2 = dxm * dxm + dym * dym
            dm = math.sqrt(dm2)

            r = base_r
            g = base_g
            b = base_b

            # A soft pool of teal light in the middle depths.
            dcx = x - 512.0
            dcy = y - 545.0
            dc2 = dcx * dcx + dcy * dcy
            pool = 1.0 / (1.0 + dc2 / 108900.0)
            r += POOL_COL[0] * pool
            g += POOL_COL[1] * pool
            b += POOL_COL[2] * pool

            # Slow caustic shimmer from the precomputed noise grid.
            sh = grid_sample(shimmer, x * scale, fy)
            lift = (sh - 0.5) * 0.055
            r += lift * 0.6
            g += lift * 0.9
            b += lift

            # God rays: bright shafts angled around the moon, strongest
            # below it and fading with distance.  The vertical fade is
            # smooth -- a hard gate printed a visible horizontal band.
            if dym > -60.0:
                ang = math.atan2(dxm, dym + 40.0)
                ray = 0.5 + 0.5 * math.sin(ang * 9.0 + 1.3 * math.sin(ang * 4.0 + 0.7))
                ray = ray * ray * ray
                ray *= 1.0 / (1.0 + dm / 250.0)
                ray *= 0.16 * smoothstep(-60.0, 70.0, dym)
                r += RAY_COL[0] * ray
                g += RAY_COL[1] * ray
                b += RAY_COL[2] * ray

            # Ripple rings spreading from three centres.
            for (cx, cy, freq, amp) in RIPPLES:
                rx = x - cx
                ry = y - cy
                rr = math.sqrt(rx * rx + ry * ry)
                ring = math.sin(rr * freq - 1.1) * 0.5 + 0.5
                ring = ring * ring
                ring *= amp / (1.0 + rr / 320.0)
                r += RIPPLE_COL[0] * ring
                g += RIPPLE_COL[1] * ring
                b += RIPPLE_COL[2] * ring

            # Moon halo: a tight warm bloom plus a wide faint one.
            if dm > MOON_R - 8.0:
                over = dm - MOON_R
                halo = 0.55 / (1.0 + (over / 95.0) * (over / 95.0))
                halo += 0.10 / (1.0 + (dm / 430.0) * (dm / 430.0))
                r += HALO_COL[0] * halo
                g += HALO_COL[1] * halo
                b += HALO_COL[2] * halo

            # The moon disc itself, softly edged, with a mottled face.
            if dm < MOON_R + 7.0:
                face = fbm(x * 0.045 + 31.7, y * 0.045 + 11.2, 3)
                limb = 0.86 + 0.14 * (1.0 - (dm / MOON_R) ** 2)
                mc = (MOON_COL[0] * (0.88 + 0.22 * face) * limb,
                      MOON_COL[1] * (0.88 + 0.22 * face) * limb,
                      MOON_COL[2] * (0.88 + 0.19 * face) * limb)
                f = smoothstep(MOON_R + 6.0, MOON_R - 6.0, dm)
                r = r + (mc[0] - r) * f
                g = g + (mc[1] - g) * f
                b = b + (mc[2] - b) * f

            i = row + x
            buf_r[i] = r
            buf_g[i] = g
            buf_b[i] = b


# --------------------------------------------------------------------------
# Koi geometry.  A spine is a cubic Bezier sampled evenly by arc length.
# The body is stamped as a chain of discs along the spine; each pixel
# keeps the sample it lies closest to, which yields a smooth distance
# field plus the body coordinates (along, side) used for patterning.
# --------------------------------------------------------------------------

def cubic(p0, p1, p2, p3, t):
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3.0 * mt * mt * t
    c = 3.0 * mt * t * t
    d = t * t * t
    return (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
            a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])


def spine_samples(p0, p1, p2, p3, step=3.0):
    """Evenly spaced (x, y, tx, ty, t) samples; t=0 tail, t=1 head."""
    dense = [cubic(p0, p1, p2, p3, i / 240.0) for i in range(241)]
    lengths = [0.0]
    for i in range(1, 241):
        dx = dense[i][0] - dense[i - 1][0]
        dy = dense[i][1] - dense[i - 1][1]
        lengths.append(lengths[-1] + math.hypot(dx, dy))
    total = lengths[-1]
    n = max(8, int(total / step))
    pts = []
    j = 0
    for i in range(n + 1):
        target = total * i / n
        while j < 239 and lengths[j + 1] < target:
            j += 1
        seg = lengths[j + 1] - lengths[j]
        f = 0.0 if seg == 0.0 else (target - lengths[j]) / seg
        pts.append((dense[j][0] + (dense[j + 1][0] - dense[j][0]) * f,
                    dense[j][1] + (dense[j + 1][1] - dense[j][1]) * f))
    samples = []
    for i, (x, y) in enumerate(pts):
        if i == 0:
            tx, ty = pts[1][0] - x, pts[1][1] - y
        elif i == n:
            tx, ty = x - pts[i - 1][0], y - pts[i - 1][1]
        else:
            tx, ty = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
        ln = math.hypot(tx, ty) or 1.0
        samples.append((x, y, tx / ln, ty / ln, i / n))
    return samples


PROFILE = ((0.00, 0.52), (0.07, 0.82), (0.18, 0.98), (0.32, 1.00),
           (0.52, 0.90), (0.72, 0.66), (0.88, 0.46), (1.00, 0.32))


def width_profile(u):
    """Body half-width as a fraction of the maximum; u=0 head, u=1 tail."""
    if u <= 0.0:
        return PROFILE[0][1]
    for k in range(len(PROFILE) - 1):
        u0, w0 = PROFILE[k]
        u1, w1 = PROFILE[k + 1]
        if u <= u1:
            f = (u - u0) / (u1 - u0)
            s = f * f * (3.0 - 2.0 * f)
            return w0 + (w1 - w0) * s
    return PROFILE[-1][1]


# --------------------------------------------------------------------------
# Stamping: shared distance-field buffers the koi draw into.
# --------------------------------------------------------------------------

GS = 256  # glow grid resolution (canvas / 4)


class Canvas:
    def __init__(self):
        n = W * H
        self.body_d = array("f", [2.0]) * n      # normalised dist to spine
        self.body_u = array("f", [0.0]) * n      # 0 at head, 1 at tail
        self.body_side = array("f", [0.0]) * n   # signed lateral, -1..1
        self.body_light = array("f", [0.0]) * n  # facing toward the moon
        self.body_id = bytearray(n)
        self.fin_a = array("f", [0.0]) * n
        self.fin_u = array("f", [0.0]) * n
        self.fin_side = array("f", [0.0]) * n
        self.fin_id = bytearray(n)
        self.glow = [array("f", [0.0]) * (GS * GS) for _ in range(2)]


def blur_grid(g, radius):
    """Two box-blur passes (horizontal then vertical), edge-clamped."""
    tmp = array("f", [0.0]) * (GS * GS)
    span = 2 * radius + 1
    for _ in range(2):
        for y in range(GS):
            row = y * GS
            for x in range(GS):
                acc = 0.0
                for k in range(-radius, radius + 1):
                    xx = x + k
                    if xx < 0:
                        xx = 0
                    elif xx >= GS:
                        xx = GS - 1
                    acc += g[row + xx]
                tmp[row + x] = acc / span
        for y in range(GS):
            for x in range(GS):
                acc = 0.0
                for k in range(-radius, radius + 1):
                    yy = y + k
                    if yy < 0:
                        yy = 0
                    elif yy >= GS:
                        yy = GS - 1
                    acc += tmp[yy * GS + x]
                g[y * GS + x] = acc / span


class Koi:
    def __init__(self, kid, spine, maxw, deep, mid, bright, patch, rim,
                 glow_col, seed_a, seed_b, patch_lo, patch_hi):
        self.kid = kid
        self.samples = spine_samples(spine[0], spine[1], spine[2], spine[3])
        self.maxw = maxw
        self.deep = deep
        self.mid = mid
        self.bright = bright
        self.patch = patch
        self.rim = rim
        self.glow_col = glow_col
        self.seed_a = seed_a
        self.seed_b = seed_b
        self.patch_lo = patch_lo
        self.patch_hi = patch_hi

    def sample_at_u(self, u):
        """The spine sample whose body coordinate u (0=head) is closest."""
        best = None
        best_err = 1e9
        for s in self.samples:
            err = abs((1.0 - s[4]) - u)
            if err < best_err:
                best_err = err
                best = s
        return best

    def stamp_body(self, cv):
        glow = cv.glow[self.kid - 1]
        for (x, y, tx, ty, t) in self.samples:
            u = 1.0 - t
            r = width_profile(u) * self.maxw
            if r < 1.5:
                continue
            nx, ny = -ty, tx
            # Direction from this spine point toward the moon (for light).
            mdx = MOON_X - x
            mdy = MOON_Y - y
            ml = math.hypot(mdx, mdy) or 1.0
            mdx /= ml
            mdy /= ml
            x0 = max(0, int(x - r - 1))
            x1 = min(W - 1, int(x + r + 1))
            y0 = max(0, int(y - r - 1))
            y1 = min(H - 1, int(y + r + 1))
            r2 = r * r
            for yy in range(y0, y1 + 1):
                dy = yy - y
                row = yy * W
                for xx in range(x0, x1 + 1):
                    dx = xx - x
                    d2 = dx * dx + dy * dy
                    if d2 > r2:
                        continue
                    dist = math.sqrt(d2)
                    d = dist / r
                    i = row + xx
                    if d < cv.body_d[i]:
                        cv.body_d[i] = d
                        cv.body_u[i] = u
                        cv.body_side[i] = (dx * nx + dy * ny) / r
                        if dist > 0.001:
                            facing = (dx / dist) * mdx + (dy / dist) * mdy
                        else:
                            facing = 0.6
                        cv.body_light[i] = 0.35 + 0.65 * max(0.0, facing)
                        cv.body_id[i] = self.kid
            # Stamp a soft disc into this koi's glow grid.
            gr = r * (GS / W) * 1.15
            gx = x * (GS / W)
            gy = y * (GS / W)
            gx0 = max(0, int(gx - gr - 1))
            gx1 = min(GS - 1, int(gx + gr + 1))
            gy0 = max(0, int(gy - gr - 1))
            gy1 = min(GS - 1, int(gy + gr + 1))
            for yy in range(gy0, gy1 + 1):
                ddy = yy - gy
                grow = yy * GS
                for xx in range(gx0, gx1 + 1):
                    ddx = xx - gx
                    gd = math.sqrt(ddx * ddx + ddy * ddy)
                    if gd < gr:
                        v = 0.9 * (1.0 - gd / gr)
                        gi = grow + xx
                        if v > glow[gi]:
                            glow[gi] = v

    def stamp_tail_fin(self, cv):
        # Start a few samples up the tail so the fin's root tucks under
        # the body (the body is composited over the fins) and the joint
        # never pinches into a separate flame shape.
        x, y, tx, ty, _t = self.samples[3]
        back_x, back_y = -tx, -ty
        nx, ny = -ty, tx
        length = self.maxw * 2.7
        steps = 44
        pts = []
        for i in range(steps + 1):
            s = i / steps
            bend = math.sin(s * math.pi * 0.9) * length * 0.10
            px = x + back_x * length * s + nx * bend
            py = y + back_y * length * s + ny * bend
            pts.append((px, py, s))
        for i, (px, py, s) in enumerate(pts):
            if i == 0:
                ftx, fty = pts[1][0] - px, pts[1][1] - py
            elif i == steps:
                ftx, fty = px - pts[i - 1][0], py - pts[i - 1][1]
            else:
                ftx, fty = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
            fl = math.hypot(ftx, fty) or 1.0
            ftx /= fl
            fty /= fl
            fnx, fny = -fty, ftx
            fw = self.maxw * 0.80 * (math.sin(math.pi * (0.16 + 0.76 * s)) ** 0.75)
            if fw < 1.2:
                continue
            x0 = max(0, int(px - fw - 1))
            x1 = min(W - 1, int(px + fw + 1))
            y0 = max(0, int(py - fw - 1))
            y1 = min(H - 1, int(py + fw + 1))
            fw2 = fw * fw
            for yy in range(y0, y1 + 1):
                dy = yy - py
                row = yy * W
                for xx in range(x0, x1 + 1):
                    dx = xx - px
                    d2 = dx * dx + dy * dy
                    if d2 > fw2:
                        continue
                    d = math.sqrt(d2) / fw
                    a = (1.0 - d) ** 1.4 * 0.85
                    i = row + xx
                    if a > cv.fin_a[i]:
                        cv.fin_a[i] = a
                        cv.fin_u[i] = 1.25 + s * 0.6
                        cv.fin_side[i] = (dx * fnx + dy * fny) / fw
                        cv.fin_id[i] = self.kid

    def stamp_pectoral_fins(self, cv):
        anchor = self.sample_at_u(0.20)
        x, y, tx, ty, _t = anchor
        nx, ny = -ty, tx
        r_here = width_profile(0.20) * self.maxw
        for sign in (-1.0, 1.0):
            cx = x + nx * sign * (r_here + self.maxw * 0.16) - tx * self.maxw * 0.10
            cy = y + ny * sign * (r_here + self.maxw * 0.16) - ty * self.maxw * 0.10
            ax = nx * sign * 0.88 - tx * 0.78
            ay = ny * sign * 0.88 - ty * 0.78
            al = math.hypot(ax, ay) or 1.0
            ax /= al
            ay /= al
            px_, py_ = -ay, ax
            a_len = self.maxw * 0.98
            b_len = self.maxw * 0.40
            rad = int(a_len + 2)
            x0 = max(0, int(cx - rad))
            x1 = min(W - 1, int(cx + rad))
            y0 = max(0, int(cy - rad))
            y1 = min(H - 1, int(cy + rad))
            for yy in range(y0, y1 + 1):
                dy = yy - cy
                row = yy * W
                for xx in range(x0, x1 + 1):
                    dx = xx - cx
                    uu = (dx * ax + dy * ay) / a_len
                    vv = (dx * px_ + dy * py_) / b_len
                    e = uu * uu + vv * vv
                    if e >= 1.0:
                        continue
                    a = (1.0 - e) ** 1.3 * 0.85
                    a *= 0.55 + 0.45 * smoothstep(-1.0, 0.3, uu)
                    i = row + xx
                    if a > cv.fin_a[i]:
                        cv.fin_a[i] = a
                        cv.fin_u[i] = uu * 0.5 + 0.5
                        cv.fin_side[i] = vv
                        cv.fin_id[i] = self.kid

    def stamp_all(self, cv):
        self.stamp_tail_fin(cv)
        self.stamp_pectoral_fins(cv)
        self.stamp_body(cv)


KOI_BY_ID = {}


def make_koi():
    gold = Koi(1,
               ((698.0, 806.0), (788.0, 584.0), (602.0, 382.0), (520.0, 238.0)),
               60.0,
               (0.80, 0.22, 0.03), (1.04, 0.43, 0.09), (1.32, 0.80, 0.31),
               (1.07, 1.02, 0.95), (1.00, 0.74, 0.42), (1.05, 0.55, 0.20),
               3.7, 9.1, 0.505, 0.585)
    silver = Koi(2,
                 ((332.0, 848.0), (228.0, 624.0), (414.0, 432.0), (452.0, 302.0)),
                 52.0,
                 (0.50, 0.60, 0.80), (0.86, 0.90, 1.00), (1.06, 1.07, 1.06),
                 (1.06, 0.45, 0.10), (0.80, 0.90, 1.10), (0.55, 0.70, 1.05),
                 17.3, 4.6, 0.565, 0.645)
    KOI_BY_ID[1] = gold
    KOI_BY_ID[2] = silver
    return gold, silver


def composite_koi(buf_r, buf_g, buf_b, cv):
    """Blend glow, fins and bodies over the painted background."""
    gscale = (GS - 1) / float(W)
    for y in range(H):
        fy = y * gscale
        row = y * W
        for x in range(W):
            i = row + x
            r = buf_r[i]
            g = buf_g[i]
            b = buf_b[i]

            fx = x * gscale
            ga = grid_sample(cv.glow[0], fx, fy)
            if ga > 0.004:
                gc = KOI_BY_ID[1].glow_col
                r += gc[0] * ga * 0.50
                g += gc[1] * ga * 0.50
                b += gc[2] * ga * 0.50
            gb = grid_sample(cv.glow[1], fx, fy)
            if gb > 0.004:
                gc = KOI_BY_ID[2].glow_col
                r += gc[0] * gb * 0.42
                g += gc[1] * gb * 0.42
                b += gc[2] * gb * 0.42

            fa = cv.fin_a[i]
            if fa > 0.003:
                koi = KOI_BY_ID[cv.fin_id[i]]
                stripes = 0.78 + 0.30 * (0.5 + 0.5 * math.sin(
                    cv.fin_side[i] * 15.0 + cv.fin_u[i] * 6.0))
                fc = mix3(koi.mid, (1.10, 1.05, 0.95), 0.60)
                a = fa * 0.80
                r = r * (1.0 - a) + fc[0] * stripes * (a + a * 0.25)
                g = g * (1.0 - a) + fc[1] * stripes * (a + a * 0.25)
                b = b * (1.0 - a) + fc[2] * stripes * (a + a * 0.25)

            kid = cv.body_id[i]
            if kid:
                koi = KOI_BY_ID[kid]
                u = cv.body_u[i]
                d = cv.body_d[i]
                side = cv.body_side[i]
                li = cv.body_light[i]
                col = mix3(koi.deep, koi.mid, li)
                col = mix3(col, koi.bright, smoothstep(0.62, 1.0, li) * 0.7)
                n = fbm(u * 3.4 + koi.seed_a, side * 1.35 + koi.seed_b, 3)
                p = smoothstep(koi.patch_lo, koi.patch_hi, n)
                col = mix3(col, koi.patch, p)
                n2 = fbm(u * 7.3 + koi.seed_b, side * 3.1 + koi.seed_a, 2)
                p2 = smoothstep(0.56, 0.66, n2) * 0.45
                col = mix3(col, koi.patch, p2 * (1.0 - p))
                tex = 0.965 + 0.05 * math.sin(u * 170.0 - abs(side) * 2.0) * (1.0 - d * 0.5)
                rim = smoothstep(0.78, 1.0, d) * (0.30 + 0.70 * li)
                alpha = smoothstep(1.0, 0.90, d)
                cr = col[0] * tex + koi.rim[0] * rim * 0.30
                cg = col[1] * tex + koi.rim[1] * rim * 0.30
                cb = col[2] * tex + koi.rim[2] * rim * 0.30
                r = r + (cr - r) * alpha
                g = g + (cg - g) * alpha
                b = b + (cb - b) * alpha

            buf_r[i] = r
            buf_g[i] = g
            buf_b[i] = b


# --------------------------------------------------------------------------
# Details painted over the composited scene: eyes, rising bubble trails,
# a spiral stream of glowing motes spiralling up to the moon, sparkles.
# --------------------------------------------------------------------------

def paint_eyes(buf_r, buf_g, buf_b, koi):
    anchor = koi.sample_at_u(0.055)
    x, y, tx, ty, _t = anchor
    nx, ny = -ty, tx
    halfw = width_profile(0.055) * koi.maxw
    eye_r = halfw * 0.17
    mdx = MOON_X - x
    mdy = MOON_Y - y
    ml = math.hypot(mdx, mdy) or 1.0
    mdx /= ml
    mdy /= ml
    for sign in (-1.0, 1.0):
        cx = x + nx * sign * halfw * 0.52 + tx * halfw * 0.18
        cy = y + ny * sign * halfw * 0.52 + ty * halfw * 0.18
        rad = eye_r * 1.7
        x0 = max(0, int(cx - rad))
        x1 = min(W - 1, int(cx + rad))
        y0 = max(0, int(cy - rad))
        y1 = min(H - 1, int(cy + rad))
        for yy in range(y0, y1 + 1):
            dy = yy - cy
            row = yy * W
            for xx in range(x0, x1 + 1):
                dx = xx - cx
                q = math.sqrt(dx * dx + dy * dy)
                if q > eye_r:
                    continue
                i = row + xx
                f = smoothstep(eye_r, eye_r * 0.72, q)
                buf_r[i] = buf_r[i] + (0.030 - buf_r[i]) * f
                buf_g[i] = buf_g[i] + (0.030 - buf_g[i]) * f
                buf_b[i] = buf_b[i] + (0.045 - buf_b[i]) * f
                sx = xx - (cx + mdx * eye_r * 0.38)
                sy = yy - (cy + mdy * eye_r * 0.38)
                if sx * sx + sy * sy < (eye_r * 0.30) ** 2:
                    buf_r[i] = 1.45
                    buf_g[i] = 1.38
                    buf_b[i] = 1.22


def bubble_list(rng, gold, silver):
    bubbles = []
    for koi, phase in ((gold, 0.0), (silver, 2.4)):
        tx, ty = koi.samples[0][0], koi.samples[0][1]
        for i in range(40):
            s = i / 40.0
            bx = tx + math.sin(s * 5.1 + phase) * 26.0 * s + rng.uniform(-9.0, 9.0)
            by = ty - s * (ty - 118.0) * rng.uniform(0.78, 1.0)
            br = 1.6 + s * 6.5 + rng.uniform(0.0, 2.2)
            bubbles.append((bx, by, br))
    for _ in range(26):
        bubbles.append((rng.uniform(60.0, 964.0), rng.uniform(300.0, 980.0),
                        rng.uniform(1.5, 4.5)))
    return bubbles


def paint_bubbles(buf_r, buf_g, buf_b, bubbles):
    for (bx, by, br) in bubbles:
        rad = br * 1.3
        x0 = max(0, int(bx - rad))
        x1 = min(W - 1, int(bx + rad))
        y0 = max(0, int(by - rad))
        y1 = min(H - 1, int(by + rad))
        mdx = MOON_X - bx
        mdy = MOON_Y - by
        ml = math.hypot(mdx, mdy) or 1.0
        mdx /= ml
        mdy /= ml
        for yy in range(y0, y1 + 1):
            dy = yy - by
            row = yy * W
            for xx in range(x0, x1 + 1):
                dx = xx - bx
                dist = math.sqrt(dx * dx + dy * dy)
                q = dist / br
                if q > 1.25:
                    continue
                ring = max(0.0, 1.0 - abs(q - 0.80) / 0.22) * 0.30
                fill = 0.05 * (1.0 - q) if q < 1.0 else 0.0
                spec = 0.0
                if dist > 0.01 and q < 1.1:
                    facing = (dx / dist) * mdx + (dy / dist) * mdy
                    spec = max(0.0, facing) ** 7 * 0.85
                add = (ring + fill + spec) * 0.8
                i = row + xx
                buf_r[i] += 0.72 * add
                buf_g[i] += 0.84 * add
                buf_b[i] += 1.05 * add


def paint_motes(buf_r, buf_g, buf_b, rng):
    """A spiral stream of glowing motes rising between the koi."""
    for _ in range(300):
        s = rng.random() ** 1.3
        ang = 0.6 + s * 7.2
        rad = 30.0 + (1.0 - s) * 330.0 * (0.75 + 0.25 * math.sin(s * 9.0))
        cx = 512.0 + math.cos(ang) * rad * 0.82 + rng.uniform(-7.0, 7.0)
        cy = 600.0 - s * 400.0 + math.sin(ang) * rad * 0.30 + rng.uniform(-16.0, 16.0)
        size = 1.0 + (1.0 - s) * 1.8 + rng.random()
        bright = 0.25 + 0.75 * rng.random()
        if rng.random() < 0.5:
            col = (1.20, 0.90, 0.50)
        else:
            col = (0.60, 0.95, 1.10)
        reach = int(size * 3.0) + 1
        x0 = max(0, int(cx - reach))
        x1 = min(W - 1, int(cx + reach))
        y0 = max(0, int(cy - reach))
        y1 = min(H - 1, int(cy + reach))
        for yy in range(y0, y1 + 1):
            dy = yy - cy
            row = yy * W
            for xx in range(x0, x1 + 1):
                dx = xx - cx
                d2 = dx * dx + dy * dy
                fall = bright / (1.0 + d2 / (size * size)) ** 2
                i = row + xx
                buf_r[i] += col[0] * fall * 0.42
                buf_g[i] += col[1] * fall * 0.42
                buf_b[i] += col[2] * fall * 0.42
    # A few larger sparkles with cross flares.
    for _ in range(26):
        cx = rng.uniform(90.0, 934.0)
        cy = rng.uniform(120.0, 900.0)
        bright = rng.uniform(0.35, 0.8)
        for off in range(-7, 8):
            f = bright * max(0.0, 1.0 - abs(off) / 7.0) * 0.5
            xi = int(cx) + off
            yi = int(cy)
            if 0 <= xi < W and 0 <= yi < H:
                i = yi * W + xi
                buf_r[i] += 0.85 * f
                buf_g[i] += 0.92 * f
                buf_b[i] += 1.05 * f
            xi = int(cx)
            yi = int(cy) + off
            if 0 <= xi < W and 0 <= yi < H:
                i = yi * W + xi
                buf_r[i] += 0.85 * f
                buf_g[i] += 0.92 * f
                buf_b[i] += 1.05 * f
        i = int(cy) * W + int(cx)
        buf_r[i] += bright
        buf_g[i] += bright
        buf_b[i] += bright


# --------------------------------------------------------------------------
# Final pass: vignette, exponential tone map, quantise to bytes.
# --------------------------------------------------------------------------

def finish(buf_r, buf_g, buf_b):
    rgb = bytearray(W * H * 3)
    cx = W * 0.5
    cy = H * 0.5
    for y in range(H):
        ny = (y - cy) / cy
        row = y * W
        for x in range(W):
            nx = (x - cx) / cx
            r2n = nx * nx + ny * ny
            vig = 1.0 - 0.36 * smoothstep(0.30, 1.55, r2n)
            i = row + x
            o = i * 3
            for ch, buf in ((0, buf_r), (1, buf_g), (2, buf_b)):
                c = buf[i] * vig
                t = 1.0 - math.exp(-c * 1.30)
                q = int(t * 255.0 + 0.5)
                if q < 0:
                    q = 0
                elif q > 255:
                    q = 255
                rgb[o + ch] = q
    return rgb


def render():
    n = W * H
    buf_r = array("f", [0.0]) * n
    buf_g = array("f", [0.0]) * n
    buf_b = array("f", [0.0]) * n

    shimmer = make_shimmer_grid()
    paint_background(buf_r, buf_g, buf_b, shimmer)

    gold, silver = make_koi()
    cv = Canvas()
    silver.stamp_all(cv)
    gold.stamp_all(cv)
    blur_grid(cv.glow[0], 6)
    blur_grid(cv.glow[1], 6)
    composite_koi(buf_r, buf_g, buf_b, cv)

    paint_eyes(buf_r, buf_g, buf_b, gold)
    paint_eyes(buf_r, buf_g, buf_b, silver)

    rng = Rng(20261116)
    paint_bubbles(buf_r, buf_g, buf_b, bubble_list(rng, gold, silver))
    paint_motes(buf_r, buf_g, buf_b, rng)

    return finish(buf_r, buf_g, buf_b)


def main():
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(outdir, exist_ok=True)
    rgb = render()
    write_png(os.path.join(outdir, "entry.png"), W, H, rgb)


if __name__ == "__main__":
    main()
