"""The placement problem: a JSON file (format: docs/problem-format.md), loaded as a plain dict and checked.

A problem holds the board (outline, keep-outs), the parts (geometry at the four rotations, pads, nets, a starting
position), and the rules the energy reads (net weights, groups, separations). Everything project-specific lives in
the file, so the engine knows no part names.
"""
from __future__ import annotations

import json

SCHEMA = "pcb-placer/1"
FACES = ("F", "B")

PART_KEYS = ("side", "x", "y", "rot", "fixed", "both_faces", "edge_margin", "groups", "pad_numbers", "pad_nets", "geom")
DEFAULT_RULES = dict(spring_weight=2.0, net_weights=[], pad_groups=[], separation=[], group_levels=[])


class ProblemError(ValueError):
    pass


def load(path):
    with open(path) as f:
        prob = json.load(f)
    validate(prob)
    return prob


def save(prob, path):
    validate(prob)
    with open(path, "w") as f:
        json.dump(prob, f, indent=1)


def validate(prob):
    """Check the structure and fill the defaults (rules, empty obstacle lists). Raises ProblemError."""
    if prob.get("schema") != SCHEMA:
        raise ProblemError(f"schema is {prob.get('schema')!r}, expected {SCHEMA!r}")
    for k in ("grid", "gap", "outline", "parts", "nets"):
        if k not in prob:
            raise ProblemError(f"missing {k!r}")
    if len(prob["outline"]) < 3:
        raise ProblemError("the outline needs at least 3 points")
    obs = prob.setdefault("obstacles", {})
    for face in FACES:
        o = obs.setdefault(face, {})
        for k in ("circles", "rects", "capsules"):
            o.setdefault(k, [])
    prob.setdefault("plane_nets", [])
    prob.setdefault("springs", [])
    rules = prob.setdefault("rules", {})
    for k, v in DEFAULT_RULES.items():
        rules.setdefault(k, v)
    for ref, p in prob["parts"].items():
        missing = [k for k in PART_KEYS if k not in p]
        if missing:
            raise ProblemError(f"part {ref}: missing {missing}")
        if p["side"] not in FACES:
            raise ProblemError(f"part {ref}: side {p['side']!r}")
        if sorted(p["geom"]) != ["0", "180", "270", "90"]:
            raise ProblemError(f"part {ref}: geom needs rotations 0, 90, 180, 270")
        for rot, g in p["geom"].items():
            if len(g["pads"]) != len(p["pad_nets"]):
                raise ProblemError(f"part {ref} rot {rot}: {len(g['pads'])} pads, {len(p['pad_nets'])} pad nets")
    for name, pins in prob["nets"].items():
        for ref, q in pins:
            if ref not in prob["parts"] or not 0 <= q < len(prob["parts"][ref]["pad_nets"]):
                raise ProblemError(f"net {name}: no pad {ref}[{q}]")
    for a, qa, b, qb in prob["springs"]:
        if a not in prob["parts"] or b not in prob["parts"]:
            raise ProblemError(f"spring {a}-{b}: unknown part")
    for ref, q, _ in rules["pad_groups"]:
        if ref not in prob["parts"]:
            raise ProblemError(f"pad group: unknown part {ref}")
    for s in rules["separation"]:
        for k in ("level", "dirty", "fragile", "range"):
            if k not in s:
                raise ProblemError(f"separation rule {s}: missing {k!r}")
    return prob


def label(prob, ref, level):
    """A part's group label at a level ('' = none)."""
    return prob["parts"][ref]["groups"].get(level, "")


def pad_labels(prob):
    """{(ref, pad index): label} for fixed pads that belong to a group (e.g. a connector pin and the circuit that
    serves it): bands include the pad, and island springs and weights treat it as a member."""
    return {(ref, q): lab for ref, q, lab in prob["rules"]["pad_groups"]}


def net_weights(prob, island=1.0, level=None):
    """Airwire weight per net, from the rules: each `net_weights` rule multiplies the weight of the nets that touch
    any of its parts (e.g. nets that leave the board, kept short until their protection). island > 1: a net whose
    labelled pins all share one label at `level` weighs that much more (unlabelled pins don't count)."""
    rules = prob["rules"]
    level = level or (rules["group_levels"] or [""])[0]
    plabel = pad_labels(prob)
    out = {}
    plane = set(prob["plane_nets"])
    for name, pins in prob["nets"].items():
        if name in plane:
            continue
        w = 1.0
        refs = {r for r, _ in pins}
        for rule in rules["net_weights"]:
            if refs & set(rule["touching"]):
                w *= rule["factor"]
        if island != 1.0:
            labs = {plabel.get((r, q)) or label(prob, r, level) for r, q in pins} - {""}
            if len(labs) == 1:
                w *= island
        out[name] = w
    return out
