import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routes.resource import (  # noqa: E402
    _compact_resource_browser_entries,
    _compact_resource_browser_entry,
)


class ResourceBrowseCompactTest(unittest.TestCase):
    def test_compact_keeps_modified_at_when_present(self):
        entry = _compact_resource_browser_entry({
            "id": "1",
            "name": "a.mkv",
            "is_dir": False,
            "size": 1024,
            "modified_at": "2026-08-18 12:00",
        })
        self.assertEqual(entry["size"], 1024)
        self.assertEqual(entry["modified_at"], "2026-08-18 12:00")

    def test_compact_drops_modified_at_when_absent(self):
        entry = _compact_resource_browser_entry({
            "id": "1",
            "name": "a.mkv",
            "is_dir": False,
            "size": 1024,
        })
        self.assertNotIn("modified_at", entry)

    def test_compact_accepts_provider_time_aliases(self):
        for key in ("last_modified", "updated_at", "create_time", "file_time", "time"):
            entry = _compact_resource_browser_entry({
                "id": "1",
                "name": "a",
                "is_dir": True,
                key: "2026-08-18 12:00",
            })
            self.assertEqual(entry.get("modified_at"), "2026-08-18 12:00")

    def test_compact_share_entries_keep_modified_at(self):
        entries = _compact_resource_browser_entries([
            {
                "id": "1",
                "name": "a.mkv",
                "is_dir": False,
                "size": 2048,
                "parent_id": "0",
                "modified_at": "1724000000",
            }
        ], include_share_fields=True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["modified_at"], "1724000000")
        self.assertEqual(entries[0]["parent_id"], "0")


if __name__ == "__main__":
    unittest.main()
