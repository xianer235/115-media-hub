let scraperCorePromise = null;

function buildScraperCoreImportUrl() {
    const query = (() => {
        try {
            return new URL(import.meta.url).search || '';
        } catch (e) {
            return '';
        }
    })();
    // core.js 里还要再动态 import 子模块（查重面板），把同一份版本号交给它，
    // 否则子模块会以无参数 URL 请求、被浏览器旧缓存命中。
    try {
        window.__scraperModuleQuery = query;
    } catch (e) {
        /* 忽略：非浏览器环境下没有 window */
    }
    return `/static/js/modules/scraper/core.js${query}`;
}

async function loadScraperCore() {
    if (!scraperCorePromise) {
        scraperCorePromise = import(buildScraperCoreImportUrl()).catch(() => null);
    }
    return scraperCorePromise;
}

export async function ensureTabData(context) {
    const core = await loadScraperCore();
    if (core?.ensureScraperManager) {
        await core.ensureScraperManager({
            firstVisit: !context.moduleVisitState.scraper,
        });
    }
    context.moduleVisitState.scraper = true;
}
