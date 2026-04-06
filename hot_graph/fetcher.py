from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .exceptions import HistorySourceUnavailableError
from .models import HistoryMessage, PluginSettings


@dataclass(frozen=True)
class FetchRequest:
    platform_id: str
    group_id: str
    user_id: str
    start_at: datetime
    end_at: datetime
    page_size: int


class HistoryFetcher(Protocol):
    async def fetch_messages(self, request: FetchRequest) -> list[HistoryMessage]:
        ...


class DisabledHistoryFetcher:
    async def fetch_messages(self, request: FetchRequest) -> list[HistoryMessage]:
        raise HistorySourceUnavailableError("未配置可用的历史消息来源。")


class ContextHistoryFetcher:
    def __init__(self, message_history_manager: Any) -> None:
        self.message_history_manager = message_history_manager

    async def fetch_messages(self, request: FetchRequest) -> list[HistoryMessage]:
        page = 1
        items: list[HistoryMessage] = []

        while True:
            records = await self.message_history_manager.get(
                platform_id=request.platform_id,
                user_id=request.group_id,
                page=page,
                page_size=request.page_size,
            )
            if not records:
                break

            for record in records:
                occurred_at = _normalize_datetime(getattr(record, "created_at", None))
                if occurred_at is None or occurred_at <= request.start_at or occurred_at > request.end_at:
                    continue
                sender_id = str(getattr(record, "sender_id", "") or "")
                if sender_id != request.user_id:
                    continue
                items.append(
                    HistoryMessage(
                        platform_id=request.platform_id,
                        group_id=request.group_id,
                        sender_id=sender_id,
                        sender_name=str(getattr(record, "sender_name", "") or ""),
                        message_id=str(getattr(record, "id", "")) or None,
                        occurred_at=occurred_at,
                        content=dict(getattr(record, "content", {}) or {}),
                    )
                )

            if len(records) < request.page_size:
                break
            page += 1

        items.sort(key=lambda item: item.occurred_at)
        return items


class MockJsonHistoryFetcher:
    def __init__(self, json_path: Path) -> None:
        self.json_path = json_path

    async def fetch_messages(self, request: FetchRequest) -> list[HistoryMessage]:
        if not self.json_path.exists():
            raise HistorySourceUnavailableError(f"Mock history file not found: {self.json_path}")

        raw_items = json.loads(self.json_path.read_text(encoding="utf-8"))
        messages: list[HistoryMessage] = []
        for raw in raw_items:
            platform_id = str(raw.get("platform_id") or request.platform_id)
            group_id = str(raw.get("group_id") or request.group_id)
            sender_id = str(raw.get("sender_id") or "")
            occurred_at = _normalize_datetime(raw.get("occurred_at") or raw.get("created_at") or raw.get("timestamp"))
            if not occurred_at:
                continue
            if platform_id != request.platform_id or group_id != request.group_id:
                continue
            if sender_id != request.user_id:
                continue
            if occurred_at <= request.start_at or occurred_at > request.end_at:
                continue
            messages.append(
                HistoryMessage(
                    platform_id=platform_id,
                    group_id=group_id,
                    sender_id=sender_id,
                    sender_name=str(raw.get("sender_name") or ""),
                    message_id=str(raw.get("message_id") or "") or None,
                    occurred_at=occurred_at,
                    content=dict(raw.get("content") or {}),
                )
            )

        messages.sort(key=lambda item: item.occurred_at)
        return messages


def build_history_fetcher(settings: PluginSettings, context: Any | None = None) -> HistoryFetcher:
    source_type = settings.history_source_type.strip().lower()
    if source_type == "mock_json" and settings.mock_history_path is not None:
        return MockJsonHistoryFetcher(settings.mock_history_path)

    if source_type in {"context_history", "auto"} and context is not None:
        manager = getattr(context, "message_history_manager", None)
        if manager is not None:
            return ContextHistoryFetcher(manager)

    if source_type == "disabled":
        return DisabledHistoryFetcher()

    if settings.mock_history_path is not None and settings.mock_history_path.exists():
        return MockJsonHistoryFetcher(settings.mock_history_path)

    if context is not None and getattr(context, "message_history_manager", None) is not None:
        return ContextHistoryFetcher(context.message_history_manager)

    return DisabledHistoryFetcher()


def _normalize_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None
