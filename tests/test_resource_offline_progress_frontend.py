import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JOB_MODAL_PATH = ROOT / "static/js/modules/resource/job-modal.js"
CSS_PATH = ROOT / "static/css/index.css"


class ResourceOfflineProgressFrontendTest(unittest.TestCase):
    def test_job_modal_renders_offline_progress_only_when_in_progress(self):
        source = JOB_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn("function renderOfflineJobProgressRow(job)", source)
        self.assertIn("function getOfflineJobProgress(job = {})", source)
        self.assertIn("['magnet', 'ed2k'].includes(linkType)", source)
        self.assertIn("!== 'submitted'", source)
        self.assertIn("extra.offline_percent", source)
        self.assertIn("resource-job-offline-progress", source)
        self.assertIn("${renderOfflineJobProgressRow(job)}", source)

    def test_offline_progress_styles_cover_day_and_night_themes(self):
        css = CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".resource-job-offline-progress-track", css)
        self.assertIn(".resource-job-offline-progress-bar", css)
        self.assertIn(".resource-job-offline-progress-text", css)
        self.assertIn("html.theme-day .resource-job-offline-progress-track", css)
        self.assertIn("html.theme-day .resource-job-offline-progress-text", css)


if __name__ == "__main__":
    unittest.main()
