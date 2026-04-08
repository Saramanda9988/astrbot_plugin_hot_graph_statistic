from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True)
class PluginSettings:
    db_path: Path
    render_dir: Path
    font_path: Path | None = None
    timezone: str = "Asia/Shanghai"
    history_days: int = 365
    aggregate_interval_seconds: int = 300
    history_page_size: int = 200
    history_source_type: str = "auto"
    mock_history_path: Path | None = None
    enable_background_sync: bool = True


@dataclass(frozen=True)
class RegisteredUser:
    id: int | None
    platform_id: str
    group_id: str
    user_id: str
    display_name: str
    registered_at: datetime


@dataclass(frozen=True)
class SyncState:
    id: int | None
    platform_id: str
    group_id: str
    user_id: str
    scope_key: str
    last_synced_at: datetime | None
    last_message_cursor: str | None
    updated_at: datetime


@dataclass(frozen=True)
class HistoryMessage:
    platform_id: str
    group_id: str
    sender_id: str
    sender_name: str
    message_id: str | None
    occurred_at: datetime
    content: dict


@dataclass(frozen=True)
class HeatmapSummary:
    range_start: date
    range_end: date
    total_messages: int
    active_days: int
    most_active_date: date | None
    most_active_count: int


@dataclass(frozen=True)
class ActivitySnapshot:
    registration: RegisteredUser
    counts_by_date: dict[date, int]
    summary: HeatmapSummary
    is_preview: bool
    generated_at: datetime
    note: str | None = None


@dataclass(frozen=True)
class SyncResult:
    registration: RegisteredUser
    synced_from: datetime | None
    synced_to: datetime
    messages_seen: int
    counts_applied: int
    applied: bool
