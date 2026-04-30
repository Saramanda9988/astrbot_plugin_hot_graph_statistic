from __future__ import annotations

from .base import HeatmapTheme, ThemePalette

DARK_THEME = HeatmapTheme(
    name="dark",
    palette=ThemePalette(
        canvas_background="#0d1117",
        canvas_text="#e6edf3",
        canvas_muted="#8b949e",
        card_background="#0d1117",
        card_border="#30363d",
        card_text="#e6edf3",
        card_muted="#8b949e",
        card_preview="#a371f7",
        zero_color="#161b22",
        low_color="#0e4429",
        medium_color="#006d32",
        high_color="#26a641",
        max_color="#39d353",
    ),
)
