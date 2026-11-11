# Autodesk MCP servers: what exists and how to connect (checked November 2026)

**MCP** (Model Context Protocol) is the standard way an AI app such as Claude calls
tools in another program. An **MCP server** is the program that offers those tools,
for example "list the layers in this drawing".

This page records what Autodesk offers today, verified against Autodesk's own
documentation (see [Sources](#sources)), and how each piece fits this project.

## Short answer

- Autodesk has **six official MCP servers**. One is for AutoCAD.
- The **AutoCAD MCP server** works inside **Autodesk Assistant** (the AI panel built into
  AutoCAD). In plain AutoCAD it can **read, analyse, select and zoom**, and manage layers
  and system variables. It **cannot draw new walls, doors or lines.** Autodesk lists
  Autodesk Assistant as its only supported AI client.
- So, today, **no official Autodesk MCP server lets Claude create an AutoCAD drawing.**
  This repository fills that gap: Claude writes a plan file, and our builder produces the
  real AutoCAD drawing (DXF). Autodesk's AutoCAD MCP is still useful for **checking**
  that drawing once it is open in AutoCAD.

## The six official servers

| Server | Runs | Stage | Works with Claude? | Creates geometry? |
|---|---|---|---|---|
| AutoCAD and Civil 3D | Local, inside AutoCAD (Windows) | Tech Preview (public beta) | Autodesk Assistant only (see the experiment below) | No in AutoCAD; Civil 3D can edit some properties and styles |
| Product Help | Remote (Autodesk cloud) | General availability | **Yes** (Claude connector directory) | Not applicable: searches documentation |
| Revit | Local, Revit 2027 add-on | Tech Preview | **Yes** (Claude Desktop) | No: read-focused in the documentation we found |
| Fusion | Local, inside Fusion | General availability | **Yes** (Claude Desktop) | Yes, for Fusion 3D models (not AutoCAD) |
| Fusion Data | Remote | General availability | Yes (Autodesk sign-in) | No: project administration |
| Fusion Compute | Remote | Public beta | Yes (Autodesk sign-in) | Yes, for Fusion (cloud) |

## 1. Autodesk Product Help MCP (connect this one to Claude now)

It searches Autodesk's help for more than 110 products. It is free and needs no sign-in.
It is how this project's research was done.

- Endpoint: `https://developer.api.autodesk.com/knowledge/public/v1/mcp`
- Tools: `get_available_products`, `search_help_content`
- Note: the `locale` value uses an underscore, for example `en_US` (not `en-US`).

**Claude Desktop or claude.ai**

1. Open **Settings**, then **Connectors**.
2. Click **Browse connectors** and search for **Autodesk Product Help**.
3. Click **Connect**. There is no sign-in.
4. Check: start a chat and ask *"Search Autodesk help for how to start the AutoCAD MCP server."*

**Claude Code** (run in a terminal):

```bash
claude mcp add --transport http autodesk-help https://developer.api.autodesk.com/knowledge/public/v1/mcp
```

Check it with `claude mcp list`. It should show `autodesk-help` as `✔ Connected`.

## 2. AutoCAD and Civil 3D MCP server (inside AutoCAD)

**What you need**

- AutoCAD (or Civil 3D) **on Windows**, in a release that has **Autodesk Assistant**.
  Autodesk's support articles mention Autodesk Assistant in AutoCAD 2026 and 2027.
  The sample drawings were last saved by AutoCAD 2024, which probably does not have it.
  If you do not see an Autodesk Assistant panel, update AutoCAD.
- **Tech Preview turned on.** In Autodesk Assistant, click the **Settings** (gear) icon
  and switch **Tech Preview** on.

**Start it and check it**

1. Open a drawing in AutoCAD.
2. On the command line, type `MCPHTTPSTART` and press Enter. AutoCAD picks a free port
   between 5001 and 5050 and prints the server address, for example
   `http://localhost:5001/mcp`, plus the enabled tools.
3. In Autodesk Assistant ask: *"What layers are in this drawing?"* It should answer with
   the real layers of your open drawing.
4. `MCPCONFIG` shows the tool configuration. `MCPHTTPSTOP` stops the server.

**Its seven tools**

| Tool | What it does | In plain AutoCAD? |
|---|---|---|
| discoverAutoCADTypes | describes object types and their fields; call it first | yes |
| queryAutoCADObjects | lists objects and properties, with filters | yes |
| aggregateAutoCADObjects | counts, sums, min/max, grouped (for example per layer) | yes |
| manipulateDrawingCanvas | select, zoom, "show me" | yes |
| checkAutoCADObjects | compares the drawing with a template drawing | yes |
| updateAutoCADObjects | updates slope analysis data on Civil 3D surfaces (2027.1+) | Civil 3D only |
| civil3dQueryModifyStyles | reads and changes Civil 3D styles | Civil 3D only |

The September 2026 update (version 26.0.516.6958) also added drawing-reference queries
(xrefs, blocks), **layer operations** (show or hide layers, create and delete eligible
layers, change layer properties such as colour, set the current layer, move objects
between layers) and reading and setting system variables.

**How this helps with the drawings from this project.** Open a generated DXF in AutoCAD
and ask Autodesk Assistant, for example:

- *"How many objects are on each layer?"* (the counts should match the build report)
- *"How many DOOR-1L and WINDOW blocks are in this drawing?"*
- *"Compare this drawing to C:\Projects\reference.dwg and list the differences."* This
  uses `checkAutoCADObjects`, a good way to compare a rebuilt plan with the original.

### Experiment: connecting Claude Code to the AutoCAD MCP server

Because `MCPHTTPSTART` serves MCP over local HTTP, Claude Code on the same PC can try to
connect to it. **Autodesk does not list Claude as a supported client, so this may not
work, and it may stop working in a future update.** Even when it works, the tools in
plain AutoCAD are read-only.

```bash
claude mcp add --transport http autocad-live http://localhost:5001/mcp
```

Use the address that `MCPHTTPSTART` printed. The port can differ.

## 3. Revit and Fusion (when you might use them instead)

- **Revit Public MCP Server**: an add-on for Revit 2027 that Claude Desktop can use, to
  query a building model, report on doors and walls, or export views. Use it if your
  architectural work moves to Revit (BIM). It is read-focused in the documentation we found.
- **Fusion MCP**: lets Claude Desktop model in Fusion (3D mechanical CAD). It is the most
  capable official server, but Fusion is not a 2D drafting tool for building plans.

## 4. Community AutoCAD MCP servers

Several unofficial open-source projects drive AutoCAD from AI tools, mostly through
AutoCAD's COM automation or AutoLISP. Autodesk does not provide or support them. They run
with full access to your PC, so review the code and the author before installing one.
This repository deliberately avoids that route: it only writes DXF files, which AutoCAD
opens like any other drawing.

## Sources

- [Autodesk MCP Server help (index of all servers)](https://help.autodesk.com/view/ADSKMCP/ENU/)
- [Autodesk AutoCAD and Civil 3D MCP Server](https://help.autodesk.com/view/ADSKMCP/ENU/?guid=ADSKMCP_AutoCADCivil3DMcp_autodesk_autocad_civil_3d_mcp_html), with its [tools](https://help.autodesk.com/view/ADSKMCP/ENU/?guid=autocadcivil3dmcp_tools) and [release notes](https://help.autodesk.com/view/ADSKMCP/ENU/?guid=autocadcivil3dmcp_relnotes)
- [Autodesk Product Help MCP Server](https://help.autodesk.com/view/ADSKMCP/ENU/?guid=ADSKMCP_ProductHelpMcp_autodesk_product_help_mcp_server_html)
- [Authentication and access](https://help.autodesk.com/view/ADSKMCP/ENU/?guid=ADSKMCP_CommonContent_authentication_and_access_html) and [Managing your MCP connection](https://help.autodesk.com/view/ADSKMCP/ENU/?guid=ADSKMCP_CommonContent_managing_your_mcp_connection_html)
- [Introducing the Revit Public MCP Server (Autodesk blog, June 2026)](https://www.autodesk.com/blogs/aec/2026/06/17/revit-public-mcp-server/)
- [How to disable the Autodesk Assistant in AutoCAD products (Autodesk support)](https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/How-to-disable-the-Autodesk-Assistant-in-AutoCAD-products.html)
- [Claude Code: connect MCP servers](https://code.claude.com/docs/en/mcp)
- [Connect Claude Desktop to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers)

The `MCPHTTPSTART` / `MCPHTTPSTOP` steps and the Tech Preview requirement come from the
newest version of the AutoCAD MCP page, as returned by Autodesk's Product Help MCP server.
The public web page may lag behind it.
