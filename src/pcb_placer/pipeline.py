"""One placement run: start -> anneal -> legalise, set by a recipe (a dict; in a study, a condition).

Recipe keys (defaults in RECIPE):
  start       "springs" (the spring guess, then spreading) or "random" (the no-guess baseline)
  island      spring stiffness inside a group (1 = flat springs; the groups self-assemble or not)
  level       the group level for island springs and bands (default: the problem's first level)
  bands       weight of the group rubber bands in the annealing energy (0 = off)
  separation  weight of the separation rules (0 = off); also pushes dirty and fragile apart while spreading
  accept0     share of uphill moves accepted at the start: 0.8 hot (forgets the start), 0.2 warm, 0.05 cool
  window      the first shift reach in mm (default a quarter of the board; a cool start wants ~2)
  temps, per_part, t_end_ratio, lam   the annealing schedule (see anneal.anneal)
  net_weight_island   the energy's airwire weight for nets inside one group (1 = off)
"""
from __future__ import annotations

import time

from . import metrics
from .anneal import anneal, random_start
from .board import Board
from .legalize import legalize
from .problem import net_weights
from .springs import solve_springs, spread, spring_list

RECIPE: dict = dict(start="springs", island=1.0, level=None, bands=0.0, separation=0.0, accept0=0.2, window=None,
              temps=100, per_part=30, t_end_ratio=1e-3, lam=(1.0, 200.0), net_weight_island=1.0)


def recipe(**kw):
    unknown = set(kw) - set(RECIPE)
    if unknown:
        raise ValueError(f"unknown recipe keys: {sorted(unknown)}")
    r = dict(RECIPE)
    r.update(kw)
    return r


def run(prob, rec, seed=0):
    """Place once. Returns a dict: score, illegal parts, the energy trace, scores after each stage, the initial guess
    and the final placement."""
    rec = recipe(**rec)
    t = time.time()
    weights = net_weights(prob)
    b = Board(prob, net_weights(prob, island=rec["net_weight_island"], level=rec["level"])
              if rec["net_weight_island"] != 1.0 else weights, eval_weights=weights)
    b.set_separation(rec["separation"])         # before spreading: the spread pushes dirty and fragile apart too
    stages = {}
    guess = None
    if rec["start"] == "random":
        random_start(b, seed)
    elif rec["start"] == "springs":
        sp = spring_list(b, island=rec["island"], level=rec["level"])
        solve_springs(b, sp)
        stages["springs"] = metrics.score(b)
        spread(b, sp, seed=seed)
        stages["spread"] = metrics.score(b)
        guess = b.placement()
    else:
        raise ValueError(f"start: {rec['start']!r}")
    if rec["bands"]:
        b.set_bands(rec["bands"], rec["level"])
        b.refresh()
    trace = []
    anneal(b, seed=seed, accept0=rec["accept0"], temps=rec["temps"], per_part=rec["per_part"], trace=trace,
           window0=rec["window"], t_end_ratio=rec["t_end_ratio"], lam=tuple(rec["lam"]))
    illegal = legalize(b)
    return dict(seed=seed, seconds=round(time.time() - t, 1), score=metrics.score(b), illegal=illegal, trace=trace,
                stages=stages, guess=guess, placement=b.placement())
