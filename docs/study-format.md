# Study file format (TOML)

A study runs several recipes (conditions) on several seeds in parallel and writes, to `out`:
- `results.json`: every run;
- `summary.md`: a table of each condition's best (legal first) and median run;
- `convergence`: the energy while annealing;
- `best_*`: each condition's best placement; `guess_*`: its initial guess.

Pictures are PNG when `rsvg-convert` is installed, otherwise SVG.

```toml
problem = "problem.json"        # relative to this file
out = "results"
seeds = 6
title = "my board"
reference_name = "hand layout"  # the problem's own placement, scored alongside

[defaults]                      # every condition starts from these (see pipeline.RECIPE)
start = "springs"               # "springs" | "random"
island = 10.0                   # spring stiffness inside a group (1 = flat)
accept0 = 0.2                   # uphill acceptance at the start: 0.8 hot, 0.2 warm, 0.05 cool
temps = 100                     # temperature steps
per_part = 30                   # moves per free part per step

[conditions.warm_rules]
name = "warm, bands x3 + separation"   # label in tables and plots
colour = "#2ca58d"
bands = 3.0                     # group rubber bands
separation = 1.0                # separation rules' weight

[conditions.cool]
accept0 = 0.05
window = 2.0                    # first shift reach (mm); a cool start wants a small one

[[sweeps]]                      # a grid around one condition: every combination becomes a condition
base = "warm_rules"             # named warm_rules[bands=1.0,separation=0.5], ...
bands = [1.0, 3.0, 10.0]
separation = [0.5, 1.0, 2.0]

[plot]
legend = [["supply", "supply"], ["mcu", "MCU"]]
[plot.palette]                  # colours by group label; globs allowed
supply = "#d9534f"
"ch:*" = "#c0558f"
```

All recipe keys:
- `start`, `island`, `level`;
- `bands`, `separation`;
- `accept0`, `window`;
- `temps`, `per_part`, `t_end_ratio`, `lam`;
- `net_weight_island`.

An unknown key is an error.

```
python -m pcb_placer study study.toml --seeds 6 --only warm_rules,cool --merge --jobs 8
```

`--merge` keeps the other conditions' runs from an earlier `results.json`.
