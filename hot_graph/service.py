from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .exceptions import UserNotRegisteredError
from .fetcher import FetchRequest, HistoryFetcher
from .models import ActivitySnapshot, HeatmapSummary, RegisteredUser, SyncResult
from .repository import HotGraphRepository
from .utils import date_window, local_date, utc_now


class HotGraphService:
    def __init__(
        self,
        repository: HotGraphRepository,
        history_fetcher: HistoryFetcher,
        settings,
    ) -> None:
        self.repository = repository
        self.history_fetcher = history_fetcher
        self.settings = settings

    async def register_user(
        self,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
        display_name: str,
    ) -> tuple[RegisteredUser, bool]:
        return self.repository.register_user(
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
            display_name=display_name,
        )

    async def sync_all_registered_users(self, now=None) -> list[SyncResult]:
        results = []
        for registration in self.repository.list_registered_users():
            results.append(await self.sync_registration(registration=registration, now=now))
        return results

    async def sync_registration(self, *, registration: RegisteredUser, now=None) -> SyncResult:
        now = now or utc_now()
        state = self.repository.get_sync_state(
            platform_id=registration.platform_id,
            group_id=registration.group_id,
            user_id=registration.user_id,
        )
        start_at = state.last_synced_at if state and state.last_synced_at else now - timedelta(days=self.settings.history_days)
        request = FetchRequest(
            platform_id=registration.platform_id,
            group_id=registration.group_id,
            user_id=registration.user_id,
            start_at=start_at,
            end_at=now,
            page_size=self.settings.history_page_size,
        )
        messages = await self.history_fetcher.fetch_messages(request)
        daily_counts = self._aggregate_messages(messages)
        applied = self.repository.apply_sync_batch(
            registration=registration,
            daily_counts=daily_counts,
            expected_last_synced_at=state.last_synced_at if state else None,
            next_synced_at=now,
        )
        return SyncResult(
            registration=registration,
            synced_from=state.last_synced_at if state else None,
            synced_to=now,
            messages_seen=len(messages),
            counts_applied=sum(daily_counts.values()),
            applied=applied,
        )

    async def get_formal_snapshot(
        self,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
        display_name: str | None = None,
        now=None,
    ) -> ActivitySnapshot:
        registration = self._require_registration(
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
        )
        if display_name:
            registration = RegisteredUser(
                id=registration.id,
                platform_id=registration.platform_id,
                group_id=registration.group_id,
                user_id=registration.user_id,
                display_name=display_name,
                registered_at=registration.registered_at,
            )
        now = now or utc_now()
        start_date, end_date = date_window(now, self.settings.timezone, self.settings.history_days)
        counts = self.repository.load_daily_counts(
            platform_id=registration.platform_id,
            group_id=registration.group_id,
            user_id=registration.user_id,
            start_date=start_date,
            end_date=end_date,
        )
        return ActivitySnapshot(
            registration=registration,
            counts_by_date=counts,
            summary=self._summarize_counts(counts, start_date, end_date),
            is_preview=False,
            generated_at=now,
        )

    async def get_preview_snapshot(
        self,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
        display_name: str | None = None,
        now=None,
    ) -> ActivitySnapshot:
        formal = await self.get_formal_snapshot(
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
            display_name=display_name,
            now=now,
        )
        now = now or utc_now()
        state = self.repository.get_sync_state(
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
        )
        start_at = state.last_synced_at if state and state.last_synced_at else now - timedelta(days=self.settings.history_days)
        request = FetchRequest(
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
            start_at=start_at,
            end_at=now,
            page_size=self.settings.history_page_size,
        )
        messages = await self.history_fetcher.fetch_messages(request)
        increment = self._aggregate_messages(messages)
        merged = dict(formal.counts_by_date)
        for stat_date, count in increment.items():
            merged[stat_date] = merged.get(stat_date, 0) + count
        note = "临时预览：本次结果未写入正式统计。"
        if not increment:
            note = "临时预览：自上次正式同步以来没有新的有效消息。"
        return ActivitySnapshot(
            registration=formal.registration,
            counts_by_date=merged,
            summary=self._summarize_counts(merged, formal.summary.range_start, formal.summary.range_end),
            is_preview=True,
            generated_at=now,
            note=note,
        )

    def _require_registration(
        self,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
    ) -> RegisteredUser:
        registration = self.repository.get_registered_user(
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
        )
        if registration is None:
            raise UserNotRegisteredError("请先执行 /registerme 注册当前群聊统计。")
        return registration

    def _aggregate_messages(self, messages) -> dict:
        counts = defaultdict(int)
        for message in messages:
            stat_date = local_date(message.occurred_at, self.settings.timezone)
            counts[stat_date] += 1
        return dict(counts)

    @staticmethod
    def _summarize_counts(counts_by_date, start_date, end_date) -> HeatmapSummary:
        total_messages = sum(counts_by_date.values())
        active_days = sum(1 for value in counts_by_date.values() if value > 0)
        if counts_by_date:
            most_active_date, most_active_count = max(
                counts_by_date.items(),
                key=lambda item: (item[1], item[0]),
            )
        else:
            most_active_date, most_active_count = None, 0
        return HeatmapSummary(
            range_start=start_date,
            range_end=end_date,
            total_messages=total_messages,
            active_days=active_days,
            most_active_date=most_active_date,
            most_active_count=most_active_count,
        )
