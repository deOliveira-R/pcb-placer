"""Simulated annealing on the full energy, and the random start (the no-guess baseline)."""
from __future__ import annotations

import math
import random

from .geometry import ROTS


def random_start(b, seed=0):
    """Every free part at a random spot on its face and a random rotation (the no-initial-guess baseline)."""
    rng = random.Random(seed)
    for i in b.movable:
        G = b.ground[i]
        x, y, r = b.x[i], b.y[i], b.rot[i]
        for _ in range(2000):
            r = rng.choice(ROTS)
            x = G.x0 + rng.random() * G.nx * G.g
            y = G.y0 + rng.random() * G.ny * G.g
            x, y = b.at_centre(i, x, y, r)
            if b.ground_cost(i, x, y, r) == 0:
                break
        b.x[i], b.y[i], b.rot[i] = x, y, r
    b.refresh()


def anneal(b, seed=0, t0=None, accept0=0.5, temps=120, per_part=25, lam=(1.0, 200.0), t_end_ratio=1e-3,
           trace=None, eval_lam=10.0, window0=None):
    """Simulated annealing. t0: starting temperature, or None to pick the one where `accept0` of uphill moves are
    accepted (0.8 = hot, forgets the start; 0.2 = warm, refines it). Geometric cooling over `temps` steps of
    `per_part` x (free parts) moves each; the overlap weight rises from lam[0] to lam[1].
    trace: a list that receives (moves so far, energy at a fixed lam = eval_lam) after each temperature step."""
    rng = random.Random(seed)
    m = b.movable
    n = len(m)
    b.lam = lam[0]
    # swap partners: same face, similar courtyard size
    area = {i: (lambda bx: (bx[2] - bx[0]) * (bx[3] - bx[1]))(b.geom[i][0][0]) for i in m}
    partners = {i: [j for j in m if j != i and b.sides[j] == b.sides[i] and 0.67 < area[j] / area[i] < 1.5] for i in m}
    G0 = b.ground[m[0]]
    window = window0 or max(G0.nx, G0.ny) * G0.g / 4     # shift reach (mm); a cool start keeps it small

    def propose():
        i = rng.choice(m)
        u = rng.random()
        if u < 0.15:
            r = (b.rot[i] + rng.choice((90, 180, 270))) % 360
            cx, cy = b.centre(i)
            return "rot", {i: (*b.at_centre(i, cx, cy, r), r)}
        if u < 0.30 and partners[i]:
            j = rng.choice(partners[i])
            ci, cj = b.centre(i), b.centre(j)
            return "swap", {i: (*b.at_centre(i, *cj, b.rot[i]), b.rot[i]), j: (*b.at_centre(j, *ci, b.rot[j]), b.rot[j])}
        g = b.grid
        dx = round(rng.uniform(-window, window) / g) * g
        dy = round(rng.uniform(-window, window) / g) * g
        if dx == 0 and dy == 0:
            dx = g
        return "shift", {i: (b.x[i] + dx, b.y[i] + dy, b.rot[i])}

    if trace is not None:
        trace.append((0, b.wirelength(common=True) + b.spring_energy() + eval_lam * (b.overlap_total() + b.out_total())))
    if t0 is None:
        ups = []
        for _ in range(300):
            _, mv = propose()
            dE, _ = b.delta(mv)
            if dE > 0:
                ups.append(dE)
        mean = sum(ups) / len(ups) if ups else 1.0
        t0 = -mean / math.log(accept0)
    alpha = t_end_ratio ** (1 / max(temps - 1, 1))
    T = t0
    moves = 0
    for k in range(temps):
        b.lam = lam[0] * (lam[1] / lam[0]) ** (k / max(temps - 1, 1))
        acc_shift = tried_shift = 0
        for _ in range(per_part * n):
            kind, mv = propose()
            dE, cache = b.delta(mv)
            ok = dE <= 0 or rng.random() < math.exp(-dE / T)
            if ok:
                b.commit(cache)
            if kind == "shift":
                tried_shift += 1
                acc_shift += ok
            moves += 1
        # keep about 44 % of shifts accepted (Lam's rule): the window shrinks as the layout settles
        if tried_shift:
            rate = acc_shift / tried_shift
            window = min(max(window * (1.1 if rate > 0.44 else 0.9), b.grid), max(G0.nx, G0.ny) * G0.g / 2)
        if trace is not None:
            trace.append((moves, b.wirelength(common=True) + b.spring_energy() + eval_lam * (b.overlap_total() + b.out_total())))
        T *= alpha
    b.refresh()
    return t0
