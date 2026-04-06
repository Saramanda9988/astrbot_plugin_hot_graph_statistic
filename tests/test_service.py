from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from hot_graph.exceptions import UserNotRegisteredError
from hot_graph.fetcher import MockJsonHistoryFetcher
from hot_graph.models import PluginSettings
from hot_graph.repository import HotGraphRepository
from hot_graph.service import HotGraphService


def _build_service(tmp_path, history_items):
    db_path = tmp_path / "hot_graph.db"
    mock_path = tmp_path / "history.json"
    mock_path.write_text(json.dumps(history_items, ensure_ascii=False), encoding="utf-8")

    settings = PluginSettings(
        db_path=db_path,
        render_dir=tmp_path / "render",
        timezone="Asia/Shanghai",
        history_days=365,
        aggregate_interval_seconds=300,
        history_page_size=50,
        history_source_type="mock_json",
        mock_history_path=mock_path,
        enable_background_sync=False,
    )
    repository = HotGraphRepository(settings.db_path)
    repository.initialize()
    fetcher = MockJsonHistoryFetcher(mock_path)
    return HotGraphService(repository, fetcher, settings), repository


def test_registration_is_idempotent_and_unregistered_query_fails(tmp_path):
    service, repository = _build_service(tmp_path, [])

    async def scenario():
        _, created_first = await service.register_user(
            platform_id="mock-platform",
            group_id="group-1",
            user_id="user-1",
            display_name="Alice",
        )
        _, created_second = await service.register_user(
            platform_id="mock-platform",
            group_id="group-1",
            user_id="user-1",
            display_name="Alice",
        )

        assert created_first is True
        assert created_second is False
        assert len(repository.list_registered_users()) == 1

        with pytest.raises(UserNotRegisteredError):
            await service.get_formal_snapshot(
                platform_id="mock-platform",
                group_id="group-1",
                user_id="missing-user",
            )

    asyncio.run(scenario())


def test_sync_is_idempotent_and_preview_does_not_persist(tmp_path):
    history = [
        {
            "platform_id": "mock-platform",
            "group_id": "group-1",
            "sender_id": "user-1",
            "sender_name": "Alice",
            "message_id": "m1",
            "occurred_at": "2026-04-01T01:00:00+00:00",
        },
        {
            "platform_id": "mock-platform",
            "group_id": "group-1",
            "sender_id": "user-1",
            "sender_name": "Alice",
            "message_id": "m2",
            "occurred_at": "2026-04-01T02:00:00+00:00",
        },
        {
            "platform_id": "mock-platform",
            "group_id": "group-1",
            "sender_id": "other-user",
            "sender_name": "Bob",
            "message_id": "m3",
            "occurred_at": "2026-04-01T03:00:00+00:00",
        },
        {
            "platform_id": "mock-platform",
            "group_id": "group-1",
            "sender_id": "user-1",
            "sender_name": "Alice",
            "message_id": "m4",
            "occurred_at": "2026-04-02T01:00:00+00:00",
        },
    ]
    service, _ = _build_service(tmp_path, history)

    async def scenario():
        registration, _ = await service.register_user(
            platform_id="mock-platform",
            group_id="group-1",
            user_id="user-1",
            display_name="Alice",
        )

        sync_cutoff = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        result_one = await service.sync_registration(registration=registration, now=sync_cutoff)
        assert result_one.applied is True
        assert result_one.counts_applied == 2

        formal_after_first_sync = await service.get_formal_snapshot(
            platform_id="mock-platform",
            group_id="group-1",
            user_id="user-1",
        )
        assert formal_after_first_sync.summary.total_messages == 2

        result_two = await service.sync_registration(
            registration=registration,
            now=datetime(2026, 4, 1, 13, 0, tzinfo=UTC),
        )
        assert result_two.applied is True
        assert result_two.counts_applied == 0

        preview = await service.get_preview_snapshot(
            platform_id="mock-platform",
            group_id="group-1",
            user_id="user-1",
            now=datetime(2026, 4, 2, 12, 0, tzinfo=UTC),
        )
        assert preview.summary.total_messages == 3
        assert preview.is_preview is True
        assert "未写入正式统计" in (preview.note or "")

        formal_still_old = await service.get_formal_snapshot(
            platform_id="mock-platform",
            group_id="group-1",
            user_id="user-1",
            now=datetime(2026, 4, 2, 12, 0, tzinfo=UTC),
        )
        assert formal_still_old.summary.total_messages == 2

        final_sync = await service.sync_registration(
            registration=registration,
            now=datetime(2026, 4, 2, 12, 0, tzinfo=UTC),
        )
        assert final_sync.counts_applied == 1

        formal_after_final_sync = await service.get_formal_snapshot(
            platform_id="mock-platform",
            group_id="group-1",
            user_id="user-1",
            now=datetime(2026, 4, 2, 12, 0, tzinfo=UTC),
        )
        assert formal_after_final_sync.summary.total_messages == 3

    asyncio.run(scenario())
