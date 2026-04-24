import copy
import json
import os
import threading
from typing import Any, Callable, Dict, Optional


class JsonConfigStore:
    """Thread-safe JSON config store with mtime-based in-memory cache."""

    def __init__(
        self,
        path: str,
        default_factory: Callable[[], Dict[str, Any]],
        normalize: Callable[[Dict[str, Any]], Dict[str, Any]],
        post_load: Optional[Callable[[Dict[str, Any]], None]] = None,
        post_save: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._path = path
        self._default_factory = default_factory
        self._normalize = normalize
        self._post_load = post_load
        self._post_save = post_save
        self._lock = threading.Lock()
        self._cache_value: Optional[Dict[str, Any]] = None
        self._cache_mtime_ns: int = -1

    def _clone(self, value: Dict[str, Any]) -> Dict[str, Any]:
        return copy.deepcopy(value)

    def _ensure_parent(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)

    def _get_mtime_ns(self) -> int:
        try:
            return int(os.stat(self._path).st_mtime_ns)
        except Exception:
            return -1

    def _write_file(self, payload: Dict[str, Any]) -> None:
        self._ensure_parent()
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _ensure_exists(self) -> None:
        if os.path.exists(self._path):
            return
        payload = self._normalize(self._default_factory())
        self._write_file(payload)
        if self._post_save:
            self._post_save(payload)

    def _load_file(self) -> Dict[str, Any]:
        with open(self._path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        payload = raw if isinstance(raw, dict) else {}
        normalized = self._normalize(payload)
        if self._post_load:
            self._post_load(normalized)
        return normalized

    def get(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_exists()
            mtime_ns = self._get_mtime_ns()
            if self._cache_value is not None and mtime_ns == self._cache_mtime_ns:
                return self._clone(self._cache_value)
            loaded = self._load_file()
            self._cache_value = loaded
            self._cache_mtime_ns = self._get_mtime_ns()
            return self._clone(loaded)

    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize(payload if isinstance(payload, dict) else {})
        with self._lock:
            self._write_file(normalized)
            if self._post_save:
                self._post_save(normalized)
            self._cache_value = normalized
            self._cache_mtime_ns = self._get_mtime_ns()
            return self._clone(normalized)
