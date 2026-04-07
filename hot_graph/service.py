from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .exceptions import UserNotRegisteredError
from .fetcher import FetchRequest, HistoryFetcher
from .models import ActivitySnapshot, HeatmapSummary, RegisteredUser, SyncResult
from .repository import HotGraphRepository
from .utils import date_window, local_date, utc_now

CONTRIBUTION_MESSAGE_COUNT = 5


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
        start_date, end_date = date_window(now, self.settings.timezone, self.settings.history_days)
        formal_raw_counts = self.repository.load_daily_counts(
            platform_id=registration.platform_id,
            group_id=registration.group_id,
            user_id=registration.user_id,
            start_date=start_date,
            end_date=end_date,
        )
        daily_counts = await self._load_pending_raw_counts(
            registration=registration,
            formal_raw_counts=formal_raw_counts,
            state=state,
            now=now,
        )
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
            messages_seen=sum(daily_counts.values()),
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
        raw_counts = self.repository.load_daily_counts(
            platform_id=registration.platform_id,
            group_id=registration.group_id,
            user_id=registration.user_id,
            start_date=start_date,
            end_date=end_date,
        )
        contribution_counts = self._to_contribution_counts(raw_counts)
        return ActivitySnapshot(
            registration=registration,
            counts_by_date=contribution_counts,
            summary=self._summarize_counts(contribution_counts, start_date, end_date),
            is_preview=False,
            generated_at=now,
            note=f"统计口径：每 {CONTRIBUTION_MESSAGE_COUNT} 条消息记 1 次贡献。",
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
        formal_raw_counts = self.repository.load_daily_counts(
            platform_id=registration.platform_id,
            group_id=registration.group_id,
            user_id=registration.user_id,
            start_date=start_date,
            end_date=end_date,
        )
        state = self.repository.get_sync_state(
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
        )
        increment = await self._load_pending_raw_counts(
            registration=registration,
            formal_raw_counts=formal_raw_counts,
            state=state,
            now=now,
        )
        merged_raw = dict(formal_raw_counts)
        for stat_date, count in increment.items():
            merged_raw[stat_date] = merged_raw.get(stat_date, 0) + count
        contribution_counts = self._to_contribution_counts(merged_raw)
        note = f"临时预览：本次结果未写入正式统计。统计口径：每 {CONTRIBUTION_MESSAGE_COUNT} 条消息记 1 次贡献。"
        if not increment:
            note = f"临时预览：自上次正式同步以来没有新的有效消息。统计口径：每 {CONTRIBUTION_MESSAGE_COUNT} 条消息记 1 次贡献。"
        return ActivitySnapshot(
            registration=registration,
            counts_by_date=contribution_counts,
            summary=self._summarize_counts(contribution_counts, start_date, end_date),
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

    async def _load_pending_raw_counts(
        self,
        *,
        registration: RegisteredUser,
        formal_raw_counts: dict,
        state,
        now,
    ) -> dict:
        start_at = state.last_synced_at if state and state.last_synced_at else now - timedelta(days=self.settings.history_days)
        increment = await self._fetch_raw_counts(
            registration=registration,
            start_at=start_at,
            end_at=now,
        )
        if increment or state is None or state.last_synced_at is None:
            return increment

        full_window_counts = await self._fetch_raw_counts(
            registration=registration,
            start_at=now - timedelta(days=self.settings.history_days),
            end_at=now,
        )
        return self._subtract_raw_counts(full_window_counts, formal_raw_counts)

    async def _fetch_raw_counts(
        self,
        *,
        registration: RegisteredUser,
        start_at,
        end_at,
    ) -> dict:
        request = FetchRequest(
            platform_id=registration.platform_id,
            group_id=registration.group_id,
            user_id=registration.user_id,
            start_at=start_at,
            end_at=end_at,
            page_size=self.settings.history_page_size,
        )
        messages = await self.history_fetcher.fetch_messages(request)
        return self._aggregate_messages(messages)

    @staticmethod
    def _subtract_raw_counts(current_raw_counts, persisted_raw_counts):
        increment = {}
        for stat_date, current_count in current_raw_counts.items():
            delta = current_count - persisted_raw_counts.get(stat_date, 0)
            if delta > 0:
                increment[stat_date] = delta
        return increment

    @staticmethod
    def _to_contribution_counts(raw_counts_by_date):
        return {
            stat_date: raw_count // CONTRIBUTION_MESSAGE_COUNT
            for stat_date, raw_count in raw_counts_by_date.items()
        }

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
