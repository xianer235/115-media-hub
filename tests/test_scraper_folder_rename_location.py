import contextlib
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from app import db
from app.services import monitor_changes
from app.services import scraper as scraper_service


class ScraperFolderRenameLocationTest(unittest.TestCase):
    """二级文件夹重命名后必须仍位于其原父目录内（根/A/B -> 根/A/新名）。"""

    def _build_payload(self, entry, base_cid, base_path):
        return {
            "provider": "115",
            "base_cid": base_cid,
            "base_path": base_path,
            "entries": [entry],
            "tmdb": {
                "tmdb_id": 1,
                "id": 1,
                "title": "新片名",
                "original_title": "New Title",
                "year": 2024,
                "tmdb_media_type": "movie",
                "media_type": "movie",
            },
            "options": {
                "file_name_mode": "standard",
                "rename_selected_folders": True,
                "organize_into_media_folder": True,
                "organize_inside_source_folder": False,
                "include_tmdb_id": False,
                "use_season_subfolder": False,
                "preserve_file_info": False,
            },
        }

    def _patch_plan_io(self):
        return [
            mock.patch.object(scraper_service, "_require_provider_cookie", return_value="cookie"),
            mock.patch.object(scraper_service, "_require_scraper_operation"),
            mock.patch.object(scraper_service, "get_config", return_value={"tmdb_language": "zh-CN"}),
            mock.patch.object(scraper_service, "_expand_selected_scraper_entries", return_value=([], [])),
            mock.patch.object(scraper_service, "_target_name_exists", return_value=False),
            mock.patch.object(scraper_service, "_walk_existing_folder", return_value=("", False)),
            mock.patch.object(scraper_service, "_collect_scraper_action_warning", return_value=""),
            mock.patch.object(scraper_service, "_resolve_scraper_selected_paths", side_effect=lambda _p, items: items),
        ]

    def test_second_level_folder_rename_stays_inside_parent(self):
        entry = {
            "id": "cid_B",
            "name": "B",
            "is_dir": True,
            "parent_id": "cid_A",
            "parent_path": "A",
            "path": "A/B",
            "size": 0,
        }
        payload = self._build_payload(entry, base_cid="cid_A", base_path="A")
        with contextlib.ExitStack() as stack:
            for patcher in self._patch_plan_io():
                stack.enter_context(patcher)
            plan = scraper_service.build_scraper_rename_plan(payload)

        folder_actions = [action for action in plan["actions"] if action.get("is_dir")]
        self.assertEqual(len(folder_actions), 1)
        folder = folder_actions[0]
        self.assertEqual(folder["old_parent_id"], "cid_A")
        self.assertEqual(folder["new_parent_id"], "cid_A")
        self.assertEqual(folder["old_path"], "A/B")
        self.assertEqual(folder["new_path"], "A/新片名 (2024)")

    def test_first_level_folder_rename_stays_under_root(self):
        entry = {
            "id": "cid_A",
            "name": "A",
            "is_dir": True,
            "parent_id": "0",
            "parent_path": "",
            "path": "A",
            "size": 0,
        }
        payload = self._build_payload(entry, base_cid="0", base_path="")
        with contextlib.ExitStack() as stack:
            for patcher in self._patch_plan_io():
                stack.enter_context(patcher)
            plan = scraper_service.build_scraper_rename_plan(payload)

        folder_actions = [action for action in plan["actions"] if action.get("is_dir")]
        self.assertEqual(len(folder_actions), 1)
        folder = folder_actions[0]
        self.assertEqual(folder["old_parent_id"], "0")
        self.assertEqual(folder["new_parent_id"], "0")
        self.assertEqual(folder["new_path"], "新片名 (2024)")

    def test_deeper_folder_files_stay_inside_selected_folder_parent(self):
        """在根目录选中库文件夹被拆分为二级条目时，文件仍整理到“二级的父目录/新片名”。

        用户场景：根/一级/二级，二级重命名后内容必须仍在“一级/新片名”，
        而不是被放到根目录下与一级同级。
        """
        folder_entry = {
            "id": "cid_B",
            "name": "B",
            "is_dir": True,
            "parent_id": "cid_A",
            "parent_path": "一级",
            "path": "一级/B",
            "size": 0,
        }
        file_entry = {
            "id": "f1",
            "name": "B.mkv",
            "is_dir": False,
            "parent_id": "cid_B",
            "parent_path": "一级/B",
            "path": "一级/B/B.mkv",
            "size": 1024,
        }
        payload = self._build_payload(folder_entry, base_cid="0", base_path="")
        with contextlib.ExitStack() as stack:
            for patcher in self._patch_plan_io():
                stack.enter_context(patcher)
            with mock.patch.object(
                scraper_service,
                "_expand_selected_scraper_entries",
                return_value=([file_entry], []),
            ):
                plan = scraper_service.build_scraper_rename_plan(payload)

        file_actions = [action for action in plan["actions"] if not action.get("is_dir")]
        self.assertEqual(len(file_actions), 1)
        file_action = file_actions[0]
        self.assertEqual(file_action["target_parent_path"], "一级/新片名 (2024)")
        self.assertEqual(file_action["new_path"], "一级/新片名 (2024)/新片名 (2024).mkv")
        self.assertEqual([row for row in plan["unchanged_rows"] if not row.get("is_dir")], [])

    def test_folder_rename_only_keeps_standard_file_as_passive_row(self):
        """文件已是标准名、唯一变化是外层文件夹改名时，不再生成文件动作。"""
        folder_entry = {
            "id": "cid_B",
            "name": "B",
            "is_dir": True,
            "parent_id": "cid_A",
            "parent_path": "一级",
            "path": "一级/B",
            "size": 0,
        }
        file_entry = {
            "id": "f1",
            "name": "新片名 (2024).mkv",
            "is_dir": False,
            "parent_id": "cid_B",
            "parent_path": "一级/B",
            "path": "一级/B/新片名 (2024).mkv",
            "size": 1024,
        }
        payload = self._build_payload(folder_entry, base_cid="0", base_path="")
        with contextlib.ExitStack() as stack:
            for patcher in self._patch_plan_io():
                stack.enter_context(patcher)
            with mock.patch.object(
                scraper_service,
                "_expand_selected_scraper_entries",
                return_value=([file_entry], []),
            ):
                plan = scraper_service.build_scraper_rename_plan(payload)

        self.assertEqual(len([action for action in plan["actions"] if action.get("is_dir")]), 1)
        self.assertEqual([action for action in plan["actions"] if not action.get("is_dir")], [])
        passive = [row for row in plan["unchanged_rows"] if not row.get("is_dir")]
        self.assertEqual(len(passive), 1)
        self.assertEqual(passive[0]["new_path"], "一级/新片名 (2024)/新片名 (2024).mkv")
        self.assertIn("随文件夹重命名", passive[0]["note"])
        self.assertEqual(plan["unchanged_count"], 1)

    def test_folder_rename_keeps_season_subfolder_file_passive(self):
        """剧集文件已在 Season 子目录且文件名标准，文件夹改名后仍只需一次改名。"""
        folder_entry = {
            "id": "cid_B",
            "name": "剧集B",
            "is_dir": True,
            "parent_id": "cid_A",
            "parent_path": "一级",
            "path": "一级/剧集B",
            "size": 0,
        }
        file_entry = {
            "id": "f1",
            "name": "新片名 (2026) - S01E01.mkv",
            "is_dir": False,
            "parent_id": "cid_B",
            "parent_path": "一级/剧集B/Season 01",
            "path": "一级/剧集B/Season 01/新片名 (2026) - S01E01.mkv",
            "size": 1024,
        }
        payload = {
            "provider": "115",
            "base_cid": "0",
            "base_path": "",
            "entries": [folder_entry],
            "tmdb": {
                "tmdb_id": 2,
                "id": 2,
                "title": "新片名",
                "original_title": "New Title",
                "year": 2026,
                "tmdb_media_type": "tv",
                "media_type": "tv",
                "tmdb_total_episodes": 10,
                "tmdb_total_seasons": 1,
                "tmdb_season_episode_map": {"1": 10},
                "tmdb_episode_mode": "seasonal",
            },
            "options": {
                "file_name_mode": "standard",
                "rename_selected_folders": True,
                "organize_into_media_folder": True,
                "organize_inside_source_folder": False,
                "include_tmdb_id": False,
                "use_season_subfolder": True,
                "preserve_file_info": False,
                "season": 1,
                "episode_mode": "auto",
            },
        }
        with contextlib.ExitStack() as stack:
            for patcher in self._patch_plan_io():
                stack.enter_context(patcher)
            with mock.patch.object(
                scraper_service,
                "_expand_selected_scraper_entries",
                return_value=([file_entry], []),
            ):
                plan = scraper_service.build_scraper_rename_plan(payload)

        self.assertEqual(len([action for action in plan["actions"] if action.get("is_dir")]), 1)
        self.assertEqual([action for action in plan["actions"] if not action.get("is_dir")], [])
        passive = [row for row in plan["unchanged_rows"] if not row.get("is_dir")]
        self.assertEqual(len(passive), 1)
        self.assertEqual(passive[0]["new_path"], "一级/新片名 (2026)/Season 01/新片名 (2026) - S01E01.mkv")
        self.assertIn("随文件夹重命名", passive[0]["note"])


