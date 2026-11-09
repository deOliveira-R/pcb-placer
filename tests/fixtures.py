"""Synthetic problems for the tests (no real board)."""
from __future__ import annotations

import copy

from pcb_placer.problem import SCHEMA, validate


def rect_part(w, h, x=0.0, y=0.0, side="F", fixed=False, nets=(None, None), groups=None, both_faces=False,
              other_copper=None, margin=1.0):
    """A w x h part with a pad at each end of its long axis; other_copper: a box (at rotation 0) of copper it puts
    on the other face."""
    geom = {}
    for rot in (0, 90, 180, 270):
        ww, hh = (w, h) if rot in (0, 180) else (h, w)
        if rot in (0, 180):
            pads = [[-w / 2 * 0.8, 0.0], [w / 2 * 0.8, 0.0]]
        else:
            pads = [[0.0, -w / 2 * 0.8], [0.0, w / 2 * 0.8]]
        if rot in (180, 270):
            pads = pads[::-1]
        g = dict(box=[-ww / 2, -hh / 2, ww / 2, hh / 2], pads=pads)
        if other_copper:
            a, b, c, d = other_copper
            g["copper_other_face"] = [a, b, c, d] if rot in (0, 180) else [b, a, d, c]
        geom[str(rot)] = g
    return dict(side=side, x=x, y=y, rot=0, fixed=fixed, both_faces=both_faces, edge_margin=margin,
                groups=dict(groups or {}), pad_numbers=["1", "2"], pad_nets=list(nets), geom=geom)


def square_problem():
    """A 20 x 20 mm board, two free 2 x 1 mm parts joined by one net to a fixed anchor's pad."""
    parts = {"A": rect_part(2, 1, 5, 5, nets=("N", None)), "B": rect_part(2, 1, 15, 15, nets=("N", None)),
             "K": rect_part(2, 1, 10, 2, fixed=True, nets=("N", None))}
    prob = dict(schema=SCHEMA, name="square", gap=0.0, grid=0.25, outline=[[0, 0], [20, 0], [20, 20], [0, 20]],
                parts=parts, nets={"N": [["A", 0], ["B", 0], ["K", 0]]})
    return validate(prob)


def two_group_problem():
    """A 40 x 30 mm board with what the rules need:
    - a fixed 2-pin connector J (pads in groups 'power' and 'signal' via pad_groups) whose nets weigh x4;
    - a 'power' group (P1..P3, one of them 'surge' at the islet level) and a 'signal' group (S1..S3);
    - a separation rule: surge parts 10 mm from signal parts;
    - a capsule keep-out and a circle on the lower face;
    - a two-faced part T (copper on the upper face) and a fixed upper-face part L;
    - a spring: P3 held at P1's pad."""
    g = lambda isl, islet=None: {"island": isl, "islet": islet or isl}
    parts = {
        "J": rect_part(4, 2, 20, 27, fixed=True, nets=("PWR", "SIG")),
        "P1": rect_part(2, 1.2, 6, 6, nets=("PWR", "V1"), groups=g("power", "surge")),
        "P2": rect_part(2, 1.2, 8, 8, nets=("V1", "V2"), groups=g("power", "surge")),
        "P3": rect_part(1.6, 0.8, 10, 6, nets=("V2", "PWR"), groups=g("power", "reg")),
        "S1": rect_part(2, 1.2, 30, 6, nets=("SIG", "D1"), groups=g("signal")),
        "S2": rect_part(2, 1.2, 32, 8, nets=("D1", "D2"), groups=g("signal")),
        "S3": rect_part(1.6, 0.8, 34, 6, nets=("D2", "V2"), groups=g("signal")),
        "T": rect_part(4, 4, 20, 12, nets=("V2", "D2"), groups=g("signal", "driver"), both_faces=True,
                       other_copper=(-1, -1, 1, 1)),
        "L": rect_part(2, 2, 20, 20, side="B", fixed=True, nets=("D1", None), groups=g("status")),
    }
    prob = dict(
        schema=SCHEMA, name="two groups", gap=0.4, grid=0.25,
        outline=[[0, 0], [40, 0], [40, 30], [0, 30]],
        obstacles={"F": {"circles": [[3, 26, 1.5]], "capsules": [[3, 26, 3, 30, 1.5]], "rects": []},
                   "B": {"circles": [], "capsules": [], "rects": []}},
        parts=parts,
        nets={"PWR": [["J", 0], ["P1", 0], ["P3", 1]], "SIG": [["J", 1], ["S1", 0]], "V1": [["P1", 1], ["P2", 0]],
              "V2": [["P2", 1], ["P3", 0], ["S3", 1], ["T", 0]], "D1": [["S1", 1], ["S2", 0], ["L", 0]],
              "D2": [["S2", 1], ["S3", 0], ["T", 1]], "GND": [["P1", 1]]},
        plane_nets=["GND"],
        springs=[["P3", 1, "P1", 0]],
        rules=dict(spring_weight=2.0, group_levels=["island", "islet"],
                   net_weights=[dict(touching=["J"], factor=4.0)],
                   pad_groups=[["J", 0, "power"], ["J", 1, "signal"]],
                   separation=[dict(level="islet", dirty="surge", fragile=["signal"], fragile_level="island",
                                    range=10.0)]))
    return validate(prob)


def copy_problem(p):
    return copy.deepcopy(p)
