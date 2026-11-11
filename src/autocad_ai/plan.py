"""The plan file format: a short, human- and AI-friendly description of a building.

A plan file is YAML. It records *design intent* (walls, doors, rooms, stairs) instead
of raw CAD lines, and builder.py turns it into an AutoCAD drawing.

Conventions used everywhere in this project:
  * All lengths are millimetres (mm).
  * Points are [x, y] in mm, x to the right, y upwards, in the level's own coordinates.
  * A wall is a straight centre line from `start` to `end` with a thickness.

The full field reference lives in plan_format.md (also returned by the MCP tool
`cad_get_plan_format`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon

Point = tuple[float, float]

# Openings closer than this to each other, or to a wall end, are reported.
TOLERANCE_MM = 1.0


class PlanError(ValueError):
    """The plan file could not be read or does not match the format."""


class _Model(BaseModel):
    # "forbid" turns typos such as `widht:` into clear errors instead of silently
    # ignoring them, which matters when an AI writes the file.
    model_config = ConfigDict(extra="forbid")


class Opening(_Model):
    """A door, window or plain opening cut into its wall."""

    type: Literal["door", "double_door", "sliding_door", "window", "opening"]
    offset: float = Field(ge=0, description="mm from the wall's start point to the opening's near edge")
    width: float = Field(gt=0, description="clear width in mm")
    hinge: Literal["start", "end"] = Field(
        "start", description="doors: which jamb holds the hinge, the one nearer the wall start or end")
    swing: Literal["left", "right"] = Field(
        "left", description="doors: side the door opens towards, looking from wall start to end")
    tag: str | None = Field(None, description="optional label such as D1 or W2")


class Wall(_Model):
    start: Point
    end: Point
    thickness: float | None = Field(None, gt=0, description="mm; defaults to defaults.wall_thickness")
    openings: list[Opening] = Field(default_factory=list)

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)


class Room(_Model):
    name: str
    boundary: list[Point] | None = Field(
        None, min_length=3, description="corner points; used to compute the area")
    label_at: Point | None = Field(None, description="where to write the name; default: centre of boundary")

    @model_validator(mode="after")
    def _needs_position(self) -> "Room":
        if self.boundary is None and self.label_at is None:
            raise ValueError("a room needs `boundary` (to compute its area) or `label_at` (label position)")
        return self


class Stair(_Model):
    start: Point = Field(description="centre of the bottom edge of the first step")
    width: float = Field(gt=0)
    length: float = Field(gt=0, description="horizontal run in mm")
    direction: float = Field(90, description="travel direction in degrees, 0 = +x, 90 = +y")
    risers: int = Field(18, ge=2)
    label: str = Field("UP", description="UP on the lower floor, DN on the upper floor; '' for no label "
                                         "(e.g. the second flight of an L-shaped stair)")
    label_at: Point | None = Field(None, description="where to write the label; default: just before the first step")


class Fixture(_Model):
    kind: Literal["wc", "lavatory", "kitchen_sink", "urinal"]
    at: Point = Field(description="centre of the fixture's back edge (the side against the wall)")
    rotation: float = Field(0, description="degrees; 0 = fixture faces +y, 180 = faces -y")


FurnitureKind = Literal["sofa", "loveseat", "table", "desk", "hutch", "plant", "piano", "dining_set",
                        "refrigerator", "range", "wet_bar", "stool"]


class Furniture(_Model):
    """Loose furniture drawn as a simple symbol, sized to `size` and turned by `rotation`."""

    kind: FurnitureKind
    at: Point = Field(description="centre of the item's footprint")
    size: tuple[float, float] = Field(description="[width, depth] in mm before rotation; the back is the +y side")
    rotation: float = Field(0, description="degrees anticlockwise; 0 = back towards +y")


class Lines(_Model):
    """Plain lines for things that are not walls: counters, toilet partitions, railings..."""

    points: list[Point] = Field(min_length=2)
    closed: bool = False
    layer: Literal["casework", "partition", "railing", "outline", "furniture"] = "outline"


class Dimension(_Model):
    p1: Point
    p2: Point
    kind: Literal["aligned", "horizontal", "vertical"] = Field(
        "aligned", description="aligned = true distance; horizontal/vertical = only the x or y difference")
    offset: float = Field(800, description="aligned only: mm from the measured points to the dimension line")
    at: Point | None = Field(None, description="horizontal/vertical: any point on the dimension line")

    @model_validator(mode="after")
    def _needs_line_position(self) -> "Dimension":
        if self.kind != "aligned" and self.at is None:
            raise ValueError("horizontal and vertical dimensions need `at`, a point on the dimension line")
        return self


class Note(_Model):
    text: str
    at: Point
    height: float = Field(2.5, gt=0, description="text height on paper in mm (scaled by the plan scale)")


class Level(_Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", description="short id such as GF or 2F")
    title: str = Field(description="drawing title, e.g. GROUND FLOOR PLAN")
    origin: Point | None = Field(
        None, description="where this level sits in model space; default: placed beside the previous level")
    walls: list[Wall] = Field(min_length=1)
    rooms: list[Room] = Field(default_factory=list)
    stairs: list[Stair] = Field(default_factory=list)
    fixtures: list[Fixture] = Field(default_factory=list)
    furniture: list[Furniture] = Field(default_factory=list)
    lines: list[Lines] = Field(default_factory=list)
    columns: Literal["grid", "none"] | list[Point] = Field(
        "grid", description="'grid' = a column at every grid intersection, or a list of points")
    auto_dimensions: bool = Field(True, description="add grid (or overall) dimension chains automatically")
    dimensions: list[Dimension] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)


class Grids(_Model):
    x: list[float] = Field(min_length=1, description="x positions of vertical grid lines (labelled 1, 2, 3...)")
    y: list[float] = Field(min_length=1, description="y positions of horizontal grid lines (labelled A, B, C...)")
    x_labels: list[str] | None = None
    y_labels: list[str] | None = None

    @model_validator(mode="after")
    def _labels_match(self) -> "Grids":
        for axis in ("x", "y"):
            labels = getattr(self, f"{axis}_labels")
            if labels is not None and len(labels) != len(getattr(self, axis)):
                raise ValueError(f"{axis}_labels must have one label per {axis} grid line")
        return self

    def labels(self, axis: Literal["x", "y"]) -> list[str]:
        given = getattr(self, f"{axis}_labels")
        if given is not None:
            return given
        count = len(getattr(self, axis))
        if axis == "x":
            return [str(i + 1) for i in range(count)]
        return [_letters(i) for i in range(count)]


class Defaults(_Model):
    wall_thickness: float = Field(150, gt=0)
    column_size: float = Field(300, gt=0, description="side of a square column in mm")


class Project(_Model):
    name: str
    scale: int = Field(100, ge=1, description="drawing scale 1:scale, e.g. 100")
    sheet_prefix: str = Field("A-1", description="sheet numbers become <prefix>01, <prefix>02, ...")
    sheet_size: Literal["A4", "A3", "A2", "A1"] = "A3"
    sheet_orientation: Literal["landscape", "portrait"] = "landscape"
    dimension_unit: Literal["mm", "m"] = Field(
        "mm", description="unit shown in dimension text; 'm' shows 15.00 for 15000 mm (drawing stays in mm)")
    location: str | None = None
    notes: list[str] = Field(default_factory=list, description="printed in every title block")


class Plan(_Model):
    project: Project
    units: Literal["mm"] = "mm"
    defaults: Defaults = Field(default_factory=Defaults)
    grids: Grids | None = None
    levels: list[Level] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_level_ids(self) -> "Plan":
        ids = [level.id for level in self.levels]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"level ids must be unique; repeated: {', '.join(duplicates)}")
        return self

    def thickness(self, wall: Wall) -> float:
        return wall.thickness if wall.thickness is not None else self.defaults.wall_thickness


def _letters(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA (spreadsheet-style grid letters)."""
    text = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        text = chr(65 + rest) + text
    return text


