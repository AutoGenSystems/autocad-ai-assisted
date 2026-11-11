"""MCP server: lets Claude create, check, build, preview and inspect AutoCAD plans.

MCP (Model Context Protocol) is the standard way an AI app such as Claude Desktop or
Claude Code calls tools on your computer. Claude starts this program itself once it
is configured (see README.md); it talks to it over stdio (standard input/output).

Files live in a *workspace* folder:
    <workspace>/plans/<name>.yaml        plan files (what Claude writes)
    <workspace>/output/<name>/...        generated DXF + PNG files
Choose the folder with the AUTOCAD_AI_WORKSPACE environment variable. Without it the
server uses the current folder (if it has a plans/ folder), else this repository.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from importlib import resources
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .inspect_drawing import DrawingError, format_summary, load_drawing, summarize
from .pipeline import build_outputs, format_report
from .plan import PlanError, check_plan, load_plan, parse_plan

INSTRUCTIONS = """\
Builds 2D architectural floor plans as AutoCAD drawings (DXF) from small YAML plan files.
Typical workflow:
1. cad_get_plan_format - read the plan format once (units are millimetres).
2. cad_list_plans / cad_get_plan - see existing plans; cad_save_plan - create or update one.
3. cad_check_plan - fix every error it reports.
4. cad_build_drawing - writes the DXF (opens in AutoCAD; SAVEAS for DWG) and PNG previews.
5. cad_preview_drawing - look at the result and correct the plan if anything is off.
6. cad_open_in_autocad - open the DXF in AutoCAD (Windows).
To study an existing drawing (e.g. a reference to re-create), use cad_inspect_drawing.
"""

mcp = MCPServer("autocad_ai_mcp", title="AutoCAD AI plan builder", instructions=INSTRUCTIONS,
                version=__version__)
# ezdxf reports routine steps ("creating ACAD_COLOR dictionary") at INFO level; keep the
# client's MCP log readable by showing only its warnings and errors.
logging.getLogger("ezdxf").setLevel(logging.WARNING)

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                            open_world_hint=False)
WRITES_OUTPUT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                open_world_hint=False)


def workspace() -> Path:
    configured = os.environ.get("AUTOCAD_AI_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    if (Path.cwd() / "plans").is_dir():
        return Path.cwd()
    repository = Path(__file__).resolve().parents[2]  # src/autocad_ai/ -> repository root
    if (repository / "plans").is_dir():
        return repository
    return Path.home() / "autocad-ai-workspace"


def _plan_path(name: str) -> Path:
    # Only simple names: this also stops paths such as ../../somewhere.
    if not NAME_PATTERN.match(name):
        raise ToolError("Plan names may only use letters, digits, '-' and '_' (max 64 characters), "
                        "for example 'corner-shop'.")
    return workspace() / "plans" / f"{name}.yaml"


def _existing_plan(name: str) -> Path:
    path = _plan_path(name)
    if not path.is_file():
        raise ToolError(f"There is no plan named '{name}'. Call cad_list_plans to see the plans.")
    return path


def _output_dir(name: str) -> Path:
    return workspace() / "output" / name


def _issues_text(issues) -> str:
    return "\n".join(f"- {issue}" for issue in issues)


@mcp.tool(annotations=READ_ONLY)
def cad_list_plans() -> str:
    """List the plan files in the workspace, with each plan's project name and levels."""
    folder = workspace() / "plans"
    files = sorted(folder.glob("*.yaml")) if folder.is_dir() else []
    if not files:
        return f"No plans in {folder} yet. Read cad_get_plan_format, then create one with cad_save_plan."
    lines = [f"Workspace: {workspace()}", ""]
    for file in files:
        try:
            plan = load_plan(file)
            levels = ", ".join(f"{level.id} ({level.title})" for level in plan.levels)
            lines.append(f"- {file.stem}: {plan.project.name}; levels: {levels}")
        except PlanError:
            lines.append(f"- {file.stem}: has format errors, run cad_check_plan")
    return "\n".join(lines)


@mcp.tool(annotations=READ_ONLY)
def cad_get_plan_format() -> str:
    """Return the plan file reference: every field, the conventions (millimetres, wall
    direction, door swing) and a complete example. Read it before writing a plan."""
    return resources.files("autocad_ai").joinpath("plan_format.md").read_text(encoding="utf-8")


@mcp.tool(annotations=READ_ONLY)
def cad_get_plan(name: str) -> str:
    """Return the YAML text of the plan `name` (as listed by cad_list_plans)."""
    return _existing_plan(name).read_text(encoding="utf-8")


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True,
                                      open_world_hint=False))
