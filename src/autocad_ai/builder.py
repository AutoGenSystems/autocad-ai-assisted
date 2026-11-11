"""Build an AutoCAD drawing (DXF) from a Plan.

AutoCAD opens the DXF directly; use SAVEAS to keep it as a DWG.

What ends up in the drawing:
  * Model space: every level drawn at full size (1 unit = 1 mm), side by side.
  * Paper space: one A3 sheet per level, with a 1:scale viewport and a title block.
  * Standard architectural layer names (A-WALL, A-DOOR, A-GLAZ, ...), so the drawing
    is easy to work with by hand and easy for AutoCAD's own AI tools to query.
  * Doors, windows and fixtures are blocks (DOOR-1L, WINDOW, FIX-WC, ...), so they
    can be counted and selected like any AutoCAD block.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from ezdxf import bbox, const
from ezdxf.document import Drawing
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from ezdxf.layouts import BaseLayout

from .geometry import LevelGeometry, WallFrame, level_geometry, polygon_area_m2, polygon_centre
from .plan import Level, Plan, PlanError, check_plan, errors_only

DXF_VERSION = "R2013"  # AutoCAD 2013 format: opens in AutoCAD / AutoCAD LT 2013 and newer
TEXT_STYLE = "PLAN"

# layer name: (AutoCAD colour index, linetype, lineweight in 1/100 mm, plots?)
LAYERS: dict[str, tuple[int, str, int, bool]] = {
    "A-WALL": (7, "Continuous", 50, True),
    "A-WALL-PATT": (8, "Continuous", 9, True),
    "A-COLS": (7, "Continuous", 35, True),
    "A-DOOR": (3, "Continuous", 25, True),
    "A-GLAZ": (5, "Continuous", 25, True),
    "A-FLOR-STRS": (6, "Continuous", 25, True),
    "A-FLOR-FIXT": (4, "Continuous", 18, True),
    "A-FLOR-CASE": (4, "Continuous", 18, True),   # counters, built-in casework
    "A-FLOR-TPTN": (4, "Continuous", 18, True),   # toilet partitions
    "A-FLOR-HRAL": (6, "Continuous", 25, True),   # railings, parapets
    "A-FLOR-OTLN": (7, "Continuous", 25, True),   # other outlines
    "A-FURN": (8, "Continuous", 13, True),        # loose furniture
    "A-GRID": (1, "CENTER", 13, True),
    "A-GRID-IDEN": (1, "Continuous", 18, True),
    "A-AREA-IDEN": (2, "Continuous", 25, True),
    "A-ANNO-DIMS": (3, "Continuous", 18, True),
    "A-ANNO-SYMB": (2, "Continuous", 18, True),
    "A-ANNO-TEXT": (7, "Continuous", 25, True),
    "A-ANNO-TTLB": (7, "Continuous", 35, True),
    "A-ANNO-VPRT": (8, "Continuous", 9, False),  # viewport frames: visible, not plotted
}

# Text heights and spacing in *paper* millimetres; multiplied by the scale in model space.
H_ROOM, H_AREA, H_GRID, H_TAG, H_TITLE, H_SUBTITLE = 3.0, 2.0, 3.5, 2.0, 5.0, 2.5
DIM_CHAIN, DIM_OVERALL, GRID_END, GRID_TOP, BUBBLE_R = 12.0, 20.0, 28.0, 8.0, 4.0
TITLE_GAP = 12.0  # gap between the lowest grid bubble and the plan title

SHEET_SIZES = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0)}
BORDER = 10.0   # sheet border, mm
STRIP_W = 70.0  # landscape sheets: title block strip on the right
STRIP_H = 48.0  # portrait sheets: title block strip along the bottom

LINE_LAYERS = {"casework": "A-FLOR-CASE", "partition": "A-FLOR-TPTN", "railing": "A-FLOR-HRAL",
               "outline": "A-FLOR-OTLN", "furniture": "A-FURN"}


@dataclass
class BuildResult:
    dxf_path: Path | None
    sheets: list[str]
    counts: dict[str, int]
    room_areas: list[tuple[str, str, float]]  # (level id, room name, area in m2)
    warnings: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------- set-up


def _new_document(plan: Plan) -> Drawing:
    doc = ezdxf.new(DXF_VERSION, setup=["linetypes"], units=ezdxf.units.MM)
    header = doc.header
    header["$MEASUREMENT"] = 1  # metric
    header["$LUNITS"] = 2       # decimal
    header["$LUPREC"] = 0       # show whole millimetres
    header["$LTSCALE"] = 1.0
    header["$PSLTSCALE"] = 0    # linetypes scale with the model, so grids look alike in sheets

    for name, (colour, linetype, lineweight, plots) in LAYERS.items():
        layer = doc.layers.add(name, color=colour, linetype=linetype, lineweight=lineweight)
        layer.dxf.plot = int(plots)

    doc.styles.add(TEXT_STYLE, font="arial.ttf")
    header["$TEXTSTYLE"] = TEXT_STYLE

    scale = plan.project.scale
    in_metres = plan.project.dimension_unit == "m"
    dimstyle = doc.dimstyles.new(f"PLAN-{scale}", dxfattribs={
        "dimscale": scale,   # all sizes below are paper mm, multiplied by the scale
        "dimtxt": 2.5, "dimexe": 1.5, "dimexo": 1.0, "dimgap": 0.8, "dimdle": 1.5,
        "dimtad": 1,         # text above the dimension line
        "dimtih": 0, "dimtoh": 0,  # text aligned with the dimension line
        "dimlunit": 2, "dimtxsty": TEXT_STYLE,
        # Metres: measure in mm but show mm x 0.001 with two decimals, e.g. 15000 -> 15.00.
        "dimlfac": 0.001 if in_metres else 1.0, "dimdec": 2 if in_metres else 0, "dimzin": 0,
        "dimdsep": ord("."),  # decimal point (the ISO default would be a comma)
    })
    dimstyle.set_tick(1.5)   # architectural tick marks instead of arrows
    header["$DIMSTYLE"] = dimstyle.dxf.name

    _define_blocks(doc)
    return doc


def _define_blocks(doc: Drawing) -> None:
    """Blocks are drawn at unit size (doors, windows) or real size (fixtures, mm).

    Their geometry sits on layer 0, so each inserted copy takes the colour and
    lineweight of the layer it is inserted on.
    """
    door = doc.blocks.new("DOOR-1L")  # hinge at (0,0), opening from x=0 to x=1, opens to +y
    door.add_line((0, 0), (0, 1))
    door.add_arc((0, 0), 1, 0, 90)

    double = doc.blocks.new("DOOR-2L")
    double.add_line((0, 0), (0, 0.5))
    double.add_arc((0, 0), 0.5, 0, 90)
    double.add_line((1, 0), (1, 0.5))
    double.add_arc((1, 0), 0.5, 90, 180)

    window = doc.blocks.new("WINDOW")  # x 0..1 along the wall, y -0.5..0.5 across it
    for y in (-0.5, 0.0, 0.5):
        window.add_line((0, y), (1, y))
    window.add_line((0, -0.5), (0, 0.5))
    window.add_line((1, -0.5), (1, 0.5))

    slide = doc.blocks.new("DOOR-SLIDE")  # same frame as WINDOW: two overlapping sliding panels
    slide.add_line((0, -0.5), (0, 0.5))
    slide.add_line((1, -0.5), (1, 0.5))
    slide.add_lwpolyline([(0, 0), (0.55, 0), (0.55, 0.22), (0, 0.22)], close=True)
    slide.add_lwpolyline([(0.45, -0.22), (1, -0.22), (1, 0), (0.45, 0)], close=True)

    # Fixtures: origin = centre of the back edge (against the wall), facing +y.
    wc = doc.blocks.new("FIX-WC")
    wc.add_lwpolyline([(-240, 0), (240, 0), (240, 200), (-240, 200)], close=True)
    wc.add_ellipse((0, 450), major_axis=(0, 250), ratio=0.76)

    lav = doc.blocks.new("FIX-LAV")
    lav.add_lwpolyline([(-275, 0), (275, 0), (275, 450), (-275, 450)], close=True)
    lav.add_ellipse((0, 240), major_axis=(200, 0), ratio=0.7)

    sink = doc.blocks.new("FIX-KSINK")
    sink.add_lwpolyline([(-450, 0), (450, 0), (450, 550), (-450, 550)], close=True)
    for x0, x1 in ((-420, -20), (20, 420)):
        sink.add_lwpolyline([(x0, 70), (x1, 70), (x1, 480), (x0, 480)], close=True)

    urinal = doc.blocks.new("FIX-URINAL")
    urinal.add_lwpolyline([(-200, 0), (200, 0), (200, 60), (-200, 60)], close=True)
    urinal.add_ellipse((0, 200), major_axis=(180, 0), ratio=0.8)

    _define_furniture_blocks(doc)


def _rect(block, x0: float, y0: float, x1: float, y1: float) -> None:
    block.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True)


def _define_furniture_blocks(doc: Drawing) -> None:
    """Simple furniture symbols drawn in a 1 x 1 square centred on the origin.

    Each insert is scaled to the item's real width (x) and depth (y); the back of the
    item is the +y side.
    """
    for name, seats in (("FURN-SOFA", 3), ("FURN-LOVESEAT", 2)):
        sofa = doc.blocks.new(name)
        _rect(sofa, -0.5, -0.5, 0.5, 0.5)
        sofa.add_line((-0.5, 0.2), (0.5, 0.2))      # back cushion
        sofa.add_line((-0.42, -0.5), (-0.42, 0.2))  # arms
        sofa.add_line((0.42, -0.5), (0.42, 0.2))
        for k in range(1, seats):
            x = -0.42 + 0.84 * k / seats
            sofa.add_line((x, -0.45), (x, 0.2))
    table = doc.blocks.new("FURN-TABLE")
    _rect(table, -0.5, -0.5, 0.5, 0.5)
    _rect(table, -0.45, -0.4, 0.45, 0.4)
    desk = doc.blocks.new("FURN-DESK")
    _rect(desk, -0.5, -0.5, 0.5, 0.5)
    _rect(desk, 0.15, -0.45, 0.45, 0.45)          # drawer unit
    hutch = doc.blocks.new("FURN-HUTCH")
    _rect(hutch, -0.5, -0.5, 0.5, 0.5)
    hutch.add_line((-0.5, -0.2), (0.5, -0.2))
    hutch.add_line((0, -0.5), (0, -0.2))
    plant = doc.blocks.new("FURN-PLANT")
    plant.add_circle((0, 0), 0.5)
    plant.add_circle((0, 0), 0.12)
    for k in range(8):
        a = math.radians(22.5 + 45 * k)
        plant.add_line((0.16 * math.cos(a), 0.16 * math.sin(a)), (0.46 * math.cos(a), 0.46 * math.sin(a)))
    piano = doc.blocks.new("FURN-PIANO")          # grand piano: keyboard along the back (+y)
    piano.add_lwpolyline([(-0.5, 0.5, 0), (0.5, 0.5, 0), (0.5, -0.05, -0.414), (-0.05, -0.5, 0),
                          (-0.5, -0.5, 0)], format="xyb", close=True)
    piano.add_line((-0.5, 0.35), (0.5, 0.35))
    dining = doc.blocks.new("FURN-DINING")        # table with three chairs per side and one per end
    _rect(dining, -0.4, -0.3, 0.4, 0.3)
    for x in (-0.25, 0.0, 0.25):
        _rect(dining, x - 0.07, 0.34, x + 0.07, 0.48)
        _rect(dining, x - 0.07, -0.48, x + 0.07, -0.34)
    _rect(dining, 0.43, -0.1, 0.5, 0.1)
    _rect(dining, -0.5, -0.1, -0.43, 0.1)
    fridge = doc.blocks.new("FURN-FRIDGE")
    _rect(fridge, -0.5, -0.5, 0.5, 0.5)
    fridge.add_line((-0.5, -0.3), (0.5, -0.3))   # door
    fridge.add_line((-0.5, -0.3), (0.5, 0.5))
    stove = doc.blocks.new("FURN-RANGE")
    _rect(stove, -0.5, -0.5, 0.5, 0.5)
    for x, y in ((-0.22, -0.2), (0.22, -0.2), (-0.22, 0.2), (0.22, 0.2)):
        stove.add_circle((x, y), 0.13)
    bar = doc.blocks.new("FURN-WETBAR")
    _rect(bar, -0.5, -0.5, 0.5, 0.5)
    _rect(bar, -0.18, -0.3, 0.18, 0.1)            # bar sink
    stool = doc.blocks.new("FURN-STOOL")
    stool.add_circle((0, 0), 0.5)


FIXTURE_BLOCKS = {"wc": "FIX-WC", "lavatory": "FIX-LAV", "kitchen_sink": "FIX-KSINK", "urinal": "FIX-URINAL"}
FURNITURE_BLOCKS = {"sofa": "FURN-SOFA", "loveseat": "FURN-LOVESEAT", "table": "FURN-TABLE",
                    "desk": "FURN-DESK", "hutch": "FURN-HUTCH", "plant": "FURN-PLANT", "piano": "FURN-PIANO",
                    "dining_set": "FURN-DINING", "refrigerator": "FURN-FRIDGE", "range": "FURN-RANGE",
                    "wet_bar": "FURN-WETBAR", "stool": "FURN-STOOL"}


# ------------------------------------------------------------------- drawing


class _LevelDrawer:
    """Draws one level into model space, shifted by its origin."""

    def __init__(self, doc: Drawing, plan: Plan, level: Level, geom: LevelGeometry, origin):
        self.doc, self.plan, self.level, self.geom = doc, plan, level, geom
        self.msp = doc.modelspace()
        self.ox, self.oy = origin
        self.s = plan.project.scale
        self.counts = {"walls": len(level.walls), "doors": 0, "windows": 0, "openings": 0,
                       "rooms": 0, "stairs": 0, "fixtures": 0, "furniture": 0, "columns": 0}
        self.room_areas: list[tuple[str, str, float]] = []
        self._start = len(self.msp)  # index of this level's first entity in model space

    # helpers ------------------------------------------------------------------
    def p(self, x: float, y: float) -> tuple[float, float]:
        return (x + self.ox, y + self.oy)

    def text(self, value: str, at, height_paper: float, layer: str,
             align=TextEntityAlignment.MIDDLE_CENTER, rotation: float = 0.0):
        entity = self.msp.add_text(value, height=height_paper * self.s, rotation=rotation,
                                   dxfattribs={"layer": layer, "style": TEXT_STYLE})
        entity.set_placement(self.p(*at), align=align)
        return entity

    def line(self, a, b, layer: str, **attribs):
        return self.msp.add_line(self.p(*a), self.p(*b), dxfattribs={"layer": layer, **attribs})

    # parts --------------------------------------------------------------------
    def walls(self) -> None:
        for polygon in self.geom.walls.geoms:
            rings = [list(polygon.exterior.coords)] + [list(r.coords) for r in polygon.interiors]
            for ring in rings:
                self.msp.add_lwpolyline([self.p(x, y) for x, y in ring[:-1]], close=True,
                                        dxfattribs={"layer": "A-WALL"})
            hatch = self.msp.add_hatch(color=256, dxfattribs={"layer": "A-WALL-PATT"})
            hatch.set_pattern_fill("ANSI31", color=256, scale=self.s * 0.25, style=0)
            for i, ring in enumerate(rings):
                flags = const.BOUNDARY_PATH_EXTERNAL if i == 0 else const.BOUNDARY_PATH_DEFAULT
                hatch.paths.add_polyline_path([self.p(x, y) for x, y in ring[:-1]], is_closed=True, flags=flags)

    def openings(self) -> None:
        for wall, frame in zip(self.level.walls, self.geom.frames):
            for opening in wall.openings:
                self._opening(frame, opening)

    def _opening(self, frame: WallFrame, opening) -> None:
        a, w, t = opening.offset, opening.width, frame.thickness
        side = 1 if opening.swing == "left" else -1  # +1 = wall's left (+n) side
        if opening.type in ("door", "double_door"):
            hinge_at_end = opening.type == "door" and opening.hinge == "end"
            # Block x axis follows the closed door leaf, y axis points the way it opens.
            # A negative y scale mirrors the block when the leaf runs the "wrong" way.
            rotation = frame.angle_deg + (180 if hinge_at_end else 0)
            yscale = w * side * (-1 if hinge_at_end else 1)
            insert = frame.at(a + w if hinge_at_end else a, side * t / 2)
            block = "DOOR-1L" if opening.type == "door" else "DOOR-2L"
            self.msp.add_blockref(block, self.p(*insert), dxfattribs={
                "layer": "A-DOOR", "xscale": w, "yscale": yscale, "rotation": rotation})
            self.counts["doors"] += 1
            tag_side = -side
        elif opening.type in ("window", "sliding_door"):
            is_window = opening.type == "window"
            self.msp.add_blockref("WINDOW" if is_window else "DOOR-SLIDE", self.p(*frame.at(a)), dxfattribs={
                "layer": "A-GLAZ" if is_window else "A-DOOR", "xscale": w, "yscale": t,
                "rotation": frame.angle_deg})
            self.counts["windows" if is_window else "doors"] += 1
            tag_side = -1
        else:
            self.counts["openings"] += 1
            tag_side = -1
        if opening.tag:
            self.text(opening.tag, frame.at(a + w / 2, tag_side * (t / 2 + 3.5 * self.s)), H_TAG, "A-ANNO-SYMB")

    def columns(self) -> None:
        spec = self.level.columns
        if spec == "none":
            return
        if spec == "grid":
            if self.plan.grids is None:
                return
            points = [(x, y) for x in self.plan.grids.x for y in self.plan.grids.y]
        else:
            points = list(spec)
        h = self.plan.defaults.column_size / 2
        for x, y in points:
            square = [self.p(x - h, y - h), self.p(x + h, y - h), self.p(x + h, y + h), self.p(x - h, y + h)]
            self.msp.add_lwpolyline(square, close=True, dxfattribs={"layer": "A-COLS"})
            fill = self.msp.add_hatch(color=256, dxfattribs={"layer": "A-COLS"})
            fill.set_solid_fill(color=256)
            fill.paths.add_polyline_path(square, is_closed=True)
            self.counts["columns"] += 1

    def reference_box(self) -> tuple[float, float, float, float]:
        """Walls plus grid lines, in level coordinates: the box annotations are placed around."""
        x0, y0, x1, y1 = self.geom.bounds
        if self.plan.grids:
            x0, x1 = min([x0, *self.plan.grids.x]), max([x1, *self.plan.grids.x])
            y0, y1 = min([y0, *self.plan.grids.y]), max([y1, *self.plan.grids.y])
        return x0, y0, x1, y1

    def grids_and_dimensions(self) -> None:
        x0, y0, x1, y1 = self.reference_box()
        s, style = self.s, f"PLAN-{self.s}"
        dim = {"layer": "A-ANNO-DIMS"}
        grids = self.plan.grids
        xs = grids.x if grids else [x0, x1]
        ys = grids.y if grids else [y0, y1]
        if grids:
            r = BUBBLE_R * s
            for x, label in zip(grids.x, grids.labels("x")):
                self.line((x, y1 + GRID_TOP * s), (x, y0 - GRID_END * s), "A-GRID", ltscale=5 * s)
                self.msp.add_circle(self.p(x, y0 - GRID_END * s - r), r, dxfattribs={"layer": "A-GRID-IDEN"})
                self.text(label, (x, y0 - GRID_END * s - r), H_GRID, "A-GRID-IDEN")
            for y, label in zip(grids.y, grids.labels("y")):
                self.line((x1 + GRID_TOP * s, y), (x0 - GRID_END * s, y), "A-GRID", ltscale=5 * s)
                self.msp.add_circle(self.p(x0 - GRID_END * s - r, y), r, dxfattribs={"layer": "A-GRID-IDEN"})
                self.text(label, (x0 - GRID_END * s - r, y), H_GRID, "A-GRID-IDEN")
        # Chain of bay dimensions, then one overall dimension further out.
        for values, horizontal in ((xs, True), (ys, False)) if self.level.auto_dimensions else ():
            rows = [(DIM_CHAIN, list(zip(values, values[1:])))]
            if len(values) > 2:
                rows.append((DIM_OVERALL, [(values[0], values[-1])]))
            for distance, pairs in rows:
                for a, b in pairs:
                    if horizontal:
                        line_y = y0 - distance * s
                        self.msp.add_linear_dim(base=self.p(a, line_y), p1=self.p(a, y0 - 3 * s),
                                                p2=self.p(b, y0 - 3 * s), angle=0, dimstyle=style,
                                                dxfattribs=dim).render()
                    else:
                        line_x = x0 - distance * s
                        self.msp.add_linear_dim(base=self.p(line_x, a), p1=self.p(x0 - 3 * s, a),
                                                p2=self.p(x0 - 3 * s, b), angle=90, dimstyle=style,
                                                dxfattribs=dim).render()
        for extra in self.level.dimensions:
            if extra.kind == "aligned":
                self.msp.add_aligned_dim(self.p(*extra.p1), self.p(*extra.p2), distance=extra.offset,
                                         dimstyle=style, dxfattribs=dim).render()
            else:  # horizontal / vertical: measures only the x or y difference
                self.msp.add_linear_dim(base=self.p(*extra.at), p1=self.p(*extra.p1), p2=self.p(*extra.p2),
                                        angle=0 if extra.kind == "horizontal" else 90, dimstyle=style,
                                        dxfattribs=dim).render()

    def _fit(self, height: float, text: str, room_width: float | None) -> float:
        """Shrink a label's paper height so the text fits across the room (never below 1.5 mm)."""
        if room_width is None or not text:
            return height
        needed = 0.8 * height * self.s * len(text)  # generous width estimate for capitals
        return max(1.5, height * min(1.0, room_width / needed))

    def rooms(self) -> None:
        for room in self.level.rooms:
            at = room.label_at or polygon_centre(room.boundary)
            width = None
            if room.boundary:
                xs = [x for x, _ in room.boundary]
                width = max(xs) - min(xs) - 400  # leave room for the walls on both sides
            # A name may span lines ("WOMEN\nCR"); the area goes on the last line.
            names = room.name.split("\n")
            name_h = min(self._fit(H_ROOM, line, width) for line in names)
            rows = [(line, name_h) for line in names]
            if room.boundary:
                area = polygon_area_m2(room.boundary)
                self.room_areas.append((self.level.id, room.name.replace("\n", " "), area))
                label = f"{area:.2f} SQ.M."
                rows.append((label, self._fit(H_AREA, label, width)))
            pitches = [1.5 * height * self.s for _, height in rows]
            y = at[1] + sum(pitches) / 2  # centre the whole label block on `at`
            for (value, height), pitch in zip(rows, pitches):
                self.text(value, (at[0], y - pitch / 2), height, "A-AREA-IDEN")
                y -= pitch
            self.counts["rooms"] += 1

    def stairs(self) -> None:
        for stair in self.level.stairs:
            angle = math.radians(stair.direction)
            u, n = (math.cos(angle), math.sin(angle)), (-math.sin(angle), math.cos(angle))

            def at(along: float, across: float = 0.0):
                return (stair.start[0] + u[0] * along + n[0] * across,
                        stair.start[1] + u[1] * along + n[1] * across)

            half, run = stair.width / 2, stair.length
            outline = [at(0, -half), at(run, -half), at(run, half), at(0, half)]
            self.msp.add_lwpolyline([self.p(*q) for q in outline], close=True,
                                    dxfattribs={"layer": "A-FLOR-STRS"})
            treads = stair.risers - 1
            for k in range(1, treads):
                self.line(at(run * k / treads, -half), at(run * k / treads, half), "A-FLOR-STRS")
            # Travel arrow along the centre line.
            tip, head = at(run * 0.92), 1.5 * self.s
            self.msp.add_lwpolyline([self.p(*at(run * 0.08)), self.p(*tip)], dxfattribs={"layer": "A-FLOR-STRS"})
            self.line(tip, at(run * 0.92 - head, head * 0.6), "A-FLOR-STRS")
            self.line(tip, at(run * 0.92 - head, -head * 0.6), "A-FLOR-STRS")
            if stair.label:
                self.text(stair.label, stair.label_at or at(-3.0 * self.s), H_ROOM, "A-FLOR-STRS")
            self.counts["stairs"] += 1

    def fixtures(self) -> None:
        for fixture in self.level.fixtures:
            self.msp.add_blockref(FIXTURE_BLOCKS[fixture.kind], self.p(*fixture.at),
                                  dxfattribs={"layer": "A-FLOR-FIXT", "rotation": fixture.rotation})
            self.counts["fixtures"] += 1

    def furniture(self) -> None:
        for item in self.level.furniture:
            width, depth = item.size
            self.msp.add_blockref(FURNITURE_BLOCKS[item.kind], self.p(*item.at), dxfattribs={
                "layer": "A-FURN", "xscale": width, "yscale": depth, "rotation": item.rotation})
            self.counts["furniture"] += 1

    def lines(self) -> None:
        for spec in self.level.lines:
            self.msp.add_lwpolyline([self.p(*q) for q in spec.points], close=spec.closed,
                                    dxfattribs={"layer": LINE_LAYERS[spec.layer]})

    def notes(self) -> None:
        for note in self.level.notes:
            self.text(note.text, note.at, note.height, "A-ANNO-TEXT", align=TextEntityAlignment.LEFT)

    def title(self) -> None:
        x0, _, x1, _ = self.reference_box()
        s, cx = self.s, (x0 + x1) / 2
        # Start below the lowest thing drawn so far for this level (dimensions, bubbles...).
        drawn = bbox.extents(list(self.msp)[self._start:])
        lowest = drawn.extmin.y - self.oy
        y = lowest - (TITLE_GAP + H_TITLE / 2) * s
        self.text(self.level.title, (cx, y), H_TITLE, "A-ANNO-TEXT")
        half = 0.36 * H_TITLE * s * len(self.level.title)  # rough width of Arial capitals
        self.line((cx - half, y - 0.8 * H_TITLE * s), (cx + half, y - 0.8 * H_TITLE * s), "A-ANNO-TEXT")
        self.text(f"SCALE 1:{s}", (cx, y - 2.0 * H_TITLE * s), H_SUBTITLE, "A-ANNO-TEXT")

    def draw(self) -> None:
        self._start = len(self.msp)
        self.walls()
        self.openings()
        self.columns()
        self.grids_and_dimensions()
        self.rooms()
        self.stairs()
        self.fixtures()
        self.furniture()
        self.lines()
        self.notes()
        self.title()