# --------------------------------------------------------------------------- loading


def _describe_validation_error(error: ValidationError) -> str:
    lines = []
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"]) or "(top level)"
        lines.append(f"- {where}: {item['msg']}")
    return "The plan does not match the format:\n" + "\n".join(lines)


def parse_plan(text: str) -> Plan:
    """Parse YAML text into a Plan, raising PlanError with readable messages."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PlanError(f"The plan is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError("The plan must be a YAML mapping with `project:` and `levels:` keys.")
    try:
        return Plan.model_validate(data)
    except ValidationError as exc:
        raise PlanError(_describe_validation_error(exc)) from exc


def load_plan(path: str | Path) -> Plan:
    return parse_plan(Path(path).read_text(encoding="utf-8"))


# ----------------------------------------------------------------- design checks


@dataclass(frozen=True)
class Issue:
    severity: Literal["error", "warning"]
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.where}: {self.message}"


def check_plan(plan: Plan) -> list[Issue]:
    """Checks the format cannot express: openings that do not fit, bad rooms, etc.

    Errors stop a build; warnings are worth a look but the drawing is still produced.
    """
    issues: list[Issue] = []
    for level in plan.levels:
        for w_index, wall in enumerate(level.walls):
            where = f"level {level.id}, wall {w_index}"
            if wall.length < TOLERANCE_MM:
                issues.append(Issue("error", where, "start and end are the same point"))
                continue
            spans = []
            for o_index, opening in enumerate(wall.openings):
                o_where = f"{where}, opening {o_index} ({opening.type})"
                far_edge = opening.offset + opening.width
                if far_edge > wall.length + TOLERANCE_MM:
                    issues.append(Issue("error", o_where, (
                        f"ends {far_edge:.0f} mm along a wall that is only {wall.length:.0f} mm long")))
                if opening.type == "door" and not 600 <= opening.width <= 1500:
                    issues.append(Issue("warning", o_where, f"unusual single-door width {opening.width:.0f} mm"))
                spans.append((opening.offset, far_edge, o_index))
            spans.sort()
            for (a0, a1, ai), (b0, _b1, bi) in zip(spans, spans[1:]):
                if b0 < a1 - TOLERANCE_MM:
                    issues.append(Issue("error", where, f"openings {ai} and {bi} overlap"))
        for r_index, room in enumerate(level.rooms):
            where = f"level {level.id}, room {r_index} ({room.name})"
            if room.boundary is not None:
                polygon = Polygon(room.boundary)
                if not polygon.is_valid or polygon.area <= 0:
                    issues.append(Issue("error", where, "boundary crosses itself or has no area"))
                elif room.label_at is not None and not polygon.contains(ShapelyPoint(room.label_at)):
                    issues.append(Issue("warning", where, "label_at lies outside the room boundary"))
        if isinstance(level.columns, str) and level.columns == "grid" and plan.grids is None:
            issues.append(Issue("warning", f"level {level.id}", "columns: grid, but the plan has no grids"))
        for s_index, stair in enumerate(level.stairs):
            angle = math.radians(stair.direction)
            run = LineString([stair.start, (stair.start[0] + stair.length * math.cos(angle),
                                            stair.start[1] + stair.length * math.sin(angle))])
            if run.length / (stair.risers - 1) < 220:
                issues.append(Issue("warning", f"level {level.id}, stair {s_index}",
                                    "treads shorter than 220 mm; check length or riser count"))
    return issues


def errors_only(issues: list[Issue]) -> list[Issue]:
    return [issue for issue in issues if issue.severity == "error"]