def cad_save_plan(name: str, plan_yaml: str, overwrite: bool = False) -> str:
    """Check plan YAML and save it as plans/<name>.yaml. Nothing is saved when the plan has
    errors; the errors are returned so they can be fixed. Use overwrite=true to replace an
    existing plan (its previous content is lost)."""
    path = _plan_path(name)
    if path.exists() and not overwrite:
        raise ToolError(f"A plan named '{name}' already exists. Pass overwrite=true to replace it, "
                        "or choose another name.")
    try:
        plan = parse_plan(plan_yaml)
    except PlanError as exc:
        raise ToolError(f"Not saved. {exc}") from exc
    issues = check_plan(plan)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise ToolError("Not saved. Fix these errors first:\n" + _issues_text(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan_yaml, encoding="utf-8")
    message = f"Saved {path}."
    if issues:
        message += "\nWarnings (the plan can still be built):\n" + _issues_text(issues)
    return message + "\nNext: cad_build_drawing."


@mcp.tool(annotations=READ_ONLY)
def cad_check_plan(name: str) -> str:
    """Check a saved plan for format errors and design problems such as an opening longer
    than its wall or two openings that overlap."""
    try:
        plan = load_plan(_existing_plan(name))
    except PlanError as exc:
        return str(exc)
    issues = check_plan(plan)
    if not issues:
        return f"Plan '{name}' has no problems."
    return f"Plan '{name}':\n" + _issues_text(issues)


@mcp.tool(annotations=WRITES_OUTPUT)
def cad_build_drawing(name: str) -> str:
    """Build the AutoCAD drawing for a plan: output/<name>/<name>.dxf (one A3 sheet per level)
    plus PNG previews. Returns the file paths, element counts and room areas."""
    plan_path = _existing_plan(name)
    try:
        outputs = build_outputs(plan_path, _output_dir(name))
    except PlanError as exc:
        raise ToolError(f"{exc}\nFix the plan with cad_save_plan, then build again.") from exc
    return format_report(outputs)


@mcp.tool(annotations=WRITES_OUTPUT)
def cad_preview_drawing(name: str, sheet: str = "model") -> Image:
    """Return a PNG picture of the built drawing, to check it visually. `sheet` is 'model'
    (all levels side by side) or a level id such as 'GF' (that level's A3 sheet). The
    drawing is (re)built first if the plan changed since the last build."""
    plan_path = _existing_plan(name)
    if not NAME_PATTERN.match(sheet):  # `sheet` becomes part of a file name
        raise ToolError("`sheet` must be 'model' or a level id such as 'GF'.")
    out_dir = _output_dir(name)
    image = out_dir / f"{name}-{sheet}.png"
    dxf = out_dir / f"{name}.dxf"
    if not image.is_file() or not dxf.is_file() or dxf.stat().st_mtime < plan_path.stat().st_mtime:
        try:
            outputs = build_outputs(plan_path, out_dir)
        except PlanError as exc:
            raise ToolError(str(exc)) from exc
        if sheet not in outputs.images:
            raise ToolError(f"Unknown sheet '{sheet}'. Use one of: {', '.join(outputs.images)}.")
        image = outputs.images[sheet]
    return Image(path=image)


@mcp.tool(annotations=READ_ONLY)
def cad_inspect_drawing(path: str, max_texts: int = 100) -> str:
    """Summarise an existing AutoCAD drawing: units, overall size, layers with entity counts,
    block usage (doors, fixtures...) and the text it contains. Accepts .dxf, and .dwg when the
    free ODA File Converter is installed. Relative paths are inside the workspace."""
    file = Path(path).expanduser()
    if not file.is_absolute():
        file = workspace() / file
    try:
        doc = load_drawing(file)
    except DrawingError as exc:
        raise ToolError(str(exc)) from exc
    return format_summary(summarize(doc, max_texts=max(1, min(max_texts, 1000))), file.name)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                                      open_world_hint=False))
def cad_open_in_autocad(name: str) -> str:
    """Open the plan's built DXF in the program Windows uses for .dxf files (normally AutoCAD).
    Build it first with cad_build_drawing. Windows only."""
    dxf = _output_dir(name) / f"{name}.dxf"
    if not dxf.is_file():
        raise ToolError(f"No drawing built for '{name}' yet. Call cad_build_drawing first.")
    if sys.platform != "win32":
        raise ToolError(f"Opening AutoCAD automatically only works on Windows. The file is at {dxf}.")
    os.startfile(dxf)  # noqa: S606 - opens the file with its associated program, like a double-click
    return f"Asked Windows to open {dxf}. In AutoCAD use SAVEAS to keep it as a DWG."


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
