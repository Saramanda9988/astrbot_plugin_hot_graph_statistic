from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from PIL import Image, ImageDraw, ImageFont

from ..models import ActivitySnapshot

TITLE_FONT_SIZE = 16
BODY_FONT_SIZE = 12
META_FONT_SIZE = 11

FontGetter = Callable[[int], ImageFont.FreeTypeFont | ImageFont.ImageFont]


@dataclass(frozen=True)
class ThemePalette:
    canvas_background: str
    canvas_text: str
    canvas_muted: str
    card_background: str
    card_border: str
    card_text: str
    card_muted: str
    card_preview: str
    zero_color: str
    low_color: str
    medium_color: str
    high_color: str
    max_color: str


@dataclass(frozen=True)
class HeatmapTheme:
    name: str
    palette: ThemePalette


def draw_heatmap_image(
    snapshot: ActivitySnapshot,
    *,
    avatar_image: Image.Image | None,
    group_name: str | None,
    scale: int,
    get_font: FontGetter,
    use_cjk: bool,
    theme: HeatmapTheme,
) -> Image.Image:
    palette = theme.palette
    start_date = snapshot.summary.range_start
    end_date = snapshot.summary.range_end
    calendar_start = start_date - timedelta(days=start_date.weekday())
    total_days = (end_date - calendar_start).days + 1
    columns = (total_days + 6) // 7

    cell = 12 * scale
    gap = 3 * scale
    title_font = get_font(TITLE_FONT_SIZE * scale)
    body_font = get_font(BODY_FONT_SIZE * scale)
    meta_font = get_font(META_FONT_SIZE * scale)
    texts = render_texts(snapshot, use_cjk=use_cjk)
    subtitle = texts["subtitle"].format(
        group_id=group_name or snapshot.registration.group_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1), palette.canvas_background))
    title_size = measure_text(measure, texts["title"], title_font)
    subtitle_size = measure_text(measure, subtitle, body_font)
    contrib_text = texts["contrib"].format(total=snapshot.summary.total_messages)
    contrib_size = measure_text(measure, contrib_text, body_font)
    active_text = texts["active_days"].format(days=snapshot.summary.active_days)
    active_size = measure_text(measure, active_text, body_font)
    note_text = texts["note"] or ""
    note_size = measure_text(measure, note_text, meta_font)

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

    width = max(
        card_x + card_width + page_margin_x,
        header_left + header_width + page_margin_x,
        card_x + contrib_size[0] + page_margin_x,
    )
    height = card_y + card_height + page_margin_y

    image = Image.new("RGB", (width, height), palette.canvas_background)
    draw = ImageDraw.Draw(image)

    if avatar_image is not None:
        avatar_x = header_left
        avatar_y = page_margin_y + max((header_height - avatar_diameter) // 2, 0)
        paste_circular_avatar(image, avatar_image, avatar_x, avatar_y, avatar_diameter)

    title_y = page_margin_y
    draw.text((text_x, title_y), texts["title"], fill=palette.canvas_text, font=title_font)
    subtitle_y = title_y + title_size[1] + 6 * scale
    draw.text((text_x, subtitle_y), subtitle, fill=palette.canvas_muted, font=body_font)
    draw.text((card_x, contrib_y), contrib_text, fill=palette.canvas_text, font=body_font)

    card_right = card_x + card_width
    card_bottom = card_y + card_height
    draw.rounded_rectangle(
        (card_x, card_y, card_right, card_bottom),
        radius=corner_radius,
        fill=palette.card_background,
        outline=palette.card_border,
        width=max(scale, 1),
    )

    grid_left = card_x + card_padding_x + weekday_band
    grid_top = card_y + card_padding_top + month_label_band
    for row, label in zip((0, 2, 4), ("Mon", "Wed", "Fri")):
        y = grid_top + row * (cell + gap) + scale
        draw.text((card_x + card_padding_x, y), label, fill=palette.card_muted, font=meta_font)

    max_count = max(snapshot.counts_by_date.values(), default=0)
    current = calendar_start
    month_labels: dict[int, str] = {}

    for index in range(total_days):
        col = index // 7
        row = index % 7
        x = grid_left + col * (cell + gap)
        y = grid_top + row * (cell + gap)
        count = snapshot.counts_by_date.get(current, 0)
        color = resolve_color(count, max_count, palette)
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
        draw.text((x, grid_top - month_label_band), label, fill=palette.card_muted, font=body_font)

    footer_top = grid_top + grid_height + 10 * scale
    note_color = palette.card_preview if snapshot.is_preview else palette.card_muted
    if note_text:
        note_y = footer_top + max((footer_band - note_size[1]) // 2, 0)
        draw.text((card_x + card_padding_x, note_y), note_text, fill=note_color, font=meta_font)
    active_x = card_right - card_padding_x - active_size[0]
    active_y = footer_top + max((footer_band - active_size[1]) // 2, 0)
    draw.text((active_x, active_y), active_text, fill=palette.card_text, font=body_font)

    return image


def paste_circular_avatar(
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


def resolve_color(count: int, max_count: int, palette: ThemePalette) -> str:
    if count <= 0:
        return palette.zero_color
    if max_count <= 1:
        return palette.low_color

    ratio = count / max_count
    if ratio <= 0.25:
        return palette.low_color
    if ratio <= 0.50:
        return palette.medium_color
    if ratio <= 0.75:
        return palette.high_color
    return palette.max_color


def render_texts(snapshot: ActivitySnapshot, *, use_cjk: bool) -> dict[str, str | None]:
    if use_cjk:
        return {
            "title": f"{snapshot.registration.display_name} 的群聊热力图",
            "subtitle": "{group_id} | {start_date} ~ {end_date}",
            "contrib": "{total} contributions in the last year",
            "active_days": "Active days: {days}",
            "note": snapshot.note or "",
        }

    safe_name = ascii_fallback(snapshot.registration.display_name, fallback=snapshot.registration.user_id)
    note = ascii_note(snapshot)
    return {
        "title": f"{safe_name} activity heatmap",
        "subtitle": "Group {group_id} | {start_date} ~ {end_date}",
        "contrib": "{total} contributions in the last year",
        "active_days": "Active days: {days}",
        "note": note,
    }


def ascii_fallback(text: str, *, fallback: str) -> str:
    safe = "".join(ch for ch in text if 32 <= ord(ch) <= 126).strip()
    return safe or fallback


def ascii_note(snapshot: ActivitySnapshot) -> str:
    if not snapshot.note:
        return "Rule: 1 contribution per 5 messages."
    if snapshot.is_preview and "没有新的有效消息" in snapshot.note:
        return "Preview: no new valid messages since last formal sync."
    if snapshot.is_preview:
        return "Preview only: this result is not written to formal stats."
    return "Rule: 1 contribution per 5 messages."


def measure_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int]:
    if not text:
        return 0, 0
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top
