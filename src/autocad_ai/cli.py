"""Command line: `autocad-ai build|check|inspect|format`.

Examples (from the repository folder):
    autocad-ai check plans/demo-commercial-building.yaml
    autocad-ai build plans/demo-commercial-building.yaml
    autocad-ai inspect output/demo-commercial-building/demo-commercial-building.dxf
"""

from __future__ import annotations

import argparse
import sys
from importlib import resources
from pathlib import Path

from .inspect_drawing import DrawingError, format_summary, load_drawing, summarize
from .pipeline import build_outputs, format_report
from .plan import PlanError, check_plan, errors_only, load_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autocad-ai", description="Build AutoCAD drawings from plan files.")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build the DXF drawing and PNG previews for a plan")
    build.add_argument("plan", type=Path)
    build.add_argument("-o", "--out", type=Path, help="output folder (default: output/<plan name>)")
    build.add_argument("--no-preview", action="store_true", help="skip the PNG previews")
    check = commands.add_parser("check", help="check a plan for errors")
    check.add_argument("plan", type=Path)
    inspect = commands.add_parser("inspect", help="summarise an existing .dxf (or .dwg with ODA File Converter)")
    inspect.add_argument("drawing", type=Path)
    commands.add_parser("format", help="print the plan file format reference")
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            out = args.out or Path("output") / args.plan.stem
            print(format_report(build_outputs(args.plan, out, previews=not args.no_preview)))
        elif args.command == "check":
            issues = check_plan(load_plan(args.plan))
            print("\n".join(str(issue) for issue in issues) or "No problems found.")
            return 1 if errors_only(issues) else 0
        elif args.command == "inspect":
            print(format_summary(summarize(load_drawing(args.drawing)), args.drawing.name))
        else:
            print(resources.files("autocad_ai").joinpath("plan_format.md").read_text(encoding="utf-8"))
    except (PlanError, DrawingError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
