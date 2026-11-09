# Problem file format (`pcb-placer/1`)

A JSON object. Lengths in mm, the board's coordinates (KiCad: x right, y down). Faces: `"F"` (the lower face in
KiCad's view, "front") and `"B"`.

```jsonc
{
  "schema": "pcb-placer/1",
  "name": "my board",
  "grid": 0.25,               // positions snap to this grid
  "gap": 0.6,                 // routing room between courtyards
  "outline": [[x, y], ...],   // closed polygon (arcs flattened)
  "obstacles": {              // what free parts may not cover, per face
    "F": {"circles": [[x, y, r]], "rects": [[x0, y0, x1, y1]], "capsules": [[x0, y0, x1, y1, r]]},
    "B": {...}
  },
  "parts": {
    "U1": {
      "side": "F", "x": 10.0, "y": -5.0, "rot": 90,   // the reference placement (footprint origin, degrees)
      "fixed": false,          // fixed parts never move; they are obstacles for the others
      "both_faces": false,     // occupies both faces (through-hole pins, exposed-pad vias)
      "edge_margin": 1.0,      // courtyard to board edge
      "groups": {"island": "mcu", "islet": "core"},    // a label per level ('' or missing = none)
      "pad_numbers": ["1", "2", ...],
      "pad_nets": ["3V3", null, ...],                  // null = unconnected
      "geom": {                // relative to the footprint origin, at each rotation
        "0":   {"box": [x0, y0, x1, y1], "pads": [[dx, dy], ...],
                "copper_other_face": [x0, y0, x1, y1]},  // optional: free two-faced parts
        "90":  {...}, "180": {...}, "270": {...}
      }
    }
  },
  "nets": {"3V3": [["U1", 0], ["C1", 1]]},    // [part, pad index]
  "plane_nets": ["GND"],                       // routed as a plane: no airwire
  "springs": [["C1", 1, "U1", 6]],             // hold C1's pad 1 at U1's pad 6
  "rules": {
    "spring_weight": 2.0,                      // per mm of spring
    "group_levels": ["island", "islet"],       // coarse to fine; the first is the default level
    "net_weights": [{"touching": ["J1"], "factor": 4.0}],   // nets on any of these parts weigh x factor
    "pad_groups": [["J1", 2, "power"]],        // a fixed pad that belongs to a group (bands, island springs)
    "separation": [                            // dirty parts keep `range` from fragile ones (courtyard to courtyard)
      {"level": "islet", "dirty": "surge", "fragile_level": "island", "fragile": ["can", "mcu"], "range": 18.0}
    ]
  }
}
```

`pcb_placer.problem.validate` checks the structure and fills defaults (empty obstacle lists, rules).
`python -m pcb_placer check problem.json` reports what the rules select.

Fixed parts are anchors: a free part may not cover a fixed part's courtyard (grown by `gap`) on the faces the fixed
part occupies. For a free two-faced part, only `copper_other_face` counts on the other face, and it only has to stay
outside fixed parts' courtyards (no gap).
