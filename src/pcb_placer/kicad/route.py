"""Compare placements by routing them (run with KiCad's Python).

Building blocks, so a project can add its own pre-routing aids between them:

    stripped_copy(src, dst)             a copy with every track, via, copper pour (planes kept) and silkscreen removed
    apply_placement(path, placement)    move the free parts: {ref: [x, y, rot]}
    freeroute(path, passes=40)          Freerouting (Docker), up to 3 rounds, the best round kept
    measure(path)                       {unrouted, vias, signal_vias, track_mm}
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pcbnew

MM = pcbnew.FromMM
FREEROUTING_JAR = pathlib.Path.home() / ".kicad-mcp" / "freerouting.jar"
JAVA_IMAGE = "eclipse-temurin:25-jre"


def stripped_copy(src, dst):
    for k, what in enumerate(("tracks", "zones", "silk")):
        subprocess.run([sys.executable, "-m", "pcb_placer.kicad.strip", str(src if k == 0 else dst), str(dst), what],
                       check=True, capture_output=True, env=_env())


def _env():
    import os
    env = dict(os.environ)
    src = str(pathlib.Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def apply_placement(path, placement, aids=None):
    """Move the parts in `placement` ({ref: [x, y, rot]}); then aids(board), if given, adds the project's pre-routing
    (escapes, fanout vias); zones are refilled and the board saved."""
    b = pcbnew.LoadBoard(str(path))
    for f in b.GetFootprints():
        ref = f.GetReference()
        if placement and ref in placement:
            x, y, rot = placement[ref]
            f.SetOrientationDegrees(rot)
            f.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    if aids:
        aids(b)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(str(path), b)


def unrouted(path):
    b = pcbnew.LoadBoard(str(path))
    b.BuildConnectivity()
    return b.GetConnectivity().GetUnconnectedCount(False)


def freeroute(path, passes=40, rounds=3, jar=FREEROUTING_JAR, image=JAVA_IMAGE):
    """Route with Freerouting in Docker (the JAR runs on a recent Java). A later round starts from the routed board
    and can do worse, so the best round is kept. Returns the unrouted count."""
    path = pathlib.Path(path)
    best_path, best = path.with_suffix(".best.kicad_pcb"), None
    for rnd in range(rounds):
        board = pcbnew.LoadBoard(str(path))
        dsn, ses = path.with_suffix(".dsn"), path.with_suffix(".ses")
        if ses.exists():
            ses.unlink()
        pcbnew.ExportSpecctraDSN(board, str(dsn))
        cmd = ["docker", "run", "--rm", "-v", f"{jar}:/app/freerouting.jar:ro", "-v", f"{dsn.parent}:/work", image,
               "java", "-jar", "/app/freerouting.jar", "-de", f"/work/{dsn.name}", "-do", f"/work/{ses.name}",
               "--gui.enabled=false", "-mp", str(passes)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3000)
        if not ses.exists():
            raise RuntimeError("freerouting produced no SES:\n" + r.stdout[-2000:] + r.stderr[-2000:])
        pcbnew.ImportSpecctraSES(board, str(ses))
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(str(path), board)
        left = unrouted(path)
        print(f"  route round {rnd + 1}: {left} unrouted")
        if best is None or left < best:
            best = left
            shutil.copyfile(path, best_path)
        if left == 0:
            break
    shutil.copyfile(best_path, path)
    best_path.unlink()
    for f in (path.with_suffix(".dsn"), path.with_suffix(".ses")):
        if f.exists():
            f.unlink()
    return best


def measure(path, plane_nets=("GND",)):
    b = pcbnew.LoadBoard(str(path))
    b.BuildConnectivity()
    tracks = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
    return dict(unrouted=b.GetConnectivity().GetUnconnectedCount(False), vias=len(vias),
                signal_vias=sum(1 for v in vias if v.GetNetname() not in plane_nets),
                track_mm=round(sum(pcbnew.ToMM(t.GetLength()) for t in tracks), 1))
