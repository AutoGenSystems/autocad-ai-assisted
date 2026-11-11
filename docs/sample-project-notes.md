# Sample project: what was found, and what is still needed

The sample is a set of two DWG drawings for a **two-storey commercial building**. The
goal is to rebuild it as a plan file, so that it can be regenerated, changed and extended
with Claude. This page records how far that got.

> The original DWG files are **not** in this repository. The repository is public, and
> client drawings can contain names, addresses and other private details. Keep them out
> of Git unless you are sure they may be shared.

## What could be read

The files are in AutoCAD 2018 DWG format, last saved by AutoCAD 2024. They were read
with a small, purpose-written reader that unpacks the DWG container and lists its text.
It does not decode geometry; see the next section for why.

| Item | Found |
|---|---|
| Views | Ground floor plan, second floor plan, foundation plan, roof framing plan, front / rear / left / right elevations, a 3D view |
| Ground floor rooms | Lounge, kitchen, service area, stockroom, men's CR, women's CR (CR = comfort room, a toilet) |
| Second floor rooms | Conference room, library / lounge, terrace (plus CRs) |
| Standards | Metric (ISO-25 dimension style), Arial text, ISO A4 sheets, CENTER / HIDDEN linetypes |
| Doors, fixtures, furniture | AutoCAD DesignCenter blocks: dynamic metric doors, toilets, sinks, kitchen range, refrigerator, sofas, tables, desks |
| Layer names (examples) | grid lines, ground / second floor doors and windows, columns, roof, roof slope, elevation, 3D floors and roof |
| 3D | One file contains a large amount of 3D solid data (a 3D model of the building) |

## What could not be read yet, and why

The exact **geometry** is missing: wall positions, door and window positions, and
dimensions. DWG stores these as packed binary data. Decoding it needs a full DWG
library, such as the open-source LibreDWG or the ODA File Converter. In the cloud
sandbox used for this work, the safety checks blocked running downloaded third-party
DWG software, so it was not used.

Because of that, `plans/demo-commercial-building.yaml` uses the **real room list** with
an **assumed layout**. Its title blocks say so. Treat it as a test of the pipeline, not as
the sample design.

## What is needed to rebuild the sample exactly

Any one of these:

1. **A DXF export** (best). In AutoCAD, open the drawing and run `SAVEAS`. Choose
   **AutoCAD 2018 DXF (\*.dxf)** as the file type and save. DXF is AutoCAD's text-based
   exchange format, and this project reads it directly (`autocad-ai inspect file.dxf`).
2. **A PDF of the sheets.** In AutoCAD use `EXPORTPDF`, or plot to "DWG To PDF.pc3". This
   shows the dimensions and room layout, but it is less exact than DXF. With only
   **AutoCAD Web** (browser): upload and open the DWG, open a layout tab, then use the
   `PLOT` command (or the Plot icon at the top right) to create the PDF. AutoCAD Web
   cannot save as DXF.
3. **Permission to run a DWG converter** (LibreDWG, or the ODA File Converter on your own
   PC with `cad_inspect_drawing`).

Then the steps are:

1. Inspect the DXF: layers, block positions (doors, windows, fixtures), grid lines, text.
2. Convert walls, openings, grids, rooms and stairs into a new plan file:
   `plans/sample-commercial-building.yaml`.
3. Build it. Compare it with the original side by side, and in AutoCAD with Autodesk
   Assistant's `checkAutoCADObjects` (see [the Autodesk MCP guide](autodesk-mcp-guide.md)).
4. Later, if wanted: foundation plan, roof framing plan and elevations. These are other
   drawing types that the builder does not make yet.
