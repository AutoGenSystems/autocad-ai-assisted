import pytest

from autocad_ai.plan import Grids, PlanError, check_plan, errors_only, load_plan, parse_plan

from .conftest import DEMO_PLAN


def test_demo_plan_has_no_errors():
    plan = load_plan(DEMO_PLAN)
    assert [level.id for level in plan.levels] == ["GF", "2F"]
    assert errors_only(check_plan(plan)) == []


def test_small_plan_parses(small_plan_text):
    plan = parse_plan(small_plan_text)
    assert plan.project.scale == 50
    assert plan.thickness(plan.levels[0].walls[0]) == 200


def test_typo_in_field_name_is_reported(small_plan_text):
    with pytest.raises(PlanError, match="widht"):
        parse_plan(small_plan_text.replace("width: 900", "widht: 900"))


def test_invalid_yaml_is_reported():
    with pytest.raises(PlanError, match="not valid YAML"):
        parse_plan("project: [unclosed")


def test_opening_longer_than_wall_is_an_error(small_plan_text):
    plan = parse_plan(small_plan_text.replace("offset: 2000, width: 1200", "offset: 3500, width: 1200"))
    errors = errors_only(check_plan(plan))
    assert any("only 4000 mm long" in issue.message for issue in errors)


def test_overlapping_openings_are_an_error(small_plan_text):
    plan = parse_plan(small_plan_text.replace("offset: 2000", "offset: 1000"))
    assert any("overlap" in issue.message for issue in errors_only(check_plan(plan)))


def test_duplicate_level_ids_are_rejected(small_plan_text):
    level = small_plan_text.split("levels:\n", 1)[1]
    with pytest.raises(PlanError, match="unique"):
        parse_plan(small_plan_text + level)


def test_grid_labels_continue_after_z():
    grids = Grids(x=[0], y=[float(i) for i in range(28)])
    assert grids.labels("y")[:3] == ["A", "B", "C"]
    assert grids.labels("y")[26:] == ["AA", "AB"]
    assert grids.labels("x") == ["1"]
