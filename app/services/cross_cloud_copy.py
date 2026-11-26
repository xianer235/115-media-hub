"""跨盘复制引擎（P0-B 首发：夸克 → 115 / 阿里）。

单文件管道（provider 无关，详见设计文档 §4.4）：：

    源取直链（resolve_download_url / resolve_download_info）
      → 流式下载 + 同步计算 SHA1/MD5（一遍读，双哈希）
      → 双通道：小文件（≤64MB）进内存；大文件进临时文件（temp_dir，可指向机械硬盘）
      → 目标秒传（upload_file 内部处理：命中零流量）
      → 未命中分片上传
      → 清理临时文件 → 返回结果

并行分段下载（0.15.1）：
    临时文件通道下，同任务内多个 16MB 段并发拉取（段队列 + worker 线程，
    ``os.pwrite`` 按段偏移落盘，无共享文件指针）；段内不算哈希，全部落盘后
    按 0..N-1 顺序整文件读一遍算 md5/sha1——同一份字节的同样计算，与切分
    边界无关，结果与整文件流逐字节一致。内存通道 / 大小未知保持串行
    （并发写 BytesIO 要加锁，收益抵不过线程开销）。worker 数由
    ``CROSS_COPY_DOWNLOAD_PARALLEL`` 控制（默认 3，1~8）。

任务断点续传（0.15.1，引擎侧接缝）：
    ``copy_file_across_clouds`` 接受上层构造的 ``resume`` 状态并就地更新：
    上次中断在下载中 → 从「连续前缀」断点续下剩余段；上次已算完哈希 →
    直接用本地临时文件做只读 sink，完全跳过下载。失败 / 取消不删临时文件
    （下载进度与上传会话都有继承价值），成功照旧删。

关键取舍：
    - 秒传与「纯流式边下边传」根本冲突（秒传必须先知道完整 SHA1），
      因此采用「先落地缓冲、再秒传探测、未命中才分片上传」的有界管道；
    - 下载一遍的同时算哈希——秒传命中的文件零上传流量，未命中的也不浪费这一遍读；
    - 直链短时效（夸克分钟级）：下载失败自动换链重试（下载侧）；
    - 上传侧断点续传依赖各 provider（当前三家均为 False，取消即清理）。

零流量快路径（P1）：
    115 / 阿里云盘的文件对象本身就带 SHA1（115 的 ``sha1``、阿里的 ``content_hash``），
    源端是这两家时只需读一次元信息就能拿到 ``sha1 + size``，交给目标端做秒传探测。
    此时引擎不再提前下载，而是用惰性 sink（``_LazyDownloadSink``）把下载推迟到
    「第一次真正读数据」：秒传命中 → read 永不发生 → 一个字节都不下。

哈希备忘录（media_hash_cache）：
    夸克这类源拿不到哈希，只能下载一遍算；算出来的 ``sha1 + size`` 会沉淀进
    SQLite（见 ``media_hash_cache.py``），下一次复制同一个文件（哪怕目标是另一个
    目录）直接命中，不必再下一遍。备忘录里的哈希若与源文件实际内容不符，
    引擎会清掉缓存、改走「下载重新算哈希」的路径重试一次，而不是把复制判死。

provider 能力依赖：
    - 源：resolve_download_url / resolve_download_info（三家均已实现）
    - 源（可选）：get_file_hash → ``{"sha1", "size", "name"}``（115/阿里已实现）
    - 目标：supports_upload + upload_file（115/夸克/阿里均已实现）
"""
import hashlib
import inspect
import io
import logging
import os
import re
import queue
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

import requests

from ..core import normalize_http_url
from ..providers.base import CloudProvider, UploadError
from . import media_hash_cache
from .local_storage import ensure_free_space, resolve_cross_copy_temp_dir

logger = logging.getLogger(__name__)

# 小文件走内存通道的阈值（64MB）
MEMORY_CHANNEL_THRESHOLD_BYTES = 64 * 1024 * 1024
# 下载分块与超时
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_CONNECT_TIMEOUT = 10
DOWNLOAD_READ_TIMEOUT = 120
# 分段下载：夸克等网盘对「整文件 GET」限速（真机实测非会员约 100KB/s），
# 但对 Range 分段请求按正常速度返回（同账号同文件实测 4~6MB/s）。
# 知道文件大小时按段请求，既绕开限速，断流也只补当前段。
DOWNLOAD_SEGMENT_BYTES = max(
    1, min(128, int(os.environ.get("CROSS_COPY_DOWNLOAD_SEGMENT_MB", "16") or 16))
) * 1024 * 1024


def _clamp_parallel_workers(raw: Any) -> int:
    """把配置值收敛到 1~8（默认 3，非法值回落 3）。

    1 = 完全串行（现状），供对照测试与出问题时回退；>8 没有带宽收益，
    反而把连接池和磁盘队列打满。
    """
    try:
        workers = int(str(raw).strip())
    except (TypeError, ValueError):
        return 3
    return workers if 1 <= workers <= 8 else 3


# 同任务内并行下载的 worker 线程数（CROSS_COPY_DOWNLOAD_PARALLEL）。
# 只作用于临时文件通道：内存通道并发写要加锁、大小未知时无法分段，
# 两者保持串行（见 _download_to_sink）。
DOWNLOAD_PARALLEL_WORKERS = _clamp_parallel_workers(
    os.environ.get("CROSS_COPY_DOWNLOAD_PARALLEL", "3") or 3
)
# 下载失败（直链过期/断流）换链重试
DOWNLOAD_MAX_RETRIES = 3
DOWNLOAD_RETRY_BASE_SECONDS = 1.5
# 孤儿临时文件默认清理阈值（小时）
ORPHAN_TEMP_MAX_AGE_HOURS = 24
TEMP_FILE_PREFIX = "xcopy-"


class CrossCloudCopyError(RuntimeError):
    """跨盘复制失败（message 为面向用户的文案）。

    retriable=True 表示瞬时故障（限流/网络/直链过期），值得重试。
    """

    def __init__(self, message: str, *, retriable: bool = False):
        super().__init__(str(message))
        self.retriable = bool(retriable)


class CrossCloudCopyCancelled(CrossCloudCopyError):
    """复制被取消（检查点命中）。"""

    def __init__(self, message: str = "复制已取消"):
        super().__init__(str(message or "复制已取消"))


class CrossCloudCopyPaused(CrossCloudCopyError):
    """复制被暂停（检查点命中）。

    与「取消」同走检查点链路，但收口不同：暂停保留断点（临时文件 + resume 会话），
    继续时从断点续传；取消同样保留断点，只是语义上用户选择终止。二者在引擎层都
    通过 ``cancel_check`` 回调在命中时抛异常来中止当前 chunk/分片——本异常由
    任务层传入的闭包在「暂停」时抛出，穿透引擎 / provider / 分片重试的检查点。
    """

    def __init__(self, message: str = "复制已暂停"):
        super().__init__(str(message or "复制已暂停"))


class _SourceHashMismatch(CrossCloudCopyError):
    """惰性下载校验失败：已知哈希与源文件实际内容对不上。

    典型来源是「哈希备忘录里的 sha1 已经过期/记错」——网盘端文件被替换但 file_id
    没变。调用方据此清掉缓存并改走「下载重新算哈希」的路径重试一次，
    而不是把复制直接判失败（见 copy_file_across_clouds 的自愈逻辑）。
    """

    def __init__(self, *, expected_sha1: str = "", actual_sha1: str = ""):
        super().__init__("源文件已变更，请重试")
        self.expected_sha1 = str(expected_sha1 or "")
        self.actual_sha1 = str(actual_sha1 or "")


class CopyFileResult:
    """单文件跨盘复制结果。"""

    __slots__ = (
        "status",
        "source_provider",
        "target_provider",
        "file_id",
        "pick_code",
        "name",
        "size",
        "sha1",
        "message",
        "elapsed_ms",
    )

    def __init__(
        self,
        *,
        status: str,
        source_provider: str = "",
        target_provider: str = "",
        file_id: str = "",
        pick_code: str = "",
        name: str = "",
        size: int = 0,
        sha1: str = "",
        message: str = "",
        elapsed_ms: int = 0,
    ):
        self.status = str(status or "")
        self.source_provider = str(source_provider or "")
        self.target_provider = str(target_provider or "")
        self.file_id = str(file_id or "")
        self.pick_code = str(pick_code or "")
        self.name = str(name or "")
        self.size = int(size or 0)
        self.sha1 = str(sha1 or "").upper()
        self.message = str(message or "")
        self.elapsed_ms = int(elapsed_ms or 0)

    @property
    def is_rapid(self) -> bool:
        return self.status == "rapid"

    def to_dict(self) -> Dict[str, Any]:
        return {key: getattr(self, key) for key in self.__slots__}

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"<CopyFileResult {self.status} {self.source_provider}->{self.target_provider} "
            f"name={self.name!r} size={self.size}>"
        )


def _report_progress(progress_cb, sent: int, total: int, phase: str) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(sent, total, phase)
    except Exception:
        pass


def _check_cancelled(cancel_check) -> None:
    if cancel_check is not None and cancel_check():
        raise CrossCloudCopyCancelled()


# ============================================================
# 源端哈希探测（零流量秒传前置条件）
#
# 秒传探测只需要 ``sha1 + size``。115 / 阿里云盘的文件元信息里本来就带 SHA1，
# 源端是这两家时读一次元信息即可，不必把整文件下载一遍再算。
# 拿不到（夸克、第三方中转、或接口没回哈希）就返回 {}，调用方回退原路径。
# ============================================================
SOURCE_HASH_CACHE_TTL_SECONDS = 10 * 60
SOURCE_HASH_CACHE_MAX_ROWS = 2000

_SHA1_PATTERN = re.compile(r"^[0-9A-F]{40}$")
# 进程内缓存：{(provider_name, cookie 摘要, file_id): {"value": {...}, "expires_at": 单调时钟}}
_source_hash_cache: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
_source_hash_cache_lock = threading.Lock()


def _normalize_sha1(value: Any) -> str:
    """统一成大写十六进制 SHA1；格式不对返回空串（宁可不走快路径，也不要传错哈希）。"""
    token = str(value or "").strip().upper()
    return token if _SHA1_PATTERN.match(token) else ""


