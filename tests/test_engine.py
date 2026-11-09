"""python -m unittest discover -s tests (from the repository root)."""
from __future__ import annotations

import json
import math
import pathlib
import random
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import copy_problem, square_problem, two_group_problem  # noqa: E402
from pcb_placer import metrics, problem  # noqa: E402
from pcb_placer.anneal import anneal  # noqa: E402
from pcb_placer.board import Board  # noqa: E402
from pcb_placer.geometry import ROTS, box_gap, hole_corridors, mst_length, octile  # noqa: E402
from pcb_placer.legalize import legalize  # noqa: E402
from pcb_placer.pipeline import run  # noqa: E402
from pcb_placer.springs import spring_list  # noqa: E402


class Geometry(unittest.TestCase):
    def test_octile_and_mst(self):
        self.assertAlmostEqual(octile(3, 4), 4 + 0.41421356 * 3)
        self.assertAlmostEqual(mst_length([(0, 0), (10, 0), (10, 5)]), 15.0)

    def test_box_gap(self):
        self.assertEqual(box_gap((0, 0, 1, 1), (0.5, 0.5, 2, 2)), 0.0)
        self.assertAlmostEqual(box_gap((0, 0, 1, 1), (4, 5, 6, 6)), 5.0)

    def test_hole_corridors(self):
        caps = hole_corridors([(5, 5), (12, 5), (40, 40)], [[0, 0], [50, 0], [50, 50], [0, 50]], 2.0, 10.0, 6.0)
        # the neighbours 7 mm apart are joined; each hole within 6 mm of an edge gets a band to it
        self.assertIn([5, 5, 12, 5, 2.0], caps)
        self.assertEqual(sum(1 for c in caps if c[:2] == [5, 5] and c[2:4] != [12, 5]), 1)
        self.assertFalse(any(c[:2] == [40, 40] for c in caps))


class Problem(unittest.TestCase):
    def test_validation(self):
        p = two_group_problem()
        bad = copy_problem(p)
        bad["nets"]["X"] = [["NOPE", 0]]
        with self.assertRaises(problem.ProblemError):
            problem.validate(bad)
        bad = copy_problem(p)
        bad["schema"] = "other"
        with self.assertRaises(problem.ProblemError):
            problem.validate(bad)

    def test_net_weights(self):
        w = problem.net_weights(two_group_problem())
        self.assertEqual(w["PWR"], 4.0)          # touches the connector
        self.assertEqual(w["V1"], 1.0)
        self.assertNotIn("GND", w)               # a plane
        wi = problem.net_weights(two_group_problem(), island=5.0)
        self.assertEqual(wi["V1"], 5.0)          # P1, P2: both 'power'
        self.assertEqual(wi["PWR"], 20.0)        # J's pad 0 counts as 'power' (pad_groups)
        self.assertEqual(wi["V2"], 1.0)          # power and signal


class Ground(unittest.TestCase):
    def test_keepouts(self):
        b = Board(two_group_problem())
        i = b.idx["P1"]
        self.assertEqual(b.ground_cost(i), 0.0)
        self.assertGreater(b.ground_cost(i, 0.0, 15.0, 0), 0.0)        # within the edge margin
        self.assertGreater(b.ground_cost(i, 3.0, 28.5, 0), 0.0)        # on the capsule
        self.assertGreater(b.ground_cost(i, 20.0, 27.0, 0), 0.0)       # on the connector

    def test_other_face_copper(self):
        """T's upper-face copper may not sit on the upper-face part L; its body may pass under L."""
        b = Board(two_group_problem())
        i, L = b.idx["T"], b.idx["L"]
        cx, cy = b.centre(L)
        self.assertGreater(b.ground_cost(i, cx, cy, 0), 0.0)
        self.assertEqual(b.ground_cost(i, cx + 2.6, cy, 0), 0.0)       # body overlaps L, copper clear of it


class Energy(unittest.TestCase):
    def check_moves(self, b, n=300, seed=1):
        rng = random.Random(seed)
        for _ in range(n):
            i, j = rng.sample(b.movable, 2)
            kind = rng.random()
            if kind < 0.4:
                r = 3 if kind < 0.2 else 20
                mv = {i: (b.x[i] + rng.uniform(-r, r), b.y[i] + rng.uniform(-r, r), b.rot[i])}
            elif kind < 0.7:
                mv = {i: (b.x[i], b.y[i], rng.choice(ROTS))}
            else:
                mv = {i: (b.x[j], b.y[j], b.rot[i]), j: (b.x[i], b.y[i], b.rot[j])}
            e0 = b.energy()
            dE, cache = b.delta(mv)
            b.commit(cache)
            cached = [t.total(b) for t in b.terms] + [sum(b.out)]
            b.refresh()
            fresh = [t.total(b) for t in b.terms] + [sum(b.out)]
            for c, f in zip(cached, fresh):
                self.assertAlmostEqual(c, f, places=6)
            self.assertAlmostEqual(b.energy() - e0, dE, places=6)

    def test_delta_wirelength_and_springs(self):
        self.check_moves(Board(two_group_problem()))

    def test_delta_bands(self):
        b = Board(two_group_problem())
        b.set_bands(2.0)
        self.check_moves(b)

    def test_delta_separation(self):
        b = Board(two_group_problem())
        b.set_separation(3.0)
        self.assertTrue(b.sep.pairs)
        self.check_moves(b)
        self.assertGreater(b.separation_intrusion() + 1, 0)

    def test_delta_everything(self):
        p = two_group_problem()
        b = Board(p, problem.net_weights(p, island=3.0), problem.net_weights(p))
        b.set_bands(1.5, "islet")
        b.set_separation(2.0)
        self.check_moves(b, n=400, seed=7)

    def test_bands_include_fixed_pads(self):
        b = Board(two_group_problem())
        b.set_bands(1.0)
        groups = {lab: fixed for lab, _, fixed in b.bands.groups}
        self.assertEqual(len(groups["power"]), 1)       # the connector's pad 0


