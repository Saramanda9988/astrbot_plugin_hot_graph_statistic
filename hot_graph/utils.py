from __future__ import annotations

import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import PluginSettings

DEFAULT_DB_FILENAME = "hot_graph.db"
DEFAULT_RENDER_DIRNAME = "render"
LEGACY_DEFAULT_DB_PATH = "data/hot_graph.db"
LEGACY_DEFAULT_RENDER_DIR = "data/hot_graph/render"


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
        return candidate.resolve()
    return (base_dir / candidate).resolve()


def normalize_storage_setting(raw: str, *, legacy_default: str, current_default: str) -> str:
    if not raw:
        return current_default
    candidate = Path(raw)
    if not candidate.is_absolute() and candidate.as_posix() == legacy_default:
        return current_default
    return raw


def build_settings(config: dict | None, base_dir: Path, storage_dir: Path) -> PluginSettings:
    config = config or {}
    storage_dir = storage_dir.resolve()
    db_path_raw = normalize_storage_setting(
        str(config.get("db_path") or "").strip(),
        legacy_default=LEGACY_DEFAULT_DB_PATH,
        current_default=DEFAULT_DB_FILENAME,
    )
    render_dir_raw = normalize_storage_setting(
        str(config.get("render_dir") or "").strip(),
        legacy_default=LEGACY_DEFAULT_RENDER_DIR,
        current_default=DEFAULT_RENDER_DIRNAME,
    )
    db_path = normalize_path(storage_dir, db_path_raw)
    render_dir = normalize_path(
        storage_dir,
        render_dir_raw,
    )
    font_path_raw = str(config.get("font_path") or "").strip()
    font_path = normalize_path(base_dir, font_path_raw) if font_path_raw else None
    mock_history_raw = str(config.get("mock_history_path") or "").strip()
    mock_history_path = normalize_path(base_dir, mock_history_raw) if mock_history_raw else None

    return PluginSettings(
        db_path=db_path,
        render_dir=render_dir,
        font_path=font_path,
        render_scale=max(int(config.get("render_scale") or 2), 1),
        timezone=str(config.get("timezone") or "Asia/Shanghai"),
        history_days=max(int(config.get("history_days") or 365), 1),
        aggregate_interval_seconds=max(int(config.get("aggregate_interval_seconds") or 300), 30),
        history_page_size=max(int(config.get("history_page_size") or 200), 20),
        history_source_type=str(config.get("history_source_type") or "auto"),
        mock_history_path=mock_history_path,
        enable_background_sync=bool(config.get("enable_background_sync", True)),
    )


def migrate_legacy_db_if_needed(
    config: dict | None,
    base_dir: Path,
    db_path: Path,
) -> Path | None:
    config = config or {}
    legacy_raw = str(config.get("db_path") or LEGACY_DEFAULT_DB_PATH).strip()
    legacy_db_path = normalize_path(base_dir, legacy_raw)
    if legacy_db_path == db_path or db_path.exists() or not legacy_db_path.exists():
        return None

    ensure_parent(db_path)
    shutil.copy2(legacy_db_path, db_path)
    for suffix in ("-wal", "-shm"):
        legacy_sidecar = Path(f"{legacy_db_path}{suffix}")
        if legacy_sidecar.exists():
            target_sidecar = Path(f"{db_path}{suffix}")
            if not target_sidecar.exists():
                shutil.copy2(legacy_sidecar, target_sidecar)
    return legacy_db_path


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
