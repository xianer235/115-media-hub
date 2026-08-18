import io
import threading
from http.cookies import SimpleCookie
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..core import *  # noqa: F401,F403
from ..db import now_text, retry_sqlite_locked
from ..memory import release_process_memory
from .strm_files import delete_managed_strm_file, managed_strm_file_path

TREE_SYNC_PATH_BATCH_SIZE = max(
    100,
    min(5000, int(os.environ.get("TREE_SYNC_PATH_BATCH_SIZE", 1000) or 1000)),
)
TREE_SYNC_SQLITE_SELECT_CHUNK_SIZE = 800


def _format_tree_elapsed_seconds(seconds: float) -> str:
    return f"{max(0.0, float(seconds or 0.0)):.2f}秒"


def _tree_stage_seconds(started_at: float) -> str:
    return _format_tree_elapsed_seconds(time.perf_counter() - started_at)


def _tree_flow_total_seconds(durations: Dict[str, float]) -> str:
    return _format_tree_elapsed_seconds(sum(max(0.0, float(value or 0.0)) for value in (durations or {}).values()))


def _normalize_tree_source_relative_path(raw_source: Any, cfg: Dict[str, Any]) -> str:
    source = str(raw_source or "").strip()
    if not source:
        return ""
    if "://" in source:
        parsed = urllib.parse.urlsplit(source)
        marker_idx = (parsed.path or "").lower().find("/d")
        if marker_idx >= 0:
            encoded = (parsed.path or "")[marker_idx + 2 :].lstrip("/")
            source = urllib.parse.unquote(encoded) if encoded else ""
        else:
            source = parsed.path or ""
    normalized_remote = normalize_remote_path(source)
    matched = match_mount_point_by_remote_path(cfg, normalized_remote)
    if matched and normalize_mount_provider(matched.get("provider", "")) == "115":
        return normalize_relative_path(matched.get("relative_path", ""))
    return normalize_relative_path(source)


def _resolve_115_file_entry_by_relative_path(cookie: str, relative_path: str) -> Dict[str, Any]:
    normalized = normalize_relative_path(relative_path)
    if not normalized:
        raise RuntimeError("目录树文件路径不能为空")
    parent_rel = normalize_relative_path(os.path.dirname(normalized))
    file_name = str(os.path.basename(normalized) or "").strip()
    if not file_name:
        raise RuntimeError("目录树文件路径不合法")
    parent_cid = resolve_115_folder_id_by_path(cookie, parent_rel) if parent_rel else "0"
    entries = list_115_entries(cookie, parent_cid)
    matched = next(
        (
            item
            for item in entries
            if (not bool(item.get("is_dir"))) and str(item.get("name", "")).strip() == file_name
        ),
        None,
    )
    if not matched:
        raise RuntimeError(f"115 网盘文件不存在：{normalized}")
    return dict(matched)


def _collect_115_download_urls(payload: Any) -> List[str]:
    urls: List[str] = []
    seen: Set[str] = set()

    def push(url_value: Any) -> None:
        token = str(url_value or "").strip()
        if (not token) or (not token.lower().startswith(("http://", "https://"))) or token in seen:
            return
        seen.add(token)
        urls.append(token)

    def walk(node: Any) -> None:
        if isinstance(node, str):
            push(node)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("url", "download_url", "file_url", "download_url_web", "download_url_web2"):
            walk(node.get(key))
        for key in ("data", "urls", "result", "info"):
            walk(node.get(key))

    walk(payload)
    return urls


def _resolve_115_download_payload(cookie: str, pick_code: str) -> Tuple[List[str], str]:
    throttle_115_api_requests()
    request_headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }
    url = "https://webapi.115.com/files/download?pickcode=" + urllib.parse.quote(pick_code)
    request = urllib.request.Request(url, headers=request_headers, method="GET")
    with urllib.request.urlopen(request, timeout=45) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="ignore")
        result = safe_json_loads(body, {})
        response_set_cookies = resp.headers.get_all("Set-Cookie") or []
    if not isinstance(result, dict):
        raise RuntimeError("115 下载地址解析返回异常")
    if not bool(result.get("state", False)):
        detail = (
            str(result.get("error", "")).strip()
            or str(result.get("msg", "")).strip()
            or str(result.get("message", "")).strip()
            or "115 下载地址解析失败"
        )
        raise RuntimeError(detail)
    download_urls = _collect_115_download_urls(result)
    if not download_urls:
        raise RuntimeError("115 返回成功，但未解析到下载链接")
    extra_cookie_pairs: List[str] = []
    for raw_cookie in response_set_cookies:
        jar = SimpleCookie()
        try:
            jar.load(str(raw_cookie or ""))
        except Exception:
            continue
        for key, morsel in jar.items():
            token = f"{str(key or '').strip()}={str(morsel.value or '').strip()}"
            if token and token not in extra_cookie_pairs:
                extra_cookie_pairs.append(token)
    return download_urls, "; ".join(extra_cookie_pairs)


