import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "static/js/modules/subscription/ui.js"
LINK_TAGS_PATH = ROOT / "static/js/modules/resource/link-tags.js"
TITLE_UTILS_PATH = ROOT / "static/js/modules/app/title-utils.js"
TEMPLATE_PATH = ROOT / "templates/index.html"
SUBSCRIPTION_MODAL_TEMPLATE_PATH = ROOT / "templates/partials/modals/subscription.html"


def run_subscription_ui(expression, provider_meta=None):
    provider_meta = provider_meta or []
    # ui.js 用到的几个状态变量声明在 index.js 里（浏览器中同一全局词法作用域），
    # 单独加载 ui.js 时得先补上，否则引用到缓存的函数会 ReferenceError。
    prelude = (
        "let subscriptionEpisodeViewCache = {};\n"
        "const SUBSCRIPTION_EPISODE_CACHE_TTL_MS = 180000;\n"
        "let subscriptionIntroEpisodeLookupLoading = {};\n"
        "let subscriptionIntroEpisodeLookupFailedAt = {};\n"
    )
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{
  window: {{ providerMeta: {json.dumps(provider_meta, ensure_ascii=False)} }},
  escapeHtml: value => String(value ?? ''),
}};
vm.createContext(context);
vm.runInContext({json.dumps(prelude)}, context);
vm.runInContext(fs.readFileSync({json.dumps(str(LINK_TAGS_PATH))}, 'utf8'), context);
vm.runInContext(fs.readFileSync({json.dumps(str(UI_PATH))}, 'utf8'), context);
const result = vm.runInContext({json.dumps(expression)}, context);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


def run_title_utils(expression):
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{ window: {{}} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(TITLE_UTILS_PATH))}, 'utf8'), context);
const api = context.window.MediaHubTitleUtils;
const result = ({expression});
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


