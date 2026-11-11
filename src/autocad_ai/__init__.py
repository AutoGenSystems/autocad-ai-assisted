"""autocad-ai: describe a building plan in a small YAML file, get a real AutoCAD drawing.

Pipeline (each step is its own module):

    plan file (.yaml)  --plan.py-->  validated Plan object
    Plan  --geometry.py-->  wall outlines with door/window gaps
    Plan + geometry  --builder.py-->  DXF drawing (opens in AutoCAD, save it as DWG)
    DXF  --preview.py-->  PNG images, so people and AI can check the result
    any DXF/DWG  --inspect_drawing.py-->  summary of layers, blocks, text

mcp_server.py exposes all of this to Claude through the Model Context Protocol (MCP).
"""

__version__ = "0.1.0"