def _download_tree_file_bytes(download_urls: List[str], cookie: str, download_cookie: str = "") -> bytes:
    def _build_download_url_candidates(raw_url: str) -> List[str]:
        source = str(raw_url or "").strip()
        if not source:
            return []
        candidates: List[str] = []
        seen: Set[str] = set()

        def push(url_value: str) -> None:
            token = str(url_value or "").strip()
            if (not token) or token in seen:
                return
            seen.add(token)
            candidates.append(token)

        push(source)
        try:
            parts = urllib.parse.urlsplit(source)
            if parts.scheme.lower() in ("http", "https") and parts.netloc:
                # 仅规范 path，保留 query 原样，避免破坏签名参数。
                encoded_path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%:@+")
                path_only = urllib.parse.urlunsplit((parts.scheme, parts.netloc, encoded_path, parts.query, parts.fragment))
                push(path_only)
                normalized = normalize_http_url(source)
                push(normalized)
        except Exception:
            pass
        return candidates

    def _request_binary_raw_url(url: str, headers: Optional[Dict[str, str]]) -> bytes:
        target_url = str(url or "").strip()
        if not target_url.lower().startswith(("http://", "https://")):
            raise RuntimeError("目录树下载链接不合法")
        request = urllib.request.Request(target_url, headers=dict(headers or {}), method="GET")
        with urllib.request.urlopen(request, timeout=60) as resp:
            return resp.read()

    merged_cookie = "; ".join([part for part in [str(cookie or "").strip(), str(download_cookie or "").strip()] if part])
    header_candidates: List[Optional[Dict[str, str]]] = [
        {
            "Cookie": merged_cookie,
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": "Mozilla/5.0 115-media-hub",
            "Accept": "*/*",
        },
        {
            "Cookie": str(download_cookie or "").strip(),
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": "Mozilla/5.0 115-media-hub",
            "Accept": "*/*",
        },
        {
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": "Mozilla/5.0 115-media-hub",
            "Accept": "*/*",
        },
        {
            "User-Agent": "Mozilla/5.0 115-media-hub",
            "Accept": "*/*",
        },
        None,
    ]
    last_error: Optional[Exception] = None
    expanded_urls: List[str] = []
    for download_url in download_urls:
        expanded_urls.extend(_build_download_url_candidates(download_url))
    for expanded_url in expanded_urls:
        for headers in header_candidates:
            try:
                data = _request_binary_raw_url(expanded_url, headers)
                if data is not None:
                    return data
            except Exception as exc:
                last_error = exc
                continue
    if last_error is not None:
        raise RuntimeError(f"目录树文件下载失败: {last_error}") from last_error
    raise RuntimeError("目录树文件下载失败")


def _fetch_115_tree_file_bytes(cookie: str, source_rel: str) -> bytes:
    entry = _resolve_115_file_entry_by_relative_path(cookie, source_rel)
    pick_code = str(entry.get("pick_code", "")).strip()
    if not pick_code:
        raise RuntimeError(f"目录树文件缺少 pickcode：{source_rel}")
    download_urls, download_cookie = _resolve_115_download_payload(cookie, pick_code)
    return _download_tree_file_bytes(download_urls, cookie, download_cookie)


def _load_tree_raw_cache(cache_path: str) -> Optional[bytes]:
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "rb") as f:
            payload = f.read()
    except Exception:
        return None
    return payload if payload else None


def _save_tree_raw_cache(cache_path: str, raw_bytes: bytes) -> None:
    payload = raw_bytes or b""
    if not payload:
        return
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp_path = cache_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(payload)
    os.replace(tmp_path, cache_path)


def _decode_tree_file_text(raw_bytes: bytes) -> str:
    payload = raw_bytes or b""
    if not payload:
        return ""
    for encoding in ("utf-8-sig", "utf-16", "utf-16le", "gb18030", "utf-8"):
        try:
            text = payload.decode(encoding)
            if text:
                return text
        except Exception:
            continue
    return payload.decode("utf-8", errors="ignore")


def _scan_tree_text(
    content: str,
    user_exts: Set[str],
    prefix: str,
    exclude: int,
    on_match: Optional[Callable[[str], None]] = None,
) -> Tuple[int, int, int]:
    path_stack: Dict[int, str] = {}
    lines_total = 0
    nodes_total = 0
    matched_total = 0
    for raw_line in io.StringIO(str(content or "")):
        line = str(raw_line or "").replace("\ufeff", "")
        if not line.strip():
            continue
        lines_total += 1
        level = line.count("|")
        clean_name = re.sub(r"^[|\s—-]+", "", line).strip()
        if not clean_name:
            continue
        nodes_total += 1
        for stale_level in [key for key in path_stack.keys() if key > level]:
            path_stack.pop(stale_level, None)
        path_stack[level] = clean_name
        if not is_video_file(clean_name, user_exts):
            continue
        # 对齐 0.2.2：不强制要求 0..level 每层都存在，按已有层级拼接即可。
        full_parts = [path_stack[depth] for depth in range(level + 1) if depth in path_stack]
        if not full_parts:
            continue
        rel_parts = full_parts[max(0, int(exclude or 0)) :]
        final_rel_path = join_relative_path(prefix, "/".join(rel_parts))
        if final_rel_path:
            matched_total += 1
            if on_match is not None:
                on_match(final_rel_path)
    return matched_total, lines_total, nodes_total


def _stream_tree_file_matches(
    raw_bytes: bytes,
    user_exts: Set[str],
    prefix: str,
    exclude: int,
    on_match: Callable[[str], None],
) -> Tuple[int, int, int]:
    content = _decode_tree_file_text(raw_bytes)
    if not str(content or "").strip():
        raise RuntimeError("目录树文件为空")
    matched_total, lines_total, nodes_total = _scan_tree_text(content, user_exts, prefix, exclude, on_match=on_match)
    return matched_total, lines_total, nodes_total


