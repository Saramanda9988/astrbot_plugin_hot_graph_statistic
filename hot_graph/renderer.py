from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from .models import ActivitySnapshot
from .utils import ensure_directory

_TITLE_FONT_SIZE = 16
_BODY_FONT_SIZE = 12
_KNOWN_FONT_FILENAMES = (
    "msyh.ttc",
    "msyhbd.ttc",
    "simhei.ttf",
    "simsun.ttc",
    "Deng.ttf",
    "Dengb.ttf",
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
)
_KNOWN_FONT_PATTERNS = (
    "NotoSansCJK-*.ttc",
    "NotoSansCJK-*.otf",
    "NotoSansSC-*.otf",
    "SourceHanSans*-Regular.otf",
    "SourceHanSans*-Normal.otf",
    "wqy-*.ttc",
)


class HeatmapRenderer:
    def __init__(self, render_dir: Path, font_path: Path | None = None) -> None:
        self.render_dir = render_dir
        ensure_directory(self.render_dir)
        self.font_path = _resolve_font_path(font_path)
        self._font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    def render_snapshot(self, snapshot: ActivitySnapshot) -> Path:
        path = self.render_dir / f"heatmap_{uuid4().hex}.png"
        image = self._draw_heatmap(snapshot)
        image.save(path, format="PNG")
        return path

    def _draw_heatmap(self, snapshot: ActivitySnapshot) -> Image.Image:
        start_date = snapshot.summary.range_start
        end_date = snapshot.summary.range_end
        calendar_start = start_date - timedelta(days=start_date.weekday())
        total_days = (end_date - calendar_start).days + 1
        columns = (total_days + 6) // 7

        cell = 12
        gap = 3
        left = 64
        top = 44
        grid_width = columns * (cell + gap)
        grid_height = 7 * (cell + gap)
        width = left + grid_width + 28
        height = top + grid_height + 82

        image = Image.new("RGB", (width, height), "#ffffff")
        draw = ImageDraw.Draw(image)

        title_font = self._get_font(_TITLE_FONT_SIZE)
        body_font = self._get_font(_BODY_FONT_SIZE)

        draw.text(
            (16, 12),
            f"{snapshot.registration.display_name} 的群聊热力图",
            fill="#1f2328",
            font=title_font,
        )
        subtitle = f"{snapshot.registration.group_id} | {start_date.isoformat()} ~ {end_date.isoformat()}"
        draw.text((16, 30), subtitle, fill="#656d76", font=body_font)

        for row, label in zip((0, 2, 4), ("Mon", "Wed", "Fri")):
            y = top + row * (cell + gap) + 1
            draw.text((16, y), label, fill="#656d76", font=body_font)

        max_count = max(snapshot.counts_by_date.values(), default=0)
        current = calendar_start
        month_labels: dict[int, str] = {}

        for index in range(total_days):
            col = index // 7
            row = index % 7
            x = left + col * (cell + gap)
            y = top + row * (cell + gap)
            count = snapshot.counts_by_date.get(current, 0)
            color = _resolve_color(count, max_count)
            outline = "#d0d7de" if current < start_date or current > end_date else color
            draw.rounded_rectangle((x, y, x + cell, y + cell), radius=2, fill=color, outline=outline)
            if current.day == 1:
                month_labels.setdefault(col, current.strftime("%b"))
            current += timedelta(days=1)

        for col, label in month_labels.items():
            x = left + col * (cell + gap)
            draw.text((x, top - 14), label, fill="#656d76", font=body_font)

        summary_y = top + grid_height + 20
        draw.text((16, summary_y), f"Contrib: {snapshot.summary.total_messages}", fill="#1f2328", font=body_font)
        draw.text((130, summary_y), f"Active days: {snapshot.summary.active_days}", fill="#1f2328", font=body_font)
        if snapshot.summary.most_active_date is not None:
            hottest = f"Hottest: {snapshot.summary.most_active_date.isoformat()} ({snapshot.summary.most_active_count})"
        else:
            hottest = "Hottest: n/a"
        draw.text((16, summary_y + 14), hottest, fill="#1f2328", font=body_font)
        if snapshot.note:
            draw.text((16, summary_y + 28), snapshot.note, fill="#8250df", font=body_font)

        return image

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


def _resolve_color(count: int, max_count: int) -> str:
    if count <= 0:
        return "#ebedf0"
    if max_count <= 1:
        return "#9be9a8"

    ratio = count / max_count
    if ratio <= 0.25:
        return "#9be9a8"
    if ratio <= 0.50:
        return "#40c463"
    if ratio <= 0.75:
        return "#30a14e"
    return "#216e39"


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
    return None


def _default_font_search_roots() -> list[Path]:
    roots = [
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
