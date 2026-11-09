"""The initial guess: airwires as springs, solved against the fixed parts, then spread until parts stop overlapping.

The springs' arrangement is the guess: parts that share many nets end up together, so the groups (islands)
assemble by themselves. Naming the groups (island > 1 in spring_list) makes the springs inside a group stiffer.
"""
from __future__ import annotations

import math
import random

from .geometry import ROTS, box_gap
from .legalize import nearest_legal


def spring_list(b, island=1.0, level=None):
    """Airwires as springs between pads: (i, qi, j, qj, k). A net of k pads is a clique of weight 1/(k-1) per pair
    (the clique's total pull on one pad equals one airwire's). Pads of the same part don't pull on each other.
    island > 1: springs within a group (at `level`) are that many times stiffer; a fixed pad in a group (the
    `pad_groups` rule) counts as a member."""
    levels = b.rules["group_levels"]
    level = level or (levels[0] if levels else "")
    lab = [b.label(i, level) for i in range(len(b.P))]
    plab = {(b.idx[r], q): l for (r, q), l in b.pad_labels.items()}
    out = []
    for name, w, pins in b.nets:
        k = len(pins)
        for a in range(k):
            for c in range(a + 1, k):
                (i, qi), (j, qj) = pins[a], pins[c]
                if i == j:
                    continue
                kk = w / (k - 1)
                li = plab.get((i, qi)) or lab[i]
                lj = plab.get((j, qj)) or lab[j]
                if island != 1.0 and li and li == lj:
                    kk *= island
                out.append((i, qi, j, qj, kk))
    for i, qi, j, qj, w in b.springs:
        k = w
        if island != 1.0 and lab[i] == lab[j]:
            k *= island
        out.append((i, qi, j, qj, k))
    return out


def solve_springs(b, springs, sweeps=300, rotate_rounds=3):
    """Gauss-Seidel: each free part moves to where its springs balance (pads at the part's current rotation);
    between rounds each part takes the rotation with the least spring energy (the springs' torque, made discrete)."""
    by_part = [[] for _ in b.P]
    for s in springs:
        i, qi, j, qj, k = s
        by_part[i].append((qi, j, qj, k))
        by_part[j].append((qj, i, qi, k))
    for rnd in range(rotate_rounds + 1):
        for _ in range(sweeps):
            for i in b.movable:
                sx = sy = sk = 0.0
                off = b.geom[i][b.rot[i]][1]
                for qi, j, qj, k in by_part[i]:
                    ox, oy = b.geom[j][b.rot[j]][1][qj]
                    sx += k * (b.x[j] + ox - off[qi][0])
                    sy += k * (b.y[j] + oy - off[qi][1])
                    sk += k
                if sk:
                    b.x[i], b.y[i] = sx / sk, sy / sk
        if rnd == rotate_rounds:
            break
        for i in b.movable:
            cx, cy = b.centre(i)
            best = (math.inf, b.rot[i], b.x[i], b.y[i])
            for r in ROTS:
                bx = b.geom[i][r][0]
                x, y = cx - (bx[0] + bx[2]) / 2, cy - (bx[1] + bx[3]) / 2
                e = 0.0
                for qi, j, qj, k in by_part[i]:
                    px, py = b.geom[i][r][1][qi]
                    ox, oy = b.geom[j][b.rot[j]][1][qj]
                    e += k * ((x + px - b.x[j] - ox) ** 2 + (y + py - b.y[j] - oy) ** 2)
                if e < best[0]:
                    best = (e, r, x, y)
            _, b.rot[i], b.x[i], b.y[i] = best
    b.refresh()


def spread(b, springs, rounds=300, step_cap=1.0, seed=0):
    """Contact relaxation: the springs pull (a relaxed Gauss-Seidel step whose pull fades over the rounds), touching
    parts push each other apart along the axis of least overlap (the lighter part moves more), and the board pushes
    back (a part on forbidden ground steps to the nearest legal spot). The pile opens up only as far as the contacts
    need, so the springs' arrangement (the islands) survives."""
    rng = random.Random(seed)
    by_part = [[] for _ in b.P]
    for i, qi, j, qj, k in springs:
        by_part[i].append((qi, j, qj, k))
        by_part[j].append((qj, i, qi, k))
    m = b.movable
    area = {i: (lambda r: (r[2] - r[0]) * (r[3] - r[1]))(b.grown(i)) for i in m}
    for rnd in range(rounds):
        pull = 0.4 * (1 - rnd / rounds) + 0.02
        for i in m:
            sx = sy = sk = 0.0
            off = b.geom[i][b.rot[i]][1]
            for qi, j, qj, k in by_part[i]:
                ox, oy = b.geom[j][b.rot[j]][1][qj]
                sx += k * (b.x[j] + ox - off[qi][0])
                sy += k * (b.y[j] + oy - off[qi][1])
                sk += k
            if sk:
                b.x[i] += pull * (sx / sk - b.x[i])
                b.y[i] += pull * (sy / sk - b.y[i])
        grow = {i: b.grown(i) for i in m}
        dx = dict.fromkeys(m, 0.0)
        dy = dict.fromkeys(m, 0.0)
        for a_ in range(len(m)):
            i = m[a_]
            gi = grow[i]
            for j in m[a_ + 1:]:
                if not (b.sides[i] & b.sides[j]):
                    continue
                gj = grow[j]
                w = min(gi[2], gj[2]) - max(gi[0], gj[0])
                h = min(gi[3], gj[3]) - max(gi[1], gj[1])
                if w <= 0 or h <= 0:
                    continue
                share_i = area[j] / (area[i] + area[j])
                if w < h:
                    sgn = 1 if gi[0] + gi[2] > gj[0] + gj[2] else (-1 if gi[0] + gi[2] < gj[0] + gj[2] else rng.choice((-1, 1)))
                    dx[i] += sgn * w * share_i
                    dx[j] -= sgn * w * (1 - share_i)
                else:
                    sgn = 1 if gi[1] + gi[3] > gj[1] + gj[3] else (-1 if gi[1] + gi[3] < gj[1] + gj[3] else rng.choice((-1, 1)))
                    dy[i] += sgn * h * share_i
                    dy[j] -= sgn * h * (1 - share_i)
        if b.sep.weight:          # noise separation: pairs inside their range push apart along the line of centres
            for (i, j), R in b.sep.pairs.items():
                gi, gj = grow[i], grow[j]
                intr = R - box_gap(gi, gj)
                if intr <= 0:
                    continue
                vx = (gi[0] + gi[2] - gj[0] - gj[2]) / 2
                vy = (gi[1] + gi[3] - gj[1] - gj[3]) / 2
                d = math.hypot(vx, vy) or 1.0
                f = 0.15 * intr / d
                share_i = area[j] / (area[i] + area[j])
                dx[i] += vx * f * share_i
                dy[i] += vy * f * share_i
                dx[j] -= vx * f * (1 - share_i)
                dy[j] -= vy * f * (1 - share_i)
        for i in m:
            d = math.hypot(dx[i], dy[i])
            f = min(1.0, step_cap / d) if d > 0 else 0.0
            b.x[i] += dx[i] * f
            b.y[i] += dy[i] * f
        if rnd % 5 == 4 or rnd == rounds - 1:
            for i in m:
                if b.ground_cost(i) > 0:
                    spot = nearest_legal(b, i, radius=6.0, others=False, rots=[b.rot[i]])
                    if spot:
                        b.x[i], b.y[i], _ = spot
    g = b.grid
    for i in m:
        b.x[i], b.y[i] = round(b.x[i] / g) * g, round(b.y[i] / g) * g
    b.refresh()
