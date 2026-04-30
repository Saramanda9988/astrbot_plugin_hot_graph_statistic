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
_META_FONT_SIZE = 11
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
_CANVAS_BACKGROUND = "#ffffff"
_CANVAS_TEXT = "#1f2328"
_CANVAS_MUTED = "#656d76"
_CARD_BACKGROUND = "#ffffff"
_CARD_BORDER = "#d0d7de"
_CARD_TEXT = "#24292f"
_CARD_MUTED = "#57606a"
_CARD_PREVIEW = "#8250df"
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
        title_font = self._get_font(_TITLE_FONT_SIZE * scale)
        body_font = self._get_font(_BODY_FONT_SIZE * scale)
        meta_font = self._get_font(_META_FONT_SIZE * scale)
        texts = _render_texts(snapshot, use_cjk=self.font_path is not None)
        subtitle = texts["subtitle"].format(
            group_id=group_name or snapshot.registration.group_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        measure = ImageDraw.Draw(Image.new("RGB", (1, 1), _CANVAS_BACKGROUND))
        title_size = _measure_text(measure, texts["title"], title_font)
        subtitle_size = _measure_text(measure, subtitle, body_font)
        contrib_text = texts["contrib"].format(total=snapshot.summary.total_messages)
        contrib_size = _measure_text(measure, contrib_text, body_font)
        active_text = texts["active_days"].format(days=snapshot.summary.active_days)
        active_size = _measure_text(measure, active_text, body_font)
        note_text = texts["note"] or ""
        note_size = _measure_text(measure, note_text, meta_font)

        page_margin_x = 16 * scale
        page_margin_y = 12 * scale
        avatar_diameter = 30 * scale
        avatar_gap = 8 * scale
        header_gap = 14 * scale
        contrib_gap = 10 * scale
        card_padding_x = 18 * scale
        card_padding_top = 14 * scale
        card_padding_bottom = 14 * scale
        month_label_band = 18 * scale
        footer_band = 22 * scale
        weekday_band = 44 * scale
        corner_radius = 10 * scale

        grid_width = columns * cell + max(columns - 1, 0) * gap
        grid_height = 7 * cell + 6 * gap
        base_card_width = card_padding_x * 2 + weekday_band + grid_width
        footer_content_width = note_size[0] + active_size[0] + 32 * scale
        card_width = max(base_card_width, card_padding_x * 2 + footer_content_width)
        card_height = card_padding_top + month_label_band + grid_height + footer_band + card_padding_bottom

        header_left = page_margin_x
        text_x = header_left
        if avatar_image is not None:
            text_x += avatar_diameter + avatar_gap
        header_width = max(title_size[0], subtitle_size[0]) + (text_x - header_left)
        header_height = max(avatar_diameter, title_size[1] + subtitle_size[1] + 6 * scale)
        card_x = page_margin_x
        contrib_y = page_margin_y + header_height + header_gap
        card_y = contrib_y + contrib_size[1] + contrib_gap

        width = max(card_x + card_width + page_margin_x, header_left + header_width + page_margin_x)
        height = card_y + card_height + page_margin_y

        image = Image.new("RGB", (width, height), _CANVAS_BACKGROUND)
        draw = ImageDraw.Draw(image)

        if avatar_image is not None:
            avatar_x = header_left
            avatar_y = page_margin_y + max((header_height - avatar_diameter) // 2, 0)
            _paste_circular_avatar(image, avatar_image, avatar_x, avatar_y, avatar_diameter)

        title_y = page_margin_y
        draw.text(
            (text_x, title_y),
            texts["title"],
            fill=_CANVAS_TEXT,
            font=title_font,
        )
        subtitle_y = title_y + title_size[1] + 6 * scale
        draw.text((text_x, subtitle_y), subtitle, fill=_CANVAS_MUTED, font=body_font)
        draw.text((card_x, contrib_y), contrib_text, fill=_CANVAS_TEXT, font=body_font)

        card_right = card_x + card_width
        card_bottom = card_y + card_height
        draw.rounded_rectangle(
            (card_x, card_y, card_right, card_bottom),
            radius=corner_radius,
            fill=_CARD_BACKGROUND,
            outline=_CARD_BORDER,
            width=max(scale, 1),
        )

        grid_left = card_x + card_padding_x + weekday_band
        grid_top = card_y + card_padding_top + month_label_band
        for row, label in zip((0, 2, 4), ("Mon", "Wed", "Fri")):
            y = grid_top + row * (cell + gap) + scale
            draw.text((card_x + card_padding_x, y), label, fill=_CARD_MUTED, font=meta_font)

        max_count = max(snapshot.counts_by_date.values(), default=0)
        current = calendar_start
        month_labels: dict[int, str] = {}

        for index in range(total_days):
            col = index // 7
            row = index % 7
            x = grid_left + col * (cell + gap)
            y = grid_top + row * (cell + gap)
            count = snapshot.counts_by_date.get(current, 0)
            color = _resolve_color(count, max_count)
            draw.rounded_rectangle(
                (x, y, x + cell, y + cell),
                radius=max(2 * scale, 2),
                fill=color,
                outline=color,
            )
            if current.day == 1:
                month_labels.setdefault(col, current.strftime("%b"))
            current += timedelta(days=1)

        for col, label in month_labels.items():
            x = grid_left + col * (cell + gap)
            draw.text((x, grid_top - month_label_band), label, fill=_CARD_MUTED, font=body_font)

        footer_top = grid_top + grid_height + 10 * scale
        note_color = _CARD_PREVIEW if snapshot.is_preview else _CARD_MUTED
        if note_text:
            note_y = footer_top + max((footer_band - note_size[1]) // 2, 0)
            draw.text((card_x + card_padding_x, note_y), note_text, fill=note_color, font=meta_font)
        active_x = card_right - card_padding_x - active_size[0]
        active_y = footer_top + max((footer_band - active_size[1]) // 2, 0)
        draw.text((active_x, active_y), active_text, fill=_CARD_TEXT, font=body_font)

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
            "contrib": "{total} contributions in the last year",
            "active_days": "Active days: {days}",
            "note": snapshot.note or "统计规则：每 5 条消息记作 1 次贡献",
        }

    safe_name = _ascii_fallback(snapshot.registration.display_name, fallback=snapshot.registration.user_id)
    note = _ascii_note(snapshot)
    return {
        "title": f"{safe_name} activity heatmap",
        "subtitle": "Group {group_id} | {start_date} ~ {end_date}",
        "contrib": "Contrib: {total}",
        "active_days": "Active days: {days}",
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


def _measure_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int]:
    if not text:
        return 0, 0
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top
