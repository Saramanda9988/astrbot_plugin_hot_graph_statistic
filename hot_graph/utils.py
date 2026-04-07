from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import PluginSettings


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat()


def local_date(dt: datetime, timezone_name: str) -> date:
    return dt.astimezone(ZoneInfo(timezone_name)).date()


def date_window(now: datetime, timezone_name: str, history_days: int) -> tuple[date, date]:
    end_date = local_date(now, timezone_name)
    start_date = end_date - timedelta(days=max(history_days - 1, 0))
    return start_date, end_date


def normalize_path(base_dir: Path, raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def build_settings(config: dict | None, base_dir: Path) -> PluginSettings:
    config = config or {}
    db_path = normalize_path(base_dir, str(config.get("db_path") or "data/hot_graph.db"))
    render_dir = normalize_path(
        base_dir,
        str(config.get("render_dir") or "data/hot_graph/render"),
    )
    mock_history_raw = str(config.get("mock_history_path") or "").strip()
    mock_history_path = normalize_path(base_dir, mock_history_raw) if mock_history_raw else None

    return PluginSettings(
        db_path=db_path,
        render_dir=render_dir,
        timezone=str(config.get("timezone") or "Asia/Shanghai"),
        history_days=max(int(config.get("history_days") or 365), 1),
        aggregate_interval_seconds=max(int(config.get("aggregate_interval_seconds") or 300), 30),
        history_page_size=max(int(config.get("history_page_size") or 200), 20),
        history_source_type=str(config.get("history_source_type") or "context_history"),
        mock_history_path=mock_history_path,
        enable_background_sync=bool(config.get("enable_background_sync", True)),
    )


def format_summary(
    snapshot_note: str | None,
    display_name: str,
    summary_total: int,
    active_days: int,
    most_active_date: date | None,
    most_active_count: int,
    range_start: date,
    range_end: date,
) -> str:
    lines = []
    if snapshot_note:
        lines.append(snapshot_note)
    lines.extend(
        [
            f"{display_name} 的群聊热力图",
            f"统计范围：{range_start.isoformat()} ~ {range_end.isoformat()}",
            f"总贡献数：{summary_total}",
            f"活跃天数：{active_days}",
        ]
    )
    if most_active_date is not None:
        lines.append(f"最活跃的一天：{most_active_date.isoformat()}（{most_active_count} 次贡献）")
    else:
        lines.append("最活跃的一天：暂无数据")
    return "\n".join(lines)