def _replay_tree_cache(cache_path: str, on_match: Callable[[str], None]) -> int:
    matched_total = 0
    if not os.path.exists(cache_path):
        return matched_total
    with open(cache_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            rel_path = normalize_relative_path(str(raw_line or "").strip())
            if not rel_path:
                continue
            on_match(rel_path)
            matched_total += 1
    return matched_total


def _stream_tree_matches_to_cache(
    cache_path: str,
    raw_bytes: bytes,
    user_exts: Set[str],
    prefix: str,
    exclude: int,
    on_match: Callable[[str], None],
) -> Tuple[int, int, int]:
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp_path = cache_path + ".tmp"
    matched_total = 0
    lines_total = 0
    nodes_total = 0
    with open(tmp_path, "w", encoding="utf-8") as cache_file:
        def handle_match(rel_path: str) -> None:
            nonlocal matched_total
            normalized = normalize_relative_path(rel_path)
            if not normalized:
                return
            cache_file.write(normalized)
            cache_file.write("\n")
            on_match(normalized)
            matched_total += 1

        try:
            _matched_total, lines_total, nodes_total = _stream_tree_file_matches(
                raw_bytes,
                user_exts,
                prefix,
                exclude,
                handle_match,
            )
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
    os.replace(tmp_path, cache_path)
    return matched_total, lines_total, nodes_total


def _iter_chunks(values: List[Any], chunk_size: int) -> List[List[Any]]:
    size = max(1, int(chunk_size or 1))
    return [values[idx : idx + size] for idx in range(0, len(values), size)]


def _build_local_file_path_hash(rel_path: str) -> str:
    return hashlib.md5(rel_path.encode("utf-8")).hexdigest()


def _mark_local_files_seen_batch(
    cursor: sqlite3.Cursor,
    rel_paths: List[str],
    scan_token: str,
) -> Tuple[List[str], int]:
    ordered_rows: List[Tuple[str, str]] = []
    batch_seen_hashes: Set[str] = set()
    duplicate_count = 0

    for raw_path in rel_paths:
        rel_path = normalize_relative_path(raw_path)
        if not rel_path:
            continue
        path_hash = _build_local_file_path_hash(rel_path)
        if path_hash in batch_seen_hashes:
            duplicate_count += 1
            continue
        batch_seen_hashes.add(path_hash)
        ordered_rows.append((path_hash, rel_path))

    if not ordered_rows:
        return [], duplicate_count

    def write_batch() -> Tuple[List[str], int]:
        duplicate_total = duplicate_count
        existing_rows: Dict[str, Tuple[str, str]] = {}
        path_hashes = [path_hash for path_hash, _rel_path in ordered_rows]
        for chunk in _iter_chunks(path_hashes, TREE_SYNC_SQLITE_SELECT_CHUNK_SIZE):
            placeholders = ",".join("?" for _item in chunk)
            cursor.execute(
                f"SELECT path_hash, relative_path, scan_token FROM local_files WHERE path_hash IN ({placeholders})",
                chunk,
            )
            for path_hash, existing_rel_path, existing_scan_token in cursor.fetchall():
                existing_rows[str(path_hash or "")] = (
                    normalize_relative_path(existing_rel_path),
                    str(existing_scan_token or ""),
                )

        upsert_rows: List[Tuple[str, str, str]] = []
        fresh_paths: List[str] = []
        for path_hash, rel_path in ordered_rows:
            existing_rel_path, existing_scan_token = existing_rows.get(path_hash, ("", ""))
            if existing_rel_path == rel_path and existing_scan_token == scan_token:
                duplicate_total += 1
                continue
            upsert_rows.append((path_hash, rel_path, scan_token))
            fresh_paths.append(rel_path)

        if upsert_rows:
            cursor.executemany(
                """
                INSERT INTO local_files (path_hash, relative_path, scan_token)
                VALUES (?, ?, ?)
                ON CONFLICT(path_hash) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    scan_token = excluded.scan_token
                WHERE local_files.relative_path <> excluded.relative_path
                   OR local_files.scan_token <> excluded.scan_token
                """,
                upsert_rows,
            )
        return fresh_paths, duplicate_total

    def transactional_write() -> Tuple[List[str], int]:
        conn = cursor.connection
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                cursor.execute("BEGIN IMMEDIATE")
            result = write_batch()
            if owns_transaction:
                conn.commit()
            return result
        except Exception:
            if owns_transaction:
                conn.rollback()
            raise

    return retry_sqlite_locked(transactional_write)


TREE_EXPORT_TARGET_ROOT = "U_1_0"
TREE_EXPORT_DEFAULT_TIMEOUT_SECONDS = max(
    60,
    int(os.environ.get("TREE_EXPORT_TIMEOUT_SECONDS", 1800) or 1800),
)
TREE_EXPORT_POLL_INTERVAL_SECONDS = 2
TREE_EXPORT_FILE_READY_ATTEMPTS = 8
TREE_EXPORT_FILE_READY_INTERVAL_SECONDS = 1.0
TREE_EXPORT_REPLACE_ATTEMPTS = 6
TREE_EXPORT_REPLACE_VERIFY_ATTEMPTS = 5
TREE_EXPORT_REPLACE_SETTLE_SECONDS = 1.0
_tree_task_running = False
_tree_task_lock = threading.Lock()


def _tree_task_busy() -> bool:
    with _tree_task_lock:
        return bool(_tree_task_running)


def _set_tree_task_running(flag: bool) -> None:
    global _tree_task_running
    with _tree_task_lock:
        _tree_task_running = bool(flag)


def _get_tree_task_by_id(cfg: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    normalized_id = str(task_id or "").strip()
    for task in cfg.get("tree_tasks", []):
        if str((task or {}).get("id", "") or "").strip() == normalized_id:
            return dict(task or {})
    return {}


def find_tree_task_name_conflict(
    cfg: Dict[str, Any],
    tree_name: str,
    folder_path: str,
) -> Optional[Dict[str, Any]]:
    normalized_name = str(tree_name or "").strip()
    normalized_folder = normalize_relative_path(folder_path)
    for task in cfg.get("tree_tasks", []):
        task_dict = task or {}
        if (
            str(task_dict.get("tree_name", "") or "").strip() == normalized_name
            and normalize_relative_path(str(task_dict.get("folder_path", "") or "").strip()) != normalized_folder
        ):
            return dict(task_dict)
    return None


def _tree_task_cache_paths(task: Dict[str, Any]) -> Tuple[str, str, str]:
    tree_key = build_tree_cache_key(
        {
            "source_type": "tree_task",
            "path": str(task.get("tree_name", "") or "").strip(),
            "prefix": normalize_relative_path(task.get("prefix", "")),
            "exclude": max(0, int(task.get("exclude", 1) or 1)),
        }
    )
    return (
        tree_key,
        os.path.join(TREE_DIR, f"cache_{tree_key}.txt"),
        os.path.join(TREE_DIR, f"raw_{tree_key}.txt"),
    )


def _tree_file_remote_name(tree_name: str) -> str:
    """115 导出的是 txt 文件，重命名时会自动补 .txt 后缀，统一用远程实际名。"""
    name = str(tree_name or "").strip()
    if not name:
        return ""
    return name if name.lower().endswith(".txt") else name + ".txt"


def _tree_export_timeout_guide(task: Dict[str, Any], export_id: str, exc: BaseException) -> str:
    """生成导出超时后的手动处理指引：找到 115 服务端命名的新文件并改名为任务标准名。"""
    remote_name = _tree_file_remote_name(str(task.get("tree_name", "") or "").strip())
    return (
        f"{exc}；官方导出可能仍在服务端执行（export_id={str(export_id or '').strip() or '-'}）。"
        f"请手动到 115 网盘根目录找到新导出的目录树文件（服务端命名，形如「根目录<时间戳>_目录树.txt」），"
        f"删除旧的「{remote_name}」并把新文件改名为「{remote_name}」，"
        f"然后点击「下载并生成」按钮直接下载并生成。"
        f"在完成改名前请勿重复点击「生成并同步」，115 同一时刻只允许一个导出任务。"
    )


def _upsert_tree_task(cfg: Dict[str, Any], updated_task: Dict[str, Any]) -> None:
    task_id = str(updated_task.get("id", "") or "").strip()
    tasks = [
        task
        for task in cfg.get("tree_tasks", [])
        if str((task or {}).get("id", "") or "").strip() != task_id
    ]
    tasks.append(dict(updated_task))
    cfg["tree_tasks"] = tasks
    save_config(cfg)


def _create_tree_export_job(task: Dict[str, Any], status: str = "running", error: str = "") -> int:
    def create() -> int:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tree_export_jobs
                    (task_id, folder_path, tree_name, prefix, exclude, status, error, submitted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(task.get("id", "") or "").strip(),
                    str(task.get("folder_path", "") or "").strip(),
                    str(task.get("tree_name", "") or "").strip(),
                    str(task.get("prefix", "") or "").strip(),
                    max(0, int(task.get("exclude", 1) or 1)),
                    status,
                    error,
                    now_text(),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    return retry_sqlite_locked(create)


def _update_tree_export_job(job_id: int, **fields: Any) -> None:
    if not job_id:
        return
    allowed = {
        "export_id",
        "file_id",
        "file_name",
        "pick_code",
        "sha1",
        "status",
        "changed",
        "parsed_count",
        "generated_count",
        "error",
        "completed_at",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [int(job_id)]

    def update() -> None:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE tree_export_jobs SET {assignments} WHERE id = ?", values)
            conn.commit()

    retry_sqlite_locked(update)


def list_tree_export_jobs(limit: int = 30) -> List[Dict[str, Any]]:
    normalized_limit = max(1, min(200, int(limit or 30)))

    def load() -> List[Dict[str, Any]]:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tree_export_jobs ORDER BY id DESC LIMIT ?",
                (normalized_limit,),
            )
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    return retry_sqlite_locked(load)


def _wait_115_export_file_ready(cookie: str, new_file_id: str) -> None:
    """等导出文件可查询后再继续操作（get_info 直查优先），避免与 115 内部后处理竞争。"""
    normalized_id = str(new_file_id or "").strip()
    attempts = max(1, int(TREE_EXPORT_FILE_READY_ATTEMPTS or 8))
    interval = max(0.0, float(TREE_EXPORT_FILE_READY_INTERVAL_SECONDS or 1.0))
    last_error = ""
    for _attempt in range(attempts):
        try:
            info = get_115_file_info(cookie, normalized_id)
            if str(info.get("name", "") or "").strip():
                return
        except Exception as exc:
            last_error = str(exc)
        try:
            entries = list_115_entries(cookie, "0", force_refresh=True)
            matched = next(
                (item for item in entries if str(item.get("id", "") or "").strip() == normalized_id),
                None,
            )
            if matched and str(matched.get("name", "") or "").strip():
                return
        except Exception as exc:
            last_error = str(exc)
        if interval > 0:
            time.sleep(interval)
    raise RuntimeError(
        f"115 导出文件尚未就绪（file_id={normalized_id}）"
        + (f"：{last_error}" if last_error else "")
    )


def _replace_115_tree_file(cookie: str, new_file_id: str, tree_name: str) -> None:
    """删除根目录同名旧树文件并把新文件重命名为 tree_name。

    115 列表接口在删除/重命名后存在秒级延迟，重命名撞名时会自动加 (1)。
    因此循环重试：先删同名旧文件，再重命名，并在每次操作后留出间隔重新校验，
    直到新文件名称正确为止。
    """
    normalized_id = str(new_file_id or "").strip()
    if not normalized_id:
        raise RuntimeError("115 导出目录树文件 ID 为空，无法重命名")
    remote_name = _tree_file_remote_name(tree_name)
    if not remote_name:
        raise RuntimeError("目录树文件名不能为空")
    attempts = max(1, int(TREE_EXPORT_REPLACE_ATTEMPTS or 6))
    verify_attempts = max(1, int(TREE_EXPORT_REPLACE_VERIFY_ATTEMPTS or 5))
    settle = max(0.0, float(TREE_EXPORT_REPLACE_SETTLE_SECONDS or 1.0))
    last_error = ""
    for _attempt in range(attempts):
        try:
            entries = list_115_entries(cookie, "0", force_refresh=True)
            old = next(
                (
                    item
                    for item in entries
                    if (not bool(item.get("is_dir")))
                    and str(item.get("name", "") or "").strip() == remote_name
                ),
                None,
            )
            new_entry = next(
                (item for item in entries if str(item.get("id", "") or "").strip() == normalized_id),
                None,
            )
            if old and str(old.get("id", "") or "").strip() != normalized_id:
                delete_115_entries(cookie, [str(old.get("id", "") or "").strip()], "0")
            if new_entry and str(new_entry.get("name", "") or "").strip() == remote_name:
                return
            rename_115_entry(cookie, normalized_id, remote_name, "0")
            verified = False
            for _verify in range(verify_attempts):
                if settle > 0:
                    time.sleep(settle)
                try:
                    info = get_115_file_info(cookie, normalized_id)
                except Exception as exc:
                    last_error = str(exc)
                    info = {}
                if str(info.get("name", "") or "").strip() == remote_name:
                    verified = True
                    break
            if verified:
                return
            # 重命名撞名被 115 改成 (1) 时，删除残留的同名冲突文件后重试。
            entries = list_115_entries(cookie, "0", force_refresh=True)
            conflict = next(
                (
                    item
                    for item in entries
                    if (not bool(item.get("is_dir")))
                    and str(item.get("name", "") or "").strip() == remote_name
                    and str(item.get("id", "") or "").strip() != normalized_id
                ),
                None,
            )
            if conflict:
                delete_115_entries(cookie, [str(conflict.get("id", "") or "").strip()], "0")
            last_error = f"重命名后名称未同步（仍不是 {remote_name}）"
        except Exception as exc:
            last_error = str(exc)
            if settle > 0:
                time.sleep(settle)
    raise RuntimeError(
        f"115 目录树文件重命名未完成（多次重试仍不是 {remote_name}）"
        + (f"：{last_error}" if last_error else "")
    )


def _download_exported_tree_bytes(cookie: str, pick_code: str) -> bytes:
    download_urls, download_cookie = _resolve_115_download_payload(cookie, pick_code)
    return _download_tree_file_bytes(download_urls, cookie, download_cookie)


async def _write_tree_timing_summary(durations: Dict[str, float], _gen_subtotal: float) -> None:
    order = (
        ("提交导出", "提交导出"),
        ("等待官方生成", "等待"),
        ("替换网盘树文件", "替换"),
        ("sha1 对比", "sha1 对比"),
        ("下载并解析", "下载解析"),
    )
    parts = [
        f"{label} {_format_tree_elapsed_seconds(durations.get(key, 0.0))}"
        for key, label in order
        if key in durations
    ]
    if parts:
        await write_log("步骤耗时：" + "｜".join(parts))
    await write_log(f"总用时：{_tree_flow_total_seconds(durations)}")


def _scope_sql_pattern(scope: str) -> str:
    escaped = (
        str(scope or "")
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return escaped + "/%"


async def _sync_task_tree_bytes(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    raw_bytes: bytes,
    force_full: bool = False,
) -> Dict[str, int]:
    user_exts = get_user_extensions(cfg)
    _tree_key, cache_path, raw_path = _tree_task_cache_paths(task)
    await asyncio.to_thread(_save_tree_raw_cache, raw_path, raw_bytes)
    ensure_db()
    conn = open_db()
    conn.isolation_level = None
    cursor = conn.cursor()
    scan_token = f"tree-{task.get('id', '')}-{int(time.time())}-{secrets.token_hex(8)}"
    pending_rel_paths: List[str] = []
    total_files = 0
    generated_file_count = 0
    unchanged_file_count = 0
    duplicate_scan_count = 0
    deleted_file_count = 0
    delete_failed_file_count = 0

    def generate_strm_for_rel_path(rel_path: str) -> None:
        nonlocal total_files, generated_file_count, unchanged_file_count
        normalized = normalize_relative_path(rel_path)
        if not normalized:
            return
        total_files += 1
        target = managed_strm_file_path(normalized)
        needs_regenerate = (not os.path.exists(target)) or force_full
        if needs_regenerate:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            remote_path = build_provider_remote_path(cfg, "115", normalized)
            strm_url = build_strm_play_url(cfg, remote_path)
            with open(target, "w", encoding="utf-8") as sf:
                sf.write(strm_url)
            generated_file_count += 1
        else:
            unchanged_file_count += 1

    def flush_path_batch() -> None:
        nonlocal duplicate_scan_count
        if not pending_rel_paths:
            return
        batch_paths = list(pending_rel_paths)
        pending_rel_paths.clear()
        fresh_paths, batch_duplicates = _mark_local_files_seen_batch(cursor, batch_paths, scan_token)
        duplicate_scan_count += batch_duplicates
        for fresh_path in fresh_paths:
            generate_strm_for_rel_path(fresh_path)

    def process_rel_path(rel_path: str) -> None:
        normalized = normalize_relative_path(rel_path)
        if not normalized:
            return
        pending_rel_paths.append(normalized)
        if len(pending_rel_paths) >= TREE_SYNC_PATH_BATCH_SIZE:
            flush_path_batch()

    try:
        matched_count, scanned_lines, scanned_nodes = _stream_tree_matches_to_cache(
            cache_path,
            raw_bytes,
            user_exts,
            str(task.get("prefix", "") or "").strip(),
            max(0, int(task.get("exclude", 1) or 1)),
            process_rel_path,
        )
        flush_path_batch()

        scope = normalize_relative_path(str(task.get("folder_path", "") or "").strip())
        scope_pattern = _scope_sql_pattern(scope)
        if cfg.get("sync_clean", True):
            cursor.execute(
                """
                SELECT relative_path FROM local_files
                WHERE scan_token <> ? AND (relative_path = ? OR relative_path LIKE ? ESCAPE '\\')
                """,
                (scan_token, scope, scope_pattern),
            )
            for (dead_path,) in cursor.fetchall():
                try:
                    if delete_managed_strm_file(str(dead_path or "")):
                        deleted_file_count += 1
                except Exception:
                    delete_failed_file_count += 1
            cursor.execute(
                """
                DELETE FROM local_files
                WHERE scan_token <> ? AND (relative_path = ? OR relative_path LIKE ? ESCAPE '\\')
                """,
                (scan_token, scope, scope_pattern),
            )
            conn.commit()

        await write_log(
            f"任务解析: 命中 {matched_count} | 生成/更新 {generated_file_count} | 保持不变 {unchanged_file_count} | "
            f"清理残留 {deleted_file_count}"
        )
    finally:
        conn.close()

    return {
        "matched_count": matched_count,
        "parsed_count": total_files,
        "generated_count": generated_file_count,
        "unchanged_count": unchanged_file_count,
        "duplicate_count": duplicate_scan_count,
        "deleted_count": deleted_file_count,
        "delete_failed_count": delete_failed_file_count,
    }


async def run_tree_task(task_id: str, full: bool = False) -> Dict[str, Any]:
    if task_status["running"] or _tree_task_busy():
        raise RuntimeError("已有目录树任务在运行，请稍后再试")
    cfg = get_config()
    task = _get_tree_task_by_id(cfg, task_id)
    if not task:
        raise RuntimeError("目录树任务不存在")
    config_error = validate_tree_runtime_config(cfg, False)
    if config_error:
        raise RuntimeError(config_error)
    _set_tree_task_running(True)
    task_status["running"] = True
    schedule_ui_state_push(0)
    job_id = _create_tree_export_job(task, status="running")
    started_at = time.perf_counter()
    try:
        result = await _run_tree_task_flow(cfg, task, job_id, full)
        elapsed = _format_tree_elapsed_seconds(time.perf_counter() - started_at)
        if bool(result.get("changed")):
            await write_log(
                f"结果汇总: ✅ 已完成 | 解析 {result.get('parsed_count', 0)} 条 | 写入 {result.get('generated_count', 0)} 条 | "
                f"清理 {result.get('deleted_count', 0)} 条"
                + (f" | sha1={str(result.get('sha1', '') or '')[:12]}…" if result.get("sha1") else "")
            )
            await write_log(
                f"━━━━━━━━━━【目录树任务结束 | 执行成功 | 总用时 {elapsed}】━━━━━━━━━━",
                "task-divider",
            )
        else:
            await write_log(
                f"结果汇总: ⏭ 未变化跳过（sha1 相同）"
                + (f" | sha1={str(result.get('sha1', '') or '')[:12]}…" if result.get("sha1") else "")
            )
            await write_log(
                f"━━━━━━━━━━【目录树任务结束 | 未变化跳过 | 总用时 {elapsed}】━━━━━━━━━━",
                "task-divider",
            )
        await update_progress("任务完成", 100, f"完成: {task['folder_path']}（{task['tree_name']}）")
        return result
    except Exception as exc:
        await write_log(f"❌ 目录树任务失败：{task['folder_path']}（{task['tree_name']}）| {exc}", "error")
        await write_log(
            f"━━━━━━━━━━【目录树任务结束 | 执行失败 | 总用时 {_format_tree_elapsed_seconds(time.perf_counter() - started_at)}】━━━━━━━━━━",
            "task-divider",
        )
        _update_tree_export_job(job_id, status="failed", error=str(exc), completed_at=now_text())
        raise
    finally:
        _set_tree_task_running(False)
        task_status["running"] = False
        task_status["progress"].update({"step": "就绪", "percent": 0, "detail": "等待指令..."})
        schedule_ui_state_push(0)
        await asyncio.to_thread(release_process_memory, "tree-task", True)


async def _run_tree_task_flow(cfg: Dict[str, Any], task: Dict[str, Any], job_id: int, full: bool) -> Dict[str, Any]:
    cookie = str(cfg.get("cookie_115", "") or "").strip()
    folder_path = str(task.get("folder_path", "") or "").strip()
    tree_name = str(task.get("tree_name", "") or "").strip()
    durations: Dict[str, float] = {}
    mode_label = "全量重写" if full else "生成并同步"
    await write_log(
        f"━━━━━━━━━━【目录树任务开始 | {folder_path} → {tree_name} | {mode_label}】━━━━━━━━━━",
        "task-divider",
    )
    await write_log("【生成目录树】")

    await update_progress("校验文件夹", 5, folder_path)
    folder_id = await asyncio.to_thread(resolve_115_folder_id_by_path, cookie, folder_path)

    stage_started = time.perf_counter()
    await update_progress("提交官方导出", 12, folder_path)
    export_id = await asyncio.to_thread(submit_115_export_dir, cookie, folder_id, TREE_EXPORT_TARGET_ROOT, 0)
    durations["提交导出"] = max(0.0, time.perf_counter() - stage_started)
    _update_tree_export_job(job_id, export_id=export_id, status="exporting")
    await write_log(f"提交导出：{_format_tree_elapsed_seconds(durations['提交导出'])}（export_id={export_id}）")

    stage_started = time.perf_counter()
    await update_progress("等待官方生成", 35, folder_path)
    try:
        result = await asyncio.to_thread(
            wait_115_export_dir,
            cookie,
            export_id,
            TREE_EXPORT_DEFAULT_TIMEOUT_SECONDS,
            TREE_EXPORT_POLL_INTERVAL_SECONDS,
        )
    except RuntimeError as exc:
        if str(exc).startswith("115 导出目录树超时"):
            raise RuntimeError(_tree_export_timeout_guide(task, export_id, exc)) from exc
        raise
    durations["等待官方生成"] = max(0.0, time.perf_counter() - stage_started)
    await write_log(f"等待官方生成：{_format_tree_elapsed_seconds(durations['等待官方生成'])}")
    file_id = str(result.get("file_id", "") or "").strip()
    file_name = str(result.get("file_name", "") or "").strip()
    pick_code = str(result.get("pick_code", "") or "").strip()
    if not file_id or not pick_code:
        raise RuntimeError(f"115 导出目录树结果不完整：{result}")
    _update_tree_export_job(job_id, file_id=file_id, file_name=file_name, pick_code=pick_code, status="replacing")

    stage_started = time.perf_counter()
    await update_progress("替换网盘树文件", 60, tree_name)
    await asyncio.to_thread(_wait_115_export_file_ready, cookie, file_id)
    await asyncio.to_thread(_replace_115_tree_file, cookie, file_id, tree_name)
    durations["替换网盘树文件"] = max(0.0, time.perf_counter() - stage_started)
    await write_log(f"替换网盘树文件：{_format_tree_elapsed_seconds(durations['替换网盘树文件'])}")
    gen_subtotal = durations.get("提交导出", 0.0) + durations.get("等待官方生成", 0.0) + durations.get("替换网盘树文件", 0.0)
    await write_log(f"生成目录树小计：{_format_tree_elapsed_seconds(gen_subtotal)}")

    await write_log("【解析目录树】")
    stage_started = time.perf_counter()
    sha1 = await asyncio.to_thread(get_115_file_sha1_by_id, cookie, file_id)
    durations["sha1 对比"] = max(0.0, time.perf_counter() - stage_started)
    await write_log(f"sha1 对比：{_format_tree_elapsed_seconds(durations['sha1 对比'])}（{str(sha1 or '')[:12]}…）")
    if sha1:
        _update_tree_export_job(job_id, sha1=sha1)

    last_sha1 = str(task.get("last_remote_sha1", "") or "").strip()
    last_local_md5 = str(task.get("last_local_md5", "") or "").strip()
    sha1_skip_enabled = bool(cfg.get("sha1_skip", True))
    remote_same = bool(sha1 and last_sha1 and sha1 == last_sha1)
    if remote_same and (not full) and sha1_skip_enabled:
        await write_log(f"sha1 未变化（{sha1[:12]}…），跳过下载与解析")
        await write_log(f"解析目录树小计：{_format_tree_elapsed_seconds(durations.get('sha1 对比', 0.0))}（未变化跳过）")
        await _write_tree_timing_summary(durations, gen_subtotal)
        _update_tree_export_job(job_id, status="completed", changed=0, completed_at=now_text())
        return {"status": "skipped", "changed": False, "sha1": sha1}

    stage_started = time.perf_counter()
    raw_bytes = None
    if remote_same and full:
        _tree_key, _cache_path, raw_path = _tree_task_cache_paths(task)
        raw_bytes = await asyncio.to_thread(_load_tree_raw_cache, raw_path)
    if raw_bytes is None:
        await update_progress("下载目录树", 70, tree_name)
        raw_bytes = await asyncio.to_thread(_download_exported_tree_bytes, cookie, pick_code)

    local_md5 = hashlib.md5(raw_bytes).hexdigest()
    if (not remote_same) and (not sha1) and last_local_md5 and local_md5 == last_local_md5 and (not full) and sha1_skip_enabled:
        await write_log("远端 sha1 不可用，本地缓存 md5 未变化，跳过解析")
        durations["下载并解析"] = max(0.0, time.perf_counter() - stage_started)
        await write_log(f"解析目录树小计：{_format_tree_elapsed_seconds(durations.get('sha1 对比', 0.0) + durations.get('下载并解析', 0.0))}（未变化跳过）")
        await _write_tree_timing_summary(durations, gen_subtotal)
        _update_tree_export_job(job_id, status="completed", changed=0, completed_at=now_text())
        return {"status": "skipped", "changed": False, "sha1": sha1}

    await update_progress("解析写入 STRM", 80, tree_name)
    counts = await _sync_task_tree_bytes(cfg, task, raw_bytes, force_full=full)
    durations["下载并解析"] = max(0.0, time.perf_counter() - stage_started)
    await write_log(f"下载并解析：{_format_tree_elapsed_seconds(durations['下载并解析'])}（命中 {counts.get('matched_count', 0)} 条）")
    parse_subtotal = durations.get("sha1 对比", 0.0) + durations.get("下载并解析", 0.0)
    await write_log(f"解析目录树小计：{_format_tree_elapsed_seconds(parse_subtotal)}")
    await _write_tree_timing_summary(durations, gen_subtotal)

    new_task = dict(task)
    if sha1:
        new_task["last_remote_sha1"] = sha1
    new_task["last_local_md5"] = local_md5
    _upsert_tree_task(cfg, new_task)
    _update_tree_export_job(
        job_id,
        status="completed",
        changed=1,
        parsed_count=int(counts.get("parsed_count", 0) or 0),
        generated_count=int(counts.get("generated_count", 0) or 0),
        completed_at=now_text(),
    )
    return {"status": "completed", "changed": True, "sha1": sha1, **counts}


async def run_sync(use_local: bool = False, force_full: bool = False) -> None:
    """目录树全部同步：遍历任务，直接下载已存在的树文件并生成（不做 sha1 跳过），不触发官方导出。"""
    if task_status["running"] or _tree_task_busy():
        return
    cfg = get_config()
    config_error = validate_tree_runtime_config(cfg, use_local)
    if config_error:
        await write_log(f"❌ 目录树全部同步未执行：{config_error}", "error")
        return
    tasks = [
        task
        for task in cfg.get("tree_tasks", [])
        if str((task or {}).get("folder_path", "") or "").strip()
    ]
    if not tasks:
        await write_log("⚠ 未配置任何目录树任务", "warn")
        return
    _set_tree_task_running(True)
    task_status["running"] = True
    schedule_ui_state_push(0)
    started_at = time.perf_counter()
    try:
        await write_log(
            f"━━━━━━━━━━【目录树任务开始 | 全部同步 | {len(tasks)} 个任务（不触发导出，直接下载已存在文件并生成）】━━━━━━━━━━",
            "task-divider",
        )
        for idx, task in enumerate(tasks):
            await update_progress(
                "全部同步",
                (idx / max(len(tasks), 1)) * 90,
                f"{task.get('folder_path', '')}（{task.get('tree_name', '')}）",
            )
            task_started = time.perf_counter()
            try:
                await _sync_existing_tree_task(cfg, task, force_full=force_full, force_fetch=True)
                await write_log(
                    f"任务 {task.get('folder_path', '')}：{_tree_stage_seconds(task_started)}"
                )
            except Exception as exc:
                await write_log(
                    f"⚠ 任务 {task.get('folder_path', '')} 同步失败（{_tree_stage_seconds(task_started)}）：{exc}",
                    "warn",
                )
        await write_log(f"总用时：{_tree_stage_seconds(started_at)}")
        await update_progress("任务完成", 100, "全部同步完成")
        await write_log(
            f"━━━━━━━━━━【目录树任务结束 | 全部同步完成 | 总用时 {_tree_stage_seconds(started_at)}】━━━━━━━━━━",
            "task-divider",
        )
    finally:
        _set_tree_task_running(False)
        task_status["running"] = False
        task_status["progress"].update({"step": "就绪", "percent": 0, "detail": "等待指令..."})
        schedule_ui_state_push(0)
        await asyncio.to_thread(release_process_memory, "tree-sync", True)


async def _sync_existing_tree_task(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    force_full: bool = False,
    force_fetch: bool = False,
) -> None:
    cookie = str(cfg.get("cookie_115", "") or "").strip()
    tree_name = str(task.get("tree_name", "") or "").strip()
    remote_name = _tree_file_remote_name(tree_name)
    entry = _resolve_115_file_entry_by_relative_path(cookie, remote_name)
    sha1 = str(entry.get("sha1", "") or "").strip()
    last_sha1 = str(task.get("last_remote_sha1", "") or "").strip()
    if (
        sha1
        and last_sha1
        and sha1 == last_sha1
        and (not force_full)
        and (not force_fetch)
        and bool(cfg.get("sha1_skip", True))
    ):
        await write_log(f"跳过：{remote_name} sha1 未变化（{sha1[:12]}…）")
        return
    raw_bytes = await asyncio.to_thread(_fetch_115_tree_file_bytes, cookie, remote_name)
    counts = await _sync_task_tree_bytes(cfg, task, raw_bytes, force_full=force_full)
    new_task = dict(task)
    if sha1:
        new_task["last_remote_sha1"] = sha1
    new_task["last_local_md5"] = hashlib.md5(raw_bytes).hexdigest()
    _upsert_tree_task(cfg, new_task)
    await write_log(
        f"{remote_name} 同步完成：生成/更新 {counts.get('generated_count', 0)} | 清理残留 {counts.get('deleted_count', 0)}"
    )
