# Plan file format (YAML)

A plan file describes a building's floor plans as *design intent*: walls, doors,
windows, rooms, stairs and fixtures. The builder turns it into an AutoCAD drawing
with standard layers, dimensions, grid bubbles and one A3 sheet per level.

## Conventions

- **Units: millimetres** for every length. `scale: 100` means the sheets are 1:100.
- **Points are `[x, y]`**: x to the right, y upwards. Each level has its own
  coordinates; levels are placed side by side in model space automatically.
- **Walls are centre lines** from `start` to `end`. A wall's *left side* is the side
  on your left when you walk from `start` to `end`. Tip: list exterior walls
  anticlockwise, so the inside of the building is always on the left.
- **Walls that touch join cleanly.** End a wall exactly on another wall's centre line
  (a corner or a T) and the junction is drawn without gaps or overlaps.
- **Openings** belong to a wall. `offset` is the distance from the wall's `start` to
  the opening's near edge; `width` is the clear width.
- **Door `swing`**: `left` or `right` = the side the door opens towards (walking from
  `start` to `end`). `hinge`: `start` or `end` = which jamb holds the hinge.

## Fields

```yaml
project:
  name: "Corner Shop"          # required; printed in every title block
  location: "Lot 4, Sample St" # optional
  scale: 100                   # 1:100 (default)
  sheet_prefix: "A-1"          # sheets become A-101, A-102, ...
  sheet_size: A3               # A4, A3 (default), A2 or A1
  sheet_orientation: landscape # landscape: title block on the right; portrait: along the bottom
  dimension_unit: mm           # mm (default) shows 15000; m shows 15.00 (the drawing stays in mm)
  notes: ["Areas are to wall centre lines."]   # optional, in every title block

units: mm                      # only mm is supported

defaults:
  wall_thickness: 150          # used when a wall has no `thickness`
  column_size: 300             # square columns

grids:                         # optional structural grid, shared by all levels
  x: [0, 6000, 12000]          # vertical lines, labelled 1, 2, 3
  y: [0, 5500, 9000]           # horizontal lines, labelled A, B, C
  # x_labels / y_labels: optional custom labels, one per line

levels:
  - id: GF                     # short id: letters, digits, - and _
    title: GROUND FLOOR PLAN
    origin: [0, 0]             # optional; default: placed beside the previous level
    columns: grid              # "grid" (every intersection), "none", or [[x, y], ...]
    walls:
      - start: [0, 0]
        end: [12000, 0]
        thickness: 200         # optional; default from `defaults`
        openings:
          - {type: door, offset: 1000, width: 900, swing: left, hinge: start, tag: D1}
          - {type: double_door, offset: 3000, width: 1800, swing: left, tag: D2}
          - {type: sliding_door, offset: 5200, width: 2400}  # two sliding panels
          - {type: window, offset: 8000, width: 1500, tag: W1}
          - {type: opening, offset: 10000, width: 1200}      # gap without a door
    rooms:
      - name: SALES AREA       # use "\n" for two lines, e.g. "WOMEN\nCR"
        boundary: [[0, 0], [12000, 0], [12000, 5500], [0, 5500]]  # gives the area
        label_at: [6000, 2750] # optional; default: middle of the boundary
    stairs:
      - start: [7650, 1000]    # centre of the bottom edge of the first step
        width: 1300
        length: 4250           # horizontal run
        direction: 90          # degrees: 0 = +x, 90 = +y, 180 = -x, 270 = -y
        risers: 18
        label: UP              # UP on the lower floor, DN on the upper floor, "" for none
        label_at: [7650, 500]  # optional; default: just before the first step
      # An L-shaped stair is two flights: give the second flight label: "".
    fixtures:                  # wc, lavatory, kitchen_sink, urinal
      - {kind: wc, at: [9500, 8900], rotation: 180}
        # `at` = centre of the fixture's back edge (against the wall);
        # rotation 0 = faces +y, 180 = faces -y, 90 = faces -x, -90 = faces +x
    furniture:                 # simple symbols, scaled to `size`
      - {kind: sofa, at: [3000, 2000], size: [2134, 864], rotation: 180}
        # kinds: sofa, loveseat, table, desk, hutch, plant, piano, dining_set,
        #        refrigerator, range, wet_bar, stool
        # `at` = centre of the footprint; size = [width, depth] before rotation;
        # the back of the item is its +y side (rotation 0 = back towards +y)
    lines:                     # plain lines that are not walls
      - {layer: casework, closed: true, points: [[0, 11000], [7500, 11000], [7500, 11480], [0, 11480]]}
        # layers: casework (counters), partition (toilet stalls), railing, outline, furniture
    auto_dimensions: true      # grid (or overall) dimension chains; false = only the list below
    dimensions:                # extra dimensions
      - {p1: [0, 0], p2: [4000, 0], offset: -800}   # aligned; offset > 0 = left of p1->p2
      - {kind: horizontal, p1: [0, 0], p2: [4000, 3500], at: [0, -1000]}  # x difference only
      - {kind: vertical, p1: [0, 0], p2: [0, 3500], at: [-1000, 0]}       # y difference only
        # horizontal/vertical: `at` is any point on the dimension line
    notes:
      - {text: "FINISHED FLOOR LEVEL +0.15", at: [500, -1500], height: 2.5}  # paper mm
```

## What gets drawn

| Layer | Contents |
|---|---|
| A-WALL / A-WALL-PATT | wall outlines / wall hatch |
| A-COLS | columns (solid squares) |
| A-DOOR | door blocks DOOR-1L, DOOR-2L (swing arcs), DOOR-SLIDE |
| A-GLAZ | window block WINDOW |
| A-FLOR-STRS | stairs, tread lines, travel arrow, UP/DN |
| A-FLOR-FIXT | fixture blocks FIX-WC, FIX-LAV, FIX-KSINK, FIX-URINAL |
| A-FURN | furniture blocks FURN-SOFA, FURN-TABLE, FURN-PLANT, ... |
| A-FLOR-CASE, A-FLOR-TPTN, A-FLOR-HRAL, A-FLOR-OTLN | `lines`: casework, toilet partitions, railings, outlines |
| A-GRID / A-GRID-IDEN | grid lines / grid bubbles |
| A-AREA-IDEN | room names and areas |
| A-ANNO-DIMS | dimensions (style PLAN-<scale>, tick marks) |
| A-ANNO-SYMB, A-ANNO-TEXT, A-ANNO-TTLB | tags, notes and titles, title blocks |

## Checks

`cad_check_plan` (or `autocad-ai check`) reports **errors** that stop a build, such as
an opening that runs past the end of its wall or two openings that overlap, and
**warnings**, such as an unusual door width, a room label outside its room or treads
shorter than 220 mm.
