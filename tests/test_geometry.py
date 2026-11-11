import pytest

from autocad_ai.geometry import level_geometry, polygon_area_m2
from autocad_ai.plan import parse_plan


def _plan(walls_yaml: str):
    return parse_plan(f"project: {{name: t}}\nlevels:\n  - id: L\n    title: T\n    walls:\n{walls_yaml}")


def test_l_corner_closes_without_gap_or_overlap():
    plan = _plan(
        "      - {start: [0, 0], end: [4000, 0], thickness: 200}\n"
        "      - {start: [4000, 0], end: [4000, 3000], thickness: 200}\n")
    geom = level_geometry(plan, plan.levels[0])
    assert len(geom.walls.geoms) == 1
    # 4100 x 200 + 3100 x 200 minus the 200 x 200 square they share.
    assert geom.walls.area == pytest.approx(1_400_000)
    assert len(geom.walls.geoms[0].interiors) == 0


def test_t_junction_merges_into_one_outline():
    plan = _plan(
        "      - {start: [0, 0], end: [6000, 0], thickness: 200}\n"
        "      - {start: [3000, 0], end: [3000, 3000], thickness: 150}\n")
    geom = level_geometry(plan, plan.levels[0])
    assert len(geom.walls.geoms) == 1
    # The branch is extended by 100 (half of the 200 wall) into the main wall: no gap.
    assert geom.walls.area == pytest.approx(6000 * 200 + 2900 * 150)


def test_opening_cuts_its_wall_in_two():
    plan = _plan(
        "      - start: [0, 0]\n        end: [4000, 0]\n"
        "        openings: [{type: door, offset: 1000, width: 900}]\n")
    geom = level_geometry(plan, plan.levels[0])
    assert len(geom.walls.geoms) == 2
    assert geom.walls.area == pytest.approx((4000 - 900) * 150)


def test_room_area_in_square_metres():
    assert polygon_area_m2([(0, 0), (4000, 0), (4000, 3500), (0, 3500)]) == pytest.approx(14.0)
