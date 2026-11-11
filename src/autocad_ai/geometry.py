"""Turn wall centre lines into clean wall outlines with door/window gaps.

How it works (all in the level's own coordinates, millimetres):
  1. Each wall becomes a rectangle around its centre line.
  2. Where a wall end touches another wall, the end is extended by half of that
     other wall's thickness, so L-corners and T-junctions close without gaps.
  3. All rectangles are merged (union) into one shape, so overlapping walls show a
     single clean outline, like a drafter would draw it.
  4. A rectangle for every opening is cut out of that shape.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, MultiPolygon, Point as ShapelyPoint, Polygon
from shapely.ops import unary_union

from .plan import TOLERANCE_MM, Level, Opening, Plan, Wall


@dataclass(frozen=True)
class WallFrame:
    """A wall's local axes: `u` runs from start to end, `n` points to its left side."""

    start: tuple[float, float]
    u: tuple[float, float]
    n: tuple[float, float]
    length: float
    thickness: float

    @property
    def angle_deg(self) -> float:
        return math.degrees(math.atan2(self.u[1], self.u[0]))

    def at(self, along: float, across: float = 0.0) -> tuple[float, float]:
        """Point `along` mm from the start and `across` mm to the left of the centre line."""
        return (self.start[0] + self.u[0] * along + self.n[0] * across,
                self.start[1] + self.u[1] * along + self.n[1] * across)


def wall_frame(wall: Wall, thickness: float) -> WallFrame:
    dx, dy = wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]
    length = math.hypot(dx, dy)
    u = (dx / length, dy / length)
    return WallFrame(wall.start, u, (-u[1], u[0]), length, thickness)


def _rectangle(frame: WallFrame, a: float, b: float, half_width: float) -> Polygon:
    """Rectangle from `a` to `b` along the wall, `half_width` to each side."""
    return Polygon([frame.at(a, -half_width), frame.at(b, -half_width),
                    frame.at(b, half_width), frame.at(a, half_width)])


def _end_extension(plan: Plan, level: Level, index: int, point: tuple[float, float]) -> float:
    """How far to extend a wall end so it reaches across any wall it touches."""
    extension = 0.0
    for other_index, other in enumerate(level.walls):
        if other_index == index or other.length < TOLERANCE_MM:
            continue
        if LineString([other.start, other.end]).distance(ShapelyPoint(point)) <= TOLERANCE_MM:
            extension = max(extension, plan.thickness(other) / 2)
    return extension


def opening_polygon(frame: WallFrame, opening: Opening) -> Polygon:
    # 1 mm wider than the wall on both faces, so the cut never leaves a hair-thin sliver.
    return _rectangle(frame, opening.offset, opening.offset + opening.width, frame.thickness / 2 + 1)


@dataclass
class LevelGeometry:
    walls: MultiPolygon            # final wall shape with all openings cut out
    frames: list[WallFrame]        # one per wall, same order as level.walls
    bounds: tuple[float, float, float, float]  # min x, min y, max x, max y of the walls


def level_geometry(plan: Plan, level: Level) -> LevelGeometry:
    frames, solids, cuts = [], [], []
    for index, wall in enumerate(level.walls):
        frame = wall_frame(wall, plan.thickness(wall))
        frames.append(frame)
        ext_start = _end_extension(plan, level, index, wall.start)
        ext_end = _end_extension(plan, level, index, wall.end)
        solids.append(_rectangle(frame, -ext_start, frame.length + ext_end, frame.thickness / 2))
        cuts.extend(opening_polygon(frame, opening) for opening in wall.openings)
    merged = unary_union(solids)
    bounds = merged.bounds
    if cuts:
        merged = merged.difference(unary_union(cuts))
    if isinstance(merged, Polygon):
        merged = MultiPolygon([merged])
    # Drop specks smaller than 1 mm x 1 mm that boolean operations can leave behind.
    parts = [p for p in getattr(merged, "geoms", []) if p.area > 1.0]
    return LevelGeometry(MultiPolygon(parts), frames, bounds)


def polygon_area_m2(points: list[tuple[float, float]]) -> float:
    return Polygon(points).area / 1_000_000


def polygon_centre(points: list[tuple[float, float]]) -> tuple[float, float]:
    # representative_point() is always inside the shape, even for L-shaped rooms.
    point = Polygon(points).representative_point()
    centroid = Polygon(points).centroid
    if Polygon(points).contains(centroid):
        return (centroid.x, centroid.y)
    return (point.x, point.y)
