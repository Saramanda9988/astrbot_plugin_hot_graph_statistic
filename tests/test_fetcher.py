from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from hot_graph.fetcher import (
    ContextHistoryFetcher,
    FetchRequest,
    HistorySourceUnavailableError,
    QqOneBotApiHistoryFetcher,
    build_history_fetcher,
)
from hot_graph.models import PluginSettings


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
        page_size=2,
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
        page_size=2,
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


class _FakeApi:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def call_action(self, action, **params):
        self.calls.append((action, params))
        return self.responses[len(self.calls) - 1]


class _FakeClient:
    def __init__(self, responses):
        self.api = _FakeApi(responses)


class _FakePlatformMeta:
    def __init__(self, *, id="aiocqhttp", name="aiocqhttp", type="aiocqhttp"):
        self.id = id
        self.name = name
        self.type = type


class _FakePlatform:
    def __init__(self, client, meta=None):
        self._client = client
        self.metadata = meta or _FakePlatformMeta()

    def get_client(self):
        return self._client


class _FakePlatformManager:
    def __init__(self, platforms):
        self._platforms = platforms

    def get_insts(self):
        return self._platforms


class _FakeContext:
    def __init__(self, platforms):
        self.platform_manager = _FakePlatformManager(platforms)


def test_qq_onebot_history_fetcher_fetches_group_history_via_api():
    responses = [
        {
            "messages": [
                {
                    "message_id": 300,
                    "message_seq": 300,
                    "time": 1775505600,
                    "sender": {"user_id": "user-1", "nickname": "Alice", "card": ""},
                    "message": [{"type": "text", "data": {"text": "ignored latest"}}],
                    "raw_message": "ignored latest",
                },
                {
                    "message_id": 200,
                    "message_seq": 200,
                    "time": 1775502000,
                    "sender": {"user_id": "user-1", "nickname": "Alice", "card": ""},
                    "message": [{"type": "text", "data": {"text": "hello"}}],
                    "raw_message": "hello",
                },
            ]
        },
        {"messages": []},
    ]
    client = _FakeClient(responses)
    context = _FakeContext([_FakePlatform(client)])
    fetcher = QqOneBotApiHistoryFetcher(context)
    request = FetchRequest(
        platform_id="aiocqhttp",
        group_id="168483623",
        user_id="user-1",
        start_at=datetime(2026, 4, 6, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
        page_size=2,
    )

    async def scenario():
        messages = await fetcher.fetch_messages(request)
        assert len(messages) == 2
        assert messages[0].message_id == "200"
        assert messages[1].message_id == "300"
        assert client.api.calls[0][0] == "get_group_msg_history"
        assert client.api.calls[0][1]["group_id"] == 168483623
        assert client.api.calls[0][1]["count"] == 2
        assert client.api.calls[1][1]["message_seq"] == 200

    asyncio.run(scenario())


def test_build_history_fetcher_prefers_qq_onebot_api_for_auto(tmp_path):
    settings = PluginSettings(
        db_path=tmp_path / "db.sqlite3",
        render_dir=tmp_path / "render",
        history_source_type="auto",
        mock_history_path=None,
        enable_background_sync=False,
    )
    context = _FakeContext([_FakePlatform(_FakeClient([{"messages": []}]))])

    fetcher = build_history_fetcher(settings, context)

    assert isinstance(fetcher, QqOneBotApiHistoryFetcher)


def test_qq_onebot_history_fetcher_accepts_napcat_platform_id():
    responses = [{"messages": []}]
    client = _FakeClient(responses)
    context = _FakeContext([_FakePlatform(client, meta=_FakePlatformMeta(id="napcat", name="napcat", type="aiocqhttp"))])
    fetcher = QqOneBotApiHistoryFetcher(context)
    request = FetchRequest(
        platform_id="napcat",
        group_id="168483623",
        user_id="user-1",
        start_at=datetime(2026, 4, 6, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
        page_size=20,
    )

    async def scenario():
        messages = await fetcher.fetch_messages(request)
        assert messages == []
        assert client.api.calls[0][0] == "get_group_msg_history"

    asyncio.run(scenario())


def test_qq_onebot_history_fetcher_accepts_custom_onebot_platform_id():
    responses = [{"messages": []}]
    client = _FakeClient(responses)
    context = _FakeContext([_FakePlatform(client, meta=_FakePlatformMeta(id="luna", name="luna", type="aiocqhttp"))])
    fetcher = QqOneBotApiHistoryFetcher(context)
    request = FetchRequest(
        platform_id="luna",
        group_id="168483623",
        user_id="user-1",
        start_at=datetime(2026, 4, 6, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
        page_size=20,
    )

    async def scenario():
        messages = await fetcher.fetch_messages(request)
        assert messages == []
        assert client.api.calls[0][0] == "get_group_msg_history"

    asyncio.run(scenario())


def test_qq_onebot_history_fetcher_accepts_single_llbot_client_with_custom_platform_id():
    responses = [
        {"data": {"app_name": "LLOneBot"}},
        {"messages": []},
    ]
    client = _FakeClient(responses)
    context = _FakeContext([_FakePlatform(client, meta=_FakePlatformMeta(id="opaque", name="opaque", type="opaque"))])
    fetcher = QqOneBotApiHistoryFetcher(context)
    request = FetchRequest(
        platform_id="luna",
        group_id="168483623",
        user_id="user-1",
        start_at=datetime(2026, 4, 6, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
        page_size=20,
    )

    async def scenario():
        messages = await fetcher.fetch_messages(request)
        assert messages == []
        assert client.api.calls[0][0] == "get_version_info"
        assert client.api.calls[1][0] == "get_group_msg_history"

    asyncio.run(scenario())


def test_qq_onebot_history_fetcher_rejects_unknown_non_onebot_platform_id():
    responses = [{"app_name": "NapCat"}]
    client = _FakeClient(responses)
    context = _FakeContext([_FakePlatform(client, meta=_FakePlatformMeta(id="luna", name="luna", type="aiocqhttp"))])
    fetcher = QqOneBotApiHistoryFetcher(context)
    request = FetchRequest(
        platform_id="telegram-custom",
        group_id="168483623",
        user_id="user-1",
        start_at=datetime(2026, 4, 6, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
        page_size=20,
    )

    async def scenario():
        try:
            await fetcher.fetch_messages(request)
        except HistorySourceUnavailableError as exc:
            assert "telegram-custom" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected HistorySourceUnavailableError")

    asyncio.run(scenario())
