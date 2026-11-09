"""A problem and one placement of it, with the energy kept up to date move by move.

Energy (all lengths in mm):
  E =   wirelength   sum over nets of weight x MST length of its pads (plane nets: 0)
      + springs      sum over springs of weight x distance (a part held at the pin it serves)
      + bands        weight x half-perimeter of each group's box (off unless set)
      + separation   weight x intrusion of dirty-fragile pairs (off unless set)
      + lam x (overlap between parts' courtyards, each grown by gap/2
               + courtyard area on forbidden ground)

The two last are the legality penalties: lam rises while annealing, so parts may pass through each other early on
and must not at the end.
"""
from __future__ import annotations

from .geometry import box_gap, overlap
from .ground import Ground
from .problem import pad_labels
from .terms import Bands, Separation, Springs, Wirelength


class Board:
    def __init__(self, prob, weights=None, eval_weights=None):
        """weights: {net: airwire weight} for the energy (default 1; see problem.net_weights). eval_weights: the
        weights every placement is scored with (default: the same)."""
        self.prob = prob
        self.rules = prob["rules"]
        self.gap = prob["gap"]
        self.grid = prob["grid"]
        self.refs = sorted(prob["parts"])
        self.idx = {r: i for i, r in enumerate(self.refs)}
        P = [prob["parts"][r] for r in self.refs]
        self.P = P
        self.fixed = [p["fixed"] for p in P]
        self.movable = [i for i, p in enumerate(P) if not p["fixed"]]
        self.sides = [frozenset([p["side"]] + (["F", "B"] if p["both_faces"] else [])) for p in P]
        self.pad_labels = pad_labels(prob)
        grounds = {}
        self.ground = []
        for p in P:
            key = (p["side"], p["edge_margin"])
            if key not in grounds:
                grounds[key] = Ground(prob, *key)
            self.ground.append(grounds[key])
        # a free part with copper on the other face too (exposed-pad vias): there, only the box round that copper counts
        self.other_ground = [None] * len(P)
        for i, p in enumerate(P):
            if not p["fixed"] and p["both_faces"] and "copper_other_face" in p["geom"]["0"]:
                key = ("B" if p["side"] == "F" else "F", p["edge_margin"], True)
                if key not in grounds:
                    grounds[key] = Ground(prob, *key)
                self.other_ground[i] = grounds[key]
        self.geom = [{int(k): (tuple(v["box"]), [tuple(q) for q in v["pads"]]) for k, v in p["geom"].items()} for p in P]
        # nets: plane nets and nets within one part carry no airwire
        weights = weights or {}
        plane = set(prob["plane_nets"])
        self.nets = []          # (name, weight, [(part, pad)])
        for name, pins in sorted(prob["nets"].items()):
            w = 0.0 if name in plane else weights.get(name, 1.0)
            pins = [(self.idx[r], q) for r, q in pins]
            if w > 0 and len({i for i, _ in pins}) > 1:
                self.nets.append((name, w, pins))
        ew = eval_weights if eval_weights is not None else weights
        self.eval_w = [ew.get(name, 1.0) for name, _, _ in self.nets]
        sw = self.rules["spring_weight"]
        self.springs = [(self.idx[a], qa, self.idx[c], qc, sw) for a, qa, c, qc in prob["springs"]]
        self.nets_of = [[] for _ in P]
        for n, (_, _, pins) in enumerate(self.nets):
            for i in {i for i, _ in pins}:
                self.nets_of[i].append(n)
        self.springs_of = [[] for _ in P]
        for s, (a, _, c, _, _) in enumerate(self.springs):
            self.springs_of[a].append(s)
            self.springs_of[c].append(s)
        self.x = [p["x"] for p in P]
        self.y = [p["y"] for p in P]
        self.rot = [p["rot"] for p in P]
        self.lam = 10.0
        self.wl = Wirelength(self)
        self.spr = Springs(self)
        self.bands = Bands(self)
        self.sep = Separation(self)
        self.terms = [self.wl, self.spr, self.bands, self.sep]      # summed in this order
        levels = self.rules["group_levels"]
        self.bands.configure(self, 0.0, levels[0] if levels else "")
        self.sep.configure(self, 0.0, self.rules["separation"])
        self.refresh()

    # ---------------------------------------------------------------- configuration
    def label(self, i, level):
        return self.P[i]["groups"].get(level, "")

    def set_bands(self, weight, level=None):
        levels = self.rules["group_levels"]
        self.bands.configure(self, weight, level or (levels[0] if levels else ""))
        self.bands.refresh(self)

    def set_separation(self, weight):
        self.sep.configure(self, weight, self.rules["separation"])

    # ---------------------------------------------------------------- geometry
    def box(self, i, x=None, y=None, rot=None):
        x = self.x[i] if x is None else x
        y = self.y[i] if y is None else y
        b = self.geom[i][self.rot[i] if rot is None else rot][0]
        return (x + b[0], y + b[1], x + b[2], y + b[3])

    def grown(self, i, x=None, y=None, rot=None):
        h = self.gap / 2
        a = self.box(i, x, y, rot)
        return (a[0] - h, a[1] - h, a[2] + h, a[3] + h)

    def pads(self, i, x=None, y=None, rot=None):
        x = self.x[i] if x is None else x
        y = self.y[i] if y is None else y
        return [(x + dx, y + dy) for dx, dy in self.geom[i][self.rot[i] if rot is None else rot][1]]

    def centre(self, i, rot=None):
        b = self.geom[i][self.rot[i] if rot is None else rot][0]
        return self.x[i] + (b[0] + b[2]) / 2, self.y[i] + (b[1] + b[3]) / 2

    def at_centre(self, i, cx, cy, rot):
        """The position that puts part i's box centre at (cx, cy) in rotation rot, snapped to the grid."""
        b = self.geom[i][rot][0]
        g = self.grid
        return round((cx - (b[0] + b[2]) / 2) / g) * g, round((cy - (b[1] + b[3]) / 2) / g) * g

    def ground_cost(self, i, x=None, y=None, rot=None):
        """Forbidden area under part i (mm^2): its courtyard on its own face, its other-face copper on the other."""
        c = self.ground[i].cost(self.box(i, x, y, rot))
        if self.other_ground[i] is not None:
            x = self.x[i] if x is None else x
            y = self.y[i] if y is None else y
            k = self.P[i]["geom"][str(self.rot[i] if rot is None else rot)]["copper_other_face"]
            c += self.other_ground[i].cost((x + k[0], y + k[1], x + k[2], y + k[3]))
        return c

    def pair_overlap(self, i, j, gi=None, gj=None):
        if not (self.sides[i] & self.sides[j]):
            return 0.0
        return overlap(gi or self.grow[i], gj or self.grow[j])

    # ---------------------------------------------------------------- energy
    def refresh(self):
        """Recompute every cached term from scratch."""
        self.padpos = [self.pads(i) for i in range(len(self.P))]
        for t in self.terms:
            t.refresh(self)
        self.grow = [self.grown(i) for i in range(len(self.P))]
        self.out = [0.0 if self.fixed[i] else self.ground_cost(i) for i in range(len(self.P))]

    def net_length(self, n, override=None):
        return self.wl.net_length(self, n, override)

    def wirelength(self, common=False):
        """Weighted airwire length: with the energy's weights, or (common) the scoring weights."""
        return self.wl.total(self, self.eval_w if common else None)

    def spring_energy(self):
        return self.spr.total(self)

    def overlap_total(self):
        m = self.movable
        tot = 0.0
        for a in range(len(m)):
            i = m[a]
            for j in m[a + 1:]:
                tot += self.pair_overlap(i, j)
        return tot

    def out_total(self):
        return sum(self.out)

    def separation_intrusion(self):
        return self.sep.intrusion(self)

    def energy(self, lam=None):
        lam = self.lam if lam is None else lam
        return sum(t.total(self) for t in self.terms) + lam * (self.overlap_total() + self.out_total())

    # ---------------------------------------------------------------- moves
    def delta(self, moves):
        """Energy change if parts move: moves = {i: (x, y, rot)}. Returns (dE, cache to commit)."""
        lam = self.lam
        newpads = {i: self.pads(i, *m) for i, m in moves.items()}
        newgrow = {i: self.grown(i, *m) for i, m in moves.items()}
        ctx = {"pads": newpads, "boxes": {i: self.box(i, *m) for i, m in moves.items()}}
        dE = 0.0
        caches = []
        for t in self.terms:
            dE, c = t.delta(self, moves, ctx, dE)
            caches.append(c)
        dov = 0.0
        moved = list(moves)
        for i in moved:
            gi_new, gi_old = newgrow[i], self.grow[i]
            for j in self.movable:
                if j == i or j in moves:
                    continue
                dov += self.pair_overlap(i, j, gi_new) - self.pair_overlap(i, j, gi_old)
        for a in range(len(moved)):          # pairs among the moved parts
            for c in range(a + 1, len(moved)):
                i, j = moved[a], moved[c]
                dov += self.pair_overlap(i, j, newgrow[i], newgrow[j]) - self.pair_overlap(i, j)
        new_out = {}
        for i, m in moves.items():
            o = self.ground_cost(i, *m)
            new_out[i] = o
            dov += o - self.out[i]
        dE += lam * dov
        return dE, (moves, newpads, newgrow, new_out, caches)

    def commit(self, cache):
        moves, newpads, newgrow, new_out, caches = cache
        for t, c in zip(self.terms, caches):
            t.commit(self, c)
        for i, (x, y, r) in moves.items():
            self.x[i], self.y[i], self.rot[i] = x, y, r
            self.padpos[i] = newpads[i]
            self.grow[i] = newgrow[i]
            self.out[i] = new_out[i]

    def set(self, i, x, y, rot):
        _, cache = self.delta({i: (x, y, rot)})
        self.commit(cache)

    def violation(self, i):
        """Overlap with other parts plus forbidden ground under part i (mm^2)."""
        if self.fixed[i]:
            return 0.0
        return self.out[i] + sum(self.pair_overlap(i, j) for j in self.movable if j != i)

    # ---------------------------------------------------------------- I/O
    def placement(self):
        return {self.refs[i]: [round(self.x[i], 4), round(self.y[i], 4), self.rot[i]] for i in range(len(self.P))}

    def load_placement(self, pl):
        for r, (x, y, rot) in pl.items():
            i = self.idx[r]
            self.x[i], self.y[i], self.rot[i] = x, y, rot
        self.refresh()


def separated_gap(b, rule):
    """For a separation rule: the closest dirty-to-fragile gap (mm) and the summed intrusion (mm)."""
    D = [i for i in b.movable if b.label(i, rule["level"]) == rule["dirty"]]
    fl = rule.get("fragile_level", rule["level"])
    F = [j for j in b.movable if b.label(j, fl) in rule["fragile"]]
    gaps = [box_gap(b.box(i), b.box(j)) for i in D for j in F]
    if not gaps:
        return None, 0.0
    return min(gaps), sum(max(0.0, rule["range"] - g) for g in gaps)