# --------------------------------------------------------------------- sheets


def layout_name(sheet_no: str, title: str) -> str:
    """AutoCAD refuses layout names containing < > / \\ " : ; ? * | , = ` (and max 255 chars)."""
    return re.sub(r'[<>/\\":;?*|,=`]', "-", f"{sheet_no} {title}")[:255]


def _mtext_safe(text: str) -> str:
    """Escape characters MTEXT would read as formatting codes."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def sheet_size(plan: Plan) -> tuple[float, float]:
    """(width, height) of the sheet in mm, honouring the plan's size and orientation."""
    w, h = SHEET_SIZES[plan.project.sheet_size]
    return (h, w) if plan.project.sheet_orientation == "portrait" else (w, h)


def _title_fields(layout, fields, x0: float, x1: float, top: float, ttlb: dict) -> float:
    """Stack label/value boxes downwards from `top` between x0 and x1; returns the bottom y."""
    y = top
    chars = max(8, int((x1 - x0 - 6) / 1.9))  # how many 3 mm characters fit on one line
    for label, value in fields:
        height = 6.0 if label == "SHEET NO." else 3.0
        layout.add_text(label, height=1.8, dxfattribs={**ttlb, "style": TEXT_STYLE}).set_placement(
            (x0 + 3, y - 4), align=TextEntityAlignment.LEFT)
        baseline = y - 6.5 - height  # value text starts below the small label
        for text_line in textwrap.wrap(value, chars) or ["-"]:
            layout.add_text(text_line, height=height, dxfattribs={**ttlb, "style": TEXT_STYLE}).set_placement(
                (x0 + 3, baseline), align=TextEntityAlignment.LEFT)
            baseline -= 1.6 * height
        y = baseline + 1.6 * height - 3.0  # bottom of this field's box
        layout.add_line((x0, y), (x1, y), dxfattribs=ttlb)
    return y


