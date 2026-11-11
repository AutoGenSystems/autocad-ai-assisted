"""Talk to the MCP server the way Claude does, through an in-process MCP client."""

import asyncio
import shutil

from mcp import Client

from autocad_ai.mcp_server import mcp

from .conftest import DEMO_PLAN

EXPECTED_TOOLS = {
    "cad_list_plans", "cad_get_plan_format", "cad_get_plan", "cad_save_plan", "cad_check_plan",
    "cad_build_drawing", "cad_preview_drawing", "cad_inspect_drawing", "cad_open_in_autocad",
}


def call(tool: str, arguments: dict | None = None):
    async def run():
        async with Client(mcp) as client:
            return await client.call_tool(tool, arguments or {})
    return asyncio.run(run())


def text_of(result) -> str:
    return "\n".join(getattr(block, "text", "") for block in result.content)


def test_all_tools_are_listed():
    async def run():
        async with Client(mcp) as client:
            return await client.list_tools()
    tools = asyncio.run(run()).tools
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    read_only = {tool.name for tool in tools if tool.annotations and tool.annotations.read_only_hint}
    assert {"cad_list_plans", "cad_get_plan", "cad_inspect_drawing"} <= read_only
    assert "cad_save_plan" not in read_only


def test_save_build_preview_and_inspect(workspace, small_plan_text):
    saved = call("cad_save_plan", {"name": "kiosk", "plan_yaml": small_plan_text})
    assert not saved.is_error, text_of(saved)
    assert (workspace / "plans" / "kiosk.yaml").is_file()
    assert "kiosk" in text_of(call("cad_list_plans"))

    built = call("cad_build_drawing", {"name": "kiosk"})
    assert not built.is_error, text_of(built)
    dxf = workspace / "output" / "kiosk" / "kiosk.dxf"
    assert dxf.is_file() and "KIOSK: 12.00 m2" in text_of(built)

    preview = call("cad_preview_drawing", {"name": "kiosk", "sheet": "GF"})
    assert not preview.is_error, text_of(preview)
    assert preview.content[0].type == "image" and preview.content[0].mime_type == "image/png"

    summary = text_of(call("cad_inspect_drawing", {"path": "output/kiosk/kiosk.dxf"}))
    assert "A-WALL" in summary and "DOOR-1L: 1" in summary and "KIOSK" in summary


def test_save_refuses_errors_and_overwrites_only_when_asked(workspace, small_plan_text):
    bad = small_plan_text.replace("offset: 2000", "offset: 3900")
    refused = call("cad_save_plan", {"name": "kiosk", "plan_yaml": bad})
    assert refused.is_error and "Not saved" in text_of(refused)
    assert not (workspace / "plans" / "kiosk.yaml").exists()

    assert not call("cad_save_plan", {"name": "kiosk", "plan_yaml": small_plan_text}).is_error
    again = call("cad_save_plan", {"name": "kiosk", "plan_yaml": small_plan_text})
    assert again.is_error and "overwrite=true" in text_of(again)
    assert not call("cad_save_plan", {"name": "kiosk", "plan_yaml": small_plan_text,
                                      "overwrite": True}).is_error


def test_unsafe_or_unknown_names_are_rejected(workspace, small_plan_text):
    escape = call("cad_get_plan", {"name": "../../etc/passwd"})
    assert escape.is_error and "letters, digits" in text_of(escape)
    assert not call("cad_save_plan", {"name": "kiosk", "plan_yaml": small_plan_text}).is_error
    sheet_escape = call("cad_preview_drawing", {"name": "kiosk", "sheet": "../../../x"})
    assert sheet_escape.is_error and "level id" in text_of(sheet_escape)
    missing = call("cad_check_plan", {"name": "nope"})
    assert missing.is_error and "cad_list_plans" in text_of(missing)


def test_check_and_format_tools(workspace):
    shutil.copy(DEMO_PLAN, workspace / "plans" / "demo.yaml")
    assert "no problems" in text_of(call("cad_check_plan", {"name": "demo"}))
    assert "Plan file format" in text_of(call("cad_get_plan_format"))
