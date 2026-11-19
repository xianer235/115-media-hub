"""订阅跨盘补源（#10）。

订阅任务（provider ≠ quark）开启 cross_copy_mode 后，把候选中的夸克分享
自动注册为跨盘复制任务，省去手动用 OpenList 跨盘复制的步骤。

流程（save_first，绕开分享直下的限速/次数/验证风险）：
    夸克分享链接 → 转存到夸克专属中转目录 → 列目录匹配拿 fid
    → 创建 cross_copy_jobs（origin=subscription）→ 后台复制到任务网盘

去重：同一订阅任务（origin_ref）+ 同一分享链接 + 同一源条目已有未完成任务时
跳过，避免每轮订阅重复注册；复制成功后按配置删除中转文件。

一个分享里可能有一整个文件夹（比如 12 集），转存后把本次新增的每个条目
都注册成任务：文件夹一个任务（整目录复制），散文件一个任务一个。
"""

import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from ..core import (
    SUBSCRIPTION_CROSS_COPY_SOURCE_PROVIDERS,
    build_subscription_movie_savepath,
    build_subscription_tv_savepath,
    get_config,
    normalize_relative_path,
)
from ..db import db_connection, ensure_db
from ..providers.registry import get_or_none as _get_provider_or_none
from ..providers.registry import label_for as _provider_label
from . import cross_copy_jobs as ccj
from .subscription_episode import _extract_task_episodes_from_file_entry

logger = logging.getLogger(__name__)

# 夸克侧中转目录（与订阅离线中转同级的独立目录，删除只删此目录内文件）
CROSS_COPY_STAGING_ROOT = "云下载/跨盘中转"

# 同一分享补源失败后的冷却（分钟）。见 share_candidate_cooldown_minutes：
# 单条失败等一会儿（多半是单集抖动），成片失败等更久（分享整体不可用）。
CROSS_COPY_RETRY_COOLDOWN_MINUTES = 60
CROSS_COPY_RETRY_COOLDOWN_MINUTES_REPEATED = 360
CROSS_COPY_REPEAT_FAILURE_THRESHOLD = 3


def staging_fallback_max_bytes() -> int:
    """整包转存的体积上限，超过就本轮放弃。

    分享目录扫不出文件时要退回整包转存（层级太深或撞限流时至少不会一集都补不上），
    但整包会把不付费的夸克账号一次塞满：一旦真塞满，后面所有补源都会失败，而多转
    进来的文件没有任何路径会删，只能等保留期。所以给一个上限：

    - ``CROSS_COPY_STAGING_FALLBACK_MAX_GB``（默认 10，0 或负数 = 不限制）；
    - 分享条目全都没带 size（例如整包是个文件夹、体积拿不到）时不拦截，保持
      原来的可用性，只在日志里说明「按整包转存」。
    """
    try:
        gb = float(os.environ.get("CROSS_COPY_STAGING_FALLBACK_MAX_GB", 10) or 10)
    except (TypeError, ValueError):
        gb = 10.0
    if gb <= 0:
        return 0
    return int(gb * 1024 ** 3)


# 「真正接通」的源网盘判定直接复用 core 里的白名单（也是任务字段归一化的白名单），
# 不另建一份常量：跨盘复制引擎本身支持 115/夸克/阿里互传，但补源只把
# 「夸克 → 目标盘」接进了主链路，其余源即使勾上也不会执行。
# 前端 static/js/modules/subscription/ui.js 的 SUBSCRIPTION_CROSS_COPY_SUPPORTED_SOURCES
# 必须与这份名单保持一致，否则又会出现「界面能勾、后端静默跳过」的错位。


def split_cross_copy_sources(sources: Any) -> Tuple[List[str], List[str]]:
    """把任务里勾的源网盘拆成「已接通」和「未接通被忽略」两组。

    返回 ``(usable, skipped)``，两者都是去重后的 provider 代号列表。
    未接通的源不报错、不中断订阅，由调用方写一条 warn 日志说明已跳过，
    避免用户误以为「补源开着在从阿里找资源，其实一次搜索都没发」。
    """
    usable: List[str] = []
    skipped: List[str] = []
    for item in (sources if isinstance(sources, (list, tuple, set)) else []):
        name = str(item or "").strip()
        if not name:
            continue
        target = usable if name in SUBSCRIPTION_CROSS_COPY_SOURCE_PROVIDERS else skipped
        if name not in target:
            target.append(name)
    return usable, skipped

# 单轮订阅最多处理几个分享候选（按分享算，不是按任务算）
MAX_REGISTERED_PER_RUN = 3

# 清理中转空目录时最多往下探几层（分享常见的「Season 1/」再套一层就够）
STAGING_CLEANUP_MAX_DEPTH = 3

# 单个分享内部最多注册多少个条目（防止一个大分享一次注册上百个任务）
# 可用环境变量 CROSS_COPY_SUBSCRIPTION_MAX_FILES 调整
MAX_FILES_PER_SHARE = 50