def _source_hash_cache_key(provider: Any, cookie: str, file_id: str) -> Tuple[str, str, str]:
    """缓存键。cookie 只存摘要，避免把凭据明文留在内存字典里，也避免跨账号串味。"""
    cookie_digest = hashlib.sha1(str(cookie or "").encode("utf-8")).hexdigest()[:16]
    return (
        str(getattr(provider, "name", "") or ""),
        cookie_digest,
        str(file_id or "").strip(),
    )


def _read_cached_source_hash(key: Tuple[str, str, str]) -> Optional[Dict[str, Any]]:
    now = time.monotonic()
    with _source_hash_cache_lock:
        row = _source_hash_cache.get(key)
        if not row:
            return None
        if float(row.get("expires_at", 0.0) or 0.0) <= now:
            _source_hash_cache.pop(key, None)
            return None
        value = row.get("value") or {}
        return dict(value) if isinstance(value, dict) else None


def _write_cached_source_hash(key: Tuple[str, str, str], value: Dict[str, Any]) -> None:
    now = time.monotonic()
    with _source_hash_cache_lock:
        if len(_source_hash_cache) >= SOURCE_HASH_CACHE_MAX_ROWS:
            for stale_key in [
                k for k, row in _source_hash_cache.items()
                if float(row.get("expires_at", 0.0) or 0.0) <= now
            ]:
                _source_hash_cache.pop(stale_key, None)
            overflow = len(_source_hash_cache) - SOURCE_HASH_CACHE_MAX_ROWS + 1
            if overflow > 0:
                # 仍然超限：按过期时间淘汰最早失效的若干行
                oldest = sorted(
                    _source_hash_cache,
                    key=lambda k: float(_source_hash_cache[k].get("expires_at", 0.0) or 0.0),
                )
                for stale_key in oldest[:overflow]:
                    _source_hash_cache.pop(stale_key, None)
        _source_hash_cache[key] = {
            "value": dict(value),
            "expires_at": now + SOURCE_HASH_CACHE_TTL_SECONDS,
        }


def clear_source_hash_cache() -> int:
    """清空源哈希缓存（配置变更 / 测试用），返回清掉的条数。"""
    with _source_hash_cache_lock:
        count = len(_source_hash_cache)
        _source_hash_cache.clear()
    return count


def _invalidate_source_hash(provider: Any, cookie: str, file_id: str) -> None:
    """哈希校验失败时丢掉缓存，避免同一份过期元信息反复把复制打失败。"""
    key = _source_hash_cache_key(provider, cookie, file_id)
    with _source_hash_cache_lock:
        _source_hash_cache.pop(key, None)


def resolve_source_hash(
    provider: Any, cookie: str, file_id: str, size: int = -1
) -> Dict[str, Any]:
    """按能力探测源端能否直接给出 ``sha1 + size``（不下载文件）。

    两级缓存，按开销从低到高依次尝试：
        1. 进程内缓存（10 分钟，键含 cookie 摘要）——挡同一任务内的重复请求；
        2. 持久化哈希备忘录 ``media_hash_cache``（30 天，跨任务复用）——
           夸克这类没有哈希能力的源，只要以前下载算过一次，这里就能直接命中；
        3. 最后才走 ``provider.get_file_hash(cookie, file_id)``（115/阿里已实现）。

    :param size: 调用方知道的文件大小；> 0 时才查备忘录（查表必须校验大小，
        大小不符说明文件被换过，旧哈希作废）。<= 0 表示大小未知，跳过备忘录。

    返回 ``{"sha1": 大写SHA1, "size": int, "name": str, "md5": str, "origin": str}``；
    都没有 → ``{}``，调用方回退「下载一遍算哈希」。
    """
    token = str(file_id or "").strip()
    if not token:
        return {}
    provider_name = str(getattr(provider, "name", "") or "")
    key = _source_hash_cache_key(provider, cookie, token)
    cached = _read_cached_source_hash(key)
    if cached is not None:
        return cached
    # 备忘录：数据库故障已在 media_hash_cache 内部吞掉；这里再兜一层，
    # 防止将来缓存模块改动把异常漏进复制主流程。
    try:
        with_size = int(size)
    except (TypeError, ValueError):
        with_size = -1
    if with_size > 0 and provider_name:
        try:
            remembered = media_hash_cache.lookup_file_hash(provider_name, token, with_size)
        except Exception as exc:
            logger.warning("媒体哈希缓存查询异常（已忽略）：%s", exc)
            remembered = ""
        if remembered:
            logger.info(
                "cross-cloud source hash hit media cache: %s file_id=%s size=%s sha1=%s",
                provider_name,
                token,
                with_size,
                remembered[:12],
            )
            return {
                "sha1": remembered,
                "size": with_size,
                "name": "",
                "md5": "",
                "origin": "cache",
            }
    getter = getattr(provider, "get_file_hash", None)
    if not callable(getter):
        return {}
    try:
        info = getter(cookie, token)
    except Exception as exc:
        logger.info("cross-cloud source hash probe failed (%s): %s", token, exc)
        return {}
    if not isinstance(info, dict):
        return {}
    sha1 = _normalize_sha1(info.get("sha1", ""))
    try:
        info_size = int(info.get("size", 0) or 0)
    except (TypeError, ValueError):
        return {}
    if not sha1 or info_size <= 0:
        return {}
    record = {
        "sha1": sha1,
        "size": info_size,
        "name": str(info.get("name", "") or "").strip(),
        "md5": str(info.get("md5", "") or "").strip().lower(),
        "origin": "provider",
    }
    _write_cached_source_hash(key, record)
    logger.info(
        "cross-cloud source hash resolved: %s file_id=%s size=%s sha1=%s",
        provider_name,
        token,
        info_size,
        sha1[:12],
    )
    return dict(record)



def _resolve_source_download(source_provider: CloudProvider, source_cookie: str, source_file_id: str) -> Dict[str, Any]:
    """取源文件下载直链。优先 resolve_download_info（带元信息），回退 resolve_download_url。"""
    info_getter = getattr(source_provider, "resolve_download_info", None)
    if callable(info_getter):
        info = info_getter(source_cookie, source_file_id)
        if isinstance(info, dict) and str(info.get("url", "") or "").strip():
            return info
    url = source_provider.resolve_download_url(source_cookie, source_file_id)
    normalized_url = str(url or "").strip()
    if not normalized_url:
        raise CrossCloudCopyError("源网盘未返回下载地址", retriable=True)
    return {"url": normalized_url}


# 各网盘 CDN 对 Referer 的校验不同：用错会被 403（夸克尤其明显）。
_REFERER_BY_PROVIDER = {
    "quark": "https://pan.quark.cn/",
    "115": "https://115.com/",
    "aliyun": "https://www.alipan.com/",
}
_DEFAULT_DOWNLOAD_REFERER = "https://pan.quark.cn/"


