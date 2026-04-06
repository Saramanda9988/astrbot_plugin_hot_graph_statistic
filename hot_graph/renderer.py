from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from .models import ActivitySnapshot
from .utils import ensure_directory


class HeatmapRenderer:
    def __init__(self, render_dir: Path) -> None:
        self.render_dir = render_dir
        ensure_directory(self.render_dir)
        self.font = ImageFont.load_default()

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

        draw.text((16, 12), f"{snapshot.registration.display_name} 的群聊热力图", fill="#1f2328", font=self.font)
        subtitle = f"{snapshot.registration.group_id} | {start_date.isoformat()} ~ {end_date.isoformat()}"
        draw.text((16, 26), subtitle, fill="#656d76", font=self.font)

        for row, label in zip((0, 2, 4), ("Mon", "Wed", "Fri")):
            y = top + row * (cell + gap) + 1
            draw.text((16, y), label, fill="#656d76", font=self.font)

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
            draw.text((x, top - 14), label, fill="#656d76", font=self.font)

        summary_y = top + grid_height + 20
        draw.text((16, summary_y), f"Total: {snapshot.summary.total_messages}", fill="#1f2328", font=self.font)
        draw.text((130, summary_y), f"Active days: {snapshot.summary.active_days}", fill="#1f2328", font=self.font)
        if snapshot.summary.most_active_date is not None:
            hottest = f"Hottest: {snapshot.summary.most_active_date.isoformat()} ({snapshot.summary.most_active_count})"
        else:
            hottest = "Hottest: n/a"
        draw.text((16, summary_y + 14), hottest, fill="#1f2328", font=self.font)
        if snapshot.note:
            draw.text((16, summary_y + 28), snapshot.note, fill="#8250df", font=self.font)

        return image


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
