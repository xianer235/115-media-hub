import unittest
from unittest import mock

from app.resource_tg import fetch_telegram_channel_post_samples


def build_post(channel_id: str, post_id: int, published_at: str) -> dict:
    return {
        "source_type": "tg",
        "source_name": channel_id,
        "channel_name": channel_id,
        "title": f"资源 {post_id}",
        "normalized_title": f"资源 {post_id}",
        "raw_text": f"资源 {post_id}",
        "link_url": f"https://pan.example.com/s/{post_id}",
        "link_type": "link",
        "message_url": f"https://t.me/{channel_id}/{post_id}",
        "quality": "",
        "year": "",
        "published_at": published_at,
        "extra": {
            "cover_url": "",
            "source_post_id": f"{channel_id}/{post_id}",
            "source_url": f"https://t.me/s/{channel_id}",
            "all_links": [f"https://pan.example.com/s/{post_id}"],
        },
    }


class ResourceChannelSyncSamplesTest(unittest.TestCase):
    def test_samples_keep_newest_when_first_page_has_more_than_target(self):
        page_posts = [
            build_post("channel", post_id, f"2026-08-03T00:{post_id - 100:02d}:00+00:00")
            for post_id in range(101, 121)
        ]
        page = {
            "posts": page_posts,
            "next_before": "101",
            "has_more": True,
            "matched_count": len(page_posts),
        }

        with mock.patch(
            "app.resource_tg.fetch_telegram_channel_posts_page",
            return_value=page,
        ) as fetch_page:
            result = fetch_telegram_channel_post_samples(
                {},
                {"channel_id": "channel", "name": "频道"},
                sample_size=10,
                page_size=20,
                max_pages=6,
            )

        returned_ids = [post["extra"]["source_post_id"] for post in result["posts"]]
        self.assertEqual(returned_ids[0], "channel/120")
        self.assertEqual(set(returned_ids), {f"channel/{post_id}" for post_id in range(111, 121)})
        fetch_page.assert_called_once()

    def test_samples_do_not_dedupe_by_link_across_different_messages(self):
        page_posts = [
            build_post("channel", post_id, f"2026-08-03T00:{post_id - 100:02d}:00+00:00")
            for post_id in range(101, 121)
        ]
        page_posts[0]["link_url"] = page_posts[1]["link_url"]
        page = {
            "posts": page_posts,
            "next_before": "101",
            "has_more": True,
            "matched_count": len(page_posts),
        }

        with mock.patch(
            "app.resource_tg.fetch_telegram_channel_posts_page",
            return_value=page,
        ):
            result = fetch_telegram_channel_post_samples(
                {},
                {"channel_id": "channel", "name": "频道"},
                sample_size=10,
                page_size=20,
                max_pages=6,
            )

        returned_ids = [post["extra"]["source_post_id"] for post in result["posts"]]
        self.assertEqual(len(returned_ids), 10)
        self.assertIn("channel/120", returned_ids)


if __name__ == "__main__":
    unittest.main()
