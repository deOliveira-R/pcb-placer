"""The energy's cost terms. Each keeps its own cache and updates it move by move:

- refresh(b): recompute from scratch;
- total(b): the term's energy (weight included);
- delta(b, moves, ctx, dE): add the energy change of `moves` ({part: (x, y, rot)}) to dE; returns (dE, cache);
- commit(b, cache): accept the move.

ctx holds what several terms share: the moved parts' new pad positions ("pads") and boxes ("boxes").
The legality penalties (overlap, forbidden ground) are not terms: the Board keeps them, under the rising weight lam.
"""
from __future__ import annotations

import math

from .geometry import box_gap, mst_length


class Wirelength:
    """Airwires: each net's minimum spanning tree over its pads (45-degree length), times the net's weight."""
    name = "wirelength"

    def __init__(self, b):
        self.length = []

    def net_length(self, b, n, override=None):
        pts = []
        for i, q in b.nets[n][2]:
            pp = override.get(i) if override else None
            pts.append((pp or b.padpos[i])[q])
        return mst_length(pts)

    def refresh(self, b):
        self.length = [self.net_length(b, n) for n in range(len(b.nets))]

    def total(self, b, weights=None):
        if weights is not None:
            return sum(w * l for w, l in zip(weights, self.length))
        return sum(w * l for (_, w, _), l in zip(b.nets, self.length))

    def delta(self, b, moves, ctx, dE):
        nets = set()
        for i in moves:
            nets.update(b.nets_of[i])
        new = {}
        for n in nets:
            l = self.net_length(b, n, ctx["pads"])
            new[n] = l
            dE += b.nets[n][1] * (l - self.length[n])
        return dE, new

    def commit(self, b, cache):
        for n, l in cache.items():
            self.length[n] = l


class Springs:
    """A part held at a pin (a decoupling cap at the pin it serves): weight x distance, pad to pad."""
    name = "springs"

    def __init__(self, b):
        self.length = []

    def spring_length(self, b, s, override=None):
        a, qa, c, qc, _ = b.springs[s]
        pa = (override.get(a) if override else None) or b.padpos[a]
        pc = (override.get(c) if override else None) or b.padpos[c]
        return math.hypot(pa[qa][0] - pc[qc][0], pa[qa][1] - pc[qc][1])

    def refresh(self, b):
        self.length = [self.spring_length(b, s) for s in range(len(b.springs))]

    def total(self, b):
        return sum(s[4] * l for s, l in zip(b.springs, self.length))

    def delta(self, b, moves, ctx, dE):
        springs = set()
        for i in moves:
            springs.update(b.springs_of[i])
        new = {}
        for s in springs:
            l = self.spring_length(b, s, ctx["pads"])
            new[s] = l
            dE += b.springs[s][4] * (l - self.length[s])
        return dE, new

    def commit(self, b, cache):
        for s, l in cache.items():
            self.length[s] = l


class Bands:
    """Groups as rubber bands: each group's free members (and its fixed pads, see the `pad_groups` rule) pay
    weight x half the perimeter of the box around them, so a group pays for spreading out. weight 0: off."""
    name = "bands"

    def __init__(self, b):
        self.weight = 0.0
        self.level = ""
        self.groups = []
        self.groups_of = [[] for _ in b.P]
        self.length = []

    def configure(self, b, weight, level):
        self.weight = weight
        self.level = level
        pins = {}
        for (ref, q), lab in b.pad_labels.items():
            p = b.prob["parts"][ref]
            px, py = p["geom"][str(p["rot"])]["pads"][q]
            pins.setdefault(lab, []).append((p["x"] + px, p["y"] + py))
        groups = {}
        for i in b.movable:
            lab = b.label(i, level)
            if lab:
                groups.setdefault(lab, []).append(i)
        self.groups = [(lab, mem, pins.get(lab, [])) for lab, mem in sorted(groups.items())
                       if len(mem) + len(pins.get(lab, [])) > 1]
        self.groups_of = [[] for _ in b.P]
        for g, (_, mem, _) in enumerate(self.groups):
            for i in mem:
                self.groups_of[i].append(g)

    def group_length(self, b, g, override=None):
        _, mem, fixed = self.groups[g]
        xs, ys = [p[0] for p in fixed], [p[1] for p in fixed]
        for i in mem:
            bx = (override.get(i) if override else None) or b.box(i)
            xs += (bx[0], bx[2])
            ys += (bx[1], bx[3])
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    def refresh(self, b):
        self.length = [self.group_length(b, g) for g in range(len(self.groups))]

    def total(self, b):
        return self.weight * sum(self.length)

    def delta(self, b, moves, ctx, dE):
        new = {}
        if not self.weight:
            return dE, new
        for g in {g for i in moves for g in self.groups_of[i]}:
            l = self.group_length(b, g, ctx["boxes"])
            new[g] = l
            dE += self.weight * (l - self.length[g])
        return dE, new

    def commit(self, b, cache):
        for g, l in cache.items():
            self.length[g] = l


class Separation:
    """Dirty and fragile parts repel (the `separation` rules): each pair closer than its range pays
    weight x (range - gap) per mm, courtyard to courtyard. weight 0: off."""
    name = "separation"

    def __init__(self, b):
        self.weight = 0.0
        self.pairs = {}
        self.of = [[] for _ in b.P]

    def configure(self, b, weight, rules):
        self.weight = weight
        rng = {}
        for r in rules:
            D = [i for i in b.movable if b.label(i, r["level"]) == r["dirty"]]
            fl = r.get("fragile_level", r["level"])
            F = [j for j in b.movable if b.label(j, fl) in r["fragile"]]
            for i in D:
                for j in F:
                    k = (min(i, j), max(i, j))
                    rng[k] = max(rng.get(k, 0.0), r["range"])
        self.pairs = rng
        self.of = [[] for _ in b.P]
        for (i, j), R in rng.items():
            self.of[i].append((j, R))
            self.of[j].append((i, R))

    def intrusion(self, b):
        """Intrusion summed over the pairs (mm); 0 = every pair keeps its range."""
        return sum(max(0.0, R - box_gap(b.box(i), b.box(j))) for (i, j), R in self.pairs.items())

    def refresh(self, b):
        pass                                  # computed from the boxes on demand

    def total(self, b):
        return self.weight * self.intrusion(b) if self.weight else 0.0

    def delta(self, b, moves, ctx, dE):
        if not self.weight:
            return dE, None
        nb = ctx["boxes"]
        ds = 0.0
        for i in moves:
            bi_new, bi_old = nb[i], b.box(i)
            for j, R in self.of[i]:
                if j in moves and j < i:        # a pair of moved parts counts once
                    continue
                bj_new = nb.get(j) or b.box(j)
                ds += max(0.0, R - box_gap(bi_new, bj_new)) - max(0.0, R - box_gap(bi_old, b.box(j)))
        dE += self.weight * ds
        return dE, None

    def commit(self, b, cache):
        pass