def _add_sheet(doc: Drawing, plan: Plan, level: Level, sheet_no: str,
               view: tuple[float, float, float, float], warnings: list[str]) -> str:
    name = layout_name(sheet_no, level.title)
    layout = doc.layouts.new(name)
    sheet_w, sheet_h = sheet_size(plan)
    media = f"ISO_full_bp_{plan.project.sheet_size}_({sheet_w:.2f}_x_{sheet_h:.2f}_MM)"
    layout.page_setup(size=(sheet_w, sheet_h), margins=(0, 0, 0, 0), units="mm",
                      name=media, device="DWG To PDF.pc3")
    ttlb = {"layer": "A-ANNO-TTLB"}
    left, bottom, right, top = BORDER, BORDER, sheet_w - BORDER, sheet_h - BORDER
    layout.add_lwpolyline([(left, bottom), (right, bottom), (right, top), (left, top)], close=True,
                          dxfattribs={**ttlb, "const_width": 0.5})

    project = plan.project
    fields = [("PROJECT", project.name), ("LOCATION", project.location or "-"),
              ("SHEET TITLE", level.title), ("SCALE", f"1:{project.scale}"),
              ("DATE", dt.date.today().isoformat()), ("SHEET NO.", sheet_no)]
    notes = project.notes + ["Generated with autocad-ai (AI-assisted). Check all dimensions on site."]
    notes_text = "NOTES:\\P" + "\\P".join(f"- {_mtext_safe(n)}" for n in notes)

    if project.sheet_orientation == "landscape":
        # Title block strip on the right: fields stacked from the top, then the notes.
        strip = right - STRIP_W
        layout.add_line((strip, bottom), (strip, top), dxfattribs=ttlb)
        y = _title_fields(layout, fields, strip, right, top, ttlb)
        notes_at, notes_width = (strip + 3, y - 3), STRIP_W - 6
        area = (left, bottom, strip, top)
    else:
        # Title block strip along the bottom: three columns of two fields, then the notes.
        strip = bottom + STRIP_H
        layout.add_line((left, strip), (right, strip), dxfattribs=ttlb)
        column = (right - left) * 0.2
        for k in range(3):
            x0 = left + k * column
            _title_fields(layout, fields[2 * k:2 * k + 2], x0, x0 + column, strip, ttlb)
            layout.add_line((x0 + column, bottom), (x0 + column, strip), dxfattribs=ttlb)
        notes_at, notes_width = (left + 3 * column + 3, strip - 3), right - left - 3 * column - 6
        area = (left, strip, right, top)
    mtext = layout.add_mtext(notes_text, dxfattribs={**ttlb, "style": TEXT_STYLE, "char_height": 2.0,
                                                     "width": notes_width})
    mtext.set_location(notes_at, attachment_point=MTextEntityAlignment.TOP_LEFT)

    # Viewport onto model space at exactly 1:scale. It is sized to this level's drawing
    # (plus a small margin) so the neighbouring level in model space stays out of view.
    area_w, area_h = area[2] - area[0] - 10, area[3] - area[1] - 10
    x0, y0, x1, y1 = view
    margin = 5.0  # paper mm around the level
    vp_w = (x1 - x0) / project.scale + 2 * margin
    vp_h = (y1 - y0) / project.scale + 2 * margin
    view_height = vp_h * project.scale  # model mm shown top-to-bottom: the level plus margins
    if vp_w > area_w or vp_h > area_h:
        # Too big for the sheet at this scale: shrink the frame, keep the same view (= zoom out).
        fit = max(vp_w / area_w, vp_h / area_h)
        vp_w, vp_h = vp_w / fit, vp_h / fit
        warnings.append(f"{name}: level does not fit an {project.sheet_size} {project.sheet_orientation} sheet "
                        f"at 1:{project.scale}; viewport zoomed out")
    layout.add_viewport(center=((area[0] + area[2]) / 2, (area[1] + area[3]) / 2), size=(vp_w, vp_h),
                        view_center_point=((x0 + x1) / 2, (y0 + y1) / 2), view_height=view_height,
                        dxfattribs={"layer": "A-ANNO-VPRT"})
    return name


