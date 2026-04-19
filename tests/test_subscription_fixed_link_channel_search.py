import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from typing import Any, Dict, List


CORE_PATH = Path("/Users/xianer/Documents/code/115-media-hub/app/core.py")
SUBSCRIPTION_SERVICE_PATH = Path("/Users/xianer/Documents/code/115-media-hub/app/services/subscription.py")


def _install_fastapi_stubs() -> None:
    if "fastapi" in sys.modules:
        return

    fastapi_module = types.ModuleType("fastapi")

    class _FakeFastAPI:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def add_middleware(self, *args, **kwargs) -> None:
            return None

        def mount(self, *args, **kwargs) -> None:
            return None

    fastapi_module.FastAPI = _FakeFastAPI
    fastapi_module.BackgroundTasks = type("BackgroundTasks", (), {})
    fastapi_module.Request = type("Request", (), {})
    sys.modules["fastapi"] = fastapi_module

    fastapi_responses = types.ModuleType("fastapi.responses")
    for name in (
        "FileResponse",
        "HTMLResponse",
        "JSONResponse",
        "RedirectResponse",
        "Response",
        "StreamingResponse",
    ):
        setattr(fastapi_responses, name, type(name, (), {}))
    sys.modules["fastapi.responses"] = fastapi_responses

    fastapi_staticfiles = types.ModuleType("fastapi.staticfiles")
    fastapi_staticfiles.StaticFiles = type("StaticFiles", (), {"__init__": lambda self, *args, **kwargs: None})
    sys.modules["fastapi.staticfiles"] = fastapi_staticfiles

    starlette_sessions = types.ModuleType("starlette.middleware.sessions")
    starlette_sessions.SessionMiddleware = type("SessionMiddleware", (), {})
    sys.modules["starlette.middleware.sessions"] = starlette_sessions


def _load_core_module():
    _install_fastapi_stubs()
    spec = importlib.util.spec_from_file_location("test_core_module_subscription_toggle", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load core.py for tests")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_subscription_function(fn_name: str):
    source = SUBSCRIPTION_SERVICE_PATH.read_text(encoding="utf-8")
    module_ast = ast.parse(source)
    target = None
    for node in module_ast.body:
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            target = node
            break
    if target is None:
        raise AssertionError(f"{fn_name} not found in subscription.py")
    isolated = ast.Module(body=[target], type_ignores=[])
    ast.fix_missing_locations(isolated)
    namespace: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
    }
    exec(compile(isolated, str(SUBSCRIPTION_SERVICE_PATH), "exec"), namespace)
    return namespace[fn_name]


class SubscriptionFixedLinkChannelSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core = _load_core_module()

    def test_normalize_subscription_task_defaults_followup_channel_search_disabled(self) -> None:
        normalized = self.core.normalize_subscription_task(
            {
                "title": "示例任务",
                "media_type": "tv",
                "savepath": "影视/示例",
                "share_link_url": "https://115.com/s/example",
            }
        )
        self.assertIn("fixed_link_channel_search", normalized)
        self.assertFalse(bool(normalized.get("fixed_link_channel_search")))

    def test_normalize_subscription_task_accepts_followup_channel_search_alias(self) -> None:
        normalized = self.core.normalize_subscription_task(
            {
                "title": "示例任务",
                "media_type": "tv",
                "savepath": "影视/示例",
                "share_link_url": "https://115.com/s/example",
                "fixed_link_followup_channel_search": True,
            }
        )
        self.assertTrue(bool(normalized.get("fixed_link_channel_search")))

    def test_merge_subscription_search_results_keeps_fixed_candidate_first(self) -> None:
        merge = _load_subscription_function("merge_subscription_search_results")
        merged = merge(
            {
                "candidate": {
                    "score": 100,
                    "item": {"link_url": "https://115.com/s/fixed", "title": "fixed"},
                },
                "candidates": [
                    {
                        "score": 100,
                        "item": {"link_url": "https://115.com/s/fixed", "title": "fixed"},
                    }
                ],
                "keywords": ["fixed-share-link"],
                "errors": [],
                "stats": {"search_keywords": 0, "searched_sources": 0, "matched_channels": 0, "best_score": 100},
            },
            {
                "candidate": {
                    "score": 86,
                    "item": {"link_url": "magnet:?xt=urn:btih:abc", "title": "fallback-1"},
                },
                "candidates": [
                    {
                        "score": 86,
                        "item": {"link_url": "magnet:?xt=urn:btih:abc", "title": "fallback-1"},
                    },
                    {
                        "score": 84,
                        "item": {"link_url": "https://115.com/s/fixed", "title": "duplicate-fixed"},
                    },
                ],
                "keywords": ["示例任务"],
                "errors": [{"channel_id": "ch1", "message": "timeout"}],
                "stats": {"search_keywords": 1, "searched_sources": 2, "matched_channels": 1, "best_score": 86},
            },
        )
        candidates = merged.get("candidates", [])
        self.assertGreaterEqual(len(candidates), 2)
        first_link = str((candidates[0].get("item", {}) or {}).get("link_url", ""))
        second_link = str((candidates[1].get("item", {}) or {}).get("link_url", ""))
        self.assertEqual(first_link, "https://115.com/s/fixed")
        self.assertEqual(second_link, "magnet:?xt=urn:btih:abc")
        self.assertEqual(len(candidates), 2)
        stats = merged.get("stats", {})
        self.assertEqual(int(stats.get("searched_sources", 0) or 0), 2)
        self.assertEqual(int(stats.get("matched_channels", 0) or 0), 1)
        self.assertEqual(int(stats.get("best_score", 0) or 0), 100)


if __name__ == "__main__":
    unittest.main()
