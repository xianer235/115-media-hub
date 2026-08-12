const TAB_HASH_KEY = 'tab';
const TAB_OWNED_PARAMS = Object.freeze({
    scraper: ['provider', 'path', 'cid'],
});

function toHashParams(hashValue) {
    const raw = String(hashValue || '').trim();
    const stripped = raw.startsWith('#') ? raw.slice(1) : raw;
    return new URLSearchParams(stripped);
}

export function readTabFromHash(tabMeta, hashValue = window.location.hash) {
    const params = toHashParams(hashValue);
    const candidate = String(params.get(TAB_HASH_KEY) || '').trim().toLowerCase();
    if (!candidate) return '';
    return tabMeta && tabMeta[candidate] ? candidate : '';
}

export function buildHashWithTab(tab, hashValue = window.location.hash) {
    const normalizedTab = String(tab || '').trim().toLowerCase();
    const params = toHashParams(hashValue);
    for (const [owner, keys] of Object.entries(TAB_OWNED_PARAMS)) {
        if (owner === normalizedTab) continue;
        keys.forEach(key => params.delete(key));
    }
    params.set(TAB_HASH_KEY, normalizedTab);
    return `#${params.toString()}`;
}
