import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from .db import (
    ensure_db,
    now_text,
    open_db,
    safe_json_dumps,
    safe_json_loads,
    sqlite_row_to_dict,
)
from .resource_identity import normalize_resource_identity_mode, normalize_telegram_channel_id_from_input
from .resource_linking import (
    apply_share_receive_code_to_url,
    detect_resource_link_type,
    normalize_receive_code,
    parse_115_share_payload,
    parse_quark_share_payload,
    resolve_resource_link_type,
)


def upsert_resource_item(
    conn: sqlite3.Connection,
    item: Dict[str, Any],
    identity_mode: str = "message",
) -> Tuple[int, bool]:
    cursor = conn.cursor()
    link_url = str(item.get("link_url", "")).strip()
    message_url = str(item.get("message_url", "")).strip()
    normalized_identity_mode = normalize_resource_identity_mode(identity_mode, fallback="message")
    now = now_text()
    existing: Optional[sqlite3.Row] = None
    if link_url:
        cursor.execute("SELECT * FROM resource_items WHERE link_url = ?", (link_url,))
        existing = cursor.fetchone()
    if not existing and message_url and normalized_identity_mode != "link":
        cursor.execute("SELECT * FROM resource_items WHERE message_url = ?", (message_url,))
        existing = cursor.fetchone()
    if not existing and (normalized_identity_mode != "link" or not link_url):
        cursor.execute(
            """
            SELECT * FROM resource_items
            WHERE title = ? AND source_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(item.get("title", "")).strip(), str(item.get("source_name", "")).strip()),
        )
        existing = cursor.fetchone()

    payload = (
        str(item.get("source_type", "manual")).strip() or "manual",
        str(item.get("source_name", "")).strip(),
        str(item.get("channel_name", "")).strip(),
        str(item.get("title", "")).strip() or "未命名资源",
        str(item.get("normalized_title", "")).strip(),
        str(item.get("raw_text", "")).strip(),
        link_url,
        str(item.get("link_type", "unknown")).strip() or "unknown",
        message_url,
        str(item.get("quality", "")).strip(),
        str(item.get("year", "")).strip(),
        str(item.get("published_at", "")).strip(),
        safe_json_dumps(item.get("extra", {})),
    )
    if existing:
        cursor.execute(
            """
            UPDATE resource_items
            SET source_type = ?, source_name = ?, channel_name = ?, title = ?, normalized_title = ?,
                raw_text = ?, link_url = ?, link_type = ?, message_url = ?, quality = ?, year = ?,
                published_at = ?, last_seen_at = ?, extra_json = ?
            WHERE id = ?
            """,
            payload[:12] + (now, payload[12], existing["id"]),
        )
        return int(existing["id"]), False

    cursor.execute(
        """
        INSERT INTO resource_items(
            source_type, source_name, channel_name, title, normalized_title, raw_text,
            link_url, link_type, message_url, quality, year, status,
            created_at, published_at, last_seen_at, extra_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)
        """,
        payload[:11] + (now, payload[11], now, payload[12]),
    )
    return int(cursor.lastrowid), True


def update_resource_item_status(conn: sqlite3.Connection, resource_id: int, status: str) -> None:
    cursor = conn.cursor()
    cursor.execute("UPDATE resource_items SET status = ?, last_seen_at = ? WHERE id = ?", (status, now_text(), resource_id))


def serialize_resource_item_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = sqlite_row_to_dict(row)
    extra = safe_json_loads(data.get("extra_json"), {})
    legacy_extra = safe_json_loads(data.get("last_seen_at"), {})
    if not isinstance(extra, dict) or not extra:
        extra = legacy_extra if isinstance(legacy_extra, dict) else {}
    elif isinstance(legacy_extra, dict):
        for key in ("cover_url", "source_post_id", "source_url"):
            if not str(extra.get(key, "") or "").strip() and str(legacy_extra.get(key, "") or "").strip():
                extra[key] = legacy_extra[key]
    data["extra"] = extra
    data["cover_url"] = str(extra.get("cover_url", "") or "").strip()
    data["source_post_id"] = str(extra.get("source_post_id", "") or "").strip()
    return data


def build_resource_job_snapshot(resource: Dict[str, Any], link_type: str = "", receive_code: str = "") -> Dict[str, Any]:
    extra = resource.get("extra", {})
    if not isinstance(extra, dict):
        extra = safe_json_loads(resource.get("extra_json"), {})
    manual_receive_code = (
        normalize_receive_code(receive_code)
        or normalize_receive_code(resource.get("receive_code", ""))
        or normalize_receive_code(extra.get("receive_code", ""))
    )
    snapshot = {
        "message_url": str(resource.get("message_url", "") or "").strip(),
        "source_post_id": str((extra or {}).get("source_post_id", "") or "").strip(),
    }
    resolved_link_type = resolve_resource_link_type(link_type or resource.get("link_type", ""), resource.get("link_url", ""))
    if resolved_link_type == "115share":
        payload = parse_115_share_payload(
            str(resource.get("link_url", "") or "").strip(),
            str(resource.get("raw_text", "") or ""),
            manual_receive_code,
        )
        resolved_receive_code = normalize_receive_code(payload.get("receive_code", ""))
        if resolved_receive_code:
            snapshot["receive_code"] = resolved_receive_code
    elif resolved_link_type == "quark":
        payload = parse_quark_share_payload(
            str(resource.get("link_url", "") or "").strip(),
            str(resource.get("raw_text", "") or ""),
            manual_receive_code,
        )
        resolved_receive_code = normalize_receive_code(payload.get("receive_code", ""))
        if resolved_receive_code:
            snapshot["receive_code"] = resolved_receive_code
    return {key: value for key, value in snapshot.items() if str(value or "").strip()}


def sanitize_resource_job_input(raw: Dict[str, Any]) -> Dict[str, Any]:
    source_type = str(raw.get("source_type", "manual") or "manual").strip() or "manual"
    source_name = str(raw.get("source_name", "") or "").strip()
    channel_name = str(raw.get("channel_name", "") or "").strip()
    title = str(raw.get("title", "") or "").strip() or "未命名资源"
    raw_text = str(raw.get("raw_text", "") or "").strip()
    link_url = str(raw.get("link_url", "") or "").strip()
    message_url = str(raw.get("message_url", "") or "").strip()
    quality = str(raw.get("quality", "") or "").strip()
    year = str(raw.get("year", "") or "").strip()
    published_at = str(raw.get("published_at", "") or "").strip()
    extra = raw.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}
    receive_code = normalize_receive_code(raw.get("receive_code", "") or extra.get("receive_code", ""))
    link_type = resolve_resource_link_type(str(raw.get("link_type", "") or "").strip(), link_url) or detect_resource_link_type(link_url)
    if link_type == "115share" and receive_code:
        link_url = apply_share_receive_code_to_url(link_url, receive_code)
    return {
        "id": int(raw.get("id", 0) or 0),
        "source_type": source_type,
        "source_name": source_name,
        "channel_name": channel_name,
        "title": title,
        "normalized_title": str(raw.get("normalized_title", "") or "").strip() or title.lower(),
        "raw_text": raw_text,
        "link_url": link_url,
        "link_type": link_type,
        "message_url": message_url,
        "quality": quality,
        "year": year,
        "published_at": published_at,
        "receive_code": receive_code,
        "extra": {
            "cover_url": str(extra.get("cover_url", "") or "").strip(),
            "source_post_id": str(extra.get("source_post_id", "") or "").strip(),
            "source_url": str(extra.get("source_url", "") or "").strip(),
            "receive_code": receive_code,
        },
    }


def get_resource_job_snapshot(raw_extra: Any) -> Dict[str, Any]:
    extra = safe_json_loads(raw_extra, {})
    snapshot = extra.get("snapshot") if isinstance(extra, dict) else {}
    return snapshot if isinstance(snapshot, dict) else {}


def get_resource_item(resource_id: int) -> Dict[str, Any]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resource_items WHERE id = ?", (resource_id,))
    row = cursor.fetchone()
    conn.close()
    return serialize_resource_item_row(row) if row else {}


def serialize_resource_job_row(row: Optional[sqlite3.Row], include_private: bool = False) -> Dict[str, Any]:
    if not row:
        return {}
    data = sqlite_row_to_dict(row)
    extra = safe_json_loads(data.get("extra_json"), {})
    snapshot = get_resource_job_snapshot(extra)
    data["response"] = safe_json_loads(data.get("response_json"), {})
    data["extra"] = extra if isinstance(extra, dict) else {}
    data["snapshot"] = {
        "message_url": str(snapshot.get("message_url", "") or "").strip(),
        "source_post_id": str(snapshot.get("source_post_id", "") or "").strip(),
    }
    if include_private:
        data["_snapshot"] = snapshot
    data["auto_refresh"] = bool(data.get("auto_refresh"))
    data["job_source"] = str(data["extra"].get("job_source", "") or "").strip()
    data["refresh_target_type"] = str(data["extra"].get("refresh_target_type", "") or "").strip()
    data["share_root_title"] = str(data["extra"].get("share_root_title", "") or "").strip()
    data["message_url"] = str(snapshot.get("message_url", "") or "").strip()
    data["source_post_id"] = str(snapshot.get("source_post_id", "") or "").strip()
    data["selected_ids"] = [
        str(item).strip()
        for item in (data["extra"].get("selected_ids") or [])
        if str(item).strip()
    ]
    data["selected_entries"] = data["extra"].get("selected_entries") if isinstance(data["extra"].get("selected_entries"), list) else []
    return data


def list_resource_items(search: str = "", status: str = "", channel_id: str = "", source_type: str = "", limit: int = 120) -> List[Dict[str, Any]]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    where_parts = []
    params: List[Any] = []
    keyword = str(search or "").strip().lower()
    if keyword:
        like = f"%{keyword}%"
        where_parts.append(
            "(lower(title) LIKE ? OR lower(source_name) LIKE ? OR lower(channel_name) LIKE ? OR lower(link_url) LIKE ? OR lower(raw_text) LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        where_parts.append("status = ?")
        params.append(normalized_status)
    normalized_channel = normalize_telegram_channel_id_from_input(channel_id)
    if normalized_channel:
        where_parts.append("channel_name = ?")
        params.append(normalized_channel)
    normalized_source_type = str(source_type or "").strip().lower()
    if normalized_source_type:
        where_parts.append("source_type = ?")
        params.append(normalized_source_type)

    sql = "SELECT * FROM resource_items"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    sql += " ORDER BY CASE WHEN published_at <> '' THEN published_at ELSE created_at END DESC, id DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return [serialize_resource_item_row(row) for row in rows]


def count_resource_items(search: str = "", status: str = "", channel_id: str = "", source_type: str = "") -> int:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    where_parts = []
    params: List[Any] = []
    keyword = str(search or "").strip().lower()
    if keyword:
        like = f"%{keyword}%"
        where_parts.append(
            "(lower(title) LIKE ? OR lower(source_name) LIKE ? OR lower(channel_name) LIKE ? OR lower(link_url) LIKE ? OR lower(raw_text) LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        where_parts.append("status = ?")
        params.append(normalized_status)
    normalized_channel = normalize_telegram_channel_id_from_input(channel_id)
    if normalized_channel:
        where_parts.append("channel_name = ?")
        params.append(normalized_channel)
    normalized_source_type = str(source_type or "").strip().lower()
    if normalized_source_type:
        where_parts.append("source_type = ?")
        params.append(normalized_source_type)

    sql = "SELECT COUNT(1) FROM resource_items"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    cursor.execute(sql, params)
    row = cursor.fetchone()
    conn.close()
    return int(row[0] if row else 0)


__all__ = [
    "upsert_resource_item",
    "update_resource_item_status",
    "serialize_resource_item_row",
    "build_resource_job_snapshot",
    "sanitize_resource_job_input",
    "get_resource_job_snapshot",
    "get_resource_item",
    "serialize_resource_job_row",
    "list_resource_items",
    "count_resource_items",
]
