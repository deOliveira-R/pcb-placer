"""Plane geometry: boxes, 45-degree track length, minimum spanning trees, polygons, keep-out capsules.

Boxes are (x0, y0, x1, y1) tuples in mm, x0 <= x1 and y0 <= y1.
"""
from __future__ import annotations

import math

ROTS = (0, 90, 180, 270)


def overlap(a, b):
    """Overlap area of two boxes (0 if they don't overlap)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    if w <= 0:
        return 0.0
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if h > 0 else 0.0


def box_gap(a, c):
    """Distance between two boxes (0 if they touch or overlap)."""
    return math.hypot(max(a[0] - c[2], 0.0, c[0] - a[2]), max(a[1] - c[3], 0.0, c[1] - a[3]))


def octile(dx, dy):
    """Track length between two points with 45-degree routing (what a router lays)."""
    dx, dy = abs(dx), abs(dy)
    return max(dx, dy) + 0.41421356 * min(dx, dy)


def mst_length(pts):
    """Prim's minimum spanning tree over the points (octile metric). Small nets: O(k^2) is fine."""
    k = len(pts)
    if k < 2:
        return 0.0
    if k == 2:
        return octile(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])
    best = [math.inf] * k
    used = [False] * k
    best[0] = 0.0
    total = 0.0
    for _ in range(k):
        i = min((j for j in range(k) if not used[j]), key=best.__getitem__)
        used[i] = True
        total += best[i]
        xi, yi = pts[i]
        for j in range(k):
            if not used[j]:
                d = octile(xi - pts[j][0], yi - pts[j][1])
                if d < best[j]:
                    best[j] = d
    return total


def mst_edges(pts):
    """The MST's edges as index pairs (for airwire plots and crossing counts)."""
    k = len(pts)
    if k < 2:
        return []
    best = [math.inf] * k
    parent = [-1] * k
    used = [False] * k
    best[0] = 0.0
    edges = []
    for _ in range(k):
        i = min((j for j in range(k) if not used[j]), key=best.__getitem__)
        used[i] = True
        if parent[i] >= 0:
            edges.append((parent[i], i))
        for j in range(k):
            if not used[j]:
                d = octile(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
                if d < best[j]:
                    best[j], parent[j] = d, i
    return edges


def point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def nearest_on_poly(x, y, poly):
    """The closest point of a closed polygon's boundary: (distance, qx, qy)."""
    best = (math.inf, x, y)
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1.0)))
        qx, qy = ax + t * dx, ay + t * dy
        d = ((x - qx) ** 2 + (y - qy) ** 2) ** 0.5
        if d < best[0]:
            best = (d, qx, qy)
    return best


def hole_corridors(holes, outline, radius, between, to_edge):
    """Keep-out capsules round mounting holes or pins that need hand or tool access: a band `radius` wide each side
    of the line between neighbouring holes up to `between` apart, and from each hole to its nearest edge point up to
    `to_edge` away. Returns [x0, y0, x1, y1, radius] lists (the problem file's `capsules`)."""
    caps = []
    for k, (x, y) in enumerate(holes):
        for x2, y2 in holes[k + 1:]:
            if ((x - x2) ** 2 + (y - y2) ** 2) ** 0.5 <= between:
                caps.append([x, y, x2, y2, radius])
        d, qx, qy = nearest_on_poly(x, y, outline)
        if d <= to_edge:
            caps.append([x, y, round(qx, 4), round(qy, 4), radius])
    return caps
