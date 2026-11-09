"""Studies: several recipes (conditions) x seeds, in parallel, from a TOML file. Format: docs/study-format.md.

  python -m pcb_placer study my_study.toml [--seeds 6] [--only A,B] [--merge] [--jobs 8]

Writes to the study's `out` folder: results.json (every run), summary.md (the table), convergence and placement
pictures (PNG when rsvg-convert is installed, else SVG).
"""
from __future__ import annotations

import itertools
import json
import os
import pathlib
import shutil
import subprocess
import time
from multiprocessing import Pool

from . import metrics, plot
from .board import Board
from .pipeline import RECIPE, run
from .problem import load, net_weights

DEFAULT_COLOURS = ["#5b8def", "#e8a33d", "#2ca58d", "#d9534f", "#9b59b6", "#8e2c2a", "#1f4fa8", "#888888"]
TABLE_KEYS = ["energy", "wirelength", "crossings"]


def read_toml(path):
    try:
        import tomllib
    except ImportError:                       # Python < 3.11
        import tomli as tomllib               # type: ignore[no-redef]
    with open(path, "rb") as f:
        return tomllib.load(f)


def conditions(cfg):
    """{name: (label, colour, recipe)} from [defaults], [conditions.*] and [[sweeps]]."""
    defaults = cfg.get("defaults", {})
    out = {}
    for k, (name, c) in enumerate(cfg.get("conditions", {}).items()):
        c = dict(c)
        label = c.pop("name", name)
        colour = c.pop("colour", DEFAULT_COLOURS[k % len(DEFAULT_COLOURS)])
        rec = dict(defaults)
        rec.update(c)
        out[name] = (label, colour, rec)
    for sw in cfg.get("sweeps", []):
        sw = dict(sw)
        base = sw.pop("base")
        blabel, bcolour, brec = out[base]
        keys = sorted(sw)
        for vals in itertools.product(*(sw[k] for k in keys)):
            tag = ",".join(f"{k}={v}" for k, v in zip(keys, vals))
            rec = dict(brec)
            rec.update(zip(keys, vals))
            out[f"{base}[{tag}]"] = (f"{blabel} [{tag}]", bcolour, rec)
    for name, (_, _, rec) in out.items():
        unknown = set(rec) - set(RECIPE)
        if unknown:
            raise ValueError(f"condition {name}: unknown keys {sorted(unknown)}")
    return out


def _job(job):
    name, rec, seed, problem = job
    r = run(load(problem), rec, seed)
    r["cond"] = name
    return r


def _png(svg_path):
    """SVG -> PNG with rsvg-convert when available (the SVG is then removed)."""
    exe = shutil.which("rsvg-convert")
    if not exe:
        return svg_path
    png = svg_path.with_suffix(".png")
    if subprocess.run([exe, "-w", "1400", str(svg_path), "-o", str(png)]).returncode == 0:
        svg_path.unlink()
        return png
    return svg_path


def best_run(runs):
    """The lowest-energy run that ended legal (any run if none did)."""
    legal = [r for r in runs if not r["illegal"]]
    return min(legal or runs, key=lambda r: r["score"]["energy"])


def main(path, seeds=None, only=None, merge=False, jobs=None):
    path = pathlib.Path(path).resolve()
    cfg = read_toml(path)
    base = path.parent
    problem = str((base / cfg["problem"]).resolve())
    out = (base / cfg.get("out", "results")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    seeds = seeds or cfg.get("seeds", 4)
    conds = conditions(cfg)
    names = only or list(conds)
    jobs_ = [(n, conds[n][2], s, problem) for n in names for s in range(seeds)]
    t = time.time()
    with Pool(min(len(jobs_), jobs or max(1, (os.cpu_count() or 2) - 1))) as pool:
        res = pool.map(_job, jobs_)
    print(f"{len(jobs_)} runs in {time.time() - t:.0f} s")

    prob = load(problem)
    ref = Board(prob, net_weights(prob))
    old = out / "results.json"
    if merge and old.exists():
        prev = [r for r in json.loads(old.read_text())["runs"] if r["cond"] not in names]
        res = prev + res
        names = list(dict.fromkeys([r["cond"] for r in prev] + names))
    summary = dict(study=cfg, reference=metrics.score(ref), fill=metrics.fill(ref),
                   netlist_clusters=metrics.netlist_clusters(ref), runs=res)
    old.write_text(json.dumps(summary, indent=1))

    title = cfg.get("title", path.stem)
    ref_name = cfg.get("reference_name", "reference (the problem's own placement)")
    pcfg = cfg.get("plot", {})
    pal, legend = pcfg.get("palette"), pcfg.get("legend")
    label = lambda n: conds[n][0] if n in conds else n
    series = {label(n): (conds[n][1] if n in conds else "#888888", [r["trace"] for r in res if r["cond"] == n])
              for n in names}
    svg = out / "convergence.svg"
    svg.write_text(plot.curves_svg(series, f"{title}: energy while annealing (common energy, "
                                           f"{ref_name} = {summary['reference']['energy']:.0f})"))
    _png(svg)
    pics = [("reference", ref, ref_name)]
    for n in names:
        rs = [r for r in res if r["cond"] == n]
        best = best_run(rs)
        bb = Board(prob, net_weights(prob))
        bb.load_placement(best["placement"])
        safe = n.replace("[", "_").replace("]", "").replace(",", "_").replace("=", "")
        pics.append((f"best_{safe}", bb, f"{label(n)}: best of {len(rs)} (seed {best['seed']})"))
        if best.get("guess"):
            bg = Board(prob, net_weights(prob))
            bg.load_placement(best["guess"])
            pics.append((f"guess_{safe}", bg, f"{label(n)}: initial guess"))
    for fname, bb, ttl in pics:
        f = out / f"{fname}.svg"
        f.write_text(plot.placement_svg(bb, ttl, palette=pal, legend=legend))
        _png(f)
    table = summary_table(summary, names, label, ref_name)
    (out / "summary.md").write_text(table)
    print(table)
    return summary


def summary_table(summary, names, label, ref_name):
    """Markdown: per condition the best (legal first) and median run, legality and the separation rules."""
    ref = summary["reference"]
    keys = TABLE_KEYS + [k for k in ref if k.startswith(("cohesion_", "gap_", "intrusion_"))]
    lines = ["| Condition | Run | " + " | ".join(keys) + " | illegal runs |",
             "|---" * (len(keys) + 3) + "|",
             f"| {ref_name} | | " + " | ".join(str(ref[k]) for k in keys) + " | |"]
    for n in names:
        rs = sorted((r for r in summary["runs"] if r["cond"] == n), key=lambda r: r["score"]["energy"])
        bad = sum(1 for r in rs if r["illegal"])
        for tag, r in (("best", best_run(rs)), ("median", rs[len(rs) // 2])):
            lines.append(f"| {label(n)} | {tag} (seed {r['seed']}) | "
                         + " | ".join(str(r["score"].get(k, "")) for k in keys)
                         + f" | {bad} / {len(rs)} |")
    return "\n".join(lines) + "\n"
