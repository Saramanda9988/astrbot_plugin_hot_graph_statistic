from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .exceptions import HistorySourceUnavailableError
from .models import HistoryMessage, PluginSettings

logger = logging.getLogger(__name__)


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
        items: list[HistoryMessage] = []
        seen_keys: set[str] = set()
        scope_candidates = _history_scope_candidates(request)

        logger.debug(
            "hot graph history fetch start: platform=%s group=%s user=%s window=(%s, %s] scopes=%s",
            request.platform_id,
            request.group_id,
            request.user_id,
            request.start_at.isoformat(),
            request.end_at.isoformat(),
            scope_candidates,
        )

        for scope_key in scope_candidates:
            page = 1
            fetched_records = 0
            matched_records = 0

            while True:
                records = await self.message_history_manager.get(
                    platform_id=request.platform_id,
                    user_id=scope_key,
                    page=page,
                    page_size=request.page_size,
                )
                if not records:
                    if page == 1:
                        logger.debug(
                            "hot graph history scope empty: platform=%s scope=%s page_size=%s",
                            request.platform_id,
                            scope_key,
                            request.page_size,
                        )
                    break

                fetched_records += len(records)
                for record in records:
                    message = _history_message_from_record(record, request)
                    if message is None:
                        continue
                    message_key = _dedupe_key(message)
                    if message_key in seen_keys:
                        continue
                    seen_keys.add(message_key)
                    matched_records += 1
                    items.append(message)

                if len(records) < request.page_size:
                    break
                page += 1

            logger.debug(
                "hot graph history scope result: platform=%s scope=%s fetched=%s matched=%s",
                request.platform_id,
                scope_key,
                fetched_records,
                matched_records,
            )

        items.sort(key=lambda item: item.occurred_at)
        logger.debug(
            "hot graph history fetch done: platform=%s group=%s user=%s matched_total=%s",
            request.platform_id,
            request.group_id,
            request.user_id,
            len(items),
        )
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
        logger.info("hot graph history source: mock_json path=%s", settings.mock_history_path)
        return MockJsonHistoryFetcher(settings.mock_history_path)

    if source_type in {"context_history", "auto"} and context is not None:
        manager = getattr(context, "message_history_manager", None)
        if manager is not None:
            logger.info(
                "hot graph history source: context_history manager=%s",
                type(manager).__name__,
            )
            return ContextHistoryFetcher(manager)
        logger.warning("hot graph history source requested context_history but message_history_manager is missing")

    logger.warning("hot graph history source disabled or unavailable: source_type=%s", source_type)
    return DisabledHistoryFetcher()


def _record_value(record: Any, *names: str) -> Any:
    if isinstance(record, dict):
        for name in names:
            if name in record:
                return record.get(name)
        return None
    for name in names:
        value = getattr(record, name, None)
        if value is not None:
            return value
    return None


def _normalize_content(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"text": value}
        return dict(parsed) if isinstance(parsed, dict) else {"value": parsed}
    return {}


def _history_scope_candidates(request: FetchRequest) -> list[str]:
    candidates = [
        request.group_id,
        f"{request.platform_id}:group:{request.group_id}",
        f"group:{request.group_id}",
    ]
    deduped = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text or text in deduped:
            continue
        deduped.append(text)
    return deduped


def _history_message_from_record(record: Any, request: FetchRequest) -> HistoryMessage | None:
    occurred_at = _normalize_datetime(_record_value(record, "created_at", "occurred_at", "timestamp"))
    if occurred_at is None or occurred_at <= request.start_at or occurred_at > request.end_at:
        return None
    sender_id = str(_record_value(record, "sender_id", "user_id", "from_user_id") or "")
    if sender_id != request.user_id:
        return None
    return HistoryMessage(
        platform_id=request.platform_id,
        group_id=request.group_id,
        sender_id=sender_id,
        sender_name=str(_record_value(record, "sender_name", "nickname", "user_name") or ""),
        message_id=str(_record_value(record, "id", "message_id") or "") or None,
        occurred_at=occurred_at,
        content=_normalize_content(_record_value(record, "content", "raw_message")),
    )


def _dedupe_key(message: HistoryMessage) -> str:
    if message.message_id:
        return f"id:{message.message_id}"
    content_key = json.dumps(message.content, ensure_ascii=False, sort_keys=True)
    return f"{message.sender_id}|{message.occurred_at.isoformat()}|{content_key}"


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
