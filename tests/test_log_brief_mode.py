import importlib.util
from pathlib import Path
import sys
import types
import unittest


CORE_PATH = Path("/Users/xianer/Documents/code/115-media-hub/app/core.py")


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
    spec = importlib.util.spec_from_file_location("test_core_module_brief_log", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load core.py for tests")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BriefLogModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core = _load_core_module()

    def setUp(self) -> None:
        self.original_log_brief_mode = bool(self.core.LOG_BRIEF_MODE)

    def tearDown(self) -> None:
        self.core.LOG_BRIEF_MODE = self.original_log_brief_mode

    def test_failure_text_should_be_kept_in_brief_mode_even_if_warn_level(self) -> None:
        self.core.LOG_BRIEF_MODE = True
        kept = self.core.should_keep_runtime_log("Webhook 校验失败", "warn")
        self.assertTrue(kept)

    def test_non_failure_warn_should_be_filtered_in_brief_mode(self) -> None:
        self.core.LOG_BRIEF_MODE = True
        kept = self.core.should_keep_runtime_log("Webhook 目录定位已回退父目录", "warn")
        self.assertFalse(kept)

    def test_monitor_read_dir_detail_should_be_filtered_in_brief_mode(self) -> None:
        self.core.LOG_BRIEF_MODE = True
        kept = self.core.should_keep_runtime_log("读取目录: /115/云下载", "info")
        self.assertFalse(kept)

    def test_monitor_summary_should_be_kept_in_brief_mode(self) -> None:
        self.core.LOG_BRIEF_MODE = True
        kept = self.core.should_keep_runtime_log("生成汇总: 新增/更新 3 | 跳过文件 10", "info")
        self.assertTrue(kept)

    def test_task_start_and_end_should_be_kept_in_brief_mode(self) -> None:
        self.core.LOG_BRIEF_MODE = True
        started = self.core.should_keep_runtime_log(
            "━━━━━━━━━━【任务开始 | 云下载 | 手动触发】━━━━━━━━━━",
            "task-divider",
        )
        ended = self.core.should_keep_runtime_log(
            "━━━━━━━━━━【任务结束 | 云下载 | 执行成功】━━━━━━━━━━",
            "task-divider",
        )
        self.assertTrue(started)
        self.assertTrue(ended)

    def test_subscription_candidate_detail_should_be_filtered_in_brief_mode(self) -> None:
        self.core.LOG_BRIEF_MODE = True
        kept = self.core.should_keep_runtime_log("候选资源 #1 为固定分享链接模式，本次强制重新导入", "info")
        self.assertFalse(kept)

    def test_info_lines_are_kept_when_brief_mode_disabled(self) -> None:
        self.core.LOG_BRIEF_MODE = False
        kept = self.core.should_keep_runtime_log("读取目录: /115/云下载", "info")
        self.assertTrue(kept)


if __name__ == "__main__":
    unittest.main()
