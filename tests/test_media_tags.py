import unittest

from app.media_tags import MEDIA_TAG_GROUP_ORDER, media_tag_labels, parse_media_tags


class MediaTagGroupOrderTest(unittest.TestCase):
    def test_new_groups_follow_audio_and_keep_release_convention(self):
        self.assertEqual(
            MEDIA_TAG_GROUP_ORDER,
            ("resolution", "source", "dynamic_range", "video", "audio", "language", "subtitle"),
        )


class MediaTagLanguageSubtitleTest(unittest.TestCase):
    def test_guoyu_zhongzi_phrase_splits_into_language_and_subtitle(self):
        parsed = parse_media_tags(
            "Show.S01E01.2160p.WEB-DL.DV.HEVC.DDP5.1.国语中字-CMCT.mkv"
        )
        self.assertEqual(parsed["groups"]["language"], ["国语"])
        self.assertEqual(parsed["groups"]["subtitle"], ["中字"])

    def test_yueyu_zhongzi_and_bilingual_subtitle_phrases(self):
        self.assertEqual(
            media_tag_labels("片名.2024.1080p.BluRay.x264.DTS-HD.MA.5.1.粤语中字.mkv"),
            ["1080p", "BluRay", "H.264", "DTS-HD MA 5.1", "粤语", "中字"],
        )
        self.assertEqual(
            media_tag_labels("片名.2024.2160p.WEB-DL.HEVC.DDP5.1.双语字幕.mkv"),
            ["2160p", "WEB-DL", "HEVC", "DDP 5.1", "双语字幕"],
        )

    def test_guo_yue_bilingual_and_taipei_dub_language_tags(self):
        self.assertEqual(
            media_tag_labels("片名.2024.1080p.WEB-DL.x264.AAC.国粤双语.mkv")[-1],
            "双语",
        )
        self.assertEqual(
            media_tag_labels("片名.2024.1080p.WEB-DL.x264.AAC.台配国语.mkv")[-1],
            "台配",
        )

    def test_combined_chinese_subtitle_markers_stay_whole(self):
        self.assertEqual(
            media_tag_labels("片名.2024.1080p.WEB-DL.x264.简中英字.mkv")[-1],
            "简中英字",
        )
        self.assertEqual(
            media_tag_labels("片名.2024.1080p.WEB-DL.x264.内封中字.mkv")[-1],
            "内封中字",
        )

    def test_language_words_inside_real_titles_are_not_tagged(self):
        self.assertEqual(media_tag_labels("我的英语老师.2024.1080p.mkv"), ["1080p"])
        self.assertEqual(media_tag_labels("双语教师.2024.WEB-DL.mkv"), ["WEB-DL"])

    def test_enabled_groups_filter_new_tags(self):
        labels = media_tag_labels(
            "Show.2024.1080p.WEB-DL.国语中字.mkv",
            {"language", "subtitle"},
        )
        self.assertEqual(labels, ["国语", "中字"])


class MediaTagAudioChannelTest(unittest.TestCase):
    def test_10bit_is_not_mistaken_for_a_1_0_channel(self):
        self.assertEqual(
            media_tag_labels("Another.2023.4K.WEBRip.HEVC.10bit.AAC.国粤双语.mkv"),
            ["2160p", "WEBRip", "HEVC", "10bit", "AAC", "双语"],
        )
        self.assertEqual(
            media_tag_labels("Movie.2024.1080p.x265.hi10p.AAC.mkv"),
            ["1080p", "HEVC", "10bit", "AAC"],
        )

    def test_real_channel_numbers_still_attach_to_audio(self):
        self.assertEqual(
            media_tag_labels("Movie.2024.1080p.WEB-DL.x264.DDP5.1.mkv"),
            ["1080p", "WEB-DL", "H.264", "DDP 5.1"],
        )
        self.assertEqual(
            media_tag_labels("Movie.2024.1080p.BluRay.TrueHD.7.1.mkv")[-1],
            "TrueHD 7.1",
        )


if __name__ == "__main__":
    unittest.main()
