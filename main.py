from __future__ import annotations

import importlib
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

_hot_graph = importlib.import_module(".hot_graph", package=__package__)
_utils = importlib.import_module(".hot_graph.utils", package=__package__)

HeatmapRenderer = _hot_graph.HeatmapRenderer
HistorySourceUnavailableError = _hot_graph.HistorySourceUnavailableError
HotGraphRepository = _hot_graph.HotGraphRepository
HotGraphService = _hot_graph.HotGraphService
SyncScheduler = _hot_graph.SyncScheduler
UserNotRegisteredError = _hot_graph.UserNotRegisteredError
build_history_fetcher = _hot_graph.build_history_fetcher
build_settings = _hot_graph.build_settings
format_summary = _utils.format_summary


@register("astrbot_hot_graph", "LunaRain_079", "群热力图统计插件", "0.1.9")
class HotGraphPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        base_dir = Path(__file__).resolve().parent
        self.config = config
        self.settings = build_settings(config, base_dir)
        self.repository = HotGraphRepository(self.settings.db_path)
        self.fetcher = build_history_fetcher(self.settings, context)
        self.service = HotGraphService(self.repository, self.fetcher, self.settings)
        self.renderer = HeatmapRenderer(
            self.settings.render_dir,
            self.settings.font_path,
            self.settings.render_scale,
        )
        self.scheduler = SyncScheduler(
            self.service,
            self.settings.aggregate_interval_seconds,
            logger,
        )
        if self.renderer.font_path is not None:
            logger.info("hot graph renderer font: %s", self.renderer.font_path)
        else:
            logger.warning("hot graph renderer did not find a CJK-capable font; falling back to Pillow default font")

    async def initialize(self):
        self.repository.initialize()
        logger.info(
            "hot graph settings: db_path=%s render_dir=%s render_scale=%s timezone=%s history_days=%s page_size=%s history_source_type=%s background_sync=%s",
            self.settings.db_path,
            self.settings.render_dir,
            self.settings.render_scale,
            self.settings.timezone,
            self.settings.history_days,
            self.settings.history_page_size,
            self.settings.history_source_type,
            self.settings.enable_background_sync,
        )
        if self.settings.enable_background_sync:
            self.scheduler.start()
            logger.info("hot graph background sync started")

    async def terminate(self):
        await self.scheduler.stop()

    @filter.command("registerme")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def registerme(self, event: AstrMessageEvent):
        """注册当前用户在当前群聊中的热力图统计。"""
        platform_id, group_id, user_id, display_name = self._extract_event_scope(event)
        if not group_id:
            yield event.plain_result("该插件当前只支持群聊场景。")
            return

        _, created = await self.service.register_user(
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
            display_name=display_name,
        )
        if created:
            yield event.plain_result("注册成功，已开始统计你在本群的发言热力图。")
            return
        yield event.plain_result("你已经在本群注册过了。")

    @filter.command("showme")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def showme(self, event: AstrMessageEvent):
        """查看自己在当前群内的正式热力图统计。"""
        platform_id, group_id, user_id, display_name = self._extract_event_scope(event)
        if not group_id:
            yield event.plain_result("该插件当前只支持群聊场景。")
            return

        try:
            snapshot = await self.service.get_formal_snapshot(
                platform_id=platform_id,
                group_id=group_id,
                user_id=user_id,
                display_name=display_name,
            )
            logger.debug(
                "hot graph showme snapshot ready: platform=%s group=%s user=%s total=%s active_days=%s note=%s",
                platform_id,
                group_id,
                user_id,
                snapshot.summary.total_messages,
                snapshot.summary.active_days,
                snapshot.note,
            )
        except UserNotRegisteredError as exc:
            yield event.plain_result(str(exc))
            return
        except Exception as exc:  # pragma: no cover
            logger.error("showme failed: %s", exc, exc_info=True)
            yield event.plain_result("获取热力图失败，请稍后再试。")
            return

        image_path = self.renderer.render_snapshot(snapshot)
        event.track_temporary_local_file(str(image_path))
        yield event.plain_result(
            format_summary(
                snapshot.note,
                snapshot.registration.display_name,
                snapshot.summary.total_messages,
                snapshot.summary.active_days,
                snapshot.summary.most_active_date,
                snapshot.summary.most_active_count,
                snapshot.summary.range_start,
                snapshot.summary.range_end,
            )
        )
        yield event.image_result(str(image_path))

    @filter.command("updateme")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def updateme(self, event: AstrMessageEvent):
        """临时拉取增量消息并预览热力图，不写入正式统计。"""
        platform_id, group_id, user_id, display_name = self._extract_event_scope(event)
        if not group_id:
            yield event.plain_result("该插件当前只支持群聊场景。")
            return

        try:
            snapshot = await self.service.get_preview_snapshot(
                platform_id=platform_id,
                group_id=group_id,
                user_id=user_id,
                display_name=display_name,
            )
            logger.debug(
                "hot graph updateme snapshot ready: platform=%s group=%s user=%s total=%s active_days=%s note=%s",
                platform_id,
                group_id,
                user_id,
                snapshot.summary.total_messages,
                snapshot.summary.active_days,
                snapshot.note,
            )
        except UserNotRegisteredError as exc:
            yield event.plain_result(str(exc))
            return
        except HistorySourceUnavailableError as exc:
            yield event.plain_result(f"临时刷新失败：{exc}")
            return
        except Exception as exc:  # pragma: no cover
            logger.error("updateme failed: %s", exc, exc_info=True)
            yield event.plain_result("临时刷新失败，请稍后再试。")
            return

        image_path = self.renderer.render_snapshot(snapshot)
        event.track_temporary_local_file(str(image_path))
        yield event.plain_result(
            format_summary(
                snapshot.note,
                snapshot.registration.display_name,
                snapshot.summary.total_messages,
                snapshot.summary.active_days,
                snapshot.summary.most_active_date,
                snapshot.summary.most_active_count,
                snapshot.summary.range_start,
                snapshot.summary.range_end,
            )
        )
        yield event.image_result(str(image_path))

    @staticmethod
    def _extract_event_scope(event: AstrMessageEvent) -> tuple[str, str, str, str]:
        platform_id = str(event.get_platform_id() or "")
        group_id = str(event.get_group_id() or "")
        user_id = str(event.get_sender_id() or "")
        display_name = str(event.get_sender_name() or user_id or "unknown")
        return platform_id, group_id, user_id, display_name