def _max_files_per_share() -> int:
    """单个分享的注册上限：环境变量优先，非法值回退到 MAX_FILES_PER_SHARE。"""
    raw = str(os.environ.get("CROSS_COPY_SUBSCRIPTION_MAX_FILES", "") or "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return int(MAX_FILES_PER_SHARE)
    return value if value > 0 else int(MAX_FILES_PER_SHARE)


# 分享目录扫描上限：真实夸克资源常见「分享根 → 剧名 → Season N → 文件」，
# 最多下探 3 层；目录数上限防止一个巨无霸分享把整轮订阅拖死。
SHARE_SCAN_MAX_DEPTH = 3
SHARE_SCAN_MAX_DIRS = 40


def _share_save_task_timeout() -> float:
    """等夸克异步转存任务完成的上限（秒），可用 CROSS_COPY_STAGE_TASK_TIMEOUT 调整。"""
    raw = str(os.environ.get("CROSS_COPY_STAGE_TASK_TIMEOUT", "") or "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 120.0
    return value if value > 0 else 120.0


def _staging_visible_timeout() -> float:
    """任务完成后，等新条目出现在目录里的上限（秒）。

    夸克任务状态变「完成」和目录真能查到条目之间有零点几秒偏差；网络抖动时
    列目录也可能拿到旧快照，所以这里再给一小段重试窗口。
    """
    raw = str(os.environ.get("CROSS_COPY_STAGE_VISIBLE_TIMEOUT", "") or "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 20.0
    return value if value > 0 else 20.0



def _staging_relative_path(task_name: str) -> str:
    """中转目录按订阅任务分子目录，避免多任务文件混在一起。"""
    safe_name = "".join(ch for ch in str(task_name or "") if ch not in '/\\:*?"<>|').strip()
    if not safe_name:
        safe_name = "未命名任务"
    return f"{CROSS_COPY_STAGING_ROOT}/{safe_name[:60]}"


def _cross_copy_target_savepath(task: Dict[str, Any], candidate: Dict[str, Any]) -> str:
    """补源文件在目标网盘的落点 = 订阅任务本来会保存到的那个目录。

    和订阅导入共用同一套函数，不在这里另拼字符串：
    - 电影：``build_subscription_movie_savepath`` → ``<savepath>/片名 年份``；
    - 剧集：``build_subscription_tv_savepath`` → ``<savepath>/Season NN``，季号
      取候选自己的季（和导入时逐文件判定一致）；候选没识别出季或季号不符被
      延后判定时，回落到任务配置的季。

    补源复制的是「分享里的一个条目」，落点必须是作品目录，否则电影会散在
    savepath 根上、剧集会缺 Season 层，和正常订阅导入的结果对不上。
    """
    base_savepath = normalize_relative_path(str(task.get("savepath", "") or ""))
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    if media_type != "tv":
        return build_subscription_movie_savepath(task, base_savepath) or base_savepath
    candidate_season = max(0, int((candidate or {}).get("season", 0) or 0))
    if bool((candidate or {}).get("season_mismatch_deferred", False)):
        candidate_season = max(1, int(task.get("season", 1) or 1))
    if candidate_season <= 0:
        candidate_season = max(1, int(task.get("season", 1) or 1))
    return build_subscription_tv_savepath(
        task,
        base_savepath,
        season=candidate_season,
    ) or base_savepath


def find_processed_cross_copy_job(
    origin_ref: str,
    source_share_url: str,
    source_file_id: str = "",
    *,
    any_share: bool = False,
) -> Optional[Dict[str, Any]]:
    """查重：这个分享条目以前是否已经处理完（成功 / 跳过 / 被用户取消）。

    只用来兜住「中转目录里已经有文件」这条分支——那种情况下不重新转存，
    但也不能无脑注册：
      - 已成功复制过 → 跳过，否则会往目标目录再塞一份；
      - 被跳过（skipped）过 → 跳过。skipped 是确定性结论（目标已有同名文件 /
        认不出集数），下一轮再注册只会再 skipped 一次，还把中转副本留到过期、
        日志持续膨胀；
      - 用户手动取消过 → 跳过，尊重用户的决定；
      - 失败过（failed）→ 允许重试，订阅每轮都该有机会补上。

    ``any_share=True`` 时不看分享链接：那一步的前提是「中转目录里已有同名同大小
    的文件」，而中转目录里的同一个文件只会有一份——不同分享是同一资源转贴时，
    按分享链接查重查不到，会再建一个复制任务指向同一份文件（目标盘重复）。
    """
    ensure_db()
    sql = """
        SELECT * FROM cross_copy_jobs
        WHERE origin = 'subscription' AND origin_ref = ?
          AND status IN ('completed', 'cancelled', 'skipped')
    """
    params: List[Any] = [str(origin_ref or "")]
    if not any_share:
        sql += " AND source_share_url = ?"
        params.append(str(source_share_url or ""))
    wanted_file_id = str(source_file_id or "").strip()
    if wanted_file_id:
        sql += " AND source_file_id = ?"
        params.append(wanted_file_id)
    sql += " ORDER BY id DESC LIMIT 1"
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
    if not row:
        return None
    from ..db import sqlite_row_to_dict

    return sqlite_row_to_dict(row)


def find_active_cross_copy_job(
    origin_ref: str,
    source_share_url: str,
    source_file_id: str = "",
    *,
    any_share: bool = False,
) -> Optional[Dict[str, Any]]:
    """查重：同一订阅任务 + 同一分享链接是否已有未完成的补源任务。

    source_file_id 传了就再收窄到「同一源条目」——一个分享会注册多个任务，
    只按分享查重会把同一分享里的第二个条目误判成「已在队列中」。
    不传（默认空）时行为和以前完全一致：只看任务 + 分享链接。

    ``any_share`` 口径同上：源条目 id 已能唯一定位中转文件时，不必再绑分享链接。
    """
    ensure_db()
    sql = """
        SELECT * FROM cross_copy_jobs
        WHERE origin = 'subscription' AND origin_ref = ?
          AND status IN ('pending', 'running')
    """
    params: List[Any] = [str(origin_ref or "")]
    if not any_share:
        sql += " AND source_share_url = ?"
        params.append(str(source_share_url or ""))
    wanted_file_id = str(source_file_id or "").strip()
    if wanted_file_id:
        sql += " AND source_file_id = ?"
        params.append(wanted_file_id)
    sql += " ORDER BY id DESC LIMIT 1"
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
    if not row:
        return None
    from ..db import sqlite_row_to_dict

    return sqlite_row_to_dict(row)


def share_candidate_cooldown_minutes(origin_ref: str, share_url: str) -> int:
    """同一分享刚失败过就先等一会儿，返回还要等多少分钟（0 = 现在就能试）。

    为什么需要：失败的补源任务允许重试，但没有节流。分享被删、被限流封禁这类
    **确定性**失败会「扫描成功 → 转存/下载失败」，而订阅默认半小时一轮，于是每
    一轮都白扫一次目录、白试一次转存，永远不停。

    冷却时长分两档（**不按失败条数判「连续失败」**）：一次失败会一次性产生
    N 条任务记录（一集一条），按条数算会让偶发失败立刻被当成「连续失败 3 次」。
    这里改成看「最近这一段连续失败里有几条」：
      - 只有 1 条 → 等 ``CROSS_COPY_RETRY_COOLDOWN_MINUTES``（默认 60 分钟，
        多半是单集下载抖动，断点还在，短等足够）；
      - ≥ ``CROSS_COPY_REPEAT_FAILURE_THRESHOLD`` 条 → 等
        ``CROSS_COPY_RETRY_COOLDOWN_MINUTES_REPEATED``（默认 360 分钟），
        这种情况基本是分享整体不可用，多等一会儿把机会留给别的候选。

    冷却到期后自动放行（分享可能恢复）。成功、取消、跳过都算「连续失败中断」。
    """
    share = str(share_url or "").strip()
    if not share:
        return 0
    ensure_db()
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status, finished_at FROM cross_copy_jobs
                WHERE origin = 'subscription' AND origin_ref = ? AND source_share_url = ?
                ORDER BY id DESC LIMIT 40
                """,
                (str(origin_ref or ""), share),
            )
            rows = cursor.fetchall() or []
    except Exception:  # noqa: BLE001 - 查不到历史就按「不需要冷却」处理
        return 0
    consecutive = 0
    latest_failed_at = ""
    for row in rows:
        status = str(row[0] or "").strip().lower()
        if status != "failed":
            break
        consecutive += 1
        if not latest_failed_at:
            latest_failed_at = str(row[1] or "").strip()
    if not consecutive or not latest_failed_at:
        return 0
    window_minutes = (
        CROSS_COPY_RETRY_COOLDOWN_MINUTES_REPEATED
        if consecutive >= CROSS_COPY_REPEAT_FAILURE_THRESHOLD
        else CROSS_COPY_RETRY_COOLDOWN_MINUTES
    )
    try:
        finished = datetime.fromisoformat(latest_failed_at)
    except (TypeError, ValueError):
        return window_minutes
    elapsed = (datetime.now() - finished).total_seconds() / 60.0
    remain = window_minutes - elapsed
    return int(remain) + 1 if remain > 0 else 0


def candidate_wait_reason(origin_ref: str, candidate: Dict[str, Any]) -> str:
    """这个候选现在该不该跳过？返回空串表示可以处理。

    两件事都在**只读评估之前**判断，省掉一次目录递归扫描：
      ① 该分享已有 pending/running 的补源任务——正在下载/上传，扫了也用不上；
      ② 该分享刚失败过且在冷却窗口内（见 ``share_candidate_cooldown_minutes``）。
    """
    share_url = _extract_share_url(candidate) if isinstance(candidate, dict) else ""
    if not share_url:
        return ""
    if find_active_cross_copy_job(origin_ref, share_url):
        return f"该分享的补源任务还在进行中，本轮不重复扫描：{share_url[:40]}"
    wait_minutes = share_candidate_cooldown_minutes(origin_ref, share_url)
    if wait_minutes > 0:
        return f"该分享刚补源失败，{wait_minutes} 分钟后再试：{share_url[:40]}"
    return ""


def _extract_share_url(candidate: Dict[str, Any]) -> str:
    item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
    return str(item.get("link_url", "") or "").strip()


def _is_plausible_share_url(url: str) -> bool:
    """粗筛分享链接是否被长文本拼接污染。

    TG 消息里一条 URL 后面经常紧跟别的内容，提取时会把尾巴粘上来
    （实测拿到 ``https://pan.quark.cn/s/xxxhttps``），这种链接转存必然失败，
    白白占掉一个「本轮最多注册 N 条」的名额。
    """
    value = str(url or "").strip()
    if not value:
        return False
    if not re.match(r"^https?://", value, re.IGNORECASE):
        return False
    if value.count("http") != 1:
        return False
    return " " not in value


def _extract_receive_code(candidate: Dict[str, Any]) -> str:
    item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    return str(item.get("receive_code", "") or extra.get("receive_code", "") or "").strip()


def _pick_share_candidates(candidates: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """从订阅候选中挑出夸克分享候选（按评分降序，去重分享链接）。"""
    picked: List[Dict[str, Any]] = []
    seen_urls: set = set()
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
        link_type = str(item.get("link_type", "") or "").strip().lower()
        share_url = _extract_share_url(candidate)
        if link_type and link_type != "quark":
            continue
        if not share_url or share_url.lower() in seen_urls:
            continue
        if not _is_plausible_share_url(share_url):
            continue
        seen_urls.add(share_url.lower())
        picked.append(candidate)
        if len(picked) >= limit:
            break
    return picked


def _entry_id(entry: Dict[str, Any]) -> str:
    return str(entry.get("id", "") or entry.get("fid", "") or "").strip()


def _entry_name(entry: Dict[str, Any]) -> str:
    return str(entry.get("name", "") or entry.get("file_name", "") or "").strip()


def _entry_size(entry: Dict[str, Any]) -> int:
    try:
        return int(entry.get("size", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _entry_is_dir(entry: Dict[str, Any]) -> bool:
    """这条是文件夹还是文件？只认列表项里的 is_dir。

    夸克的列表项统一经 app/providers/quark.py 的 _parse_quark_entry 解析，
    里面按 file_type / dir / obj_category 算好了 is_dir（bool）。拿不到这个
    字段就一律按文件处理——不凭「大小为 0」「没有后缀」去猜，猜错了要么把
    文件夹当文件注册、要么把文件当文件夹，都是白跑一趟。
    """
    raw = entry.get("is_dir")
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    try:
        return bool(int(raw))
    except (TypeError, ValueError):
        return bool(raw)


def _staging_keys(entries: List[Dict[str, Any]]) -> set:
    """中转目录现有条目的 (名字, 大小) 集合，用来判断哪些是这轮新转存进来的。"""
    keys = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name = _entry_name(entry)
        if not name:
            continue
        keys.add((name, _entry_size(entry)))
    return keys


def _stage_share_to_quark(
    quark_provider,
    cookie: str,
    share_url: str,
    receive_code: str,
    staging_rel_path: str,
    task: Optional[Dict[str, Any]] = None,
    last_episode: int = 0,
    existing_episodes: Optional[Set[int]] = None,
    prescanned_files: Optional[List[Dict[str, Any]]] = None,
    share_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把夸克分享转存到中转目录，返回本次真正新进来的条目。

    返回结构::

        {
          "folder_id": "中转目录 id",
          "folders": [{"id": ..., "name": ..., "size": ...}],  # 新转存进来的文件夹
          "files":   [{"id": ..., "name": ..., "size": ...}],  # 新转存进来的散文件
          "skipped": ["跳过原因（人话）", ...],
          "already_staged": True/False,  # 分享内容上次已经全部转存过
        }

    中转目录是按订阅任务复用的，里面可能躺着前几轮转存的文件，所以不能
    「转存后把目录里所有东西都注册一遍」——那样会把历史文件重复补一遍。
    这里的做法是：转存前先记下目录里已有的 (名字, 大小)，只把缺的条目发给
    夸克转存，转存后重新列目录，只认不在旧集合里的条目。同名同大小的老条目
    一律当已存在跳过（宁可少补一次，也不要白跑一遍复制）。

    一个分享里可能是文件夹（12 集），也可能是几个散文件，还可能是混合，
    所以返回的是列表而不是单个文件。

    剧集任务传了 ``task`` + 进度（``last_episode`` / ``existing_episodes``）时，
    会**先扫分享、只转存缺的集**（返回里 ``episode_filtered=True``），不再整包
    转存；转存这一步省下的是夸克侧配额，后面的复制本来也只做缺的集。

    传了 ``prescanned_files``（调用方已经只读扫过分享、算好缺集）时直接按这份
    清单转存：省掉一次重复扫目录，也**不再依赖「本盘已有进度」这个前提**——
    首轮补源（本盘一集都没有）同样按集转存，不会整包搬一份重复的进中转。
    ``share_payload`` 同理，评估阶段解析过就直接复用。
    """
    share_payload = share_payload or quark_provider.resolve_share_payload(
        cookie, share_url, "", receive_code
    )
    listed = quark_provider.list_share_entries(cookie, share_payload, cid="0")
    # 真实 provider 返回 {"entries": [...], "summary": ...}（见 base.list_share_entries
    # 的 Dict 契约），不是裸列表；2026-10-20 真机发现这里按列表迭代导致分享永远
    # 被判定为空，订阅补源转存整链不可用。
    raw_entries = listed.get("entries", []) if isinstance(listed, dict) else (listed or [])
    entries = [entry for entry in raw_entries if isinstance(entry, dict)]
    if not entries:
        raise RuntimeError("分享内没有可转存的文件")

    folder_id = ""
    skipped: List[str] = []
    share_entries: List[Dict[str, Any]] = []
    for entry in entries:
        entry_id = _entry_id(entry)
        name = _entry_name(entry)
        if not entry_id or not name:
            continue
        share_entries.append(
            {
                "id": entry_id,
                "name": name,
                "size": _entry_size(entry),
                "is_dir": _entry_is_dir(entry),
                "fid_token": str(
                    entry.get("fid_token", "") or entry.get("share_fid_token", "") or ""
                ).strip(),
            }
        )
    if not share_entries:
        raise RuntimeError("分享内没有可转存的文件")

    # 剧集 + 本盘已有进度时，只把「缺的集」转存进夸克中转，而不是整包。
    # 以前是整包转存、再去中转目录里筛：文件虽然筛掉了，但夸克配额已经被整包
    # 占住（不付费账号一个 30GB 的季包就塞满），转存那几秒也白等。
    # 扫不出文件（目录读取失败 / 层级太深）才退回整包，至少不会一集都补不上。
    episode_filtered = False
    if prescanned_files is not None:
        # 调用方（register_cross_copy_from_candidates）已经只读扫过这个分享、
        # 按「本盘缺哪几集」算好了清单。这里直接照单转存：
        # ① 不重复扫一次分享目录；② 不再要求「本盘已有进度」才筛集——
        # 首轮补源正是最容易把整包重复搬进中转的场景。
        pending_files = [
            item
            for item in prescanned_files
            if isinstance(item, dict) and _entry_id(item) and str(item.get("name", "") or "").strip()
        ]
        if not pending_files:
            return {
                "folder_id": "",
                "folders": [],
                "files": [],
                "skipped": skipped + ["分享里没有本盘缺的集，本次不转存（不占配额）"],
                "already_staged": False,
                "episode_filtered": True,
            }
        share_entries = [
            {
                "id": _entry_id(item),
                "name": str(item.get("name", "") or "").strip(),
                "size": int(item.get("size", 0) or 0),
                "is_dir": False,
                "fid_token": str(item.get("fid_token", "") or ""),
                "parent_id": str(item.get("parent_id", "") or "0"),
            }
            for item in pending_files
        ]
        episode_filtered = True
        skipped.append(
            "只转存本盘缺的集："
            + "、".join(f"E{int(item.get('episode', 0) or 0)}" for item in pending_files)
        )
    elif (
        task is not None
        and str(task.get("media_type", "") or "").strip().lower() == "tv"
        and (int(last_episode or 0) > 0 or existing_episodes)
    ):
        scanned, scan_notes = _scan_share_media_files(quark_provider, cookie, share_payload)
        skipped.extend(scan_notes)
        if scanned:
            missing, why = _select_missing_episode_files(
                task, scanned, "", last_episode, existing_episodes
            )
            skipped.extend(why)
            missing = _dedupe_episode_files(missing)
            if not missing:
                return {
                    "folder_id": "",
                    "folders": [],
                    "files": [],
                    "skipped": skipped + ["分享里没有本盘缺的集，本次不转存（不占配额）"],
                    "already_staged": False,
                    "episode_filtered": True,
                }
            share_entries = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "size": int(item.get("size", 0) or 0),
                    "is_dir": False,
                    "fid_token": str(item.get("fid_token", "") or ""),
                    "parent_id": str(item.get("parent_id", "") or "0"),
                }
                for item in missing
            ]
            episode_filtered = True
            skipped.append(
                "只转存本盘缺的集："
                + "、".join(f"E{int(item.get('episode', 0) or 0)}" for item in missing)
            )
        else:
            # 退回整包之前先看体积：整包把配额塞满之后，后面所有补源都会失败，
            # 而多转进来的部分没有任何路径会删（只能等保留期）。宁可这一轮不补，
            # 下一轮重扫——扫描失败多半是限流或网络抖动，会自己好。
            total_bytes = sum(
                _entry_size(item) for item in share_entries if not _entry_is_dir(item)
            )
            limit_bytes = staging_fallback_max_bytes()
            if limit_bytes and total_bytes > limit_bytes:
                return {
                    "folder_id": "",
                    "folders": [],
                    "files": [],
                    "skipped": skipped
                    + [
                        f"分享目录读不出文件，退回整包需转存 {total_bytes / (1024 ** 3):.1f}GB，"
                        f"超过整包上限 {limit_bytes / (1024 ** 3):.0f}GB，本轮不转存"
                        "（避免占满夸克空间），下一轮再试"
                    ],
                    "already_staged": False,
                    "episode_filtered": False,
                }
            skipped.append("分享目录里没扫到文件，本轮按整包转存")

    folder_id = str(quark_provider.ensure_folder_id_by_path(cookie, staging_rel_path) or "0")

    existing_entries = [
        entry for entry in (quark_provider.list_entries(cookie, folder_id) or []) if isinstance(entry, dict)
    ]
    existing_keys = _staging_keys(existing_entries)
    pending: List[Dict[str, Any]] = []
    for item in share_entries:
        if (item["name"], item["size"]) in existing_keys:
            skipped.append(f"中转目录已有同名文件，跳过：{item['name']}")
            continue
        pending.append(item)

    if not pending:
        # 分享内容已在中转目录里。这可能是「上一轮转存成功、但注册/复制没走完」，
        # 也可能是「已经在补过、中转文件还没删」，所以不能一律当没事发生：
        # 把目录里对应的条目原样返回，交给注册侧查重后再决定要不要补注册。
        skipped.append("这个分享的内容上次已经转存过，这次不再重复转存")
        reused_folders: List[Dict[str, Any]] = []
        reused_files: List[Dict[str, Any]] = []
        for entry in existing_entries:
            name = _entry_name(entry)
            size = _entry_size(entry)
            entry_id = _entry_id(entry)
            if not entry_id or not name:
                continue
            if (name, size) not in {(item["name"], item["size"]) for item in share_entries}:
                continue
            target = reused_folders if _entry_is_dir(entry) else reused_files
            target.append({"id": entry_id, "name": name, "size": size, "is_dir": _entry_is_dir(entry)})
        return {
            "folder_id": folder_id,
            "folders": reused_folders,
            "files": reused_files,
            "skipped": skipped,
            "already_staged": True,
            "episode_filtered": episode_filtered,
        }

    # 单个分享最多处理 MAX_FILES_PER_SHARE 个条目，超出的留给下一轮（不静默截断）
    cap = _max_files_per_share()
    if len(pending) > cap:
        skipped.append(
            f"本次分享共 {len(share_entries)} 个条目，这轮只补前 {cap} 个，"
            f"其余 {len(pending) - cap} 个下次再补"
        )
        pending = pending[:cap]

    selected_entries = [
        {
            "id": item["id"],
            "name": item["name"],
            "size": item["size"],
            "is_dir": item["is_dir"],
            "cid": item["id"] if item["is_dir"] else "",
            "fid": "" if item["is_dir"] else item["id"],
            "fid_token": item["fid_token"],
            # 按文件转存时，parent_id 是夸克补 fid_token 的入口；根条目为 "0"
            "parent_id": str(item.get("parent_id", "") or "0"),
        }
        for item in pending
    ]
    receive_payload = quark_provider.prepare_share_receive(
        cookie,
        {
            **share_payload,
            "selected_ids": [item["id"] for item in selected_entries],
            "selected_entries": selected_entries,
        },
        cid=folder_id,
    )
    save_result = quark_provider.submit_share_receive(cookie, receive_payload, selected_entries)

    # 夸克的 save 只是「提交任务」，文件要过一会儿才进目录。2026-10-22 真机实测：
    # 立刻列目录必然拿到旧列表，整条补源挂在「转存后没在中转目录找到新条目」上。
    # 所以先等 task 落地，再列目录；任务状态没确认也不直接判失败，继续给一个可见窗口。
    wait_timeout = _share_save_task_timeout()
    wait_fn = getattr(quark_provider, "wait_share_save", None)
    if callable(wait_fn):
        try:
            wait_result = wait_fn(
                cookie,
                save_result,
                timeout=wait_timeout,
                interval=1.0,
            )
        except Exception as exc:
            wait_result = {"ok": False, "reason": str(exc)}
    else:
        # provider 没实现任务等待（例如测试桩）：退回「直接列目录 + 短窗口重试」
        wait_result = {"ok": True, "status": 0, "reason": "provider 未实现任务等待"}
    if isinstance(wait_result, dict) and not wait_result.get("ok", False):
        reason = str(wait_result.get("reason", "") or "").strip()
        skipped.append(
            "夸克转存任务未确认完成"
            + (f"（{reason}）" if reason else "")
            + "，仍继续等目录出现新条目"
        )

    def _diff_entries(entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
        """从当前目录列表里挑出这轮新进来的条目，并返回是否带文件/文件夹标记。"""
        dir_flag = any("is_dir" in entry for entry in entries)
        fresh: List[Dict[str, Any]] = []
        seen_local = set()
        for entry in entries:
            entry_id = _entry_id(entry)
            name = _entry_name(entry)
            if not entry_id or not name:
                continue
            key = (name, _entry_size(entry))
            if key in existing_keys or key in seen_local:
                continue
            seen_local.add(key)
            fresh.append(
                {
                    "id": entry_id,
                    "name": name,
                    "size": _entry_size(entry),
                    "is_dir": _entry_is_dir(entry),
                }
            )
        return fresh, dir_flag

    # 任务完成后目录可能还有零点几秒延迟，留一个短窗口重试，避免偶发误判
    visible_deadline = time.monotonic() + _staging_visible_timeout()
    has_dir_flag = False
    new_entries: List[Dict[str, Any]] = []
    attempts = 0
    while True:
        attempts += 1
        staged_entries = [
            entry
            for entry in (quark_provider.list_entries(cookie, folder_id) or [])
            if isinstance(entry, dict)
        ]
        new_entries, has_dir_flag = _diff_entries(staged_entries)
        if new_entries or time.monotonic() >= visible_deadline:
            break
        time.sleep(1.5)

    if not new_entries:
        raise RuntimeError(
            "转存后没在中转目录找到新条目"
            f"（等任务 {int(wait_timeout)} 秒 + 列目录重试 {attempts} 次）"
        )

    if not has_dir_flag:
        # 拿不到文件/文件夹标记时保守处理：全部当文件注册，并在报告里说明
        skipped.append("目录列表没有文件/文件夹标记，这次全部按文件注册")

    return {
        "folder_id": folder_id,
        "folders": [item for item in new_entries if item["is_dir"]],
        "files": [item for item in new_entries if not item["is_dir"]],
        "skipped": skipped,
        "already_staged": False,
        "episode_filtered": episode_filtered,
    }


def _scan_share_media_files(
    provider: Any,
    cookie: str,
    share_payload: Dict[str, Any],
    max_depth: int = SHARE_SCAN_MAX_DEPTH,
    max_dirs: int = SHARE_SCAN_MAX_DIRS,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """在分享里递归列文件（只读，不转存），返回带相对路径的条目。

    为什么要先扫分享：补源真正需要的往往只是「缺的那几集」。以前是把分享根
    条目整包转存进夸克中转，再在中转目录里筛——文件是筛掉了，但**配额已经
    被整包占了**（夸克不付费时一个 30GB 的季包就能塞满），转存那几秒也白等。

    比 `_expand_staged_folder_media_files` 多返回 `parent_id` / `fid_token`：
    夸克按文件转存要这两个字段，缺 token 时 prepare 阶段还得再扫一遍目录。
    """
    notes: List[str] = []
    files: List[Dict[str, Any]] = []
    pending: List[Tuple[str, str, int]] = [("0", "", 0)]
    visited: set = set()
    while pending and len(visited) < max_dirs:
        cid, prefix, depth = pending.pop(0)
        normalized_cid = str(cid or "0").strip() or "0"
        if normalized_cid in visited:
            continue
        visited.add(normalized_cid)
        try:
            listed = provider.list_share_entries(cookie, share_payload, cid=normalized_cid)
        except Exception as exc:  # noqa: BLE001 - 某个子目录读不出来不该拖垮整轮
            notes.append(f"分享目录读取失败（{prefix or '/'}）：{exc}")
            continue
        entries = listed.get("entries", []) if isinstance(listed, dict) else (listed or [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = _entry_id(entry)
            name = _entry_name(entry)
            if not entry_id or not name:
                continue
            rel_path = f"{prefix}/{name}".strip("/") if prefix else name
            if _entry_is_dir(entry):
                if depth < max_depth:
                    pending.append((entry_id, rel_path, depth + 1))
                continue
            files.append(
                {
                    "id": entry_id,
                    "name": name,
                    "rel_path": rel_path,
                    "size": _entry_size(entry),
                    "is_dir": False,
                    "parent_id": normalized_cid,
                    "fid_token": str(
                        entry.get("fid_token", "") or entry.get("share_fid_token", "") or ""
                    ).strip(),
                }
            )
    if pending:
        notes.append(f"分享目录超过 {int(max_dirs)} 个，已停止继续下探")
    return files, notes


def _dedupe_episode_files(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一集常同时有 4K / 1080p 两份，只留体积最大的那个。

    只在这里去重，是为了别把两份都转存进夸克——白占双倍配额。真要挑画质，
    入口应该是订阅任务的画质偏好，而不是靠文件名里碰运气。
    """
    best: Dict[int, Dict[str, Any]] = {}
    for item in files:
        episode_no = int(item.get("episode", 0) or 0)
        if episode_no <= 0:
            continue
        current = best.get(episode_no)
        if current is None or int(item.get("size", 0) or 0) > int(current.get("size", 0) or 0):
            best[episode_no] = item
    return [best[key] for key in sorted(best)]


def _expand_staged_folder_media_files(
    provider: Any,
    cookie: str,
    folder_id: str,
    max_depth: int = 2,
) -> List[Dict[str, Any]]:
    """列出中转文件夹里的文件（含浅层子目录），返回带相对路径的条目。

    整季分享的常见形态是「一个文件夹里直接躺着 S01E01~E44」，也偶见
    `Season 1/` 再套一层。这里最多下探两层，够用又不至于在大目录上炸开。
    """
    files: List[Dict[str, Any]] = []
    pending: List[Tuple[str, str, int]] = [(str(folder_id or "").strip(), "", 0)]
    while pending:
        current_id, prefix, depth = pending.pop(0)
        if not current_id:
            continue
        try:
            entries = provider.list_entries(cookie, current_id) or []
        except Exception:
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = _entry_id(entry)
            name = _entry_name(entry)
            if not entry_id or not name:
                continue
            rel_path = f"{prefix}/{name}".strip("/") if prefix else name
            if _entry_is_dir(entry):
                if depth + 1 <= max_depth:
                    pending.append((entry_id, rel_path, depth + 1))
                continue
            files.append(
                {
                    "id": entry_id,
                    "name": name,
                    "rel_path": rel_path,
                    "size": _entry_size(entry),
                    "is_dir": False,
                }
            )
    return files


def _select_missing_episode_files(
    task: Dict[str, Any],
    files: List[Dict[str, Any]],
    parent_path: str,
    last_episode: int,
    existing_episodes: Optional[Set[int]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """按集数挑出「本盘还没有」的文件。

    返回 ``(要复制的文件, 跳过说明)``。集数解析复用订阅侧的
    `_extract_task_episodes_from_file_entry`：它认得 SxxEyy、Exx、裸数字、
    "第N集" 这些写法，也会顺手过滤字幕/音频/非视频文件。

    判「已存在」有两种口径：

    - 传了 ``existing_episodes``（目标目录实际落盘的集集合）：文件覆盖的集
      **全部**都在集合里才跳过。这是主用口径——只看最高集会漏掉中间缺集，
      而分享常带整季范围（一条 E1-E44 的文件），里面只要有一集本盘没有就
      仍要复制整个文件。
    - 没传就退回 ``last_episode``（最高集）：``newest <= last_episode`` 视为已有。

    解析不出集数的文件一律不复制——补源只该补「正片集」，猜错就是把花絮、
    预告、别人的剧塞进季目录。宁可这一轮少补，也不要污染库结构。
    """
    selected: List[Dict[str, Any]] = []
    skipped: List[str] = []
    normalized_existing = (
        {max(0, int(item or 0)) for item in existing_episodes if max(0, int(item or 0)) > 0}
        if existing_episodes is not None
        else None
    )
    for item in files:
        # 优先用带相对路径的条目名解析集数：分享里内嵌 `Season 2/` 子目录时，
        # 裸文件名 `S01E42.mp4` 里的 "S01" 会被误当成季号，把 S02 的集判成 S01
        # 并落进 Season 01。把 `rel_path`（含父目录）传进去，`_extract_task_episodes_
        # from_file_entry` 会拆出父目录参与季号识别——季号不符的文件（单季任务）
        # 会被正确丢弃，而不是污染别的季目录。
        entry_path = str(item.get("rel_path", "") or "").strip()
        parse_name = entry_path or str(item.get("name", "") or "")
        episodes = _extract_task_episodes_from_file_entry(
            task,
            parse_name,
            parent_path=parent_path,
        )
        if not episodes:
            skipped.append(f"认不出集数，没复制：{item.get('rel_path') or item.get('name')}")
            continue
        newest = max(episodes)
        if normalized_existing is not None:
            if episodes.issubset(normalized_existing):
                continue  # 这个文件覆盖的集本盘全都有，不用重复下
        elif newest <= int(last_episode or 0):
            continue  # 本盘已经有这集，不用重复下
        selected.append({**item, "episode": newest})
    return selected, skipped


def _evaluate_share_candidate(
    provider: Any,
    cookie: str,
    candidate: Dict[str, Any],
    task: Dict[str, Any],
    last_episode: int,
    existing_episodes: Optional[Set[int]],
) -> Dict[str, Any]:
    """只读扫一个候选分享，算出它到底能补哪些缺集。**不转存、不占配额**。

    返回::

        {
          "candidate": 原始候选,
          "share_url": "...",
          "share_payload": {...},   # 后续转存复用，省一次解析
          "scan_ok": True/False,    # 分享目录是否扫出了能认集数的视频
          "files": [...],           # 本盘缺的、可直接按文件转存的条目（同集去重）
          "episodes": {1, 2, ...},  # 上面这些文件覆盖的集
          "notes": ["人话说明", ...],
        }

    为什么要先评估：候选只按标题/评分排序，**和「这个分享里到底有没有缺的集」
    完全无关**。以前的做法是每个候选都先转存再筛，同一部剧的三个分享就会各
    转一份进夸克中转，目标盘也跟着复制三遍（2026-11 实测：3 份 E01~E10）。

    注意 ``scan_ok`` 与「没有缺集」是两件事：前者为 False 表示目录读不出来
    （层级太深 / 被限流），调用方可以退回整包兜底；后者只是本盘真的不缺。
    """
    share_url = _extract_share_url(candidate)
    receive_code = _extract_receive_code(candidate)
    result: Dict[str, Any] = {
        "candidate": candidate,
        "share_url": share_url,
        "share_payload": {},
        "scan_ok": False,
        "files": [],
        "episodes": set(),
        "notes": [],
    }
    try:
        payload = provider.resolve_share_payload(cookie, share_url, "", receive_code)
    except Exception as exc:  # noqa: BLE001 - 单个候选打不开不该拖垮整轮
        result["notes"].append(f"打开分享失败：{share_url[:40]}（{exc}）")
        return result
    if isinstance(payload, dict):
        result["share_payload"] = payload
    scanned, scan_notes = _scan_share_media_files(provider, cookie, payload)
    result["notes"].extend(scan_notes)
    if not scanned:
        result["notes"].append(f"分享里没扫到视频文件：{share_url[:40]}")
        return result
    # 先按「本盘一集都没有」的口径跑一遍，只为了确认「这份分享里到底有没有能认出
    # 集数的正片」。全是花絮/预告/非标准命名时不能记成「本盘不缺」——那样会把
    # 「认不出」误判成「不用补」，一集都补不上。这种情况交给调用方退回整包。
    recognizable, _ = _select_missing_episode_files(task, scanned, "", 0, None)
    if not recognizable:
        result["notes"].append(f"分享里的文件都认不出集数：{share_url[:40]}")
        return result
    missing, why = _select_missing_episode_files(
        task, scanned, "", last_episode, existing_episodes
    )
    result["notes"].extend(why)
    missing = _dedupe_episode_files(missing)
    result["scan_ok"] = True
    result["files"] = missing
    result["episodes"] = {
        int(item.get("episode", 0) or 0)
        for item in missing
        if int(item.get("episode", 0) or 0) > 0
    }
    if not missing:
        result["notes"].append(f"分享里没有本盘缺的集：{share_url[:40]}")
    return result


def _choose_share_plan(evaluations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从评估结果里挑出真正要转存的分享：按「能补的缺集数」贪心，绝不重复搬。

    排序口径：能补的集数降序；同分沿用候选原顺序——``find_subscription_cross_copy_candidates``
    已按「标题命中 → 评分」排过，``sorted`` 是稳定排序，原顺序自然保留。

    为什么是贪心集合覆盖，而不是「只取第一个」：最常见的情况是三个分享都是同一
    部剧的 E01~E10 全集，第一个就覆盖全部缺集，后两个一个都不会转存；但也存在
    「A 只有 E01~E05、B 有 E06~E10」的拆包分享，只取第一个会漏掉一半。
    """
    ranked = sorted(
        (
            item
            for item in (evaluations or [])
            if isinstance(item, dict) and item.get("scan_ok") and item.get("episodes")
        ),
        key=lambda item: -len(item.get("episodes") or ()),
    )
    plan: List[Dict[str, Any]] = []
    covered: Set[int] = set()
    for item in ranked:
        remain = set(item.get("episodes") or set()) - covered
        if not remain:
            continue
        files = [
            file_item
            for file_item in (item.get("files") or [])
            if int(file_item.get("episode", 0) or 0) in remain
        ]
        if not files:
            continue
        plan.append(
            {
                "candidate": item.get("candidate") or {},
                "share_url": str(item.get("share_url", "") or ""),
                "share_payload": item.get("share_payload") or {},
                "mode": "episodes",
                "files": files,
                "notes": list(item.get("notes") or []),
            }
        )
        covered |= remain
    return plan


def cleanup_staging_empty_folders(provider: Any, cookie: str, task_name: str) -> int:
    """删掉补源中转目录里的空文件夹，返回删除个数。

    逐文件复制成功后 `cross_copy_jobs` 会把源文件删掉，但分享带进来的文件夹
    外壳（「某剧 4K 全季」这种）会留在中转目录里当空壳，越积越多；下一条分享
    重新转存时也容易撞上同名空目录。

    只处理 ``<中转根>/<任务名>`` 之下、且**确实为空**的目录：里面还有文件一律
    不动——可能是另一个任务还没复制完的，也可能是认不出集数故意没注册的。
    中转根目录本身永远保留。
    """
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie or not getattr(provider, "supports_delete", False):
        return 0
    resolve_cid = getattr(provider, "resolve_folder_id_by_path", None)
    if not callable(resolve_cid):
        return 0
    try:
        root_cid = str(resolve_cid(normalized_cookie, _staging_relative_path(task_name)) or "").strip()
    except Exception:
        return 0
    # "0" 是网盘根目录，绝不能当成本任务的中转目录去清理
    if not root_cid or root_cid == "0":
        return 0

    nodes: List[Dict[str, Any]] = []

    def _collect(cid: str, depth: int) -> None:
        if depth > STAGING_CLEANUP_MAX_DEPTH:
            return
        try:
            entries = provider.list_entries(normalized_cookie, cid) or []
        except Exception:
            # 读不到就当它有内容：宁可不删，也不能瞎删
            nodes.append({"cid": cid, "has_content": True, "children": []})
            return
        children: List[str] = []
        has_content = False
        for entry in entries:
            if not isinstance(entry, dict):
                has_content = True
                continue
            if _entry_is_dir(entry):
                child_id = _entry_id(entry)
                if child_id:
                    children.append(child_id)
                continue
            has_content = True
        nodes.append({"cid": cid, "has_content": has_content, "children": children})
        for child_id in children:
            _collect(child_id, depth + 1)

    _collect(root_cid, 0)

    # nodes 是按先序追加的，倒着走就能保证子目录先判定、父目录后判定
    deleted: Set[str] = set()
    removed = 0
    for node in reversed(nodes):
        cid = str(node.get("cid", "") or "")
        if not cid or cid == root_cid or node.get("has_content"):
            continue
        if any(str(child) not in deleted for child in (node.get("children") or [])):
            continue  # 还有没删掉的子目录，当前目录不算空
        try:
            provider.delete_entries(normalized_cookie, [cid])
        except Exception as exc:  # 清理失败不影响补源主流程
            logger.info("跨盘补源中转目录清理失败（%s）：%s", cid, exc)
            continue
        deleted.add(cid)
        removed += 1
    return removed


def register_cross_copy_from_candidates(
    *,
    task: Dict[str, Any],
    cfg: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    origin: str = "subscription",
    last_episode: int = 0,
    existing_episodes: Optional[Set[int]] = None,
) -> Dict[str, Any]:
    """把订阅候选中的夸克分享注册为跨盘复制任务。

    :param task: 归一化后的订阅任务（含 cross_copy_mode / cross_copy_sources / provider）
    :param cfg: 应用配置
    :param candidates: ranked_candidates
    :param last_episode: 本盘已有的最高集数（0 表示本盘还没有任何集数）。
        大于 0 且分享是整季文件夹时，按集数只挑缺的、并把文件铺平到目标目录，
        避免把已有的集数再下载一遍、也避免目标里多出一层分享文件夹名。
    :param existing_episodes: 目标目录实际落盘的集集合（更准的判缺口径）。
        传了就按集合判「已存在」，能识别中间缺集；不传退回 last_episode。
    :return: {"registered": [...job_id], "skipped": 原因列表, "logs": [(message, level), ...]}

    纯同步函数（供 asyncio.to_thread 调用）；日志消息通过 logs 返回，
    由调用方在事件循环里写入订阅日志。
    """
    logs: List[Tuple[str, str]] = []

    mode = str(task.get("cross_copy_mode", "off") or "off")
    sources = list(task.get("cross_copy_sources", []) or [])
    if mode == "off" or "quark" not in sources:
        return {"registered": [], "skipped": ["补源未开启"], "logs": logs}

    target_provider = str(task.get("provider", "115") or "115").strip()
    # 订阅日志会直接展示给用户，用中文名而不是内部代号（否则会看到 tianyi 这种）
    target_label = _provider_label(target_provider, default=target_provider)
    if target_provider == "quark":
        return {"registered": [], "skipped": ["任务网盘即夸克，无需补源"], "logs": logs}

    quark_provider = _get_provider_or_none("quark")
    target = _get_provider_or_none(target_provider)
    if quark_provider is None or target is None:
        return {"registered": [], "skipped": ["夸克或目标网盘未注册"], "logs": logs}
    if not getattr(target, "supports_upload", False):
        return {"registered": [], "skipped": [f"{getattr(target, 'label', target_provider)} 暂不支持上传"], "logs": logs}

    cookie_quark = str(cfg.get("cookie_quark", "") or "").strip()
    if not cookie_quark:
        return {"registered": [], "skipped": ["夸克 Cookie 未配置"], "logs": logs}

    picked = _pick_share_candidates(candidates, MAX_REGISTERED_PER_RUN)
    if not picked:
        return {"registered": [], "skipped": ["候选中没有夸克分享"], "logs": logs}

    task_name = str(task.get("name", "") or task.get("title", "") or "").strip()
    staging_rel_path = _staging_relative_path(task_name)
    registered: List[int] = []
    skipped: List[str] = []
    claimed_episodes: set = set()
    is_tv = str(task.get("media_type", "") or "").strip().lower() == "tv"

    # 转存之前先决定「只搬哪一个」。以前是 picked 里的候选逐个「先转存、再筛」：
    # 新剧首轮（本盘一集都没有）连筛集这一步都会被跳过，于是三个分享各整包转存
    # 一份进夸克中转，目标盘跟着复制三遍。现在剧集先只读扫一遍分享，按能补多少
    # 缺集择优；电影没有「集」的概念，按候选顺序只搬第一个，成功即止。
    plan: List[Dict[str, Any]] = []
    # 只读评估要递归列一遍分享目录（最多 3 个候选）。所以先排除两种「现在处理也
    # 没意义」的候选：① 这个分享已经有补源任务在下载/上传（一轮补源可能跑几小时，
    # 期间每轮订阅都会把同样的目录重扫一遍）；② 刚失败过还在冷却窗口内。
    ready_candidates: List[Dict[str, Any]] = []
    for candidate in picked:
        wait_reason = candidate_wait_reason(task_name, candidate)
        if wait_reason:
            skipped.append(wait_reason)
            continue
        ready_candidates.append(candidate)
    if not ready_candidates:
        logs.append(
            ("跨盘补源：候选分享都还在补源或失败冷却中，本轮不重复扫描", "info")
        )
        return {"registered": [], "skipped": skipped, "logs": logs}
    if is_tv:
        evaluations = [
            _evaluate_share_candidate(
                quark_provider, cookie_quark, candidate, task, last_episode, existing_episodes
            )
            for candidate in ready_candidates
        ]
        plan = _choose_share_plan(evaluations)
        if not plan:
            # 一个能补的缺集都没算出来，两种原因必须分开：
            #   ① 都扫成功但本盘不缺 → 本轮不转存（正确，别白占配额）；
            #   ② 有分享扫不出来（层级太深 / 限流）→ 兜底整包试一个，
            #      否则「扫描失败」会被当成「没东西可补」，一集都补不上。
            fallback = next((item for item in evaluations if not item.get("scan_ok")), None)
            if fallback is None:
                # 扫得出来、但每一集本盘都有了。写一条日志明说「没缺集，未转存」，
                # 否则界面只剩「尚未命中」，看起来像是连候选都没找到。
                logs.append(("跨盘补源：候选里没有本盘缺的集，本轮未转存（未占用夸克空间）", "info"))
                return {
                    "registered": [],
                    "skipped": skipped + ["分享里没有本盘缺的集，本轮不转存"],
                    "logs": logs,
                }
            plan = [
                {
                    "candidate": fallback.get("candidate") or {},
                    "share_url": str(fallback.get("share_url", "") or ""),
                    "share_payload": fallback.get("share_payload") or {},
                    "mode": "whole",
                    "files": [],
                    "notes": list(fallback.get("notes") or []),
                }
            ]
    else:
        plan = [
            {
                "candidate": candidate,
                "share_url": _extract_share_url(candidate),
                "share_payload": {},
                "mode": "whole",
                "files": [],
                "notes": [],
            }
            for candidate in ready_candidates
        ]

    for item in plan:
        candidate = item.get("candidate") or {}
        share_url = str(item.get("share_url", "") or _extract_share_url(candidate))
        receive_code = _extract_receive_code(candidate)
        skipped.extend(item.get("notes") or [])
        # 同一轮里前几个分享已经补过的集，后面的分享不用再转存一份（省夸克配额）。
        if claimed_episodes:
            stage_existing_episodes = set(existing_episodes or set()) | set(claimed_episodes)
        else:
            stage_existing_episodes = existing_episodes
        try:
            staged = _stage_share_to_quark(
                quark_provider,
                cookie_quark,
                share_url,
                receive_code,
                staging_rel_path,
                task=task,
                last_episode=last_episode,
                existing_episodes=stage_existing_episodes,
                prescanned_files=item.get("files") if item.get("mode") == "episodes" else None,
                share_payload=item.get("share_payload") or None,
            )
        except Exception as exc:
            skipped.append(f"转存失败：{share_url[:40]}（{exc}）")
            logs.append((f"跨盘补源转存失败：{share_url[:60]}（{exc}）", "warn"))
            continue

        skipped.extend(staged.get("skipped", []) or [])
        folders: List[Dict[str, Any]] = list(staged.get("folders", []) or [])
        files: List[Dict[str, Any]] = list(staged.get("files", []) or [])
        if not folders and not files:
            if staged.get("episode_filtered"):
                # 分享里全是本盘已有的集：一集都没转存，也没有配额消耗
                logs.append(
                    (f"跨盘补源：该分享没有本盘缺的集，已跳过（未转存）：{share_url[:60]}", "info")
                )
            # 分享内容已经转存过，但中转目录里连对应条目都没匹配到（可能被清理了）
            continue
        if staged.get("episode_filtered"):
            logs.append(
                (
                    f"跨盘补源：该分享按缺失集只转存了 {len(files)} 个文件"
                    f"（{share_url[:60]}）",
                    "info",
                )
            )

        registered_here = 0
        folders_here = 0
        files_here = 0

        # 整季文件夹分享 + 本盘已有进度时，只挑缺的集并铺平到目标目录：
        # 既不会把已有的 E01~E41 再下一遍，也不会在 Season 目录下多出一层
        # 「某剧 4K 全季」这种分享文件夹名。本盘一集都没有时仍整目录复制
        # （一个任务复制整个文件夹，比逐集注册更快）。
        # 散文件（分享里直接躺着的 E43/E44）也走同一套按集筛选：以前只筛文件夹、
        # 散文件无脑全注册，本盘已有的集照样会被再下一遍。
        register_items: List[Tuple[Dict[str, Any], bool]] = []
        has_local_progress = int(last_episode or 0) > 0 or bool(existing_episodes)
        tv_episode_filter = (
            has_local_progress
            and str(task.get("media_type", "") or "").strip().lower() == "tv"
        )

        def _claim_missing(missing: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            """同一轮里多个分享常重复提供同一集（两个「全季」包都含 E43/E44）。

            候选取前 3 个分享，先到先得：排行榜靠前的分享优先，同一轮不重复注册。
            """
            deduped: List[Dict[str, Any]] = []
            for file_item in missing:
                episode_no = int(file_item.get("episode", 0) or 0)
                if episode_no in claimed_episodes:
                    skipped.append(
                        f"本轮其它分享已补过第 {episode_no} 集，跳过：{file_item.get('name')}"
                    )
                    continue
                claimed_episodes.add(episode_no)
                deduped.append(file_item)
            return deduped

        for folder in folders:
            folder_name = str(folder.get("name", "") or "").strip()
            if tv_episode_filter:
                expanded = _expand_staged_folder_media_files(
                    quark_provider,
                    cookie_quark,
                    str(folder.get("id", "") or ""),
                )
                missing, why = _select_missing_episode_files(
                    task, expanded, folder_name, last_episode, existing_episodes
                )
                skipped.extend(why)
                missing = _claim_missing(missing)
                if not missing:
                    skipped.append(f"分享文件夹「{folder_name}」里没有本盘缺的集，跳过")
                    continue
                for file_item in missing:
                    register_items.append(
                        (
                            {
                                **file_item,
                                "staging_rel": f"{folder_name}/{file_item.get('rel_path', '')}".strip("/"),
                            },
                            False,
                        )
                    )
                continue
            register_items.append((folder, True))

        if tv_episode_filter and files:
            missing_files, why = _select_missing_episode_files(
                task, files, "", last_episode, existing_episodes
            )
            skipped.extend(why)
            missing_files = _claim_missing(missing_files)
            register_items.extend((item, False) for item in missing_files)
        else:
            register_items.extend((item, False) for item in files)

        for item, is_folder in register_items:
            item_name = str(item.get("name", "") or "").strip()
            item_id = str(item.get("id", "") or "").strip()
            # already_staged = 这个条目是从中转目录复用的（本轮没有真转存）。
            # 那种情况下中转里只可能有这一份文件，查重就不能再绑分享链接：
            # 同一资源的不同分享链接会各自查不到、各建一个任务指向同一份文件，
            # 目标盘就重复了。
            reused = bool(staged.get("already_staged"))
            if find_active_cross_copy_job(
                task_name, share_url, source_file_id=item_id, any_share=reused
            ):
                skipped.append(f"已在补源队列中，跳过：{item_name}")
                continue
            # 「中转目录里已经有文件」这条分支会走到这里：如果上次其实已经复制成功，
            # 再注册一次会往目标目录塞第二份，所以按已完成/已取消再挡一道。
            if reused and find_processed_cross_copy_job(
                task_name, share_url, source_file_id=item_id, any_share=True
            ):
                skipped.append(f"以前已补过，跳过：{item_name}")
                continue
            source_rel = str(item.get("staging_rel") or "").strip().strip("/") or item_name
            job_id = ccj.create_cross_copy_job(
                title=str(
                    task.get("title", "")
                    or task.get("name", "")
                    or item_name
                    or "跨盘复制"
                ),
                source_provider="quark",
                target_provider=target_provider,
                source_file_id=item_id,
                target_savepath=_cross_copy_target_savepath(task, candidate),
                source_path="/" + "/".join(
                    part
                    for part in (
                        str(staging_rel_path or "").strip().strip("/"),
                        source_rel,
                    )
                    if part
                ),
                filename=item_name,
                file_size=int(item.get("size", 0) or 0) if not is_folder else 0,
                source_mode="save_first",
                source_share_url=share_url,
                origin=origin,
                origin_ref=task_name,
                source_is_dir=is_folder,
            )
            ccj.submit_cross_copy_job(job_id)
            registered.append(job_id)
            registered_here += 1
            if is_folder:
                folders_here += 1
            else:
                files_here += 1
            logs.append(
                (
                    f"跨盘补源已入队：夸克{'文件夹' if is_folder else ''} → {target_label}"
                    f"（{item_name or share_url[:40]}，任务 #{job_id}）",
                    # 「命中并已入队」是补源这条链上最该被看见的结论，用 success 让它在
                    # 日志里显绿；以前是 info，和「搜索中/等待中」一个颜色，读者要逐行
                    # 找才知道到底补没补上。
                    "success",
                )
            )

        if registered_here:
            logs.append(
                (
                    f"本次从该分享注册了 {registered_here} 个任务"
                    f"（{folders_here} 个文件夹、{files_here} 个文件）：{share_url[:60]}",
                    "success",
                )
            )
        # 电影/其它只搬第一个候选：成功注册就不再试后面的分享，避免同一部电影
        # 落三份；失败（没注册出任务）才继续下一个。
        if not is_tv and registered_here:
            break

    if registered:
        logs.append((f"跨盘补源：本轮注册 {len(registered)} 个复制任务（目标 {target_label}）", "success"))
    return {"registered": registered, "skipped": skipped, "logs": logs}
