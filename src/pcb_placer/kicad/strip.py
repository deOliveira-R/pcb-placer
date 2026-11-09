"""Remove one kind of item from a board, in its own process (pcbnew's Remove() leaves its Python unusable for later
removals; two kinds in one process can crash it):

  python -m pcb_placer.kicad.strip SRC DST tracks|zones|silk
"""
from __future__ import annotations

import sys

import pcbnew


def strip(src, dst, what):
    """tracks: every track and via; zones: every copper zone except plane layers' (kept: rule areas and the planes
    given by inner layers of type 'power'); silk: silkscreen drawings."""
    b = pcbnew.LoadBoard(str(src))
    if what == "tracks":
        for t in list(b.GetTracks()):
            b.Remove(t)
    elif what == "zones":
        for z in list(b.Zones()):
            if z.GetIsRuleArea():
                continue
            lay = z.GetLayer()
            if pcbnew.IsInnerCopperLayer(lay) and b.GetLayerType(lay) == pcbnew.LT_POWER:
                continue
            b.Remove(z)
    elif what == "silk":
        for d in list(b.GetDrawings()):
            if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                b.Remove(d)
    else:
        raise SystemExit(f"unknown kind {what!r}")
    pcbnew.SaveBoard(str(dst), b)


if __name__ == "__main__":
    strip(*sys.argv[1:4])
