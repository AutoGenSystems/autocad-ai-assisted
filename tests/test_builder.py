from collections import Counter

import ezdxf
import pytest

from autocad_ai.builder import LAYERS, build_document
from autocad_ai.pipeline import build_outputs
from autocad_ai.plan import PlanError, load_plan, parse_plan

from .conftest import DEMO_PLAN


@pytest.fixture(scope="module")
def demo():
    plan = load_plan(DEMO_PLAN)
    doc, result = build_document(plan)
    return plan, doc, result


def _openings(plan, kind):
    return sum(o.type == kind for level in plan.levels for w in level.walls for o in w.openings)


def test_demo_counts_match_the_plan(demo):
    plan, doc, result = demo
    inserts = Counter(e.dxf.name for e in doc.modelspace().query("INSERT"))
    assert inserts["DOOR-1L"] == _openings(plan, "door")
    assert inserts["DOOR-2L"] == _openings(plan, "double_door")
    assert inserts["WINDOW"] == _openings(plan, "window") == result.counts["windows"]
    fixtures = sum(len(level.fixtures) for level in plan.levels)
    assert sum(n for name, n in inserts.items() if name.startswith("FIX-")) == fixtures
    assert result.counts["levels"] == 2


def test_demo_has_layers_dimensions_and_sheets(demo):
    _plan, doc, result = demo
    assert set(LAYERS) <= {layer.dxf.name for layer in doc.layers}
    assert len(doc.modelspace().query("DIMENSION")) >= 6
    assert result.sheets == ["A-101 GROUND FLOOR PLAN", "A-102 SECOND FLOOR PLAN"]
    assert set(doc.layouts.names()) == {"Model", *result.sheets}
    for sheet in result.sheets:  # each sheet has a viewport onto model space
        assert len(doc.paperspace(sheet).query("VIEWPORT")) >= 1
    assert doc.header["$INSUNITS"] == 4  # millimetres


def test_demo_room_areas(demo):
    _plan, _doc, result = demo
    areas = {(level, room): area for level, room, area in result.room_areas}
    assert areas[("GF", "LOUNGE")] == pytest.approx(66.0)
    assert areas[("2F", "CONFERENCE ROOM")] == pytest.approx(39.0)


def test_saved_dxf_passes_audit(tmp_path):
    outputs = build_outputs(DEMO_PLAN, tmp_path)
    doc = ezdxf.readfile(outputs.result.dxf_path)
    auditor = doc.audit()
    assert auditor.errors == [] and auditor.fixes == []
    assert set(outputs.images) == {"model", "GF", "2F"}
    assert all(path.stat().st_size > 10_000 for path in outputs.images.values())


@pytest.mark.parametrize("hinge,swing,expect_side", [
    ("start", "left", +1), ("start", "right", -1), ("end", "left", +1), ("end", "right", -1)])
def test_door_swing_ends_up_on_the_requested_side(hinge, swing, expect_side):
    # Wall along +x, so "left" is +y. The door sits at x 1000..1900.
    plan = parse_plan(f"""
project: {{name: t}}
levels:
  - id: L
    title: T
    walls:
      - start: [0, 0]
        end: [4000, 0]
        openings: [{{type: door, offset: 1000, width: 900, hinge: {hinge}, swing: {swing}}}]
""")
    doc, _ = build_document(plan)
    door = doc.modelspace().query("INSERT[name=='DOOR-1L']").first
    arc = next(e for e in door.virtual_entities() if e.dxftype() == "ARC")
    points = list(arc.flattening(sagitta=1.0))  # points along the swing path, world coordinates
    mid = points[len(points) // 2]
    assert (mid.y > 0) == (expect_side > 0)
    assert all(1000 - 1 <= p.x <= 1900 + 1 for p in points)  # the swing stays over the opening
    hinge_x = 1000 if hinge == "start" else 1900
    assert door.dxf.insert.x == pytest.approx(hinge_x)  # hinge on the requested jamb
    assert abs(arc.dxf.radius) == pytest.approx(900)


def test_sheet_names_are_valid_autocad_layout_names(small_plan_text):
    plan = parse_plan(small_plan_text.replace("title: KIOSK PLAN", 'title: "ROOF/DECK: PLAN"')
                      .replace("{name: Test kiosk,", '{name: Test kiosk, notes: ["see C:\\\\x {a}"],'))
    doc, result = build_document(plan)
    assert result.sheets == ["A-101 ROOF-DECK- PLAN"]
    notes = doc.paperspace(result.sheets[0]).query("MTEXT").first
    assert "see C:\\x {a}" in notes.plain_text()  # shown literally, not as MTEXT codes


def test_level_too_big_for_a3_gives_a_warning():
    plan = parse_plan("""
project: {name: long shed, scale: 100}
levels:
  - id: L
    title: SHED
    walls: [{start: [0, 0], end: [60000, 0], thickness: 200}]
""")
    _doc, result = build_document(plan)
    assert any("does not fit an A3 sheet" in warning for warning in result.warnings)


def test_plan_with_errors_is_not_built(small_plan_text):
    plan = parse_plan(small_plan_text.replace("offset: 2000", "offset: 3900"))
    with pytest.raises(PlanError, match="errors"):
        build_document(plan)