def _download_headers(
    source_cookie: str,
    provider_name: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """下载请求头。按源网盘选 Referer，provider 返回的 headers 可覆盖任意字段。

    夸克 CDN 直链不需要 Cookie，但带上无害；115/阿里作源需要。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
        ),
        "Referer": _REFERER_BY_PROVIDER.get(
            str(provider_name or "").strip().lower(), _DEFAULT_DOWNLOAD_REFERER
        ),
        "Cookie": str(source_cookie or "").strip(),
    }
    if isinstance(extra, dict):
        for key, value in extra.items():
            if isinstance(key, str) and isinstance(value, str) and key.strip():
                headers[key] = value
    return headers


def _info_filename(info: Dict[str, Any]) -> str:
    """取源文件名的兼容读法：115 provider 返回 name，阿里/夸克返回 file_name。"""
    if not isinstance(info, dict):
        return ""
    for key in ("file_name", "name"):
        value = str(info.get(key, "") or "").strip()
        if value:
            return value
    return ""


def resolve_temp_dir(cfg: Optional[Dict[str, Any]], *, create: bool = False) -> str:
    """从应用配置解析跨盘复制临时目录（存储位置 + 子目录）。

    调用方（任务/订阅）传入 get_config() 即可；cfg=None 表示未接入配置，
    返回空串由调用方使用系统临时目录。
    """
    if cfg is None:
        return ""
    try:
        return resolve_cross_copy_temp_dir(cfg, create=create)
    except Exception as exc:
        logger.warning("resolve cross-copy temp dir failed (%s), fallback to default", exc)
        return ""


def _precheck_disk_space(temp_dir: str, size: int) -> None:
    """大文件落盘前预检空间，不足直接失败（不下到一半磁盘满）。"""
    if size < 0 or size <= MEMORY_CHANNEL_THRESHOLD_BYTES:
        return
    check_dir = str(temp_dir or "").strip() or tempfile.gettempdir()
    try:
        ensure_free_space(check_dir, size)
    except ValueError as exc:
        raise CrossCloudCopyError(str(exc)) from exc
    except Exception as exc:
        # 探测失败不阻塞复制（如特殊文件系统），仅记录
        logger.info("disk space precheck skipped for %s: %s", check_dir, exc)


def _open_sink(size: int, temp_dir: str):
    """双通道：小文件内存流，大文件临时文件。

    返回 (sink, is_temp_file, temp_path)。调用方负责 finally 清理临时文件。
    """
    if 0 <= int(size) <= MEMORY_CHANNEL_THRESHOLD_BYTES:
        return io.BytesIO(), False, ""
    safe_dir = str(temp_dir or "").strip()
    if safe_dir:
        try:
            os.makedirs(safe_dir, exist_ok=True)
        except Exception as exc:
            raise CrossCloudCopyError(f"临时目录不可用：{safe_dir}（{exc}）") from exc
    fd, path = tempfile.mkstemp(prefix=TEMP_FILE_PREFIX, suffix=".part", dir=safe_dir or None)
    return os.fdopen(fd, "w+b"), True, path


def _reset_sink(sink, keep_prefix_bytes: int = 0) -> None:
    """重试前重置写入位置（内存流与文件对象均支持）。

    keep_prefix_bytes > 0（续传场景）：只把写入口移回断点，已落盘的连续前缀
    必须保留——truncate 会把它一起毁掉；前缀之外的残余字节无所谓，重下时覆盖。
    """
    try:
        sink.seek(int(keep_prefix_bytes))
        if keep_prefix_bytes <= 0:
            sink.truncate(0)
    except Exception:
        pass


def _consume_download_response(
    response,
    sink,
    *,
    md5_hasher,
    sha1_hasher,
    sent: int,
    total: int,
    progress_cb,
    cancel_check,
    limit: int = 0,
) -> int:
    """把一个响应体写进 sink 并同步喂哈希，返回累计字节数。limit>0 时读够即停。"""
    received = 0
    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
        if not chunk:
            continue
        sink.write(chunk)
        md5_hasher.update(chunk)
        sha1_hasher.update(chunk)
        received += len(chunk)
        sent += len(chunk)
        _check_cancelled(cancel_check)
        _report_progress(progress_cb, sent, total, "download")
        if limit and received >= limit:
            break
    return sent


def _sink_file_descriptor(sink) -> Optional[int]:
    """取 sink 的底层文件描述符；内存流（BytesIO）没有 fd，返回 None。

    并行分段下载要求「按段偏移写盘」（os.pwrite，无共享文件指针），只有真正的
    临时文件通道做得到；内存通道并发写要额外加锁，收益抵不过线程开销，
    因此保持串行（见 _download_to_sink 的通道判定）。
    """
    fileno_getter = getattr(sink, "fileno", None)
    if not callable(fileno_getter):
        return None
    try:
        fd = fileno_getter()
    except Exception:
        return None
    return fd if isinstance(fd, int) else None


class _ParallelProgress:
    """跨 worker 的「已落盘字节」计数（含续传前缀，绝对偏移）。

    进度回调也在锁内调用：多个 worker 并发上报时，UI 侧收到的 sent 仍然是
    单调汇总值，不会出现乱序回退。
    """

    def __init__(self, written: int, total: int, progress_cb):
        self._lock = threading.Lock()
        self._written = int(written)
        self._total = int(total)
        self._progress_cb = progress_cb

    def add(self, count: int) -> None:
        with self._lock:
            self._written += int(count)
            _report_progress(self._progress_cb, self._written, self._total, "download")

    def snapshot(self) -> int:
        with self._lock:
            return self._written


class _SegmentLedger:
    """记录已完成的段，推算出「连续前缀」字节数。

    并行落盘是乱序的：第 3 段落了盘不代表第 1、2 段也在盘上。续传状态里的
    downloaded_bytes 必须是连续前缀——否则下次从断点续下会跳过空洞，产出
    哈希错误的文件并传上网盘。这里按段完成记账，前缀只沿连续段推进，
    宁可少报（下次多下几段）也绝不多报。
    """

    def __init__(self, base_offset: int, segment_bytes: int, total: int):
        self._base = int(base_offset)
        self._segment = int(segment_bytes)
        self._total = int(total)
        self._done = set()
        self._prefix = self._base
        self._lock = threading.Lock()

    def mark_done(self, segment_start: int) -> int:
        """标记一段完成，返回推进后的连续前缀（绝对字节数）。"""
        with self._lock:
            self._done.add(int(segment_start))
            while self._prefix < self._total and self._prefix in self._done:
                self._prefix = min(self._prefix + self._segment, self._total)
            return self._prefix


def _hash_local_file(fd: int, total: int, *, cancel_check=None) -> Tuple[str, str]:
    """把 fd 指向的本地文件按 0..N-1 顺序整读一遍，算 md5/sha1。

    并行段内不算哈希：同一份字节的同样计算，与切分边界无关（流式哈希与
    分块拼接再哈希结果相同），这是哈希的基本性质。读的是本地盘，相对网络
    下载是可接受成本；读盘期间同样响应取消（每块检查）。
    """
    md5_hasher = hashlib.md5()
    sha1_hasher = hashlib.sha1()
    hashed = 0
    while hashed < total:
        _check_cancelled(cancel_check)
        chunk = os.pread(fd, DOWNLOAD_CHUNK_SIZE, hashed)
        if not chunk:
            raise CrossCloudCopyError(
                f"临时文件读取不完整（{hashed}/{total} 字节）", retriable=True
            )
        md5_hasher.update(chunk)
        sha1_hasher.update(chunk)
        hashed += len(chunk)
    return md5_hasher.hexdigest(), sha1_hasher.hexdigest().upper()


def _hash_file_prefix(sink, length: int, md5_hasher, sha1_hasher, *, cancel_check) -> None:
    """把 sink 前 length 字节喂进哈希器（续传的串行分支专用）。

    串行分支是「边下边算」：续传时前缀上次已落盘、这次不会再流过 worker，
    必须先读一遍补进哈希，否则最终哈希只覆盖后半段。
    """
    sink.seek(0)
    remaining = int(length)
    while remaining > 0:
        _check_cancelled(cancel_check)
        chunk = sink.read(min(DOWNLOAD_CHUNK_SIZE, remaining))
        if not chunk:
            raise CrossCloudCopyError(
                f"续传前缀读取不完整（{length - remaining}/{length} 字节）", retriable=True
            )
        md5_hasher.update(chunk)
        sha1_hasher.update(chunk)
        remaining -= len(chunk)
    sink.seek(length)


def _fetch_segment_to_fd(
    *,
    url: str,
    headers: Dict[str, str],
    fd: int,
    start: int,
    end: int,
    progress: "_ParallelProgress",
    cancel_check,
    stop_event: "threading.Event",
) -> Tuple[int, bool, bool]:
    """把 [start, end] 这一段按偏移写进 fd，返回 (收到字节, 是否整文件响应, 是否被联动停止)。

    段内独立重试 DOWNLOAD_MAX_RETRIES 次（退避基数沿用外层）——断流只补当前段，
    不换链（换链是外层重试循环的事）。stop_event 被其他 worker 的失败置位时，
    在下一个检查点丢弃半截数据退出：未完成的段不计入连续前缀，重下时覆盖。
    """
    expected = end - start + 1
    last_error: Optional[Exception] = None
    for seg_attempt in range(1, DOWNLOAD_MAX_RETRIES + 1):
        if stop_event.is_set():
            return 0, False, True
        segment_headers = dict(headers)
        segment_headers["Range"] = f"bytes={start}-{end}"
        response = None
        try:
            response = requests.get(
                url,
                stream=True,
                headers=segment_headers,
                timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
            )
            range_ignored = int(getattr(response, "status_code", 0) or 0) == 200
            if range_ignored and start > 0:
                # 200 响应体是整个文件：断点续传时把它追加到前缀后面只会得到脏文件
                raise CrossCloudCopyError(
                    "下载服务不支持分段续传（HTTP 200）", retriable=True
                )
            response.raise_for_status()
            received = 0
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue
                if stop_event.is_set():
                    return received, range_ignored, True
                os.pwrite(fd, chunk, start + received)
                received += len(chunk)
                progress.add(len(chunk))
                _check_cancelled(cancel_check)
            if not range_ignored and received != expected:
                raise CrossCloudCopyError(
                    f"分段下载不完整（{received}/{expected} 字节）", retriable=True
                )
            return received, range_ignored, False
        except CrossCloudCopyCancelled:
            raise
        except Exception as exc:
            last_error = exc
            if seg_attempt >= DOWNLOAD_MAX_RETRIES:
                raise
            logger.info(
                "cross-cloud segment %s-%s attempt %s/%s failed (%s)",
                start,
                end,
                seg_attempt,
                DOWNLOAD_MAX_RETRIES,
                exc,
            )
            time.sleep(DOWNLOAD_RETRY_BASE_SECONDS * seg_attempt)
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
    raise CrossCloudCopyError(f"分段下载失败：{last_error}", retriable=True)


def _download_segments_parallel(
    *,
    url: str,
    headers: Dict[str, str],
    fd: int,
    total: int,
    start_offset: int,
    workers: int,
    progress_cb,
    cancel_check,
    on_segment_done: Optional[Callable[[int], None]],
) -> int:
    """并行分段下载（仅临时文件通道）：段队列 + worker 线程 + os.pwrite 按偏移写盘。

    - 首段由驱动线程先单独取：服务端若不认 Range（回 200），这一遍响应体就是
      整个文件，按单流写完即算哈希，不起其余 worker——否则并发段会各自收到
      一份完整响应，互相踩写；
    - 其余段进队列，worker 竞争消费；每段独立请求、段内独立重试；
    - 任一 worker 失败 / 取消：置停止事件，其余 worker 在下一个检查点收尾，
      本函数抛错，由外层既有重试循环换链重来；
    - 返回落盘的绝对字节数（含 start_offset 前缀）。
    """
    segment_bytes = DOWNLOAD_SEGMENT_BYTES
    progress = _ParallelProgress(start_offset, total, progress_cb)
    ledger = _SegmentLedger(start_offset, segment_bytes, total)
    stop_event = threading.Event()
    failures = []  # 线程内 append 原子，join 后统一汇总

    # 预分配：稀疏文件先撑到目标大小，磁盘不足尽早暴露，段按偏移写
    # （续传分支不 truncate：前缀已在盘上，且文件尾部可能有上次的残余字节）
    if start_offset <= 0:
        try:
            os.ftruncate(fd, total)
        except OSError as exc:
            logger.info("cross-cloud temp file preallocate skipped: %s", exc)

    # ---- 首段：确认服务端认 Range（206）再并发其余段 ----
    lead_start = start_offset
    lead_end = min(lead_start + segment_bytes, total) - 1
    lead_received, range_ignored, lead_stopped = _fetch_segment_to_fd(
        url=url,
        headers=headers,
        fd=fd,
        start=lead_start,
        end=lead_end,
        progress=progress,
        cancel_check=cancel_check,
        stop_event=stop_event,
    )
    if range_ignored:
        # 服务端不认 Range：这一遍响应体就是整个文件，已从 start_offset 顺序写盘
        if lead_received != total:
            raise CrossCloudCopyError(
                f"下载不完整（{lead_received}/{total} 字节）", retriable=True
            )
        if on_segment_done is not None:
            try:
                on_segment_done(total)
            except Exception:
                pass
        return progress.snapshot()
    if lead_stopped or lead_received != lead_end - lead_start + 1:
        raise CrossCloudCopyError(
            f"分段下载不完整（{lead_received}/{lead_end - lead_start + 1} 字节）",
            retriable=True,
        )
    if on_segment_done is not None:
        try:
            on_segment_done(ledger.mark_done(lead_start))
        except Exception:
            pass
    _check_cancelled(cancel_check)

    # ---- 其余段进队列，workers 个线程竞争消费（驱动线程已下掉首段） ----
    segment_queue: "queue.Queue" = queue.Queue()
    seg_start = lead_start + segment_bytes
    while seg_start < total:
        segment_queue.put(seg_start)
        seg_start += segment_bytes

    def _worker() -> None:
        while not stop_event.is_set():
            try:
                segment_start = segment_queue.get_nowait()
            except queue.Empty:
                return
            try:
                _, _, stopped = _fetch_segment_to_fd(
                    url=url,
                    headers=headers,
                    fd=fd,
                    start=segment_start,
                    end=min(segment_start + segment_bytes, total) - 1,
                    progress=progress,
                    cancel_check=cancel_check,
                    stop_event=stop_event,
                )
            except BaseException as exc:  # noqa: BLE001 - 线程内异常必须带走，不能烂在线程里
                stop_event.set()
                failures.append(exc)
                return
            if stopped:
                # 被其他 worker 的失败联动停止：本段未完成，不计入连续前缀
                return
            done_prefix = ledger.mark_done(segment_start)
            if on_segment_done is not None:
                try:
                    on_segment_done(done_prefix)
                except Exception:
                    pass

    threads = []
    for index in range(max(1, workers) - 1):
        thread = threading.Thread(
            target=_worker, name=f"cross-copy-dl-{index}", daemon=True
        )
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()

    # 汇总失败：取消优先（用户意图大于网络错误），其余抛第一个
    for exc in failures:
        if isinstance(exc, CrossCloudCopyCancelled):
            raise exc
    if failures:
        raise failures[0]
    return progress.snapshot()


def _download_to_sink(
    *,
    source_provider: CloudProvider,
    source_cookie: str,
    source_file_id: str,
    sink,
    total: int,
    progress_cb=None,
    cancel_check=None,
    start_offset: int = 0,
    on_segment_done: Optional[Callable[[int], None]] = None,
) -> Dict[str, Any]:
    """流式下载源文件到 sink，同步计算 SHA1/MD5；直链失效自动换链重试。

    知道文件大小时按 Range 分段请求（绕开网盘对整文件流的限速，断流只补当前段）；
    大小未知时退回整文件流。服务端忽略 Range（返回 200）时自动降级。

    并行（0.15.1）：临时文件通道且剩余段数 >= 2 时，段并发拉取、按偏移写盘，
    全部落盘后整文件算一遍哈希（与串行逐字节一致）；内存通道 / 大小未知 /
    PARALLEL=1 / 剩余不足 2 段保持串行。

    start_offset：断点续传——只请求 [start_offset, total) 范围的段，之前落盘的
    连续前缀由调用方保证有效（引擎只从连续前缀续传）。非 0 时必须按段边界对齐，
    否则抛错（错位说明续传状态已损坏，继续下只会产出脏文件）。
    on_segment_done：每完成一段时回调，参数为推进后的「连续前缀」绝对字节数
    （供上层写续传状态；串行/200 降级路径同样按段回调）。

    返回 {"size": 落盘字节数, "md5": ..., "sha1": ..., "downloaded_bytes": 同 size}
    （downloaded_bytes 含前缀，是「本次运行后盘上的有效总量」）。
    """
    # start_offset 由调用方保证按段边界对齐；这里做断言式校验，坏状态直接失败
    try:
        start_offset = int(start_offset or 0)
    except (TypeError, ValueError) as exc:
        raise CrossCloudCopyError(f"非法的续传起始偏移：{start_offset!r}") from exc
    if start_offset < 0:
        raise CrossCloudCopyError(f"非法的续传起始偏移：{start_offset}")
    if start_offset > 0 and start_offset % DOWNLOAD_SEGMENT_BYTES != 0:
        raise CrossCloudCopyError(
            f"续传起始偏移未按分段边界对齐（{start_offset}，分段 {DOWNLOAD_SEGMENT_BYTES}）"
        )
    if start_offset > 0 and total <= 0:
        raise CrossCloudCopyError("文件大小未知时无法从断点续传")
    if total > 0 and start_offset >= total:
        if start_offset > total:
            raise CrossCloudCopyError(
                f"续传起始偏移 {start_offset} 超出文件大小 {total}"
            )
        # 断点已到末尾（状态里没记哈希的自愈场景）：本地就是完整文件，算一遍哈希
        fd = _sink_file_descriptor(sink)
        if fd is None:
            raise CrossCloudCopyError("续传数据不在临时文件中，无法校验")
        _check_cancelled(cancel_check)
        md5_hex, sha1_hex = _hash_local_file(fd, total, cancel_check=cancel_check)
        return {"size": total, "md5": md5_hex, "sha1": sha1_hex, "downloaded_bytes": total}

    last_error: Optional[Exception] = None
    for attempt in range(1, DOWNLOAD_MAX_RETRIES + 1):
        md5_hasher = hashlib.md5()
        sha1_hasher = hashlib.sha1()
        sent = start_offset  # 绝对偏移：续传时前缀已在盘上，从断点继续
        try:
            info = _resolve_source_download(source_provider, source_cookie, source_file_id)
            url = normalize_http_url(str(info.get("url", "") or ""))
            # 源网盘可能返回必须配套使用的最新 cookie（夸克 __puus 会轮换，旧值下载 403）
            download_cookie = str(info.get("cookie", "") or "").strip() or source_cookie
            headers = _download_headers(
                download_cookie,
                str(getattr(source_provider, "name", "") or ""),
                info.get("headers"),
            )
            _check_cancelled(cancel_check)

            if total > 0:
                fd = _sink_file_descriptor(sink)
                workers = _clamp_parallel_workers(DOWNLOAD_PARALLEL_WORKERS)
                remaining = total - start_offset
                segment_count = (
                    remaining + DOWNLOAD_SEGMENT_BYTES - 1
                ) // DOWNLOAD_SEGMENT_BYTES
                if fd is not None and workers > 1 and segment_count >= 2:
                    # 并行分段：仅临时文件通道（内存流没有 fd，无法按偏移写）
                    written = _download_segments_parallel(
                        url=url,
                        headers=headers,
                        fd=fd,
                        total=total,
                        start_offset=start_offset,
                        workers=min(workers, segment_count),
                        progress_cb=progress_cb,
                        cancel_check=cancel_check,
                        on_segment_done=on_segment_done,
                    )
                    sent = written
                    # 并行段内不算哈希，落盘后统一算；读盘期间按「已下载字节」
                    # 继续上报进度（sent 不会超过 total，不伪造）
                    _report_progress(progress_cb, sent, total, "download")
                    md5_hex, sha1_hex = _hash_local_file(
                        fd, total, cancel_check=cancel_check
                    )
                    return {
                        "size": sent,
                        "md5": md5_hex,
                        "sha1": sha1_hex,
                        "downloaded_bytes": sent,
                    }
                # 串行分段：每段独立请求，哈希按顺序累计，结果与整文件流一致
                if start_offset > 0:
                    # 续传的串行分支：前缀上次已落盘，先读一遍补进哈希
                    _hash_file_prefix(
                        sink,
                        start_offset,
                        md5_hasher,
                        sha1_hasher,
                        cancel_check=cancel_check,
                    )
                while sent < total:
                    end = min(sent + DOWNLOAD_SEGMENT_BYTES, total) - 1
                    expected = end - sent + 1
                    segment_headers = dict(headers)
                    segment_headers["Range"] = f"bytes={sent}-{end}"
                    response = requests.get(
                        url,
                        stream=True,
                        headers=segment_headers,
                        timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
                    )
                    try:
                        range_ignored = int(getattr(response, "status_code", 0) or 0) == 200
                        if range_ignored and sent > 0:
                            raise CrossCloudCopyError(
                                "下载服务不支持分段续传（HTTP 200）", retriable=True
                            )
                        response.raise_for_status()
                        before = sent
                        sent = _consume_download_response(
                            response,
                            sink,
                            md5_hasher=md5_hasher,
                            sha1_hasher=sha1_hasher,
                            sent=sent,
                            total=total,
                            progress_cb=progress_cb,
                            cancel_check=cancel_check,
                            limit=0 if range_ignored else expected,
                        )
                    finally:
                        try:
                            response.close()
                        except Exception:
                            pass
                    if range_ignored:
                        # 服务端不认 Range，这一遍已经是整个文件
                        break
                    if sent - before != expected:
                        raise CrossCloudCopyError(
                            f"分段下载不完整（{sent - before}/{expected} 字节）", retriable=True
                        )
                    if on_segment_done is not None:
                        try:
                            on_segment_done(sent)
                        except Exception:
                            pass
            else:
                response = requests.get(
                    url,
                    stream=True,
                    headers=headers,
                    timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
                )
                try:
                    response.raise_for_status()
                    sent = _consume_download_response(
                        response,
                        sink,
                        md5_hasher=md5_hasher,
                        sha1_hasher=sha1_hasher,
                        sent=sent,
                        total=total,
                        progress_cb=progress_cb,
                        cancel_check=cancel_check,
                    )
                finally:
                    try:
                        response.close()
                    except Exception:
                        pass

            if total >= 0 and sent != total:
                raise CrossCloudCopyError(
                    f"下载不完整（{sent}/{total} 字节）", retriable=True
                )
            return {
                "size": sent,
                "md5": md5_hasher.hexdigest(),
                "sha1": sha1_hasher.hexdigest().upper(),
                "downloaded_bytes": sent,
            }
        except CrossCloudCopyCancelled:
            raise
        except Exception as exc:
            last_error = exc
            if attempt >= DOWNLOAD_MAX_RETRIES:
                break
            logger.info(
                "cross-cloud download attempt %s/%s failed (%s), refreshing link",
                attempt,
                DOWNLOAD_MAX_RETRIES,
                exc,
            )
            _reset_sink(sink, keep_prefix_bytes=start_offset)
            time.sleep(DOWNLOAD_RETRY_BASE_SECONDS * attempt)
    raise CrossCloudCopyError(f"源文件下载失败：{last_error}", retriable=True)


class _LazyDownloadSink:
    """惰性下载 sink：构造时不下载，第一次真正需要数据时才落地。

    用途：源端已知 ``sha1 + size`` 时，目标端做秒传探测只用到元信息，
    命中就完全不读数据。把下载推迟到第一次 ``read()`` / 「seek 到非零位置」，
    秒传命中 → 这些调用永不发生 → 零下载流量；未命中 → 才真正下一遍。

    双通道沿用 ``_open_sink``：≤64MB 进内存，>64MB 进临时文件（``temp_dir``）。
    下载完成后用已知 SHA1 校验；不一致说明已知哈希已经不可信（源文件被替换、
    或备忘录记错了），抛 ``_SourceHashMismatch``（文案「源文件已变更，请重试」），
    由上层决定是「清缓存重算」自愈还是直接失败。

    ``size`` 是属性（符合 ``UploadSink`` 协议与各 provider 的
    ``getattr(sink, "size", -1)`` 用法），读取它**不会**触发下载。
    """

    def __init__(
        self,
        *,
        source_provider: CloudProvider,
        source_cookie: str,
        source_file_id: str,
        size: int,
        expected_sha1: str = "",
        temp_dir: str = "",
        progress_cb=None,
        cancel_check=None,
    ):
        self._source_provider = source_provider
        self._source_cookie = str(source_cookie or "")
        self._source_file_id = str(source_file_id or "")
        self._size = int(size)
        self._expected_sha1 = _normalize_sha1(expected_sha1)
        self._temp_dir = str(temp_dir or "")
        self._progress_cb = progress_cb
        self._cancel_check = cancel_check

        self._sink: Optional[Any] = None
        self._is_temp_file = False
        self._temp_path = ""
        self._pos = 0
        self._loaded = False
        self._closed = False
        self._keep_temp = False
        self._md5 = ""
        self._sha1 = ""

    # ---- 状态查询（都不触发下载） ----
    @property
    def size(self) -> int:
        return self._size

    @property
    def downloaded(self) -> bool:
        """是否真的发生过下载（零流量路径下应为 False）。"""
        return self._loaded

    @property
    def md5(self) -> str:
        return self._md5

    @property
    def sha1(self) -> str:
        return self._sha1 or self._expected_sha1

    @property
    def temp_path(self) -> str:
        return self._temp_path

    # ---- 内部：下载落地 ----
    @staticmethod
    def _release(sink, is_temp_file: bool, temp_path: str) -> None:
        if sink is not None:
            try:
                sink.close()
            except Exception:
                pass
        if is_temp_file and temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                logger.warning("cross-cloud lazy temp file cleanup failed: %s", temp_path)

    def _ensure_loaded(self) -> None:
        """首次需要数据时完整下载一次，并用已知 SHA1 / 大小校验。"""
        if self._loaded:
            return
        if self._closed:
            raise CrossCloudCopyError("下载数据源已关闭，无法继续读取")
        _precheck_disk_space(self._temp_dir, self._size)
        sink, is_temp_file, temp_path = _open_sink(self._size, self._temp_dir)
        try:
            download_result = _download_to_sink(
                source_provider=self._source_provider,
                source_cookie=self._source_cookie,
                source_file_id=self._source_file_id,
                sink=sink,
                total=self._size,
                progress_cb=self._progress_cb,
                cancel_check=self._cancel_check,
            )
        except BaseException:
            self._release(sink, is_temp_file, temp_path)
            raise
        downloaded = int(download_result.get("size", 0) or 0)
        sha1 = _normalize_sha1(download_result.get("sha1", ""))
        if downloaded <= 0:
            self._release(sink, is_temp_file, temp_path)
            raise CrossCloudCopyError("源文件为空或下载不到数据")
        if downloaded != self._size:
            self._release(sink, is_temp_file, temp_path)
            raise CrossCloudCopyError(
                f"下载不完整（{downloaded}/{self._size} 字节）", retriable=True
            )
        if self._expected_sha1 and sha1 != self._expected_sha1:
            self._release(sink, is_temp_file, temp_path)
            _invalidate_source_hash(self._source_provider, self._source_cookie, self._source_file_id)
            logger.warning(
                "cross-cloud lazy sink hash mismatch: file_id=%s expected=%s actual=%s",
                self._source_file_id,
                self._expected_sha1[:12],
                sha1[:12],
            )
            raise _SourceHashMismatch(expected_sha1=self._expected_sha1, actual_sha1=sha1)
        sink.seek(0)
        self._sink = sink
        self._is_temp_file = is_temp_file
        self._temp_path = temp_path
        self._md5 = str(download_result.get("md5", "") or "")
        self._sha1 = sha1
        self._pos = 0
        self._loaded = True
        logger.info(
            "cross-cloud lazy sink downloaded on demand: file_id=%s size=%s temp=%s",
            self._source_file_id,
            downloaded,
            bool(is_temp_file),
        )

    def _target_offset(self, offset: int, whence: int) -> int:
        if whence == 1:
            return self._pos + offset
        if whence == 2:
            return self._size + offset
        return offset

    # ---- UploadSink 协议 ----
    def read(self, n: int = -1) -> bytes:
        # read(0) 不需要数据，别为它触发一次整文件下载
        if n == 0:
            return b""
        if self._closed:
            raise CrossCloudCopyError("下载数据源已关闭，无法继续读取")
        self._ensure_loaded()
        data = self._sink.read(n)
        self._pos = self._sink.tell()
        return data

    def seek(self, offset: int, whence: int = 0) -> int:
        try:
            offset = int(offset or 0)
        except (TypeError, ValueError) as exc:
            raise CrossCloudCopyError(f"非法的定位偏移：{offset!r}") from exc
        if self._closed:
            raise CrossCloudCopyError("下载数据源已关闭，无法定位")
        # seek 到非零位置意味着上层要用数据（如 115 二次验证读片段、proof_code 取 8 字节）
        if self._target_offset(offset, whence) != 0:
            self._ensure_loaded()
        if self._loaded:
            self._pos = self._sink.seek(offset, whence)
        else:
            self._pos = 0
        return self._pos

    def tell(self) -> int:
        return self._pos

    def close(self) -> None:
        """释放底层 sink 并删除临时文件；从未下载过时也必须安静返回。

        ``keep_temp_file()`` 标记过的除外：断点续传场景下本次运行失败但
        已完整下载的数据要留在盘上给下次继承，删了就白下了。
        """
        if self._closed:
            return
        self._closed = True
        sink = self._sink
        is_temp_file = self._is_temp_file
        temp_path = self._temp_path
        self._sink = None
        self._temp_path = ""
        if sink is not None:
            try:
                sink.close()
            except Exception:
                pass
        if is_temp_file and temp_path and not self._keep_temp:
            try:
                os.remove(temp_path)
            except Exception:
                logger.warning("cross-cloud lazy temp file cleanup failed: %s", temp_path)

    def keep_temp_file(self) -> None:
        """标记关闭时不删临时文件（断点续传：本次失败但数据要留给下次）。"""
        self._keep_temp = True


def _target_has_same_file(
    target_provider: CloudProvider,
    target_cookie: str,
    target_dir_id: str,
    filename: str,
    size: int,
) -> bool:
    """幂等预检：目标目录已存在同名同大小文件则跳过（列目录失败不阻断）。"""
    try:
        kwargs: Dict[str, Any] = {}
        try:
            if "force_refresh" in inspect.signature(target_provider.list_entries_payload).parameters:
                # 刚上传完就复跑时，列表缓存里还没有新文件；跳过预检会重复上传
                kwargs["force_refresh"] = True
        except (TypeError, ValueError):
            pass
        payload = target_provider.list_entries_payload(target_cookie, target_dir_id, **kwargs)
    except Exception as exc:
        logger.info("cross-cloud existing check skipped (list failed): %s", exc)
        return False
    entries = payload.get("entries", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("is_dir"):
            continue
        if str(entry.get("name", "") or "") != filename:
            continue
        if int(entry.get("size", 0) or 0) == int(size):
            return True
    return False


def _remember_hash_quietly(provider: str, file_id: str, size: int, sha1: str) -> None:
    """把确认过的哈希写进备忘录。缓存只是优化，任何异常都不许冒泡到复制主流程。"""
    if not provider or not file_id or int(size or 0) <= 0 or not sha1:
        return
    try:
        media_hash_cache.remember_file_hash(provider, file_id, int(size), sha1)
    except Exception as exc:
        logger.warning("媒体哈希缓存写入异常（已忽略）：%s", exc)


def _forget_hash_quietly(provider: str, file_id: str) -> None:
    """清掉一条哈希记录（脏缓存自愈用）。同样不允许因缓存故障打断复制。"""
    try:
        media_hash_cache.forget_file_hash(provider, file_id)
    except Exception as exc:
        logger.warning("媒体哈希缓存清除异常（已忽略）：%s", exc)


def _safe_int(value: Any, default: int = -1) -> int:
    """宽松取整：续传状态等外部输入的坏值回落默认值，不让脏数据抛出来。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class _ResumeTracker:
    """续传状态的「就地更新 + 回调节流」管家（引擎侧 F2 接缝）。

    resume dict 由上层（任务层）构造并持有，引擎只消费合法字段、就地更新；
    每次实质变更通过 on_resume_update 通知上层落库。回调异常一律吞掉——
    续传状态持久化失败不该打断复制本身（最坏后果是下次重试多下几段）。

    更新时机（设计文档 §3.3）：
      ① 下载每完成一段：节流 ≥1s（段完成频率高，每次落库没有意义；
         阈值内的更新仍会写进内存 dict，上层失败时读到的就是最新值）；
      ② 下载完成算出哈希：一次性写 sha1/md5/downloaded_bytes=size，不节流；
      ③ 上传每个分片完成：on_part_done 回调，不节流（分片频率低，
         且取消/失败时要的就是最新 parts）。

    两种激活方式（integration：缺了第二种，首跑失败的数据没人记录，
    续传链 bootstrap 不起来）：
      - **继承**（resume_active）：任务层传来的状态校验通过，续下/跳过下载；
      - **只记账**（tracking-only）：任务层传了空骨架 + 落库回调，本次是
        全新运行，但临时文件路径、下载进度、哈希、上传会话都要记进状态——
        失败/取消时任务层凭它落库，重试时才接得上。
    """

    _MIN_INTERVAL_SECONDS = 1.0

    def __init__(self, resume: Optional[Dict[str, Any]], on_resume_update=None):
        self._resume = resume if isinstance(resume, dict) else None
        self._callback = on_resume_update if callable(on_resume_update) else None
        self._last_fire = 0.0

    @property
    def active(self) -> bool:
        return self._resume is not None

    @property
    def records(self) -> bool:
        """是否处于「记账且有人落库」状态——只有这时保留临时文件才有意义。"""
        return self._resume is not None and self._callback is not None

    def _fire(self) -> None:
        if self._resume is None or self._callback is None:
            return
        try:
            self._callback(self._resume)
        except Exception as exc:
            logger.info("cross-cloud resume update callback failed (ignored): %s", exc)

    def note_downloaded(self, downloaded_bytes: int) -> None:
        """下载进度更新（连续前缀字节数，节流）。

        入参按分段栅格向下对齐后再记：并行路径的末段、200 降级路径上报的是
        「文件末尾」，文件大小不是段整数倍时该值天然不对齐；把它当续传起点
        存下去，下次续传就会被引擎的栅格校验拦死（「续传起始偏移未按分段
        边界对齐」）。对齐只少记不足一段，属于安全方向。
        """
        if self._resume is None:
            return
        value = int(downloaded_bytes)
        if value > 0 and value % DOWNLOAD_SEGMENT_BYTES:
            value = (value // DOWNLOAD_SEGMENT_BYTES) * DOWNLOAD_SEGMENT_BYTES
        self._resume["downloaded_bytes"] = value
        now = time.monotonic()
        if now - self._last_fire < self._MIN_INTERVAL_SECONDS:
            return
        self._last_fire = now
        self._fire()

    def note_hashes(self, sha1: str, md5: str, size: int) -> None:
        """下载完成：一次性写哈希与全量字节（立即触发，不节流）。"""
        if self._resume is None:
            return
        self._resume["sha1"] = str(sha1 or "")
        self._resume["md5"] = str(md5 or "")
        self._resume["downloaded_bytes"] = int(size)
        if int(size) > 0:
            self._resume["size"] = int(size)
        self._last_fire = time.monotonic()
        self._fire()

    def note_size(self, size: int) -> None:
        """源元信息补全了总大小（全新运行且调用方没给大小时）。"""
        if self._resume is None:
            return
        value = int(size or 0)
        if value <= 0 or _safe_int(self._resume.get("size"), 0) == value:
            return
        self._resume["size"] = value
        self._fire()

    def adopt_temp_file(self, temp_path: str, size: int = 0) -> None:
        """认领本次运行新建的临时文件（tracking-only 的起点）。

        在 ``_open_sink`` 之后立刻调用：路径先入状态，后续每段进度、哈希、
        分片才有地方可写。重复调用不覆盖已有路径（续传运行的路径以状态为准）。
        """
        if self._resume is None or not str(temp_path or "").strip():
            return
        if not str(self._resume.get("temp_path") or "").strip():
            self._resume["temp_path"] = str(temp_path)
        value = int(size or 0)
        if value > 0:
            self._resume["size"] = value
        if _safe_int(self._resume.get("downloaded_bytes"), 0) < 0:
            self._resume["downloaded_bytes"] = 0
        self._fire()

    def adopt_downloaded(self, temp_path: str, size: int, sha1: str, md5: str) -> None:
        """认领一份「已完整下载并算过哈希」的本地文件（惰性 sink 专用）。

        零流量路径的下载发生在 provider 上传内部，引擎拿不到中间进度；
        上传失败/取消时惰性 sink 里已是完整文件，这里一次性把
        temp_path/哈希/字节数全部写进状态，临时文件随之保留给下次。
        """
        if self._resume is None or not str(temp_path or "").strip():
            return
        self._resume["temp_path"] = str(temp_path)
        value = int(size or 0)
        if value > 0:
            self._resume["size"] = value
            self._resume["downloaded_bytes"] = value
        self._resume["sha1"] = str(sha1 or "")
        self._resume["md5"] = str(md5 or "")
        self._fire()

    @property
    def upload_session(self) -> Optional[Dict[str, Any]]:
        """目标端上传会话（115 分片续传用）；无效字段按无会话处理。"""
        if self._resume is None:
            return None
        session = self._resume.get("upload")
        return session if isinstance(session, dict) and session else None

    def arm_upload_session(self, provider_name: str = "") -> Optional[Dict[str, Any]]:
        """给上传会话挂 on_part_done 回调，返回会话本体（无会话返回 None）。

        回调由 provider 每完成一个分片调用一次：按 PartNumber 去重记账
        （OSS 重试同一 part 会再次上报，不能重复），并触发一次续传更新。

        首跑（骨架里还没有会话）时现场新建一个空会话挂上去：provider 的
        首run 分支会把 initupload 的 fields/upload_id 填进来，分片完成
        再逐个记账——没有这一步，首跑的上传会话永远不进状态，取消/失败
        后无会话可续。
        """
        session = self.upload_session
        if session is None:
            if not self.records:
                return None
            session = {
                "provider": str(provider_name or ""),
                "fields": {},
                "upload_id": "",
                "parts": [],
            }
            self._resume["upload"] = session
        parts = session.get("parts")
        if not isinstance(parts, list):
            parts = []
            session["parts"] = parts

        def _on_part_done(part_number, etag) -> None:
            try:
                number = int(part_number)
            except (TypeError, ValueError):
                return
            for existing in parts:
                if isinstance(existing, dict) and existing.get("PartNumber") == number:
                    existing["ETag"] = str(etag or "")
                    break
            else:
                parts.append({"PartNumber": number, "ETag": str(etag or "")})
            self._fire()

        session["on_part_done"] = _on_part_done
        return session


def copy_file_across_clouds(
    *,
    source_provider: CloudProvider,
    source_cookie: str,
    source_file_id: str,
    target_provider: CloudProvider,
    target_cookie: str,
    target_dir_id: str,
    filename: str = "",
    size: int = -1,
    temp_dir: str = "",
    cfg: Optional[Dict[str, Any]] = None,
    progress_cb=None,
    cancel_check=None,
    check_existing: bool = False,
    source_sha1: str = "",
    source_size: int = -1,
    source_md5: str = "",
    resume: Optional[Dict[str, Any]] = None,
    on_resume_update=None,
) -> CopyFileResult:
    """把源网盘的单个文件复制到目标网盘（秒传优先，未命中分片上传）。

    :param source_file_id: 源网盘文件 id（夸克 fid / 115 fid 或 pick_code / 阿里 file_id）
    :param filename: 保存到目标网盘的文件名；为空则用源文件名
    :param size: 文件总大小；-1 时下载后按实际字节数
    :param temp_dir: 大文件临时目录（空 = 系统默认；建议指向机械硬盘挂载点）
    :param cfg: 应用配置（get_config()）；temp_dir 为空时按其解析存储位置
    :param check_existing: 复制前检查目标目录是否已有同名同大小文件（跳过则记 skipped）
    :param source_sha1: 源端已知 SHA1（大写十六进制）；给了就不再下载算哈希
    :param source_size: 源端已知大小（配合 source_sha1 使用，须 > 0）
    :param source_md5: 可选；115/阿里通常没有 md5，允许为空
    :param resume: 断点续传状态（任务层构造、引擎就地更新）。字段：
        temp_path / size / sha1 / md5 / downloaded_bytes / upload。
        sha1 非空且临时文件完整 → 跳过下载直接用本地文件；无 sha1 →
        从 downloaded_bytes（连续前缀）续下剩余段；None → 原路径不变。
    :param on_resume_update: 续传状态变更回调（上层落库用），异常被吞掉不打断复制

    零流量判定：``source_sha1`` 合法且 ``source_size > 0``；未传时先问
    ``resolve_source_hash()``（115/阿里的元信息里就有 SHA1）。命中则走惰性 sink，
    目标端秒传命中时一个字节都不下载（resume 生效时优先按断点续传/直读，
    不走惰性 sink）。
    """
    started = time.monotonic()
    source_name = str(getattr(source_provider, "name", "") or "")
    target_name = str(getattr(target_provider, "name", "") or "")

    if source_provider is None or target_provider is None:
        raise CrossCloudCopyError("复制源或目标未配置")
    if not str(source_file_id or "").strip():
        raise CrossCloudCopyError("源文件 ID 不能为空")
    if not getattr(target_provider, "supports_upload", False):
        raise CrossCloudCopyError(
            f"{getattr(target_provider, 'label', target_name) or '目标网盘'} 暂不支持上传，无法作为复制目标"
        )
    if source_name and source_name == target_name:
        raise CrossCloudCopyError("复制源与目标不能是同一个网盘")

    filename = str(filename or "").strip()

    # ---- 续传状态（resume）规范化与校验 ----
    # resume 由任务层构造（temp_path/size/sha1/md5/downloaded_bytes/upload），
    # 引擎只消费合法状态；字段缺失、文件不在、大小对不上都按「无续传」处理——
    # 带着坏状态往下走只会产出脏文件并传上网盘。
    resume_state = resume if isinstance(resume, dict) else None
    resume_active = False
    resume_skip_download = False
    resume_temp_path = ""
    resume_size = -1
    resume_downloaded = 0
    resume_sha1 = ""
    resume_md5 = ""
    if resume_state is not None:
        resume_temp_path = str(resume_state.get("temp_path", "") or "").strip()
        resume_size = _safe_int(resume_state.get("size"), -1)
        resume_sha1 = _normalize_sha1(resume_state.get("sha1", ""))
        resume_md5 = str(resume_state.get("md5", "") or "").strip().lower()
        resume_downloaded = _safe_int(resume_state.get("downloaded_bytes"), 0)
        # 续传起点必须落在下载分段栅格上，否则 _download_to_sink 会拒绝（从段
        # 中间接下去写出的文件是错位的）。历史状态里出现非栅格值的原因：末段
        # 完成 / 200 降级路径上报的是「文件末尾」，落库时没跟哈希一起写成功就
        # 留下「位置是文件尾、哈希为空」的半套状态。这里向下取整到段边界——
        # 连续前缀 [0, downloaded) 必然包含 [0, 对齐后)，所以永远安全，最坏
        # 只多重下不足一段；同时对就地把状态修正成合法值，避免反复失败。
        if resume_downloaded > 0 and resume_downloaded % DOWNLOAD_SEGMENT_BYTES:
            aligned_offset = (
                resume_downloaded // DOWNLOAD_SEGMENT_BYTES
            ) * DOWNLOAD_SEGMENT_BYTES
            logger.info(
                "cross-cloud resume offset %s not segment-aligned, rewinding to %s",
                resume_downloaded,
                aligned_offset,
            )
            resume_downloaded = aligned_offset
            resume_state["downloaded_bytes"] = aligned_offset
        valid = (
            bool(resume_temp_path)
            and resume_size > 0
            and 0 <= resume_downloaded <= resume_size
        )
        if valid and size >= 0 and int(size) != resume_size:
            logger.info(
                "cross-cloud resume size %s != declared size %s, ignoring resume",
                resume_size,
                size,
            )
            valid = False
        if valid and not os.path.isfile(resume_temp_path):
            logger.info("cross-cloud resume temp file missing: %s", resume_temp_path)
            valid = False
        if valid:
            try:
                resume_actual_size = os.path.getsize(resume_temp_path)
            except OSError as exc:
                logger.info(
                    "cross-cloud resume temp file unreadable: %s (%s)",
                    resume_temp_path,
                    exc,
                )
                valid = False
            else:
                if resume_actual_size < resume_downloaded:
                    logger.info(
                        "cross-cloud resume temp file %s smaller than prefix %s, ignoring resume",
                        resume_actual_size,
                        resume_downloaded,
                    )
                    valid = False
                elif resume_sha1 and resume_actual_size == resume_size:
                    # 哈希上次已算且文件完整：本地就是完整文件，完全跳过下载
                    resume_skip_download = True
        if valid:
            resume_active = True
            if size < 0:
                # 调用方不知道大小时，用续传状态里记录的大小
                size = resume_size
            logger.info(
                "cross-cloud resume armed: temp=%s size=%s downloaded=%s sha1=%s skip_download=%s",
                resume_temp_path,
                resume_size,
                resume_downloaded,
                resume_sha1[:12] or "-",
                resume_skip_download,
            )
    # tracking-only：状态本身不可继承（首跑 / 已作废），但任务层给了骨架 +
    # 落库回调——本次运行照常全新复制，临时文件/进度/哈希/上传会话全部记账，
    # 失败取消时任务层凭它落库，重试才接得上（集成修复：否则首跑失败的数据
    # 没人记录，续传链永远走不到第二步）。
    tracking_only = (
        resume_state is not None
        and not resume_active
        and callable(on_resume_update)
    )
    tracker = _ResumeTracker(
        resume_state if (resume_active or tracking_only) else None,
        on_resume_update,
    )

    # ---- 幂等预检 ----
    if check_existing and filename and size >= 0:
        if _target_has_same_file(target_provider, target_cookie, target_dir_id, filename, size):
            return CopyFileResult(
                status="skipped",
                source_provider=source_name,
                target_provider=target_name,
                name=filename,
                size=size,
                message="目标已存在同名同大小文件，跳过",
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

    # ---- 源端已知哈希（零流量快路径的前置条件） ----
    # 调用方显式给出优先；否则问 provider（115/阿里读元信息即可，夸克拿不到会返回 {}）。
    known_sha1 = _normalize_sha1(source_sha1)
    try:
        known_size = int(source_size) if source_size is not None else -1
    except (TypeError, ValueError):
        known_size = -1
    known_md5 = str(source_md5 or "").strip().lower()
    hash_name_hint = ""
    hash_origin = "caller" if (known_sha1 and known_size > 0) else ""
    if not hash_origin:
        known_sha1, known_size, known_md5 = "", -1, ""
        probed = resolve_source_hash(source_provider, source_cookie, source_file_id, size=size)
        if probed:
            known_sha1 = _normalize_sha1(probed.get("sha1", ""))
            try:
                known_size = int(probed.get("size", 0) or 0)
            except (TypeError, ValueError):
                known_size = -1
            if known_sha1 and known_size > 0:
                known_md5 = known_md5 or str(probed.get("md5", "") or "").strip().lower()
                hash_name_hint = str(probed.get("name", "") or "").strip()
                # 哈希来自持久化备忘录时记成 cache：校验不一致就自愈（清缓存重算）
                hash_origin = str(probed.get("origin", "") or "provider")
            else:
                known_sha1, known_size = "", -1

    zero_traffic = bool(known_sha1 and known_size > 0)
    if zero_traffic and size >= 0 and int(size) != known_size:
        logger.info(
            "cross-cloud size hint %s != source hash size %s, using hash size",
            size,
            known_size,
        )

    if not str(temp_dir or "").strip() and cfg is not None:
        temp_dir = resolve_temp_dir(cfg)

    total = int(size)

    def _copy_once(use_zero_traffic: bool) -> CopyFileResult:
        """跑一遍「准备数据源 → 上传」，一次尝试独占自己的 sink 与临时文件。

        之所以收成内部函数：脏缓存自愈需要换条路径重跑一遍，而惰性 sink 与临时
        文件必须在两次尝试之间彻底释放，不能串用上一轮的半截数据。
        """
        nonlocal filename
        attempt_total = int(total if not use_zero_traffic else known_size)
        attempt_sha1 = ""
        attempt_md5 = ""
        attempt_sink = None
        attempt_lazy: Optional[_LazyDownloadSink] = None
        attempt_is_temp = False
        attempt_temp_path = ""
        attempt_ok = False
        attempt_start_offset = 0
        # 本次运行已下到的字节旁路（失败时决定临时文件保留还是清理）；
        # 并行路径会预分配稀疏文件，文件大小可能虚高，不能只看 getsize
        downloaded_high_water = [0]
        try:
            if resume_skip_download:
                # ---- 续传直达：本地临时文件已是完整文件（哈希上次已算），只读 sink ----
                if not filename:
                    try:
                        info = _resolve_source_download(source_provider, source_cookie, source_file_id)
                        filename = _info_filename(info)
                    except Exception as exc:
                        logger.info("cross-cloud filename probe failed: %s", exc)
                if not filename:
                    filename = f"cross-copy-{int(started)}"
                try:
                    attempt_sink = open(resume_temp_path, "rb")
                except OSError as exc:
                    raise CrossCloudCopyError(
                        f"续传临时文件不可读：{resume_temp_path}（{exc}）"
                    ) from exc
                attempt_is_temp = True
                attempt_temp_path = resume_temp_path
                attempt_start_offset = resume_downloaded
                downloaded_high_water[0] = resume_downloaded
                attempt_sha1 = resume_sha1
                attempt_md5 = resume_md5
                attempt_sink.seek(0)
                logger.info(
                    "cross-cloud resume skip-download: %s->%s file_id=%s size=%s sha1=%s",
                    source_name,
                    target_name,
                    source_file_id,
                    attempt_total,
                    attempt_sha1[:12],
                )
            elif use_zero_traffic:
                # ---- 零流量路径：不提前下载，用惰性 sink 把下载推迟到首次读数据 ----
                if not filename:
                    filename = hash_name_hint
                if not filename:
                    # 只为拿文件名探一次元信息（元信息请求不产生下载流量）
                    try:
                        info = _resolve_source_download(source_provider, source_cookie, source_file_id)
                        filename = _info_filename(info)
                    except Exception as exc:
                        logger.info("cross-cloud filename probe failed: %s", exc)
                if not filename:
                    filename = f"cross-copy-{int(started)}"

                attempt_sha1 = known_sha1
                attempt_md5 = known_md5
                attempt_lazy = _LazyDownloadSink(
                    source_provider=source_provider,
                    source_cookie=source_cookie,
                    source_file_id=source_file_id,
                    size=attempt_total,
                    expected_sha1=attempt_sha1,
                    temp_dir=str(temp_dir or ""),
                    progress_cb=progress_cb,
                    cancel_check=cancel_check,
                )
                attempt_sink = attempt_lazy
                logger.info(
                    "cross-cloud zero-traffic path armed: %s->%s file_id=%s size=%s sha1=%s origin=%s",
                    source_name,
                    target_name,
                    source_file_id,
                    attempt_total,
                    attempt_sha1[:12],
                    hash_origin,
                )
                # 不伪造 0→100 的下载进度，直接进入上传阶段（秒传命中即瞬间完成）
                _report_progress(progress_cb, 0, attempt_total, "upload")
            else:
                # ---- 原路径：下载（双通道 + 同步哈希），拿不到源哈希时走这里 ----
                if resume_active:
                    # 续传分支：打开既有临时文件（保留已落盘的连续前缀，不能 truncate）；
                    # 空间预检只看剩余字节——前缀已经在盘上，不占新增空间。
                    _precheck_disk_space(
                        str(temp_dir or ""),
                        max(0, attempt_total - resume_downloaded),
                    )
                    try:
                        attempt_sink = open(resume_temp_path, "r+b")
                    except OSError as exc:
                        raise CrossCloudCopyError(
                            f"续传临时文件不可写：{resume_temp_path}（{exc}）"
                        ) from exc
                    attempt_is_temp = True
                    attempt_temp_path = resume_temp_path
                    attempt_start_offset = resume_downloaded
                    # 串行分支的写入口；并行分支用 os.pwrite 按段偏移写，无视该位置
                    attempt_sink.seek(resume_downloaded)
                else:
                    sink_size = size if size >= 0 else -1
                    _precheck_disk_space(str(temp_dir or ""), sink_size)
                    attempt_sink, attempt_is_temp, attempt_temp_path = _open_sink(sink_size, temp_dir)
                    if tracker.records and not resume_active:
                        # 全新运行也要记断点：临时文件路径立刻入状态，后续每段
                        # 进度 / 哈希 / 上传分片才有地方可写（tracking-only）
                        tracker.adopt_temp_file(
                            attempt_temp_path,
                            attempt_total if attempt_total > 0 else 0,
                        )
                # 先探一次源元信息补全文件名/大小
                if not filename or size < 0:
                    try:
                        info = _resolve_source_download(source_provider, source_cookie, source_file_id)
                        if not filename:
                            filename = _info_filename(info)
                        if size < 0:
                            hinted = int(info.get("size", 0) or 0)
                            if hinted > 0:
                                attempt_total = hinted
                    except Exception as exc:
                        logger.info("cross-cloud source meta probe failed: %s", exc)
                if tracker.records and attempt_total > 0:
                    # 元信息补全了总大小：同步进状态（大小是续传校验的前提）
                    tracker.note_size(attempt_total)
                if not filename:
                    filename = f"cross-copy-{int(started)}"

                downloaded_high_water[0] = attempt_start_offset

                def _recording_progress(
                    sent_bytes: int, total_bytes: int, phase: str = "download"
                ) -> None:
                    # 旁路记录下载水位（失败时判断临时文件里有没有已下到的字节），
                    # 再原样转发给调用方的进度回调
                    if phase == "download":
                        try:
                            if int(sent_bytes) > downloaded_high_water[0]:
                                downloaded_high_water[0] = int(sent_bytes)
                        except (TypeError, ValueError):
                            pass
                    _report_progress(progress_cb, sent_bytes, total_bytes, phase)

                download_result = _download_to_sink(
                    source_provider=source_provider,
                    source_cookie=source_cookie,
                    source_file_id=source_file_id,
                    sink=attempt_sink,
                    total=attempt_total,
                    progress_cb=_recording_progress,
                    cancel_check=cancel_check,
                    start_offset=attempt_start_offset,
                    on_segment_done=tracker.note_downloaded,
                )
                downloaded = int(download_result.get("size", 0) or 0)
                if downloaded <= 0:
                    raise CrossCloudCopyError("源文件为空或下载不到数据")
                if size >= 0 and downloaded != size:
                    raise CrossCloudCopyError(
                        f"下载不完整（{downloaded}/{size} 字节）", retriable=True
                    )
                attempt_total = downloaded
                attempt_md5 = str(download_result.get("md5", "") or "")
                attempt_sha1 = str(download_result.get("sha1", "") or "").upper()
                attempt_sink.seek(0)
                # 时机②：下载完成、哈希已算——一次性把 sha1/md5/全量字节写进续传状态
                tracker.note_hashes(attempt_sha1, attempt_md5, attempt_total)

            # ---- 上传（秒传优先） ----
            def _upload_progress(sent_bytes: int, total_bytes: int, _phase: str = "upload") -> None:
                _report_progress(progress_cb, sent_bytes, total_bytes, "upload")

            # resume 为 None 时不传 upload_resume 参数（provider 旧签名无此关键字参数）
            upload_kwargs: Dict[str, Any] = {}
            upload_resume = tracker.arm_upload_session(target_name)
            if upload_resume is not None:
                # 115 分片续传会话：provider 每完成一个 part 调一次 on_part_done
                # （tracker 已挂好），parts 随之写进 resume 并触发上层落库
                upload_kwargs["upload_resume"] = upload_resume
            try:
                upload_result = target_provider.upload_file(
                    target_cookie,
                    attempt_sink,
                    filename,
                    str(target_dir_id or "").strip(),
                    sha1=attempt_sha1,
                    md5=attempt_md5,
                    size=attempt_total,
                    progress_cb=_upload_progress,
                    cancel_check=cancel_check,
                    **upload_kwargs,
                )
            except CrossCloudCopyCancelled:
                raise
            except CrossCloudCopyError:
                # 惰性 sink 在 upload_file 内部才下载：下载失败 / 源文件变更要原样冒泡，
                # 不能被下面的 UploadError 映射或「上传失败」包装吃掉
                raise
            except UploadError as exc:
                raise CrossCloudCopyError(str(exc), retriable=bool(getattr(exc, "retriable", False))) from exc
            except Exception as exc:
                raise CrossCloudCopyError(f"上传到目标网盘失败：{exc}", retriable=True) from exc

            status = str(getattr(upload_result, "status", "") or "uploaded")
            message = str(getattr(upload_result, "message", "") or "")
            # 「零流量」只在下游真的没读数据时成立。夸克做目标时秒传探测必须带 md5，
            # 而 115 / 阿里只给 sha1 —— 惰性 sink 会被迫下载一遍算 md5，此时上传确实
            # 零流量，但下载已经发生了，不能对用户说"未产生下载流量"。
            lazy_downloaded = bool(attempt_lazy is not None and attempt_lazy.downloaded)
            if use_zero_traffic and status == "rapid":
                if lazy_downloaded:
                    message = "秒传命中，未消耗上传流量（源端只有 SHA1，为算 MD5 下载了一遍）"
                else:
                    message = "秒传命中，未产生下载流量"
                logger.info(
                    "cross-cloud zero-traffic hit: %s->%s file_id=%s size=%s sha1=%s downloaded=%s",
                    source_name,
                    target_name,
                    source_file_id,
                    attempt_total,
                    attempt_sha1[:12],
                    lazy_downloaded,
                )
            elif use_zero_traffic and lazy_downloaded:
                logger.info(
                    "cross-cloud zero-traffic missed rapid, downloaded on demand: file_id=%s size=%s",
                    source_file_id,
                    attempt_total,
                )

            # 成功路径才沉淀哈希：算出来的 sha1 + size 已经过上传侧确认（惰性路径
            # 还经过下载校验），下次复制同一文件可以直接秒传，不必再下一遍。
            _remember_hash_quietly(source_name, source_file_id, attempt_total, attempt_sha1)
            attempt_ok = True
            return CopyFileResult(
                status=status,
                source_provider=source_name,
                target_provider=target_name,
                file_id=str(getattr(upload_result, "file_id", "") or ""),
                pick_code=str(getattr(upload_result, "pick_code", "") or ""),
                name=filename,
                size=attempt_total,
                sha1=attempt_sha1,
                message=message,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            # 断点续传：惰性 sink 已完整下载、但本次上传失败/取消——数据要留给
            # 下次（零流量路径的下载发生在 provider 上传内部，引擎拿不到中间
            # 进度，只能在这里按「已下载」一次性认领）。注意必须在 close 之前
            # 调 keep_temp_file：惰性 sink 的 close 默认删自己的临时文件。
            if (
                not attempt_ok
                and tracker.records
                and attempt_lazy is not None
                and attempt_lazy.downloaded
                and attempt_lazy.temp_path
            ):
                tracker.adopt_downloaded(
                    attempt_lazy.temp_path,
                    attempt_total,
                    attempt_lazy.sha1,
                    attempt_lazy.md5,
                )
                attempt_lazy.keep_temp_file()
            # 数据源自己负责底层 sink 与临时文件（惰性 sink 的 close 会删临时文件）
            if attempt_sink is not None:
                try:
                    attempt_sink.close()
                except Exception:
                    pass
            if attempt_is_temp and attempt_temp_path:
                # 临时文件保留规则（设计文档 §3.3）：成功即删；失败/取消时只要盘上
                # 已有数据就保留。分两种情况：
                # ① 续传运行（resume_active）：路径本来就是调用方给的、状态也由它
                #    持有（引擎就地更新同一个 dict），失败必须留——否则下次重试
                #    连前缀都没了；
                # ② 全新运行：只有确实下到字节（并行预分配会让文件虚大，必须按
                #    真实下载水位判断）且有人记账（tracker.records：任务层能落库）
                #    才留。没有记录、也没下到东西，保留了也没人继承，只会堆孤儿，
                #    保持旧行为直接删（残余由 24h 孤儿清理兜底）。
                keep_temp = not attempt_ok and (
                    resume_active
                    or (tracker.records and downloaded_high_water[0] > attempt_start_offset)
                )
                if keep_temp:
                    logger.info(
                        "cross-cloud temp file kept for resume: %s (downloaded=%s)",
                        attempt_temp_path,
                        downloaded_high_water[0],
                    )
                else:
                    try:
                        os.remove(attempt_temp_path)
                    except Exception:
                        logger.warning(
                            "cross-cloud temp file cleanup failed: %s", attempt_temp_path
                        )
    try:
        try:
            return _copy_once(zero_traffic and not resume_active)
        except _SourceHashMismatch as exc:
            # 脏缓存自愈：备忘录里的 sha1 不可信（网盘端文件被替换但 file_id 没变，
            # 或者上次记错了）。此时零流量路径会在下载校验时直接失败，必须清掉缓存、
            # 改走「正常下载重新算哈希」的路径重试一次，而不是把复制判死。
            # 只对来自备忘录的哈希自愈：调用方显式给 / provider 刚回的哈希对不上，
            # 说明源文件真的变了，静默换一份内容上传反而更危险。
            if hash_origin != "cache":
                raise
            _forget_hash_quietly(source_name, source_file_id)
            logger.warning(
                "哈希缓存与源文件不一致，已清除并重新计算：provider=%s file_id=%s expected=%s actual=%s",
                source_name,
                source_file_id,
                exc.expected_sha1[:12],
                exc.actual_sha1[:12],
            )
            total = int(size)
            return _copy_once(False)
    except CrossCloudCopyCancelled:
        raise
    except CrossCloudCopyError:
        raise
    except Exception as exc:
        raise CrossCloudCopyError(f"跨盘复制失败：{exc}") from exc


def cleanup_orphan_temp_files(temp_dir: str, max_age_hours: int = ORPHAN_TEMP_MAX_AGE_HOURS) -> int:
    """清理孤儿临时文件（超过 max_age_hours 的 xcopy-*.part）。

    启动时与周期性任务调用。返回清理数量。
    """
    safe_dir = str(temp_dir or "").strip()
    if not safe_dir or not os.path.isdir(safe_dir):
        return 0
    cutoff = time.time() - max(1, int(max_age_hours or ORPHAN_TEMP_MAX_AGE_HOURS)) * 3600
    removed = 0
    try:
        for name in os.listdir(safe_dir):
            if not name.startswith(TEMP_FILE_PREFIX) or not name.endswith(".part"):
                continue
            path = os.path.join(safe_dir, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except Exception:
                continue
    except Exception as exc:
        logger.info("cross-cloud orphan cleanup skipped: %s", exc)
    if removed:
        logger.info("cross-cloud orphan temp cleanup removed %s files in %s", removed, safe_dir)
    return removed
