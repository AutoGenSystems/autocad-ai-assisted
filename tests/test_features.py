"""Builder features used to redraw existing drawings faithfully (synthetic test plans)."""

from collections import Counter

import pytest

from autocad_ai.builder import build_document
from autocad_ai.plan import PlanError, parse_plan

ROOM = """\
project: {{name: t, dimension_unit: {unit}, sheet_orientation: {orientation}}}
levels:
  - id: L
    title: T
    columns: none
    auto_dimensions: {auto}
    walls:
      - start: [0, 0]
        end: [4000, 0]
        thickness: 150
        openings: [{{type: sliding_door, offset: 500, width: 2000}}]
      - {{start: [4000, 0], end: [4000, 3000], thickness: 150}}
      - {{start: [4000, 3000], end: [0, 3000], thickness: 150}}
      - {{start: [0, 3000], end: [0, 0], thickness: 150}}
    stairs:
      - {{start: [1000, 500], width: 900, length: 2000, direction: 90, risers: 9, label: ""}}
      - {{start: [2500, 500], width: 900, length: 2000, direction: 90, risers: 9, label: UP, label_at: [3000, 200]}}
    furniture:
      - {{kind: sofa, at: [2000, 2500], size: [2100, 850], rotation: 180}}
      - {{kind: plant, at: [3500, 2500], size: [600, 600]}}
    lines:
      - {{layer: casework, closed: true, points: [[100, 100], [900, 100], [900, 600], [100, 600]]}}
      - {{layer: railing, points: [[0, 3500], [4000, 3500]]}}
    dimensions:
      - {{kind: horizontal, p1: [0, 0], p2: [4000, 0], at: [0, -800]}}
"""


def build(unit="m", orientation="landscape", auto="false"):
    plan = parse_plan(ROOM.format(unit=unit, orientation=orientation, auto=auto))
    return build_document(plan)


def dimension_texts(doc):
    texts = []
    for dim in doc.modelspace().query("DIMENSION"):
        block = dim.get_geometry_block()
        texts += [e.plain_text() for e in block if e.dxftype() == "MTEXT"]
    return texts


def test_metre_dimensions_use_two_decimals_and_a_point():
    doc, _ = build(unit="m")
    assert dimension_texts(doc) == ["4.00"]


def test_millimetre_dimensions_are_whole_numbers():
    doc, _ = build(unit="mm")
    assert dimension_texts(doc) == ["4000"]


def test_auto_dimensions_can_be_turned_off_and_on():
    doc_off, _ = build(auto="false")
    doc_on, _ = build(auto="true")
    assert len(doc_off.modelspace().query("DIMENSION")) == 1  # only the manual one
    assert len(doc_on.modelspace().query("DIMENSION")) == 3   # plus overall width and depth


def test_sliding_door_furniture_and_lines():
    doc, result = build()
    msp = doc.modelspace()
    inserts = Counter(e.dxf.name for e in msp.query("INSERT"))
    assert inserts["DOOR-SLIDE"] == 1 and result.counts["doors"] == 1
    assert inserts["FURN-SOFA"] == 1 and inserts["FURN-PLANT"] == 1 and result.counts["furniture"] == 2
    sofa = msp.query("INSERT[name=='FURN-SOFA']").first
    assert (sofa.dxf.xscale, sofa.dxf.yscale, sofa.dxf.rotation) == (2100, 850, 180)
    assert sofa.dxf.layer == "A-FURN"
    layers = Counter(e.dxf.layer for e in msp.query("LWPOLYLINE"))
    assert layers["A-FLOR-CASE"] == 1 and layers["A-FLOR-HRAL"] == 1


def test_stair_labels_can_be_omitted_or_placed():
    doc, result = build()
    labels = [e for e in doc.modelspace().query("TEXT") if e.dxf.layer == "A-FLOR-STRS"]
    assert result.counts["stairs"] == 2
    assert [e.dxf.text for e in labels] == ["UP"]
    assert tuple(labels[0].dxf.align_point)[:2] == pytest.approx((3000, 200))


def test_horizontal_dimension_needs_a_line_position():
    with pytest.raises(PlanError, match="need `at`"):
        parse_plan(ROOM.format(unit="m", orientation="landscape", auto="false").replace(", at: [0, -800]", ""))


def test_portrait_sheet_has_a3_portrait_border_and_fits():
    doc, result = build(orientation="portrait")
    assert result.warnings == []
    sheet = doc.paperspace(result.sheets[0])
    border = max(sheet.query("LWPOLYLINE"), key=lambda e: len(list(e.vertices())) and e.dxf.const_width)
    xs = [x for x, y in border.vertices()]
    ys = [y for x, y in border.vertices()]
    assert (min(xs), max(xs), min(ys), max(ys)) == (10, 287, 10, 410)
