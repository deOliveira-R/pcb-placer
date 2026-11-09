"""Command line:

  python -m pcb_placer study STUDY.toml [--seeds N] [--only A,B] [--merge] [--jobs N]
  python -m pcb_placer score PROBLEM.json [PLACEMENT.json]
  python -m pcb_placer check PROBLEM.json
"""
from __future__ import annotations

import argparse
import json


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pcb_placer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("study", help="run a study (conditions x seeds) from a TOML file")
    s.add_argument("toml")
    s.add_argument("--seeds", type=int)
    s.add_argument("--only", help="comma-separated condition names")
    s.add_argument("--merge", action="store_true", help="keep the other conditions' runs in results.json")
    s.add_argument("--jobs", type=int)
    c = sub.add_parser("score", help="score the problem's own placement, or a placement file {ref: [x, y, rot]}")
    c.add_argument("problem")
    c.add_argument("placement", nargs="?")
    k = sub.add_parser("check", help="validate a problem file and report what the rules select")
    k.add_argument("problem")
    a = ap.parse_args(argv)
    if a.cmd == "study":
        from .study import main as study
        study(a.toml, seeds=a.seeds, only=a.only.split(",") if a.only else None, merge=a.merge, jobs=a.jobs)
    elif a.cmd == "score":
        from . import metrics
        from .board import Board
        from .problem import load, net_weights
        prob = load(a.problem)
        b = Board(prob, net_weights(prob))
        if a.placement:
            with open(a.placement) as f:
                b.load_placement(json.load(f))
        print(json.dumps(metrics.score(b), indent=1))
        print("illegal:", [b.refs[i] for i in b.movable if b.violation(i) > 1e-9])
    elif a.cmd == "check":
        from . import metrics
        from .board import Board
        from .problem import load, net_weights
        prob = load(a.problem)
        b = Board(prob, net_weights(prob))
        b.set_separation(1.0)
        print(f"{len(b.P)} parts ({len(b.movable)} free), {len(b.nets)} nets with airwires, {len(b.springs)} springs")
        for level in prob["rules"]["group_levels"]:
            labs = sorted({b.label(i, level) for i in b.movable})
            print(f"groups at {level!r}: {len(labs)}: {labs}")
        print("separation pairs:", len(b.sep.pairs), " fill:", metrics.fill(b))
        print("illegal in the problem's own placement:", [b.refs[i] for i in b.movable if b.violation(i) > 1e-9])


if __name__ == "__main__":
    main()
