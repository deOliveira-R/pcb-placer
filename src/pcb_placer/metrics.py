"""Scores for a placement, the same for a reference layout and every candidate."""
from __future__ import annotations

import math
import random
from collections import defaultdict

from .board import separated_gap
from .geometry import mst_edges


def airwires(b):
    """Every net's MST edges as segments ((x0, y0), (x1, y1), net index)."""
    segs = []
    for n, (_, _, pins) in enumerate(b.nets):
        pts = [b.padpos[i][q] for i, q in pins]
        for a, c in mst_edges(pts):
            if pts[a] != pts[c]:
                segs.append((pts[a], pts[c], n))
    return segs


def _cross(p, q, r, s):
    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return (v > 1e-9) - (v < -1e-9)
    return orient(p, q, r) * orient(p, q, s) < 0 and orient(r, s, p) * orient(r, s, q) < 0


def crossings(b):
    """Pairs of airwires of different nets that cross: each is a place where one of them must change layer."""
    segs = airwires(b)
    boxes = [(min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])) for p, q, _ in segs]
    count = 0
    for a in range(len(segs)):
        pa, qa, na = segs[a]
        ba = boxes[a]
        for c in range(a + 1, len(segs)):
            pc, qc, nc = segs[c]
            if na == nc:
                continue
            bc = boxes[c]
            if ba[2] < bc[0] or bc[2] < ba[0] or ba[3] < bc[1] or bc[3] < ba[1]:
                continue
            if _cross(pa, qa, pc, qc):
                count += 1
    return count


def silhouette(b, level):
    """How well the parts sit with their own group: for each free part, a = mean distance to its group's other
    parts, c = the smallest mean distance to another group; s = (c - a) / max(a, c). Mean over parts: 1 = tight,
    separate groups; 0 = mixed; negative = parts nearer another group than their own."""
    groups = defaultdict(list)
    for i in b.movable:
        lab = b.label(i, level)
        if lab:
            groups[lab].append(i)
    ctr = {i: b.centre(i) for i in b.movable}
    scores = []
    for lab, mem in groups.items():
        if len(mem) < 2:
            continue
        for i in mem:
            xi, yi = ctr[i]
            a = sum(math.hypot(xi - ctr[j][0], yi - ctr[j][1]) for j in mem if j != i) / (len(mem) - 1)
            c = min(sum(math.hypot(xi - ctr[j][0], yi - ctr[j][1]) for j in o) / len(o)
                    for l2, o in groups.items() if l2 != lab)
            scores.append((c - a) / max(a, c, 1e-9))
    return sum(scores) / len(scores) if scores else 0.0


def score(b):
    """The common score: energy = airwires (scoring weights) + springs; penalties; crossings; cohesion per group
    level; per separation rule the closest gap and the intrusion."""
    wl = b.wirelength(common=True)
    out = dict(wirelength=round(wl, 1), springs=round(b.spring_energy(), 1), energy=round(wl + b.spring_energy(), 1),
               overlap=round(b.overlap_total(), 2), off_ground=round(b.out_total(), 2), crossings=crossings(b))
    for level in b.rules["group_levels"]:
        out[f"cohesion_{level}"] = round(silhouette(b, level), 3)
    out.update(separation(b))
    return out


def separation(b):
    """The separation rules as metrics: per rule, the closest dirty-to-fragile gap (mm) and the intrusion summed over
    pairs inside the range (mm; 0 = rule kept)."""
    out = {}
    for r in b.rules["separation"]:
        g, intr = separated_gap(b, r)
        if g is not None:
            out[f"gap_{r['dirty']}"] = round(g, 1)
            out[f"intrusion_{r['dirty']}"] = round(intr, 1)
    return out


