"""One call that does a full build: plan file -> DXF + PNG previews + a short report.

Shared by the command line (cli.py) and the MCP server (mcp_server.py), so both
produce exactly the same files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .builder import BuildResult, build_document
from .plan import load_plan
from .preview import save_png


@dataclass
class BuildOutputs:
    result: BuildResult
    images: dict[str, Path]  # "model" or a level id -> PNG path


def build_outputs(plan_path: str | Path, out_dir: str | Path, previews: bool = True) -> BuildOutputs:
    """Build `<out_dir>/<plan name>.dxf` and, optionally, one PNG per sheet plus a model overview."""
    plan_path, out_dir = Path(plan_path), Path(out_dir)
    plan = load_plan(plan_path)
    doc, result = build_document(plan)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.dxf_path = out_dir / f"{plan_path.stem}.dxf"
    doc.saveas(result.dxf_path)
    images: dict[str, Path] = {}
    if previews:
        images["model"] = save_png(doc, out_dir / f"{plan_path.stem}-model.png")
        for level, sheet in zip(plan.levels, result.sheets):
            images[level.id] = save_png(doc, out_dir / f"{plan_path.stem}-{level.id}.png", sheet=sheet)
    return BuildOutputs(result, images)


def format_report(outputs: BuildOutputs) -> str:
    """Markdown summary of a build, for the terminal and for Claude."""
    result = outputs.result
    counts = ", ".join(f"{value} {key}" for key, value in result.counts.items() if value)
    lines = [f"Built {result.dxf_path}", "", f"Contents: {counts}", "",
             "Sheets (paper space layouts):"]
    lines += [f"- {sheet}" for sheet in result.sheets]
    if result.room_areas:
        lines += ["", "Room areas (to wall centre lines):"]
        lines += [f"- {level} {room}: {area:.2f} m2" for level, room, area in result.room_areas]
    if outputs.images:
        lines += ["", "Preview images:"]
        lines += [f"- {key}: {path}" for key, path in outputs.images.items()]
    if result.warnings:
        lines += ["", "Warnings:"]
        lines += [f"- {warning}" for warning in result.warnings]
    lines += ["", "Open the .dxf in AutoCAD (or AutoCAD LT / AutoCAD Web), then SAVEAS to keep a .dwg."]
    return "\n".join(lines)
