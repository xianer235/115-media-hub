const TAB_MODULE_IMPORT_QUERY = (() => {
    try {
        const url = new URL(import.meta.url);
        const version = String(url.searchParams.get('v') || '').trim();
        return version ? `?v=${encodeURIComponent(version)}` : '';
    } catch (e) {
        return '';
    }
})();

function withTabModuleImportQuery(path) {
    const value = String(path || '').trim();
    if (!value || !TAB_MODULE_IMPORT_QUERY || value.includes('?')) return value;
    return `${value}${TAB_MODULE_IMPORT_QUERY}`;
}

export const TAB_MODULE_IMPORT_PATHS = Object.freeze({
    resource: withTabModuleImportQuery('/static/js/modules/tabs/resource.js'),
    subscription: withTabModuleImportQuery('/static/js/modules/tabs/subscription.js'),
    monitor: withTabModuleImportQuery('/static/js/modules/tabs/monitor.js'),
    task: withTabModuleImportQuery('/static/js/modules/tabs/task.js'),
    settings: withTabModuleImportQuery('/static/js/modules/tabs/settings.js'),
    about: withTabModuleImportQuery('/static/js/modules/tabs/about.js'),
});

const TAB_HASH_SYNC_IMPORT_PATH = withTabModuleImportQuery('/static/js/modules/tabs/url-sync.js');

export function createTabModuleContext(deps = {}) {
    return {
        moduleVisitState: deps.moduleVisitState || {},
        refreshResourceState: deps.refreshResourceState,
        refreshSubscriptionState: deps.refreshSubscriptionState,
        refreshMonitorState: deps.refreshMonitorState,
        refreshMainLogs: deps.refreshMainLogs,
        refreshVersionInfo: deps.refreshVersionInfo,
        versionInfo: typeof deps.getVersionInfo === 'function' ? deps.getVersionInfo() : (deps.versionInfo || {}),
        isResourceStateHydrated: typeof deps.isResourceStateHydrated === 'function'
            ? deps.isResourceStateHydrated
            : (() => false),
    };
}

export async function loadTabModule(tab, { tabModuleCache } = {}) {
    const normalized = String(tab || '').trim().toLowerCase();
    if (!normalized || !TAB_MODULE_IMPORT_PATHS[normalized]) return null;
    const cache = tabModuleCache && typeof tabModuleCache === 'object' ? tabModuleCache : {};
    if (cache[normalized]) return cache[normalized];
    try {
        const mod = await import(TAB_MODULE_IMPORT_PATHS[normalized]);
        cache[normalized] = mod;
        return mod;
    } catch (e) {
        return null;
    }
}

async function loadShellTabRouterModule(state = {}) {
    if (state.shellTabRouterPromise) return state.shellTabRouterPromise;
    state.shellTabRouterPromise = import(TAB_HASH_SYNC_IMPORT_PATH).catch(() => null);
    return state.shellTabRouterPromise;
}

export async function readTabFromLocationHash({ state = {}, shellTabMeta = {}, currentHash = '' } = {}) {
    const router = await loadShellTabRouterModule(state);
    if (!router?.readTabFromHash) return '';
    return router.readTabFromHash(shellTabMeta, currentHash);
}

export async function syncLocationHashWithTab(
    tab,
    {
        state = {},
        currentHash = '',
        pathname = '',
        search = '',
        replace = false,
        setHash = null,
        replaceUrl = null,
        onBeforeHashWrite = null,
        onAfterHashWrite = null,
    } = {},
) {
    const router = await loadShellTabRouterModule(state);
    if (!router?.buildHashWithTab) return;
    const nextHash = router.buildHashWithTab(tab, currentHash);
    if (!nextHash || nextHash === currentHash) return;
    if (replace) {
        if (typeof replaceUrl === 'function') {
            replaceUrl(`${pathname}${search}${nextHash}`);
        }
        return;
    }
    if (typeof onBeforeHashWrite === 'function') onBeforeHashWrite();
    if (typeof setHash === 'function') {
        setHash(nextHash);
    } else if (typeof window !== 'undefined') {
        window.location.hash = nextHash;
    }
    if (typeof onAfterHashWrite === 'function') onAfterHashWrite();
}
