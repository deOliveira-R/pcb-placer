"""pcb-placer: automatic PCB part placement by energy minimisation.

Airwires are springs; parts self-assemble into their groups, then simulated annealing refines the layout against
an energy that states the board's rules (net weights, groups held together, dirty and fragile parts kept apart,
keep-outs). Pure Python, no dependencies; the KiCad adapter (pcb_placer.kicad) runs in KiCad's own Python.
"""
__version__ = "0.1.0"