def fill(b):
    """How full each face is: free parts' courtyards (grown by half the gap) over the legal ground."""
    out = {}
    for side in "FB":
        free = [i for i in b.movable if b.P[i]["side"] == side]
        if not free:
            continue
        G = b.ground[free[0]]
        legal = sum(row.count(False) for row in G.bad) * G.g * G.g
        area = sum((lambda r: (r[2] - r[0]) * (r[3] - r[1]))(b.grown(i)) for i in free)
        out[side] = dict(parts=len(free), courtyards_mm2=round(area), legal_mm2=round(legal), fill=round(area / legal, 3))
    return out


# -------------------------------------------------------------------- does the netlist alone know the groups?
def part_graph(b):
    """Part-to-part connection strength from the netlist only (GND dropped; a net of k parts gives 1/(k-1) per pair)."""
    W = defaultdict(float)
    for _, w, pins in b.nets:
        parts = sorted({i for i, _ in pins})
        k = len(parts)
        for a in range(k):
            for c in range(a + 1, k):
                W[parts[a], parts[c]] += w / (k - 1)
    for i, _, j, _, w in b.springs:
        if i != j:
            W[min(i, j), max(i, j)] += 1.0
    return W


def louvain(nodes, W, seed=0):
    """Communities by modularity, one level of Louvain's local moving (enough for ~100 nodes)."""
    rng = random.Random(seed)
    adj = defaultdict(dict)
    for (i, j), w in W.items():
        adj[i][j] = adj[i].get(j, 0) + w
        adj[j][i] = adj[j].get(i, 0) + w
    deg = {i: sum(adj[i].values()) for i in nodes}
    m2 = sum(deg.values()) or 1.0
    com = {i: i for i in nodes}
    tot = dict(deg)
    moved = True
    while moved:
        moved = False
        order = list(nodes)
        rng.shuffle(order)
        for i in order:
            ci = com[i]
            links = defaultdict(float)
            for j, w in adj[i].items():
                links[com[j]] += w
            tot[ci] -= deg[i]
            best, gain = ci, links.get(ci, 0) - tot[ci] * deg[i] / m2
            for c, l in links.items():
                g = l - tot[c] * deg[i] / m2
                if g > gain + 1e-12:
                    best, gain = c, g
            tot[best] = tot.get(best, 0) + deg[i]
            if best != ci:
                com[i] = best
                moved = True
    return com


def adjusted_rand(a, b):
    """Agreement of two labellings of the same items: 1 = identical groupings, 0 = as good as chance."""
    items = list(a)
    n = len(items)
    cont = defaultdict(int)
    ra = defaultdict(int)
    rb = defaultdict(int)
    for x in items:
        cont[a[x], b[x]] += 1
        ra[a[x]] += 1
        rb[b[x]] += 1
    c2 = lambda k: k * (k - 1) / 2
    s = sum(c2(v) for v in cont.values())
    sa = sum(c2(v) for v in ra.values())
    sb = sum(c2(v) for v in rb.values())
    exp = sa * sb / c2(n)
    mx = (sa + sb) / 2
    return (s - exp) / (mx - exp) if mx != exp else 1.0


def netlist_clusters(b, seed=0):
    """Does the netlist alone know the groups? Louvain communities on the part graph (plane nets dropped), compared
    with each group level's labels: purity = share of parts whose community's majority label is their own; ARI =
    adjusted Rand index (1 = the same grouping)."""
    W = part_graph(b)
    nodes = b.movable
    W = {k: v for k, v in W.items() if k[0] in nodes and k[1] in nodes}
    com = louvain(nodes, W, seed)
    out = dict(communities=len(set(com.values())))
    for level in b.rules["group_levels"]:
        lab = {i: b.label(i, level) for i in nodes}
        groups = {}
        for i in nodes:
            groups.setdefault(com[i], []).append(lab[i])
        pure = sum(max(g.count(l) for l in set(g)) for g in groups.values())
        out[level] = dict(labels=len(set(lab.values())), ari=round(adjusted_rand(com, lab), 3),
                          purity=round(pure / len(nodes), 3))
    return out
