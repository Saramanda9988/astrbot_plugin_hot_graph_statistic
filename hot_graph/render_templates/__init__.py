from __future__ import annotations

from .base import BODY_FONT_SIZE, META_FONT_SIZE, TITLE_FONT_SIZE, HeatmapTheme, draw_heatmap_image, render_texts
from .dark import DARK_THEME
from .light import LIGHT_THEME

DEFAULT_THEME_NAME = "light"
THEMES: dict[str, HeatmapTheme] = {
    LIGHT_THEME.name: LIGHT_THEME,
    DARK_THEME.name: DARK_THEME,
}


def get_theme(theme_name: str | None) -> HeatmapTheme:
    normalized = (theme_name or DEFAULT_THEME_NAME).strip().lower() or DEFAULT_THEME_NAME
    return THEMES.get(normalized, LIGHT_THEME)


def get_theme_names() -> tuple[str, ...]:
    return tuple(THEMES.keys())


__all__ = [
    "BODY_FONT_SIZE",
    "DEFAULT_THEME_NAME",
    "META_FONT_SIZE",
    "TITLE_FONT_SIZE",
    "HeatmapTheme",
    "draw_heatmap_image",
    "get_theme",
    "get_theme_names",
    "render_texts",
]
