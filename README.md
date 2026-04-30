# 群热力图统计插件

统计已注册用户在群聊中的按日消息数，并渲染为类似 GitHub 贡献图的热力图。

> _看看群里谁贡(水)献(群)最多_

## 功能特性

- **GitHub 风格热力图** — 按日统计群聊消息，生成类似 GitHub Contribution Graph 的可视化图片
- **后台定时同步** — 可配置的后台任务自动拉取并聚合群聊历史消息
- **预览模式** — 支持临时拉取增量消息预览热力图，不写入正式统计
- **CJK 字体自动检测** — 自动扫描系统字体目录，查找可用的中日韩字体

## 命令列表

| 命令 | 说明 |
|------|------|
| `/registerme` | 注册当前用户在当前群聊中的热力图统计 |
| `/showme` | 查看自己在当前群内的正式热力图 |
| `/updateme` | 临时拉取增量消息并预览热力图，不写入正式统计 |
| `/show @某人` | 查看被 @ 用户在当前群内的热力图（需对方已注册，@请使用im平台的@功能） |

> 所有命令仅在群聊场景下可用。

## 数据持久化

| 路径 | 说明 |
|------|------|
| `data/plugin_data/astrbot_hot_graph/hot_graph.db` | SQLite 数据库，存储用户注册信息、每日消息计数、同步状态 |
| `data/plugin_data/astrbot_hot_graph/render/` | 热力图临时图片输出目录 |
| `data/plugin_data/astrbot_hot_graph/avatar_cache/` | 用户头像磁盘缓存目录（24 小时过期） |

> 默认持久化目录位于 AstrBot 的 `plugin_data` 下，卸载插件时只要不勾选“删除持久化数据”，重装后会继续复用这些数据。
>
> 从旧版本升级时，如果检测到插件源码目录下的旧 `data/hot_graph.db`，会在首次启动时自动迁移到新的持久化目录。

## 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `db_path` | string | `hot_graph.db` | SQLite 数据库路径；相对路径基于 `data/plugin_data/astrbot_hot_graph/` |
| `render_dir` | string | `render` | 热力图临时图片输出目录；相对路径基于 `data/plugin_data/astrbot_hot_graph/` |
| `font_path` | string | *(空)* | 自定义字体文件路径（ttf/ttc/otf） |
| `render_scale` | int | `2` | 图片渲染倍率，值越大越清晰 |
| `timezone` | string | `Asia/Shanghai` | 统计使用的时区 |
| `history_days` | int | `365` | 展示和初次同步的历史天数 |
| `aggregate_interval_seconds` | int | `300` | 后台正式同步周期（秒） |
| `history_page_size` | int | `200` | 每次读取历史消息的分页大小 |
| `history_source_type` | string | `auto` | 历史消息来源类型：`auto` / `qq_onebot_api` / `legacy_context_history` / `mock_json` / `disabled` |
| `mock_history_path` | string | *(空)* | 当 `history_source_type=mock_json` 时使用的 JSON 文件路径 |
| `enable_background_sync` | bool | `true` | 是否启用后台定时正式同步 |

## 支持平台

- QQ（通过 aiocqhttp / NapCat / Lagrange / LLOneBot 等 OneBot v11 实现）

## 依赖

- `Pillow>=10`
- `aiohttp>=3`

## 相关链接

- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [插件开发文档（中文）](https://docs.astrbot.app/dev/star/plugin-new.html)
- [插件开发文档（English）](https://docs.astrbot.app/en/dev/star/plugin-new.html)
