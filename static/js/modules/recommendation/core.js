function escapeRecHtml(str) {
    const s = String(str == null ? '' : str);
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

let recommendationItems = [];
let recommendationWatchlist = [];
let recommendationActiveTab = 'trending-week';
let recommendationPreviousTab = 'trending-week';
let recommendationBusy = false;

let recommendationPagination = {
    currentPage: 1,
    totalPages: 1,
    currentContext: null,
};

let exploreGenres = { movie: [], tv: [] };
let exploreGenresLoaded = { movie: false, tv: false };
const EXPLORE_COMPACT_BREAKPOINT = 1180;
const EXPLORE_DEFAULT_FILTERS = Object.freeze({
    mediaType: 'movie',
    sortBy: 'popularity.desc',
    language: '',
    decade: '',
    rating: '',
    voteCount: '',
    runtimeGte: '',
    runtimeLte: '',
    genres: [],
});

let exploreFilterState = getDefaultExploreFilters();
let exploreDrawerOpen = false;

function getDefaultExploreFilters() {
    return {
        mediaType: EXPLORE_DEFAULT_FILTERS.mediaType,
        sortBy: EXPLORE_DEFAULT_FILTERS.sortBy,
        language: EXPLORE_DEFAULT_FILTERS.language,
        decade: EXPLORE_DEFAULT_FILTERS.decade,
        rating: EXPLORE_DEFAULT_FILTERS.rating,
        voteCount: EXPLORE_DEFAULT_FILTERS.voteCount,
        runtimeGte: EXPLORE_DEFAULT_FILTERS.runtimeGte,
        runtimeLte: EXPLORE_DEFAULT_FILTERS.runtimeLte,
        genres: [],
    };
}

function setRecommendationContentHeader(title, subtitle) {
    const titleEl = document.getElementById('recommendation-content-title');
    const subtitleEl = document.getElementById('recommendation-content-subtitle');
    if (titleEl) titleEl.innerText = title;
    if (subtitleEl) subtitleEl.innerText = subtitle || '';
}

function setRecommendationBusy(busy) {
    recommendationBusy = !!busy;
    const el = document.getElementById('recommendation-loading');
    if (el) el.classList.toggle('hidden', !recommendationBusy);
    document.querySelectorAll('.rec-tab-btn').forEach((btn) => {
        btn.disabled = recommendationBusy;
        btn.classList.toggle('opacity-50', recommendationBusy);
    });
}

function setActiveRecTab(tabKey) {
    if (tabKey !== 'search' && recommendationActiveTab !== 'search') {
        recommendationPreviousTab = tabKey;
    }
    recommendationActiveTab = tabKey;
    document.querySelectorAll('.rec-tab-btn').forEach((btn) => {
        btn.classList.toggle('is-active', btn.dataset.recTab === tabKey);
    });
    const pageEl = document.getElementById('page-recommendation');
    const workspaceEl = document.getElementById('recommendation-workspace');
    const searchToolbar = document.getElementById('recommendation-standard-toolbar');
    const quickbar = document.getElementById('rec-explore-mobile-quickbar');
    const exploreFilters = document.getElementById('rec-explore-filters');
    const isExplore = tabKey === 'explore';

    pageEl?.classList.toggle('is-explore', isExplore);
    workspaceEl?.classList.toggle('is-explore', isExplore);
    if (isExplore) {
        if (searchToolbar) searchToolbar.classList.add('hidden');
        if (quickbar) quickbar.classList.remove('hidden');
        if (exploreFilters) exploreFilters.classList.remove('hidden');
    } else {
        closeExploreFiltersDrawer();
        if (exploreFilters) exploreFilters.classList.add('hidden');
        if (quickbar) quickbar.classList.add('hidden');
        if (searchToolbar) searchToolbar.classList.remove('hidden');
    }
    syncExploreFilterUi();
}

function isCompactExploreFilters() {
    return window.matchMedia
        ? window.matchMedia('(max-width: ' + EXPLORE_COMPACT_BREAKPOINT + 'px)').matches
        : window.innerWidth <= EXPLORE_COMPACT_BREAKPOINT;
}

function getExploreSelectedCount() {
    let count = 0;
    if (exploreFilterState.mediaType === 'tv') count += 1;
    if (exploreFilterState.language) count += 1;
    if (exploreFilterState.decade) count += 1;
    if (exploreFilterState.rating) count += 1;
    if (exploreFilterState.voteCount) count += 1;
    if (exploreFilterState.runtimeGte) count += 1;
    if (exploreFilterState.runtimeLte) count += 1;
    count += exploreFilterState.genres.length;
    return count;
}

function getExploreSortOptions(mediaType) {
    const isTv = mediaType === 'tv';
    return [
        { value: 'popularity.desc', label: '最热门' },
        { value: 'vote_average.desc', label: '最高评分' },
        { value: isTv ? 'first_air_date.desc' : 'primary_release_date.desc', label: '最新上映' },
        { value: isTv ? 'first_air_date.asc' : 'primary_release_date.asc', label: '最早上映' },
        { value: 'popularity.asc', label: '最冷门' },
    ];
}

function getExploreSortLabel() {
    const option = getExploreSortOptions(exploreFilterState.mediaType).find((o) => o.value === exploreFilterState.sortBy);
    return option ? option.label : '最热门';
}

function getExploreLanguageLabel() {
    const labels = {
        zh: '中文',
        en: '英语',
        ja: '日语',
        ko: '韩语',
        th: '泰语',
        fr: '法语',
        de: '德语',
        es: '西班牙语',
    };
    return exploreFilterState.language ? (labels[exploreFilterState.language] || exploreFilterState.language) : '全部语言';
}

function getExploreSummaryText() {
    const parts = [
        exploreFilterState.mediaType === 'tv' ? '剧集' : '电影',
        getExploreSortLabel(),
        getExploreLanguageLabel(),
    ];
    if (exploreFilterState.decade) parts.push(exploreFilterState.decade + 's');
    if (exploreFilterState.rating) parts.push('评分≥' + exploreFilterState.rating);
    if (exploreFilterState.voteCount) parts.push('投票≥' + exploreFilterState.voteCount);
    if (exploreFilterState.runtimeGte || exploreFilterState.runtimeLte) {
        parts.push('片长 ' + (exploreFilterState.runtimeGte || '不限') + '-' + (exploreFilterState.runtimeLte || '不限'));
    }
    if (exploreFilterState.genres.length) parts.push(exploreFilterState.genres.length + ' 个分类');
    return parts.join(' · ');
}

function updateSortOptions(mediaType) {
    const options = getExploreSortOptions(mediaType || exploreFilterState.mediaType);
    if (exploreFilterState.sortBy === 'primary_release_date.desc' && (mediaType || exploreFilterState.mediaType) === 'tv') {
        exploreFilterState.sortBy = 'first_air_date.desc';
    } else if (exploreFilterState.sortBy === 'primary_release_date.asc' && (mediaType || exploreFilterState.mediaType) === 'tv') {
        exploreFilterState.sortBy = 'first_air_date.asc';
    } else if (exploreFilterState.sortBy === 'first_air_date.desc' && (mediaType || exploreFilterState.mediaType) === 'movie') {
        exploreFilterState.sortBy = 'primary_release_date.desc';
    } else if (exploreFilterState.sortBy === 'first_air_date.asc' && (mediaType || exploreFilterState.mediaType) === 'movie') {
        exploreFilterState.sortBy = 'primary_release_date.asc';
    }
    if (!options.some((o) => o.value === exploreFilterState.sortBy)) {
        exploreFilterState.sortBy = EXPLORE_DEFAULT_FILTERS.sortBy;
    }
    const html = options.map(function(o) {
        return '<option value="' + o.value + '">' + o.label + '</option>';
    }).join('');
    ['rec-explore-sort', 'rec-explore-sort-mobile'].forEach(function(id) {
        const select = document.getElementById(id);
        if (!select) return;
        select.innerHTML = html;
        select.value = exploreFilterState.sortBy;
    });
}

function syncExploreFilterUi() {
    const compact = isCompactExploreFilters();
    const drawerVisible = recommendationActiveTab === 'explore' && compact && exploreDrawerOpen;
    const filters = document.getElementById('rec-explore-filters');
    const backdrop = document.getElementById('rec-explore-backdrop');
    const count = getExploreSelectedCount();
    const mobileCount = document.getElementById('rec-explore-mobile-count');
    const drawerToggle = document.getElementById('rec-explore-drawer-toggle');
    const summaryText = document.getElementById('rec-explore-summary-text');

    updateSortOptions(exploreFilterState.mediaType);

    const valueMap = {
        'rec-explore-media-type': exploreFilterState.mediaType,
        'rec-explore-language': exploreFilterState.language,
        'rec-explore-rating': exploreFilterState.rating,
        'rec-explore-vote-count': exploreFilterState.voteCount,
        'rec-explore-runtime-gte': exploreFilterState.runtimeGte,
        'rec-explore-runtime-lte': exploreFilterState.runtimeLte,
    };
    Object.keys(valueMap).forEach(function(id) {
        const el = document.getElementById(id);
        if (el && el.value !== valueMap[id]) el.value = valueMap[id];
    });

    document.getElementById('rec-explore-media-movie')?.classList.toggle('is-active', exploreFilterState.mediaType === 'movie');
    document.getElementById('rec-explore-media-tv')?.classList.toggle('is-active', exploreFilterState.mediaType === 'tv');
    document.getElementById('rec-explore-media-movie')?.setAttribute('aria-pressed', exploreFilterState.mediaType === 'movie' ? 'true' : 'false');
    document.getElementById('rec-explore-media-tv')?.setAttribute('aria-pressed', exploreFilterState.mediaType === 'tv' ? 'true' : 'false');

    document.querySelectorAll('#rec-explore-decade-chips .rec-genre-chip').forEach(function(chip) {
        chip.classList.toggle('is-selected', chip.dataset.decade === exploreFilterState.decade);
    });
    document.querySelectorAll('#rec-explore-genres .rec-genre-chip').forEach(function(chip) {
        chip.classList.toggle('is-selected', exploreFilterState.genres.includes(String(chip.dataset.genreId)));
    });

    if (mobileCount) {
        mobileCount.textContent = ' · ' + count;
        mobileCount.classList.toggle('hidden', count <= 0);
    }
    if (summaryText) summaryText.textContent = getExploreSummaryText();
    if (recommendationActiveTab === 'explore') {
        const subtitle = '当前条件：' + getExploreSummaryText();
        const subtitleEl = document.getElementById('recommendation-content-subtitle');
        if (subtitleEl) subtitleEl.innerText = subtitle;
    }

    if (filters) filters.classList.toggle('is-mobile-open', drawerVisible);
    if (drawerToggle) drawerToggle.setAttribute('aria-expanded', drawerVisible ? 'true' : 'false');
    if (backdrop) {
        backdrop.classList.toggle('hidden', !drawerVisible);
    }
    document.body?.classList.toggle('rec-explore-drawer-open', drawerVisible);
}

function setExploreDrawerOpen(open) {
    exploreDrawerOpen = !!open && recommendationActiveTab === 'explore';
    syncExploreFilterUi();
}

function openExploreFiltersDrawer() {
    setExploreDrawerOpen(true);
}

function closeExploreFiltersDrawer() {
    setExploreDrawerOpen(false);
}

function toggleExploreMoreFilters(forceExpanded) {
    setExploreDrawerOpen(typeof forceExpanded === 'boolean' ? forceExpanded : !exploreDrawerOpen);
}

function bindExploreFilterInputs() {
    const bindings = [
        { id: 'rec-explore-language', key: 'language', event: 'change' },
        { id: 'rec-explore-rating', key: 'rating', event: 'input' },
        { id: 'rec-explore-vote-count', key: 'voteCount', event: 'input' },
        { id: 'rec-explore-runtime-gte', key: 'runtimeGte', event: 'input' },
        { id: 'rec-explore-runtime-lte', key: 'runtimeLte', event: 'input' },
    ];
    bindings.forEach(function(binding) {
        const el = document.getElementById(binding.id);
        if (!el || el.dataset.recExploreBound === '1') return;
        el.addEventListener(binding.event, function() {
            exploreFilterState[binding.key] = (el.value || '').trim();
            syncExploreFilterUi();
        });
        el.dataset.recExploreBound = '1';
    });
}

async function applyExploreFilters() {
    if (isCompactExploreFilters()) {
        closeExploreFiltersDrawer();
    }
    await searchRecommendationDiscover();
}

async function applyExploreMoreFilters() {
    await applyExploreFilters();
}

function syncExploreMoreToggle() {
    syncExploreFilterUi();
}

function buildPaginationHtml(page, totalPages) {
    if (totalPages <= 1) return '';
    var pages = [];
    var windowSize = 2;
    if (totalPages <= 7) {
        for (var i = 1; i <= totalPages; i++) pages.push(i);
    } else {
        pages.push(1);
        var start = Math.max(2, page - windowSize);
        var end = Math.min(totalPages - 1, page + windowSize);
        if (start > 2) pages.push('...');
        for (var j = start; j <= end; j++) pages.push(j);
        if (end < totalPages - 1) pages.push('...');
        pages.push(totalPages);
    }
    var html = '<button type="button" class="rec-page-btn" onclick="goToRecommendationPage(' + (page - 1) + ')"' + (page <= 1 ? ' disabled' : '') + '>&#8249;</button>';
    for (var k = 0; k < pages.length; k++) {
        var p = pages[k];
        if (p === '...') {
            html += '<span class="rec-page-ellipsis">···</span>';
        } else {
            var cls = p === page ? 'rec-page-btn rec-page-active' : 'rec-page-btn';
            html += '<button type="button" class="' + cls + '" onclick="goToRecommendationPage(' + p + ')">' + p + '</button>';
        }
    }
    html += '<button type="button" class="rec-page-btn" onclick="goToRecommendationPage(' + (page + 1) + ')"' + (page >= totalPages ? ' disabled' : '') + '>&#8250;</button>';
    html += '<span class="rec-page-jump"><span class="rec-page-jump-label">跳至</span><input type="number" class="rec-page-jump-input" min="1" max="' + totalPages + '" placeholder="" value="" onkeydown="if(event.key===\'Enter\')jumpToRecommendationPage(this)"><span class="rec-page-jump-label">/ ' + totalPages + ' 页</span><button type="button" class="rec-page-btn rec-page-jump-btn" onclick="jumpToRecommendationPage(this.previousElementSibling.previousElementSibling)">确定</button></span>';
    return html;
}

function jumpToRecommendationPage(inputEl) {
    if (!inputEl) return;
    var val = parseInt(inputEl.value, 10);
    if (isNaN(val) || val < 1 || val > recommendationPagination.totalPages) return;
    goToRecommendationPage(val);
    inputEl.value = '';
}

function updatePagination() {
    var el = document.getElementById('recommendation-pagination');
    if (!el) return;
    if (recommendationActiveTab === 'watchlist' || recommendationPagination.totalPages <= 1) {
        el.classList.add('hidden');
        el.innerHTML = '';
        return;
    }
    el.innerHTML = buildPaginationHtml(recommendationPagination.currentPage, recommendationPagination.totalPages);
    el.classList.remove('hidden');
}

function resetPagination() {
    recommendationPagination.currentPage = 1;
    recommendationPagination.totalPages = 1;
    recommendationPagination.currentContext = null;
    updatePagination();
}

function scrollRecommendationToTop() {
    if (typeof window === 'undefined' || typeof window.scrollTo !== 'function') return;
    try {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
        window.scrollTo(0, 0);
    }
}

async function goToRecommendationPage(page) {
    if (recommendationBusy) return;
    var p = Math.max(1, Math.min(page, recommendationPagination.totalPages));
    if (p === recommendationPagination.currentPage) return;
    scrollRecommendationToTop();
    var ctx = recommendationPagination.currentContext;
    if (!ctx) return;
    if (ctx.type === 'trending') {
        await loadRecommendationTrending(ctx.timeWindow, p);
    } else if (ctx.type === 'popular') {
        await loadRecommendationPopular(ctx.mediaType, p);
    } else if (ctx.type === 'search') {
        await searchRecommendationTmdb(ctx.query, ctx.mediaType, p);
    } else if (ctx.type === 'discover') {
        await searchRecommendationDiscover(p);
    }
}

function getWatchlistCount() {
    return Array.isArray(recommendationWatchlist) ? recommendationWatchlist.length : 0;
}

function isInWatchlist(tmdbId, mediaType) {
    return recommendationWatchlist.some((w) => w.tmdb_id === tmdbId && w.media_type === mediaType);
}

function updateWatchlistCount() {
    const el = document.getElementById('recommendation-watchlist-count');
    if (el) el.innerText = String(getWatchlistCount());
}

function syncSearchClearBtn() {
    const input = document.getElementById('recommendation-search-input');
    const btn = document.getElementById('recommendation-search-clear');
    if (!input || !btn) return;
    btn.classList.toggle('hidden', !input.value.trim());
}

function onRecommendationSearchInput() {
    syncSearchClearBtn();
}

function restorePreviousRecTab() {
    const tab = recommendationPreviousTab || 'trending-week';
    const prefix = tab.split('-')[0];
    if (prefix === 'trending') {
        loadRecommendationTrending(tab.split('-')[1]);
    } else if (prefix === 'popular') {
        loadRecommendationPopular(tab.split('-')[1]);
    } else if (tab === 'watchlist') {
        showRecommendationWatchlist();
    } else if (tab === 'explore') {
        showRecommendationExplore();
    } else {
        loadRecommendationTrending('week');
    }
}

function clearRecommendationSearch() {
    const input = document.getElementById('recommendation-search-input');
    if (input) {
        input.value = '';
        input.focus();
    }
    syncSearchClearBtn();
    restorePreviousRecTab();
}

function buildVoteBadgeHtml(voteAverage) {
    const val = Number(voteAverage || 0);
    if (val <= 0) return '';
    return '<div class="rec-card-vote">' +
        '<svg viewBox="0 0 20 20" fill="currentColor"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/></svg>' +
        '<span>' + val.toFixed(1) + '</span>' +
    '</div>';
}

function buildPosterHtml(posterUrl, title) {
    if (posterUrl) {
        return '<img src="' + escapeRecHtml(posterUrl) + '" alt="' + escapeRecHtml(title || '') + '" loading="lazy">';
    }
    return '<div class="rec-card-poster-placeholder">' +
        '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>' +
    '</div>';
}

function buildCardMetaHtml(item, options) {
    const opts = options || {};
    const parts = [];
    const mediaLabel = item.media_type === 'tv' ? '剧集' : '电影';
    parts.push('<span class="rec-card-meta-tag">' + escapeRecHtml(mediaLabel) + '</span>');
    if (item.year) {
        parts.push('<span class="rec-card-meta-text rec-card-meta-year">' + escapeRecHtml(String(item.year)) + '</span>');
    }
    if (opts.includeOriginalTitle && item.original_title && item.original_title !== item.title) {
        parts.push('<span class="rec-card-original-title">' + escapeRecHtml(item.original_title) + '</span>');
    }
    return '<div class="rec-card-meta">' + parts.join('') + '</div>';
}

function buildRecCardHtml(item, index) {
    const poster = buildPosterHtml(item.poster_url, item.title);
    const voteBadge = buildVoteBadgeHtml(item.vote_average);
    const meta = buildCardMetaHtml(item, { includeOriginalTitle: true });
    const inWatchlist = isInWatchlist(item.id, item.media_type);
    const watchlistBtnClass = inWatchlist ? 'rec-btn-watchlist-active' : 'rec-btn-watchlist';
    const watchlistLabel = inWatchlist ? '已想看' : '想看';

    return '<div class="rec-card">' +
        '<div class="rec-card-poster-wrap" onclick="openRecDetail(' + index + ')">' + poster + voteBadge + '</div>' +
        '<div class="rec-card-info">' +
            '<div class="rec-card-title" onclick="openRecDetail(' + index + ')">' + escapeRecHtml(item.title || '--') + '</div>' +
            meta +
        '</div>' +
        '<div class="rec-card-actions">' +
            '<button type="button" onclick="toggleRecommendationWatchlist(' + index + ')" class="rec-card-btn ' + watchlistBtnClass + '">' + watchlistLabel + '</button>' +
            '<button type="button" onclick="searchResourceForRecommendation(' + index + ')" class="rec-card-btn rec-btn-search-resource">搜索</button>' +
            '<button type="button" onclick="subscribeRecommendation(' + index + ')" class="rec-card-btn rec-btn-subscribe">订阅</button>' +
        '</div>' +
    '</div>';
}

function buildWatchlistCardHtml(item) {
    const poster = buildPosterHtml(item.poster_url, item.title);
    const voteBadge = buildVoteBadgeHtml(item.vote_average);
    const statusMap = { want: '想看', subscribed: '已订阅', done: '已完成' };
    const statusColorMap = { want: 'bg-amber-500/20 text-amber-300 border border-amber-500/30', subscribed: 'bg-sky-500/20 text-sky-300 border border-sky-500/30', done: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' };
    const status = item.status || 'want';
    const statusLabel = statusMap[status] || status;
    const statusColor = statusColorMap[status] || 'bg-slate-700 text-slate-300';
    const meta = buildCardMetaHtml(item);

    return '<div class="rec-card">' +
        '<div class="rec-card-poster-wrap" onclick="openWatchlistDetail(' + item.id + ')">' + poster + voteBadge +
            '<div class="rec-card-status-badge ' + statusColor + '">' + escapeRecHtml(statusLabel) + '</div>' +
        '</div>' +
        '<div class="rec-card-info">' +
            '<div class="rec-card-title" onclick="openWatchlistDetail(' + item.id + ')">' + escapeRecHtml(item.title || '--') + '</div>' +
            meta +
        '</div>' +
        '<div class="rec-card-actions">' +
            '<button type="button" onclick="searchResourceForWatchlist(' + item.id + ')" class="rec-card-btn rec-btn-search-resource">搜索</button>' +
            '<button type="button" onclick="subscribeWatchlist(' + item.id + ')" class="rec-card-btn rec-btn-subscribe">订阅</button>' +
            '<button type="button" onclick="removeFromWatchlist(' + item.id + ')" class="rec-card-btn rec-btn-remove">移除</button>' +
        '</div>' +
    '</div>';
}

function buildLoadingSkeletonHtml(count) {
    let html = '';
    for (let i = 0; i < count; i++) {
        html += '<div class="rec-card animate-pulse">' +
            '<div class="aspect-[2/3] bg-slate-800/60"></div>' +
            '<div class="rec-card-info space-y-2">' +
                '<div class="h-3 bg-slate-800/60 rounded w-3/4"></div>' +
                '<div class="h-2.5 bg-slate-800/40 rounded w-1/2"></div>' +
            '</div>' +
            '<div class="rec-card-actions">' +
                '<div class="h-7 bg-slate-800/40 rounded flex-1"></div>' +
                '<div class="h-7 bg-slate-800/40 rounded flex-1"></div>' +
                '<div class="h-7 bg-slate-800/40 rounded flex-1"></div>' +
            '</div>' +
        '</div>';
    }
    return html;
}

function showRecommendationEmpty(isError, message) {
    const emptyEl = document.getElementById('recommendation-empty');
    const iconEl = document.getElementById('recommendation-empty-icon');
    const textEl = document.getElementById('recommendation-empty-text');
    const hintEl = document.getElementById('recommendation-empty-hint');
    if (!emptyEl) return;
    if (isError) {
        if (iconEl) {
            iconEl.className = 'rec-empty-error mb-2';
            iconEl.innerHTML = '<svg class="w-8 h-8 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
        }
        if (textEl) {
            textEl.className = 'rec-empty-error-text text-sm';
            textEl.textContent = message || '请求失败';
        }
        if (hintEl) {
            hintEl.className = 'rec-empty-hint text-xs mt-1';
            hintEl.textContent = '请检查网络连接或 TMDB 配置后重试';
            hintEl.classList.remove('hidden');
        }
    } else {
        if (iconEl) {
            iconEl.className = 'text-slate-600 mb-2';
            iconEl.innerHTML = '<svg class="w-8 h-8 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 4V2m0 2a2 2 0 012 2v8a2 2 0 01-2 2m0-12a2 2 0 00-2 2v8a2 2 0 002 2m0 0v2m10-12V2m0 2a2 2 0 00-2 2v8a2 2 0 002 2m0-12a2 2 0 012 2v8a2 2 0 01-2 2m0 0v2"/></svg>';
        }
        if (textEl) {
            textEl.className = 'text-sm text-slate-500';
            textEl.textContent = '暂无内容';
        }
        if (hintEl) {
            hintEl.classList.add('hidden');
        }
    }
    emptyEl.classList.remove('hidden');
}

function renderRecommendationGrid(items) {
    const gridEl = document.getElementById('recommendation-grid');
    const emptyEl = document.getElementById('recommendation-empty');
    if (!gridEl) return;

    if (!Array.isArray(items) || !items.length) {
        gridEl.innerHTML = '';
        gridEl.classList.add('hidden');
        showRecommendationEmpty(false);
        updatePagination();
        return;
    }

    if (emptyEl) emptyEl.classList.add('hidden');
    gridEl.classList.remove('hidden');
    gridEl.innerHTML = items.map((item, idx) => buildRecCardHtml(item, idx)).join('');
    updatePagination();
}

function renderLoadingGrid() {
    const gridEl = document.getElementById('recommendation-grid');
    const emptyEl = document.getElementById('recommendation-empty');
    if (!gridEl) return;
    if (emptyEl) emptyEl.classList.add('hidden');
    gridEl.classList.remove('hidden');
    gridEl.innerHTML = buildLoadingSkeletonHtml(12);
}

function renderWatchlistGrid() {
    const gridEl = document.getElementById('recommendation-grid');
    const emptyEl = document.getElementById('recommendation-empty');
    if (!gridEl) return;

    if (!recommendationWatchlist.length) {
        gridEl.innerHTML = '';
        gridEl.classList.add('hidden');
        showRecommendationEmpty(false);
        return;
    }

    if (emptyEl) emptyEl.classList.add('hidden');
    gridEl.classList.remove('hidden');
    gridEl.innerHTML = recommendationWatchlist.map((item) => buildWatchlistCardHtml(item)).join('');
}

async function loadRecommendationTrending(timeWindow, page) {
    const mediaType = document.getElementById('recommendation-media-type')?.value || 'all';
    setActiveRecTab('trending-' + timeWindow);
    setRecommendationContentHeader(
        timeWindow === 'day' ? '今日热榜' : '本周热榜',
        timeWindow === 'day' ? 'TMDB 今日热度变化最快的影视条目。' : '过去一周热度最高的影视资源。'
    );
    recommendationItems = [];
    setRecommendationBusy(true);
    renderLoadingGrid();
    try {
        const p = page || 1;
        const data = await window.MediaHubApi.getJson('/tmdb/trending?media_type=' + encodeURIComponent(mediaType) + '&time_window=' + encodeURIComponent(timeWindow) + '&page=' + p);
        recommendationItems = Array.isArray(data?.items) ? data.items : [];
        recommendationPagination.currentPage = data?.page || p;
        recommendationPagination.totalPages = data?.total_pages || 1;
        recommendationPagination.currentContext = { type: 'trending', timeWindow: timeWindow, mediaType: mediaType };
        renderRecommendationGrid(recommendationItems);
    } catch (e) {
        recommendationItems = [];
        const gridEl = document.getElementById('recommendation-grid');
        if (gridEl) { gridEl.innerHTML = ''; gridEl.classList.add('hidden'); }
        const msg = e?.message || '未知错误';
        showRecommendationEmpty(true, '加载热榜失败：' + msg);
        updatePagination();
    } finally {
        setRecommendationBusy(false);
    }
}

async function loadRecommendationPopular(mediaType, page) {
    setActiveRecTab('popular-' + mediaType);
    setRecommendationContentHeader(
        mediaType === 'movie' ? '热门电影' : '热门剧集',
        mediaType === 'movie' ? '当前最受关注的电影片单。' : '当前最受关注的剧集片单。'
    );
    recommendationItems = [];
    setRecommendationBusy(true);
    renderLoadingGrid();
    try {
        const p = page || 1;
        const data = await window.MediaHubApi.getJson('/tmdb/popular?media_type=' + encodeURIComponent(mediaType) + '&page=' + p);
        recommendationItems = Array.isArray(data?.items) ? data.items : [];
        recommendationPagination.currentPage = data?.page || p;
        recommendationPagination.totalPages = data?.total_pages || 1;
        recommendationPagination.currentContext = { type: 'popular', mediaType: mediaType };
        renderRecommendationGrid(recommendationItems);
    } catch (e) {
        recommendationItems = [];
        const gridEl = document.getElementById('recommendation-grid');
        if (gridEl) { gridEl.innerHTML = ''; gridEl.classList.add('hidden'); }
        const msg = e?.message || '未知错误';
        showRecommendationEmpty(true, '加载热门失败：' + msg);
        updatePagination();
    } finally {
        setRecommendationBusy(false);
    }
}

async function searchRecommendationTmdb(queryOverride, mediaTypeOverride, page) {
    const query = queryOverride || document.getElementById('recommendation-search-input')?.value?.trim();
    if (!query) {
        restorePreviousRecTab();
        return;
    }
    const mediaType = mediaTypeOverride || document.getElementById('recommendation-media-type')?.value || 'all';
    setActiveRecTab('search');
    setRecommendationContentHeader('搜索：' + query, '在 TMDB 中搜索影视名称，并可继续搜索资源或创建订阅。');
    recommendationItems = [];
    setRecommendationBusy(true);
    renderLoadingGrid();
    try {
        const p = page || 1;
        const data = await window.MediaHubApi.getJson('/tmdb/search?q=' + encodeURIComponent(query) + '&media_type=' + encodeURIComponent(mediaType) + '&page=' + p);
        recommendationItems = Array.isArray(data?.items) ? data.items : [];
        recommendationPagination.currentPage = data?.page || p;
        recommendationPagination.totalPages = data?.total_pages || 1;
        recommendationPagination.currentContext = { type: 'search', query: query, mediaType: mediaType };
        renderRecommendationGrid(recommendationItems);
    } catch (e) {
        recommendationItems = [];
        const gridEl = document.getElementById('recommendation-grid');
        if (gridEl) { gridEl.innerHTML = ''; gridEl.classList.add('hidden'); }
        const msg = e?.message || '未知错误';
        showRecommendationEmpty(true, '搜索失败：' + msg);
        updatePagination();
    } finally {
        setRecommendationBusy(false);
    }
}

function showRecommendationWatchlist() {
    setActiveRecTab('watchlist');
    setRecommendationContentHeader('想看清单', '你保存的待看条目，后续可继续搜索资源或创建订阅。');
    resetPagination();
    renderWatchlistGrid();
}

async function loadRecommendationWatchlist() {
    try {
        const data = await window.MediaHubApi.getJson('/recommendation/state');
        recommendationWatchlist = Array.isArray(data?.items) ? data.items : [];
        updateWatchlistCount();
    } catch (e) {
        recommendationWatchlist = [];
        updateWatchlistCount();
    }
}

async function toggleRecommendationWatchlist(index) {
    const item = recommendationItems[index];
    if (!item) return;
    if (isInWatchlist(item.id, item.media_type)) {
        const wlItem = recommendationWatchlist.find((w) => w.tmdb_id === item.id && w.media_type === item.media_type);
        if (wlItem) {
            await removeFromWatchlist(wlItem.id);
        }
        return;
    }
    try {
        await window.MediaHubApi.postJson('/recommendation/watchlist/add', {
            tmdb_id: item.id,
            media_type: item.media_type,
            title: item.title,
            original_title: item.original_title || '',
            year: item.year || '',
            poster_url: item.poster_url || '',
            overview: item.overview || '',
            vote_average: item.vote_average || 0,
        });
        window.showToast('已添加到想看清单', { tone: 'success', duration: 2000, placement: 'top-center' });
        await loadRecommendationWatchlist();
        renderRecommendationGrid(recommendationItems);
    } catch (e) {
        window.showToast('添加失败：' + (e?.message || '未知错误'), { tone: 'error', duration: 3000, placement: 'top-center' });
    }
}

async function removeFromWatchlist(itemId) {
    try {
        await window.MediaHubApi.postJson('/recommendation/watchlist/remove', { id: itemId });
        window.showToast('已从想看清单移除', { tone: 'info', duration: 2000, placement: 'top-center' });
        await loadRecommendationWatchlist();
        if (recommendationActiveTab === 'watchlist') {
            renderWatchlistGrid();
        }
    } catch (e) {
        window.showToast('移除失败：' + (e?.message || '未知错误'), { tone: 'error', duration: 3000, placement: 'top-center' });
    }
}

function buildSearchKeyword(item) {
    return item.title || item.original_title || '';
}

function searchResourceForRecommendation(index) {
    const item = recommendationItems[index];
    if (!item) return;
    doSearchResource(item);
}

function searchResourceForWatchlist(itemId) {
    const item = recommendationWatchlist.find((w) => w.id === itemId);
    if (!item) return;
    doSearchResource(item);
}

function doSearchResource(item) {
    const keyword = buildSearchKeyword(item);
    if (!keyword) {
        window.showToast('无法生成搜索关键词', { tone: 'warn', duration: 2200, placement: 'top-center' });
        return;
    }
    if (typeof switchTab === 'function') {
        switchTab('resource');
    }
    const input = document.getElementById('resource-search-input');
    if (input) {
        input.value = keyword;
        input.focus();
        input.setSelectionRange?.(keyword.length, keyword.length);
    }
    if (typeof syncResourceSearchInputActions === 'function') syncResourceSearchInputActions();
    if (typeof searchResources === 'function') {
        searchResources();
    }
}

async function subscribeRecommendation(index) {
    const item = recommendationItems[index];
    if (!item) return;
    await doSubscribe(item);
}

async function subscribeWatchlist(itemId) {
    const item = recommendationWatchlist.find((w) => w.id === itemId);
    if (!item) return;
    await doSubscribe(item);
}

async function doSubscribe(item) {
    if (typeof openNewSubscriptionTask !== 'function') {
        window.showToast('订阅模块未加载', { tone: 'error', duration: 2600, placement: 'top-center' });
        return;
    }
    const tmdbId = item.tmdb_id || item.id;
    const mediaType = item.media_type || 'movie';
    if (!tmdbId) {
        window.showToast('缺少 TMDB ID', { tone: 'error', duration: 2600, placement: 'top-center' });
        return;
    }
    try {
        const data = await window.MediaHubApi.getJson('/tmdb/detail?tmdb_id=' + tmdbId + '&media_type=' + encodeURIComponent(mediaType));
        if (!data?.ok || !data.task_binding) {
            window.showToast('获取 TMDB 详情失败', { tone: 'error', duration: 2600, placement: 'top-center' });
            return;
        }
        openNewSubscriptionTask();
        const mediaTypeEl = document.getElementById('subscription_media_type');
        if (mediaTypeEl) mediaTypeEl.value = mediaType;
        const titleEl = document.getElementById('subscription_title');
        if (titleEl) titleEl.value = String(item.title || data.task_binding?.tmdb_title || '').trim();
        const yearEl = document.getElementById('subscription_year');
        if (yearEl) yearEl.value = String(item.year || data.task_binding?.tmdb_year || '').trim();
        setTimeout(() => {
            if (typeof setSubscriptionTmdbBinding === 'function') {
                setSubscriptionTmdbBinding(data.task_binding);
            }
        }, 100);
    } catch (e) {
        window.showToast('获取 TMDB 详情失败：' + (e?.message || '未知错误'), { tone: 'error', duration: 3000, placement: 'top-center' });
    }
}

function closeRecDetail() {
    if (typeof hideLockedModal === 'function') {
        hideLockedModal('rec-detail-modal');
    } else {
        document.getElementById('rec-detail-modal')?.classList.add('hidden');
    }
}

function renderRecDetailContent(item, detail) {
    const el = document.getElementById('rec-detail-content');
    if (!el) return;

    const posterHtml = item.poster_url
        ? '<img src="' + escapeRecHtml(item.poster_url) + '" alt="' + escapeRecHtml(item.title) + '">'
        : '<div class="rec-detail-poster-placeholder">无封面</div>';

    const mediaLabel = item.media_type === 'tv' ? '电视剧' : '电影';
    const val = Number(item.vote_average || 0);
    const voteHtml = val > 0
        ? '<div class="rec-detail-vote"><svg viewBox="0 0 20 20" fill="currentColor"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/></svg><span class="rec-detail-vote-score">' + val.toFixed(1) + '</span><span class="rec-detail-vote-max">/ 10</span></div>'
        : '';

    const statusText = detail?.status || '';
    const statusMap = { 'Released': '已上映', 'Returning Series': '连载中', 'Ended': '已完结', 'Canceled': '已取消', 'In Production': '制作中', 'Planned': '计划中', 'Post Production': '后期制作中' };
    const statusLabel = statusMap[statusText] || statusText;

    const aliases = detail?.aliases || [];
    const aliasesHtml = aliases.length
        ? '<div class="rec-detail-aliases"><div class="rec-detail-aliases-label">别名</div><div class="rec-detail-aliases-list">' + aliases.slice(0, 8).map((a) => '<span class="rec-detail-alias-chip">' + escapeRecHtml(a) + '</span>').join('') + '</div></div>'
        : '';

    let episodeHtml = '';
    if (item.media_type === 'tv' && detail) {
        const seasons = detail.total_seasons || 0;
        const episodes = detail.total_episodes || 0;
        if (seasons > 0 || episodes > 0) {
            episodeHtml = '<div class="rec-detail-episodes">';
            if (seasons > 0) episodeHtml += '<div>季数：<strong>' + seasons + '</strong></div>';
            if (episodes > 0) episodeHtml += '<div>集数：<strong>' + episodes + '</strong></div>';
            episodeHtml += '</div>';
            const seasonMap = detail.season_episode_map || {};
            const seasonKeys = Object.keys(seasonMap).sort((a, b) => Number(a) - Number(b));
            if (seasonKeys.length > 0) {
                episodeHtml += '<div class="rec-detail-season-chips">';
                seasonKeys.forEach((s) => {
                    episodeHtml += '<span class="rec-detail-season-chip">S' + s + ': ' + seasonMap[s] + '集</span>';
                });
                episodeHtml += '</div>';
            }
        }
    }

    const inWatchlist = isInWatchlist(item.id, item.media_type);
    const watchlistBtnClass = inWatchlist ? 'rec-detail-btn-watchlist-active' : 'rec-detail-btn-watchlist';
    const watchlistLabel = inWatchlist ? '已想看' : '想看';

    el.innerHTML =
        '<div class="rec-detail-header">' +
            '<h3>' + escapeRecHtml(item.title || '--') + '</h3>' +
            '<button type="button" onclick="closeRecDetail()" class="rec-detail-close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg></button>' +
        '</div>' +
        '<div class="rec-detail-body">' +
            '<div class="rec-detail-layout">' +
                '<div class="rec-detail-poster">' + posterHtml + '</div>' +
                '<div class="rec-detail-info">' +
                    (item.original_title && item.original_title !== item.title
                        ? '<div class="rec-detail-original-title">' + escapeRecHtml(item.original_title) + '</div>'
                        : '') +
                    '<div class="rec-detail-tags">' +
                        '<span class="rec-detail-tag-type">' + escapeRecHtml(mediaLabel) + '</span>' +
                        (item.year ? '<span class="rec-detail-tag-year">' + escapeRecHtml(String(item.year)) + '</span>' : '') +
                        (statusLabel ? '<span class="rec-detail-tag-status">' + escapeRecHtml(statusLabel) + '</span>' : '') +
                    '</div>' +
                    (voteHtml || '') +
                    (item.overview ? '<div class="rec-detail-overview">' + escapeRecHtml(item.overview) + '</div>' : '') +
                    episodeHtml +
                    aliasesHtml +
                '</div>' +
            '</div>' +
        '</div>' +
        '<div class="rec-detail-footer">' +
            '<button type="button" onclick="closeRecDetail(); toggleRecommendationWatchlistByItem(' + item.id + ')" class="rec-detail-btn ' + watchlistBtnClass + '">' + watchlistLabel + '</button>' +
            '<button type="button" onclick="closeRecDetail(); searchResourceForRecommendationByItem(' + item.id + ')" class="rec-detail-btn rec-detail-btn-search">搜索</button>' +
            '<button type="button" onclick="closeRecDetail(); subscribeRecommendationByItem(' + item.id + ')" class="rec-detail-btn rec-detail-btn-subscribe">订阅</button>' +
        '</div>';
}

async function openRecDetail(index) {
    const item = recommendationItems[index];
    if (!item) return;
    const contentEl = document.getElementById('rec-detail-content');
    if (contentEl) contentEl.innerHTML = '<div class="py-12 text-center text-slate-500 text-sm">加载详情中...</div>';
    if (typeof showLockedModal === 'function') {
        showLockedModal('rec-detail-modal');
    } else {
        document.getElementById('rec-detail-modal')?.classList.remove('hidden');
    }
    try {
        const data = await window.MediaHubApi.getJson('/tmdb/detail?tmdb_id=' + item.id + '&media_type=' + encodeURIComponent(item.media_type));
        renderRecDetailContent(item, data?.detail || {});
    } catch (e) {
        renderRecDetailContent(item, {});
    }
}

async function openWatchlistDetail(itemId) {
    const item = recommendationWatchlist.find((w) => w.id === itemId);
    if (!item) return;
    const contentEl = document.getElementById('rec-detail-content');
    if (contentEl) contentEl.innerHTML = '<div class="py-12 text-center text-slate-500 text-sm">加载详情中...</div>';
    if (typeof showLockedModal === 'function') {
        showLockedModal('rec-detail-modal');
    } else {
        document.getElementById('rec-detail-modal')?.classList.remove('hidden');
    }
    try {
        const data = await window.MediaHubApi.getJson('/tmdb/detail?tmdb_id=' + item.tmdb_id + '&media_type=' + encodeURIComponent(item.media_type));
        renderRecDetailContent(item, data?.detail || {});
    } catch (e) {
        renderRecDetailContent(item, {});
    }
}

function toggleRecommendationWatchlistByItem(tmdbId) {
    const idx = recommendationItems.findIndex((i) => i.id === tmdbId);
    if (idx >= 0) toggleRecommendationWatchlist(idx);
}

function searchResourceForRecommendationByItem(tmdbId) {
    const item = recommendationItems.find((i) => i.id === tmdbId);
    if (item) doSearchResource(item);
}

function subscribeRecommendationByItem(tmdbId) {
    const item = recommendationItems.find((i) => i.id === tmdbId);
    if (item) doSubscribe(item);
}

async function loadExploreGenres(mediaType) {
    if (exploreGenresLoaded[mediaType]) return;
    try {
        const data = await window.MediaHubApi.getJson('/tmdb/genres?media_type=' + encodeURIComponent(mediaType));
        exploreGenres[mediaType] = Array.isArray(data?.genres) ? data.genres : [];
        exploreGenresLoaded[mediaType] = true;
    } catch (e) {
        exploreGenres[mediaType] = [];
    }
}

function renderExploreGenreChips(mediaType) {
    const container = document.getElementById('rec-explore-genres');
    if (!container) return;
    const genres = exploreGenres[mediaType] || [];
    container.innerHTML = genres.map(function(g) {
        const genreId = String(g.id);
        const selectedClass = exploreFilterState.genres.includes(genreId) ? ' is-selected' : '';
        return '<button type="button" class="rec-genre-chip' + selectedClass + '" data-genre-id="' + genreId + '" onclick="toggleExploreGenre(\'' + genreId + '\')">' +
            escapeRecHtml(g.name) +
        '</button>';
    }).join('');
    syncExploreFilterUi();
}

function getSelectedExploreGenres() {
    return exploreFilterState.genres.join(',');
}

function renderDecadeChips() {
    var container = document.getElementById('rec-explore-decade-chips');
    if (!container) return;
    var currentDecade = Math.floor(new Date().getFullYear() / 10) * 10;
    var html = '';
    for (var d = currentDecade; d >= 1950; d -= 10) {
        html += '<button type="button" class="rec-genre-chip" data-decade="' + d + '" onclick="selectDecade(\'' + d + '\')">' + d + 's</button>';
    }
    container.innerHTML = html;
    syncExploreFilterUi();
}

function selectDecade(input) {
    const decade = typeof input === 'string' ? input : (input?.dataset?.decade || '');
    exploreFilterState.decade = exploreFilterState.decade === decade ? '' : decade;
    syncExploreFilterUi();
}

function getSelectedDecade() {
    return exploreFilterState.decade;
}

async function onExploreMediaTypeChange() {
    const mediaType = document.getElementById('rec-explore-media-type')?.value || 'movie';
    await setExploreMediaType(mediaType, false);
}

async function setExploreMediaType(mediaType, applyNow) {
    const normalized = mediaType === 'tv' ? 'tv' : 'movie';
    const changed = exploreFilterState.mediaType !== normalized;
    exploreFilterState.mediaType = normalized;
    if (changed) {
        exploreFilterState.genres = [];
    }
    updateSortOptions(normalized);
    await loadExploreGenres(normalized);
    renderExploreGenreChips(normalized);
    syncExploreFilterUi();
    if (applyNow && recommendationActiveTab === 'explore' && isCompactExploreFilters()) {
        await searchRecommendationDiscover();
    }
}

async function setExploreSort(sortBy, applyNow) {
    exploreFilterState.sortBy = sortBy || EXPLORE_DEFAULT_FILTERS.sortBy;
    syncExploreFilterUi();
    if (applyNow && recommendationActiveTab === 'explore' && isCompactExploreFilters()) {
        await searchRecommendationDiscover();
    }
}

function toggleExploreGenre(genreId) {
    const id = String(genreId);
    if (exploreFilterState.genres.includes(id)) {
        exploreFilterState.genres = exploreFilterState.genres.filter((item) => item !== id);
    } else {
        exploreFilterState.genres = exploreFilterState.genres.concat(id);
    }
    syncExploreFilterUi();
}

async function resetExploreFilters() {
    exploreFilterState = getDefaultExploreFilters();
    updateSortOptions(exploreFilterState.mediaType);
    await loadExploreGenres(exploreFilterState.mediaType);
    renderExploreGenreChips(exploreFilterState.mediaType);
    syncExploreFilterUi();
}

async function showRecommendationExplore() {
    setActiveRecTab('explore');
    setRecommendationContentHeader('探索发现', '当前条件：' + getExploreSummaryText());
    resetPagination();
    recommendationItems = [];
    bindExploreFilterInputs();
    closeExploreFiltersDrawer();
    updateSortOptions(exploreFilterState.mediaType);
    await loadExploreGenres(exploreFilterState.mediaType);
    renderExploreGenreChips(exploreFilterState.mediaType);
    syncExploreFilterUi();
    await searchRecommendationDiscover();
}

async function searchRecommendationDiscover(page) {
    const mediaType = exploreFilterState.mediaType;
    const sortBy = exploreFilterState.sortBy;
    const language = exploreFilterState.language;
    const decade = exploreFilterState.decade;
    const yearFrom = decade || '';
    const yearTo = decade ? String(Number(decade) + 9) : '';
    const rating = exploreFilterState.rating;
    const voteCount = exploreFilterState.voteCount;
    const runtimeGte = exploreFilterState.runtimeGte;
    const runtimeLte = exploreFilterState.runtimeLte;
    const genres = getSelectedExploreGenres();
    recommendationItems = [];
    setRecommendationContentHeader('探索发现', '当前条件：' + getExploreSummaryText());
    setRecommendationBusy(true);
    renderLoadingGrid();
    try {
        const p = page || 1;
        let url = '/tmdb/discover?media_type=' + encodeURIComponent(mediaType) +
            '&sort_by=' + encodeURIComponent(sortBy) +
            '&page=' + p;
        if (genres) url += '&genres=' + encodeURIComponent(genres);
        if (language) url += '&with_original_language=' + encodeURIComponent(language);
        if (yearFrom) url += '&year_from=' + encodeURIComponent(yearFrom);
        if (yearTo) url += '&year_to=' + encodeURIComponent(yearTo);
        if (rating) url += '&vote_average_gte=' + encodeURIComponent(rating);
        if (voteCount) url += '&vote_count_gte=' + encodeURIComponent(voteCount);
        if (runtimeGte) url += '&runtime_gte=' + encodeURIComponent(runtimeGte);
        if (runtimeLte) url += '&runtime_lte=' + encodeURIComponent(runtimeLte);
        const data = await window.MediaHubApi.getJson(url);
        recommendationItems = Array.isArray(data?.items) ? data.items : [];
        recommendationPagination.currentPage = data?.page || p;
        recommendationPagination.totalPages = data?.total_pages || 1;
        recommendationPagination.currentContext = { type: 'discover' };
        renderRecommendationGrid(recommendationItems);
    } catch (e) {
        recommendationItems = [];
        const gridEl = document.getElementById('recommendation-grid');
        if (gridEl) { gridEl.innerHTML = ''; gridEl.classList.add('hidden'); }
        const msg = e?.message || '未知错误';
        showRecommendationEmpty(true, '探索失败：' + msg);
        updatePagination();
    } finally {
        setRecommendationBusy(false);
        syncExploreFilterUi();
    }
}

async function initRecommendationPage() {
    renderDecadeChips();
    bindExploreFilterInputs();
    updateSortOptions(exploreFilterState.mediaType);
    syncExploreFilterUi();
    window.addEventListener('resize', syncExploreFilterUi);
    await loadRecommendationWatchlist();
    if (!recommendationItems.length) {
        await loadRecommendationTrending('week');
    }
}

Object.assign(window, {
    loadRecommendationTrending,
    loadRecommendationPopular,
    searchRecommendationTmdb,
    showRecommendationWatchlist,
    toggleRecommendationWatchlist,
    removeFromWatchlist,
    searchResourceForRecommendation,
    searchResourceForWatchlist,
    subscribeRecommendation,
    subscribeWatchlist,
    openRecDetail,
    openWatchlistDetail,
    closeRecDetail,
    toggleRecommendationWatchlistByItem,
    searchResourceForRecommendationByItem,
    subscribeRecommendationByItem,
    initRecommendationPage,
    onRecommendationSearchInput,
    clearRecommendationSearch,
    goToRecommendationPage,
    showRecommendationExplore,
    searchRecommendationDiscover,
    applyExploreFilters,
    applyExploreMoreFilters,
    onExploreMediaTypeChange,
    setExploreMediaType,
    setExploreSort,
    toggleExploreGenre,
    openExploreFiltersDrawer,
    closeExploreFiltersDrawer,
    resetExploreFilters,
    toggleExploreMoreFilters,
    syncExploreMoreToggle,
    syncExploreFilterUi,
    updateSortOptions,
    selectDecade,
    getSelectedDecade,
});
