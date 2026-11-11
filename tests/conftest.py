from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEMO_PLAN = REPO / "plans" / "demo-commercial-building.yaml"

SMALL_PLAN = """\
project: {name: Test kiosk, scale: 50}
grids: {x: [0, 4000], y: [0, 3000]}
levels:
  - id: GF
    title: KIOSK PLAN
    walls:
      - start: [0, 0]
        end: [4000, 0]
        thickness: 200
        openings:
          - {type: door, offset: 500, width: 900, swing: left, tag: D1}
          - {type: window, offset: 2000, width: 1200, tag: W1}
      - {start: [4000, 0], end: [4000, 3000], thickness: 200}
      - {start: [4000, 3000], end: [0, 3000], thickness: 200}
      - {start: [0, 3000], end: [0, 0], thickness: 200}
    rooms:
      - {name: KIOSK, boundary: [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}
"""


@pytest.fixture
def small_plan_text() -> str:
    return SMALL_PLAN


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
    """An empty workspace folder used by the MCP server during a test."""
    (tmp_path / "plans").mkdir()
    monkeypatch.setenv("AUTOCAD_AI_WORKSPACE", str(tmp_path))
    return tmp_path
