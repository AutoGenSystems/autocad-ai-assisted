"""Summarise an existing drawing: units, size, layers, blocks and text.

DXF files are read directly. DWG files need the free ODA File Converter installed
on the same computer (https://www.opendesign.com/guestfiles/oda_file_converter);
ezdxf uses it to convert the DWG behind the scenes. Without it, open the DWG in
AutoCAD and use SAVEAS -> "AutoCAD 2018 DXF".
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf import bbox, recover
from ezdxf.document import Drawing

UNIT_NAMES = {0: "unitless", 1: "inches", 2: "feet", 4: "millimetres", 5: "centimetres", 6: "metres"}


class DrawingError(ValueError):
    """The file could not be read as a drawing."""


def load_drawing(path: str | Path) -> Drawing:
    path = Path(path)
    if not path.is_file():
        raise DrawingError(f"No file at {path}")
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        try:
            doc, _auditor = recover.readfile(path)  # tolerant reader, fixes small defects
        except (OSError, ezdxf.DXFStructureError) as exc:
            raise DrawingError(f"Could not read {path.name} as DXF: {exc}") from exc
        return doc
    if suffix == ".dwg":
        from ezdxf.addons import odafc

        if not odafc.is_installed():
            raise DrawingError(
                "Reading DWG needs the free ODA File Converter on this computer. Install it, or open the "
                "file in AutoCAD and use SAVEAS -> 'AutoCAD 2018 DXF (*.dxf)', then inspect the DXF.")
        return odafc.readfile(str(path))
    raise DrawingError("Only .dxf and .dwg files can be inspected.")


def _plain(entity) -> str:
    if entity.dxftype() == "MTEXT":
        return entity.plain_text().replace("\n", " / ")
    return entity.dxf.text


def summarize(doc: Drawing, max_texts: int = 200) -> dict:
    msp = doc.modelspace()
    per_layer: Counter[str] = Counter()
    per_type: Counter[str] = Counter()
    inserts: Counter[str] = Counter()
    texts: list[str] = []
    for entity in msp:
        per_layer[entity.dxf.layer] += 1
        per_type[entity.dxftype()] += 1
        if entity.dxftype() == "INSERT":
            inserts[entity.dxf.name] += 1
        elif entity.dxftype() in ("TEXT", "MTEXT") and len(texts) < max_texts:
            value = _plain(entity).strip()
            if value:
                texts.append(value)
    extents = bbox.extents(msp, fast=True)
    return {
        "dxf_version": doc.acad_release,
        "units": UNIT_NAMES.get(doc.header.get("$INSUNITS", 0), "other"),
        "extents": None if not extents.has_data else {
            "min": [round(extents.extmin.x, 1), round(extents.extmin.y, 1)],
            "max": [round(extents.extmax.x, 1), round(extents.extmax.y, 1)],
            "size": [round(extents.size.x, 1), round(extents.size.y, 1)],
        },
        "entity_count": sum(per_type.values()),
        "entities_by_type": dict(per_type.most_common()),
        "layers": [{"name": layer.dxf.name, "color": layer.dxf.color, "linetype": layer.dxf.linetype,
                    "entities": per_layer.get(layer.dxf.name, 0)} for layer in doc.layers],
        "block_inserts": dict(inserts.most_common()),
        "sheets": [name for name in doc.layouts.names() if name != "Model"],
        "texts": texts,
    }


def format_summary(summary: dict, title: str) -> str:
    """Markdown version of summarize(), for people and for Claude."""
    lines = [f"# {title}", "",
             f"- DXF version: {summary['dxf_version']}", f"- Units: {summary['units']}",
             f"- Entities in model space: {summary['entity_count']}"]
    if summary["extents"]:
        size = summary["extents"]["size"]
        lines.append(f"- Overall size: {size[0]:,.0f} x {size[1]:,.0f} ({summary['units']})")
    lines.append(f"- Sheets (layouts): {', '.join(summary['sheets']) or 'none'}")
    lines += ["", "## Layers (entities in model space)", ""]
    lines += [f"- {l['name']}: {l['entities']}" for l in summary["layers"]]
    lines += ["", "## Entity types", ""]
    lines += [f"- {k}: {v}" for k, v in summary["entities_by_type"].items()]
    lines += ["", "## Block inserts", ""]
    lines += [f"- {k}: {v}" for k, v in summary["block_inserts"].items()] or ["- none"]
    lines += ["", "## Text in model space", ""]
    lines += [f"- {t}" for t in summary["texts"]] or ["- none"]
    return "\n".join(lines)
