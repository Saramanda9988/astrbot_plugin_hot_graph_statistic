from __future__ import annotations

import importlib
import re
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:
    from astrbot.api.star import StarTools
except ImportError:  # pragma: no cover
    StarTools = None

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
fetch_group_name = _hot_graph.fetch_group_name
fetch_qq_avatar = _hot_graph.fetch_qq_avatar
format_summary = _utils.format_summary
migrate_legacy_db_if_needed = _utils.migrate_legacy_db_if_needed

PLUGIN_NAME = "astrbot_hot_graph"


@register(PLUGIN_NAME, "LunaRain_079", "群热力图统计插件", "0.1.14")
class HotGraphPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        base_dir = Path(__file__).resolve().parent
        self.config = config
        self.plugin_data_dir = _resolve_plugin_data_dir()
        self.settings = build_settings(config, base_dir, self.plugin_data_dir)
        self.migrated_legacy_db_path = migrate_legacy_db_if_needed(
            config,
            base_dir,
            self.settings.db_path,
        )
        self.repository = HotGraphRepository(self.settings.db_path)
        self.fetcher = build_history_fetcher(self.settings, context)
        self.service = HotGraphService(self.repository, self.fetcher, self.settings)
        self.renderer = HeatmapRenderer(
            self.settings.render_dir,
            self.settings.font_path,
            self.settings.render_scale,
        )
        self.avatar_cache_dir = self.settings.render_dir.parent / "avatar_cache"
        self._group_name_cache: dict[str, str] = {}
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
        if self.migrated_legacy_db_path is not None:
            logger.info(
                "hot graph migrated legacy database: from=%s to=%s",
                self.migrated_legacy_db_path,
                self.settings.db_path,
            )
        logger.info(
            "hot graph settings: plugin_data_dir=%s db_path=%s render_dir=%s render_scale=%s timezone=%s history_days=%s page_size=%s history_source_type=%s background_sync=%s",
            self.plugin_data_dir,
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

        avatar_data = await fetch_qq_avatar(user_id, cache_dir=self.avatar_cache_dir)
        group_name = await self._fetch_group_name(platform_id, group_id)
        image_path = self.renderer.render_snapshot(snapshot, avatar_data=avatar_data, group_name=group_name)
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

        avatar_data = await fetch_qq_avatar(user_id, cache_dir=self.avatar_cache_dir)
        group_name = await self._fetch_group_name(platform_id, group_id)
        image_path = self.renderer.render_snapshot(snapshot, avatar_data=avatar_data, group_name=group_name)
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

    @filter.command("show")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def show(self, event: AstrMessageEvent):
        """查看被 @ 用户在当前群内的正式热力图统计。"""
        platform_id, group_id, _, _ = self._extract_event_scope(event)
        if not group_id:
            yield event.plain_result("该插件当前只支持群聊场景。")
            return

        target_user_id = self._extract_at_target(event)
        if not target_user_id:
            yield event.plain_result("请在命令中 @ 一位群成员，例如：/show @某人")
            return

        try:
            snapshot = await self.service.get_formal_snapshot(
                platform_id=platform_id,
                group_id=group_id,
                user_id=target_user_id,
            )
        except UserNotRegisteredError:
            yield event.plain_result(f"该用户（{target_user_id}）尚未注册热力图统计。")
            return
        except Exception as exc:  # pragma: no cover
            logger.error("show failed: %s", exc, exc_info=True)
            yield event.plain_result("获取热力图失败，请稍后再试。")
            return

        avatar_data = await fetch_qq_avatar(target_user_id, cache_dir=self.avatar_cache_dir)
        group_name = await self._fetch_group_name(platform_id, group_id)
        image_path = self.renderer.render_snapshot(snapshot, avatar_data=avatar_data, group_name=group_name)
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

    async def _fetch_group_name(self, platform_id: str, group_id: str) -> str | None:
        if group_id in self._group_name_cache:
            return self._group_name_cache[group_id]
        name = await fetch_group_name(self.context, platform_id, group_id)
        if name:
            self._group_name_cache[group_id] = name
        return name

    @staticmethod
    def _extract_event_scope(event: AstrMessageEvent) -> tuple[str, str, str, str]:
        platform_id = str(event.get_platform_id() or "")
        group_id = str(event.get_group_id() or "")
        user_id = str(event.get_sender_id() or "")
        display_name = str(event.get_sender_name() or user_id or "unknown")
        return platform_id, group_id, user_id, display_name

    @staticmethod
    def _extract_at_target(event: AstrMessageEvent) -> str | None:
        for component in event.message_obj.message:
            if isinstance(component, Comp.At):
                return str(component.qq)
        raw_text = str(getattr(event, "message_str", "") or "")
        cq_match = re.search(r"\[CQ:at,qq=(\d+)]", raw_text)
        if cq_match:
            return cq_match.group(1)
        plain_match = re.search(r"@(\d{5,12})", raw_text)
        if plain_match:
            return plain_match.group(1)
        return None


def _resolve_plugin_data_dir() -> Path:
    if StarTools is not None:
        try:
            plugin_data_dir = StarTools.get_data_dir()
            return Path(plugin_data_dir).resolve()
        except Exception:
            pass

    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        return Path(plugin_data_dir).resolve()
    except Exception:
        return (Path.cwd() / "data" / "plugin_data" / PLUGIN_NAME).resolve()
