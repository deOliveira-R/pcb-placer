"""SVG pictures: a placement (outline, keep-outs, parts coloured by group, airwires) and convergence curves."""
from __future__ import annotations

import colorsys
import fnmatch
import hashlib

from .metrics import airwires


def label_colour(lab, palette=None):
    """A group's colour: the palette's entry (exact, or the first matching glob such as 'ch:*'), else one derived
    from the label so it stays the same between pictures."""
    palette = palette or {}
    if lab in palette:
        return palette[lab]
    for pat, col in palette.items():
        if any(c in pat for c in "*?[") and fnmatch.fnmatchcase(lab, pat):
            return col
    if not lab:
        return "#999999"
    h = int(hashlib.md5(lab.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hls_to_rgb(h, 0.55, 0.5)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def placement_svg(b, title="", scale=8.0, wires=True, side="F", level=None, palette=None, legend=None):
    """One face of the board (the problem's coordinates, y down). level: the group level that colours the parts
    (default the first); legend: [(label, name), ...] shown at the top right."""
    levels = b.rules["group_levels"]
    level = level or (levels[0] if levels else "")
    xs = [p[0] for p in b.prob["outline"]]
    ys = [p[1] for p in b.prob["outline"]]
    x0, y0, x1, y1 = min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3
    top = 64 if legend else 40                    # title row, then the legend's row
    W, H = (x1 - x0) * scale, (y1 - y0) * scale + top
    X = lambda x: (x - x0) * scale
    Y = lambda y: (y - y0) * scale + top
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" font-family="Helvetica">',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<text x="10" y="26" font-size="{min(20, max(9, 1.8 * W / max(len(title), 1))):.0f}">{title}</text>']
    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in b.prob["outline"])
    out.append(f'<polygon points="{pts}" fill="#f4f1e8" stroke="#333" stroke-width="1.5"/>')
    obs = b.prob["obstacles"][side]
    for cx, cy, r in obs["circles"]:
        out.append(f'<circle cx="{X(cx):.1f}" cy="{Y(cy):.1f}" r="{r * scale:.1f}" fill="#e3ddd0" stroke="#bbb"/>')
    for ax, ay, bx, by, r in obs["capsules"]:
        out.append(f'<line x1="{X(ax):.1f}" y1="{Y(ay):.1f}" x2="{X(bx):.1f}" y2="{Y(by):.1f}" stroke="#e3ddd0" '
                   f'stroke-width="{2 * r * scale:.1f}" stroke-linecap="round" stroke-opacity="0.9"/>')
    for a, c, d, e in obs["rects"]:
        out.append(f'<rect x="{X(a):.1f}" y="{Y(c):.1f}" width="{(d - a) * scale:.1f}" height="{(e - c) * scale:.1f}" '
                   f'fill="#e3ddd0" stroke="#bbb" stroke-dasharray="4,3"/>')
    for i in range(len(b.P)):
        if side not in b.sides[i]:
            continue
        a, c, d, e = b.box(i)
        on_face = b.P[i]["side"] == side
        col = "#555555" if b.fixed[i] and not b.label(i, level) else label_colour(b.label(i, level), palette)
        op = 0.85 if on_face else 0.25
        out.append(f'<rect x="{X(a):.1f}" y="{Y(c):.1f}" width="{(d - a) * scale:.1f}" height="{(e - c) * scale:.1f}" '
                   f'fill="{col}" fill-opacity="{op}" stroke="#222" stroke-width="0.6"/>')
        if on_face and (d - a) * scale > 18:
            fs = min(11, (d - a) * scale / 4)
            out.append(f'<text x="{X((a + d) / 2):.1f}" y="{Y((c + e) / 2) + fs / 3:.1f}" font-size="{fs:.1f}" '
                       f'text-anchor="middle" fill="#111">{b.refs[i]}</text>')
    if wires:
        for (ax, ay), (cx, cy), _ in airwires(b):
            out.append(f'<line x1="{X(ax):.1f}" y1="{Y(ay):.1f}" x2="{X(cx):.1f}" y2="{Y(cy):.1f}" '
                       f'stroke="#000" stroke-opacity="0.35" stroke-width="0.7"/>')
    if legend:
        lx = 10
        for lab, name in legend:
            out.append(f'<rect x="{lx:.0f}" y="38" width="12" height="12" fill="{label_colour(lab, palette)}"/>'
                       f'<text x="{lx + 17:.0f}" y="49" font-size="12">{name}</text>')
            lx += 24 + 7 * len(name)
    out.append("</svg>")
    return "\n".join(out)


def curves_svg(series, title, W=900, H=420, ylabel="energy (mm)", xlabel="annealing moves"):
    """series: {label: (colour, [[(x, y), ...], ...])} -- several runs per label, drawn thin, median drawn thick."""
    allx = [x for _, runs in series.values() for run in runs for x, _ in run]
    ally = [y for _, runs in series.values() for run in runs for _, y in run]
    x1 = max(allx)
    ys = sorted(ally)
    y0, y1 = ys[0] * 0.95, ys[int(len(ys) * 0.97)] * 1.05     # clip the hot starts' spikes
    L, R, T, B = 70, 260, 40, 50
    X = lambda x: L + x / x1 * (W - L - R)
    Y = lambda y: T + (1 - (min(max(y, y0), y1) - y0) / (y1 - y0)) * (H - T - B)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="Helvetica">',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<text x="{L}" y="24" font-size="17">{title}</text>',
           f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="#333"/>',
           f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H - B}" stroke="#333"/>',
           f'<text x="{(L + W - R) / 2}" y="{H - 12}" font-size="13" text-anchor="middle">{xlabel}</text>',
           f'<text x="16" y="{(T + H - B) / 2}" font-size="13" transform="rotate(-90 16 {(T + H - B) / 2})" '
           f'text-anchor="middle">{ylabel}</text>']
    for k in range(5):
        yv = y0 + (y1 - y0) * k / 4
        out.append(f'<text x="{L - 6}" y="{Y(yv) + 4:.0f}" font-size="11" text-anchor="end">{yv:.0f}</text>'
                   f'<line x1="{L}" y1="{Y(yv):.0f}" x2="{W - R}" y2="{Y(yv):.0f}" stroke="#eee"/>')
        xv = x1 * k / 4
        out.append(f'<text x="{X(xv):.0f}" y="{H - B + 16}" font-size="11" text-anchor="middle">{xv / 1000:.0f}k</text>')
    ly = T + 10
    for label, (col, runs) in series.items():
        for run in runs:
            p = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in run)
            out.append(f'<polyline points="{p}" fill="none" stroke="{col}" stroke-opacity="0.35" stroke-width="1"/>')
        n = min(len(r) for r in runs)
        med = []
        for k in range(n):
            vals = sorted(r[k][1] for r in runs)
            med.append((runs[0][k][0], vals[len(vals) // 2]))
        p = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in med)
        out.append(f'<polyline points="{p}" fill="none" stroke="{col}" stroke-width="2.5"/>')
        out.append(f'<line x1="{W - R + 12}" y1="{ly}" x2="{W - R + 34}" y2="{ly}" stroke="{col}" stroke-width="3"/>'
                   f'<text x="{W - R + 40}" y="{ly + 4}" font-size="12">{label}</text>')
        ly += 20
    out.append("</svg>")
    return "\n".join(out)
