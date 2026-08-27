const SCRAPER_JOB_ACTIVE_STATUSES = new Set(['pending', 'running', 'rollback_running']);
const SCRAPER_ENTRY_PAGE_LIMIT = 300;

function renderJobPageButtons(page, totalPages, maxVisible = 5) {
    const currentPage = Math.max(1, Number(page || 1) || 1);
    const lastPage = Math.max(1, Number(totalPages || 1) || 1);
    const visibleCount = Math.max(1, Math.min(lastPage, Number(maxVisible || 5) || 5));
    const halfWindow = Math.floor(visibleCount / 2);
    const firstPage = Math.max(1, Math.min(lastPage, currentPage - halfWindow));
    const endPage = Math.min(lastPage, firstPage + visibleCount - 1);
    const startPage = Math.max(1, endPage - visibleCount + 1);
    return Array.from({ length: endPage - startPage + 1 }, (_, index) => {
        const pageNumber = startPage + index;
        return `<button type="button" data-scraper-action="jobs-page-number" data-scraper-job-page="${pageNumber}" class="resource-job-page-button ${pageNumber === currentPage ? 'resource-job-page-button-active' : ''}" ${pageNumber === currentPage ? 'aria-current="page"' : ''}>${pageNumber}</button>`;
    }).join('');
}

function getScraperProviderOptions() {
    const meta = window.providerMeta || [];
    return meta
        .filter(p => p.enabled && p.supports_folder_browse !== false)
        .map(p => ({
            provider: p.name,
            label: p.label,
            configured: true,
            configuredKnown: false,
            operations: buildProviderOperationsFromMeta(p),
        }));
}

const state = {
    initialized: false,
    provider: '115',
    providers: [],
    providersLoaded: false,
    cid: '0',
    trail: [{ id: '0', name: '根目录' }],
    entries: [],
    entryError: '',
    summary: { folder_count: 0, file_count: 0 },
    nextOffset: 0,
    hasMore: false,
    loadingMore: false,
    selected: new Map(),
    entrySort: { key: 'name', direction: 'asc' },
    search: '',
    loading: false,
    navigationBusy: false,
    moveBuffer: null,
    copyBuffer: null,
    activeTool: '',
    identifyBusy: false,
    identifyResult: null,
    identifySelectionKey: '',
    identifyRequestSeq: 0,
    identifyPathSelection: createEmptyIdentifyPathSelection(),
    identifyPathGesture: null,
    tmdb: null,
    manualBusy: false,
    manualResults: [],
    manualMediaTypeTouched: false,
    batchBusy: false,
    batchScan: null,
    batchIdentify: null,
    batchBindings: {},
    batchIncluded: new Set(),
    batchSearchState: {},
    batchSplitMode: 'auto',
    batchPathGesture: null,
    batchPlanContext: null,
    batchError: '',
    batchSelection: [],
    batchPreferencesLoaded: false,
    batchPreferenceProvider: '',
    batchPreferenceSaveTimer: null,
    planBusy: false,
    plan: null,
    planSelections: new Set(),
    planEpisodeOverrides: {},
    planRequestSeq: 0,
    executeBusy: false,
    jobs: [],
    jobsPage: 1,
    jobsPagination: {},
    jobsBusy: false,
    jobsPollTimer: 0,
};

function $(id) {
    return document.getElementById(id);
}

function getFileManager() {
    return window.MediaHubFileManager;
}

