# pcb-placer

Automatic PCB part placement by energy minimisation, in pure Python.

Airwires are springs. Pulled by them, parts that share many nets come together, so a board's functional groups
(supply, MCU, interfaces, …) assemble by themselves. Simulated annealing then refines the layout against an energy
that also states the board's rules:
- which nets must stay short;
- which groups stay compact;
- which parts must keep away from which;
- where parts may not go.

A KiCad adapter turns a board into a problem file and routes candidate placements with Freerouting, so that
placements are compared by what a router makes of them, not only by airwire length.

The approach is the classic one: force-directed placement (Quinn & Breuer, 1979, written for PCBs), simulated
annealing (as in TimberWolf), and the spreading ideas of modern chip placers (ePlace, RePlAce, DREAMPlace). The
contribution here is a small, readable implementation built for PCBs. It handles parts on both faces, keep-outs
round mechanical features, rules about noisy and sensitive circuits, and studies with parameter sweeps.

## Install

No dependencies (Python ≥ 3.9; `tomli` on 3.9–3.10 for studies). The KiCad adapter runs in KiCad's own Python
(it needs `pcbnew`); the rest runs anywhere.

```
pip install -e .                 # or put src/ on PYTHONPATH (e.g. as a git submodule)
python -m unittest discover -s tests
```

## Use

```
python -m pcb_placer check examples/two_groups/problem.json     # what the rules select
python -m pcb_placer study examples/two_groups/study.toml       # conditions x seeds -> examples/two_groups/results/
python -m pcb_placer score problem.json placement.json          # score any placement
```

From a KiCad board (in KiCad's Python):

```python
import pcbnew
from pcb_placer.kicad.export import problem_from_board, hold_at_pin
from pcb_placer.problem import save

board = pcbnew.LoadBoard("my_board.kicad_pcb")
prob = problem_from_board(
    board,
    fixed={"J1", "H1", "H2"},                                   # connectors, mounting holes: never move
    groups={"U1": {"island": "mcu"}, "U2": {"island": "supply"}, ...},
    rules={"group_levels": ["island"],
           "net_weights": [{"touching": ["J1"], "factor": 4.0}],   # wires that leave the board: short
           "separation": [{"level": "island", "dirty": "supply", "fragile": ["mcu"], "range": 10.0}]})
prob["springs"] = [hold_at_pin(prob["parts"], "C1", "U1", "7")]   # C1 at U1 pin 7
save(prob, "problem.json")
```

Then route the best placement against the reference (`pcb_placer.kicad.route`: stripped copy, apply placement,
your own pre-routing aids, Freerouting, measure).

## Ontology

| Concept | What | Where |
|---|---|---|
| **Problem** | the board and its rules, a JSON file | `problem.py`, [docs/problem-format.md](docs/problem-format.md) |
| **Part** | a footprint: face, courtyard and pads at 0/90/180/270°, fixed or free, groups, copper on the other face | problem file |
| **Group** | a label at a *level* (e.g. island → islet); a fixed pad can belong to one (`pad_groups`) | problem rules |
| **Keep-out** | circles, rectangles, capsules per face; the edge margin per part; fixed parts' courtyards | `ground.py` |
| **Board** | a problem plus one placement, with the energy kept up to date move by move | `board.py` |
| **Term** | one part of the energy, with its own cache and move-by-move update | `terms.py` |
| **Stage** | a function on a board: spring guess, spreading, annealing, legalisation | `springs.py`, `anneal.py`, `legalize.py` |
| **Recipe** | one run's settings: start, temperatures, which terms are on | `pipeline.py` |
| **Study** | recipes (conditions) × seeds, with parameter sweeps, from a TOML file | `study.py`, [docs/study-format.md](docs/study-format.md) |
| **Metrics** | weighted airwire length, airwire crossings, group cohesion, separation, netlist clustering | `metrics.py` |

## The energy

All lengths in mm:

| Term | Cost | Rule it states |
|---|---|---|
| Wirelength | each net's minimum spanning tree over its pads (45° length) × the net's weight | short connections; `net_weights` rules weigh some nets more |
| Springs | weight × distance from a part's pad to the pin it serves | a decoupling cap at its pin |
| Bands | weight × half-perimeter of each group's bounding box | groups stay compact |
| Separation | weight × (range − gap) for each dirty–fragile pair closer than the range | noisy circuits away from sensitive ones |
| Penalties | λ × (courtyard overlap + courtyard area on forbidden ground) | legality; λ rises while annealing |

Plane nets (e.g. GND on an inner plane) carry no airwire. A part with copper on both faces (exposed-pad vias, through-hole pins) has its other-face copper checked against that face's fixed parts.

## The stages

1. **Spring guess:** every airwire is a spring (a net of k pads is a clique of 1/(k−1) springs), solved by
   Gauss-Seidel against the fixed parts; each part then takes the rotation its springs pull it to. With
   `island > 1`, springs inside a group are stiffer.
2. **Spreading:** the springs keep pulling while overlapping parts push apart (the lighter one moves more), the
   edge pushes back, and with separation on, dirty and fragile parts push apart.
3. **Annealing:** moves are shift, rotate and swap. The shift reach adapts to keep about 44 % of shifts accepted
   (Lam's rule). The start temperature is set by the share of uphill moves accepted: hot, warm or cool.
4. **Legalisation:** each part still illegal goes to the nearest legal spot, then a zero-temperature polish.

## What experiments have shown

On two real 4-layer boards of about 100 parts each, filling 41 % and 51 % of their legal area:
- **The groups assemble by themselves:** clustering the netlist alone recovers the designer's groups at 93–100 %
  purity (the higher figure with the external nets weighted).
- **Wire length alone dissolves groups:** shorter wiring doesn't need compact groups. Rules the netlist can't
  know, like keeping noisy circuits away from sensitive ones, have to be stated: bands and separation.
- **Warm start for rules that move whole groups:** with separation on, a warm start (20 % uphill acceptance) from
  the spring guess works best. A cool start can't move a whole group across the board, and on the fuller board it
  left parts overlapping.
- **Routed comparison:** routed with Freerouting under the same conditions as the hand layouts, the best placements
  were as complete, used the same or fewer signal vias, and needed 7–15 % less track.

## Layout

```
src/pcb_placer/      geometry, problem, ground, terms, board, springs, anneal, legalize, pipeline, study,
                     metrics, plot, __main__ (command line)
src/pcb_placer/kicad export (board -> problem), route (compare placements by routing), strip
tests/               synthetic boards only
examples/            a small synthetic board and a study
docs/                problem and study file formats
```

## License

MIT.