# ---------------------------------------------------------------------- entry


def build_document(plan: Plan) -> tuple[Drawing, BuildResult]:
    """Create the drawing in memory. Raises PlanError if the plan has design errors."""
    issues = check_plan(plan)
    if errors_only(issues):
        raise PlanError("The plan has errors:\n" + "\n".join(f"- {i}" for i in errors_only(issues)))
    doc = _new_document(plan)
    result = BuildResult(None, [], {}, [], [str(i) for i in issues])

    cursor_x = 0.0
    gap = 30.0 * plan.project.scale  # space between levels in model space
    for index, level in enumerate(plan.levels):
        geom = level_geometry(plan, level)
        if level.origin is not None:
            origin = level.origin
        elif index == 0:
            origin = (0.0, 0.0)  # first level: AutoCAD coordinates = plan coordinates
        else:
            # Put this level to the right of everything drawn so far.
            probe = _LevelDrawer(doc, plan, level, geom, (0, 0))
            left_edge = probe.reference_box()[0] - (GRID_END + 2 * BUBBLE_R + 5) * plan.project.scale
            origin = (cursor_x + gap - left_edge, 0.0)
        drawer = _LevelDrawer(doc, plan, level, geom, origin)
        before = len(doc.modelspace())
        drawer.draw()
        level_box = bbox.extents(list(doc.modelspace())[before:])
        cursor_x = level_box.extmax.x
        for key, value in drawer.counts.items():
            result.counts[key] = result.counts.get(key, 0) + value
        result.room_areas.extend(drawer.room_areas)
        sheet_no = f"{plan.project.sheet_prefix}{index + 1:02d}"
        view = (level_box.extmin.x, level_box.extmin.y, level_box.extmax.x, level_box.extmax.y)
        result.sheets.append(_add_sheet(doc, plan, level, sheet_no, view, result.warnings))

    doc.layouts.delete("Layout1")  # the empty default sheet
    everything = bbox.extents(doc.modelspace())
    doc.set_modelspace_vport(height=everything.size.y * 1.1, center=everything.center)
    result.counts["levels"] = len(plan.levels)
    return doc, result


def build_to_file(plan: Plan, dxf_path: str | Path) -> BuildResult:
    """Build and save the DXF only (see pipeline.build_outputs for DXF + previews)."""
    doc, result = build_document(plan)
    dxf_path = Path(dxf_path)
    dxf_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(dxf_path)
    result.dxf_path = dxf_path
    return result
