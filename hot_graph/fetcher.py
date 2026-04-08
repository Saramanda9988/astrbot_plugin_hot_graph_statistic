from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .exceptions import HistorySourceUnavailableError
from .models import HistoryMessage, PluginSettings

logger = logging.getLogger(__name__)
_QQ_ONEBOT_PLATFORM_ALIASES = {
    "aiocqhttp",
    "napcat",
    "onebot",
    "onebotv11",
    "qq",
    "lagrange",
    "llbot",
    "llonebot",
}


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


class QqOneBotApiHistoryFetcher:
    def __init__(self, context: Any) -> None:
        self.context = context

    async def fetch_messages(self, request: FetchRequest) -> list[HistoryMessage]:
        if not _is_qq_onebot_platform(request.platform_id):
            raise HistorySourceUnavailableError(
                f"当前仅支持 QQ OneBot 历史拉取，收到平台: {request.platform_id or 'unknown'}"
            )

        client = _resolve_onebot_client(self.context, request.platform_id)
        if client is None:
            raise HistorySourceUnavailableError("未找到可用的 QQ OneBot 客户端。")

        start_timestamp = int(request.start_at.timestamp())
        end_timestamp = int(request.end_at.timestamp())
        page_size = max(1, min(request.page_size, 100))
        current_anchor_id: str | int | None = None
        items: list[HistoryMessage] = []
        seen_keys: set[str] = set()

        logger.debug(
            "hot graph qq history fetch start: platform=%s group=%s user=%s window=(%s, %s] page_size=%s",
            request.platform_id,
            request.group_id,
            request.user_id,
            request.start_at.isoformat(),
            request.end_at.isoformat(),
            page_size,
        )

        for page in range(1, 201):
            params: dict[str, Any] = {
                "group_id": int(request.group_id),
                "count": page_size,
                "reverseOrder": True,
            }
            if current_anchor_id is not None:
                params["message_seq"] = current_anchor_id

            result = await _call_onebot_action(client, "get_group_msg_history", **params)
            messages = _extract_onebot_messages(result)

            if not messages:
                logger.debug(
                    "hot graph qq history page empty: platform=%s group=%s page=%s anchor=%s",
                    request.platform_id,
                    request.group_id,
                    page,
                    current_anchor_id,
                )
                break

            earliest_message = _earliest_onebot_message(messages)
            earliest_time = int(earliest_message.get("time", 0) or 0)
            matched_this_page = 0

            for raw_message in messages:
                history_message = _history_message_from_onebot_record(raw_message, request)
                if history_message is None:
                    continue
                occurred_timestamp = int(history_message.occurred_at.timestamp())
                if occurred_timestamp <= start_timestamp or occurred_timestamp > end_timestamp:
                    continue
                dedupe_key = _dedupe_key(history_message)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                items.append(history_message)
                matched_this_page += 1

            next_anchor_id = _onebot_anchor_id(earliest_message)
            logger.debug(
                "hot graph qq history page result: platform=%s group=%s page=%s fetched=%s matched=%s earliest_time=%s next_anchor=%s",
                request.platform_id,
                request.group_id,
                page,
                len(messages),
                matched_this_page,
                earliest_time,
                next_anchor_id,
            )

            if earliest_time <= start_timestamp:
                break
            if next_anchor_id is None or str(next_anchor_id) == str(current_anchor_id):
                break
            if len(messages) < page_size:
                break

            current_anchor_id = next_anchor_id
            await asyncio.sleep(0.05)

        items.sort(key=lambda item: item.occurred_at)
        logger.debug(
            "hot graph qq history fetch done: platform=%s group=%s user=%s matched_total=%s",
            request.platform_id,
            request.group_id,
            request.user_id,
            len(items),
        )
        return items


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

    if source_type in {"qq_onebot_api", "context_history", "auto"} and context is not None:
        logger.info("hot graph history source: qq_onebot_api mode=%s", source_type)
        return QqOneBotApiHistoryFetcher(context)

    if source_type == "legacy_context_history" and context is not None:
        manager = getattr(context, "message_history_manager", None)
        if manager is not None:
            logger.info(
                "hot graph history source: legacy_context_history manager=%s",
                type(manager).__name__,
            )
            return ContextHistoryFetcher(manager)
        logger.warning("hot graph history source requested legacy_context_history but message_history_manager is missing")

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


