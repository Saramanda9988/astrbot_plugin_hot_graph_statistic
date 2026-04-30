from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hot_graph.models import ActivitySnapshot, HeatmapSummary, RegisteredUser
from hot_graph.render_templates import get_theme_names
from hot_graph.renderer import HeatmapRenderer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a fake hot graph snapshot without AstrBot.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=REPO_ROOT / "data" / "debug_render",
        help="Output file or directory. If a directory is provided, a PNG name is generated automatically.",
    )
    parser.add_argument(
        "--name",
        default="寒蝉_Official",
        help="Fake display name used in the rendered title.",
    )
    parser.add_argument(
        "--group-name",
        default="天天向上",
        help="Fake group name shown in the subtitle.",
    )
    parser.add_argument(
        "--user-id",
        default="114514",
        help="Fake user id used by the snapshot.",
    )
    parser.add_argument(
        "--group-id",
        default="186483623",
        help="Fake group id used by the snapshot.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Number of days to render.",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=2,
        help="Renderer scale passed to HeatmapRenderer.",
    )
    parser.add_argument(
        "--theme",
        default="light",
        choices=get_theme_names(),
        help="Render theme name.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic fake counts.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Render preview mode note instead of formal mode.",
    )
    parser.add_argument(
        "--no-avatar",
        action="store_true",
        help="Disable fake avatar generation.",
    )
    return parser.parse_args()


def build_fake_counts(start_date: date, days: int, seed: int) -> dict[date, int]:
    rng = random.Random(seed)
    counts: dict[date, int] = {}
    for offset in range(days):
        current = start_date + timedelta(days=offset)
        weekday = current.weekday()
        base = 0
        roll = rng.random()
        if weekday in (1, 2, 3):
            if roll > 0.20:
                base = rng.randint(1, 5)
        elif weekday in (4, 5):
            if roll > 0.35:
                base = rng.randint(1, 4)
        else:
            if roll > 0.55:
                base = rng.randint(1, 3)
        if rng.random() > 0.94:
            base += rng.randint(2, 5)
        if base > 0:
            counts[current] = base
    return counts


def build_snapshot(args: argparse.Namespace) -> ActivitySnapshot:
    days = max(int(args.days), 1)
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=days - 1)
    counts = build_fake_counts(start_date, days, args.seed)
    total_messages = sum(counts.values())
    active_days = len(counts)
    most_active_date = max(counts, key=counts.get) if counts else None
    most_active_count = counts[most_active_date] if most_active_date else 0

    registration = RegisteredUser(
        id=1,
        platform_id="mock-platform",
        group_id=str(args.group_id),
        user_id=str(args.user_id),
        display_name=str(args.name),
        registered_at=datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
    )
    summary = HeatmapSummary(
        range_start=start_date,
        range_end=end_date,
        total_messages=total_messages,
        active_days=active_days,
        most_active_date=most_active_date,
        most_active_count=most_active_count,
    )
    note = None
    if args.preview:
        note = "临时预览：本次结果未写入正式统计。"
    return ActivitySnapshot(
        registration=registration,
        counts_by_date=counts,
        summary=summary,
        is_preview=bool(args.preview),
        generated_at=datetime.now(UTC),
        note=note,
    )


def build_fake_avatar(display_name: str, size: int = 256) -> bytes:
    bg = Image.new("RGBA", (size, size), (232, 238, 247, 255))
    draw = ImageDraw.Draw(bg)
    draw.ellipse((18, 18, size - 18, size - 18), fill=(205, 219, 240, 255))
    draw.ellipse((size * 0.31, size * 0.22, size * 0.69, size * 0.56), fill=(76, 92, 119, 255))
    draw.rounded_rectangle(
        (size * 0.24, size * 0.58, size * 0.76, size * 0.92),
        radius=size * 0.08,
        fill=(102, 120, 150, 255),
    )

    # Use the first visible character as a simple badge so sample outputs are easier to distinguish.
    badge_text = next((ch for ch in display_name.strip() if not ch.isspace()), "?")
    try:
        from PIL import ImageFont

        font = ImageFont.truetype("arial.ttf", size // 3)
    except Exception:
        font = None
    text_bbox = draw.textbbox((0, 0), badge_text, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]
    draw.text(
        ((size - text_w) / 2, size * 0.33 - text_h / 2),
        badge_text,
        fill=(255, 255, 255, 220),
        font=font,
    )

    buf = BytesIO()
    bg.save(buf, format="PNG")
    return buf.getvalue()


def resolve_output(output: Path) -> tuple[Path, Path]:
    if output.suffix.lower() == ".png":
        render_dir = output.parent
        final_output = output
    else:
        render_dir = output
        final_output = output / "debug_render.png"
    render_dir.mkdir(parents=True, exist_ok=True)
    return render_dir, final_output


def main() -> int:
    args = parse_args()
    render_dir, final_output = resolve_output(args.output)

    snapshot = build_snapshot(args)
    avatar_data = None if args.no_avatar else build_fake_avatar(snapshot.registration.display_name)
    renderer = HeatmapRenderer(
        render_dir=render_dir,
        render_scale=max(int(args.scale), 1),
        render_theme=str(args.theme),
    )
    temp_output = renderer.render_snapshot(
        snapshot,
        avatar_data=avatar_data,
        group_name=str(args.group_name),
    )
    temp_output.replace(final_output)
    print(final_output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
