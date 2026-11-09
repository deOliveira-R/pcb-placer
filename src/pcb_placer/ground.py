"""What a part may not cover on one face, as a raster with a summed-area table: the covered area of any box in O(1).

Forbidden: outside the outline, within the edge margin, the keep-out shapes (circles, rects, capsules) and the fixed
parts' courtyards (grown by the gap).
"""
from __future__ import annotations

import math


class Ground:
    """Forbidden cells on one face for one edge margin, as a summed-area table: covered area of any box in O(1)."""

    def __init__(self, prob, side, margin, copper_only=False):
        """side: the face; margin: the courtyard-to-edge distance; copper_only: for copper reaching the other face
        (exposed-pad vias), which only has to stay outside the anchors' outlines, not a gap away."""
        g = self.g = prob["grid"]
        poly = prob["outline"]
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        self.x0, self.y0 = min(xs) - 2, min(ys) - 2
        self.nx = int((max(xs) + 2 - self.x0) / g) + 1
        self.ny = int((max(ys) + 2 - self.y0) / g) + 1
        bad = [[True] * self.nx for _ in range(self.ny)]
        # inside the outline (scanline crossings per cell row)
        n = len(poly)
        for iy in range(self.ny):
            y = self.y0 + (iy + 0.5) * g
            xc = []
            for i in range(n):
                ax, ay = poly[i]
                bx, by = poly[(i + 1) % n]
                if (ay > y) != (by > y):
                    xc.append(ax + (y - ay) * (bx - ax) / (by - ay))
            xc.sort()
            for a, b in zip(xc[::2], xc[1::2]):
                for ix in range(max(0, math.ceil((a - self.x0) / g - 0.5)), min(self.nx, math.floor((b - self.x0) / g - 0.5) + 1)):
                    bad[iy][ix] = False
        # the edge margin, the keep-outs (circles and capsules exact, rects grown by the gap), fixed parts on this face
        for i in range(n):                       # every edge, sampled at the cell pitch
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % n]
            steps = max(1, int(math.hypot(bx - ax, by - ay) / g))
            for k in range(steps):
                self._disc(bad, ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps, margin)
        obs = prob["obstacles"][side]
        for cx, cy, r in obs["circles"]:
            self._disc(bad, cx, cy, r)
        for ax, ay, bx, by, r in obs["capsules"]:     # a line r wide each side: discs at the cell pitch
            steps = max(1, int(math.hypot(bx - ax, by - ay) / g))
            for k in range(steps + 1):
                self._disc(bad, ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps, r)
        gap = 0.0 if copper_only else prob["gap"]     # other-face copper: outside the anchors' outlines suffices
        rects = [(a - gap, b - gap, c + gap, d + gap) for a, b, c, d in obs["rects"]]
        for p in prob["parts"].values():
            if p["fixed"] and (p["side"] == side or p["both_faces"]):
                bx0, by0, bx1, by1 = p["geom"][str(p["rot"])]["box"]
                rects.append((p["x"] + bx0 - gap, p["y"] + by0 - gap, p["x"] + bx1 + gap, p["y"] + by1 + gap))
        for r in rects:
            ix0, iy0, ix1, iy1 = self._span(r)
            for iy in range(max(iy0, 0), min(iy1, self.ny - 1) + 1):
                row = bad[iy]
                for ix in range(max(ix0, 0), min(ix1, self.nx - 1) + 1):
                    row[ix] = True
        self.bad = bad
        # summed-area table, one row and column of zeros in front
        S = [[0] * (self.nx + 1) for _ in range(self.ny + 1)]
        for iy in range(self.ny):
            acc = 0
            row, prev, cur = bad[iy], S[iy], S[iy + 1]
            for ix in range(self.nx):
                acc += row[ix]
                cur[ix + 1] = prev[ix + 1] + acc
        self.S = S

    def _disc(self, bad, cx, cy, r):
        g = self.g
        for iy in range(max(0, int((cy - r - self.y0) / g) - 1), min(self.ny, int((cy + r - self.y0) / g) + 2)):
            y = self.y0 + (iy + 0.5) * g
            for ix in range(max(0, int((cx - r - self.x0) / g) - 1), min(self.nx, int((cx + r - self.x0) / g) + 2)):
                x = self.x0 + (ix + 0.5) * g
                if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                    bad[iy][ix] = True

    def _span(self, r):
        """Cells whose centres lie inside the box (inclusive index range)."""
        g = self.g
        return (math.ceil((r[0] - self.x0) / g - 0.5), math.ceil((r[1] - self.y0) / g - 0.5),
                math.floor((r[2] - self.x0) / g - 0.5), math.floor((r[3] - self.y0) / g - 0.5))

    def cost(self, r):
        """Forbidden area (mm^2) under the box; cells beyond the map count as forbidden."""
        ix0, iy0, ix1, iy1 = self._span(r)
        if ix1 < ix0 or iy1 < iy0:
            return 0.0
        total = (ix1 - ix0 + 1) * (iy1 - iy0 + 1)
        a0, b0 = max(ix0, 0), max(iy0, 0)
        a1, b1 = min(ix1, self.nx - 1), min(iy1, self.ny - 1)
        inside = 0
        bad = 0
        if a1 >= a0 and b1 >= b0:
            S = self.S
            inside = (a1 - a0 + 1) * (b1 - b0 + 1)
            bad = S[b1 + 1][a1 + 1] - S[b0][a1 + 1] - S[b1 + 1][a0] + S[b0][a0]
        return (bad + total - inside) * self.g * self.g