class SubscriptionUiFrontendTest(unittest.TestCase):
    def test_resource_link_tags_load_before_subscription_ui(self):
        html = TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertLess(
            html.index('src="/static/js/modules/resource/link-tags.js'),
            html.index('src="/static/js/modules/subscription/ui.js'),
        )

    def test_title_utils_loads_before_subscription_ui_and_resource_import(self):
        html = TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertLess(
            html.index('src="/static/js/modules/app/title-utils.js'),
            html.index('src="/static/js/modules/subscription/ui.js'),
        )
        self.assertLess(
            html.index('src="/static/js/modules/app/title-utils.js'),
            html.index('src="/static/js/modules/resource/import-modal.js'),
        )

    def test_recommend_folder_name_formats_title_with_year(self):
        result = run_title_utils("""
        ({
            withYear: api.recommendFolderName('沙丘 2', '2024'),
            withoutYear: api.recommendFolderName('沙丘 2', ''),
            yearInTitle: api.recommendFolderName('沙丘 2 2024', '2024'),
            yearInParens: api.recommendFolderName('Your Sky 那片晴空之下 (2026)', '2026'),
            unsafe: api.recommendFolderName('A/B:*?<|C', '2023'),
            magnetStyle: api.recommendFolderName('死侍与金刚狼 2024 1080p WEB-DL 中字', '2024'),
        })
        """)
        self.assertEqual(result["withYear"], "沙丘 2 (2024)")
        self.assertEqual(result["withoutYear"], "沙丘 2")
        self.assertEqual(result["yearInTitle"], "沙丘 2 (2024)")
        self.assertEqual(result["yearInParens"], "Your Sky 那片晴空之下 (2026)")
        self.assertEqual(result["unsafe"], "A B：＊？＜ (2023)")
        self.assertEqual(result["magnetStyle"], "死侍与金刚狼 (2024)")

    def test_title_utils_maps_colon_to_full_width_in_folder_name(self):
        source = TITLE_UTILS_PATH.read_text(encoding="utf-8")
        self.assertIn(".replace(/:/g, '：')", source)

    def test_bind_tmdb_always_replaces_subscription_title(self):
        source = UI_PATH.read_text(encoding="utf-8")
        bind_body = source[source.index("function selectSubscriptionTmdbResult("):source.index("function openSubscriptionTmdbSearchModal(")]
        self.assertNotIn("!String(titleInput.value || '').trim()", bind_body)
        self.assertIn("titleInput.value = String(binding.tmdb_title || target.title || '').trim();", bind_body)
        self.assertIn("yearInput.value = normalizeTmdbYear(binding.tmdb_year || '');", bind_body)

    def test_subscription_folder_modal_prefills_recommended_name(self):
        folders_source = (ROOT / "static/js/modules/subscription/folders.js").read_text(encoding="utf-8")
        self.assertIn("function getSubscriptionRecommendedFolderName(", folders_source)
        self.assertIn("applySubscriptionRecommendedFolderName();", folders_source)
        self.assertIn("window.MediaHubTitleUtils?.recommendFolderName", folders_source)
        html = SUBSCRIPTION_MODAL_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn('id="subscription-folder-recommend-btn"', html)
        self.assertIn('onclick="applySubscriptionRecommendedFolderName()"', html)

    def test_cross_copy_sources_narrowed_to_connected_providers(self):
        # 跨盘引擎支持 115/夸克/阿里互传，但补源只接通了夸克作源。
        # 界面必须只列已接通的源，否则会出现「勾了阿里、后端静默跳过」。
        source = UI_PATH.read_text(encoding="utf-8")
        self.assertIn("const SUBSCRIPTION_CROSS_COPY_SUPPORTED_SOURCES = ['quark'];", source)
        self.assertIn(
            "SUBSCRIPTION_CROSS_COPY_SUPPORTED_SOURCES.includes(String(item?.name || ''))",
            source,
        )
        # 保存和卡片展示也要过滤，防止历史配置里的未接通源被重新写回 / 显示成「补源：阿里云盘」
        self.assertIn(
            ".filter(item => SUBSCRIPTION_CROSS_COPY_SUPPORTED_SOURCES.includes(item));",
            source,
        )
        self.assertIn(
            ".filter(name => name && SUBSCRIPTION_CROSS_COPY_SUPPORTED_SOURCES.includes(name))",
            source,
        )

    def test_cross_copy_source_ui_says_quark_only(self):
        html = SUBSCRIPTION_MODAL_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn("源网盘（当前仅支持夸克）", html)
        source = UI_PATH.read_text(encoding="utf-8")
        self.assertIn("目前跨盘补源只支持从夸克网盘复制资源", source)
        self.assertIn("目前跨盘补源只支持夸克网盘，请勾选夸克作为源网盘", source)

    def test_subscription_provider_badges_use_global_tones(self):
        providers = [
            {"name": "115", "label": "115网盘", "link_type": "115share"},
            {"name": "quark", "label": "夸克网盘", "link_type": "quark"},
            {"name": "aliyun", "label": "阿里云盘", "link_type": "aliyun"},
            {"name": "123pan", "label": "123云盘", "link_type": "123pan"},
            {"name": "tianyi", "label": "天翼云盘", "link_type": "tianyi"},
            {"name": "future", "label": "未来网盘", "link_type": "future"},
        ]
        result = run_subscription_ui(
            "window.providerMeta.map(provider => getSubscriptionProviderBadgeMeta(provider.name))",
            providers,
        )
        self.assertEqual(
            [item["className"] for item in result],
            [
                "resource-link-tag resource-link-tag--blue",
                "resource-link-tag resource-link-tag--violet",
                "resource-link-tag resource-link-tag--orange",
                "resource-link-tag resource-link-tag--emerald",
                "resource-link-tag resource-link-tag--rose",
                "resource-link-tag resource-link-tag--neutral",
            ],
        )
        self.assertEqual(result[1]["label"], "夸克网盘")

    def test_subscription_last_hit_badge_uses_calendar_date_boundaries(self):
        now = "2026-08-31T12:00:00"
        values = [
            "2026-08-31T00:01:00",
            "2026-08-30T23:59:00",
            "2026-08-29T00:00:00",
            "2026-08-02T00:00:00",
            "2026-08-01T00:00:00",
            "2025-12-31T00:00:00",
            "2026-09-01T00:00:00",
        ]
        result = run_subscription_ui(
            f"{json.dumps(values)}.map(value => formatSubscriptionLastHitAge(value, {json.dumps(now)}))"
        )
        self.assertEqual(result, ["今天", "昨天", "2天前", "29天前", "08-01", "2025-12-31", "09-01"])

    def test_subscription_last_hit_badge_handles_missing_and_invalid_dates(self):
        result = run_subscription_ui(
            "({ none: buildSubscriptionLastHitBadge({}), unknown: buildSubscriptionLastHitBadge({ matched_resource_title: '仙逆' }), invalid: buildSubscriptionLastHitBadge({ last_success_at: 'bad' }) })"
        )
        self.assertIn("尚未命中", result["none"])
        self.assertIn("命中日期未知", result["unknown"])
        self.assertIn("尚未命中", result["invalid"])

    def test_subscription_last_hit_badge_and_detail_use_same_timestamp(self):
        task = {
            "matched_resource_title": "仙逆",
            "last_success_at": "2026-08-02T04:34:25",
        }
        result = run_subscription_ui(
            f"({{ badge: buildSubscriptionLastHitBadge({json.dumps(task, ensure_ascii=False)}), detail: buildSubscriptionLatestMatchText({json.dumps(task, ensure_ascii=False)}) }})"
        )
        self.assertIn("最近命中", result["badge"])
        self.assertIn("仙逆", result["detail"])
        self.assertIn("2026-08-02 04:34", result["detail"])

    def test_subscription_last_hit_badge_shows_saved_episode(self):
        task = {
            "name": "仙逆",
            "media_type": "tv",
            "last_success_at": "2026-08-02T04:34:25",
            "last_episode": 42,
        }
        html = run_subscription_ui(
            f"buildSubscriptionLastHitBadge({json.dumps(task, ensure_ascii=False)})"
        )
        self.assertIn("最近命中", html)
        self.assertIn("已到 E42", html)
        self.assertIn("资源库里已保存到 E42", html)

    def test_subscription_last_hit_badge_prefers_higher_scanned_episode(self):
        task = {
            "name": "仙逆",
            "media_type": "tv",
            "last_success_at": "2026-08-02T04:34:25",
            "last_episode": 42,
            "stats": {"existing_episode_max": 43},
        }
        html = run_subscription_ui(
            f"buildSubscriptionLastHitBadge({json.dumps(task, ensure_ascii=False)})"
        )
        self.assertIn("已到 E43", html)

    def test_subscription_last_hit_badge_keeps_movie_clean(self):
        task = {
            "name": "流浪地球",
            "media_type": "movie",
            "last_success_at": "2026-08-02T04:34:25",
            "last_episode": 0,
        }
        html = run_subscription_ui(
            f"buildSubscriptionLastHitBadge({json.dumps(task, ensure_ascii=False)})"
        )
        self.assertIn("最近命中", html)
        self.assertNotIn("已到", html)

    def test_subscription_last_hit_badge_without_episode_unchanged(self):
        html = run_subscription_ui("buildSubscriptionLastHitBadge({ media_type: 'tv' })")
        self.assertIn("尚未命中", html)
        self.assertNotIn("已到", html)


    def test_subscription_season_badge_shows_padded_season_for_tv(self):
        html = run_subscription_ui("buildSubscriptionTaskSeasonBadge({ media_type: 'tv', season: 3 })")
        self.assertIn("S03", html)
        self.assertIn("第3季", html)
        # 必须是 sky 系：日间主题有 text-sky-200 深色覆盖，cyan 在浅色卡片上会发白
        self.assertIn("text-sky-200", html)

    def test_subscription_season_badge_uses_all_seasons_label(self):
        html = run_subscription_ui(
            "buildSubscriptionTaskSeasonBadge({ media_type: 'tv', season: 2, multi_season_mode: true })"
        )
        self.assertIn("全季", html)
        self.assertNotIn("S02", html)

    def test_subscription_season_badge_hidden_for_movie(self):
        self.assertEqual(
            run_subscription_ui("buildSubscriptionTaskSeasonBadge({ media_type: 'movie', season: 1 })"),
            "",
        )

    def test_subscription_task_intro_mentions_season(self):
        # buildSubscriptionTaskIntro 还依赖 resource 模块的工具函数，这里只做源码断言，
        # 避免为了一个文案把整个前端依赖树搬进 vm。
        source = UI_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "const seasonText = !isTv ? '' : (multiSeasonMode ? '全季' : (seasonNo > 0 ? `第${seasonNo}季` : ''));",
            source,
        )
        self.assertIn("《${titleText}》${seasonText}保存到", source)

    def test_subscription_task_card_renders_season_badge_after_title(self):
        source = UI_PATH.read_text(encoding="utf-8")
        self.assertIn("function buildSubscriptionTaskSeasonBadge(", source)
        self.assertIn("const seasonBadgeHtml = seasonLabel &&", source)
        self.assertLess(
            source.index("${escapeHtml(displayTitle)}"),
            source.index("${seasonBadgeHtml}"),
        )


if __name__ == "__main__":
    unittest.main()