class Stages(unittest.TestCase):
    def test_anneal_pulls_parts_together(self):
        b = Board(square_problem())
        e0 = b.energy()
        anneal(b, seed=0, temps=30, per_part=50)
        self.assertEqual(legalize(b), [])
        self.assertLess(b.energy(), e0)
        self.assertLess(b.wirelength(), 6.0)

    def test_island_springs(self):
        b = Board(two_group_problem())
        flat = {(i, qi, j, qj): k for i, qi, j, qj, k in spring_list(b)}
        stiff = {(i, qi, j, qj): k for i, qi, j, qj, k in spring_list(b, island=10.0)}
        J, P1, S1 = b.idx["J"], b.idx["P1"], b.idx["S1"]
        key = next(k for k in flat if {k[0], k[2]} == {J, P1})
        self.assertAlmostEqual(stiff[key], 10 * flat[key])          # J's pad 0 is 'power' like P1
        key = next(k for k in flat if {k[0], k[2]} == {J, S1})
        self.assertAlmostEqual(stiff[key], 10 * flat[key])          # J's pad 1 is 'signal' like S1

    def test_pipeline_keeps_the_rules(self):
        p = two_group_problem()
        rec = dict(start="springs", island=10.0, bands=2.0, temps=40, per_part=20)
        off = [run(p, dict(rec, separation=0.0), seed=s)["score"]["intrusion_surge"] for s in range(3)]
        on = [run(p, dict(rec, separation=3.0), seed=s) for s in range(3)]
        self.assertTrue(all(r["illegal"] == [] for r in on))
        # both groups hang off neighbouring connector pins, so 10 mm can't always be met: the rule must still help
        self.assertLess(sum(r["score"]["intrusion_surge"] for r in on), sum(off))
        again = run(p, dict(rec, separation=3.0), seed=0)
        self.assertEqual(on[0]["placement"], again["placement"])     # same seed, same placement

    def test_random_start(self):
        r = run(two_group_problem(), dict(start="random", accept0=0.8, temps=40, per_part=20), seed=3)
        self.assertEqual(r["illegal"], [])
        self.assertIsNone(r["guess"])


class Metrics(unittest.TestCase):
    def test_crossings(self):
        p = square_problem()
        p["nets"] = {"N": [["A", 0], ["B", 0]], "M": [["A", 1], ["B", 1]]}
        b = Board(problem.validate(p))
        b.load_placement({"A": [0, 0, 0], "B": [10, 10, 0], "K": [10, 2, 0]})
        n0 = metrics.crossings(b)
        b.load_placement({"A": [0, 0, 0], "B": [10, 10, 180], "K": [10, 2, 0]})
        self.assertNotEqual(n0, metrics.crossings(b))

    def test_adjusted_rand(self):
        a = {1: "x", 2: "x", 3: "y", 4: "y"}
        self.assertAlmostEqual(metrics.adjusted_rand(a, {1: 0, 2: 0, 3: 1, 4: 1}), 1.0)

    def test_louvain_two_cliques(self):
        W = {}
        for grp in ((0, 1, 2, 3), (4, 5, 6, 7)):
            for a in grp:
                for c in grp:
                    if a < c:
                        W[a, c] = 1.0
        W[3, 4] = 0.1
        com = metrics.louvain(list(range(8)), W)
        self.assertEqual(len({com[i] for i in range(4)}), 1)
        self.assertNotEqual(com[0], com[7])

    def test_score_has_the_rules(self):
        s = metrics.score(Board(two_group_problem()))
        for k in ("energy", "crossings", "cohesion_island", "cohesion_islet", "gap_surge", "intrusion_surge"):
            self.assertIn(k, s)


class Study(unittest.TestCase):
    def test_study_from_toml(self):
        from pcb_placer import study
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "p.json").write_text(json.dumps(two_group_problem()))
            (d / "s.toml").write_text('''problem = "p.json"
out = "res"
seeds = 2
[defaults]
temps = 20
per_part = 10
island = 10.0
[conditions.warm]
bands = 2.0
separation = 2.0
[[sweeps]]
base = "warm"
bands = [0.0, 4.0]
''')
            conds = study.conditions(study.read_toml(d / "s.toml"))
            self.assertEqual(sorted(conds), ["warm", "warm[bands=0.0]", "warm[bands=4.0]"])
            summary = study.main(d / "s.toml", jobs=2)
            self.assertEqual(len(summary["runs"]), 6)
            self.assertTrue((d / "res" / "results.json").exists())
            self.assertTrue((d / "res" / "summary.md").exists())

    def test_unknown_recipe_key(self):
        from pcb_placer import study
        with self.assertRaises(ValueError):
            study.conditions({"conditions": {"x": {"tempz": 3}}})


if __name__ == "__main__":
    unittest.main()