def _resolve_onebot_client(context: Any, platform_id: str | None) -> Any | None:
    platform_id = str(platform_id or "").strip().lower()
    platform_manager = getattr(context, "platform_manager", None)
    get_insts = getattr(platform_manager, "get_insts", None)
    if not callable(get_insts):
        logger.debug("hot graph qq history resolve client failed: context.platform_manager.get_insts unavailable")
        return None

    platforms = list(get_insts() or [])
    logger.debug(
        "hot graph qq history resolve client: platform_id=%s platform_count=%s",
        platform_id,
        len(platforms),
    )
    fallback_client = None

    for platform in platforms:
        meta_names = _platform_meta_names(platform)
        client = _platform_client(platform)
        logger.debug(
            "hot graph qq history inspect platform: meta=%s client=%s",
            meta_names,
            type(client).__name__ if client is not None else None,
        )
        if client is None or not _is_onebot_client(client):
            continue
        if fallback_client is None:
            fallback_client = client
        if not platform_id:
            continue
        if _platform_matches_requested_id(platform_id, meta_names):
            return client

    return fallback_client


def _platform_meta_names(platform: Any) -> list[str]:
    names: list[str] = []
    for attr_name in ("metadata", "meta"):
        meta = getattr(platform, attr_name, None)
        if callable(meta):
            try:
                meta = meta()
            except Exception:
                meta = None
        if meta is None:
            continue
        for key in ("id", "name", "type"):
            value = getattr(meta, key, None)
            text = str(value or "").strip().lower()
            if text and text not in names:
                names.append(text)
    for key in ("id", "platform_id", "platform_name"):
        value = getattr(platform, key, None)
        text = str(value or "").strip().lower()
        if text and text not in names:
            names.append(text)
    class_name = type(platform).__name__.lower()
    if class_name and class_name not in names:
        names.append(class_name)
    return names


def _platform_matches_requested_id(request_platform_id: str, meta_names: list[str]) -> bool:
    if any(request_platform_id == name or request_platform_id in name for name in meta_names):
        return True
    if request_platform_id not in _QQ_ONEBOT_PLATFORM_ALIASES:
        return False
    return any(
        name in _QQ_ONEBOT_PLATFORM_ALIASES or any(alias in name for alias in _QQ_ONEBOT_PLATFORM_ALIASES)
        for name in meta_names
    )


def _is_qq_onebot_platform(platform_id: str | None) -> bool:
    platform_text = str(platform_id or "").strip().lower()
    if not platform_text:
        return False
    if platform_text in _QQ_ONEBOT_PLATFORM_ALIASES:
        return True
    return any(alias in platform_text for alias in _QQ_ONEBOT_PLATFORM_ALIASES)


def _platform_client(platform: Any) -> Any | None:
    get_client = getattr(platform, "get_client", None)
    if callable(get_client):
        try:
            client = get_client()
            if client is not None:
                return client
        except Exception:
            pass
    for attr_name in ("bot", "client", "api"):
        value = getattr(platform, attr_name, None)
        if value is not None:
            return value
    return None


def _is_onebot_client(client: Any) -> bool:
    api = getattr(client, "api", None)
    if api is not None and hasattr(api, "call_action"):
        return True
    return hasattr(client, "call_action")


async def _call_onebot_action(client: Any, action: str, **params) -> Any:
    api = getattr(client, "api", None)
    if api is not None and hasattr(api, "call_action"):
        return await api.call_action(action, **params)
    if hasattr(client, "call_action"):
        return await client.call_action(action, **params)
    raise HistorySourceUnavailableError("OneBot 客户端不支持 call_action。")


def _extract_onebot_messages(result: Any) -> list[dict]:
    if isinstance(result, dict):
        if isinstance(result.get("messages"), list):
            return result["messages"]
        data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return data["messages"]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _earliest_onebot_message(messages: list[dict]) -> dict:
    if len(messages) == 1:
        return messages[0]
    first_message = messages[0]
    last_message = messages[-1]
    first_time = int(first_message.get("time", 0) or 0)
    last_time = int(last_message.get("time", 0) or 0)
    return first_message if first_time <= last_time else last_message


def _onebot_anchor_id(message: dict) -> str | int | None:
    return (
        message.get("message_seq")
        or message.get("real_id")
        or message.get("seq")
        or message.get("message_id")
    )


def _history_message_from_onebot_record(raw_message: dict, request: FetchRequest) -> HistoryMessage | None:
    sender = raw_message.get("sender", {}) if isinstance(raw_message, dict) else {}
    sender_id = str(
        raw_message.get("user_id")
        or sender.get("user_id")
        or ""
    )
    if sender_id != request.user_id:
        return None

    occurred_at = _normalize_datetime(raw_message.get("time"))
    if occurred_at is None:
        return None

    return HistoryMessage(
        platform_id=request.platform_id,
        group_id=request.group_id,
        sender_id=sender_id,
        sender_name=str(sender.get("card") or sender.get("nickname") or sender_id),
        message_id=str(raw_message.get("message_id") or "") or None,
        occurred_at=occurred_at,
        content={
            "message": raw_message.get("message") or [],
            "raw_message": raw_message.get("raw_message") or "",
        },
    )


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