class ScraperFolderRenameExecutionTest(unittest.TestCase):
    """执行层：文件动作目标父目录为空时，从挂载根用完整挂载路径建目录。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "data.db")
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = self.db_path
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    def test_file_action_ensures_full_parent_path_from_mount_root(self):
        plan = {
            "base_cid": "0",
            "base_path": "",
            "actions": [
                {
                    "action_index": 1,
                    "entry_id": "cid_B",
                    "is_dir": True,
                    "old_parent_id": "cid_A",
                    "old_name": "B",
                    "old_path": "一级/B",
                    "new_parent_id": "cid_A",
                    "new_name": "新片名 (2024)",
                    "new_path": "一级/新片名 (2024)",
                    "target_parent_path": "",
                    "file_size": 0,
                    "remote_modified": "",
                    "ready": True,
                },
                {
                    "action_index": 2,
                    "entry_id": "f1",
                    "is_dir": False,
                    "old_parent_id": "cid_B",
                    "old_name": "B.mkv",
                    "old_path": "一级/B/B.mkv",
                    "new_parent_id": "",
                    "new_name": "新片名 (2024).mkv",
                    "new_path": "一级/新片名 (2024)/新片名 (2024).mkv",
                    "target_parent_path": "一级/新片名 (2024)",
                    "file_size": 1024,
                    "remote_modified": "",
                    "ready": True,
                },
            ],
        }
        job_id = scraper_service._insert_scraper_job("115", plan, {"base_path": ""}, {})
        ensure_calls = []
        with (
            mock.patch.object(scraper_service, "get_config", return_value={"monitor_tasks": [], "mount_points": []}),
            mock.patch.object(scraper_service, "_require_scraper_operation"),
            mock.patch.object(scraper_service, "_require_provider_cookie", return_value="cookie"),
            mock.patch.object(scraper_service, "_target_name_exists", return_value=False),
            mock.patch.object(
                scraper_service,
                "_ensure_folder_from_base",
                side_effect=lambda *args: ensure_calls.append(args) or "cid_target",
            ),
            mock.patch.object(scraper_service, "_rename_provider_entries", return_value={"state": True}),
            mock.patch.object(scraper_service, "_move_provider_entries", return_value={"state": True}),
            mock.patch.object(scraper_service, "_invalidate_provider_parent"),
            mock.patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper_service.run_scraper_job(job_id)

        self.assertIn(
            ("115", "cookie", "0", "一级/新片名 (2024)"),
            [tuple(call) for call in ensure_calls],
        )


class ScraperBatchRenameExecutionTest(unittest.TestCase):
    """批量执行器：原地改名合并、移动按目标分组、移动+改名三阶段。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "data.db")
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = self.db_path
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    def _run_job(self, actions, base_path=""):
        job_id = scraper_service._insert_scraper_job("115", {"base_path": base_path, "actions": actions}, {"base_path": base_path}, {})
        with (
            mock.patch.object(scraper_service, "get_config", return_value={"monitor_tasks": [], "mount_points": []}),
            mock.patch.object(scraper_service, "_require_scraper_operation"),
            mock.patch.object(scraper_service, "_require_provider_cookie", return_value="cookie"),
            mock.patch.object(scraper_service, "_target_name_exists", return_value=False),
            mock.patch.object(scraper_service, "_ensure_folder_from_base", return_value="target-cid"),
            mock.patch.object(scraper_service, "_invalidate_provider_parent"),
            mock.patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper_service.run_scraper_job(job_id)
        with sqlite3.connect(self.db_path) as conn:
            statuses = dict(conn.execute("SELECT entry_id, status FROM scraper_job_actions").fetchall())
            job_status = conn.execute("SELECT status FROM scraper_jobs WHERE id = ?", (job_id,)).fetchone()[0]
        return statuses, job_status

    def test_rename_only_actions_merged_into_one_batch_request(self):
        actions = [
            {
                "action_index": i,
                "entry_id": f"f{i}",
                "is_dir": False,
                "old_parent_id": "p1",
                "old_name": f"旧{i}.mkv",
                "old_path": f"影视/旧{i}.mkv",
                "new_parent_id": "p1",
                "new_name": f"新{i}.mkv",
                "new_path": f"影视/新{i}.mkv",
                "target_parent_path": "影视",
                "file_size": 1,
                "remote_modified": "",
                "ready": True,
            }
            for i in range(1, 4)
        ]
        captured = {}

        def fake_rename(provider, cookie, renames, parent_id=""):
            captured["renames"] = dict(renames)
            captured["parent_id"] = parent_id
            return {"state": True}

        with mock.patch.object(scraper_service, "_rename_provider_entries", side_effect=fake_rename):
            statuses, job_status = self._run_job(actions)

        self.assertEqual(captured["parent_id"], "p1")
        self.assertEqual(
            captured["renames"],
            {"f1": "新1.mkv", "f2": "新2.mkv", "f3": "新3.mkv"},
        )
        self.assertEqual(set(statuses.values()), {"completed"})
        self.assertEqual(job_status, "completed")

    def test_move_only_actions_grouped_by_target(self):
        actions = [
            {
                "action_index": i,
                "entry_id": f"f{i}",
                "is_dir": False,
                "old_parent_id": f"src{i}",
                "old_name": f"同名{i}.mkv",
                "old_path": f"src{i}/同名{i}.mkv",
                "new_parent_id": "target-cid",
                "new_name": f"同名{i}.mkv",
                "new_path": f"影视/目标/同名{i}.mkv",
                "target_parent_path": "影视/目标",
                "file_size": 1,
                "remote_modified": "",
                "ready": True,
            }
            for i in range(1, 3)
        ]
        captured = {}

        def fake_move(provider, cookie, ids, target_id, source_id=""):
            captured["ids"] = sorted(ids)
            captured["target_id"] = target_id
            return {"state": True}

        with mock.patch.object(scraper_service, "_move_provider_entries", side_effect=fake_move):
            statuses, job_status = self._run_job(actions)

        self.assertEqual(captured["ids"], ["f1", "f2"])
        self.assertEqual(captured["target_id"], "target-cid")
        self.assertEqual(set(statuses.values()), {"completed"})

    def test_move_rename_uses_temp_then_move_then_final(self):
        action = {
            "action_index": 1,
            "entry_id": "f1",
            "is_dir": False,
            "old_parent_id": "src1",
            "old_name": "旧.mkv",
            "old_path": "影视/旧.mkv",
            "new_parent_id": "target-cid",
            "new_name": "新.mkv",
            "new_path": "影视/目标/新.mkv",
            "target_parent_path": "影视/目标",
            "file_size": 1,
            "remote_modified": "",
            "ready": True,
        }
        rename_calls = []
        move_calls = []

        def fake_rename(provider, cookie, renames, parent_id=""):
            rename_calls.append({"parent_id": parent_id, "renames": dict(renames)})
            return {"state": True}

        def fake_move(provider, cookie, ids, target_id, source_id=""):
            move_calls.append({"ids": ids, "target_id": target_id})
            return {"state": True}

        with mock.patch.object(scraper_service, "_rename_provider_entries", side_effect=fake_rename), mock.patch.object(
            scraper_service, "_move_provider_entries", side_effect=fake_move
        ):
            statuses, job_status = self._run_job([action])

        self.assertEqual(len(rename_calls), 2)
        temp_name = next(iter(rename_calls[0]["renames"].values()))
        self.assertIn(".mediahub-tmp-", temp_name)
        self.assertEqual(rename_calls[1]["renames"], {"f1": "新.mkv"})
        self.assertEqual(rename_calls[1]["parent_id"], "target-cid")
        self.assertEqual(len(move_calls), 1)
        self.assertEqual(move_calls[0]["ids"], ["f1"])
        self.assertEqual(move_calls[0]["target_id"], "target-cid")
        self.assertEqual(statuses, {"f1": "completed"})
        self.assertEqual(job_status, "completed")

    def test_startup_requeue_pending_and_interrupt_running_jobs(self):
        pending_job = scraper_service._insert_scraper_job("115", {"base_path": "", "actions": []}, {}, {})
        running_job = scraper_service._insert_scraper_job("115", {"base_path": "", "actions": []}, {}, {})
        with db.db_connection() as conn:
            conn.execute("UPDATE scraper_jobs SET status = 'pending' WHERE id = ?", (pending_job,))
            conn.execute("UPDATE scraper_jobs SET status = 'running' WHERE id = ?", (running_job,))
            conn.commit()
        submitted = []
        with mock.patch.object(
            scraper_service,
            "submit_scraper_job",
            side_effect=lambda job_id: submitted.append(job_id),
        ):
            result = scraper_service.requeue_scraper_jobs_on_startup()

        self.assertEqual(submitted, [pending_job])
        self.assertEqual(result["pending_requeued"], 1)
        self.assertEqual(result["running_interrupted"], 1)
        with db.db_connection() as conn:
            status = conn.execute("SELECT status FROM scraper_jobs WHERE id = ?", (running_job,)).fetchone()[0]
            self.assertEqual(status, "failed")

    def test_batch_plan_shares_directory_lookups_across_items(self):
        """批量整理多个同父目录条目时，父目录列表只按模式扫一次（共享缓存）。"""
        tree = {
            "0": [{"id": "col", "name": "合集", "is_dir": True}],
            "col": [
                {"id": "dA", "name": "电影A", "is_dir": True},
                {"id": "dB", "name": "电影B", "is_dir": True},
            ],
            "dA": [{"id": "f1", "name": "A.mkv", "is_dir": False, "size": 10, "sha1": "s1", "pc": "p1", "fid": "f1"}],
            "dB": [{"id": "f2", "name": "B.mkv", "is_dir": False, "size": 10, "sha1": "s2", "pc": "p2", "fid": "f2"}],
        }
        calls = []

        def fake_list(provider, cookie, cid, folders_only=False, offset=0, limit=0):
            calls.append((str(cid), bool(folders_only), int(offset or 0)))
            all_entries = tree.get(str(cid), [])
            if limit and limit > 0:
                page = all_entries[int(offset or 0): int(offset or 0) + int(limit)]
                return {
                    "entries": page,
                    "summary": {"folder_count": len([e for e in page if e.get("is_dir")]), "file_count": 0},
                    "entries_complete": False,
                    "count": len(all_entries),
                    "offset": int(offset or 0),
                    "next_offset": int(offset or 0) + len(page),
                    "has_more": int(offset or 0) + len(page) < len(all_entries),
                    "pages_scanned": 1,
                }
            return {"entries": all_entries, "summary": {"folder_count": len(all_entries), "file_count": 0}, "entries_complete": True}

        def make_binding(title):
            return {
                "tmdb_id": 1,
                "id": 1,
                "title": title,
                "original_title": title,
                "year": "2024",
                "tmdb_media_type": "movie",
                "media_type": "movie",
            }

        items = [
            {
                "item_index": i,
                "name": name,
                "entry": {
                    "id": cid,
                    "name": name,
                    "is_dir": True,
                    "parent_id": "col",
                    "parent_path": "合集",
                    "path": f"合集/{name}",
                    "size": 0,
                },
                "tmdb": make_binding(f"片名{i}"),
            }
            for i, (cid, name) in enumerate([("dA", "电影A"), ("dB", "电影B")], start=1)
        ]
        payload = {
            "provider": "115",
            "base_cid": "0",
            "base_path": "",
            "items": items,
            "options": {
                "file_name_mode": "standard",
                "rename_selected_folders": True,
                "use_season_subfolder": False,
                "organize_inside_source_folder": False,
                "include_tmdb_id": False,
            },
        }
        with (
            mock.patch.object(scraper_service, "_require_scraper_operation"),
            mock.patch.object(scraper_service, "_require_provider_cookie", return_value="cookie"),
            mock.patch.object(scraper_service, "get_config", return_value={"tmdb_enabled": True, "tmdb_api_key": "k", "tmdb_language": "zh-CN"}),
            mock.patch.object(scraper_service, "_list_provider_entries_payload", side_effect=fake_list),
            mock.patch.object(scraper_service, "_resolve_batch_tmdb_binding", side_effect=lambda tmdb, cfg: make_binding(tmdb.get("title") or "片名")),
            mock.patch.object(scraper_service, "_collect_scraper_action_warning", return_value=""),
        ):
            plan = scraper_service.build_scraper_batch_plan(payload)

        self.assertGreater(plan["ready_count"], 0)
        col_full = [call for call in calls if call[0] == "col" and call[1] is False]
        col_folders = [call for call in calls if call[0] == "col" and call[1] is True]
        # 两个条目共享缓存：合集列表每种模式只请求一次（无共享会各请求一次）。
        self.assertEqual(len(col_full), 1)
        self.assertEqual(len(col_folders), 1)


if __name__ == "__main__":
    unittest.main()