function escapeHtml(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(value);
    return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function showToast(message, options = {}) {
    if (typeof window.showToast === 'function') {
        window.showToast(message, options);
        return;
    }
    console.log(message);
}

async function showConfirm(message, options = {}) {
    if (typeof window.showAppConfirm === 'function') {
        return window.showAppConfirm(message, options);
    }
    return window.confirm(message);
}

function normalizeProvider(value) {
    const raw = String(value || '').trim().toLowerCase();
    if (!raw) return '115';
    const known = [
        ...(Array.isArray(state?.providers) ? state.providers : []),
        ...(Array.isArray(window.providerMeta) ? window.providerMeta : []),
    ];
    const matched = known.find(item => {
        const providerName = String(item?.provider || item?.name || '').trim().toLowerCase();
        return providerName === raw;
    });
    return String(matched?.provider || matched?.name || raw).trim();
}

function buildProviderOperationsFromMeta(item = {}) {
    const browseSupported = item?.supports_folder_browse !== false;
    const renameSupported = item?.supports_rename === true;
    const moveSupported = item?.supports_move === true;
    const copySupported = item?.supports_copy === true;
    const deleteSupported = item?.supports_delete === true;
    const scrapeSupported = browseSupported && renameSupported && moveSupported;
    return {
        browse: browseSupported,
        create_folder: browseSupported,
        rename: renameSupported,
        copy: copySupported,
        move: moveSupported,
        delete: deleteSupported,
        scrape: scrapeSupported,
        rollback: scrapeSupported,
    };
}

function getProviderInfo(provider = state.provider) {
    const normalized = normalizeProvider(provider);
    return state.providers.find(item => normalizeProvider(item.provider) === normalized)
        || (window.providerMeta || []).find(item => normalizeProvider(item.name) === normalized)
        || null;
}

function getProviderOperations(provider = state.provider) {
    const normalized = normalizeProvider(provider);
    const info = getProviderInfo(normalized);
    if (info?.operations && typeof info.operations === 'object') return info.operations;
    if (info) return buildProviderOperationsFromMeta(info);
    return { browse: true, create_folder: true, rename: false, copy: false, move: false, delete: false, scrape: false, rollback: false };
}

function supportsProviderOperation(operation, provider = state.provider) {
    return getProviderOperations(provider)?.[operation] === true;
}

function getProviderLabel(provider = state.provider) {
    const normalized = normalizeProvider(provider);
    const p = getProviderInfo(normalized) || getScraperProviderOptions().find(o => normalizeProvider(o.provider) === normalized);
    return p ? (p.label || normalized) : normalized;
}

function isProviderConfigured(provider = state.provider) {
    const normalized = normalizeProvider(provider);
    const item = getProviderInfo(normalized);
    if (item && typeof item.configured === 'boolean') return item.configured;
    return true;
}

function normalizeCid(value) {
    return String(value || '0').trim() || '0';
}

function normalizePath(value) {
    return String(value || '')
        .split(/[\\/]+/)
        .map(part => part.trim())
        .filter(Boolean)
        .join('/');
}

function joinPath(...parts) {
    return normalizePath(parts.join('/'));
}

function currentParentPath() {
    return normalizePath(state.trail.slice(1).map(item => item.name || '').join('/'));
}

function getScraperUrlParams() {
    const raw = String(window.location.hash || '').replace(/^#/, '');
    const params = new URLSearchParams(raw);
    return {
        provider: String(params.get('provider') || '').trim(),
        path: String(params.get('path') || '').trim(),
    };
}

function syncScraperLocationHash() {
    try {
        const raw = String(window.location.hash || '').replace(/^#/, '');
        const params = new URLSearchParams(raw);
        // 只在刮削页写入刮削参数，避免污染其它 tab 的链接。
        if (String(params.get('tab') || '').trim().toLowerCase() !== 'scraper') return;
        params.set('tab', 'scraper');
        params.set('provider', String(state.provider || '115'));
        const path = currentParentPath();
        const hasSearchJump = state.trail.some(item => item.searchJump);
        if (hasSearchJump) params.delete('path');
        else if (path) params.set('path', path);
        else params.delete('path');
        const url = `${window.location.pathname}${window.location.search}#${params.toString()}`;
        history.replaceState(null, '', url);
    } catch (error) {
        // URL 写入失败不影响刮削浏览。
    }
}

async function restoreScraperLocation() {
    const params = getScraperUrlParams();
    const provider = normalizeProvider(params.provider);
    const knownProvider = provider && state.providers.some(
        item => normalizeProvider(item.provider) === provider,
    );
    if (!knownProvider) return false;
    if (provider !== state.provider) {
        state.provider = provider;
        state.cid = '0';
        state.trail = [{ id: '0', name: '根目录' }];
        state.search = '';
        $('scraper-search-input').value = '';
        clearSelection();
        clearPlan();
        resetIdentifyContext({ resetInputs: true });
        closeIdentifyPanel();
        renderProviderTabs();
    }
    const segments = String(params.path || '').split('/').filter(Boolean);
    if (!segments.length) return true;
    let currentCid = '0';
    const trail = [{ id: '0', name: '根目录' }];
    try {
        for (const segment of segments) {
            const data = await window.MediaHubApi.getJson(
                `/scraper/${encodeURIComponent(state.provider)}/entries?cid=${encodeURIComponent(currentCid)}`
            );
            const entries = Array.isArray(data.entries) ? data.entries : [];
            const matched = entries.find(item => item.is_dir && String(item.name || '') === segment);
            if (!matched) break;
            currentCid = normalizeCid(matched.cid || matched.id);
            trail.push({ id: currentCid, name: segment });
        }
    } catch (error) {
        // 目录已失效时停留在最近可访问的位置。
    }
    if (trail.length > 1) {
        state.cid = currentCid;
        state.trail = trail;
    }
    return true;
}

function formatFileSize(size) {
    const value = Number(size || 0);
    if (!Number.isFinite(value) || value <= 0) return '--';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let next = value;
    let unit = 0;
    while (next >= 1024 && unit < units.length - 1) {
        next /= 1024;
        unit += 1;
    }
    return `${next.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDateMinute(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '';
    const pad = value => String(value).padStart(2, '0');
    return [
        date.getFullYear(),
        pad(date.getMonth() + 1),
        pad(date.getDate()),
    ].join('-') + ` ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatTimeText(value) {
    const text = String(value || '').trim();
    if (!text) return '--';
    if (/^\d{10,17}$/.test(text)) {
        const numeric = Number(text);
        if (Number.isFinite(numeric)) {
            const timestamp = text.length === 10 ? numeric * 1000 : numeric;
            const formatted = formatDateMinute(new Date(timestamp));
            if (formatted) return formatted;
        }
    }
    const parsed = Date.parse(text);
    if (Number.isFinite(parsed)) {
        const formatted = formatDateMinute(new Date(parsed));
        if (formatted) return formatted;
    }
    return text.replace('T', ' ').slice(0, 16);
}

function parseEntryModifiedMs(value) {
    const text = String(value || '').trim();
    if (!text) return 0;
    if (/^\d{10,17}$/.test(text)) {
        const numeric = Number(text);
        if (Number.isFinite(numeric)) return text.length === 10 ? numeric * 1000 : numeric;
    }
    const parsed = Date.parse(text);
    return Number.isFinite(parsed) ? parsed : 0;
}

function getEntryIcon(isDir) {
    if (isDir) {
        return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M3.75 6.75A2.25 2.25 0 0 1 6 4.5h3.172c.597 0 1.169.237 1.591.659l1.078 1.078c.14.14.33.22.53.22H18A2.25 2.25 0 0 1 20.25 8.7v.6H3.75v-2.55Z"/><path fill="currentColor" d="M3 10.8A1.8 1.8 0 0 1 4.8 9h14.4A1.8 1.8 0 0 1 21 10.8v4.95A3.75 3.75 0 0 1 17.25 19.5H6.75A3.75 3.75 0 0 1 3 15.75V10.8Z"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M7.5 3.75A2.25 2.25 0 0 0 5.25 6v12A2.25 2.25 0 0 0 7.5 20.25h9A2.25 2.25 0 0 0 18.75 18V8.56a2.25 2.25 0 0 0-.659-1.591l-2.56-2.56A2.25 2.25 0 0 0 13.94 3.75H7.5Z"/><path fill="rgba(15,23,42,0.18)" d="M14.25 3.9v3.6c0 .414.336.75.75.75h3.6"/></svg>';
}

function enrichEntry(entry) {
    const item = entry && typeof entry === 'object' ? entry : {};
    const id = String(item.id || item.cid || item.fid || '').trim();
    const name = String(item.name || '').trim();
    const isSearchResult = !!item.search_result;
    const parentPath = isSearchResult ? '' : currentParentPath();
    const itemPath = normalizePath(item.path || '');
    const combinedPath = normalizePath(joinPath(parentPath, name));
    const path = isSearchResult
        ? (itemPath || name)
        : (itemPath && (itemPath.includes('/') || !parentPath) ? itemPath : combinedPath);
    const rawParentId = String(item.parent_id || '').trim();
    return {
        ...item,
        id,
        name,
        parent_id: isSearchResult ? rawParentId : normalizeCid(rawParentId || state.cid),
        parent_path: isSearchResult ? normalizePath(item.parent_path || '') : parentPath,
        path,
        is_dir: !!item.is_dir,
        size: Number(item.size || 0) || 0,
    };
}

function getSelectedEntries() {
    return Array.from(state.selected.values())
        .filter(item => item && item.id && item.name)
        .map(item => ({ ...item }));
}

function getSelectionPath(entry = {}) {
    const item = entry && typeof entry === 'object' ? entry : {};
    return normalizePath(item.path || joinPath(item.parent_path || '', item.name || ''));
}

function getSelectionParentPath(entry = {}) {
    const item = entry && typeof entry === 'object' ? entry : {};
    const parentPath = normalizePath(item.parent_path || '');
    if (item.search_result && !parentPath) return '';
    return normalizePath(parentPath || currentParentPath());
}

function getUnknownSearchResultEntries(entries = []) {
    return (Array.isArray(entries) ? entries : [])
        .filter(item => item && item.search_result && item.path_unknown !== false);
}

function hasUnknownSearchResultEntries(entries = []) {
    return getUnknownSearchResultEntries(entries).length > 0;
}

function buildMonitorScanScopes(entries) {
    const scopeSet = new Set();
    (Array.isArray(entries) ? entries : []).forEach(item => {
        if (!item || !item.name) return;
        scopeSet.add(item.is_dir ? getSelectionPath(item) : getSelectionParentPath(item));
    });
    return Array.from(scopeSet).filter(path => path && path !== '');
}

function buildMutationRequestId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function buildMonitorEntrySnapshot(entry = {}) {
    const item = entry && typeof entry === 'object' ? entry : {};
    return {
        id: String(item.id || '').trim(),
        name: String(item.name || '').trim(),
        path: getSelectionPath(item),
        parent_path: getSelectionParentPath(item),
        parent_id: normalizeCid(item.parent_id || state.cid),
        is_dir: !!item.is_dir,
        cid: item.is_dir ? String(item.cid || item.id || '').trim() : '',
        fid: item.is_dir ? '' : String(item.fid || item.id || '').trim(),
        size: Math.max(0, Number(item.size || 0) || 0),
        modified_at: String(item.modified_at || '').trim(),
    };
}

function withMonitorSyncResult(message, response = {}) {
    const sync = response?.monitor_sync;
    if (!sync || sync.status === 'not_applicable') return message;
    const taskCount = Array.isArray(sync.matched_tasks) ? sync.matched_tasks.length : 0;
    if (sync.status === 'queued') {
        return `${message}，STRM 同步已排队${taskCount ? `（${taskCount} 个监控任务）` : ''}`;
    }
    if (sync.status === 'reconcile_queued') return `${message}，STRM 局部校正已排队`;
    if (sync.status === 'processing') return `${message}，STRM 正在同步`;
    if (sync.status === 'completed') return `${message}，STRM 同步已完成`;
    if (sync.status === 'manual_required') return `${message}，STRM 将同步已知内容，完成后需手动监控补齐`;
    if (sync.status === 'failed') return `${message}，STRM 同步失败，已保留重试`;
    if (sync.status === 'not_matched') return `${message}，未命中文件夹监控任务`;
    if (sync.status === 'unavailable') return `${message}，STRM 同步信息不可用`;
    return message;
}

function isSelectionPathCovered(path, ancestorPath) {
    const normalizedPath = normalizePath(path);
    const normalizedAncestor = normalizePath(ancestorPath);
    if (!normalizedPath || !normalizedAncestor) return false;
    return normalizedPath === normalizedAncestor || normalizedPath.startsWith(`${normalizedAncestor}/`);
}

function getEffectiveSelectedEntries(entries = getSelectedEntries()) {
    const items = Array.isArray(entries) ? entries : [];
    const normalized = items
        .filter(item => item && item.id && item.name)
        .map(item => ({
            ...item,
            path: getSelectionPath(item),
        }))
        .sort((a, b) => {
            const depthA = getSelectionPath(a).split('/').filter(Boolean).length;
            const depthB = getSelectionPath(b).split('/').filter(Boolean).length;
            if (depthA !== depthB) return depthA - depthB;
            if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
            const pathCompare = String(a.path || '').localeCompare(String(b.path || ''), 'zh-Hans-CN');
            if (pathCompare !== 0) return pathCompare;
            return String(a.id || '').localeCompare(String(b.id || ''));
        });
    const selected = [];
    const seenIds = new Set();
    const seenPaths = new Set();
    normalized.forEach(item => {
        const id = String(item.id || '').trim();
        const path = normalizePath(item.path || '');
        if (!id || !path) return;
        if (seenIds.has(id) || seenPaths.has(path)) return;
        if (selected.some(ancestor => ancestor.is_dir && isSelectionPathCovered(path, ancestor.path))) return;
        selected.push({ ...item, path });
        seenIds.add(id);
        seenPaths.add(path);
    });
    return selected;
}

function getSelectionKey(entries = getSelectedEntries()) {
    return getEffectiveSelectedEntries(entries)
        .map(item => `${item.is_dir ? 'd' : 'f'}:${item.id}`)
        .sort()
        .join('|');
}

function getSelectionMode(entries = getSelectedEntries()) {
    const items = getEffectiveSelectedEntries(entries);
    return items.length === 1 && !!items[0]?.is_dir ? 'folder' : 'contents';
}

function isWholeFolderSelection(entries = getSelectedEntries()) {
    return getSelectionMode(entries) === 'folder';
}

function createEmptyIdentifyPathSelection() {
    return {
        source: '',
        tokens: [],
        selectedIndexes: [],
        expanded: true,
    };
}

function createIdentifyPathSelection(entries) {
    const pathSelection = window.ScraperPathSelection;
    if (!pathSelection) throw new Error('ScraperPathSelection 尚未加载');
    return pathSelection.createSelection(entries, currentParentPath());
}

function resetIdentifyContext({ resetInputs = false } = {}) {
    state.identifyRequestSeq += 1;
    state.identifyBusy = false;
    state.identifyResult = null;
    state.identifySelectionKey = '';
    state.identifyPathSelection = createEmptyIdentifyPathSelection();
    state.identifyPathGesture = null;
    state.tmdb = null;
    state.manualResults = [];
    state.manualMediaTypeTouched = false;
    state.planEpisodeOverrides = {};
    if (resetInputs) {
        const manualInput = $('scraper-manual-query');
        if (manualInput) manualInput.value = '';
        const mediaSelect = $('scraper-manual-media-type');
        if (mediaSelect) mediaSelect.value = 'movie';
    }
}

function applyIdentifyManualSearchDefaults(identifyResult = {}) {
    const data = identifyResult && typeof identifyResult === 'object' ? identifyResult : {};
    const mediaSelect = $('scraper-manual-media-type');
    if (mediaSelect && data.media_type && !state.manualMediaTypeTouched) {
        mediaSelect.value = data.media_type === 'tv' ? 'tv' : 'movie';
    }
}

function clearSelection() {
    state.selected.clear();
}

function clearPlan() {
    state.planRequestSeq += 1;
    state.planBusy = false;
    state.plan = null;
    state.planSelections.clear();
    state.batchPlanContext = null;
    renderPlan();
    renderEntries();
}

function clearIdentifyMode({ resetInputs = true } = {}) {
    clearPlan();
    resetIdentifyContext({ resetInputs });
    closeIdentifyPanel();
    renderIdentify();
    renderSelection();
}

function invalidateSelectionContext() {
    resetIdentifyContext({ resetInputs: true });
    closeIdentifyPanel();
    clearPlan();
}

function openIdentifyPanel() {
    const panel = $('scraper-identify-panel');
    if (!panel) return;
    panel.classList.remove('hidden');
    panel.classList.add('is-open');
}

function closeIdentifyPanel() {
    const panel = $('scraper-identify-panel');
    if (!panel) return;
    panel.classList.add('hidden');
    panel.classList.remove('is-open');
}

function setBusyButton(button, busy, busyText = '处理中...', idleText = '') {
    if (!button) return;
    button.disabled = !!busy;
    button.classList.toggle('btn-disabled', !!busy);
    if (busy) {
        button.dataset.idleText = button.textContent || idleText;
        button.textContent = busyText;
    } else if (button.dataset.idleText) {
        button.textContent = button.dataset.idleText;
        delete button.dataset.idleText;
    }
}

function scrollScraperToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function syncScraperBackTopButton() {
    const btn = $('scraper-back-top-btn');
    const page = $('page-scraper');
    if (!btn || !page) return;
    const isVisible = !page.classList.contains('hidden');
    const isModalLocked = document.body.classList.contains('body-scroll-lock');
    const scrollTop = Math.max(0, window.scrollY || window.pageYOffset || 0);
    const shouldShow = isVisible && !isModalLocked && scrollTop > 360;
    btn.classList.toggle('hidden', !shouldShow);
}

function syncScraperBrowserHeight() {
    const page = $('page-scraper');
    const panel = document.querySelector('#page-scraper .scraper-browser-panel');
    if (!page || !panel || page.classList.contains('hidden')) return;
    const rect = panel.getBoundingClientRect();
    const reservedBottom = window.matchMedia('(max-width: 1023px)').matches ? 96 : 28;
    const available = Math.max(380, Math.floor(window.innerHeight - Math.max(rect.top, 0) - reservedBottom));
    panel.style.setProperty('--scraper-browser-height', `${available}px`);
}

function closeToolPopovers() {
    state.activeTool = '';
    $('scraper-search-popover')?.classList.add('hidden');
    $('scraper-create-popover')?.classList.add('hidden');
}

function toggleToolPopover(tool) {
    const normalized = String(tool || '').trim();
    const nextTool = state.activeTool === normalized ? '' : normalized;
    closeToolPopovers();
    state.activeTool = nextTool;
    if (nextTool === 'search') {
        $('scraper-search-popover')?.classList.remove('hidden');
        setTimeout(() => $('scraper-search-input')?.focus(), 20);
    } else if (nextTool === 'create') {
        $('scraper-create-popover')?.classList.remove('hidden');
        setTimeout(() => $('scraper-new-folder-name')?.focus(), 20);
    }
    requestAnimationFrame(syncScraperBrowserHeight);
}

function openSearchPopover({ focus = false } = {}) {
    state.activeTool = 'search';
    $('scraper-search-popover')?.classList.remove('hidden');
    if (focus) {
        setTimeout(() => $('scraper-search-input')?.focus(), 20);
    }
    requestAnimationFrame(syncScraperBrowserHeight);
}

async function promptText({ title = '输入名称', message = '', defaultValue = '', confirmText = '确认' } = {}) {
    return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.className = 'scraper-prompt-modal';
        modal.innerHTML = `
            <div class="scraper-prompt-shell" role="dialog" aria-modal="true">
                <div class="scraper-prompt-title">${escapeHtml(title)}</div>
                ${message ? `<div class="scraper-prompt-message">${escapeHtml(message)}</div>` : ''}
                <input class="scraper-input scraper-prompt-input" value="${escapeHtml(defaultValue)}">
                <div class="scraper-prompt-actions">
                    <button type="button" class="scraper-compact-btn" data-prompt-cancel>取消</button>
                    <button type="button" class="scraper-compact-btn scraper-primary-soft" data-prompt-confirm>${escapeHtml(confirmText)}</button>
                </div>
            </div>
        `;
        const input = modal.querySelector('.scraper-prompt-input');
        const cleanup = (value) => {
            document.removeEventListener('keydown', onKeydown);
            modal.remove();
            resolve(value);
        };
        const onKeydown = (event) => {
            if (event.key === 'Escape') cleanup(null);
            if (event.key === 'Enter' && !event.isComposing) cleanup(String(input.value || '').trim());
        };
        // 遮罩关闭只认 pointerdown（按下时就在遮罩上）：文本选择从输入框拖出、
        // 在遮罩上松开时点击事件的公共祖先仍是遮罩，若用 click 判断会误关重命名框。
        modal.addEventListener('pointerdown', (event) => {
            if (event.target === modal) cleanup(null);
        });
        modal.addEventListener('click', (event) => {
            if (!modal.isConnected) return;
            if (event.target.closest('[data-prompt-cancel]')) cleanup(null);
            if (event.target.closest('[data-prompt-confirm]')) cleanup(String(input.value || '').trim());
        });
        document.addEventListener('keydown', onKeydown);
        document.body.appendChild(modal);
        setTimeout(() => {
            input.focus();
            input.select();
        }, 20);
    });
}

function renderProviderTabs() {
    const container = $('scraper-provider-tabs');
    if (!container) return;
    const providers = state.providers.length
        ? state.providers
        : getScraperProviderOptions();
    if (!providers.length) {
        container.innerHTML = '';
        return;
    }
    container.innerHTML = providers.map((item) => {
        const provider = normalizeProvider(item.provider);
        const active = provider === state.provider;
        const configuredKnown = item.configuredKnown !== false && typeof item.configured === 'boolean';
        const configured = configuredKnown ? !!item.configured : true;
        const statusText = configuredKnown ? (configured ? '已配置' : '未配置') : '已启用';
        return `
            <button
                type="button"
                class="scraper-provider-tab ${active ? 'is-active' : ''} ${configured ? '' : 'is-muted'}"
                data-scraper-provider="${escapeHtml(provider)}"
                aria-pressed="${active ? 'true' : 'false'}"
            >
                <span>${escapeHtml(item.label || getProviderLabel(provider))}</span>
                <small>${statusText}</small>
            </button>
        `;
    }).join('');
}

function renderProviderStatus() {
    const el = $('scraper-provider-status');
    if (!el) return;
    const availableProviders = state.providers.length ? state.providers : getScraperProviderOptions();
    if (!availableProviders.length) {
        el.textContent = '未启用可浏览网盘。';
        return;
    }
    const providerLabel = getProviderLabel();
    if (!isProviderConfigured()) {
        el.textContent = `${providerLabel} 认证信息未配置，文件管理和刮削执行暂不可用。`;
        return;
    }
    const folderCount = Number(state.summary.folder_count || 0);
    const fileCount = Number(state.summary.file_count || 0);
    const scrapeNote = state.providersLoaded && !supportsProviderOperation('scrape') ? ' / 暂不支持刮削执行' : '';
    el.textContent = `${providerLabel} / 当前目录 ${folderCount} 个文件夹、${fileCount} 个文件${scrapeNote}`;
}

function renderBreadcrumbs() {
    const container = $('scraper-breadcrumbs');
    if (!container) return;
    container.innerHTML = state.trail.map((item, index) => {
        const active = index === state.trail.length - 1;
        const separator = index > 0 ? '<span class="scraper-breadcrumb-sep">/</span>' : '';
        if (active) {
            return `${separator}<span class="scraper-breadcrumb is-active">${escapeHtml(item.name || '根目录')}</span>`;
        }
        return `${separator}<button type="button" class="scraper-breadcrumb" data-scraper-trail-index="${index}">${escapeHtml(item.name || '根目录')}</button>`;
    }).join('');
}

function getPlanActions() {
    return state.plan && Array.isArray(state.plan.actions) ? state.plan.actions : [];
}

function parseManualEpisode(value) {
    const episode = Number(value);
    return Number.isInteger(episode) && episode > 0 ? episode : 0;
}

function getPlanEpisodeOverrides() {
    return Object.fromEntries(
        Object.entries(state.planEpisodeOverrides)
            .map(([entryId, episode]) => [String(entryId || '').trim(), parseManualEpisode(episode)])
            .filter(([entryId, episode]) => entryId && episode > 0),
    );
}

function getPlanAction(actionIndex) {
    const normalizedIndex = Number(actionIndex || 0) || 0;
    return getPlanActions().find(action => Number(action.action_index || 0) === normalizedIndex) || null;
}

function renderManualEpisodeEditor(action) {
    const actionIndex = Number(action.action_index || 0) || 0;
    const entryId = String(action.entry_id || '').trim();
    const manualEpisode = parseManualEpisode(action.manual_episode || state.planEpisodeOverrides[entryId]);
    if (!actionIndex || !entryId || (!action.manual_episode_allowed && manualEpisode <= 0)) return '';
    return `
        <div class="scraper-preview-manual-episode">
            <label for="scraper-manual-episode-${escapeHtml(String(actionIndex))}">手动集数</label>
            <input id="scraper-manual-episode-${escapeHtml(String(actionIndex))}" type="number" min="1" step="1" inputmode="numeric" class="scraper-input" data-scraper-manual-episode-input="${escapeHtml(String(actionIndex))}" value="${manualEpisode ? escapeHtml(String(manualEpisode)) : ''}" placeholder="如 12">
            <button type="button" class="scraper-compact-btn scraper-primary-soft" data-scraper-action="apply-manual-episode" data-scraper-action-index="${escapeHtml(String(actionIndex))}">应用</button>
            ${manualEpisode ? `<button type="button" class="scraper-compact-btn" data-scraper-action="clear-manual-episode" data-scraper-action-index="${escapeHtml(String(actionIndex))}">清除</button>` : ''}
        </div>
    `;
}

function getSelectedReadyPlanCount() {
    return getPlanActions().filter(action => action.ready && state.planSelections.has(Number(action.action_index || 0))).length;
}

function renderSelection() {
    const countEl = $('scraper-selection-count');
    const selectedEntries = getEffectiveSelectedEntries();
    const planActions = getPlanActions();
    const selectedReadyCount = getSelectedReadyPlanCount();
    const hasPlan = planActions.length > 0;
    const hasBinding = !!(state.tmdb && Number(state.tmdb.tmdb_id || state.tmdb.id || 0) > 0);
    if (countEl) {
        countEl.title = '';
        if (hasPlan) {
            const readyCount = planActions.filter(action => action.ready).length;
            countEl.textContent = `已勾选 ${selectedReadyCount} 项`;
            countEl.title = `预览 ${planActions.length} 项 / 可执行 ${readyCount} 项 / 已勾选 ${selectedReadyCount} 项`;
        } else {
            const count = selectedEntries.length;
            if (!count) {
                countEl.textContent = '未选择条目';
            } else if (isWholeFolderSelection(selectedEntries)) {
                countEl.textContent = `已选择 ${count} 项`;
                countEl.title = `已选择整个文件夹：${selectedEntries[0].name || '--'}`;
            } else {
                const hasFolder = selectedEntries.some(item => item.is_dir);
                countEl.textContent = `已选择 ${count} 项`;
                countEl.title = `内容模式（只改文件名${hasFolder ? '，含子文件夹内文件' : ''}）`;
            }
        }
    }
    const bindingBtn = $('scraper-bound-media-btn');
    if (bindingBtn) {
        bindingBtn.classList.toggle('hidden', !hasBinding);
        bindingBtn.disabled = !hasBinding;
        bindingBtn.textContent = hasBinding ? `已绑定：${getTmdbDisplayTitle()}` : '';
    }
    const checkAll = $('scraper-check-all');
    if (checkAll) {
        const selectable = getDisplayEntries();
        const selectedInCurrent = selectable.filter(item => state.selected.has(item.id)).length;
        checkAll.checked = selectable.length > 0 && selectedInCurrent === selectable.length;
        checkAll.indeterminate = selectedInCurrent > 0 && selectedInCurrent < selectable.length;
        checkAll.disabled = state.loading || selectable.length <= 0;
    }
    const hasSelection = selectedEntries.length > 0;
    const selectedInCurrent = getDisplayEntries().filter(item => state.selected.has(item.id)).length;
    const renameButton = document.querySelector('[data-scraper-action="rename-selected"]');
    if (renameButton) {
        const canRename = supportsProviderOperation('rename') && selectedEntries.length === 1 && !hasPlan;
        renameButton.classList.toggle('hidden', hasPlan);
        renameButton.disabled = state.loading || !canRename;
        renameButton.classList.toggle('btn-disabled', state.loading || !canRename);
        renameButton.textContent = '重命名';
        renameButton.title = supportsProviderOperation('rename')
            ? (canRename ? '重命名选中的文件或文件夹' : '请选择一个文件或文件夹进行重命名')
            : `${getProviderLabel()} 暂不支持重命名`;
    }
    const actionRules = {
        'select-range': !hasPlan && selectedInCurrent >= 2,
        'prepare-copy': supportsProviderOperation('copy') && hasSelection,
        'prepare-move': supportsProviderOperation('move') && hasSelection,
        'delete-selected': supportsProviderOperation('delete') && hasSelection,
    };
    Object.entries(actionRules).forEach(([action, enabled]) => {
        const button = document.querySelector(`[data-scraper-action="${action}"]`);
        if (!button) return;
        button.classList.toggle('hidden', hasPlan);
        button.disabled = state.loading || !enabled;
        button.classList.toggle('btn-disabled', state.loading || !enabled);
    });
    const monitorScanButton = document.querySelector('[data-scraper-action="monitor-scan"]');
    if (monitorScanButton) {
        const canMonitorScan = !hasPlan && hasSelection;
        monitorScanButton.classList.toggle('hidden', hasPlan);
        monitorScanButton.disabled = state.loading || !canMonitorScan;
        monitorScanButton.classList.toggle('btn-disabled', state.loading || !canMonitorScan);
        monitorScanButton.title = canMonitorScan
            ? '对勾选的文件夹（或文件所在目录）执行监控扫描并刷新 STRM'
            : (hasPlan ? '退出预览后再扫描监控' : '请先勾选要扫描的文件夹或文件');
    }
    const batchButton = document.querySelector('[data-scraper-action="open-batch"]');
    if (batchButton) {
        const canBatch = supportsProviderOperation('scrape') && isProviderConfigured() && !hasPlan && selectedEntries.length > 0;
        batchButton.classList.toggle('hidden', hasPlan);
        batchButton.disabled = state.loading || !canBatch;
        batchButton.classList.toggle('btn-disabled', state.loading || !canBatch);
        batchButton.title = canBatch
            ? `批量整理勾选的 ${selectedEntries.length} 个条目`
            : (hasPlan ? '退出预览后再批量整理' : '请先勾选要批量整理的文件夹或文件');
    }
    const reopenBatchButton = $('scraper-reopen-batch-btn');
    if (reopenBatchButton) {
        const batchItems = Array.isArray(state.batchScan?.items) ? state.batchScan.items : [];
        const canReopen = hasPlan && batchItems.length > 0;
        reopenBatchButton.classList.toggle('hidden', !canReopen);
        reopenBatchButton.disabled = state.loading || state.executeBusy || !canReopen;
        reopenBatchButton.classList.toggle('btn-disabled', state.loading || state.executeBusy || !canReopen);
    }
    const clearPlanBtn = $('scraper-clear-plan-btn');
    if (clearPlanBtn) {
        clearPlanBtn.classList.toggle('hidden', !hasPlan);
        clearPlanBtn.disabled = !hasPlan || state.executeBusy;
        clearPlanBtn.classList.toggle('btn-disabled', !hasPlan || state.executeBusy);
    }
    const inlineExecuteBtn = $('scraper-inline-execute-btn');
    if (inlineExecuteBtn) {
        const showExecute = hasPlan;
        inlineExecuteBtn.classList.toggle('hidden', !showExecute);
        const executeDisabled = state.executeBusy || selectedReadyCount <= 0 || !supportsProviderOperation('scrape');
        inlineExecuteBtn.disabled = executeDisabled;
        inlineExecuteBtn.classList.toggle('btn-disabled', executeDisabled);
        inlineExecuteBtn.textContent = state.executeBusy ? '提交中...' : `执行重命名 ${selectedReadyCount} 项`;
    }
    syncFolderScopedControls();
    syncBuildPlanControls();
}

function syncBuildPlanControls() {
    const selectedEntries = getEffectiveSelectedEntries();
    const hasBinding = !!(state.tmdb && Number(state.tmdb.tmdb_id || state.tmdb.id || 0) > 0);
    const hasPlan = getPlanActions().length > 0;
    const showBuild = supportsProviderOperation('scrape') && selectedEntries.length > 0 && hasBinding && !hasPlan;
    const inlineBuildBtn = $('scraper-inline-build-plan-btn');
    if (inlineBuildBtn) {
        inlineBuildBtn.classList.toggle('hidden', !showBuild);
        inlineBuildBtn.disabled = state.loading || state.planBusy || !showBuild;
        inlineBuildBtn.classList.toggle('btn-disabled', state.loading || state.planBusy || !showBuild);
        inlineBuildBtn.textContent = state.planBusy ? '识别中...' : '生成预览';
    }
    const buildBtn = $('scraper-build-plan-btn');
    if (buildBtn) {
        buildBtn.disabled = state.loading || state.planBusy || !showBuild;
        buildBtn.classList.toggle('btn-disabled', state.loading || state.planBusy || !showBuild);
        buildBtn.textContent = state.planBusy ? '识别中...' : '生成预览';
        buildBtn.title = state.planBusy
            ? '正在识别文件并生成预览'
            : (showBuild ? '生成命名预览' : '请先选择要刮削的文件或文件夹');
    }
}

function renderMoveBuffer() {
    const el = $('scraper-move-buffer');
    if (!el) return;
    const buffer = state.copyBuffer || state.moveBuffer;
    const mode = state.copyBuffer ? 'copy' : 'move';
    if (!buffer || !Array.isArray(buffer.entries) || buffer.entries.length <= 0) {
        el.classList.add('hidden');
        el.innerHTML = '';
        return;
    }
    const modeText = mode === 'copy' ? '复制' : '移动';
    const actionName = mode === 'copy' ? 'copy-here' : 'move-here';
    const clearName = mode === 'copy' ? 'clear-copy' : 'clear-move';
    el.classList.remove('hidden');
    el.innerHTML = `
        <div>
            <strong>待${modeText} ${escapeHtml(String(buffer.entries.length))} 项</strong>
            <span>来源：${escapeHtml(buffer.source_path || '根目录')}</span>
        </div>
        <div class="scraper-move-actions">
            <button type="button" class="scraper-compact-btn scraper-primary-soft" data-scraper-action="${actionName}">${modeText}到当前目录</button>
            <button type="button" class="scraper-compact-btn" data-scraper-action="${clearName}">取消</button>
        </div>
    `;
}

function renderEntries() {
    const list = $('scraper-entry-list');
    if (!list) return;
    const manager = getFileManager();
    renderProviderStatus();
    renderBreadcrumbs();
    renderSelection();
    renderMoveBuffer();
    const refreshBtn = $('scraper-refresh-btn');
    if (refreshBtn) {
        refreshBtn.disabled = !!state.loading;
        refreshBtn.classList.toggle('btn-disabled', !!state.loading);
    }
    const canCreateFolder = isProviderConfigured() && supportsProviderOperation('create_folder');
    document.querySelectorAll('[data-scraper-action="toggle-create-folder"], [data-scraper-action="create-folder"]').forEach((button) => {
        const disabled = state.loading || !canCreateFolder;
        button.disabled = disabled;
        button.classList.toggle('btn-disabled', disabled);
        button.title = canCreateFolder ? (button.title || '新建文件夹') : `${getProviderLabel()} 暂不支持新建文件夹`;
    });
    const header = document.querySelector('.scraper-entry-header');
    const table = document.querySelector('.scraper-entry-table');
    const planActions = getPlanActions();
    table?.classList.add('file-manager-table');
    header?.classList.add('file-manager-header');
    list.classList.add('file-manager-list');
    if (table) {
        table.style.setProperty('--file-manager-columns', 'minmax(220px, 1fr) 142px 110px');
        table.style.setProperty('--file-manager-min-width', '680px');
    }
    table?.classList.toggle('is-preview-mode', planActions.length > 0);
    if (planActions.length) {
        const planWarnings = Array.isArray(state.plan?.warnings) ? state.plan.warnings : [];
        const warningBar = planWarnings.length
            ? `
                <div class="scraper-plan-warning-bar">
                    ${planWarnings.map(text => `<div>${escapeHtml(String(text || ''))}</div>`).join('')}
                </div>
            `
            : '';
        if (header) {
            header.innerHTML = `
                <div>原文件</div>
                <span>新名称预览</span>
                <span>执行</span>
            `;
        }
        const actionRows = planActions.map((action) => {
            const actionIndex = Number(action.action_index || 0) || 0;
            const checked = action.ready && state.planSelections.has(actionIndex);
            const isDelete = !!action.delete;
            const readyClass = isDelete
                ? 'is-delete'
                : (action.ready ? (action.is_dir ? 'is-ready is-ready-dir' : 'is-ready') : 'is-blocked');
            const statusText = isDelete ? '删除' : (action.ready ? '可执行' : '需处理');
            const oldPath = String(action.old_path || action.old_name || '--');
            const newPath = isDelete ? '（删除广告文件）' : String(action.new_path || action.new_name || '--');
            return `
                <div class="scraper-preview-row ${readyClass}">
                    <div class="scraper-preview-original">
                        <span class="scraper-plan-badge">${action.is_dir ? '文件夹' : (isDelete ? '广告' : '文件')}</span>
                        <strong title="${escapeHtml(oldPath)}">${escapeHtml(action.old_name || '--')}</strong>
                    </div>
                    <div class="scraper-preview-target">
                        <div class="scraper-preview-target-head">
                            <span class="scraper-preview-status ${isDelete ? 'is-danger' : (action.ready ? 'is-ok' : 'is-warn')}">${statusText}</span>
                            <strong title="${escapeHtml(newPath)}">${escapeHtml(action.new_name || '--')}</strong>
                        </div>
                        ${action.issue ? `<em>${escapeHtml(action.issue)}</em>` : ''}
                        ${action.warning ? `<em class="scraper-plan-warning">${escapeHtml(action.warning)}</em>` : ''}
                        ${renderManualEpisodeEditor(action)}
                    </div>
                    <label class="scraper-preview-check">
                        <input type="checkbox" class="ui-checkbox ui-checkbox-sm" data-scraper-plan-check="${escapeHtml(String(actionIndex))}" ${checked ? 'checked' : ''} ${action.ready ? '' : 'disabled'}>
                        <span>${action.ready ? '执行' : '不可执行'}</span>
                    </label>
                </div>
            `;
        }).join('');
        const unchangedRows = Array.isArray(state.plan?.unchanged_rows) ? state.plan.unchanged_rows : [];
        const unchangedHtml = unchangedRows.map((row) => {
            const title = row.item_name ? `${row.item_name} / ${row.old_name || '--'}` : (row.old_name || '--');
            const followsFolderRename = !!row.note;
            const rowTitle = followsFolderRename
                ? (row.new_path || row.old_path || row.old_name || '--')
                : (row.old_path || row.old_name || '--');
            return `
                <div class="scraper-preview-row is-unchanged">
                    <div class="scraper-preview-original">
                        <span class="scraper-plan-badge">${row.is_dir ? '文件夹' : '文件'}</span>
                        <strong title="${escapeHtml(rowTitle)}">${escapeHtml(title)}</strong>
                    </div>
                    <div class="scraper-preview-target">
                        <div class="scraper-preview-target-head">
                            <span class="scraper-preview-status is-muted">${followsFolderRename ? '随文件夹重命名' : '无变化'}</span>
                            <strong>${followsFolderRename ? '文件未单独移动，保持原名' : '保持原名，已跳过'}</strong>
                        </div>
                    </div>
                    <label class="scraper-preview-check">
                        <input type="checkbox" class="ui-checkbox ui-checkbox-sm" disabled>
                        <span>跳过</span>
                    </label>
                </div>
            `;
        }).join('');
        list.innerHTML = warningBar + actionRows + unchangedHtml;
        return;
    }
    if (header) {
        header.innerHTML = `
            <div class="scraper-entry-name-cell">
                <input id="scraper-check-all" type="checkbox" class="ui-checkbox ui-checkbox-sm" aria-label="选择当前目录全部条目">
                ${manager.renderSortButton({ key: 'name', label: '名称' }, state.entrySort, { sortDataAttr: 'data-scraper-sort' })}
            </div>
            ${manager.renderSortButton({ key: 'modified_at', label: '修改时间' }, state.entrySort, { sortDataAttr: 'data-scraper-sort' })}
            ${manager.renderSortButton({ key: 'size', label: '大小' }, state.entrySort, { sortDataAttr: 'data-scraper-sort' })}
        `;
        renderSelection();
    }
    if (state.loading && !state.entries.length) {
        list.innerHTML = `<div class="scraper-empty-row">正在读取${escapeHtml(getProviderLabel())}目录...</div>`;
        return;
    }
    if (!isProviderConfigured()) {
        list.innerHTML = `<div class="scraper-empty-row">请先到参数配置填写 ${escapeHtml(getProviderLabel())} 认证信息。</div>`;
        return;
    }
    if (state.entryError) {
        list.innerHTML = `<div class="scraper-empty-row">读取${escapeHtml(getProviderLabel())}目录失败：${escapeHtml(state.entryError)}</div>`;
        return;
    }
    if (!state.entries.length) {
        list.innerHTML = state.search
            ? `<div class="scraper-empty-row">没有找到匹配“${escapeHtml(state.search)}”的条目。</div>`
            : '<div class="scraper-empty-row">当前目录没有可显示条目。</div>';
        return;
    }
    const columns = [
        {
            key: 'name',
            cellClass: 'file-manager-cell--name',
            render: (entry) => {
                const selected = state.selected.has(entry.id);
                const entryTitle = escapeHtml(entry.path || entry.name || '');
                const entryName = escapeHtml(entry.name || '--');
                const nameHtml = entry.is_dir
                    ? `<button type="button" class="scraper-entry-link" data-scraper-entry-enter="${escapeHtml(entry.id)}" title="${entryTitle}" ${state.loading || state.navigationBusy ? 'disabled' : ''}>${entryName}</button>`
                    : `<span class="scraper-entry-filename" title="${entryTitle}">${entryName}</span>`;
                return manager.renderNameCell(entry, {
                    checkboxHtml: `<input type="checkbox" class="ui-checkbox ui-checkbox-sm" data-scraper-check="${escapeHtml(entry.id)}" ${selected ? 'checked' : ''}>`,
                    nameHtml,
                });
            },
        },
        {
            key: 'modified_at',
            cellClass: 'file-manager-cell--modified',
            render: (entry) => escapeHtml(formatTimeText(entry.modified_at)),
        },
        {
            key: 'size',
            cellClass: 'file-manager-cell--size',
            render: (entry) => entry.is_dir ? '--' : escapeHtml(formatFileSize(entry.size)),
        },
    ];
    let listHtml = manager.renderRows(getDisplayEntries(), columns, {
        emptyText: '当前目录没有可显示条目。',
        isSelected: (entry) => state.selected.has(entry.id),
        rowAttrs: (entry) => `data-scraper-entry-id="${escapeHtml(entry.id)}"`,
    });
    if (state.hasMore) {
        listHtml += `
            <div class="scraper-empty-row">
                <button
                    type="button"
                    class="scraper-compact-btn scraper-primary-soft"
                    data-scraper-action="load-more-entries"
                    ${state.loadingMore ? 'disabled' : ''}
                >${state.loadingMore ? '加载中...' : `加载更多条目（已加载 ${state.entries.length}）`}</button>
            </div>
        `;
    }
    list.innerHTML = listHtml;
}

function getTmdbDisplayTitle(binding = state.tmdb) {
    const item = binding && typeof binding === 'object' ? binding : {};
    const title = item.tmdb_title || item.title || item.tmdb_localized_title || item.tmdb_english_title || '';
    const year = item.tmdb_year || item.year || '';
    return `${title || '--'}${year ? ` (${year})` : ''}`;
}

function getBoundTmdbKey(binding = state.tmdb) {
    const item = binding && typeof binding === 'object' ? binding : {};
    const id = Number(item.tmdb_id || item.id || 0) || 0;
    if (id <= 0) return '';
    const mediaType = (item.tmdb_media_type || item.media_type) === 'tv' ? 'tv' : 'movie';
    return `${mediaType}:${id}`;
}

function getManualResultTmdbKey(item = {}) {
    const id = Number(item.id || item.tmdb_id || 0) || 0;
    if (id <= 0) return '';
    const mediaType = item.media_type === 'tv' ? 'tv' : 'movie';
    return `${mediaType}:${id}`;
}

function getTmdbSeasonCount(binding = state.tmdb) {
    const item = binding && typeof binding === 'object' ? binding : {};
    const map = item.tmdb_season_episode_map || item.season_episode_map || {};
    const mapSeasons = map && typeof map === 'object'
        ? Object.keys(map).map(value => Number(value || 0)).filter(value => value > 0)
        : [];
    return Math.max(0, Number(item.tmdb_total_seasons || item.total_seasons || 0) || 0, ...mapSeasons);
}

function getSelectedEpisodeModeLabel(mode) {
    const normalized = String(mode || 'auto').trim();
    if (normalized === 'absolute') return '多季：按 TMDB 连续编号';
    if (normalized === 'seasonal') return '单季：按季号识别';
    return '自动跟随 TMDB';
}

function getEffectiveEpisodeModeLabel() {
    const selected = String($('scraper-episode-mode')?.value || 'auto').trim();
    if (selected !== 'auto') return getSelectedEpisodeModeLabel(selected);
    const tmdbMode = String(state.tmdb?.tmdb_episode_mode || '').trim();
    return tmdbMode ? `TMDB 推荐：${getSelectedEpisodeModeLabel(tmdbMode)}` : '自动跟随 TMDB';
}

function syncSeasonControl() {
    const field = $('scraper-season-field');
    const input = $('scraper-season');
    if (!field || !input) return;
    if (!$('scraper-batch-panel')?.classList.contains('hidden')) return;
    const isTv = (state.tmdb?.tmdb_media_type || state.tmdb?.media_type || $('scraper-manual-media-type')?.value) === 'tv';
    field.classList.toggle('hidden', !isTv);
    if (!isTv) return;
    const seasonCount = getTmdbSeasonCount();
    const current = Math.max(1, Number(input.value || 1) || 1);
    if (seasonCount > 0) {
        input.max = String(seasonCount);
        if (current > seasonCount) input.value = String(seasonCount);
    } else {
        input.max = '99';
    }
}

function syncEpisodeModeControl() {
    const field = $('scraper-episode-mode-field');
    const input = $('scraper-episode-mode');
    if (!field || !input) return;
    if (!$('scraper-batch-panel')?.classList.contains('hidden')) return;
    const isTv = (state.tmdb?.tmdb_media_type || state.tmdb?.media_type || $('scraper-manual-media-type')?.value) === 'tv';
    field.classList.toggle('hidden', !isTv);
    if (!isTv) return;
    if (!['auto', 'seasonal', 'absolute'].includes(String(input.value || ''))) {
        input.value = 'auto';
    }
}

function syncFileInfoControls() {
    const enabled = !!$('scraper-preserve-file-info')?.checked;
    document.querySelectorAll('[data-scraper-tag]').forEach(input => {
        input.disabled = !enabled;
        input.closest('label')?.classList.toggle('is-disabled', !enabled);
    });
}

function syncIncludeTmdbIdControl() {
    const input = $('scraper-include-tmdb-id');
    const label = input?.closest('label');
    if (!input) return;
    if (!$('scraper-batch-panel')?.classList.contains('hidden')) return;
    const wholeFolderMode = isWholeFolderSelection();
    input.disabled = !wholeFolderMode;
    if (!wholeFolderMode) {
        if (input.checked) {
            input.dataset.autoDisabled = '1';
        }
        input.checked = false;
    } else if (input.dataset.autoDisabled === '1') {
        input.checked = true;
        delete input.dataset.autoDisabled;
    }
    label?.classList.toggle('is-disabled', !wholeFolderMode);
    if (label) {
        label.title = wholeFolderMode ? '' : '仅在选中整个剧集文件夹时可用';
    }
}

function syncSeasonSubfolderControl() {
    const input = $('scraper-use-season-subfolder');
    const label = $('scraper-use-season-subfolder-wrap');
    if (!input) return;
    if (!$('scraper-batch-panel')?.classList.contains('hidden')) return;
    const wholeFolderMode = isWholeFolderSelection();
    input.disabled = !wholeFolderMode;
    if (!wholeFolderMode) {
        input.checked = false;
        input.dataset.autoDisabled = '1';
    } else if (input.dataset.autoDisabled === '1') {
        input.checked = true;
        delete input.dataset.autoDisabled;
    }
    label?.classList.toggle('is-disabled', !wholeFolderMode);
    if (label) {
        label.title = wholeFolderMode ? '' : '仅在选中整个剧集文件夹时可用';
    }
}

function syncFolderRenameControl() {
    const input = $('scraper-rename-selected-folders');
    const label = $('scraper-rename-selected-folders-wrap');
    if (!input) return;
    if (!$('scraper-batch-panel')?.classList.contains('hidden')) return;
    const wholeFolderMode = isWholeFolderSelection();
    input.disabled = !wholeFolderMode;
    if (!wholeFolderMode) {
        input.checked = false;
        input.dataset.autoDisabled = '1';
    } else if (input.dataset.autoDisabled === '1') {
        input.checked = true;
        delete input.dataset.autoDisabled;
    }
    label?.classList.toggle('is-disabled', !wholeFolderMode);
    if (label) {
        label.title = wholeFolderMode
            ? '仅在选中整个剧集文件夹时可用。'
            : '仅在选中整个剧集文件夹时可用';
    }
}

function syncFolderScopedControls() {
    syncIncludeTmdbIdControl();
    syncSeasonSubfolderControl();
    syncFolderRenameControl();
}

function syncBatchOptionControls() {
    const items = Array.isArray(state.batchScan?.items) ? state.batchScan.items : [];
    const identifyResults = Array.isArray(state.batchIdentify) ? state.batchIdentify : [];
    const hasFolder = items.some(item => !!item.is_dir);
    const hasTv = items.some(item => {
        const index = Number(item.item_index || 0);
        const identify = identifyResults.find(result => Number(result.item_index || 0) === index) || {};
        const binding = getBatchBinding(index);
        return identify.media_type === 'tv'
            || binding?.tmdb_media_type === 'tv'
            || binding?.media_type === 'tv';
    });
    $('scraper-season-field')?.classList.toggle('hidden', !hasTv);
    $('scraper-episode-mode-field')?.classList.toggle('hidden', !hasTv);
    const folderScoped = [
        ['scraper-include-tmdb-id', null],
        ['scraper-use-season-subfolder', 'scraper-use-season-subfolder-wrap'],
        ['scraper-rename-selected-folders', 'scraper-rename-selected-folders-wrap'],
    ];
    folderScoped.forEach(([inputId, labelId]) => {
        const input = $(inputId);
        if (!input) return;
        const label = $(labelId) || input.closest('label');
        input.disabled = !hasFolder;
        if (!hasFolder) {
            if (input.checked) input.dataset.autoDisabled = '1';
            input.checked = false;
        } else if (input.dataset.autoDisabled === '1') {
            input.checked = true;
            delete input.dataset.autoDisabled;
        }
        label?.classList.toggle('is-disabled', !hasFolder);
        if (label) label.title = hasFolder ? '' : '仅在整理文件夹条目时可用';
    });
    syncFileInfoControls();
}

function syncFileNamingModeControls() {
    const mode = String($('scraper-file-name-mode')?.value || 'standard').trim();
    const standard = mode === 'standard';
    const wrap = $('scraper-standard-naming-wrap');
    if (wrap) {
        wrap.classList.toggle('hidden', !standard);
        wrap.classList.toggle('is-disabled', !standard);
        wrap.querySelectorAll('input, select').forEach((control) => {
            control.disabled = !standard;
        });
    }
}

function getDisplayEntries() {
    const manager = getFileManager();
    const keyword = String(state.search || '').trim().toLowerCase();
    const entries = keyword
        ? state.entries.filter(entry => String(entry.name || '').toLowerCase().includes(keyword))
        : state.entries;
    if (manager?.sortEntries) {
        return manager.sortEntries(entries, state.entrySort, {
            foldersFirst: true,
            entryFilter: 'all',
        });
    }
    const sortKey = ['name', 'size', 'modified_at'].includes(state.entrySort?.key) ? state.entrySort.key : 'name';
    const direction = state.entrySort?.direction === 'desc' ? -1 : 1;
    return entries.slice().sort((a, b) => {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
        let result = 0;
        if (sortKey === 'size') {
            result = (Number(a.size || 0) || 0) - (Number(b.size || 0) || 0);
        } else if (sortKey === 'modified_at') {
            result = parseEntryModifiedMs(a.modified_at) - parseEntryModifiedMs(b.modified_at);
        }
        if (result === 0) {
            result = String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans-CN');
        }
        return result * direction;
    });
}

function renderSortButton(key, label) {
    const active = state.entrySort?.key === key;
    const direction = active && state.entrySort?.direction === 'desc' ? 'desc' : 'asc';
    const nextDirection = active && direction === 'asc' ? 'desc' : 'asc';
    const indicator = active ? (direction === 'asc' ? '↑' : '↓') : '';
    return `
        <button
            type="button"
            class="scraper-sort-button ${active ? 'is-active' : ''}"
            data-scraper-sort="${escapeHtml(key)}"
            aria-label="按${escapeHtml(label)}${nextDirection === 'asc' ? '升序' : '降序'}排序"
            aria-pressed="${active ? 'true' : 'false'}"
        >
            <span>${escapeHtml(label)}</span>
            <span class="scraper-sort-indicator" aria-hidden="true">${escapeHtml(indicator)}</span>
        </button>
    `;
}

function setEntrySort(key) {
    const normalized = ['name', 'size', 'modified_at'].includes(String(key || '')) ? String(key) : 'name';
    if (state.entrySort.key === normalized) {
        state.entrySort = {
            key: normalized,
            direction: state.entrySort.direction === 'asc' ? 'desc' : 'asc',
        };
    } else {
        state.entrySort = { key: normalized, direction: 'asc' };
    }
    renderEntries();
}

function renderIdentifyPathSelection() {
    const candidates = $('scraper-candidate-list');
    if (!candidates) return;
    if (state.identifyBusy) {
        candidates.innerHTML = '<div class="scraper-empty-small">正在读取完整路径...</div>';
        return;
    }
    const selection = state.identifyPathSelection || createEmptyIdentifyPathSelection();
    const source = String(selection.source || '').trim();
    const tokens = Array.isArray(selection.tokens) ? selection.tokens : [];
    if (!source || !tokens.length) {
        candidates.innerHTML = '<div class="scraper-empty-small">当前选择没有可用的文件夹路径，可直接在下方输入影视名称。</div>';
        return;
    }
    const selectedIndexes = Array.isArray(selection.selectedIndexes) ? selection.selectedIndexes : [];
    const selected = new Set(selectedIndexes.map(Number));
    const query = window.ScraperPathSelection?.composeQuery(selection) || '';
    if (selection.expanded === false) {
        candidates.innerHTML = `
            <div class="scraper-path-selector is-collapsed">
                <div class="scraper-path-collapsed">
                    <div class="scraper-path-result">
                        <span>已填入搜索框</span>
                        <strong>${escapeHtml(query || '尚未选择标题')}</strong>
                    </div>
                    <button
                        type="button"
                        class="scraper-path-reselect"
                        data-scraper-action="reopen-path-selection"
                        title="重新选择 TMDB 搜索标题"
                        aria-label="重新选择 TMDB 搜索标题"
                    >
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M12 20h9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                            <path d="M16.5 3.5a2.12 2.12 0 013 3L8 18l-4 1 1-4L16.5 3.5z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                </div>
            </div>
        `;
        return;
    }
    candidates.innerHTML = `
        <div class="scraper-path-selector">
            <div class="scraper-path-heading">
                <span>完整路径</span>
                <span>${selected.size ? `已选择 ${selected.size} 个词块` : '请选择影视标题'}</span>
            </div>
            <div class="scraper-path-source" title="${escapeHtml(source)}">${escapeHtml(source)}</div>
            <div class="scraper-path-tokens" role="listbox" aria-label="完整路径标题选词">
                ${tokens.map((token, index) => `
                    <button
                        type="button"
                        class="scraper-path-token ${selected.has(index) ? 'is-selected' : ''}"
                        data-scraper-path-token-index="${index}"
                        role="option"
                        aria-selected="${selected.has(index) ? 'true' : 'false'}"
                    >${escapeHtml(token.text || '')}</button>
                `).join('')}
            </div>
            <div class="scraper-path-actions">
                <button type="button" class="scraper-compact-btn" data-scraper-action="clear-path-selection" ${selected.size ? '' : 'disabled'}>清空</button>
                <button type="button" class="scraper-compact-btn scraper-primary-soft" data-scraper-action="complete-path-selection" ${selected.size ? '' : 'disabled'}>完成选词</button>
            </div>
        </div>
    `;
}

function beginIdentifyPathSelection(event, index) {
    const selection = state.identifyPathSelection;
    const tokenIndex = Number(index);
    if (!selection || !Number.isInteger(tokenIndex) || tokenIndex < 0) return;
    event.preventDefault();
    const selectedIndexes = Array.isArray(selection.selectedIndexes) ? selection.selectedIndexes : [];
    state.identifyPathGesture = {
        pointerId: event.pointerId,
        startIndex: tokenIndex,
        lastIndex: tokenIndex,
        baseSelection: selectedIndexes.slice(),
        shouldSelect: !selectedIndexes.includes(tokenIndex),
    };
    selection.selectedIndexes = window.MediaHubTextSelection.applySelectionRange(
        state.identifyPathGesture.baseSelection,
        tokenIndex,
        tokenIndex,
        state.identifyPathGesture.shouldSelect
    );
    renderIdentifyPathSelection();
}

function continueIdentifyPathSelection(event, index) {
    const gesture = state.identifyPathGesture;
    const tokenIndex = Number(index);
    if (
        !gesture
        || gesture.pointerId !== event.pointerId
        || !Number.isInteger(tokenIndex)
        || tokenIndex < 0
        || gesture.lastIndex === tokenIndex
    ) return;
    gesture.lastIndex = tokenIndex;
    state.identifyPathSelection.selectedIndexes = window.MediaHubTextSelection.applySelectionRange(
        gesture.baseSelection,
        gesture.startIndex,
        tokenIndex,
        gesture.shouldSelect
    );
    renderIdentifyPathSelection();
}

function clearIdentifyPathSelection() {
    state.identifyPathSelection.selectedIndexes = [];
    state.identifyPathSelection.expanded = true;
    renderIdentifyPathSelection();
}

function completeIdentifyPathSelection() {
    const query = window.ScraperPathSelection?.composeQuery(state.identifyPathSelection) || '';
    if (!query) {
        showToast('请先选择影视标题文字', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    const input = $('scraper-manual-query');
    if (input) input.value = query;
    state.identifyPathSelection.expanded = false;
    state.manualResults = [];
    renderIdentify();
    if (input) {
        input.focus();
        input.setSelectionRange?.(query.length, query.length);
    }
}

function reopenIdentifyPathSelection() {
    if (!state.identifyPathSelection?.tokens?.length) return;
    state.identifyPathSelection.expanded = true;
    renderIdentifyPathSelection();
    requestAnimationFrame(() => {
        const container = $('scraper-candidate-list');
        container?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        const selectedIndex = state.identifyPathSelection.selectedIndexes?.[0] ?? 0;
        container?.querySelector(`[data-scraper-path-token-index="${selectedIndex}"]`)?.focus();
    });
}

function renderPoster(item = {}) {
    const posterUrl = String(item.poster_url || '').trim();
    if (posterUrl) {
        return `<img class="scraper-result-poster" src="${escapeHtml(posterUrl)}" alt="" loading="lazy">`;
    }
    return '<div class="scraper-result-poster is-empty">无封面</div>';
}

function renderIdentify() {
    const summary = $('scraper-identify-summary');
    const candidates = $('scraper-candidate-list');
    const manualResults = $('scraper-manual-results');
    const identifyResult = state.identifyResult || {};
    if (summary) {
        if (state.identifyBusy) {
            summary.textContent = '正在识别 TMDB 信息...';
        } else if (state.tmdb) {
            const typeLabel = (state.tmdb.tmdb_media_type || state.tmdb.media_type) === 'tv' ? '电视剧' : '电影';
            const seasonText = typeLabel === '电视剧' ? ` / 第 ${escapeHtml(String(Math.max(1, Number($('scraper-season')?.value || 1) || 1)))} 季 / ${escapeHtml(getEffectiveEpisodeModeLabel())}` : '';
            summary.innerHTML = `已绑定 <strong>${escapeHtml(typeLabel)} #${escapeHtml(String(state.tmdb.tmdb_id || state.tmdb.id || 0))}</strong>：${escapeHtml(getTmdbDisplayTitle())}${seasonText}`;
        } else if (identifyResult.msg) {
            summary.textContent = identifyResult.msg;
        } else if (identifyResult.query || state.identifyPathSelection?.source) {
            summary.textContent = '已读取所选资源的完整文件夹路径，请选择影视标题后搜索并绑定 TMDB。';
        } else {
            summary.textContent = '等待选择文件或文件夹。';
        }
    }
    if (candidates) renderIdentifyPathSelection();
    if (manualResults) {
        if (state.manualBusy) {
            manualResults.innerHTML = '<div class="scraper-empty-small">搜索中...</div>';
        } else if (!state.manualResults.length) {
            manualResults.innerHTML = '';
        } else {
            manualResults.innerHTML = state.manualResults.slice(0, 8).map((item, index) => {
                const typeLabel = item.media_type === 'tv' ? '电视剧' : '电影';
                const isBound = getBoundTmdbKey() && getBoundTmdbKey() === getManualResultTmdbKey(item);
                return `
                    <div class="scraper-manual-result">
                        ${renderPoster(item)}
                        <div class="scraper-manual-result-main">
                            <strong>${escapeHtml(item.title || '--')}</strong>
                            <span>${escapeHtml(typeLabel)}${item.year ? ` / ${escapeHtml(item.year)}` : ''}${item.vote_average ? ` / 评分 ${escapeHtml(String(item.vote_average))}` : ''}</span>
                            ${item.overview ? `<p>${escapeHtml(item.overview)}</p>` : ''}
                        </div>
                        <button type="button" class="scraper-compact-btn ${isBound ? 'scraper-manual-result-bound btn-disabled' : ''}" data-scraper-manual-index="${index}" ${isBound ? 'disabled aria-pressed="true"' : ''}>${isBound ? '已绑定' : '绑定'}</button>
                    </div>
                `;
            }).join('');
        }
    }
    syncSeasonControl();
    syncEpisodeModeControl();
    syncFileInfoControls();
    syncFolderScopedControls();
    syncFileNamingModeControls();
    syncBuildPlanControls();
}

function collectOptions() {
    const preserveTags = {};
    document.querySelectorAll('[data-scraper-tag]').forEach((input) => {
        preserveTags[String(input.dataset.scraperTag || '').trim()] = !!input.checked;
    });
    const selectionMode = getSelectionMode();
    const folderMode = selectionMode === 'folder';
    return {
        selection_mode: selectionMode,
        file_name_mode: String($('scraper-file-name-mode')?.value || 'standard'),
        title_language: String($('scraper-title-language')?.value || 'zh'),
        season: Math.max(1, Number($('scraper-season')?.value || 1) || 1),
        episode_mode: String($('scraper-episode-mode')?.value || 'auto'),
        include_tmdb_id: folderMode && !$('scraper-include-tmdb-id')?.disabled && !!$('scraper-include-tmdb-id')?.checked,
        use_season_subfolder: folderMode && !$('scraper-use-season-subfolder')?.disabled && !!$('scraper-use-season-subfolder')?.checked,
        rename_selected_folders: folderMode && !$('scraper-rename-selected-folders')?.disabled && !!$('scraper-rename-selected-folders')?.checked,
        preserve_file_info: !!$('scraper-preserve-file-info')?.checked,
        preserve_tags: preserveTags,
    };
}

function renderPlan() {
    const summary = $('scraper-plan-summary');
    const list = $('scraper-plan-list');
    const executeBtn = $('scraper-execute-btn');
    const plan = state.plan || null;
    const selectedReadyCount = getSelectedReadyPlanCount();
    syncBuildPlanControls();
    const clearPlanBtn = $('scraper-clear-plan-btn');
    if (clearPlanBtn) {
        const showClear = getPlanActions().length > 0;
        clearPlanBtn.classList.toggle('hidden', !showClear);
        clearPlanBtn.disabled = state.executeBusy || !showClear;
        clearPlanBtn.classList.toggle('btn-disabled', state.executeBusy || !showClear);
    }
    const inlineExecuteBtn = $('scraper-inline-execute-btn');
    if (inlineExecuteBtn) {
        const showExecute = getPlanActions().length > 0;
        inlineExecuteBtn.classList.toggle('hidden', !showExecute);
        const executeDisabled = state.executeBusy || selectedReadyCount <= 0 || !supportsProviderOperation('scrape');
        inlineExecuteBtn.disabled = executeDisabled;
        inlineExecuteBtn.classList.toggle('btn-disabled', executeDisabled);
        inlineExecuteBtn.textContent = state.executeBusy ? '提交中...' : `执行重命名 ${selectedReadyCount} 项`;
    }
    if (executeBtn) {
        const executeDisabled = state.executeBusy || selectedReadyCount <= 0 || !supportsProviderOperation('scrape');
        executeBtn.disabled = executeDisabled;
        executeBtn.classList.toggle('btn-disabled', executeDisabled);
        executeBtn.textContent = state.executeBusy ? '提交中...' : `执行重命名 ${selectedReadyCount} 项`;
    }
    if (!summary || !list) return;
    if (state.planBusy) {
        summary.textContent = '正在识别文件并生成预览，请稍候...';
        list.innerHTML = '<div class="scraper-empty-row">识别中，请稍候...</div>';
        return;
    }
    if (!plan) {
        summary.textContent = '生成预览后会显示旧路径、新路径、识别依据和冲突状态。';
        list.innerHTML = '';
        return;
    }
    const total = Number(plan.total_count || 0);
    const ready = Number(plan.ready_count || 0);
    const unchanged = Number(plan.unchanged_count || 0);
    const issues = Array.isArray(plan.issues) ? plan.issues : [];
    const warnings = Array.isArray(plan.warnings) ? plan.warnings : [];
    if (total === 0 && unchanged > 0) {
        summary.innerHTML = `
            <span class="scraper-ok-text">无需改名</span>
            <span> / 已跳过 ${escapeHtml(String(unchanged))} 项无变化文件</span>
        `;
    } else {
        summary.innerHTML = `
            <span class="${ready > 0 ? 'scraper-ok-text' : 'scraper-warn-text'}">${ready > 0 ? '可执行' : '需要处理'}</span>
            <span> / 已勾选 ${escapeHtml(String(selectedReadyCount))} 项，${escapeHtml(String(ready))} / ${escapeHtml(String(total))} 项可执行${unchanged > 0 ? ` / 已跳过 ${escapeHtml(String(unchanged))} 项无变化` : ''}${issues.length ? ` / ${escapeHtml(String(issues.length))} 个冲突` : ''}${warnings.length ? ` / ${escapeHtml(String(warnings.length))} 个提醒` : ''}</span>
        `;
    }
    const actions = Array.isArray(plan.actions) ? plan.actions : [];
    if (!actions.length) {
        list.innerHTML = '<div class="scraper-empty-row">没有需要改名的文件。</div>';
        return;
    }
    list.innerHTML = '';
}

function getJobStatusLabel(status) {
    const normalized = String(status || '').trim();
    const labels = {
        pending: '等待中',
        running: '执行中',
        completed: '已完成',
        partial: '部分完成',
        failed: '失败',
        rollback_running: '回退中',
        rolled_back: '已回退',
        rollback_failed: '回退失败',
    };
    return labels[normalized] || normalized || '--';
}

function renderJobs() {
    const list = $('scraper-job-list');
    if (!list) return;
    if (state.jobsBusy && !state.jobs.length) {
        list.innerHTML = '<div class="scraper-empty-row">正在读取任务记录...</div>';
        return;
    }
    if (!state.jobs.length) {
        list.innerHTML = '<div class="scraper-empty-row">暂无刮削任务记录。</div>';
        return;
    }
    const rowsHtml = state.jobs.map((job) => {
        const actions = Array.isArray(job.actions) ? job.actions : [];
        const actionPreview = actions.slice(0, 4).map(action => `
            <div class="scraper-job-action">
                <span>${escapeHtml(getJobStatusLabel(action.rollback_status || action.status))}</span>
                <span>${escapeHtml(action.new_path || action.old_path || action.old_name || '--')}</span>
            </div>
        `).join('');
        return `
            <div class="scraper-job-card">
                <div class="scraper-job-head">
                    <div>
                        <strong>#${escapeHtml(String(job.id || 0))} ${escapeHtml(getProviderLabel(job.provider))} · ${escapeHtml(getJobStatusLabel(job.status))}</strong>
                        <span>${escapeHtml(job.status_detail || '')}</span>
                    </div>
                    <div class="scraper-job-actions">
                        ${job.can_rollback ? `<button type="button" class="scraper-compact-btn" data-scraper-rollback-job="${escapeHtml(String(job.id || 0))}">回退</button>` : ''}
                    </div>
                </div>
                <div class="scraper-job-meta">
                    <span>成功 ${escapeHtml(String(job.succeeded_actions || 0))}</span>
                    <span>失败 ${escapeHtml(String(job.failed_actions || 0))}</span>
                    <span>${escapeHtml(formatTimeText(job.created_at))}</span>
                    <span>${escapeHtml(getTmdbDisplayTitle(job.tmdb || {}))}</span>
                </div>
                ${actionPreview ? `<div class="scraper-job-action-list">${actionPreview}</div>` : ''}
            </div>
        `;
    }).join('');
    const pagination = state.jobsPagination || {};
    const total = Number(pagination.total || 0) || 0;
    const totalPages = Math.max(1, Number(pagination.total_pages || 1) || 1);
    const page = Math.max(1, Number(pagination.page || state.jobsPage || 1) || 1);
    const paginationHtml = total > 0 ? `
        <div class="resource-browser-load-more-row">
            <div class="resource-job-pagination-controls">
            <button type="button" data-scraper-action="jobs-page-prev" class="resource-browser-load-more-btn" ${page <= 1 ? 'disabled' : ''}>上一页</button>
            <div class="resource-job-pagination-pages resource-job-pagination-pages-desktop" aria-label="刮削任务页码">${renderJobPageButtons(page, totalPages, 5)}</div>
            <div class="resource-job-pagination-pages resource-job-pagination-pages-mobile" aria-label="刮削任务页码">${renderJobPageButtons(page, totalPages, 3)}</div>
            <button type="button" data-scraper-action="jobs-page-next" class="resource-browser-load-more-btn" ${page >= totalPages ? 'disabled' : ''}>下一页</button>
            </div>
            <span class="resource-job-pagination-label">共 ${escapeHtml(String(total))} 条</span>
        </div>
    ` : '';
    list.innerHTML = `${rowsHtml}${paginationHtml}`;
}

function applyProvidersFromMeta() {
    const providers = getScraperProviderOptions();
    if (!providers.length) return false;
    state.providers = providers;
    const current = providers.find(item => normalizeProvider(item.provider) === state.provider);
    if (!current) state.provider = normalizeProvider(providers[0].provider);
    renderProviderTabs();
    renderProviderStatus();
    return true;
}

async function loadProviders() {
    applyProvidersFromMeta();
    try {
        const data = await window.MediaHubApi.getJson('/scraper/providers');
        state.providersLoaded = true;
        state.providers = (Array.isArray(data.providers) ? data.providers : []).map(item => ({
            ...item,
            configuredKnown: true,
        }));
        const current = state.providers.find(item => normalizeProvider(item.provider) === state.provider);
        if (!current && state.providers.length) {
            state.provider = normalizeProvider(state.providers[0].provider);
        }
    } catch (error) {
        state.providersLoaded = false;
        if (!state.providers.length) applyProvidersFromMeta();
        showToast(`读取网盘列表失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
    }
    renderProviderTabs();
    renderProviderStatus();
}

async function loadEntries({ force = false, keepSearch = true, more = false } = {}) {
    if (more) {
        state.loadingMore = true;
    } else {
        state.loading = true;
    }
    state.entryError = '';
    renderEntries();
    try {
        const params = new URLSearchParams({ cid: state.cid });
        if (force) params.set('force_refresh', '1');
        if (keepSearch && state.search) params.set('q', state.search);
        params.set('offset', String(more ? (state.nextOffset || 0) : 0));
        params.set('limit', String(SCRAPER_ENTRY_PAGE_LIMIT));
        const data = await window.MediaHubApi.getJson(`/scraper/${encodeURIComponent(state.provider)}/entries?${params.toString()}`);
        const incoming = (Array.isArray(data.entries) ? data.entries : []).map(enrichEntry);
        if (more) {
            state.entries = state.entries.concat(incoming);
        } else {
            state.entries = incoming;
            clearSelection();
            resetIdentifyContext({ resetInputs: true });
        }
        const incomingFolders = incoming.filter(entry => entry.is_dir).length;
        const incomingFiles = incoming.length - incomingFolders;
        if (more) {
            state.summary = {
                folder_count: Number(state.summary.folder_count || 0) + incomingFolders,
                file_count: Number(state.summary.file_count || 0) + incomingFiles,
            };
        } else {
            const pageSummary = data.summary || { folder_count: 0, file_count: 0 };
            state.summary = {
                folder_count: Math.max(incomingFolders, Number(pageSummary.folder_count || 0)),
                file_count: Math.max(incomingFiles, Number(pageSummary.file_count || 0)),
            };
        }
        state.nextOffset = Number(data.next_offset ?? (more ? state.nextOffset : incoming.length)) || 0;
        state.hasMore = !!data.has_more;
        state.entryError = '';
    } catch (error) {
        if (more) {
            showToast(`加载更多条目失败：${error.message || '请稍后重试'}`, { tone: 'warn', duration: 3200, placement: 'top-center' });
        } else {
            state.entries = [];
            state.summary = { folder_count: 0, file_count: 0 };
            state.nextOffset = 0;
            state.hasMore = false;
            state.entryError = error.message || '未知错误';
            showToast(`读取目录失败：${state.entryError}`, { tone: 'error', duration: 3200, placement: 'top-center' });
        }
    } finally {
        state.loading = false;
        state.loadingMore = false;
        renderEntries();
        requestAnimationFrame(syncScraperBrowserHeight);
    }
}

async function switchProvider(provider) {
    const nextProvider = normalizeProvider(provider);
    if (state.provider === nextProvider) return;
    state.provider = nextProvider;
    state.cid = '0';
    state.trail = [{ id: '0', name: '根目录' }];
    state.search = '';
    $('scraper-search-input').value = '';
    clearSelection();
    clearPlan();
    resetIdentifyContext({ resetInputs: true });
    closeIdentifyPanel();
    renderProviderTabs();
    renderIdentify();
    await loadBatchPreferences();
    await loadEntries();
    syncScraperLocationHash();
}

async function enterFolder(entryId) {
    if (state.loading || state.navigationBusy) return;
    const entry = state.entries.find(item => item.id === String(entryId || ''));
    if (!entry || !entry.is_dir) return;
    const nextCid = normalizeCid(entry.cid || entry.id);
    if (!nextCid || normalizeCid(state.cid) === nextCid) return;
    state.navigationBusy = true;
    try {
        state.cid = nextCid;
        if (entry.search_result) {
            // 搜索结果来自网盘任意位置：先向服务端补查真实祖先链，恢复完整路径栏；
            // 查询失败时退回“根目录 / 该文件夹”，避免把结果误挂到当前目录下。
            const resolved = await resolveSearchFolderPath(entry, nextCid);
            state.trail = resolved.resolved
                ? [{ id: '0', name: '根目录' }, ...resolved.ancestors]
                : [{ id: '0', name: '根目录' }, { id: state.cid, name: entry.name, searchJump: true }];
        } else {
            state.trail = state.trail.concat([{ id: state.cid, name: entry.name }]);
        }
        state.search = '';
        $('scraper-search-input').value = '';
        clearPlan();
        resetIdentifyContext({ resetInputs: true });
        closeIdentifyPanel();
        await loadEntries({ keepSearch: false });
    } finally {
        state.navigationBusy = false;
        renderEntries();
    }
    syncScraperLocationHash();
}

async function resolveSearchFolderPath(entry, cid) {
    try {
        const data = await window.MediaHubApi.getJson(
            `/scraper/${encodeURIComponent(state.provider)}/folder-path?cid=${encodeURIComponent(cid)}`
        );
        const ancestors = (Array.isArray(data.ancestors) ? data.ancestors : [])
            .map(item => item && typeof item === 'object' ? {
                id: String(item.id || item.cid || '').trim(),
                name: String(item.name || '').trim(),
            } : null)
            .filter(item => item && item.id && item.name && item.id !== '0');
        const normalizedCid = String(cid || '').trim();
        const lastAncestor = ancestors[ancestors.length - 1] || null;
        if (lastAncestor && lastAncestor.id === normalizedCid) {
            return { ancestors, resolved: true };
        }
        // 接口偶尔只返回上级链时，把当前目录补在末尾，保证路径栏完整可点击。
        const folderName = String(entry?.name || '').trim();
        if (!folderName) return { ancestors: [], resolved: false };
        return {
            ancestors: ancestors.concat([{ id: normalizedCid, name: folderName }]),
            resolved: true,
        };
    } catch (error) {
        return { ancestors: [], resolved: false };
    }
}

async function goTrail(index) {
    if (state.loading || state.navigationBusy) return;
    const targetIndex = Math.max(0, Number(index || 0) || 0);
    const target = state.trail[targetIndex] || state.trail[0];
    if (normalizeCid(target.id) === normalizeCid(state.cid) && targetIndex === state.trail.length - 1) return;
    state.navigationBusy = true;
    try {
        state.trail = state.trail.slice(0, targetIndex + 1);
        state.cid = normalizeCid(target.id);
        state.search = '';
        $('scraper-search-input').value = '';
        clearPlan();
        resetIdentifyContext({ resetInputs: true });
        closeIdentifyPanel();
        await loadEntries({ keepSearch: false });
    } finally {
        state.navigationBusy = false;
        renderEntries();
    }
    syncScraperLocationHash();
}

async function createFolder() {
    const input = $('scraper-new-folder-name');
    const name = String(input?.value || '').trim();
    if (!name) {
        showToast('请先输入文件夹名称', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    try {
        const data = await window.MediaHubApi.postJson(`/scraper/${encodeURIComponent(state.provider)}/folders`, {
            cid: state.cid,
            name,
            parent_path: currentParentPath(),
            request_id: buildMutationRequestId(),
        });
        if (input) input.value = '';
        closeToolPopovers();
        showToast(withMonitorSyncResult('文件夹已创建', data), { tone: 'success', duration: 2600, placement: 'top-center' });
        await loadEntries({ force: true });
    } catch (error) {
        showToast(`新建失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
    }
}

async function renameSelected() {
    const selected = getEffectiveSelectedEntries();
    if (selected.length !== 1) {
        showToast('请选择一个文件或文件夹进行重命名', { tone: 'warn', duration: 2400, placement: 'top-center' });
        return;
    }
    if (hasUnknownSearchResultEntries(selected)) {
        showToast('搜索结果真实路径未知，请先进入该文件夹后再重命名', { tone: 'warn', duration: 3000, placement: 'top-center' });
        return;
    }
    const target = selected[0];
    const targetLabel = target.is_dir ? '文件夹' : '文件';
    const name = await promptText({
        title: `重命名${targetLabel}`,
        message: target.name,
        defaultValue: target.name,
        confirmText: '保存',
    });
    if (!name || name === target.name) return;
    const oldPath = getSelectionPath(target);
    const newPath = normalizePath(joinPath(getSelectionParentPath(target), name));
    try {
        if (target.is_dir && oldPath && newPath) {
            let warning = '';
            try {
                const warningData = await window.MediaHubApi.postJson(`/scraper/${encodeURIComponent(state.provider)}/rename-warning`, {
                    old_path: oldPath,
                    new_path: newPath,
                });
                warning = String(warningData?.warning || '').trim();
            } catch (error) {
                showToast(`检查订阅保存路径失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return;
            }
            if (warning) {
                const ok = await showConfirm(warning, {
                    title: '路径提醒',
                    confirmText: '继续重命名',
                });
                if (!ok) return;
            }
        }
        const data = await window.MediaHubApi.postJson(`/scraper/${encodeURIComponent(state.provider)}/rename`, {
            entry_id: target.id,
            parent_id: target.parent_id || state.cid,
            name,
            entry: buildMonitorEntrySnapshot(target),
            request_id: buildMutationRequestId(),
        });
        showToast(withMonitorSyncResult(`${targetLabel}已重命名`, data), { tone: 'success', duration: 2800, placement: 'top-center' });
        await loadEntries({ force: true });
    } catch (error) {
        showToast(`重命名失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
    }
}

function prepareMove() {
    const selected = getEffectiveSelectedEntries();
    if (!selected.length) {
        showToast('请先选择要移动的条目', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    if (hasUnknownSearchResultEntries(selected)) {
        showToast('搜索结果真实路径未知，请先进入该文件夹后再移动', { tone: 'warn', duration: 3000, placement: 'top-center' });
        return;
    }
    state.copyBuffer = null;
    state.moveBuffer = {
        provider: state.provider,
        source_cid: state.cid,
        source_path: currentParentPath() || '根目录',
        entries: selected,
    };
    clearSelection();
    renderEntries();
    showToast('已记录待移动条目，请进入目标目录后执行移动', { tone: 'info', duration: 3000, placement: 'top-center' });
}

function prepareCopy() {
    const selected = getEffectiveSelectedEntries();
    if (!selected.length) {
        showToast('请先选择要复制的条目', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    if (hasUnknownSearchResultEntries(selected)) {
        showToast('搜索结果真实路径未知，请先进入该文件夹后再复制', { tone: 'warn', duration: 3000, placement: 'top-center' });
        return;
    }
    state.moveBuffer = null;
    state.copyBuffer = {
        provider: state.provider,
        source_cid: state.cid,
        source_path: currentParentPath() || '根目录',
        entries: selected,
    };
    clearSelection();
    renderEntries();
    showToast('已记录待复制条目，请进入目标目录后执行复制', { tone: 'info', duration: 3000, placement: 'top-center' });
}

async function moveHere() {
    const buffer = state.moveBuffer;
    if (!buffer || !buffer.entries?.length) return;
    if (buffer.provider !== state.provider) {
        showToast('待移动条目与当前网盘不一致', { tone: 'warn', duration: 2600, placement: 'top-center' });
        return;
    }
    if (normalizeCid(buffer.source_cid) === normalizeCid(state.cid)) {
        showToast('目标目录与来源目录相同', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    const ok = await showConfirm(`将 ${buffer.entries.length} 个条目移动到当前目录，确定继续吗？`, {
        title: '确认移动',
        confirmText: '移动',
    });
    if (!ok) return;
    try {
        const data = await window.MediaHubApi.postJson(`/scraper/${encodeURIComponent(state.provider)}/move`, {
            entry_ids: buffer.entries.map(item => item.id),
            source_cid: buffer.source_cid,
            target_cid: state.cid,
            entries: buffer.entries.map(buildMonitorEntrySnapshot),
            target_parent_path: currentParentPath(),
            request_id: buildMutationRequestId(),
        });
        state.moveBuffer = null;
        showToast(withMonitorSyncResult('移动已完成', data), { tone: 'success', duration: 2800, placement: 'top-center' });
        await loadEntries({ force: true });
    } catch (error) {
        showToast(`移动失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
    }
}

async function copyHere() {
    const buffer = state.copyBuffer;
    if (!buffer || !buffer.entries?.length) return;
    if (buffer.provider !== state.provider) {
        showToast('待复制条目与当前网盘不一致', { tone: 'warn', duration: 2600, placement: 'top-center' });
        return;
    }
    if (normalizeCid(buffer.source_cid) === normalizeCid(state.cid)) {
        showToast('目标目录与来源目录相同', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    const ok = await showConfirm(`将 ${buffer.entries.length} 个条目复制到当前目录，确定继续吗？`, {
        title: '确认复制',
        confirmText: '复制',
    });
    if (!ok) return;
    try {
        const data = await window.MediaHubApi.postJson(`/scraper/${encodeURIComponent(state.provider)}/copy`, {
            entry_ids: buffer.entries.map(item => item.id),
            source_cid: buffer.source_cid,
            target_cid: state.cid,
            entries: buffer.entries.map(buildMonitorEntrySnapshot),
            target_parent_path: currentParentPath(),
            request_id: buildMutationRequestId(),
        });
        state.copyBuffer = null;
        showToast(withMonitorSyncResult('复制已完成', data), { tone: 'success', duration: 2800, placement: 'top-center' });
        await loadEntries({ force: true });
    } catch (error) {
        showToast(`复制失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
    }
}

async function deleteSelected() {
    const selected = getEffectiveSelectedEntries();
    if (!selected.length) {
        showToast('请先选择要删除的条目', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    if (hasUnknownSearchResultEntries(selected)) {
        showToast('搜索结果真实路径未知，请先进入该文件夹后再删除', { tone: 'warn', duration: 3000, placement: 'top-center' });
        return;
    }
    const ok = await showConfirm(`确定删除 ${selected.length} 个条目吗？删除不纳入刮削任务回退。`, {
        title: '确认删除',
        confirmText: '删除',
        tone: 'error',
    });
    if (!ok) return;
    try {
        const data = await window.MediaHubApi.postJson(`/scraper/${encodeURIComponent(state.provider)}/delete`, {
            entry_ids: selected.map(item => item.id),
            parent_id: state.cid,
            entries: selected.map(buildMonitorEntrySnapshot),
            request_id: buildMutationRequestId(),
        });
        showToast(withMonitorSyncResult('已删除选中条目', data), { tone: 'success', duration: 2800, placement: 'top-center' });
        await loadEntries({ force: true });
    } catch (error) {
        showToast(`删除失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
    }
}

async function identifySelected() {
    const entries = getEffectiveSelectedEntries();
    if (!entries.length) {
        showToast('请先选择要识别的文件或文件夹', { tone: 'warn', duration: 2400, placement: 'top-center' });
        return;
    }
    const selectionKey = getSelectionKey(entries);
    if ((state.identifyResult || state.tmdb) && state.identifySelectionKey === selectionKey) {
        openIdentifyPanel();
        renderIdentify();
        return;
    }
    resetIdentifyContext({ resetInputs: true });
    state.identifyPathSelection = createIdentifyPathSelection(entries);
    state.identifyBusy = true;
    state.identifySelectionKey = selectionKey;
    clearPlan();
    const requestSeq = state.identifyRequestSeq;
    openIdentifyPanel();
    renderIdentify();
    try {
        const data = await window.MediaHubApi.postJson('/scraper/identify', {
            provider: state.provider,
            entries,
        });
        if (state.identifyRequestSeq !== requestSeq) return;
        state.identifyResult = data || {};
        state.tmdb = null;
        state.identifySelectionKey = selectionKey;
        applyIdentifyManualSearchDefaults(data || {});
        showToast('请选择完整路径中的影视标题，再搜索并绑定 TMDB 条目', {
            tone: 'info',
            duration: 2600,
            placement: 'top-center',
        });
    } catch (error) {
        if (state.identifyRequestSeq !== requestSeq) return;
        state.identifyResult = { msg: error.message || '识别失败' };
        state.identifySelectionKey = selectionKey;
        showToast(`识别失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
    } finally {
        if (state.identifyRequestSeq === requestSeq) {
            state.identifyBusy = false;
            renderIdentify();
        }
    }
}

async function bindTmdbCandidate(item) {
    if (!item) return;
    try {
        const mediaType = item.media_type === 'tv' ? 'tv' : 'movie';
        const params = new URLSearchParams({
            tmdb_id: String(item.id || item.tmdb_id || 0),
            media_type: mediaType,
        });
        const data = await window.MediaHubApi.getJson(`/tmdb/detail?${params.toString()}`);
        state.tmdb = data.task_binding || null;
        if (state.tmdb?.tmdb_media_type) {
            const mediaSelect = $('scraper-manual-media-type');
            if (mediaSelect) mediaSelect.value = state.tmdb.tmdb_media_type === 'tv' ? 'tv' : 'movie';
            state.manualMediaTypeTouched = false;
            const seasonInput = $('scraper-season');
            if (seasonInput && state.tmdb.tmdb_media_type === 'tv') {
                const maxSeason = getTmdbSeasonCount(state.tmdb);
                seasonInput.value = String(Math.min(Math.max(1, Number(seasonInput.value || 1) || 1), maxSeason || 99));
            }
        }
        clearPlan();
        state.identifySelectionKey = getSelectionKey();
        renderIdentify();
        renderSelection();
        showToast(`已绑定 TMDB：${getTmdbDisplayTitle()}`, { tone: 'success', duration: 2600, placement: 'top-center' });
    } catch (error) {
        showToast(`读取 TMDB 详情失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
    }
}

async function manualSearchTmdb() {
    const query = String($('scraper-manual-query')?.value || '').trim();
    if (!query) {
        showToast('请先输入影视名称', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    const mediaType = $('scraper-manual-media-type')?.value === 'tv' ? 'tv' : 'movie';
    state.manualBusy = true;
    state.manualResults = [];
    renderIdentify();
    try {
        state.manualResults = await fetchTmdbSearch(query, mediaType);
        if (!state.manualResults.length) {
            showToast('未找到 TMDB 条目', { tone: 'warn', duration: 2400, placement: 'top-center' });
        }
    } catch (error) {
        showToast(`TMDB 搜索失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
    } finally {
        state.manualBusy = false;
        renderIdentify();
    }
}

function collectBatchOptions() {
    const preserveTags = {};
    document.querySelectorAll('[data-scraper-tag]').forEach((input) => {
        preserveTags[String(input.dataset.scraperTag || '').trim()] = !!input.checked;
    });
    return {
        selection_mode: 'batch',
        file_name_mode: String($('scraper-file-name-mode')?.value || 'standard'),
        title_language: String($('scraper-title-language')?.value || 'zh'),
        season: Math.max(1, Number($('scraper-season')?.value || 1) || 1),
        episode_mode: String($('scraper-episode-mode')?.value || 'auto'),
        include_tmdb_id: !!$('scraper-include-tmdb-id')?.checked,
        use_season_subfolder: $('scraper-use-season-subfolder')?.checked !== false,
        rename_selected_folders: $('scraper-rename-selected-folders')?.checked !== false,
        delete_ad_files: !!$('scraper-delete-ad-files')?.checked,
        preserve_file_info: !!$('scraper-preserve-file-info')?.checked,
        preserve_tags: preserveTags,
    };
}

function applyBatchPreferences(prefs = {}) {
    const options = (prefs && typeof prefs === 'object' ? prefs.options : {}) || {};
    const setCheck = (id, value) => {
        const input = $(id);
        if (input) input.checked = !!value;
    };
    const setSelect = (id, value, allowed) => {
        const select = $(id);
        if (select) select.value = allowed.includes(String(value || '')) ? String(value) : allowed[0];
    };
    setCheck('scraper-include-tmdb-id', options.include_tmdb_id);
    setCheck('scraper-use-season-subfolder', options.use_season_subfolder !== false);
    setCheck('scraper-rename-selected-folders', options.rename_selected_folders !== false);
    setCheck('scraper-delete-ad-files', options.delete_ad_files);
    setCheck('scraper-preserve-file-info', options.preserve_file_info);
    setSelect('scraper-file-name-mode', options.file_name_mode, ['standard', 'clean', 'keep']);
    setSelect('scraper-title-language', options.title_language, ['auto', 'zh', 'en']);
    setSelect('scraper-episode-mode', options.episode_mode, ['auto', 'seasonal', 'absolute']);
    const seasonInput = $('scraper-season');
    if (seasonInput) {
        seasonInput.value = String(Math.max(1, Math.min(99, Number(options.season || 1) || 1)));
    }
    const tags = (options.preserve_tags && typeof options.preserve_tags === 'object') ? options.preserve_tags : {};
    document.querySelectorAll('[data-scraper-tag]').forEach((input) => {
        const key = String(input.dataset.scraperTag || '').trim();
        if (Object.prototype.hasOwnProperty.call(tags, key)) {
            input.checked = !!tags[key];
        }
    });
    const splitMode = String(options.split_mode || 'auto').trim();
    state.batchSplitMode = ['single', 'split'].includes(splitMode) ? splitMode : 'auto';
    syncFileInfoControls();
    syncBatchOptionControls();
    syncFileNamingModeControls();
    renderBatchSplitMode();
}

async function loadBatchPreferences() {
    const provider = normalizeProvider(state.provider);
    if (!provider) return;
    if (state.batchPreferenceProvider === provider && state.batchPreferencesLoaded) return;
    state.batchPreferenceProvider = provider;
    state.batchPreferencesLoaded = false;
    try {
        const data = await window.MediaHubApi.getJson(`/scraper/${encodeURIComponent(provider)}/batch/preferences`);
        state.batchPreferencesLoaded = true;
        applyBatchPreferences(data || {});
    } catch (error) {
        // 偏好加载失败不阻塞批量整理，沿用当前控件值。
        state.batchPreferencesLoaded = false;
    }
}

async function persistBatchPreferences() {
    const provider = normalizeProvider(state.provider);
    if (!provider || !state.batchPreferencesLoaded) return;
    try {
        await window.MediaHubApi.postJson(`/scraper/${encodeURIComponent(provider)}/batch/preferences`, {
            options: {
                ...collectBatchOptions(),
                split_mode: state.batchSplitMode || 'auto',
            },
        });
    } catch (error) {
        // 保存失败静默处理，避免打断用户操作。
    }
}

function scheduleBatchPreferenceSave() {
    if (!state.batchPreferencesLoaded) return;
    if (state.batchPreferenceSaveTimer) clearTimeout(state.batchPreferenceSaveTimer);
    state.batchPreferenceSaveTimer = setTimeout(() => {
        state.batchPreferenceSaveTimer = null;
        void persistBatchPreferences();
    }, 400);
}

async function resetBatchPreferences() {
    const provider = normalizeProvider(state.provider);
    if (!provider) return;
    try {
        await window.MediaHubApi.postJson(`/scraper/${encodeURIComponent(provider)}/batch/preferences`, {
            options: {},
        });
    } catch (error) {
        // 清除失败不阻塞恢复默认。
    }
    state.batchPreferencesLoaded = true;
    applyBatchPreferences({});
    showToast('已恢复默认选项', { tone: 'success', duration: 2400, placement: 'top-center' });
}

function resetBatchContext() {
    state.batchBusy = false;
    state.batchScan = null;
    state.batchIdentify = null;
    state.batchBindings = {};
    state.batchIncluded = new Set();
    state.batchSearchState = {};
    state.batchSplitMode = 'auto';
    state.batchError = '';
    state.batchSelection = [];
}

function openBatchPanel() {
    if (!supportsProviderOperation('scrape')) {
        showToast(`${getProviderLabel()} 暂不支持批量整理`, { tone: 'warn', duration: 2400, placement: 'top-center' });
        return;
    }
    if (!state.batchPreferencesLoaded) void loadBatchPreferences();
    const entries = getEffectiveSelectedEntries();
    if (!entries.length) {
        showToast('请先勾选要整理的文件夹或文件（可全选当前目录）', { tone: 'warn', duration: 2800, placement: 'top-center' });
        return;
    }
    const panel = $('scraper-batch-panel');
    if (!panel) return;
    panel.classList.remove('hidden');
    panel.classList.add('is-open');
    resetBatchContext();
    state.batchSelection = entries;
    void scanBatch(entries);
}

function closeBatchPanel() {
    const panel = $('scraper-batch-panel');
    if (!panel) return;
    panel.classList.add('hidden');
    panel.classList.remove('is-open');
}

function reopenBatchPanel() {
    const panel = $('scraper-batch-panel');
    if (!panel) return;
    const items = Array.isArray(state.batchScan?.items) ? state.batchScan.items : [];
    if (!items.length) {
        openBatchPanel();
        return;
    }
    // 保留已识别的条目与绑定，直接回到批量识别界面继续改绑。
    panel.classList.remove('hidden');
    panel.classList.add('is-open');
    renderBatch();
}

function setBatchSplitMode(mode) {
    const normalized = mode === 'single' || mode === 'split' ? mode : 'auto';
    if (state.batchSplitMode === normalized) return;
    state.batchSplitMode = normalized;
    renderBatchSplitMode();
    scheduleBatchPreferenceSave();
    if (state.batchSelection.length && !state.batchBusy) {
        void scanBatch();
    }
}

function renderBatchSplitMode() {
    const mode = state.batchSplitMode || 'auto';
    const text = $('scraper-split-mode-text');
    if (text) {
        text.textContent = mode === 'single' ? '整个文件夹' : (mode === 'split' ? '按子目录拆分' : '自动判断');
    }
    document.querySelectorAll('[data-split-mode]').forEach((button) => {
        const active = String(button.dataset.splitMode || '').trim() === mode;
        button.classList.toggle('is-active', active);
        button.classList.toggle('is-auto', mode === 'auto');
    });
}

function getBatchItem(itemIndex) {
    const items = Array.isArray(state.batchScan?.items) ? state.batchScan.items : [];
    return items.find(item => Number(item.item_index || 0) === Number(itemIndex || 0)) || null;
}

function getBatchIdentify(itemIndex) {
    const results = Array.isArray(state.batchIdentify) ? state.batchIdentify : [];
    return results.find(item => Number(item.item_index || 0) === Number(itemIndex || 0)) || null;
}

function getBatchBinding(itemIndex) {
    return state.batchBindings[String(Number(itemIndex || 0))] || null;
}

function getBatchCandidateTitle(candidate = {}) {
    const title = candidate.tmdb_title || candidate.title || candidate.original_title || '';
    const year = candidate.tmdb_year || candidate.year || '';
    return `${title || '--'}${year ? ` (${year})` : ''}`;
}

function setBatchBinding(itemIndex, candidate) {
    const index = Number(itemIndex || 0);
    if (!candidate || index <= 0) return;
    state.batchBindings[String(index)] = candidate;
    state.batchIncluded.add(index);
}

async function scanBatch(entries) {
    if (state.batchBusy) return;
    const selectedEntries = (Array.isArray(entries) && entries.length ? entries : state.batchSelection) || [];
    if (!selectedEntries.length) {
        showToast('请先勾选要整理的文件夹或文件', { tone: 'warn', duration: 2600, placement: 'top-center' });
        return;
    }
    state.batchBusy = true;
    const summary = $('scraper-batch-summary');
    if (summary) summary.textContent = `正在整理勾选的 ${selectedEntries.length} 个条目并识别...`;
    renderBatch();
    try {
        const data = await window.MediaHubApi.postJson('/scraper/batch/scan', {
            provider: state.provider,
            cid: state.cid,
            base_path: currentParentPath(),
            selected: selectedEntries,
            split_mode: state.batchSplitMode || 'auto',
        });
        state.batchScan = data || {};
        state.batchIdentify = null;
        state.batchBindings = {};
        state.batchIncluded = new Set();
        state.batchSearchState = {};
        await identifyBatch();
    } catch (error) {
        state.batchError = error.message || '未知错误';
        if (summary) summary.textContent = `扫描失败：${error.message || '未知错误'}`;
        showToast(`批量扫描失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
    } finally {
        state.batchBusy = false;
        renderBatch();
    }
}

async function identifyBatch() {
    const items = Array.isArray(state.batchScan?.items) ? state.batchScan.items : [];
    if (!items.length) return;
    state.batchBusy = true;
    renderBatch();
    try {
        const data = await window.MediaHubApi.postJson('/scraper/batch/identify', {
            provider: state.provider,
            items: items.map(item => ({
                item_index: Number(item.item_index || 0),
                name: item.name,
                entry: item.entry,
                files: Array.isArray(item.files) ? item.files.slice(0, 40) : [],
            })),
        });
        state.batchIdentify = Array.isArray(data.results) ? data.results : [];
        for (const result of state.batchIdentify) {
            if (result?.ok && result.auto_pick) {
                const index = Number(result.item_index || 0);
                if (index > 0) {
                    state.batchBindings[String(index)] = result.auto_pick;
                    state.batchIncluded.add(index);
                }
            }
        }
    } catch (error) {
        showToast(`自动识别失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
    } finally {
        state.batchBusy = false;
        renderBatch();
    }
}

function renderBatchItemSearch(itemIndex) {
    const index = Number(itemIndex || 0);
    const searchState = state.batchSearchState[String(index)] || {};
    if (!searchState.open) return '';
    const query = String(searchState.query ?? '');
    const mediaType = searchState.mediaType === 'tv' ? 'tv' : 'movie';
    const results = Array.isArray(searchState.results) ? searchState.results : [];
    const busy = !!searchState.busy;
    const pathHtml = renderBatchPathSelection(index);
    const resultHtml = busy
        ? '<div class="scraper-empty-small">搜索中...</div>'
        : (results.length
            ? results.map((candidate, candidateIndex) => `
                <div class="scraper-batch-result">
                    ${renderPoster(candidate)}
                    <div class="scraper-batch-result-main">
                        <strong title="${escapeHtml(getBatchCandidateTitle(candidate))}">${escapeHtml(getBatchCandidateTitle(candidate))}</strong>
                        <span>${candidate.media_type === 'tv' ? '剧集' : '电影'} #${escapeHtml(String(candidate.id || ''))}</span>
                    </div>
                    <button type="button" class="scraper-compact-btn scraper-primary-soft" data-batch-bind="${escapeHtml(String(index))}" data-batch-bind-candidate="${escapeHtml(String(candidateIndex))}">绑定</button>
                </div>
            `).join('')
            : '<div class="scraper-empty-small">输入名称后点击搜索。</div>');
    return `
        <div class="scraper-batch-search">
            ${pathHtml}
            <div class="scraper-batch-search-row">
                <input class="scraper-input" data-batch-query="${escapeHtml(String(index))}" placeholder="影视名称" value="${escapeHtml(query)}">
                <select class="scraper-select" data-batch-query-type="${escapeHtml(String(index))}" aria-label="TMDB 类型">
                    <option value="movie" ${mediaType === 'movie' ? 'selected' : ''}>电影</option>
                    <option value="tv" ${mediaType === 'tv' ? 'selected' : ''}>电视剧</option>
                </select>
                <button type="button" class="scraper-compact-btn scraper-primary-soft" data-batch-search-run="${escapeHtml(String(index))}" ${busy ? 'disabled' : ''}>搜索</button>
            </div>
            ${resultHtml}
        </div>
    `;
}

function renderBatchPathSelection(index) {
    const searchState = state.batchSearchState[String(index)] || {};
    const selection = searchState.selection;
    if (!selection) return '';
    const source = String(selection.source || '').trim();
    const tokens = Array.isArray(selection.tokens) ? selection.tokens : [];
    if (!source || !tokens.length) return '';
    const selectedIndexes = Array.isArray(selection.selectedIndexes) ? selection.selectedIndexes : [];
    const selected = new Set(selectedIndexes.map(Number));
    const query = window.ScraperPathSelection?.composeQuery(selection) || '';
    if (selection.expanded === false) {
        return `
            <div class="scraper-batch-path is-collapsed">
                <div class="scraper-path-collapsed">
                    <div class="scraper-path-result">
                        <span>已填入搜索框</span>
                        <strong>${escapeHtml(query || '尚未选择标题')}</strong>
                    </div>
                    <button type="button" class="scraper-compact-btn" data-batch-path-reopen="${escapeHtml(String(index))}">重新选词</button>
                </div>
            </div>
        `;
    }
    return `
        <div class="scraper-batch-path">
            <div class="scraper-path-heading">
                <span>完整路径选词</span>
                <span>${selected.size ? `已选择 ${selected.size} 个词块` : '请选择影视标题'}</span>
            </div>
            <div class="scraper-path-source" title="${escapeHtml(source)}">${escapeHtml(source)}</div>
            <div class="scraper-path-tokens" role="listbox" aria-label="完整路径标题选词">
                ${tokens.map((token, tokenIndex) => `
                    <button
                        type="button"
                        class="scraper-path-token ${selected.has(tokenIndex) ? 'is-selected' : ''}"
                        data-batch-path-token="${escapeHtml(String(index))}"
                        data-batch-path-token-index="${escapeHtml(String(tokenIndex))}"
                        role="option"
                        aria-selected="${selected.has(tokenIndex) ? 'true' : 'false'}"
                    >${escapeHtml(token.text || '')}</button>
                `).join('')}
            </div>
            <div class="scraper-path-actions">
                <button type="button" class="scraper-compact-btn" data-batch-path-clear="${escapeHtml(String(index))}" ${selected.size ? '' : 'disabled'}>清空</button>
                <button type="button" class="scraper-compact-btn scraper-primary-soft" data-batch-path-complete="${escapeHtml(String(index))}" ${selected.size ? '' : 'disabled'}>完成选词</button>
            </div>
        </div>
    `;
}

function renderBatchItem(item) {
    const index = Number(item.item_index || 0);
    const identify = getBatchIdentify(index);
    const binding = getBatchBinding(index);
    const included = state.batchIncluded.has(index);
    const typeLabel = identify?.media_type === 'tv' ? '剧集' : (identify?.media_type === 'movie' ? '电影' : '未知');
    const fileCount = Array.isArray(item.files) ? item.files.length : 0;
    const dirBadge = item.is_dir ? '文件夹' : '文件';
    let matchHtml = '';
    let actionsHtml = '';
    if (binding) {
        const status = identify?.status || 'manual';
        const badgeClass = 'is-auto';
        const badgeText = status === 'auto' ? '自动匹配' : '已绑定';
        matchHtml = `
            <div class="scraper-batch-match-info">
                <div class="scraper-batch-match">
                    <span class="scraper-batch-badge ${badgeClass}">${badgeText}</span>
                    <span class="scraper-batch-type">${typeLabel}</span>
                </div>
                <strong class="scraper-batch-title" title="${escapeHtml(getBatchCandidateTitle(binding))}">${escapeHtml(getBatchCandidateTitle(binding))}</strong>
            </div>
        `;
        actionsHtml = `<button type="button" class="scraper-compact-btn" data-batch-search="${escapeHtml(String(index))}">改绑</button>`;
    } else if (identify?.status === 'suggest' && Array.isArray(identify.candidates) && identify.candidates.length) {
        const candidate = identify.candidates[0];
        matchHtml = `
            <div class="scraper-batch-match">
                <span class="scraper-batch-badge is-suggest">建议</span>
                <strong title="${escapeHtml(getBatchCandidateTitle(candidate))}">${escapeHtml(getBatchCandidateTitle(candidate))}</strong>
                <span class="scraper-batch-type">${typeLabel}</span>
                <button type="button" class="scraper-compact-btn scraper-primary-soft" data-batch-accept="${escapeHtml(String(index))}">接受</button>
            </div>
        `;
        actionsHtml = `<button type="button" class="scraper-compact-btn" data-batch-search="${escapeHtml(String(index))}">搜索绑定</button>`;
    } else if (item.no_media) {
        matchHtml = `
            <div class="scraper-batch-match">
                <span class="scraper-batch-badge is-manual">无媒体</span>
                <span class="scraper-batch-status-text">文件夹内没有可整理的媒体文件</span>
            </div>
        `;
    } else {
        const queryText = identify?.query || item.name || '';
        matchHtml = `
            <div class="scraper-batch-match">
                <span class="scraper-batch-badge is-manual">未匹配</span>
                <span class="scraper-batch-status-text">${identify ? `未找到可信条目（关键词：${escapeHtml(queryText)}）` : '等待识别'}</span>
            </div>
        `;
        actionsHtml = `<button type="button" class="scraper-compact-btn" data-batch-search="${escapeHtml(String(index))}">搜索绑定</button>`;
    }
    const searchHtml = renderBatchItemSearch(index);
    const posterUrl = binding ? (binding.tmdb_poster_url || binding.poster_url || '') : '';
    const posterHtml = posterUrl
        ? `
            <div class="scraper-batch-poster-col">
                <img class="scraper-batch-poster" src="${escapeHtml(posterUrl)}" alt="" loading="lazy">
            </div>
        `
        : '';
    return `
        <div class="scraper-batch-row ${included ? 'is-included' : ''}">
            <label class="scraper-batch-check">
                <input type="checkbox" class="ui-checkbox ui-checkbox-sm" data-batch-toggle="${escapeHtml(String(index))}" ${included ? 'checked' : ''}>
            </label>
            <div class="scraper-batch-main">
                <div class="scraper-batch-head">
                    <span class="scraper-plan-badge">${dirBadge}</span>
                    <strong title="${escapeHtml(item.name || '')}">${escapeHtml(item.name || '--')}</strong>
                    <span class="scraper-batch-count">${fileCount} 个媒体文件</span>
                </div>
                ${matchHtml}
                <div class="scraper-batch-actions">${actionsHtml}</div>
                ${searchHtml}
            </div>
            ${posterHtml}
        </div>
    `;
}

function renderBatch() {
    const summary = $('scraper-batch-summary');
    const list = $('scraper-batch-list');
    const buildBtn = $('scraper-batch-build-plan-btn');
    if (!summary || !list) return;
    const items = Array.isArray(state.batchScan?.items) ? state.batchScan.items : [];
    const issues = Array.isArray(state.batchScan?.issues) ? state.batchScan.issues : [];
    if (!items.length) {
        if (state.batchBusy) {
            summary.innerHTML = '<span class="scraper-busy-spinner inline" aria-hidden="true"></span>正在扫描并匹配 TMDB 条目，请稍候...';
            list.innerHTML = '<div class="scraper-empty-row">正在识别中，请不要关闭页面</div>';
        } else if (state.batchError) {
            summary.textContent = `扫描失败：${state.batchError}`;
            list.innerHTML = '';
        } else {
            summary.textContent = '勾选的条目中没有可整理的影视条目（文件夹或媒体文件）。';
            list.innerHTML = '';
        }
        if (buildBtn) {
            buildBtn.disabled = true;
            buildBtn.classList.add('btn-disabled');
        }
        return;
    }
    const results = Array.isArray(state.batchIdentify) ? state.batchIdentify : [];
    const autoCount = results.filter(item => item?.ok && item.status === 'auto').length;
    const suggestCount = results.filter(item => item?.ok && item.status === 'suggest').length;
    const manualCount = results.filter(item => item?.ok && item.status === 'manual').length;
    const boundCount = Object.keys(state.batchBindings).length;
    const includedCount = state.batchIncluded.size;
    const hasPlanItems = items.some(item => {
        const index = Number(item.item_index || 0);
        return state.batchIncluded.has(index) && !!getBatchBinding(index);
    });
    if (state.batchBusy) {
        summary.innerHTML = '<span class="scraper-busy-spinner inline" aria-hidden="true"></span>正在扫描并匹配 TMDB 条目，请稍候...';
    } else {
        summary.innerHTML = `
            <span class="scraper-ok-text">${escapeHtml(String(items.length))} 个条目</span>
            <span> / 自动匹配 ${escapeHtml(String(autoCount))}，建议 ${escapeHtml(String(suggestCount))}，待确认 ${escapeHtml(String(manualCount))}</span>
            <span> / 已勾选 ${escapeHtml(String(includedCount))}（已绑定 ${escapeHtml(String(boundCount))}）</span>
            ${issues.length ? `<em class="scraper-plan-warning">${escapeHtml(String(issues.length))} 个扫描提醒</em>` : ''}
        `;
    }
    list.innerHTML = items.map(item => renderBatchItem(item)).join('');
    if (buildBtn) {
        const disabled = state.batchBusy || !hasPlanItems;
        buildBtn.disabled = disabled;
        buildBtn.classList.toggle('btn-disabled', disabled);
    }
    syncBatchOptionControls();
    syncFileNamingModeControls();
    renderBatchSplitMode();
}

function toggleBatchInclude(itemIndex, checked) {
    const index = Number(itemIndex || 0);
    if (checked) {
        state.batchIncluded.add(index);
    } else {
        state.batchIncluded.delete(index);
    }
    renderBatch();
}

function acceptBatchSuggestion(itemIndex) {
    const index = Number(itemIndex || 0);
    const identify = getBatchIdentify(index);
    const candidates = Array.isArray(identify?.candidates) ? identify.candidates : [];
    if (!candidates.length) return;
    setBatchBinding(index, candidates[0]);
    renderBatch();
}

function toggleBatchItemSearch(itemIndex) {
    const index = Number(itemIndex || 0);
    const item = getBatchItem(index);
    const identify = getBatchIdentify(index);
    const current = state.batchSearchState[String(index)] || {};
    const wasOpen = !!current.open;
    state.batchSearchState[String(index)] = {
        open: !wasOpen,
        query: wasOpen ? current.query : (identify?.query || item?.name || ''),
        mediaType: current.mediaType || (identify?.media_type === 'tv' ? 'tv' : 'movie'),
        results: [],
        busy: false,
        selection: current.selection || createBatchPathSelection(item),
    };
    renderBatch();
}

function createBatchPathSelection(item) {
    if (!item?.entry) return null;
    const pathSelection = window.ScraperPathSelection;
    if (!pathSelection) return null;
    try {
        const selection = pathSelection.createSelection([item.entry], currentParentPath());
        selection.expanded = true;
        return selection;
    } catch (error) {
        return null;
    }
}

function beginBatchPathSelection(event, index, tokenIndex) {
    const current = state.batchSearchState[String(index)] || {};
    const selection = current.selection;
    if (!selection || !Number.isInteger(tokenIndex) || tokenIndex < 0) return;
    event.preventDefault();
    const selectedIndexes = Array.isArray(selection.selectedIndexes) ? selection.selectedIndexes : [];
    state.batchPathGesture = {
        pointerId: event.pointerId,
        itemIndex: Number(index || 0),
        startIndex: tokenIndex,
        lastIndex: tokenIndex,
        baseSelection: selectedIndexes.slice(),
        shouldSelect: !selectedIndexes.includes(tokenIndex),
    };
    selection.selectedIndexes = window.MediaHubTextSelection.applySelectionRange(
        state.batchPathGesture.baseSelection,
        tokenIndex,
        tokenIndex,
        state.batchPathGesture.shouldSelect,
    );
    state.batchSearchState[String(index)] = { ...current, selection: { ...selection } };
    syncBatchPathTokenDom(index);
}

function continueBatchPathSelection(event, index, tokenIndex) {
    const gesture = state.batchPathGesture;
    const current = state.batchSearchState[String(index)] || {};
    const selection = current.selection;
    if (
        !gesture
        || gesture.pointerId !== event.pointerId
        || gesture.itemIndex !== Number(index || 0)
        || !selection
        || !Number.isInteger(tokenIndex)
        || tokenIndex < 0
        || gesture.lastIndex === tokenIndex
    ) return;
    gesture.lastIndex = tokenIndex;
    selection.selectedIndexes = window.MediaHubTextSelection.applySelectionRange(
        gesture.baseSelection,
        gesture.startIndex,
        tokenIndex,
        gesture.shouldSelect,
    );
    state.batchSearchState[String(index)] = { ...current, selection: { ...selection } };
    syncBatchPathTokenDom(index);
}

function syncBatchPathTokenDom(index) {
    const selection = state.batchSearchState[String(index)]?.selection;
    if (!selection) return;
    const selected = new Set((Array.isArray(selection.selectedIndexes) ? selection.selectedIndexes : []).map(Number));
    document.querySelectorAll(`[data-batch-path-token="${String(index)}"]`).forEach((button) => {
        const tokenIndex = Number(button.dataset.batchPathTokenIndex || 0);
        button.classList.toggle('is-selected', selected.has(tokenIndex));
        button.setAttribute('aria-selected', selected.has(tokenIndex) ? 'true' : 'false');
    });
}

function clearBatchPathSelection(index) {
    const current = state.batchSearchState[String(index)] || {};
    const selection = current.selection;
    if (!selection) return;
    selection.selectedIndexes = [];
    state.batchSearchState[String(index)] = { ...current, query: '', selection: { ...selection } };
    renderBatch();
}

function completeBatchPathSelection(index) {
    const current = state.batchSearchState[String(index)] || {};
    const selection = current.selection;
    if (!selection) return;
    const query = window.ScraperPathSelection?.composeQuery(selection) || '';
    if (!query) {
        showToast('请先选择影视标题文字', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    selection.expanded = false;
    state.batchSearchState[String(index)] = { ...current, query, selection: { ...selection } };
    renderBatch();
}

function reopenBatchPathSelection(index) {
    const current = state.batchSearchState[String(index)] || {};
    const selection = current.selection;
    if (!selection) return;
    selection.expanded = true;
    state.batchSearchState[String(index)] = { ...current, selection: { ...selection } };
    renderBatch();
}

async function fetchTmdbSearch(query, mediaType) {
    const params = new URLSearchParams({
        q: String(query || '').trim(),
        media_type: String(mediaType || 'movie').trim(),
    });
    const data = await window.MediaHubApi.getJson(`/tmdb/search?${params.toString()}`);
    return Array.isArray(data.items) ? data.items : [];
}

async function batchSearchTmdb(itemIndex) {
    const index = Number(itemIndex || 0);
    const searchState = state.batchSearchState[String(index)] || {};
    const queryInput = document.querySelector(`[data-batch-query="${String(index)}"]`);
    const typeSelect = document.querySelector(`[data-batch-query-type="${String(index)}"]`);
    const query = String(queryInput?.value ?? searchState.query ?? '').trim();
    const mediaType = String(typeSelect?.value || searchState.mediaType || 'movie').trim();
    if (!query) {
        showToast('请输入影视名称', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    state.batchSearchState[String(index)] = { ...searchState, query, mediaType, busy: true, results: [] };
    renderBatch();
    try {
        const items = await fetchTmdbSearch(query, mediaType);
        const next = state.batchSearchState[String(index)] || {};
        state.batchSearchState[String(index)] = { ...next, busy: false, results: items };
    } catch (error) {
        const next = state.batchSearchState[String(index)] || {};
        state.batchSearchState[String(index)] = { ...next, busy: false, results: [] };
        showToast(`TMDB 搜索失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
    }
    renderBatch();
}

function batchBindItem(itemIndex, candidateIndex) {
    const index = Number(itemIndex || 0);
    const searchState = state.batchSearchState[String(index)] || {};
    const results = Array.isArray(searchState.results) ? searchState.results : [];
    const candidate = results[Number(candidateIndex || 0)];
    if (!candidate) return;
    setBatchBinding(index, candidate);
    state.batchSearchState[String(index)] = { ...searchState, open: false, results: [] };
    renderBatch();
}

async function buildBatchPlan() {
    if (state.batchBusy) return;
    const items = Array.isArray(state.batchScan?.items) ? state.batchScan.items : [];
    const selected = items.filter(item => {
        const index = Number(item.item_index || 0);
        return state.batchIncluded.has(index) && !!getBatchBinding(index);
    });
    if (!selected.length) {
        showToast('请先勾选并绑定要整理的条目', { tone: 'warn', duration: 2400, placement: 'top-center' });
        return;
    }
    state.batchBusy = true;
    const buildBtn = $('scraper-batch-build-plan-btn');
    if (buildBtn) {
        buildBtn.disabled = true;
        buildBtn.textContent = '生成中...';
    }
    renderBatch();
    const requestPayload = {
        provider: state.provider,
        base_cid: state.cid,
        base_path: currentParentPath(),
        options: collectBatchOptions(),
        items: selected.map(item => ({
            item_index: Number(item.item_index || 0),
            name: item.name,
            entry: item.entry,
            entries: Array.isArray(item.entries) && item.entries.length ? item.entries : undefined,
            tmdb: getBatchBinding(Number(item.item_index || 0)),
        })),
    };
    state.batchPlanContext = requestPayload;
    state.planOptionsSnapshot = JSON.stringify(requestPayload.options || {});
    try {
        const data = await window.MediaHubApi.postJson('/scraper/batch/plan', requestPayload);
        applyPlanResponse(data);
        closeBatchPanel();
        renderPlan();
        renderEntries();
        showPlanReadyToast(data);
    } catch (error) {
        showToast(`生成批量预览失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
    } finally {
        state.batchBusy = false;
        if (buildBtn) {
            buildBtn.disabled = false;
            buildBtn.textContent = '生成预览';
        }
        renderBatch();
    }
}

function buildPlanRequestPayload() {
    const entries = getEffectiveSelectedEntries();
    if (!entries.length) throw new Error('请先选择要刮削的文件或文件夹');
    if (hasUnknownSearchResultEntries(entries)) {
        throw new Error('搜索结果来自网盘其他位置，真实路径未知，请先进入该文件夹后再批量整理');
    }
    if (!state.tmdb || Number(state.tmdb.tmdb_id || state.tmdb.id || 0) <= 0) {
        throw new Error('请先绑定 TMDB 条目');
    }
    const options = collectOptions();
    const tmdb = { ...state.tmdb };
    if (options.episode_mode && options.episode_mode !== 'auto') {
        tmdb.tmdb_episode_mode = options.episode_mode;
    }
    const payload = {
        provider: state.provider,
        base_cid: state.cid,
        base_path: currentParentPath(),
        entries,
        tmdb,
        options,
    };
    const episodeOverrides = getPlanEpisodeOverrides();
    if (Object.keys(episodeOverrides).length) payload.episode_overrides = episodeOverrides;
    return payload;
}

function applyPlanResponse(data) {
    state.plan = data;
    const actions = Array.isArray(data.actions) ? data.actions : [];
    state.planSelections = new Set(
        actions
            .filter(action => action.ready)
            .map(action => Number(action.action_index || 0) || 0)
            .filter(Boolean),
    );
    state.planEpisodeOverrides = Object.fromEntries(
        actions
            .map(action => [String(action.entry_id || '').trim(), parseManualEpisode(action.manual_episode)])
            .filter(([entryId, episode]) => entryId && episode > 0),
    );
}

async function requestPlan(payload, { resetPlan = false } = {}) {
    state.planRequestSeq += 1;
    const requestSeq = state.planRequestSeq;
    state.planBusy = true;
    if (resetPlan) {
        state.plan = null;
        state.planSelections.clear();
    }
    renderPlan();
    renderEntries();
    try {
        const data = await window.MediaHubApi.postJson('/scraper/rename-plan', payload);
        if (state.planRequestSeq !== requestSeq) return null;
        applyPlanResponse(data);
        return data;
    } finally {
        if (state.planRequestSeq === requestSeq) {
            state.planBusy = false;
            renderPlan();
            renderEntries();
        }
    }
}

function showPlanReadyToast(data) {
    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const warningCount = warnings.length;
    const readyCount = Number(data.ready_count || 0);
    const totalCount = Number(data.total_count || 0);
    const unchangedCount = Number(data.unchanged_count || 0);
    const unchangedNote = unchangedCount > 0 ? `，已跳过 ${unchangedCount} 项无变化` : '';
    const warningText = warnings
        .map(text => String(text || '').trim())
        .filter(Boolean)
        .slice(0, 2)
        .map(text => (text.length > 60 ? `${text.slice(0, 60)}…` : text))
        .join('；');
    const warningNote = warningText ? `：${warningText}${warningCount > 2 ? ' 等' : ''}` : '';
    const issues = Array.isArray(data.issues) ? data.issues : [];
    const issueText = issues
        .map(text => String(text || '').trim())
        .filter(Boolean)
        .slice(0, 2)
        .map(text => (text.length > 60 ? `${text.slice(0, 60)}…` : text))
        .join('；');
    const noChangeOnly = readyCount <= 0 && totalCount === 0 && unchangedCount > 0;
    showToast(
        readyCount > 0
            ? (warningCount > 0 ? `预览已生成，含 ${warningCount} 个提醒${warningNote}${unchangedNote}` : `预览已生成，请勾选确认后执行${unchangedNote}`)
            : (noChangeOnly
                ? '识别完成，没有需要改名的文件'
                : `预览没有可执行项：${issueText || '请处理冲突后再试'}${unchangedNote}`),
        {
            tone: readyCount > 0 ? (warningCount > 0 ? 'warn' : 'success') : (noChangeOnly ? 'info' : 'warn'),
            duration: 2800,
            placement: 'top-center',
        },
    );
}

async function buildPlan() {
    if (state.planBusy) return;
    let payload;
    try {
        payload = buildPlanRequestPayload();
    } catch (error) {
        showToast(error.message || '无法生成预览', { tone: 'warn', duration: 2400, placement: 'top-center' });
        return;
    }
    state.planOptionsSnapshot = JSON.stringify(payload.options || {});
    showToast('正在识别文件并生成预览...', { tone: 'info', duration: 1800, placement: 'top-center' });
    try {
        const data = await requestPlan(payload, { resetPlan: true });
        if (!data) return;
        showPlanReadyToast(data);
        closeIdentifyPanel();
    } catch (error) {
        showToast(`生成预览失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
    }
}

async function updateManualEpisode(actionIndex, { clear = false } = {}) {
    if (state.planBusy) return;
    const action = getPlanAction(actionIndex);
    const entryId = String(action?.entry_id || '').trim();
    if (!action || !entryId) return;
    const previousOverrides = { ...state.planEpisodeOverrides };
    const previousContext = state.batchPlanContext;
    if (clear) {
        delete state.planEpisodeOverrides[entryId];
    } else {
        const input = document.querySelector(`[data-scraper-manual-episode-input="${Number(actionIndex || 0)}"]`);
        const episode = parseManualEpisode(input?.value);
        if (episode <= 0) {
            showToast('请输入大于 0 的集数', { tone: 'warn', duration: 2400, placement: 'top-center' });
            input?.focus();
            return;
        }
        state.planEpisodeOverrides[entryId] = episode;
    }
    if (state.plan?.tmdb?.batch && state.batchPlanContext) {
        const itemIndex = Number(action.item_index || 0);
        const items = (Array.isArray(state.batchPlanContext.items) ? state.batchPlanContext.items : [])
            .map(item => ({ ...item }));
        const target = items.find(item => Number(item.item_index || 0) === itemIndex);
        if (!target) {
            state.planEpisodeOverrides = previousOverrides;
            showToast('批量预览上下文已失效，请重新生成预览', { tone: 'warn', duration: 2600, placement: 'top-center' });
            return;
        }
        const overrides = { ...(target.episode_overrides || {}) };
        if (clear) {
            delete overrides[entryId];
        } else {
            overrides[entryId] = state.planEpisodeOverrides[entryId];
        }
        target.episode_overrides = overrides;
        state.batchPlanContext = { ...state.batchPlanContext, items };
        showToast(clear ? '正在恢复自动识别...' : '正在按手动集数更新预览...', { tone: 'info', duration: 1800, placement: 'top-center' });
        try {
            const data = await window.MediaHubApi.postJson('/scraper/batch/plan', state.batchPlanContext);
            applyPlanResponse(data);
            renderPlan();
            renderEntries();
            showToast(clear ? '已恢复自动识别' : '已应用手动集数', { tone: 'success', duration: 2200, placement: 'top-center' });
        } catch (error) {
            state.planEpisodeOverrides = previousOverrides;
            state.batchPlanContext = previousContext;
            showToast(`更新预览失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
        }
        return;
    }
    let payload;
    try {
        payload = buildPlanRequestPayload();
    } catch (error) {
        state.planEpisodeOverrides = previousOverrides;
        showToast(error.message || '无法更新预览', { tone: 'warn', duration: 2400, placement: 'top-center' });
        return;
    }
    showToast(clear ? '正在恢复自动识别...' : '正在按手动集数更新预览...', { tone: 'info', duration: 1800, placement: 'top-center' });
    try {
        const data = await requestPlan(payload);
        if (!data) return;
        showToast(clear ? '已恢复自动识别' : '已应用手动集数', { tone: 'success', duration: 2200, placement: 'top-center' });
    } catch (error) {
        state.planEpisodeOverrides = previousOverrides;
        showToast(`更新预览失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
    }
}

async function executePlan() {
    if (!state.plan) return;
    const currentOptions = JSON.stringify(state.plan?.tmdb?.batch ? collectBatchOptions() : collectOptions());
    if (state.planOptionsSnapshot && currentOptions !== state.planOptionsSnapshot) {
        showToast('批量整理选项已变更，已按新选项重新生成预览，请确认后再次执行', { tone: 'warn', duration: 3200, placement: 'top-center' });
        void buildPlan();
        return;
    }
    const selectedActions = (Array.isArray(state.plan.actions) ? state.plan.actions : [])
        .filter(action => action.ready && state.planSelections.has(Number(action.action_index || 0)));
    if (!selectedActions.length) {
        showToast('请先勾选要执行的预览项', { tone: 'warn', duration: 2400, placement: 'top-center' });
        return;
    }
    const warningLines = Array.from(new Set(selectedActions
        .map(action => String(action.warning || '').trim())
        .filter(Boolean)));
    const deleteCount = selectedActions.filter(action => !!action.delete).length;
    let message = deleteCount > 0
        ? `确认执行已勾选的 ${selectedActions.length} 项操作吗？其中 ${deleteCount} 项为删除广告文件（进入网盘回收站，整理任务不支持回退删除）`
        : `确认执行已勾选的 ${selectedActions.length} 项重命名和移动吗？`;
    let title = '确认执行';
    let confirmText = '执行';
    if (warningLines.length > 0) {
        message = warningLines.join('\n');
        title = '路径提醒';
        confirmText = '继续执行';
    }
    const ok = await showConfirm(message, {
        title,
        confirmText,
    });
    if (!ok) return;
    state.executeBusy = true;
    renderPlan();
    try {
        const data = await window.MediaHubApi.postJson('/scraper/jobs/create', {
            plan: {
                ...state.plan,
                actions: selectedActions,
                ready: true,
                ready_count: selectedActions.length,
                total_count: selectedActions.length,
                issues: [],
            },
        });
        showToast(`刮削任务已提交 #${data.job_id}`, { tone: 'success', duration: 2600, placement: 'top-center' });
        if (typeof window.refreshTaskCenterJobsOnly === 'function') {
            await window.refreshTaskCenterJobsOnly({ preferTab: 'scraper' });
        } else if (typeof window.fetchScraperJobsState === 'function') {
            await window.fetchScraperJobsState({ silent: true });
        }
        if (typeof window.scheduleResourcePolling === 'function') {
            window.scheduleResourcePolling(1000);
        }
        state.plan = null;
        state.planSelections.clear();
        state.planEpisodeOverrides = {};
        state.batchPlanContext = null;
        await refreshJobs();
        scheduleJobsPoll();
        await loadEntries({ force: true });
    } catch (error) {
        showToast(`提交失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
    } finally {
        state.executeBusy = false;
        renderPlan();
    }
}

async function refreshJobs({ page = state.jobsPage || 1 } = {}) {
    state.jobsBusy = true;
    renderJobs();
    try {
        const normalizedPage = Math.max(1, Number(page || 1) || 1);
        const data = await window.MediaHubApi.getJson(`/scraper/jobs/state?page=${normalizedPage}&page_size=10&status=all`);
        state.jobs = Array.isArray(data.jobs) ? data.jobs : [];
        state.jobsPage = normalizedPage;
        state.jobsPagination = data.pagination && typeof data.pagination === 'object' ? data.pagination : {};
    } catch (error) {
        showToast(`读取任务记录失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
    } finally {
        state.jobsBusy = false;
        renderJobs();
    }
}

async function scanMonitorDir() {
    const selectedEntries = getSelectedEntries();
    if (!selectedEntries.length) {
        showToast('请先勾选要扫描的文件夹或文件', { tone: 'warn', duration: 2600, placement: 'top-center' });
        return;
    }
    const scopes = buildMonitorScanScopes(selectedEntries);
    if (!scopes.length) {
        showToast('未识别到可扫描的目录', { tone: 'error', duration: 3200, placement: 'top-center' });
        return;
    }
    if (scopes.length > 50) {
        showToast('勾选范围超过 50 个目录，请缩小选择范围', { tone: 'error', duration: 3400, placement: 'top-center' });
        return;
    }
    const preview = scopes.length <= 3
        ? scopes.join(' / ')
        : `${scopes.slice(0, 3).join(' / ')} 等 ${scopes.length} 个目录`;
    const confirmed = await showConfirm(
        `将对以下目录执行监控扫描并刷新 STRM：\n${preview}\n\n继续？`,
        { title: '扫描监控', confirmText: '开始扫描' },
    );
    if (!confirmed) return;
    try {
        const data = await window.MediaHubApi.postJson('/monitor/scan', {
            provider: state.provider,
            paths: scopes,
        });
        const tasks = Array.isArray(data.tasks) ? data.tasks : [];
        const unmatchedCount = Array.isArray(data.unmatched) ? data.unmatched.length : 0;
        if (tasks.length) {
            const taskLabels = tasks.map(item => `${item.task_name}（${item.status}）`).join('、');
            const unmatchedText = unmatchedCount > 0 ? `，${unmatchedCount} 个目录未匹配监控任务` : '';
            showToast(`已加入监控队列：${taskLabels}${unmatchedText}`, {
                tone: 'success',
                duration: 4200,
                placement: 'top-center',
            });
        } else {
            showToast(data.msg || '未匹配到监控任务', { tone: 'warn', duration: 3600, placement: 'top-center' });
        }
    } catch (error) {
        showToast(error.message || '扫描入队失败', { tone: 'error', duration: 3600, placement: 'top-center' });
    }
}

function hasActiveJobs() {
    return state.jobs.some(job => SCRAPER_JOB_ACTIVE_STATUSES.has(String(job.status || '').trim()));
}

function scheduleJobsPoll() {
    if (state.jobsPollTimer) return;
    state.jobsPollTimer = window.setInterval(async () => {
        await refreshJobs({ page: 1 });
        if (!hasActiveJobs()) {
            window.clearInterval(state.jobsPollTimer);
            state.jobsPollTimer = 0;
            await loadEntries({ force: true });
        }
    }, 3000);
}

async function rollbackJob(jobId) {
    const normalizedJobId = Number(jobId || 0) || 0;
    if (normalizedJobId <= 0) return;
    const ok = await showConfirm(`回退刮削任务 #${normalizedJobId} 的成功动作吗？`, {
        title: '确认回退',
        confirmText: '回退',
    });
    if (!ok) return;
    try {
        await window.MediaHubApi.postJson(`/scraper/jobs/${encodeURIComponent(String(normalizedJobId))}/rollback`, {});
        showToast('回退任务已提交', { tone: 'success', duration: 2400, placement: 'top-center' });
        await refreshJobs();
        scheduleJobsPoll();
    } catch (error) {
        showToast(`回退提交失败：${error.message || '未知错误'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
    }
}

function setSelected(entryId, checked) {
    const id = String(entryId || '').trim();
    if (!id) return;
    const entry = state.entries.find(item => item.id === id);
    if (!entry) return;
    if (checked) {
        state.selected.set(id, entry);
    } else {
        state.selected.delete(id);
    }
    invalidateSelectionContext();
    renderEntries();
}

function toggleAll(checked) {
    const visibleEntries = getDisplayEntries();
    if (checked) {
        visibleEntries.forEach(entry => state.selected.set(entry.id, entry));
    } else {
        visibleEntries.forEach(entry => state.selected.delete(entry.id));
    }
    invalidateSelectionContext();
    renderEntries();
}

function selectRangeBetweenChecked() {
    if (getPlanActions().length > 0) return;
    const entries = getDisplayEntries();
    const selectedIndexes = entries
        .map((entry, index) => state.selected.has(entry.id) ? index : -1)
        .filter(index => index >= 0);
    if (selectedIndexes.length < 2) {
        showToast('请先勾选区间的起点和终点', { tone: 'warn', duration: 2400, placement: 'top-center' });
        return;
    }
    const start = Math.min(...selectedIndexes);
    const end = Math.max(...selectedIndexes);
    entries.slice(start, end + 1).forEach(entry => {
        state.selected.set(entry.id, entry);
    });
    invalidateSelectionContext();
    renderEntries();
    showToast(`已补齐选择 ${end - start + 1} 项`, { tone: 'success', duration: 2200, placement: 'top-center' });
}

function handlePointerDown(event) {
    const token = event.target.closest('[data-scraper-path-token-index]');
    if (token) {
        beginIdentifyPathSelection(event, Number(token.dataset.scraperPathTokenIndex));
        return;
    }
    const batchToken = event.target.closest('[data-batch-path-token]');
    if (batchToken) {
        beginBatchPathSelection(
            event,
            Number(batchToken.dataset.batchPathToken || 0),
            Number(batchToken.dataset.batchPathTokenIndex || 0),
        );
    }
}

function handleGlobalPointerMove(event) {
    const gesture = state.identifyPathGesture;
    if (gesture && gesture.pointerId === event.pointerId) {
        const token = document.elementFromPoint(event.clientX, event.clientY)
            ?.closest?.('[data-scraper-path-token-index]');
        if (!token) return;
        continueIdentifyPathSelection(event, Number(token.dataset.scraperPathTokenIndex));
        return;
    }
    const batchGesture = state.batchPathGesture;
    if (batchGesture && batchGesture.pointerId === event.pointerId) {
        const token = document.elementFromPoint(event.clientX, event.clientY)
            ?.closest?.('[data-batch-path-token]');
        if (!token) return;
        continueBatchPathSelection(
            event,
            Number(batchGesture.itemIndex || 0),
            Number(token.dataset.batchPathTokenIndex || 0),
        );
    }
}

function endIdentifyPathGesture(event) {
    if (state.identifyPathGesture?.pointerId === event.pointerId) {
        state.identifyPathGesture = null;
    }
    if (state.batchPathGesture?.pointerId === event.pointerId) {
        const gesture = state.batchPathGesture;
        state.batchPathGesture = null;
        if (gesture.itemIndex) renderBatch();
    }
}

function handleClick(event) {
    if (event.target?.id === 'scraper-identify-panel') {
        closeIdentifyPanel();
        return;
    }
    const providerButton = event.target.closest('[data-scraper-provider]');
    if (providerButton) {
        void switchProvider(providerButton.dataset.scraperProvider);
        return;
    }
    const trailButton = event.target.closest('[data-scraper-trail-index]');
    if (trailButton) {
        void goTrail(trailButton.dataset.scraperTrailIndex);
        return;
    }
    const entryButton = event.target.closest('[data-scraper-entry-enter]');
    if (entryButton) {
        void enterFolder(entryButton.dataset.scraperEntryEnter);
        return;
    }
    const sortButton = event.target.closest('[data-scraper-sort]');
    if (sortButton) {
        setEntrySort(sortButton.dataset.scraperSort);
        return;
    }
    const manualButton = event.target.closest('[data-scraper-manual-index]');
    if (manualButton) {
        void bindTmdbCandidate(state.manualResults[Number(manualButton.dataset.scraperManualIndex || 0)]);
        return;
    }
    const rollbackButton = event.target.closest('[data-scraper-rollback-job]');
    if (rollbackButton) {
        void rollbackJob(rollbackButton.dataset.scraperRollbackJob);
        return;
    }
    const jobsPageButton = event.target.closest('[data-scraper-action="jobs-page-prev"], [data-scraper-action="jobs-page-next"], [data-scraper-action="jobs-page-number"]');
    if (jobsPageButton) {
        const currentPage = Number(state.jobsPagination?.page || state.jobsPage || 1) || 1;
        const action = jobsPageButton.dataset.scraperAction;
        const targetPage = action === 'jobs-page-number'
            ? Number(jobsPageButton.dataset.scraperJobPage || currentPage)
            : currentPage + (action === 'jobs-page-next' ? 1 : -1);
        void refreshJobs({ page: targetPage });
        return;
    }
    const batchAcceptBtn = event.target.closest('[data-batch-accept]');
    if (batchAcceptBtn) {
        acceptBatchSuggestion(batchAcceptBtn.dataset.batchAccept);
        return;
    }
    const batchSearchBtn = event.target.closest('[data-batch-search]');
    if (batchSearchBtn) {
        toggleBatchItemSearch(batchSearchBtn.dataset.batchSearch);
        return;
    }
    const batchSearchRunBtn = event.target.closest('[data-batch-search-run]');
    if (batchSearchRunBtn) {
        void batchSearchTmdb(batchSearchRunBtn.dataset.batchSearchRun);
        return;
    }
    const batchBindBtn = event.target.closest('[data-batch-bind]');
    if (batchBindBtn) {
        batchBindItem(batchBindBtn.dataset.batchBind, batchBindBtn.dataset.batchBindCandidate);
        return;
    }
    const batchPathClear = event.target.closest('[data-batch-path-clear]');
    if (batchPathClear) {
        clearBatchPathSelection(Number(batchPathClear.dataset.batchPathClear || 0));
        return;
    }
    const batchPathComplete = event.target.closest('[data-batch-path-complete]');
    if (batchPathComplete) {
        completeBatchPathSelection(Number(batchPathComplete.dataset.batchPathComplete || 0));
        return;
    }
    const batchPathReopen = event.target.closest('[data-batch-path-reopen]');
    if (batchPathReopen) {
        reopenBatchPathSelection(Number(batchPathReopen.dataset.batchPathReopen || 0));
        return;
    }
    const splitModeButton = event.target.closest('[data-split-mode]');
    if (splitModeButton) {
        setBatchSplitMode(splitModeButton.dataset.splitMode);
        return;
    }
    const actionButton = event.target.closest('[data-scraper-action]');
    if (!actionButton) return;
    const action = String(actionButton.dataset.scraperAction || '').trim();
    if (action === 'refresh') void loadEntries({ force: true });
    if (action === 'load-more-entries') void loadEntries({ more: true });
    if (action === 'back-top') scrollScraperToTop();
    if (action === 'toggle-search') toggleToolPopover('search');
    if (action === 'toggle-create-folder') toggleToolPopover('create');
    if (action === 'close-tools') closeToolPopovers();
    if (action === 'search') {
        state.search = String($('scraper-search-input')?.value || '').trim();
        openSearchPopover({ focus: true });
        void loadEntries();
    }
    if (action === 'clear-search') {
        state.search = '';
        const input = $('scraper-search-input');
        if (input) input.value = '';
        openSearchPopover({ focus: true });
        void loadEntries();
    }
    if (action === 'create-folder') void createFolder();
    if (action === 'select-range') selectRangeBetweenChecked();
    if (action === 'rename-selected') void renameSelected();
    if (action === 'prepare-copy') prepareCopy();
    if (action === 'prepare-move') prepareMove();
    if (action === 'delete-selected') void deleteSelected();
    if (action === 'identify' || action === 'open-batch') openBatchPanel();
    if (action === 'reopen-batch') reopenBatchPanel();
    if (action === 'close-batch') closeBatchPanel();
    if (action === 'rescan-batch') void scanBatch();
    if (action === 'build-batch-plan') void buildBatchPlan();
    if (action === 'reset-batch-preferences') void resetBatchPreferences();
    if (action === 'clear-identify') clearIdentifyMode();
    if (action === 'open-identify') {
        if (state.identifyResult || state.tmdb) {
            openIdentifyPanel();
            renderIdentify();
        } else {
            void identifySelected();
        }
    }
    if (action === 'close-identify') closeIdentifyPanel();
    if (action === 'clear-path-selection') clearIdentifyPathSelection();
    if (action === 'complete-path-selection') completeIdentifyPathSelection();
    if (action === 'reopen-path-selection') reopenIdentifyPathSelection();
    if (action === 'manual-search') void manualSearchTmdb();
    if (action === 'build-plan') void buildPlan();
    if (action === 'apply-manual-episode') void updateManualEpisode(actionButton.dataset.scraperActionIndex);
    if (action === 'clear-manual-episode') void updateManualEpisode(actionButton.dataset.scraperActionIndex, { clear: true });
    if (action === 'clear-plan') {
        clearPlan();
        renderSelection();
    }
    if (action === 'execute-plan') void executePlan();
    if (action === 'refresh-jobs') void refreshJobs();
    if (action === 'monitor-scan') void scanMonitorDir();
    if (action === 'copy-here') void copyHere();
    if (action === 'move-here') void moveHere();
    if (action === 'clear-copy') {
        state.copyBuffer = null;
        renderEntries();
    }
    if (action === 'clear-move') {
        state.moveBuffer = null;
        renderEntries();
    }
}

function handleChange(event) {
    const check = event.target.closest('[data-scraper-check]');
    if (check) {
        setSelected(check.dataset.scraperCheck, check.checked);
        return;
    }
    if (event.target?.id === 'scraper-check-all') {
        toggleAll(!!event.target.checked);
        return;
    }
    const batchCheck = event.target.closest('[data-batch-toggle]');
    if (batchCheck) {
        toggleBatchInclude(batchCheck.dataset.batchToggle, !!batchCheck.checked);
        return;
    }
    const planCheck = event.target.closest('[data-scraper-plan-check]');
    if (planCheck) {
        const index = Number(planCheck.dataset.scraperPlanCheck || 0) || 0;
        if (index > 0) {
            if (planCheck.checked) {
                state.planSelections.add(index);
            } else {
                state.planSelections.delete(index);
            }
            renderPlan();
            renderSelection();
        }
        return;
    }
    if (event.target?.id === 'scraper-manual-media-type') {
        state.manualMediaTypeTouched = true;
        state.manualResults = [];
        syncSeasonControl();
        syncEpisodeModeControl();
        renderIdentify();
        return;
    }
    if (event.target?.id === 'scraper-episode-mode') {
        clearPlan();
        scheduleBatchPreferenceSave();
        return;
    }
    if (event.target?.id === 'scraper-preserve-file-info') {
        syncFileInfoControls();
        clearPlan();
        scheduleBatchPreferenceSave();
        return;
    }
    if (event.target?.id === 'scraper-file-name-mode') {
        syncFileNamingModeControls();
        clearPlan();
        scheduleBatchPreferenceSave();
        return;
    }
    if (event.target?.matches('[data-scraper-tag], #scraper-title-language, #scraper-season, #scraper-include-tmdb-id, #scraper-use-season-subfolder, #scraper-rename-selected-folders, #scraper-delete-ad-files')) {
        clearPlan();
        scheduleBatchPreferenceSave();
    }
}

function handleGlobalKeydown(event) {
    if (event.key !== 'Escape') return;
    const batchPanel = $('scraper-batch-panel');
    if (batchPanel && !batchPanel.classList.contains('hidden')) {
        closeBatchPanel();
        return;
    }
    const panel = $('scraper-identify-panel');
    if (panel && !panel.classList.contains('hidden')) {
        closeIdentifyPanel();
        return;
    }
    closeToolPopovers();
}

function bindEvents() {
    const root = $('page-scraper');
    if (!root || root.dataset.scraperBound === '1') return;
    root.dataset.scraperBound = '1';
    root.addEventListener('click', handleClick);
    root.addEventListener('change', handleChange);
    root.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('scroll', syncScraperBackTopButton, { passive: true });
    window.addEventListener('resize', () => {
        syncScraperBackTopButton();
        syncScraperBrowserHeight();
    });
    document.addEventListener('keydown', handleGlobalKeydown);
    document.addEventListener('pointermove', handleGlobalPointerMove, { passive: true });
    document.addEventListener('pointerup', endIdentifyPathGesture, { passive: true });
    document.addEventListener('pointercancel', endIdentifyPathGesture, { passive: true });
    window.syncScraperBackTopButton = syncScraperBackTopButton;
    window.syncScraperBrowserHeight = syncScraperBrowserHeight;
    $('scraper-search-input')?.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' || event.isComposing) return;
        state.search = String(event.target.value || '').trim();
        openSearchPopover({ focus: false });
        void loadEntries();
    });
    $('scraper-new-folder-name')?.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' || event.isComposing) return;
        void createFolder();
    });
    $('scraper-manual-query')?.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' || event.isComposing) return;
        void manualSearchTmdb();
    });
}

async function refreshInitialData() {
    await loadProviders();
    renderProviderTabs();
    renderIdentify();
    renderPlan();
    await restoreScraperLocation();
    await loadBatchPreferences();
    await Promise.all([
        loadEntries(),
        refreshJobs(),
    ]);
    syncScraperLocationHash();
    if (hasActiveJobs()) scheduleJobsPoll();
}

export async function ensureScraperManager({ firstVisit = false } = {}) {
    bindEvents();
    requestAnimationFrame(syncScraperBrowserHeight);
    if (!state.initialized || firstVisit) {
        state.initialized = true;
        await refreshInitialData();
        syncScraperBackTopButton();
        syncScraperBrowserHeight();
        return;
    }
    renderProviderTabs();
    renderEntries();
    renderIdentify();
    renderPlan();
    renderJobs();
    syncScraperBackTopButton();
    syncScraperBrowserHeight();
    if (hasActiveJobs()) scheduleJobsPoll();
}
