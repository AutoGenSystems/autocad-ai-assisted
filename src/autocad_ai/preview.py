"""Render a drawing (model space or one sheet) to a PNG image.

Uses ezdxf's drawing add-on with matplotlib, so no AutoCAD is needed. The image
looks like a monochrome plot: black lines with their real lineweights on white.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files only; never try to open a window

from ezdxf.addons.drawing import matplotlib as dxf_matplotlib  # noqa: E402
from ezdxf.addons.drawing.config import (  # noqa: E402
    BackgroundPolicy,
    ColorPolicy,
    Configuration,
    LineweightPolicy,
)
from ezdxf.document import Drawing  # noqa: E402

PRINT_LIKE = Configuration(
    background_policy=BackgroundPolicy.WHITE,
    color_policy=ColorPolicy.BLACK,
    lineweight_policy=LineweightPolicy.ABSOLUTE,
    lineweight_scaling=1.0,
)


def save_png(doc: Drawing, path: str | Path, sheet: str | None = None,
             size_inches: tuple[float, float] = (16.5, 11.7), dpi: int = 110) -> Path:
    """Write a PNG of model space (sheet=None) or of the named paper-space sheet."""
    layout = doc.modelspace() if sheet is None else doc.paperspace(sheet)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dxf_matplotlib.qsave(layout, path, bg="#FFFFFF", dpi=dpi, config=PRINT_LIKE, size_inches=size_inches)
    return path
