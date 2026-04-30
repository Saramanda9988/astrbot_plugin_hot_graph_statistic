from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import uuid4

from io import BytesIO

from PIL import Image, ImageFont

from .models import ActivitySnapshot
from .render_templates import (
    BODY_FONT_SIZE,
    DEFAULT_THEME_NAME,
    META_FONT_SIZE,
    TITLE_FONT_SIZE,
    draw_heatmap_image,
    get_theme,
    render_texts as _render_texts,
)
from .utils import ensure_directory

_KNOWN_FONT_FILENAMES = (
    "LXGWWenKai-Regular.ttf",
    "LXGWWenKaiLite-Regular.ttf",
    "lxgwwenkai-regular.ttf",
    "msyh.ttc",
    "msyhbd.ttc",
    "simhei.ttf",
    "simsun.ttc",
    "PingFang.ttc",
    "Hiragino Sans GB.ttc",
    "STHeiti Medium.ttc",
    "NotoSansCJK-Regular.ttc",
    "NotoSansCJK-Regular.otf",
    "NotoSansSC-Regular.otf",
    "SourceHanSansCN-Regular.otf",
    "SourceHanSansSC-Regular.otf",
    "wqy-zenhei.ttc",
    "wqy-microhei.ttc",
    "Deng.ttf",
    "Dengb.ttf",
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
    "Arial.ttf",
)
_KNOWN_FONT_PATTERNS = (
    "LXGW*.ttf",
    "lxgw*.ttf",
    "NotoSansCJK-*.ttc",
    "NotoSansCJK-*.otf",
    "NotoSansSC-*.otf",
    "SourceHanSans*-Regular.otf",
    "SourceHanSans*-Normal.otf",
    "wqy-*.ttc",
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
)
logger = logging.getLogger(__name__)


class HeatmapRenderer:
    def __init__(
        self,
        render_dir: Path,
        font_path: Path | None = None,
        render_scale: int = 2,
        render_theme: str = DEFAULT_THEME_NAME,
    ) -> None:
        self.render_dir = render_dir
        ensure_directory(self.render_dir)
        self.font_path = _resolve_font_path(font_path)
        self.render_scale = max(int(render_scale), 1)
        requested_theme = (render_theme or DEFAULT_THEME_NAME).strip().lower() or DEFAULT_THEME_NAME
        self.theme = get_theme(requested_theme)
        self.render_theme = self.theme.name
        if self.render_theme != requested_theme:
            logger.warning("unknown hot graph render theme '%s', falling back to '%s'", requested_theme, self.render_theme)
        self._font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    def render_snapshot(
        self,
        snapshot: ActivitySnapshot,
        avatar_data: bytes | None = None,
        group_name: str | None = None,
    ) -> Path:
        avatar_image = None
        if avatar_data:
            try:
                avatar_image = Image.open(BytesIO(avatar_data)).convert("RGBA")
            except Exception:
                logger.debug("failed to decode avatar data, skipping")
        path = self.render_dir / f"heatmap_{uuid4().hex}.png"
        image = self._draw_heatmap(snapshot, avatar_image=avatar_image, group_name=group_name)
        dpi = 72 * self.render_scale
        image.save(path, format="PNG", dpi=(dpi, dpi))
        return path

    def _draw_heatmap(self, snapshot: ActivitySnapshot, *, avatar_image: Image.Image | None = None, group_name: str | None = None) -> Image.Image:
        return draw_heatmap_image(
            snapshot,
            avatar_image=avatar_image,
            group_name=group_name,
            scale=self.render_scale,
            get_font=self._get_font,
            use_cjk=self.font_path is not None,
            theme=self.theme,
        )

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        cached = self._font_cache.get(size)
        if cached is not None:
            return cached

        if self.font_path is None:
            font = ImageFont.load_default()
        else:
            font = ImageFont.truetype(str(self.font_path), size=size)
        self._font_cache[size] = font
        return font


def _resolve_font_path(
    configured_font_path: Path | None = None,
    search_roots: list[Path] | tuple[Path, ...] | None = None,
    candidate_names: tuple[str, ...] = _KNOWN_FONT_FILENAMES,
    recursive_patterns: tuple[str, ...] = _KNOWN_FONT_PATTERNS,
) -> Path | None:
    if configured_font_path is not None and configured_font_path.is_file():
        return configured_font_path

    roots = _default_font_search_roots() if search_roots is None else list(search_roots)
    for root in roots:
        if not root.exists():
            continue
        for font_name in candidate_names:
            candidate = root / font_name
            if candidate.is_file():
                return candidate
        for pattern in recursive_patterns:
            for candidate in root.rglob(pattern):
                if candidate.is_file():
                    return candidate
    logger.debug("hot graph renderer could not resolve a font from search roots: %s", roots)
    return None


def _default_font_search_roots() -> list[Path]:
    roots = [
        Path(__file__).resolve().parent.parent / "fonts",
        Path(__file__).resolve().parent / "assets" / "fonts",
        Path.home() / ".fonts",
        Path.home() / ".local" / "share" / "fonts",
    ]
    windir = os.environ.get("WINDIR")
    if os.name == "nt":
        roots.append(Path(windir) / "Fonts" if windir else Path("C:/Windows/Fonts"))

    roots.extend(
        [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
        ]
    )
    return roots
