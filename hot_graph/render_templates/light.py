from __future__ import annotations

from .base import HeatmapTheme, ThemePalette

LIGHT_THEME = HeatmapTheme(
    name="light",
    palette=ThemePalette(
        canvas_background="#ffffff",
        canvas_text="#1f2328",
        canvas_muted="#656d76",
        card_background="#ffffff",
        card_border="#d0d7de",
        card_text="#24292f",
        card_muted="#57606a",
        card_preview="#8250df",
        zero_color="#ebedf0",
        low_color="#9be9a8",
        medium_color="#40c463",
        high_color="#30a14e",
        max_color="#216e39",
    ),
)
