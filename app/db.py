import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional


DB_PATH = "/app/config/data.db"


def ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def safe_json_loads(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


def merge_json_object(base: Any, patch: Any) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(base, dict):
        merged.update(base)
    if isinstance(patch, dict):
        merged.update(patch)
    return merged


def sqlite_row_to_dict(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def ensure_db() -> None:
    ensure_parent(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS local_files (path_hash TEXT PRIMARY KEY, relative_path TEXT)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_files (
            task_name TEXT NOT NULL,
            local_rel_path TEXT NOT NULL,
            remote_rel_path TEXT NOT NULL,
            remote_modified TEXT,
            file_size INTEGER DEFAULT 0,
            PRIMARY KEY (task_name, local_rel_path)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_dirs (
            task_name TEXT NOT NULL,
            dir_rel_path TEXT NOT NULL,
            remote_modified TEXT,
            PRIMARY KEY (task_name, dir_rel_path)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL DEFAULT 'manual',
            source_name TEXT NOT NULL DEFAULT '',
            channel_name TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL DEFAULT '',
            link_url TEXT NOT NULL DEFAULT '',
            link_type TEXT NOT NULL DEFAULT 'unknown',
            message_url TEXT NOT NULL DEFAULT '',
            quality TEXT NOT NULL DEFAULT '',
            year TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL,
            published_at TEXT NOT NULL DEFAULT '',
            last_seen_at TEXT NOT NULL DEFAULT '',
            extra_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            link_url TEXT NOT NULL DEFAULT '',
            link_type TEXT NOT NULL DEFAULT '',
            folder_id TEXT NOT NULL DEFAULT '',
            savepath TEXT NOT NULL DEFAULT '',
            sharetitle TEXT NOT NULL DEFAULT '',
            monitor_task_name TEXT NOT NULL DEFAULT '',
            refresh_delay_seconds INTEGER NOT NULL DEFAULT 0,
            auto_refresh INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            status_detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            last_triggered_at TEXT NOT NULL DEFAULT '',
            response_json TEXT NOT NULL DEFAULT '{}',
            extra_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_task_state (
            task_name TEXT PRIMARY KEY,
            media_type TEXT NOT NULL DEFAULT 'movie',
            status TEXT NOT NULL DEFAULT 'idle',
            progress INTEGER NOT NULL DEFAULT 0,
            detail TEXT NOT NULL DEFAULT '',
            last_run_at TEXT NOT NULL DEFAULT '',
            last_success_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            last_episode INTEGER NOT NULL DEFAULT 0,
            total_episodes INTEGER NOT NULL DEFAULT 0,
            matched_resource_id INTEGER NOT NULL DEFAULT 0,
            matched_resource_title TEXT NOT NULL DEFAULT '',
            matched_score INTEGER NOT NULL DEFAULT 0,
            queued_job_id INTEGER NOT NULL DEFAULT 0,
            stats_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_channel_search_watermarks (
            task_name TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            last_post_cursor INTEGER NOT NULL DEFAULT 0,
            last_published_at TEXT NOT NULL DEFAULT '',
            last_run_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (task_name, channel_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_channel_support_stats (
            channel_id TEXT PRIMARY KEY,
            channel_name TEXT NOT NULL DEFAULT '',
            searched_runs INTEGER NOT NULL DEFAULT 0,
            matched_runs INTEGER NOT NULL DEFAULT 0,
            matched_items INTEGER NOT NULL DEFAULT 0,
            error_runs INTEGER NOT NULL DEFAULT 0,
            incremental_stop_hits INTEGER NOT NULL DEFAULT 0,
            pages_scanned INTEGER NOT NULL DEFAULT 0,
            last_task_name TEXT NOT NULL DEFAULT '',
            last_provider TEXT NOT NULL DEFAULT '',
            last_trigger TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            last_searched_at TEXT NOT NULL DEFAULT '',
            last_matched_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            resource_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL DEFAULT 0,
            media_type TEXT NOT NULL DEFAULT 'movie',
            season INTEGER NOT NULL DEFAULT 0,
            episode INTEGER NOT NULL DEFAULT 0,
            total_episodes INTEGER NOT NULL DEFAULT 0,
            score INTEGER NOT NULL DEFAULT 0,
            matched_at TEXT NOT NULL,
            UNIQUE(task_name, resource_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_episode_ledger (
            task_name TEXT NOT NULL,
            episode INTEGER NOT NULL,
            season INTEGER NOT NULL DEFAULT 0,
            media_type TEXT NOT NULL DEFAULT 'tv',
            best_score INTEGER NOT NULL DEFAULT 0,
            best_resolution INTEGER NOT NULL DEFAULT 0,
            source_fp TEXT NOT NULL DEFAULT '',
            content_fp TEXT NOT NULL DEFAULT '',
            link_type TEXT NOT NULL DEFAULT '',
            link_url TEXT NOT NULL DEFAULT '',
            resource_id INTEGER NOT NULL DEFAULT 0,
            job_id INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            first_seen_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (task_name, episode)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS share_entries_cache (
            cache_key TEXT PRIMARY KEY,
            share_code TEXT NOT NULL DEFAULT '',
            receive_code TEXT NOT NULL DEFAULT '',
            cid TEXT NOT NULL DEFAULT '0',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_dedupe (
            dedupe_key TEXT PRIMARY KEY,
            scene TEXT NOT NULL DEFAULT '',
            task_name TEXT NOT NULL DEFAULT '',
            episode INTEGER NOT NULL DEFAULT 0,
            savepath TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute("PRAGMA table_info(resource_jobs)")
    job_columns = {str(row[1]) for row in cursor.fetchall()}
    if "extra_json" not in job_columns:
        cursor.execute("ALTER TABLE resource_jobs ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resource_items_link ON resource_items(link_url) WHERE link_url <> ''"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_message_url ON resource_items(message_url) WHERE message_url <> ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_title_source ON resource_items(title, source_name, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_created_at ON resource_items(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_published_created ON resource_items(published_at DESC, created_at DESC, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_source_type ON resource_items(source_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_channel_name ON resource_items(channel_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_source_channel ON resource_items(source_type, channel_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_source_channel_created ON resource_items(source_type, channel_name, created_at DESC, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_status ON resource_items(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_status_created ON resource_items(status, created_at DESC, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_jobs_created_at ON resource_jobs(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_jobs_status ON resource_jobs(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscription_state_status ON subscription_task_state(status)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_channel_watermarks_updated_at "
        "ON subscription_channel_search_watermarks(updated_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_channel_support_updated_at "
        "ON subscription_channel_support_stats(updated_at DESC)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscription_matches_task ON subscription_matches(task_name, matched_at DESC)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_episode_ledger_task_status ON subscription_episode_ledger(task_name, status)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_share_entries_cache_expires_at ON share_entries_cache(expires_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_share_entries_cache_share_cid ON share_entries_cache(share_code, cid)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notification_dedupe_expires_at ON notification_dedupe(expires_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notification_dedupe_scene ON notification_dedupe(scene, task_name)")
    cursor.execute(
        """
        SELECT id, last_seen_at, extra_json
        FROM resource_items
        WHERE last_seen_at LIKE '{%' AND extra_json NOT LIKE '{%'
        """
    )
    for row in cursor.fetchall():
        row_id = int(row[0] or 0)
        legacy_extra_raw = str(row[1] or "").strip()
        last_seen_raw = str(row[2] or "").strip()
        legacy_extra = safe_json_loads(legacy_extra_raw, {})
        if not isinstance(legacy_extra, dict):
            continue
        if not any(str(legacy_extra.get(key, "") or "").strip() for key in ("cover_url", "source_post_id", "source_url")):
            continue
        cursor.execute(
            "UPDATE resource_items SET last_seen_at = ?, extra_json = ? WHERE id = ?",
            (last_seen_raw or now_text(), legacy_extra_raw, row_id),
        )
    conn.commit()
    conn.close()


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn
