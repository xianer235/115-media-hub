import unittest
from datetime import datetime
from pathlib import Path


from app.core import (
    compute_subscription_cooldown_until,
    compute_subscription_next_due_ts,
    is_subscription_task_finished,
    normalize_subscription_hit_cooldown_hours,
    normalize_subscription_hit_cooldown_mode,
    normalize_subscription_task,
    normalize_tmdb_air_date,
    normalize_tmdb_status,
)


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "static/js/modules/subscription/ui.js"
MODAL_PATH = ROOT / "templates/partials/modals/subscription.html"


def ts(value: str) -> float:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp()


def fmt(value: float) -> str:
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M") if value else ""


class TestNormalizeCooldownFields(unittest.TestCase):
    def test_mode_default_and_invalid(self):
        self.assertEqual(normalize_subscription_hit_cooldown_mode(None), "auto")
        self.assertEqual(normalize_subscription_hit_cooldown_mode(""), "auto")
        self.assertEqual(normalize_subscription_hit_cooldown_mode("MANUAL"), "manual")
        self.assertEqual(normalize_subscription_hit_cooldown_mode("off"), "off")
        self.assertEqual(normalize_subscription_hit_cooldown_mode("bogus"), "auto")
        self.assertEqual(normalize_subscription_hit_cooldown_mode("bogus", fallback="off"), "off")

    def test_hours_clamped(self):
        self.assertEqual(normalize_subscription_hit_cooldown_hours(0), 0)
        self.assertEqual(normalize_subscription_hit_cooldown_hours(-5), 0)
        self.assertEqual(normalize_subscription_hit_cooldown_hours("24"), 24)
        self.assertEqual(normalize_subscription_hit_cooldown_hours(2.6), 3)
        self.assertEqual(normalize_subscription_hit_cooldown_hours(10 ** 6), 336)
        self.assertEqual(normalize_subscription_hit_cooldown_hours("abc"), 0)
        self.assertEqual(normalize_subscription_hit_cooldown_hours(float("inf")), 0)
        self.assertEqual(normalize_subscription_hit_cooldown_hours(float("nan")), 0)

    def test_air_date_and_status(self):
        self.assertEqual(normalize_tmdb_air_date("2026-10-27"), "2026-10-27")
        self.assertEqual(normalize_tmdb_air_date("2026-13-01"), "")
        self.assertEqual(normalize_tmdb_air_date(""), "")
        self.assertEqual(normalize_tmdb_air_date(None), "")
        self.assertEqual(normalize_tmdb_status("Ended"), "Ended")
        self.assertEqual(normalize_tmdb_status("Returning Series"), "Returning Series")
        self.assertEqual(normalize_tmdb_status("weird"), "")


class TestTaskNormalization(unittest.TestCase):
    def _tv_task(self, **extra):
        payload = {
            "name": "测试剧",
            "title": "测试剧",
            "savepath": "剧集",
            "media_type": "tv",
            "tmdb_id": 123,
            "tmdb_media_type": "tv",
        }
        payload.update(extra)
        return normalize_subscription_task(payload)

    def test_cooldown_fields_survive_normalization(self):
        task = self._tv_task(hit_cooldown_mode="manual", hit_cooldown_hours=30)
        self.assertEqual(task["hit_cooldown_mode"], "manual")
        self.assertEqual(task["hit_cooldown_hours"], 30)

    def test_cooldown_defaults_when_absent(self):
        task = self._tv_task()
        self.assertEqual(task["hit_cooldown_mode"], "auto")
        self.assertEqual(task["hit_cooldown_hours"], 0)

    def test_schedule_fields_survive_normalization(self):
        task = self._tv_task(
            tmdb_status="Ended",
            tmdb_next_air_date="2026-11-02",
            tmdb_last_air_date="2026-10-26",
            tmdb_next_episode_number=5,
        )
        self.assertEqual(task["tmdb_status"], "Ended")
        self.assertEqual(task["tmdb_next_air_date"], "2026-11-02")
        self.assertEqual(task["tmdb_last_air_date"], "2026-10-26")
        self.assertEqual(task["tmdb_next_episode_number"], 5)

    def test_movie_drops_schedule_fields(self):
        task = normalize_subscription_task(
            {
                "name": "测试电影",
                "title": "测试电影",
                "savepath": "电影",
                "media_type": "movie",
                "tmdb_id": 456,
                "tmdb_media_type": "movie",
                "tmdb_status": "Ended",
                "tmdb_next_air_date": "2026-11-02",
            }
        )
        self.assertEqual(task["tmdb_status"], "")
        self.assertEqual(task["tmdb_next_air_date"], "")


class TestCooldownUntil(unittest.TestCase):
    HIT = "2026-10-26 20:05:00"

    def _task(self, **extra):
        payload = {"media_type": "tv", "hit_cooldown_mode": "auto"}
        payload.update(extra)
        return payload

    def test_off_mode_returns_zero(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=ts(self.HIT),
            task=self._task(
                hit_cooldown_mode="off",
                tmdb_next_air_date="2026-10-27",
                tmdb_last_air_date="2026-10-26",
            ),
        )
        self.assertEqual(value, 0.0)

    def test_manual_hours(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=ts(self.HIT),
            task=self._task(hit_cooldown_mode="manual", hit_cooldown_hours=6),
        )
        self.assertEqual(fmt(value), "2026-10-27 02:05")

    def test_manual_zero_hours_returns_zero(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=ts(self.HIT),
            task=self._task(hit_cooldown_mode="manual", hit_cooldown_hours=0),
        )
        self.assertEqual(value, 0.0)

    def test_daily_show_keeps_below_one_period(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=ts(self.HIT),
            task=self._task(tmdb_next_air_date="2026-10-27", tmdb_last_air_date="2026-10-26"),
        )
        # 周期 1 天 → 0.85 天 ≈ 20.4 小时，严格早于下一集
        self.assertEqual(fmt(value), "2026-10-27 16:29")

    def test_next_air_date_already_aired_still_cools(self):
        """回归钉：命中那一轮刷新到的 next_episode_to_air 往往就是刚入库的这集。

        日期取「今天」时不能直接当冷却终点（否则终点在过去、冷却永不触发），
        必须退回周期推算。
        """
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=ts(self.HIT),
            task=self._task(tmdb_next_air_date="2026-10-26", tmdb_last_air_date="2026-10-25"),
        )
        self.assertEqual(fmt(value), "2026-10-27 16:29")

    def test_weekly_show(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=ts(self.HIT),
            task=self._task(tmdb_next_air_date="2026-11-02", tmdb_last_air_date="2026-10-26"),
        )
        self.assertEqual(fmt(value), "2026-11-01 18:53")

    def test_long_hiatus_is_capped(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=ts(self.HIT),
            task=self._task(tmdb_next_air_date="2027-01-24", tmdb_last_air_date="2026-10-26"),
        )
        self.assertEqual(fmt(value), "2026-11-02 19:05")

    def test_same_day_double_episode_does_not_cool(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=ts(self.HIT),
            task=self._task(tmdb_next_air_date="2026-10-26", tmdb_last_air_date="2026-10-26"),
        )
        self.assertEqual(value, 0.0)

    def test_no_schedule_data_does_not_cool(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=ts(self.HIT),
            task=self._task(),
        )
        self.assertEqual(value, 0.0)

    def test_never_hit_does_not_cool(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts(self.HIT) + 1,
            last_hit_ts=0.0,
            task=self._task(tmdb_next_air_date="2026-10-27", tmdb_last_air_date="2026-10-26"),
        )
        self.assertEqual(value, 0.0)

    def test_expired_cooldown_returns_zero(self):
        value = compute_subscription_cooldown_until(
            now_ts=ts("2026-12-01 00:00:00"),
            last_hit_ts=ts(self.HIT),
            task=self._task(tmdb_next_air_date="2026-10-27", tmdb_last_air_date="2026-10-26"),
        )
        self.assertEqual(value, 0.0)


class TestNextDue(unittest.TestCase):
    def test_cold_start_runs_immediately(self):
        now = ts("2026-10-26 20:00:00")
        value = compute_subscription_next_due_ts(
            now_ts=now,
            last_run_ts=0.0,
            interval_seconds=7200,
        )
        self.assertEqual(value, now)

    def test_interval_wins_when_later(self):
        now = ts("2026-10-26 20:00:00")
        last_run = now - 3600
        value = compute_subscription_next_due_ts(
            now_ts=now,
            last_run_ts=last_run,
            interval_seconds=7200,
            cooldown_until=now + 60,
        )
        self.assertEqual(value, last_run + 7200)

    def test_cooldown_wins_when_later(self):
        now = ts("2026-10-26 20:00:00")
        cooldown_until = now + 86400
        value = compute_subscription_next_due_ts(
            now_ts=now,
            last_run_ts=now - 7200,
            interval_seconds=7200,
            cooldown_until=cooldown_until,
        )
        self.assertEqual(value, cooldown_until)


class TestFinishedTask(unittest.TestCase):
    def test_only_tmdb_ended_markers_count(self):
        self.assertTrue(is_subscription_task_finished({"media_type": "tv", "tmdb_status": "Ended"}))
        self.assertTrue(is_subscription_task_finished({"media_type": "tv", "tmdb_status": "Canceled"}))
        self.assertFalse(is_subscription_task_finished({"media_type": "tv", "tmdb_status": "Returning Series"}))
        self.assertFalse(is_subscription_task_finished({"media_type": "tv", "tmdb_status": "In Production"}))
        self.assertFalse(is_subscription_task_finished({"media_type": "tv", "tmdb_status": ""}))
        self.assertFalse(is_subscription_task_finished({"media_type": "movie", "tmdb_status": "Ended"}))
        self.assertFalse(is_subscription_task_finished({}))


class TestFrontendWiring(unittest.TestCase):
    def test_modal_exposes_cooldown_controls(self):
        text = MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn('id="subscription_hit_cooldown_mode"', text)
        self.assertIn('id="subscription_hit_cooldown_hours"', text)
        self.assertIn('id="subscription_tmdb_status"', text)
        self.assertIn('id="subscription_tmdb_next_air_date"', text)

    def test_ui_js_round_trips_cooldown_fields(self):
        text = UI_PATH.read_text(encoding="utf-8")
        self.assertIn("hit_cooldown_mode", text)
        self.assertIn("hit_cooldown_hours", text)
        self.assertIn("syncSubscriptionHitCooldownUI", text)
        self.assertIn("isSubscriptionTaskFinished", text)
        self.assertIn("已完结，自动查询已停止", text)
        self.assertIn("tmdb_next_air_date", text)


if __name__ == "__main__":
    unittest.main()
