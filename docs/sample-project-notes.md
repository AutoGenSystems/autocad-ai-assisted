# Sample project: how the floor plans were rebuilt

The sample is a set of two DWG drawings for a **two-storey commercial building**:
ground and second floor plans, a foundation plan, a roof framing plan, four
elevations and a 3D model. The **ground and second floor plans have been rebuilt**
as a plan file from the original geometry, so they can now be regenerated, changed
and extended with Claude.

> The original DWG files, and the rebuilt plan file of that design, are **not**
> committed to this repository. The repository is public, and a client's design
> should only be published with their agreement. `*.dwg` is in `.gitignore` to
> prevent accidents.

## How it was done

1. **DWG → DXF.** The DWG files were converted to DXF with LibreDWG (open-source,
   GNU project) compiled to WebAssembly. This ran with the user's approval, in the
   temporary cloud machine.
2. **3D removed.** The 3D solids and surfaces were stripped, because floor plans are 2D
   and one surface object could not be read.
3. **Geometry read.** The original uses these layers:
   - `GFPW` / `SFPW`: walls, drawn as thick polylines along their centre lines. Width
     0.15 m is exterior, 0.10 m is interior. Each gap between two pieces is an opening.
   - `GFPD&W` / `SFPD&W`: doors (dynamic "Door - Metric" blocks, which show the hinge and
     swing), window frames, the stair, fixtures and furniture.
   - `FPD` and `0`: dimension strings. `TEXT`: room names.
4. **Plan file written.** Every wall, opening, stair flight, fixture, piece of
   furniture and dimension was converted from metres to millimetres, measured from the
   front-left corner of the building.
5. **Checked against the original.** The rebuilt drawing was overlaid on the original,
   with the original in red and the rebuild in black. Walls, door swings, windows,
   fixtures, furniture, counters and stairs coincide on both floors, and the room names
   sit where the original has them.

## What the rebuild contains

Both floors: every wall and opening, the L-shaped stair, the CR fixtures, the kitchen
equipment, the furniture, the room names and the original dimension strings (in
metres). The output is two A3 portrait sheets at 1:100, **A-101 GROUND FLOOR PLAN** and
**A-102 SECOND FLOOR PLAN**. The builder features this needed (sliding doors,
furniture, plain lines, horizontal/vertical dimensions, metre dimensions, portrait
sheets) are general, documented in the plan format, and covered by tests.

## Deliberate differences from the original

- **Interior partitions** drawn in the original as single lines are shown as 100 mm walls.
- **Furniture and fixtures** use simple symbols at the original's positions, sizes and
  rotations, instead of AutoCAD's DesignCenter blocks. Lavatories are the builder's
  standard 550 × 450 mm size, slightly larger than the original's 460 × 375 mm.
- **The second floor's overall width** reads 15.00. The original's overall dimension
  was drawn to the outer face of a window frame and read 15.08.
- **Floor areas** were added for the kitchen, stockroom, terrace and conference room.
  The original has none.
- **Two-line room names** (WOMEN / CR) are centred. In the original they are left-aligned.

## Not rebuilt yet

The foundation plan, roof framing plan, elevations and 3D model. The builder does not
draw those drawing types yet.
