from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from .models import ActivitySnapshot
from .utils import ensure_directory

_TITLE_FONT_SIZE = 16
_BODY_FONT_SIZE = 12
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
    def __init__(self, render_dir: Path, font_path: Path | None = None, render_scale: int = 2) -> None:
        self.render_dir = render_dir
        ensure_directory(self.render_dir)
        self.font_path = _resolve_font_path(font_path)
        self.render_scale = max(int(render_scale), 1)
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
        start_date = snapshot.summary.range_start
        end_date = snapshot.summary.range_end
        calendar_start = start_date - timedelta(days=start_date.weekday())
        total_days = (end_date - calendar_start).days + 1
        columns = (total_days + 6) // 7

        scale = self.render_scale
        cell = 12 * scale
        gap = 3 * scale
        left = 48 * scale
        top = 64 * scale
        grid_width = columns * (cell + gap)
        grid_height = 7 * (cell + gap)
        width = left + grid_width + 28 * scale
        height = top + grid_height + 82 * scale

        image = Image.new("RGB", (width, height), "#ffffff")
        draw = ImageDraw.Draw(image)

        title_font = self._get_font(_TITLE_FONT_SIZE * scale)
        body_font = self._get_font(_BODY_FONT_SIZE * scale)
        texts = _render_texts(snapshot, use_cjk=self.font_path is not None)

        # --- Avatar + title area ---
        avatar_diameter = 30 * scale
        margin_left = 16 * scale
        text_x = margin_left
        if avatar_image is not None:
            avatar_x = margin_left
            avatar_y = 9 * scale
            text_x = avatar_x + avatar_diameter + 6 * scale
            _paste_circular_avatar(image, avatar_image, avatar_x, avatar_y, avatar_diameter)

        draw.text(
            (text_x, 12 * scale),
            texts["title"],
            fill="#1f2328",
            font=title_font,
        )
        subtitle = texts["subtitle"].format(
            group_id=group_name or snapshot.registration.group_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        draw.text((text_x, 30 * scale), subtitle, fill="#656d76", font=body_font)

        for row, label in zip((0, 2, 4), ("Mon", "Wed", "Fri")):
            y = top + row * (cell + gap) + scale
            draw.text((16 * scale, y), label, fill="#656d76", font=body_font)

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
            draw.rounded_rectangle((x, y, x + cell, y + cell), radius=2 * scale, fill=color, outline=outline)
            if current.day == 1:
                month_labels.setdefault(col, current.strftime("%b"))
            current += timedelta(days=1)

        for col, label in month_labels.items():
            x = left + col * (cell + gap)
            draw.text((x, top - 14 * scale), label, fill="#656d76", font=body_font)

        summary_y = top + grid_height + 20 * scale
        draw.text((16 * scale, summary_y), texts["contrib"].format(total=snapshot.summary.total_messages), fill="#1f2328", font=body_font)
        draw.text((130 * scale, summary_y), texts["active_days"].format(days=snapshot.summary.active_days), fill="#1f2328", font=body_font)
        if snapshot.summary.most_active_date is not None:
            hottest = texts["hottest"].format(
                date=snapshot.summary.most_active_date.isoformat(),
                count=snapshot.summary.most_active_count,
            )
        else:
            hottest = texts["hottest_empty"]
        draw.text((16 * scale, summary_y + 14 * scale), hottest, fill="#1f2328", font=body_font)
        note_text = texts["note"]
        if note_text:
            draw.text((16 * scale, summary_y + 28 * scale), note_text, fill="#8250df", font=body_font)

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


def _paste_circular_avatar(
    target: Image.Image,
    avatar: Image.Image,
    x: int,
    y: int,
    diameter: int,
) -> None:
    resized = avatar.resize((diameter, diameter), Image.LANCZOS)
    ss = 4
    ss_size = diameter * ss
    mask_hires = Image.new("L", (ss_size, ss_size), 0)
    ImageDraw.Draw(mask_hires).ellipse((0, 0, ss_size, ss_size), fill=255)
    mask = mask_hires.resize((diameter, diameter), Image.LANCZOS)
    holder = Image.new("RGBA", target.size, (0, 0, 0, 0))
    holder.paste(resized, (x, y), mask)
    target.paste(holder, (0, 0), holder)


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


def _render_texts(snapshot: ActivitySnapshot, *, use_cjk: bool) -> dict[str, str | None]:
    if use_cjk:
        return {
            "title": f"{snapshot.registration.display_name} 的群聊热力图",
            "subtitle": "{group_id} | {start_date} ~ {end_date}",
            "contrib": "Contrib: {total}",
            "active_days": "Active days: {days}",
            "hottest": "Hottest: {date} ({count})",
            "hottest_empty": "Hottest: n/a",
            "note": snapshot.note,
        }

    safe_name = _ascii_fallback(snapshot.registration.display_name, fallback=snapshot.registration.user_id)
    note = _ascii_note(snapshot)
    return {
        "title": f"{safe_name} activity heatmap",
        "subtitle": "Group {group_id} | {start_date} ~ {end_date}",
        "contrib": "Contrib: {total}",
        "active_days": "Active days: {days}",
        "hottest": "Hottest: {date} ({count})",
        "hottest_empty": "Hottest: n/a",
        "note": note,
    }


def _ascii_fallback(text: str, *, fallback: str) -> str:
    safe = "".join(ch for ch in text if 32 <= ord(ch) <= 126).strip()
    return safe or fallback


def _ascii_note(snapshot: ActivitySnapshot) -> str:
    if not snapshot.note:
        return "Rule: 1 contribution per 5 messages."
    if snapshot.is_preview and "没有新的有效消息" in snapshot.note:
        return "Preview: no new valid messages since last formal sync."
    if snapshot.is_preview:
        return "Preview only: this result is not written to formal stats."
    return "Rule: 1 contribution per 5 messages."
