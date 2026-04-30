from __future__ import annotations

from pathlib import Path

from hot_graph.utils import build_settings, migrate_legacy_db_if_needed


def test_build_settings_stores_default_persistent_files_under_plugin_data(tmp_path):
    base_dir = tmp_path / "plugin_root"
    storage_dir = tmp_path / "astrbot_data" / "plugin_data" / "astrbot_hot_graph"

    settings = build_settings({}, base_dir, storage_dir)

    assert settings.db_path == (storage_dir / "hot_graph.db").resolve()
    assert settings.render_dir == (storage_dir / "render").resolve()


def test_build_settings_maps_legacy_default_relative_values_to_new_plugin_data_paths(tmp_path):
    base_dir = tmp_path / "plugin_root"
    storage_dir = tmp_path / "astrbot_data" / "plugin_data" / "astrbot_hot_graph"
    config = {
        "db_path": "data/hot_graph.db",
        "render_dir": "data/hot_graph/render",
    }

    settings = build_settings(config, base_dir, storage_dir)

    assert settings.db_path == (storage_dir / "hot_graph.db").resolve()
    assert settings.render_dir == (storage_dir / "render").resolve()


def test_build_settings_keeps_non_storage_relative_paths_under_plugin_root(tmp_path):
    base_dir = tmp_path / "plugin_root"
    storage_dir = tmp_path / "astrbot_data" / "plugin_data" / "astrbot_hot_graph"
    config = {
        "db_path": "custom/hot_graph.db",
        "render_dir": "cache/render",
        "font_path": "fonts/test.ttf",
        "mock_history_path": "fixtures/history.json",
    }

    settings = build_settings(config, base_dir, storage_dir)

    assert settings.db_path == (storage_dir / "custom" / "hot_graph.db").resolve()
    assert settings.render_dir == (storage_dir / "cache" / "render").resolve()
    assert settings.font_path == (base_dir / "fonts" / "test.ttf").resolve()
    assert settings.mock_history_path == (base_dir / "fixtures" / "history.json").resolve()


def test_migrate_legacy_db_if_needed_copies_old_relative_db_to_plugin_data(tmp_path):
    base_dir = tmp_path / "plugin_root"
    legacy_db_path = base_dir / "data" / "hot_graph.db"
    legacy_db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_db_path.write_text("legacy-db", encoding="utf-8")
    Path(f"{legacy_db_path}-wal").write_text("wal", encoding="utf-8")

    target_db_path = tmp_path / "astrbot_data" / "plugin_data" / "astrbot_hot_graph" / "hot_graph.db"

    migrated_from = migrate_legacy_db_if_needed({}, base_dir, target_db_path)

    assert migrated_from == legacy_db_path.resolve()
    assert target_db_path.read_text(encoding="utf-8") == "legacy-db"
    assert Path(f"{target_db_path}-wal").read_text(encoding="utf-8") == "wal"


def test_migrate_legacy_db_if_needed_skips_when_new_db_exists(tmp_path):
    base_dir = tmp_path / "plugin_root"
    legacy_db_path = base_dir / "data" / "hot_graph.db"
    legacy_db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_db_path.write_text("legacy-db", encoding="utf-8")

    target_db_path = tmp_path / "astrbot_data" / "plugin_data" / "astrbot_hot_graph" / "hot_graph.db"
    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    target_db_path.write_text("new-db", encoding="utf-8")

    migrated_from = migrate_legacy_db_if_needed({}, base_dir, target_db_path)

    assert migrated_from is None
    assert target_db_path.read_text(encoding="utf-8") == "new-db"
