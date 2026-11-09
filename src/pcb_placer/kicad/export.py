"""KiCad board -> placement problem (run with KiCad's Python: it needs pcbnew).

The generic part: every footprint's courtyard box and pad offsets at 0/90/180/270 degrees, its pads' nets, which
faces it occupies and the copper it puts on the other face, the board outline. The project supplies the rest:
which parts are fixed, their group labels, edge margins, keep-outs, springs and rules.

    import pcbnew
    from pcb_placer.kicad.export import problem_from_board
    board = pcbnew.LoadBoard("my.kicad_pcb")
    prob = problem_from_board(board, fixed={"J1", "H1"}, groups={"U1": {"island": "mcu"}, ...},
                              rules={"net_weights": [{"touching": ["J1"], "factor": 4.0}]})
    pcb_placer.problem.save(prob, "problem.json")
"""
from __future__ import annotations

import pcbnew

from ..problem import SCHEMA, validate

ROTS = (0, 90, 180, 270)


def mm(v):
    return round(pcbnew.ToMM(v), 4)


def courtyard_box(fp):
    """The courtyard's bounding box relative to the footprint position (mm), on the footprint's own face (the whole
    footprint without text if it has no courtyard)."""
    fp.BuildCourtyardCaches()
    layer = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
    c = fp.GetCourtyard(layer)
    bb = c.BBox() if c.OutlineCount() else fp.GetBoundingBox(False)
    pos = fp.GetPosition()
    return (pcbnew.ToMM(bb.GetLeft() - pos.x), pcbnew.ToMM(bb.GetTop() - pos.y),
            pcbnew.ToMM(bb.GetRight() - pos.x), pcbnew.ToMM(bb.GetBottom() - pos.y))


def pad_xy(pad):
    p = pad.GetPosition()
    return pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)


def connected(net):
    return bool(net) and not net.startswith("unconnected")


def part_entry(fp, fixed=False, groups=None, edge_margin=1.0, both_faces=None, other_face_copper=True) -> dict:
    """One part's problem entry. both_faces: None = decide from the pads (a lower-face part with copper on the upper
    face, e.g. through-hole pins or exposed-pad vias); other_face_copper: record the box of that copper (free parts
    only), so on the other face only the copper counts, not the whole body."""
    pos, rot0 = fp.GetPosition(), fp.GetOrientationDegrees()
    pads = list(fp.Pads())
    side = "B" if fp.IsFlipped() else "F"
    other = pcbnew.F_Cu if side == "B" else pcbnew.B_Cu
    if both_faces is None:
        both_faces = side == "F" and any(q.IsOnLayer(pcbnew.B_Cu) for q in pads)
    geom = {}
    for rot in ROTS:
        fp.SetOrientationDegrees(rot)
        box = courtyard_box(fp)
        g = dict(box=[round(v, 4) for v in box],
                 pads=[[mm(q.GetPosition().x - pos.x), mm(q.GetPosition().y - pos.y)] for q in pads])
        back = [q.GetBoundingBox() for q in pads if q.IsOnLayer(other)]
        if back and both_faces and other_face_copper and not fixed:
            g["copper_other_face"] = [round(v, 4) for v in (
                mm(min(bb.GetLeft() for bb in back) - pos.x), mm(min(bb.GetTop() for bb in back) - pos.y),
                mm(max(bb.GetRight() for bb in back) - pos.x), mm(max(bb.GetBottom() for bb in back) - pos.y))]
        geom[str(rot)] = g
    fp.SetOrientationDegrees(rot0)
    pad_nets = [q.GetNetname() if connected(q.GetNetname()) else None for q in pads]
    return dict(side=side, x=mm(pos.x), y=mm(pos.y), rot=int(round(rot0)) % 360, fixed=bool(fixed),
                both_faces=bool(both_faces), edge_margin=edge_margin, groups=dict(groups or {}),
                pad_numbers=[q.GetNumber() for q in pads], pad_nets=pad_nets, geom=geom)


def board_outline(board, step=0.5):
    """The Edge.Cuts outline as a point list (arcs flattened at about `step` mm)."""
    polys = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(polys)
    if polys.OutlineCount() == 0:
        raise ValueError("no closed board outline on Edge.Cuts")
    ol = polys.Outline(0)
    pts = [(pcbnew.ToMM(ol.CPoint(k).x), pcbnew.ToMM(ol.CPoint(k).y)) for k in range(ol.PointCount())]
    out = []
    for k in range(len(pts)):
        (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % len(pts)]
        n = max(1, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / step))
        out += [[round(x0 + (x1 - x0) * i / n, 4), round(y0 + (y1 - y0) * i / n, 4)] for i in range(n)]
    return out


def hold_at_pin(parts, held, part, pin=None, plane_nets=("GND",)):
    """A spring [held, pad, part, pad]: `held`'s signal pad (its first pad not on a plane net) to `part`'s pin
    `pin` (a pad number), or with pin None to `part`'s pad on the same net (e.g. a decoupling cap at the pin it
    serves). None if the parts or pads aren't there."""
    if held not in parts or part not in parts:
        return None
    c, p = parts[held], parts[part]
    ci = next((i for i, n in enumerate(c["pad_nets"]) if n and n not in plane_nets), None)
    if pin:
        pi = p["pad_numbers"].index(pin) if pin in p["pad_numbers"] else None
    else:
        shared = set(c["pad_nets"]) - set(plane_nets) - {None}
        pi = next((i for i, n in enumerate(p["pad_nets"]) if n and n in shared), None)
    if ci is None or pi is None:
        return None
    return [held, ci, part, pi]


def problem_from_board(board, fixed=(), groups=None, edge_margin=1.0, both_faces=None, outline=None,
                       obstacles=None, springs=(), rules=None, plane_nets=("GND",), grid=0.25, gap=0.6, name=""):
    """The problem for a placed board (its positions become the reference placement).

    fixed: refs that never move. groups: {ref: {level: label}}. edge_margin: mm, or a function (ref, footprint) ->
    mm. both_faces: {ref: bool} overrides. outline: a point list (default: Edge.Cuts). obstacles: {"F"/"B":
    {"circles", "rects", "capsules"}}. springs: [[held, pad, part, pad]] (see hold_at_pin). rules: the problem's
    rules (net_weights, pad_groups, separation, group_levels, spring_weight)."""
    groups = groups or {}
    both_faces = both_faces or {}
    fixed = set(fixed)
    parts, nets = {}, {}
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    for ref, f in sorted(fps.items()):
        m = edge_margin(ref, f) if callable(edge_margin) else edge_margin
        e = part_entry(f, fixed=ref in fixed, groups=groups.get(ref), edge_margin=m, both_faces=both_faces.get(ref))
        for i, n in enumerate(e["pad_nets"]):
            if n:
                nets.setdefault(n, []).append([ref, i])
        parts[ref] = e
    prob = dict(schema=SCHEMA, name=name, grid=grid, gap=gap, outline=outline or board_outline(board),
                obstacles=obstacles or {}, parts=parts, nets=nets, plane_nets=list(plane_nets),
                springs=[list(s) for s in springs if s], rules=dict(rules or {}))
    return validate(prob)
