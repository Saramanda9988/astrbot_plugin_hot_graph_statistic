from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from hot_graph.models import ActivitySnapshot, HeatmapSummary, RegisteredUser
from hot_graph.renderer import HeatmapRenderer, _resolve_font_path


def _build_snapshot(display_name: str = "图_Official") -> ActivitySnapshot:
    registration = RegisteredUser(
        id=1,
        platform_id="mock-platform",
        group_id="186483623",
        user_id="user-1",
        display_name=display_name,
        registered_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    summary = HeatmapSummary(
        range_start=date(2025, 4, 8),
        range_end=date(2026, 4, 7),
        total_messages=5,
        active_days=1,
        most_active_date=date(2026, 4, 7),
        most_active_count=5,
    )
    return ActivitySnapshot(
        registration=registration,
        counts_by_date={date(2026, 4, 7): 5},
        summary=summary,
        is_preview=True,
        generated_at=datetime(2026, 4, 7, tzinfo=UTC),
        note="预览包含 5 条消息，1 条新记录",
    )


def test_resolve_font_path_prefers_configured_font(tmp_path):
    configured = tmp_path / "custom-font.ttf"
    configured.write_bytes(b"font-placeholder")

    resolved = _resolve_font_path(
        configured_font_path=configured,
        search_roots=[tmp_path / "unused"],
        candidate_names=("missing.ttf",),
        recursive_patterns=(),
    )

    assert resolved == configured


def test_resolve_font_path_scans_search_roots(tmp_path):
    font_dir = tmp_path / "fonts" / "nested"
    font_dir.mkdir(parents=True)
    discovered = font_dir / "NotoSansCJK-Regular.ttc"
    discovered.write_bytes(b"font-placeholder")

    resolved = _resolve_font_path(
        configured_font_path=None,
        search_roots=[tmp_path / "fonts"],
        candidate_names=("missing.ttf",),
        recursive_patterns=("NotoSansCJK-Regular.ttc",),
    )

    assert resolved == discovered


def test_renderer_renders_snapshot_with_detected_font(tmp_path):
    font_path = _resolve_font_path()
    if font_path is None:
        pytest.skip("No detectable CJK font in test environment")

    renderer = HeatmapRenderer(tmp_path, font_path=font_path)
    output = renderer.render_snapshot(_build_snapshot())

    assert renderer.font_path == font_path
    assert output.exists()
    assert output.stat().st_size > 0
