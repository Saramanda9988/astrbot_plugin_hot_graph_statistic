from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from hot_graph.fetcher import ContextHistoryFetcher, FetchRequest


class _DictHistoryManager:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, *, platform_id, user_id, page, page_size):
        self.calls.append(
            {
                "platform_id": platform_id,
                "user_id": user_id,
                "page": page,
                "page_size": page_size,
            }
        )
        return self.pages.get(page, [])


def test_context_history_fetcher_supports_dict_records():
    manager = _DictHistoryManager(
        {
            1: [
                {
                    "message_id": "m1",
                    "sender_id": "user-1",
                    "sender_name": "Alice",
                    "timestamp": 1775502000,
                    "content": "{\"text\": \"hello\"}",
                },
                {
                    "message_id": "m2",
                    "sender_id": "other-user",
                    "sender_name": "Bob",
                    "timestamp": 1775505600,
                    "content": {"text": "ignored"},
                },
            ]
        }
    )
    fetcher = ContextHistoryFetcher(manager)
    request = FetchRequest(
        platform_id="aiocqhttp",
        group_id="168483623",
        user_id="user-1",
        start_at=datetime(2026, 4, 6, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
        page_size=50,
    )

    async def scenario():
        messages = await fetcher.fetch_messages(request)
        assert len(messages) == 1
        assert messages[0].message_id == "m1"
        assert messages[0].sender_name == "Alice"
        assert messages[0].content == {"text": "hello"}
        assert manager.calls[0]["user_id"] == "168483623"

    asyncio.run(scenario())


def test_context_history_fetcher_probes_alternate_scope_keys():
    class _ScopedHistoryManager:
        def __init__(self):
            self.calls = []

        async def get(self, *, platform_id, user_id, page, page_size):
            self.calls.append((platform_id, user_id, page, page_size))
            if user_id == "aiocqhttp:group:168483623" and page == 1:
                return [
                    {
                        "message_id": "m-alt",
                        "sender_id": "user-1",
                        "sender_name": "Alice",
                        "timestamp": 1775502000,
                        "content": {"text": "hello"},
                    }
                ]
            return []

    manager = _ScopedHistoryManager()
    fetcher = ContextHistoryFetcher(manager)
    request = FetchRequest(
        platform_id="aiocqhttp",
        group_id="168483623",
        user_id="user-1",
        start_at=datetime(2026, 4, 6, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
        page_size=50,
    )

    async def scenario():
        messages = await fetcher.fetch_messages(request)
        assert len(messages) == 1
        assert messages[0].message_id == "m-alt"
        assert [call[1] for call in manager.calls[:2]] == [
            "168483623",
            "aiocqhttp:group:168483623",
        ]

    asyncio.run(scenario())
