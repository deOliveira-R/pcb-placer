"""Legalisation: parts still overlapping or on forbidden ground go to the nearest legal spot."""
from __future__ import annotations

from .geometry import ROTS


def nearest_legal(b, i, radius=15.0, others=True, rots=None):
    """The nearest grid spot (centre distance) where part i covers no forbidden ground (and, with others, overlaps
    no other part), trying each rotation; ties go to the shorter wiring. Returns (x, y, rot) or None."""
    cx, cy = b.centre(i)
    g = b.grid
    n = int(radius / g)
    cands = []
    for dx in range(-n, n + 1):
        for dy in range(-n, n + 1):
            d = (dx * dx + dy * dy) * g * g
            if d <= radius * radius:
                cands.append((d, dx * g, dy * g))
    cands.sort()
    rots = rots or [b.rot[i]] + [r for r in ROTS if r != b.rot[i]]
    best = None
    for d, dx, dy in cands:
        if best and d > best[0] + 1e-9:
            break
        for r in rots:
            x, y = b.at_centre(i, cx + dx, cy + dy, r)
            if b.ground_cost(i, x, y, r) > 0:
                continue
            if others:
                gi = b.grown(i, x, y, r)
                if any(b.pair_overlap(i, j, gi) > 0 for j in b.movable if j != i):
                    continue
            e = sum(b.nets[n_][1] * b.net_length(n_, {i: b.pads(i, x, y, r)}) for n_ in b.nets_of[i])
            if best is None or e < best[1]:
                best = (d, e, (x, y, r))
        if best:
            return best[2]
    return best[2] if best else None


def legalize(b, passes=3):
    """Parts still overlapping or on forbidden ground go to the nearest legal spot (worst first), then a zero-
    temperature polish of small shifts and rotations that keep everything legal. Returns the parts left illegal."""
    for _ in range(passes):
        bad = sorted((i for i in b.movable if b.violation(i) > 1e-9), key=b.violation, reverse=True)
        if not bad:
            break
        for i in bad:
            if b.violation(i) <= 1e-9:
                continue
            spot = nearest_legal(b, i, radius=25.0)
            if spot:
                b.set(i, *spot)
    b.lam = 1e6
    g = b.grid
    for _ in range(4):
        improved = False
        for i in b.movable:
            if b.violation(i) > 1e-9:
                continue
            for dx, dy, r in [(g, 0, None), (-g, 0, None), (0, g, None), (0, -g, None)] + [(0, 0, r) for r in ROTS]:
                if r is None:
                    mv = {i: (b.x[i] + dx, b.y[i] + dy, b.rot[i])}
                else:
                    if r == b.rot[i]:
                        continue
                    cx, cy = b.centre(i)
                    mv = {i: (*b.at_centre(i, cx, cy, r), r)}
                dE, cache = b.delta(mv)
                if dE < -1e-6:
                    b.commit(cache)
                    improved = True
        if not improved:
            break
    b.refresh()
    return [b.refs[i] for i in b.movable if b.violation(i) > 1e-9]
