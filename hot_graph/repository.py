from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import RegisteredUser, SyncState
from .utils import ensure_parent, parse_datetime, to_iso, utc_now


class HotGraphRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        ensure_parent(self.db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS registered_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(platform_id, group_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS user_daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    stat_date TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(platform_id, group_id, user_id, stat_date)
                );

                CREATE TABLE IF NOT EXISTS sync_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL DEFAULT 'default',
                    last_synced_at TEXT,
                    last_message_cursor TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(platform_id, group_id, user_id, scope_key)
                );
                """
            )

    def register_user(
        self,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
        display_name: str,
    ) -> tuple[RegisteredUser, bool]:
        now = utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, platform_id, group_id, user_id, display_name, registered_at
                FROM registered_users
                WHERE platform_id = ? AND group_id = ? AND user_id = ?
                """,
                (platform_id, group_id, user_id),
            ).fetchone()
            if row:
                return self._row_to_registered_user(row), False

            conn.execute(
                """
                INSERT INTO registered_users (
                    platform_id, group_id, user_id, display_name, registered_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    platform_id,
                    group_id,
                    user_id,
                    display_name,
                    to_iso(now),
                    to_iso(now),
                ),
            )
        user = self.get_registered_user(platform_id=platform_id, group_id=group_id, user_id=user_id)
        if user is None:
            raise RuntimeError("Registration insert succeeded but row was not found.")
        return user, True

    def get_registered_user(
        self,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
    ) -> RegisteredUser | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, platform_id, group_id, user_id, display_name, registered_at
                FROM registered_users
                WHERE platform_id = ? AND group_id = ? AND user_id = ?
                """,
                (platform_id, group_id, user_id),
            ).fetchone()
        return self._row_to_registered_user(row) if row else None

    def list_registered_users(self) -> list[RegisteredUser]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, platform_id, group_id, user_id, display_name, registered_at
                FROM registered_users
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._row_to_registered_user(row) for row in rows]

    def get_sync_state(
        self,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
        scope_key: str = "default",
    ) -> SyncState | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, platform_id, group_id, user_id, scope_key, last_synced_at, last_message_cursor, updated_at
                FROM sync_state
                WHERE platform_id = ? AND group_id = ? AND user_id = ? AND scope_key = ?
                """,
                (platform_id, group_id, user_id, scope_key),
            ).fetchone()
        return self._row_to_sync_state(row) if row else None

    def load_daily_counts(
        self,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[date, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT stat_date, message_count
                FROM user_daily_stats
                WHERE platform_id = ? AND group_id = ? AND user_id = ?
                  AND stat_date >= ? AND stat_date <= ?
                ORDER BY stat_date ASC
                """,
                (
                    platform_id,
                    group_id,
                    user_id,
                    start_date.isoformat(),
                    end_date.isoformat(),
                ),
            ).fetchall()
        return {date.fromisoformat(row["stat_date"]): int(row["message_count"]) for row in rows}

    def apply_sync_batch(
        self,
        *,
        registration: RegisteredUser,
        daily_counts: dict[date, int],
        expected_last_synced_at: datetime | None,
        next_synced_at: datetime,
        last_message_cursor: str | None = None,
    ) -> bool:
        expected_iso = to_iso(expected_last_synced_at)
        now_iso = to_iso(utc_now())
        next_iso = to_iso(next_synced_at)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT last_synced_at
                FROM sync_state
                WHERE platform_id = ? AND group_id = ? AND user_id = ? AND scope_key = 'default'
                """,
                (registration.platform_id, registration.group_id, registration.user_id),
            ).fetchone()
            current_iso = row["last_synced_at"] if row else None
            if current_iso != expected_iso:
                conn.rollback()
                return False

            for stat_date, count in daily_counts.items():
                conn.execute(
                    """
                    INSERT INTO user_daily_stats (
                        platform_id, group_id, user_id, stat_date, message_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform_id, group_id, user_id, stat_date)
                    DO UPDATE SET
                        message_count = user_daily_stats.message_count + excluded.message_count,
                        updated_at = excluded.updated_at
                    """,
                    (
                        registration.platform_id,
                        registration.group_id,
                        registration.user_id,
                        stat_date.isoformat(),
                        count,
                        now_iso,
                    ),
                )

            conn.execute(
                """
                INSERT INTO sync_state (
                    platform_id, group_id, user_id, scope_key, last_synced_at, last_message_cursor, updated_at
                ) VALUES (?, ?, ?, 'default', ?, ?, ?)
                ON CONFLICT(platform_id, group_id, user_id, scope_key)
                DO UPDATE SET
                    last_synced_at = excluded.last_synced_at,
                    last_message_cursor = excluded.last_message_cursor,
                    updated_at = excluded.updated_at
                """,
                (
                    registration.platform_id,
                    registration.group_id,
                    registration.user_id,
                    next_iso,
                    last_message_cursor,
                    now_iso,
                ),
            )
            conn.commit()
        return True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_registered_user(row: sqlite3.Row) -> RegisteredUser:
        registered_at = parse_datetime(row["registered_at"])
        if registered_at is None:
            raise ValueError("registered_at cannot be null")
        return RegisteredUser(
            id=int(row["id"]) if row["id"] is not None else None,
            platform_id=str(row["platform_id"]),
            group_id=str(row["group_id"]),
            user_id=str(row["user_id"]),
            display_name=str(row["display_name"]),
            registered_at=registered_at,
        )

    @staticmethod
    def _row_to_sync_state(row: sqlite3.Row) -> SyncState:
        updated_at = parse_datetime(row["updated_at"])
        if updated_at is None:
            raise ValueError("updated_at cannot be null")
        return SyncState(
            id=int(row["id"]) if row["id"] is not None else None,
            platform_id=str(row["platform_id"]),
            group_id=str(row["group_id"]),
            user_id=str(row["user_id"]),
            scope_key=str(row["scope_key"]),
            last_synced_at=parse_datetime(row["last_synced_at"]),
            last_message_cursor=row["last_message_cursor"],
            updated_at=updated_at,
        )
