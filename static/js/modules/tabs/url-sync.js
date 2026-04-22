const TAB_HASH_KEY = 'tab';

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
    const params = toHashParams(hashValue);
    params.set(TAB_HASH_KEY, String(tab || '').trim().toLowerCase());
    return `#${params.toString()}`;
}
