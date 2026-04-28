        function currentResourceSourceFormData() {
            return {
                name: document.getElementById('resource_source_name').value.trim(),
                channel_id: normalizeTelegramChannelIdInput(document.getElementById('resource_source_channel').value.trim()),
                enabled: document.getElementById('resource_source_enabled').checked
            };
        }

        function normalizeResourceSourceFilterValue(value) {
            const normalized = String(value || 'all').trim().toLowerCase();
            return normalized || 'all';
        }

        function sanitizeResourceLinkTypeList(values) {
            return uniquePreserveOrder((Array.isArray(values) ? values : [])
                .map(item => String(item || '').trim().toLowerCase())
                .filter(Boolean));
        }

        function getResourceSourcePrimaryLinkType(profile) {
            const primary = String(profile?.primary_link_type || '').trim().toLowerCase();
            if (primary && primary !== 'unknown') return primary;
            const dominant = sanitizeResourceLinkTypeList(profile?.dominant_link_types);
            const fallback = dominant.find(type => type !== 'unknown');
            return fallback || 'unknown';
        }

        function getResourceSourceTypes(profile) {
            const counts = profile?.link_type_counts && typeof profile.link_type_counts === 'object'
                ? profile.link_type_counts
                : {};
            const sorted = Object.entries(counts)
                .map(([type, count]) => [String(type || '').trim().toLowerCase(), Number(count || 0)])
                .filter(([type, count]) => type && Number.isFinite(count) && count > 0)
                .sort((a, b) => {
                    const countDiff = Number(b[1]) - Number(a[1]);
                    if (countDiff !== 0) return countDiff;
                    return String(getResourceLinkTypeLabel(a[0])).localeCompare(String(getResourceLinkTypeLabel(b[0])));
                })
                .map(([type]) => type);
            const nonUnknown = sorted.filter(type => type !== 'unknown');
            if (nonUnknown.length) return nonUnknown;
            if (sorted.length) return sorted;

            const dominant = sanitizeResourceLinkTypeList(profile?.dominant_link_types).filter(type => type !== 'unknown');
            if (dominant.length) return dominant;
            const primary = getResourceSourcePrimaryLinkType(profile);
            return primary && primary !== 'unknown' ? [primary] : [];
        }

        function getResourceSourceTypeCount(profile, type) {
            const normalized = String(type || '').trim().toLowerCase();
            const counts = profile?.link_type_counts && typeof profile.link_type_counts === 'object'
                ? profile.link_type_counts
                : {};
            const value = Number(counts[normalized] || 0);
            return Number.isFinite(value) && value > 0 ? value : 0;
        }

        function renderResourceSourceTypeBadges(profile, types = []) {
            const sourceTypes = sanitizeResourceLinkTypeList(types).filter(Boolean);
            const safeTypes = sourceTypes.length ? sourceTypes : [getResourceSourcePrimaryLinkType(profile)];
            return safeTypes
                .slice(0, 4)
                .map(type => {
                    const count = getResourceSourceTypeCount(profile, type);
                    const countText = count > 0 ? ` ${count}` : '';
                    return `<span class="resource-source-manager-type-badge">${escapeHtml(getResourceLinkTypeLabel(type))}${escapeHtml(countText)}</span>`;
                })
                .join('');
        }

        function getResourceSourceOutputCount(view) {
            const value = Number(view?.support?.matched_items || 0);
            return Number.isFinite(value) && value > 0 ? value : 0;
        }

        function getResourceSourceSectionIndex() {
            const index = {};
            (Array.isArray(resourceState.channel_sections) ? resourceState.channel_sections : []).forEach(section => {
                const channelId = normalizeTelegramChannelIdInput(section?.channel_id || '');
                if (!channelId) return;
                index[channelId] = section;
            });
            return index;
        }

        function getResourceSourceIndexByChannelId(channelId) {
            const normalized = normalizeTelegramChannelIdInput(channelId || '');
            if (!normalized) return -1;
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            for (let i = 0; i < sources.length; i += 1) {
                if (getResourceSourceChannelId(sources[i]) === normalized) return i;
            }
            return -1;
        }

        function getResourceSourceProfileFromIndex(source, sectionIndex = {}) {
            const channelId = getResourceSourceChannelId(source);
            if (!channelId) return {};
            const profileFromState = resourceState?.channel_profiles && typeof resourceState.channel_profiles === 'object'
                ? resourceState.channel_profiles[channelId]
                : null;
            if (profileFromState && typeof profileFromState === 'object') return profileFromState;
            const section = sectionIndex[channelId];
            if (section?.channel_profile && typeof section.channel_profile === 'object') return section.channel_profile;
            return {};
        }

        function parseResourceTimeMs(value) {
            if (!value) return 0;
            const d = new Date(value);
            const ms = d.getTime();
            return Number.isFinite(ms) ? ms : 0;
        }

        function formatResourceAgeText(timeMs) {
            if (!timeMs) return '未知';
            const diffMs = Math.max(0, Date.now() - timeMs);
            const diffMinutes = Math.floor(diffMs / 60000);
            if (diffMinutes < 60) return `${Math.max(1, diffMinutes)} 分钟前`;
            const diffHours = Math.floor(diffMinutes / 60);
            if (diffHours < 24) return `${diffHours} 小时前`;
            const diffDays = Math.floor(diffHours / 24);
            if (diffDays < 30) return `${diffDays} 天前`;
            const diffMonths = Math.floor(diffDays / 30);
            return `${diffMonths} 个月前`;
        }

        function getResourceSourceActivityMeta(profile) {
            const latestPublishedAt = String(profile?.latest_published_at || '').trim();
            const publishedMs = parseResourceTimeMs(latestPublishedAt);
            if (!publishedMs) {
                return {
                    tone: 'idle',
                    label: '待同步',
                    detail: '最近资源发布时间：--',
                };
            }

            const diffDays = (Date.now() - publishedMs) / 86400000;
            if (diffDays <= 3) {
                return {
                    tone: 'active',
                    label: '活跃',
                    detail: `最近资源发布时间：${formatTimeText(latestPublishedAt)}（${formatResourceAgeText(publishedMs)}）`,
                };
            }
            if (diffDays <= 14) {
                return {
                    tone: 'warm',
                    label: '近期',
                    detail: `最近资源发布时间：${formatTimeText(latestPublishedAt)}（${formatResourceAgeText(publishedMs)}）`,
                };
            }
            if (diffDays <= 45) {
                return {
                    tone: 'cool',
                    label: '稍冷',
                    detail: `最近资源发布时间：${formatTimeText(latestPublishedAt)}（${formatResourceAgeText(publishedMs)}）`,
                };
            }
            return {
                tone: 'cold',
                label: '不活跃',
                detail: `最近资源发布时间：${formatTimeText(latestPublishedAt)}（${formatResourceAgeText(publishedMs)}）`,
            };
        }

        function getResourceSourceActivityBucket(profile) {
            const latestPublishedAt = String(profile?.latest_published_at || '').trim();
            const publishedMs = parseResourceTimeMs(latestPublishedAt);
            if (!publishedMs) return 'unknown';
            const diffDays = (Date.now() - publishedMs) / 86400000;
            if (diffDays <= 7) return 'week';
            if (diffDays <= 30) return 'month';
            if (diffDays <= 180) return 'half_year';
            return 'older';
        }

        function getResourceSourceActivityBucketLabel(bucket) {
            const normalized = String(bucket || '').trim().toLowerCase();
            if (normalized === 'week') return '一周内';
            if (normalized === 'month') return '一月内';
            if (normalized === 'half_year') return '半年内';
            if (normalized === 'older') return '半年以上';
            if (normalized === 'unknown') return '待检测';
            return '全部';
        }

        function getResourceSourceViewList(sources = [], sectionIndex = {}) {
            return (Array.isArray(sources) ? sources : []).map((source, index) => {
                const channelId = getResourceSourceChannelId(source);
                const profile = getResourceSourceProfileFromIndex(source, sectionIndex);
                const support = resourceState?.subscription_channel_support && typeof resourceState.subscription_channel_support === 'object'
                    ? (resourceState.subscription_channel_support[channelId] || {})
                    : {};
                const activity = getResourceSourceActivityMeta(profile);
                const primaryType = getResourceSourcePrimaryLinkType(profile);
                const activityBucket = getResourceSourceActivityBucket(profile);
                const dominantTypes = sanitizeResourceLinkTypeList(profile?.dominant_link_types);
                const sourceTypes = getResourceSourceTypes(profile);
                const latestPublishedAt = String(profile?.latest_published_at || '').trim();
                const latestPublishedMs = parseResourceTimeMs(latestPublishedAt);
                return {
                    source,
                    index,
                    channelId,
                    support,
                    channelUrl: String(source?.url || (channelId ? `https://t.me/s/${channelId}` : '')).trim(),
                    profile,
                    activity,
                    activityBucket,
                    primaryType,
                    dominantTypes,
                    sourceTypes,
                    latestPublishedAt,
                    latestPublishedMs,
                };
            });
        }

        function getResourceSourceSortMode() {
            const mode = String(resourceSourceSortMode || 'manual').trim().toLowerCase();
            return mode || 'manual';
        }

        function compareResourceSourceViews(a, b, mode = getResourceSourceSortMode()) {
            const normalizedMode = String(mode || 'manual').trim().toLowerCase();
            if (normalizedMode === 'manual') {
                return Number(a?.index || 0) - Number(b?.index || 0);
            }
            if (normalizedMode === 'name') {
                return String(a?.source?.name || a?.channelId || '').localeCompare(String(b?.source?.name || b?.channelId || ''));
            }
            if (normalizedMode === 'activity') {
                const ad = (a?.activityBucket === 'week' ? 4 : a?.activityBucket === 'month' ? 3 : a?.activityBucket === 'half_year' ? 2 : a?.activityBucket === 'older' ? 1 : 0);
                const bd = (b?.activityBucket === 'week' ? 4 : b?.activityBucket === 'month' ? 3 : b?.activityBucket === 'half_year' ? 2 : b?.activityBucket === 'older' ? 1 : 0);
                if (bd !== ad) return bd - ad;
            }
            if (normalizedMode === 'support') {
                const aSearched = Math.max(0, Number(a?.support?.searched_runs || 0));
                const bSearched = Math.max(0, Number(b?.support?.searched_runs || 0));
                const aMatched = Math.max(0, Number(a?.support?.matched_runs || 0));
                const bMatched = Math.max(0, Number(b?.support?.matched_runs || 0));
                const aItems = getResourceSourceOutputCount(a);
                const bItems = getResourceSourceOutputCount(b);
                const aRate = aSearched > 0 ? (aMatched / aSearched) : -1;
                const bRate = bSearched > 0 ? (bMatched / bSearched) : -1;
                if (bRate !== aRate) return bRate - aRate;
                if (bItems !== aItems) return bItems - aItems;
                if (bSearched !== aSearched) return bSearched - aSearched;
            }
            if (normalizedMode === 'output') {
                const aItems = getResourceSourceOutputCount(a);
                const bItems = getResourceSourceOutputCount(b);
                if (bItems !== aItems) return bItems - aItems;
                const aMatched = Math.max(0, Number(a?.support?.matched_runs || 0));
                const bMatched = Math.max(0, Number(b?.support?.matched_runs || 0));
                if (bMatched !== aMatched) return bMatched - aMatched;
            }
            const aMs = Number(a?.latestPublishedMs || 0);
            const bMs = Number(b?.latestPublishedMs || 0);
            if (bMs !== aMs) return bMs - aMs;
            return String(a?.source?.name || a?.channelId || '').localeCompare(String(b?.source?.name || b?.channelId || ''));
        }

        function sortResourceSourceViews(views = [], mode = getResourceSourceSortMode()) {
            return [...(Array.isArray(views) ? views : [])].sort((a, b) => compareResourceSourceViews(a, b, mode));
        }

        function buildResourceSourceFilterOptions(sources, sectionIndex = {}) {
            const list = Array.isArray(sources) ? sources : [];
            const counters = {};
            list.forEach(source => {
                const profile = getResourceSourceProfileFromIndex(source, sectionIndex);
                const types = getResourceSourceTypes(profile);
                types.forEach(type => {
                    if (!type || type === 'unknown') return;
                    counters[type] = (Number(counters[type] || 0) + 1);
                });
            });

            const options = [{ value: 'all', label: '全部', count: list.length }];
            Object.entries(counters)
                .sort((a, b) => {
                    const countDiff = Number(b[1] || 0) - Number(a[1] || 0);
                    if (countDiff !== 0) return countDiff;
                    return String(getResourceLinkTypeLabel(a[0])).localeCompare(String(getResourceLinkTypeLabel(b[0])));
                })
                .forEach(([type, count]) => {
                    options.push({
                        value: String(type),
                        label: getResourceLinkTypeLabel(type),
                        count: Number(count || 0),
                    });
                });
            return options;
        }

        function isResourceSourceVisibleByFilter(source, sectionIndex = {}, typeFilter = resourceSourceFilter) {
            const filter = normalizeResourceSourceFilterValue(typeFilter);
            if (filter === 'all') return true;
            const profile = getResourceSourceProfileFromIndex(source, sectionIndex);
            const types = getResourceSourceTypes(profile);
            return types.includes(filter);
        }

        function isResourceSourceVisibleByActivity(source, sectionIndex = {}, activityFilter = resourceSourceActivityFilter) {
            const filter = normalizeResourceSourceFilterValue(activityFilter);
            if (filter === 'all') return true;
            const profile = getResourceSourceProfileFromIndex(source, sectionIndex);
            return getResourceSourceActivityBucket(profile) === filter;
        }

        function isResourceSourceVisibleByEnabled(source, enabledFilter = resourceSourceEnabledFilter) {
            const filter = normalizeResourceSourceFilterValue(enabledFilter);
            if (filter === 'all') return true;
            const enabled = source?.enabled !== false;
            if (filter === 'enabled') return enabled;
            if (filter === 'disabled') return !enabled;
            return true;
        }

        function buildResourceSourceActivityFilterOptions(sources, sectionIndex = {}) {
            const counters = { week: 0, month: 0, half_year: 0, older: 0, unknown: 0 };
            (Array.isArray(sources) ? sources : []).forEach(source => {
                const profile = getResourceSourceProfileFromIndex(source, sectionIndex);
                const bucket = getResourceSourceActivityBucket(profile);
                counters[bucket] = Number(counters[bucket] || 0) + 1;
            });
            return [
                { value: 'all', label: '全部', count: (Array.isArray(sources) ? sources.length : 0) },
                { value: 'week', label: '一周内', count: counters.week },
                { value: 'month', label: '一月内', count: counters.month },
                { value: 'half_year', label: '半年内', count: counters.half_year },
                { value: 'older', label: '半年以上', count: counters.older },
                { value: 'unknown', label: '待检测', count: counters.unknown },
            ];
        }

        function buildResourceSourceEnabledFilterOptions(sources) {
            const list = Array.isArray(sources) ? sources : [];
            let enabledCount = 0;
            let disabledCount = 0;
            list.forEach(source => {
                if (source?.enabled === false) disabledCount += 1;
                else enabledCount += 1;
            });
            return [
                { value: 'all', label: '全部', count: list.length },
                { value: 'enabled', label: '已启用', count: enabledCount },
                { value: 'disabled', label: '已停用', count: disabledCount },
            ];
        }

        function normalizeResourceSourceBulkSelections() {
            const validChannelIds = new Set((resourceState.sources || []).map(source => getResourceSourceChannelId(source)).filter(Boolean));
            const next = {};
            Object.entries(resourceSourceBulkSelected || {}).forEach(([channelId, checked]) => {
                if (!validChannelIds.has(channelId) || !checked) return;
                next[channelId] = true;
            });
            resourceSourceBulkSelected = next;
        }

        function normalizeResourceSourceManagerMobilePanel(panel) {
            return String(panel || '').trim().toLowerCase() === 'tools' ? 'tools' : 'list';
        }

        function isCompactResourceSourceManager() {
            return !!window.matchMedia && window.matchMedia('(max-width: 1279px)').matches;
        }

        function setResourceSourceManagerMobilePanel(panel) {
            resourceSourceManagerMobilePanel = normalizeResourceSourceManagerMobilePanel(panel);
        }

        function resetResourceSourceSortMode() {
            resourceSourceSortSessionActive = false;
            resourceSourceSortDraftIndexes = [];
            resourceSourceSortDragIndex = -1;
            resourceSourceSortPointerActive = false;
            resourceSourceSortPointerId = null;
            resourceSourceSortPointerIndex = -1;
            document.body?.classList.remove('resource-source-sort-pointer-active');
            document.querySelectorAll('.resource-source-manager-sort-row-over').forEach(row => {
                row.classList.remove('resource-source-manager-sort-row-over');
            });
        }

        function normalizeResourceSourceSortDraftIndexes() {
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            const validIndexes = new Set(sources.map((_, index) => index));
            const seen = new Set();
            const draft = [];
            (Array.isArray(resourceSourceSortDraftIndexes) ? resourceSourceSortDraftIndexes : []).forEach(rawIndex => {
                const index = Number(rawIndex);
                if (!Number.isInteger(index) || !validIndexes.has(index) || seen.has(index)) return;
                seen.add(index);
                draft.push(index);
            });
            sources.forEach((_, index) => {
                if (seen.has(index)) return;
                seen.add(index);
                draft.push(index);
            });
            resourceSourceSortDraftIndexes = draft;
            return draft;
        }

        function getResourceSourceSortDraftViews() {
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            const sectionIndex = getResourceSourceSectionIndex();
            const viewByIndex = new Map(getResourceSourceViewList(sources, sectionIndex).map(view => [view.index, view]));
            return normalizeResourceSourceSortDraftIndexes()
                .map(index => viewByIndex.get(index))
                .filter(Boolean);
        }

        function isResourceSourceSortDraftChanged() {
            const draft = normalizeResourceSourceSortDraftIndexes();
            return draft.some((sourceIndex, position) => sourceIndex !== position);
        }

        function startResourceSourceSortMode() {
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            if (!sources.length) {
                showToast('当前没有可排序的频道', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            resourceSourceSortSessionActive = true;
            resourceSourceSortMode = 'manual';
            resourceSourceSortDraftIndexes = sources.map((_, index) => index);
            resourceSourceSortDragIndex = -1;
            setResourceSourceManagerMobilePanel('list');
            renderResourceSourceManagerModal();
        }

        function cancelResourceSourceSortMode() {
            resetResourceSourceSortMode();
            renderResourceSourceManagerModal();
        }

        function moveResourceSourceSortDraftIndex(sourceIndex, offset) {
            const draft = normalizeResourceSourceSortDraftIndexes();
            const currentPosition = draft.indexOf(sourceIndex);
            const nextPosition = currentPosition + offset;
            if (currentPosition < 0 || nextPosition < 0 || nextPosition >= draft.length) return false;
            [draft[currentPosition], draft[nextPosition]] = [draft[nextPosition], draft[currentPosition]];
            resourceSourceSortDraftIndexes = draft;
            renderResourceSourceManagerModal();
            return true;
        }

        function moveResourceSourceSortDraftRelative(sourceIndex, targetIndex, after = false) {
            if (sourceIndex === targetIndex) return false;
            const draft = normalizeResourceSourceSortDraftIndexes();
            if (!draft.includes(sourceIndex) || !draft.includes(targetIndex)) return false;
            const nextDraft = draft.filter(index => index !== sourceIndex);
            let targetPosition = nextDraft.indexOf(targetIndex);
            if (targetPosition < 0) return false;
            if (after) targetPosition += 1;
            nextDraft.splice(targetPosition, 0, sourceIndex);
            const changed = nextDraft.some((value, index) => value !== draft[index]);
            if (!changed) return false;
            resourceSourceSortDraftIndexes = nextDraft;
            renderResourceSourceManagerModal();
            return true;
        }

        function beginResourceSourceSortPointerDrag(sourceIndex, pointerId = null) {
            if (!resourceSourceSortSessionActive || sourceIndex < 0) return false;
            resourceSourceSortPointerActive = true;
            resourceSourceSortPointerId = pointerId;
            resourceSourceSortPointerIndex = sourceIndex;
            resourceSourceSortDragIndex = sourceIndex;
            document.body?.classList.add('resource-source-sort-pointer-active');
            const row = document.querySelector(`[data-resource-source-sort-index="${String(sourceIndex)}"]`);
            row?.classList.add('resource-source-manager-sort-row-dragging');
            return true;
        }

        function updateResourceSourceSortPointerDrag(clientX, clientY) {
            if (!resourceSourceSortPointerActive || !resourceSourceSortSessionActive) return false;
            const sourceIndex = Number(resourceSourceSortPointerIndex);
            if (!Number.isInteger(sourceIndex) || sourceIndex < 0) return false;
            const hit = document.elementFromPoint(Number(clientX || 0), Number(clientY || 0));
            const row = hit?.closest?.('[data-resource-source-sort-index]');
            document.querySelectorAll('.resource-source-manager-sort-row-over').forEach(item => {
                if (item !== row) item.classList.remove('resource-source-manager-sort-row-over');
            });
            if (!row) return false;
            const targetIndex = parseInt(row.dataset.resourceSourceSortIndex || '-1', 10);
            if (targetIndex < 0 || targetIndex === sourceIndex) return false;
            row.classList.add('resource-source-manager-sort-row-over');
            const rect = row.getBoundingClientRect();
            const placeAfter = Number(clientY || 0) > rect.top + rect.height / 2;
            return moveResourceSourceSortDraftRelative(sourceIndex, targetIndex, placeAfter);
        }

        function endResourceSourceSortPointerDrag() {
            if (!resourceSourceSortPointerActive && resourceSourceSortDragIndex < 0) return;
            resourceSourceSortPointerActive = false;
            resourceSourceSortPointerId = null;
            resourceSourceSortPointerIndex = -1;
            resourceSourceSortDragIndex = -1;
            document.body?.classList.remove('resource-source-sort-pointer-active');
            document.querySelectorAll('.resource-source-manager-sort-row-dragging, .resource-source-manager-sort-row-over').forEach(row => {
                row.classList.remove('resource-source-manager-sort-row-dragging', 'resource-source-manager-sort-row-over');
            });
            renderResourceSourceManagerModal();
        }

        function applyResourceSourceSortPresetToDraft(mode = null) {
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            if (!sources.length) return;
            const presetEl = document.getElementById('resource-source-manager-sort-preset');
            const sortMode = String(mode || presetEl?.value || 'manual').trim().toLowerCase() || 'manual';
            const sectionIndex = getResourceSourceSectionIndex();
            resourceSourceSortDraftIndexes = sortResourceSourceViews(
                getResourceSourceViewList(sources, sectionIndex),
                sortMode
            ).map(view => view.index);
            resourceSourceSortDragIndex = -1;
            renderResourceSourceManagerModal();
        }

        async function saveResourceSourceSortMode() {
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            if (!sources.length) {
                resetResourceSourceSortMode();
                renderResourceSourceManagerModal();
                return;
            }
            const draft = normalizeResourceSourceSortDraftIndexes();
            const nextSources = draft.map(index => sources[index]).filter(Boolean);
            const changed = isResourceSourceSortDraftChanged();
            if (!changed) {
                resetResourceSourceSortMode();
                renderResourceSourceManagerModal();
                showToast('频道顺序未变化', { tone: 'info', duration: 2200, placement: 'top-center' });
                return;
            }
            try {
                const saveTask = persistResourceSources(nextSources, { immediate: true });
                resetResourceSourceSortMode();
                renderResourceSourceManagerModal();
                showToast(`已保存 ${nextSources.length} 个频道的顺序`, { tone: 'success', duration: 2600, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, '排序');
            } catch (e) {
                showToast(`排序保存失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        function openResourceSourceManagerModal() {
            switchTab('settings');
            resourceSourceManagerOpen = true;
            resetResourceSourceSortMode();
            setResourceSourceManagerMobilePanel('list');
            normalizeResourceSourceBulkSelections();
            showLockedModal('resource-source-manager-modal');
            renderResourceSourceManagerModal();
        }

        function closeResourceSourceManagerModal() {
            resourceSourceManagerOpen = false;
            resetResourceSourceSortMode();
            hideLockedModal('resource-source-manager-modal');
        }

        function setResourceSourceBulkSelected(channelId, selected) {
            const normalized = normalizeTelegramChannelIdInput(channelId);
            if (!normalized) return;
            resourceSourceBulkSelected = {
                ...resourceSourceBulkSelected,
                [normalized]: !!selected,
            };
            if (!selected) delete resourceSourceBulkSelected[normalized];
        }

        function selectAllFilteredResourceSources() {
            toggleSelectAllFilteredResourceSources(true);
        }

        function unselectFilteredResourceSources() {
            toggleSelectAllFilteredResourceSources(false);
        }

        function toggleSelectAllFilteredResourceSources(checked) {
            const filtered = getFilteredResourceSourceViewList();
            const next = { ...resourceSourceBulkSelected };
            filtered.forEach(view => {
                if (!view.channelId) return;
                if (checked) next[view.channelId] = true;
                else delete next[view.channelId];
            });
            resourceSourceBulkSelected = next;
            renderResourceSourceManagerModal();
        }

        function clearResourceSourceSelections() {
            resourceSourceBulkSelected = {};
            renderResourceSourceManagerModal();
        }

        function invertFilteredResourceSourceSelections() {
            const filtered = getFilteredResourceSourceViewList();
            const next = { ...resourceSourceBulkSelected };
            filtered.forEach(view => {
                if (!view.channelId) return;
                if (next[view.channelId]) delete next[view.channelId];
                else next[view.channelId] = true;
            });
            resourceSourceBulkSelected = next;
            renderResourceSourceManagerModal();
        }

        function getResourceSourceSortModeLabel(mode = getResourceSourceSortMode()) {
            const normalized = String(mode || 'manual').trim().toLowerCase();
            if (normalized === 'recent') return '最近发布时间';
            if (normalized === 'activity') return '活跃度';
            if (normalized === 'support') return '订阅支持度';
            if (normalized === 'output') return '产出次数';
            if (normalized === 'name') return '频道名称';
            return '手动顺序';
        }

        async function applyResourceSourceCurrentSortOrder() {
            const mode = getResourceSourceSortMode();
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            if (!sources.length) {
                showToast('当前没有可排序的频道', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            if (mode === 'manual') {
                showToast('当前已经是手动顺序，无需应用', { tone: 'info', duration: 2200, placement: 'top-center' });
                return;
            }

            const sectionIndex = getResourceSourceSectionIndex();
            const sortedViews = sortResourceSourceViews(getResourceSourceViewList(sources, sectionIndex), mode);
            const nextSources = sortedViews.map(view => view.source);
            const changed = nextSources.some((source, index) => getResourceSourceChannelId(source) !== getResourceSourceChannelId(sources[index]));
            if (!changed) {
                showToast('当前频道顺序已经符合这个排序', { tone: 'info', duration: 2200, placement: 'top-center' });
                return;
            }
            const ok = await showAppConfirm(`将按“${getResourceSourceSortModeLabel(mode)}”重排全部 ${nextSources.length} 个频道，并保存为新的手动顺序。确定继续吗？`);
            if (!ok) return;
            try {
                const saveTask = persistResourceSources(nextSources);
                resourceSourceSortMode = 'manual';
                renderResourceSourceManagerModal();
                showToast('已应用为频道顺序', { tone: 'success', duration: 2400, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, '排序');
            } catch (e) {
                showToast(`排序保存失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        async function bulkMoveResourceSources(position) {
            const selectedIds = getSelectedResourceSourceIdsInFiltered();
            if (!selectedIds.length) {
                showToast('请先在当前筛选结果中勾选要移动的频道', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const direction = String(position || '').trim().toLowerCase() === 'bottom' ? 'bottom' : 'top';
            const selectedSet = new Set(selectedIds);
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            const selectedInView = getFilteredResourceSourceViewList()
                .filter(view => selectedSet.has(view.channelId))
                .map(view => view.source);
            const rest = sources.filter(source => !selectedSet.has(getResourceSourceChannelId(source)));
            const nextSources = direction === 'bottom'
                ? [...rest, ...selectedInView]
                : [...selectedInView, ...rest];
            try {
                const saveTask = persistResourceSources(nextSources);
                resourceSourceSortMode = 'manual';
                renderResourceSourceManagerModal();
                showToast(`已${direction === 'bottom' ? '置底' : '置顶'} ${selectedInView.length} 个频道`, { tone: 'success', duration: 2400, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, direction === 'bottom' ? '置底' : '置顶');
            } catch (e) {
                showToast(`移动失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        async function syncSelectedResourceSourceNames() {
            const selectedIds = getSelectedResourceSourceIdsInFiltered();
            if (!selectedIds.length) {
                showToast('请先勾选要同步名称的频道', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const ok = await showAppConfirm(`将从 TG 公开频道页同步 ${selectedIds.length} 个频道的官方名称，并覆盖当前频道名称。确定继续吗？`);
            if (!ok) return;

            resourceSourceNameSyncBusy = true;
            renderResourceSourceManagerModal();
            try {
                const data = await window.MediaHubApi.postJson('/resource/channels/sync-names', {
                    channel_ids: selectedIds,
                });
                const nextSources = Array.isArray(data.sources) ? data.sources : null;
                if (nextSources) {
                    applyResourceSourcesLocal(nextSources, { deferHeavyRender: true });
                }
                const success = Math.max(0, Number(data.success || 0));
                const failed = Math.max(0, Number(data.failed || 0));
                if (success > 0 && failed > 0) {
                    const firstError = Array.isArray(data.errors) && data.errors[0]
                        ? `；示例：${data.errors[0].channel_id || '--'} ${data.errors[0].message || ''}`
                        : '';
                    showToast(`已同步 ${success} 个频道名称，失败 ${failed} 个${firstError}`, { tone: 'warn', duration: 4200, placement: 'top-center' });
                } else if (success > 0) {
                    showToast(`已同步 ${success} 个频道名称`, { tone: 'success', duration: 2600, placement: 'top-center' });
                } else {
                    const firstError = Array.isArray(data.errors) && data.errors[0]
                        ? `${data.errors[0].channel_id || '--'} ${data.errors[0].message || '未识别到名称'}`
                        : '未同步到频道名称';
                    showToast(firstError, { tone: 'warn', duration: 3600, placement: 'top-center' });
                }
            } catch (e) {
                showToast(`同步频道名称失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
            } finally {
                resourceSourceNameSyncBusy = false;
                renderResourceSourceManagerModal();
            }
        }

        function getFilteredResourceSourceViewList() {
            const sources = resourceState.sources || [];
            const sectionIndex = getResourceSourceSectionIndex();
            const list = getResourceSourceViewList(sources, sectionIndex);
            const keyword = String(resourceSourceKeyword || '').trim().toLowerCase();
            const filtered = list.filter(view => {
                if (!isResourceSourceVisibleByFilter(view.source, sectionIndex, resourceSourceFilter)) return false;
                if (!isResourceSourceVisibleByEnabled(view.source, resourceSourceEnabledFilter)) return false;
                if (!isResourceSourceVisibleByActivity(view.source, sectionIndex, resourceSourceActivityFilter)) return false;
                if (keyword) {
                    const name = String(view?.source?.name || '').trim().toLowerCase();
                    const id = String(view?.channelId || '').trim().toLowerCase();
                    const typeText = (Array.isArray(view?.sourceTypes) ? view.sourceTypes : []).join(' ').toLowerCase();
                    if (!name.includes(keyword) && !id.includes(keyword) && !typeText.includes(keyword)) return false;
                }
                return true;
            });

            return sortResourceSourceViews(filtered, getResourceSourceSortMode());
        }

        function getSelectedResourceSourceIdsInFiltered() {
            const filteredSet = new Set(
                getFilteredResourceSourceViewList()
                    .map(view => view.channelId)
                    .filter(Boolean)
            );
            return Object.keys(resourceSourceBulkSelected || {}).filter(channelId => {
                return !!resourceSourceBulkSelected[channelId] && filteredSet.has(channelId);
            });
        }

        async function bulkEnableResourceSources(enabled) {
            const selectedIds = getSelectedResourceSourceIdsInFiltered();
            if (!selectedIds.length) {
                showToast('请先在当前筛选结果中勾选要操作的频道', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const selectedSet = new Set(selectedIds);
            const nextSources = (resourceState.sources || []).map(source => {
                const channelId = getResourceSourceChannelId(source);
                if (!selectedSet.has(channelId)) return source;
                return { ...source, enabled: !!enabled };
            });
            try {
                const saveTask = persistResourceSources(nextSources);
                renderResourceSourceManagerModal();
                showToast(`已${enabled ? '启用' : '停用'} ${selectedIds.length} 个频道`, { tone: 'success', duration: 2400, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, enabled ? '启用' : '停用');
            } catch (e) {
                showToast(`操作失败：${e.message}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        async function bulkDeleteResourceSources() {
            const selectedIds = getSelectedResourceSourceIdsInFiltered();
            if (!selectedIds.length) {
                showToast('请先在当前筛选结果中勾选要删除的频道', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const sampleNames = (resourceState.sources || [])
                .filter(source => selectedIds.includes(getResourceSourceChannelId(source)))
                .slice(0, 3)
                .map(source => source?.name || getResourceSourceChannelId(source) || '未命名频道')
                .filter(Boolean);
            const summary = sampleNames.length
                ? `将删除 ${selectedIds.length} 个频道（如：${sampleNames.join('、')}）\n此操作不可恢复，确定继续吗？`
                : `将删除 ${selectedIds.length} 个频道，此操作不可恢复，确定继续吗？`;
            const ok = await showAppConfirm(summary);
            if (!ok) return;
            const selectedSet = new Set(selectedIds);
            const nextSources = (resourceState.sources || []).filter(source => !selectedSet.has(getResourceSourceChannelId(source)));
            try {
                const saveTask = persistResourceSources(nextSources);
                const nextSelected = { ...resourceSourceBulkSelected };
                selectedIds.forEach(channelId => {
                    delete nextSelected[channelId];
                });
                resourceSourceBulkSelected = nextSelected;
                renderResourceSourceManagerModal();
                showToast(`已删除 ${selectedIds.length} 个频道`, { tone: 'success', duration: 2600, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, '删除');
            } catch (e) {
                showToast(`删除失败：${e.message}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        function renderResourceSourceManagerModal() {
            const modal = document.getElementById('resource-source-manager-modal');
            if (!modal || !resourceSourceManagerOpen) return;

            const shell = modal.querySelector('.resource-source-manager-shell');
            const typeFiltersEl = document.getElementById('resource-source-manager-type-filters');
            const statusFiltersEl = document.getElementById('resource-source-manager-status-filters');
            const activityFiltersEl = document.getElementById('resource-source-manager-activity-filters');
            const searchInputEl = document.getElementById('resource-source-manager-search');
            const sortSelectEl = document.getElementById('resource-source-manager-sort');
            const sortHintEl = document.getElementById('resource-source-manager-sort-hint');
            const hintEl = document.getElementById('resource-source-manager-filter-hint');
            const listEl = document.getElementById('resource-source-manager-list');
            const titleEl = document.getElementById('resource-source-manager-title');
            const subtitleEl = document.getElementById('resource-source-manager-subtitle');
            const sortPanelEl = document.getElementById('resource-source-manager-sort-panel');
            const sortSummaryEl = document.getElementById('resource-source-manager-sort-summary');
            const sortDirtyEl = document.getElementById('resource-source-manager-sort-dirty');
            const selectedCountEl = document.getElementById('resource-source-manager-selected-count');
            const mobileFilteredCountEl = document.getElementById('resource-source-manager-mobile-filtered-count');
            const mobileSelectedCountEl = document.getElementById('resource-source-manager-mobile-selected-count');
            const mobileListTabEl = document.getElementById('resource-source-manager-mobile-list-tab');
            const mobileToolsTabEl = document.getElementById('resource-source-manager-mobile-tools-tab');
            const resultEl = document.getElementById('resource-source-manager-test-result');
            const testBtn = document.getElementById('resource-source-manager-test-btn');
            const sampleInput = document.getElementById('resource-source-manager-test-sample-size');
            const selectAllBtn = document.getElementById('resource-source-manager-select-all-btn');
            const invertBtn = document.getElementById('resource-source-manager-invert-btn');
            const syncNamesBtn = document.getElementById('resource-source-manager-sync-names-btn');
            if (!shell || !typeFiltersEl || !statusFiltersEl || !activityFiltersEl || !searchInputEl || !sortSelectEl || !sortHintEl || !hintEl || !listEl || !selectedCountEl || !mobileFilteredCountEl || !mobileSelectedCountEl || !mobileListTabEl || !mobileToolsTabEl || !resultEl || !testBtn || !sampleInput || !selectAllBtn || !invertBtn || !syncNamesBtn) return;

            const sources = resourceState.sources || [];
            const sectionIndex = getResourceSourceSectionIndex();
            const sourceViews = getResourceSourceViewList(sources, sectionIndex);
            const typeOptions = buildResourceSourceFilterOptions(sources, sectionIndex);
            const enabledOptions = buildResourceSourceEnabledFilterOptions(sources);
            const activityOptions = buildResourceSourceActivityFilterOptions(sources, sectionIndex);

            if (!typeOptions.some(option => option.value === normalizeResourceSourceFilterValue(resourceSourceFilter))) {
                resourceSourceFilter = 'all';
            }
            if (!enabledOptions.some(option => option.value === normalizeResourceSourceFilterValue(resourceSourceEnabledFilter))) {
                resourceSourceEnabledFilter = 'all';
            }
            if (!activityOptions.some(option => option.value === normalizeResourceSourceFilterValue(resourceSourceActivityFilter))) {
                resourceSourceActivityFilter = 'all';
            }

            const filtered = getFilteredResourceSourceViewList();
            const sortMode = getResourceSourceSortMode();
            searchInputEl.value = resourceSourceKeyword;
            sortSelectEl.value = sortMode;
            sortHintEl.textContent = sortMode === 'manual'
                ? '当前按真实频道顺序查看。需要调整真实顺序时，请进入排序模式。'
                : `当前按“${getResourceSourceSortModeLabel(sortMode)}”查看；这里只改变列表查看方式，不会改动真实顺序。`;

            typeFiltersEl.innerHTML = typeOptions.map(option => `
                <button
                    type="button"
                    data-resource-source-manager-filter="type"
                    data-filter-value="${escapeHtml(option.value)}"
                    class="resource-source-manager-filter-tab ${normalizeResourceSourceFilterValue(resourceSourceFilter) === option.value ? 'resource-source-manager-filter-tab-active' : ''}"
                >${escapeHtml(option.label)} (${escapeHtml(String(option.count || 0))})</button>
            `).join('');

            statusFiltersEl.innerHTML = enabledOptions.map(option => `
                <button
                    type="button"
                    data-resource-source-manager-filter="status"
                    data-filter-value="${escapeHtml(option.value)}"
                    class="resource-source-manager-filter-tab ${normalizeResourceSourceFilterValue(resourceSourceEnabledFilter) === option.value ? 'resource-source-manager-filter-tab-active' : ''}"
                >${escapeHtml(option.label)} (${escapeHtml(String(option.count || 0))})</button>
            `).join('');

            activityFiltersEl.innerHTML = activityOptions.map(option => `
                <button
                    type="button"
                    data-resource-source-manager-filter="activity"
                    data-filter-value="${escapeHtml(option.value)}"
                    class="resource-source-manager-filter-tab ${normalizeResourceSourceFilterValue(resourceSourceActivityFilter) === option.value ? 'resource-source-manager-filter-tab-active' : ''}"
                >${escapeHtml(option.label)} (${escapeHtml(String(option.count || 0))})</button>
            `).join('');

            const selectedCount = Object.keys(resourceSourceBulkSelected || {}).filter(channelId => resourceSourceBulkSelected[channelId]).length;
            const selectedInFiltered = filtered.filter(view => !!resourceSourceBulkSelected[view.channelId]).length;
            const compactLayout = isCompactResourceSourceManager();
            const activeMobilePanel = compactLayout ? normalizeResourceSourceManagerMobilePanel(resourceSourceManagerMobilePanel) : 'list';
            shell.classList.toggle('resource-source-manager-shell-mobile', compactLayout);
            shell.classList.toggle('resource-source-manager-shell-mobile-list', compactLayout && activeMobilePanel === 'list');
            shell.classList.toggle('resource-source-manager-shell-mobile-tools', compactLayout && activeMobilePanel === 'tools');
            shell.classList.toggle('resource-source-manager-shell-sorting', !!resourceSourceSortSessionActive);
            if (titleEl) titleEl.textContent = resourceSourceSortSessionActive ? '频道排序' : '频道管理中心';
            if (subtitleEl) {
                subtitleEl.textContent = resourceSourceSortSessionActive
                    ? '排序模式只保留顺序调整；保存前不会改动真实频道顺序。'
                    : '管理频道筛选、分类测试、批量操作和频道顺序；导入导出已移到设置页的频道数据区。';
            }
            if (sortPanelEl) sortPanelEl.classList.toggle('hidden', !resourceSourceSortSessionActive);

            selectedCountEl.textContent = String(selectedInFiltered);
            mobileFilteredCountEl.textContent = String(filtered.length);
            mobileSelectedCountEl.textContent = String(selectedCount);
            mobileListTabEl.classList.toggle('resource-source-manager-mobile-tab-active', activeMobilePanel === 'list');
            mobileListTabEl.setAttribute('aria-pressed', activeMobilePanel === 'list' ? 'true' : 'false');
            mobileToolsTabEl.classList.toggle('resource-source-manager-mobile-tab-active', activeMobilePanel === 'tools');
            mobileToolsTabEl.setAttribute('aria-pressed', activeMobilePanel === 'tools' ? 'true' : 'false');
            hintEl.textContent = selectedCount > selectedInFiltered
                ? `当前筛选结果 ${filtered.length} 个频道，已选中 ${selectedInFiltered} 个（全局已选 ${selectedCount} 个）。`
                : `当前筛选结果 ${filtered.length} 个频道，已选中 ${selectedInFiltered} 个。`;

            const hasFiltered = filtered.length > 0;
            const isAllSelected = hasFiltered && selectedInFiltered === filtered.length;
            selectAllBtn.disabled = !hasFiltered || isAllSelected;
            selectAllBtn.classList.toggle('btn-disabled', !hasFiltered || isAllSelected);
            selectAllBtn.classList.toggle('resource-source-manager-select-btn-active', isAllSelected);
            selectAllBtn.textContent = isAllSelected ? '当前筛选结果已全选' : '全选当前筛选结果';
            invertBtn.disabled = !hasFiltered;
            invertBtn.classList.toggle('btn-disabled', !hasFiltered);
            syncNamesBtn.disabled = selectedInFiltered <= 0 || resourceSourceNameSyncBusy;
            syncNamesBtn.classList.toggle('btn-disabled', selectedInFiltered <= 0 || resourceSourceNameSyncBusy);
            syncNamesBtn.textContent = resourceSourceNameSyncBusy ? '同步中...' : '同步频道名称';

            if (resourceSourceTestBusy) {
                const total = Number(resourceSourceTestResult.total || sources.length || 0);
                const done = Number(resourceSourceTestResult.done || 0);
                const success = Number(resourceSourceTestResult.success || 0);
                const failed = Number(resourceSourceTestResult.failed || 0);
                const threads = Math.max(1, Number(resourceSourceTestResult.threads || 1));
                const sampleSize = Math.max(1, Number(resourceSourceTestResult.sample_size || sampleInput.value || 20));
                const lastName = String(resourceSourceTestResult.last_name || '').trim();
                resultEl.textContent = `测试中：${done}/${total}，成功 ${success}，失败 ${failed}，线程 ${threads}，每频道资源数 ${sampleSize}${lastName ? `，当前 ${lastName}` : ''}`;
            } else if (Number(resourceSourceTestResult.total || 0) > 0) {
                const threads = Math.max(1, Number(resourceSourceTestResult.threads || 1));
                const sampleSize = Math.max(1, Number(resourceSourceTestResult.sample_size || sampleInput.value || 20));
                const base = `测试完成：共 ${resourceSourceTestResult.total} 个频道，成功 ${resourceSourceTestResult.success || 0}，失败 ${resourceSourceTestResult.failed || 0}，线程 ${threads}，每频道资源数 ${sampleSize}。`;
                const firstError = String(resourceSourceTestResult.error || '').trim();
                resultEl.textContent = firstError ? `${base} 失败示例：${firstError}` : base;
            } else if (resourceSourceTestResult.error) {
                resultEl.textContent = `测试失败：${resourceSourceTestResult.error}`;
            } else {
                const defaultThreads = getCurrentTgChannelThreads();
                const sampleSize = Math.max(1, Number(sampleInput.value || 20));
                resultEl.textContent = `点击后会按当前配置并发测试频道分类（线程 ${defaultThreads}，每频道资源数 ${sampleSize}）。`;
            }
            testBtn.disabled = resourceSourceTestBusy || sources.length <= 0;
            sampleInput.disabled = resourceSourceTestBusy;

            if (resourceSourceSortSessionActive) {
                const draftViews = getResourceSourceSortDraftViews();
                const changed = isResourceSourceSortDraftChanged();
                mobileFilteredCountEl.textContent = String(draftViews.length);
                mobileSelectedCountEl.textContent = changed ? '已调整' : '0';
                if (sortSummaryEl) sortSummaryEl.textContent = `共 ${draftViews.length} 个频道。按住拖拽手柄调整顺序，手机端也可以直接使用上移/下移。`;
                if (sortDirtyEl) {
                    sortDirtyEl.textContent = changed ? '待保存' : '未调整';
                    sortDirtyEl.classList.toggle('resource-source-manager-sort-dirty-active', changed);
                }
                if (!draftViews.length) {
                    listEl.innerHTML = '<div class="resource-source-empty"><div class="resource-source-empty-title">当前没有频道</div><div class="resource-source-empty-copy">请先添加频道后再排序。</div></div>';
                    return;
                }
                listEl.innerHTML = draftViews.map((view, position) => {
                    const enabled = view.source.enabled !== false;
                    const latestAge = view.latestPublishedMs ? formatResourceAgeText(view.latestPublishedMs) : '待同步';
                    const typeText = (Array.isArray(view.sourceTypes) ? view.sourceTypes : [])
                        .slice(0, 3)
                        .map(type => getResourceLinkTypeLabel(type))
                        .join(' / ');
                    const typeBadges = renderResourceSourceTypeBadges(view.profile, view.sourceTypes);
                    const upDisabled = position <= 0 ? 'btn-disabled' : '';
                    const downDisabled = position >= draftViews.length - 1 ? 'btn-disabled' : '';
                    return `
                        <div
                            class="resource-source-manager-row resource-source-manager-sort-row ${resourceSourceSortDragIndex === view.index ? 'resource-source-manager-sort-row-dragging' : ''}"
                            data-resource-source-sort-index="${escapeHtml(String(view.index))}"
                        >
                            <button
                                type="button"
                                class="resource-source-manager-drag-handle"
                                data-resource-source-sort-handle="1"
                                aria-label="拖拽调整 ${escapeHtml(view.source.name || view.channelId || '频道')} 的顺序"
                            >☰</button>
                            <div class="resource-source-manager-sort-rank">#${escapeHtml(String(position + 1))}</div>
                            <div class="resource-source-manager-row-main">
                                <div class="resource-source-manager-row-title">
                                    <span>${escapeHtml(view.source.name || view.channelId || '未命名频道')}</span>
                                    <span class="resource-source-manager-channel-link">@${escapeHtml(view.channelId || '--')}</span>
                                    ${typeBadges}
                                    <span class="text-[10px] px-2 py-0.5 rounded-full ${enabled ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20' : 'bg-slate-700 text-slate-300 border border-slate-600'}">${enabled ? '已启用' : '已停用'}</span>
                                </div>
                                <div class="resource-source-manager-row-meta">类型：${escapeHtml(typeText || getResourceLinkTypeLabel(view.primaryType || 'unknown'))} · 最近：${escapeHtml(latestAge)}</div>
                            </div>
                            <div class="resource-source-manager-row-actions">
                                <button type="button" data-resource-source-manager-action="sort-up" data-source-index="${view.index}" class="resource-source-compact-btn ${upDisabled}" ${position <= 0 ? 'disabled' : ''}>上移</button>
                                <button type="button" data-resource-source-manager-action="sort-down" data-source-index="${view.index}" class="resource-source-compact-btn ${downDisabled}" ${position >= draftViews.length - 1 ? 'disabled' : ''}>下移</button>
                            </div>
                        </div>
                    `;
                }).join('');
                return;
            }

            if (!filtered.length) {
                listEl.innerHTML = '<div class="resource-source-empty"><div class="resource-source-empty-title">当前筛选无结果</div><div class="resource-source-empty-copy">可以切换资源类型、启用状态或活跃时间范围。</div></div>';
                return;
            }

            listEl.innerHTML = filtered.map(view => {
                const checked = !!resourceSourceBulkSelected[view.channelId];
                const enabled = view.source.enabled !== false;
                const latest = String(view.latestPublishedAt || '').trim();
                const latestAge = view.latestPublishedMs ? formatResourceAgeText(view.latestPublishedMs) : '待同步';
                const typeText = (Array.isArray(view.sourceTypes) ? view.sourceTypes : [])
                    .slice(0, 3)
                    .map(type => getResourceLinkTypeLabel(type))
                    .join(' / ');
                const supportSearched = Math.max(0, Number(view?.support?.searched_runs || 0));
                const supportMatched = Math.max(0, Number(view?.support?.matched_runs || 0));
                const supportItems = Math.max(0, Number(view?.support?.matched_items || 0));
                const supportErrors = Math.max(0, Number(view?.support?.error_runs || 0));
                const supportHitRate = supportSearched > 0 ? Math.round((supportMatched / supportSearched) * 100) : 0;
                const supportText = supportSearched > 0
                    ? `订阅支持：${supportMatched}/${supportSearched}（命中率 ${supportHitRate}%） · 产出 ${supportItems} 条 · 异常 ${supportErrors} 次`
                    : '订阅支持：暂无订阅任务统计';
                const typeBadges = renderResourceSourceTypeBadges(view.profile, view.sourceTypes);
                const channelLink = String(view.channelUrl || (view.channelId ? `https://t.me/s/${view.channelId}` : '')).trim();
                return `
                    <div class="resource-source-manager-row">
                        <label class="ui-checkbox">
                            <input type="checkbox" data-resource-source-bulk-toggle="${escapeHtml(view.channelId)}" ${checked ? 'checked' : ''}>
                            <span></span>
                        </label>
                        <div class="resource-source-manager-row-main">
                            <div class="resource-source-manager-row-title">
                                <span>${escapeHtml(view.source.name || view.channelId || '未命名频道')}</span>
                                ${channelLink ? `<a href="${escapeHtml(channelLink)}" target="_blank" rel="noopener noreferrer" class="resource-source-manager-channel-link">@${escapeHtml(view.channelId || '--')}</a>` : `<span class="resource-source-manager-channel-link">@${escapeHtml(view.channelId || '--')}</span>`}
                                ${typeBadges}
                                <span class="text-[10px] px-2 py-0.5 rounded-full ${enabled ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20' : 'bg-slate-700 text-slate-300 border border-slate-600'}">${enabled ? '已启用' : '已停用'}</span>
                            </div>
                            <div class="resource-source-manager-row-meta">类型：${escapeHtml(typeText || getResourceLinkTypeLabel(view.primaryType || 'unknown'))} · 活跃度：${escapeHtml(getResourceSourceActivityBucketLabel(view.activityBucket))} · 最近：${escapeHtml(latestAge)}${latest ? `（${escapeHtml(formatTimeText(latest))}）` : ''} · ${escapeHtml(supportText)}</div>
                        </div>
                        <div class="resource-source-manager-row-actions">
                            <button type="button" data-resource-source-manager-action="toggle" data-source-index="${view.index}" data-enabled="${enabled ? '1' : '0'}" class="resource-source-compact-btn">${enabled ? '停用' : '启用'}</button>
                            <button type="button" data-resource-source-manager-action="edit" data-source-index="${view.index}" class="resource-source-compact-btn">编辑</button>
                            <button type="button" data-resource-source-manager-action="delete" data-source-index="${view.index}" class="resource-source-compact-btn resource-source-compact-btn-danger">删除</button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function testResourceSourceClassification() {
            const sources = resourceState.sources || [];
            const sourceEntries = sources
                .map(source => {
                    const channelId = getResourceSourceChannelId(source);
                    return {
                        channel_id: channelId,
                        name: String(source?.name || channelId).trim() || channelId,
                    };
                })
                .filter(item => item.channel_id);
            if (!sourceEntries.length) {
                showToast('当前没有可测试的频道', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }

            const sampleInput = document.getElementById('resource-source-manager-test-sample-size');
            const sampleSize = Math.max(1, Math.min(100, parseInt(sampleInput?.value || '20', 10) || 20));
            if (sampleInput) sampleInput.value = String(sampleSize);
            const threadLimit = Math.min(getCurrentTgChannelThreads(), sourceEntries.length);
            resourceSourceTestBusy = true;
            resourceSourceTestResult = {
                total: sourceEntries.length,
                done: 0,
                success: 0,
                failed: 0,
                running: true,
                last_name: '',
                error: '',
                threads: threadLimit,
                sample_size: sampleSize,
            };
            renderResourceSourceManagerModal();
            const nextProfiles = { ...(resourceState.channel_profiles || {}) };
            try {
                let cursor = 0;
                const worker = async () => {
                    while (true) {
                        const currentIndex = cursor;
                        cursor += 1;
                        if (currentIndex >= sourceEntries.length) break;
                        const item = sourceEntries[currentIndex];
                        resourceSourceTestResult = {
                            ...resourceSourceTestResult,
                            last_name: item.name || item.channel_id,
                        };
                        renderResourceSourceManagerModal();
                        try {
                            const data = await window.MediaHubApi.postJson('/resource/channels/classify', {
                                channel_id: item.channel_id,
                                sample_size: sampleSize,
                            });
                            const profile = data.profile && typeof data.profile === 'object' ? data.profile : {};
                            nextProfiles[item.channel_id] = profile;
                            resourceSourceTestResult = {
                                ...resourceSourceTestResult,
                                done: Number(resourceSourceTestResult.done || 0) + 1,
                                success: Number(resourceSourceTestResult.success || 0) + 1,
                            };
                        } catch (e) {
                            resourceSourceTestResult = {
                                ...resourceSourceTestResult,
                                done: Number(resourceSourceTestResult.done || 0) + 1,
                                failed: Number(resourceSourceTestResult.failed || 0) + 1,
                                error: String(resourceSourceTestResult.error || '').trim() || (e.message || '分类测试失败'),
                            };
                        }
                        renderResourceSourceManagerModal();
                    }
                };

                await Promise.all(Array.from({ length: threadLimit }, () => worker()));

                resourceState = {
                    ...resourceState,
                    channel_profiles: nextProfiles,
                };
                renderResourceSources();
                resourceSourceTestResult = {
                    ...resourceSourceTestResult,
                    running: false,
                };
            } finally {
                resourceSourceTestBusy = false;
                renderResourceSourceManagerModal();
            }
        }

        function syncResourceSourceSummary() {
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            const enabledCount = sources.filter(source => source.enabled !== false).length;
            const disabledCount = Math.max(0, sources.length - enabledCount);
            const sectionIndex = getResourceSourceSectionIndex();
            const outputCount = getResourceSourceViewList(sources, sectionIndex)
                .filter(view => getResourceSourceOutputCount(view) > 0)
                .length;
            const totalEl = document.getElementById('resource-source-total-count');
            const enabledEl = document.getElementById('resource-source-enabled-count');
            const disabledEl = document.getElementById('resource-source-disabled-count');
            const outputEl = document.getElementById('resource-source-output-count');
            if (totalEl) totalEl.innerText = String(sources.length);
            if (enabledEl) enabledEl.innerText = String(enabledCount);
            if (disabledEl) disabledEl.innerText = String(disabledCount);
            if (outputEl) outputEl.innerText = String(outputCount);
        }

        function syncResourceSourceModalState() {
            const editing = editingResourceSourceIndex !== null && editingResourceSourceIndex >= 0;
            const titleEl = document.getElementById('resource-source-modal-title');
            const subtitleEl = document.getElementById('resource-source-modal-subtitle');
            const saveBtn = document.getElementById('resource-source-modal-save-btn');
            if (titleEl) titleEl.innerText = editing ? '编辑频道订阅' : '新增频道订阅';
            if (subtitleEl) {
                subtitleEl.innerText = editing
                    ? '修改名称、频道 ID 或启用状态后会立即保存，并同步更新资源中心里的订阅展示。'
                    : '只需要填写公开频道 ID，保存后会立刻出现在资源中心的订阅列表里。';
            }
            if (saveBtn) saveBtn.innerText = editing ? '保存修改' : '保存频道订阅';
        }

        function resetResourceSourceForm() {
            editingResourceSourceIndex = null;
            document.getElementById('resource_source_name').value = '';
            document.getElementById('resource_source_channel').value = '';
            document.getElementById('resource_source_enabled').checked = true;
            syncResourceSourceModalState();
        }

        function openResourceSourceModal(index = null) {
            if (resourceSourceManagerOpen) closeResourceSourceManagerModal();
            const sources = resourceState.sources || [];
            if (Number.isInteger(index) && index >= 0 && sources[index]) {
                const source = sources[index];
                editingResourceSourceIndex = index;
                document.getElementById('resource_source_name').value = source.name || '';
                document.getElementById('resource_source_channel').value = getResourceSourceChannelId(source);
                document.getElementById('resource_source_enabled').checked = source.enabled !== false;
            } else {
                resetResourceSourceForm();
            }
            syncResourceSourceModalState();
            switchTab('settings');
            resourceSourceModalOpen = true;
            document.getElementById('resource-source-modal').classList.remove('hidden');
            requestAnimationFrame(() => {
                const targetId = editingResourceSourceIndex !== null ? 'resource_source_name' : 'resource_source_channel';
                const target = document.getElementById(targetId);
                if (!target) return;
                target.focus();
                target.select?.();
            });
        }

        function closeResourceSourceModal() {
            resourceSourceModalOpen = false;
            document.getElementById('resource-source-modal').classList.add('hidden');
            resetResourceSourceForm();
        }

        function syncResourceChannelManageModalState() {
            const titleEl = document.getElementById('resource-channel-manage-title');
            const orderEl = document.getElementById('resource-channel-manage-order');
            const pinBtn = document.getElementById('resource-channel-manage-pin-btn');
            const enabledEl = document.getElementById('resource-channel-manage-enabled');
            const nameEl = document.getElementById('resource-channel-manage-name');
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            const index = resourceChannelManageSourceIndex;
            const source = index >= 0 ? sources[index] : null;
            if (!source) {
                if (titleEl) titleEl.innerText = '频道快捷管理';
                if (orderEl) orderEl.innerText = '--';
                if (pinBtn) {
                    pinBtn.disabled = true;
                    pinBtn.classList.add('btn-disabled');
                    pinBtn.innerText = '置顶（排序挪到1号）';
                }
                if (enabledEl) enabledEl.checked = false;
                if (nameEl) nameEl.value = '';
                return;
            }
            const displayName = String(source?.name || getResourceSourceChannelId(source) || '未命名频道').trim() || '未命名频道';
            const keepLocalForm = resourceChannelManageModalOpen && resourceChannelManageDirty;
            if (titleEl) titleEl.innerText = `频道快捷管理 · ${displayName}`;
            if (orderEl) orderEl.innerText = `#${index + 1}`;
            if (pinBtn) {
                const alreadyTop = index <= 0;
                pinBtn.disabled = alreadyTop;
                pinBtn.classList.toggle('btn-disabled', alreadyTop);
                pinBtn.innerText = alreadyTop ? '已在1号位' : '置顶（排序挪到1号）';
            }
            if (enabledEl && !keepLocalForm) enabledEl.checked = source?.enabled !== false;
            if (nameEl && (!keepLocalForm || !nameEl.value.trim())) {
                nameEl.value = displayName;
            }
        }

        function resetResourceChannelManageForm() {
            resourceChannelManageSourceIndex = -1;
            resourceChannelManageChannelId = '';
            resourceChannelManageDirty = false;
            const nameEl = document.getElementById('resource-channel-manage-name');
            const enabledEl = document.getElementById('resource-channel-manage-enabled');
            if (nameEl) nameEl.value = '';
            if (enabledEl) enabledEl.checked = true;
            syncResourceChannelManageModalState();
        }

        function openResourceChannelManageModal(channelId) {
            const normalized = normalizeTelegramChannelIdInput(channelId || '');
            const index = getResourceSourceIndexByChannelId(normalized);
            if (!normalized || index < 0) {
                showToast('未找到对应频道，可能已被删除或停用', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const source = (resourceState.sources || [])[index] || {};
            resourceChannelManageSourceIndex = index;
            resourceChannelManageChannelId = normalized;
            resourceChannelManageDirty = false;
            const nameEl = document.getElementById('resource-channel-manage-name');
            const enabledEl = document.getElementById('resource-channel-manage-enabled');
            if (nameEl) nameEl.value = String(source?.name || normalized).trim() || normalized;
            if (enabledEl) enabledEl.checked = source?.enabled !== false;
            syncResourceChannelManageModalState();
            resourceChannelManageModalOpen = true;
            showLockedModal('resource-channel-manage-modal');
            requestAnimationFrame(() => {
                const input = document.getElementById('resource-channel-manage-name');
                if (!input) return;
                input.focus();
                input.select?.();
            });
        }

        function closeResourceChannelManageModal() {
            resourceChannelManageModalOpen = false;
            hideLockedModal('resource-channel-manage-modal');
            resetResourceChannelManageForm();
        }

        async function saveResourceChannelManage() {
            const index = resourceChannelManageSourceIndex;
            const channelId = resourceChannelManageChannelId;
            const sources = [...(resourceState.sources || [])];
            if (index < 0 || index >= sources.length) {
                showToast('频道不存在，无法保存', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            const nameEl = document.getElementById('resource-channel-manage-name');
            const enabledEl = document.getElementById('resource-channel-manage-enabled');
            const nextName = String(nameEl?.value || '').trim() || channelId;
            sources[index] = {
                ...sources[index],
                name: nextName,
                enabled: !!enabledEl?.checked,
            };
            try {
                const saveTask = persistResourceSources(sources);
                resourceChannelManageDirty = false;
                resourceChannelManageSourceIndex = getResourceSourceIndexByChannelId(channelId);
                syncResourceChannelManageModalState();
                showToast('频道设置已更新', { tone: 'success', duration: 2200, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, '保存');
            } catch (e) {
                showToast(`保存失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
            }
        }

        async function deleteResourceChannelManage() {
            const index = resourceChannelManageSourceIndex;
            const sources = [...(resourceState.sources || [])];
            if (index < 0 || index >= sources.length) {
                showToast('频道不存在，无法删除', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            const source = sources[index] || {};
            const channelId = getResourceSourceChannelId(source) || resourceChannelManageChannelId;
            const displayName = String(source?.name || channelId || '未命名频道').trim() || '未命名频道';
            const ok = await showAppConfirm(`确定删除频道“${displayName}”吗？\n删除后会从资源中心频道列表移除，此操作不可恢复。`);
            if (!ok) return;
            sources.splice(index, 1);
            try {
                const saveTask = persistResourceSources(sources);
                closeResourceChannelManageModal();
                showToast(`已删除频道：${displayName}`, { tone: 'success', duration: 2400, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, '删除');
            } catch (e) {
                showToast(`删除失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
            }
        }

        async function pinResourceChannelToTop() {
            const index = resourceChannelManageSourceIndex;
            const channelId = resourceChannelManageChannelId;
            const sources = [...(resourceState.sources || [])];
            if (index <= 0 || index >= sources.length) return;
            const source = sources[index];
            sources.splice(index, 1);
            sources.unshift(source);
            try {
                const saveTask = persistResourceSources(sources);
                resourceChannelManageSourceIndex = getResourceSourceIndexByChannelId(channelId);
                syncResourceChannelManageModalState();
                showToast('已置顶到1号位', { tone: 'success', duration: 2200, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, '置顶');
            } catch (e) {
                showToast(`置顶失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
            }
        }

        function buildResourceSourceExportItems(sources = []) {
            return (Array.isArray(sources) ? sources : [])
                .map((source, index) => {
                    const channelId = getResourceSourceChannelId(source);
                    if (!channelId) return null;
                    const fallbackName = `频道 ${index + 1}`;
                    return {
                        name: String(source?.name || channelId || fallbackName).trim() || fallbackName,
                        id: channelId,
                    };
                })
                .filter(Boolean);
        }

        function buildResourceSourceExportText(sources = []) {
            const items = buildResourceSourceExportItems(sources);
            return {
                label: 'CloudSaver JSON',
                count: items.length,
                text: JSON.stringify(items, null, 2),
            };
        }

        function getResourceSourceExportTextFromModal() {
            const input = document.getElementById('resource_source_export_json');
            return String(input?.value || '').trim();
        }

        function downloadResourceSourceExportFile(text) {
            const payload = String(text || '').trim();
            if (!payload) return false;
            try {
                const blob = new Blob([`${payload}\n`], { type: 'application/json;charset=utf-8' });
                const stamp = new Date().toISOString().replace(/[:]/g, '-').replace(/\..+$/, '');
                const link = document.createElement('a');
                const href = URL.createObjectURL(blob);
                link.href = href;
                link.download = `tg-resource-sources-${stamp}.json`;
                document.body.appendChild(link);
                link.click();
                link.remove();
                window.setTimeout(() => URL.revokeObjectURL(href), 1200);
                return true;
            } catch (e) {
                return false;
            }
        }

        function openResourceSourceExportModal() {
            if (resourceSourceManagerOpen) closeResourceSourceManagerModal();
            if (resourceSourceImportModalOpen) closeResourceSourceImportModal();
            if (resourceSourceModalOpen) closeResourceSourceModal();
            switchTab('settings');
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            const exportData = buildResourceSourceExportText(sources);
            if (!exportData.count) {
                showToast('当前没有可导出的频道源', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const subtitle = document.getElementById('resource-source-export-subtitle');
            if (subtitle) subtitle.innerText = `当前将导出 ${exportData.count} 个频道，格式为 CloudSaver JSON。需要文件时请点击“下载 JSON”。`;
            const input = document.getElementById('resource_source_export_json');
            if (input) input.value = exportData.text;
            showLockedModal('resource-source-export-modal');
            requestAnimationFrame(() => {
                const exportInput = document.getElementById('resource_source_export_json');
                exportInput?.focus();
                exportInput?.select?.();
            });
        }

        function closeResourceSourceExportModal() {
            hideLockedModal('resource-source-export-modal');
        }

        async function copyResourceSourceExportJson() {
            const text = getResourceSourceExportTextFromModal();
            if (!text) {
                showToast('没有可复制的频道 JSON', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            try {
                if (!navigator.clipboard?.writeText) throw new Error('当前浏览器不支持剪贴板接口');
                await navigator.clipboard.writeText(text);
                showToast('已复制频道 JSON', { tone: 'success', duration: 2200, placement: 'top-center' });
            } catch (e) {
                void showAppPrompt('复制失败，请手动复制下面的频道 JSON：', text);
            }
        }

        function downloadResourceSourceExportJson() {
            const text = getResourceSourceExportTextFromModal();
            if (!text) {
                showToast('没有可下载的频道 JSON', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            if (downloadResourceSourceExportFile(text)) {
                showToast('已生成频道 JSON 下载文件', { tone: 'success', duration: 2600, placement: 'top-center' });
            } else {
                showToast('下载 JSON 失败，请复制文本后手动保存', { tone: 'error', duration: 3000, placement: 'top-center' });
            }
        }

        function exportResourceSources() {
            openResourceSourceExportModal();
        }

        function resetResourceSourceImportForm() {
            const input = document.getElementById('resource_source_import_json');
            const replaceEl = document.getElementById('resource_source_import_replace');
            if (input) input.value = '';
            if (replaceEl) replaceEl.checked = true;
            setResourceSourceImportBusy(false);
        }

        function openResourceSourceImportModal() {
            if (resourceSourceManagerOpen) closeResourceSourceManagerModal();
            if (resourceSourceModalOpen) closeResourceSourceModal();
            switchTab('settings');
            resourceSourceImportModalOpen = true;
            showLockedModal('resource-source-import-modal');
            requestAnimationFrame(() => {
                const input = document.getElementById('resource_source_import_json');
                if (!input) return;
                input.focus();
                input.select?.();
            });
        }

        function closeResourceSourceImportModal() {
            resourceSourceImportModalOpen = false;
            hideLockedModal('resource-source-import-modal');
            resetResourceSourceImportForm();
        }

        function normalizeImportedResourceSourceItem(raw, index = 0) {
            const displayIndex = index + 1;
            if (typeof raw === 'string') {
                const channelId = normalizeTelegramChannelIdInput(raw);
                if (!channelId) return { source: null, reason: `第 ${displayIndex} 项缺少频道 ID` };
                if (!isLikelyTelegramChannelId(channelId)) return { source: null, reason: `第 ${displayIndex} 项频道 ID 格式不正确：${channelId}` };
                return {
                    source: {
                        name: channelId,
                        channel_id: channelId,
                        enabled: true,
                    },
                    reason: '',
                };
            }
            if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
                return { source: null, reason: `第 ${displayIndex} 项不是对象` };
            }

            const channelRaw = raw.channel_id || raw.channel || raw.id || raw.url || '';
            const channelId = normalizeTelegramChannelIdInput(channelRaw);
            if (!channelId) return { source: null, reason: `第 ${displayIndex} 项缺少频道 ID（支持 id / channel_id / channel / url）` };
            if (!isLikelyTelegramChannelId(channelId)) return { source: null, reason: `第 ${displayIndex} 项频道 ID 格式不正确：${channelId}` };

            const normalized = {
                name: String(raw.name || raw.title || channelId).trim() || channelId,
                channel_id: channelId,
                enabled: typeof raw.enabled === 'boolean' ? raw.enabled : true,
            };
            return { source: normalized, reason: '' };
        }

        function parsePanSearchResourceSourceImportText(text) {
            const matched = String(text || '').match(/(?:^|\n)\s*(?:export\s+)?CHANNELS\s*=\s*([^\n\r]+)/i);
            if (!matched) return null;
            let value = String(matched[1] || '').trim();
            value = value.replace(/^['"]|['"]$/g, '').trim();
            const items = value
                .split(',')
                .map(item => item.trim())
                .filter(Boolean);
            if (!items.length) throw new Error('盘搜 CHANNELS 格式中没有频道 ID');
            return items;
        }

        function parseCloudSaverResourceSourceImportText(text) {
            const payload = JSON.parse(text);
            if (!Array.isArray(payload)) throw new Error('导入内容必须是 JSON 数组');
            return payload;
        }

        function parseResourceSourceImportText(rawText) {
            const text = String(rawText || '').trim();
            if (!text) throw new Error('请先粘贴频道源配置');
            let payload = null;
            let detectedFormat = '';
            let jsonError = null;
            try {
                payload = parseCloudSaverResourceSourceImportText(text);
                detectedFormat = 'CloudSaver JSON';
            } catch (e) {
                jsonError = e;
            }
            if (!payload) {
                try {
                    payload = parsePanSearchResourceSourceImportText(text);
                    if (!payload) throw new Error('未找到 CHANNELS=...');
                    detectedFormat = '盘搜 CHANNELS';
                } catch (e) {
                    throw new Error(`无法识别频道格式：${e.message || jsonError?.message || '请粘贴 JSON 数组或 export CHANNELS=...'}`);
                }
            }
            if (!Array.isArray(payload)) throw new Error('导入内容必须是频道数组');

            const parsed = [];
            const seen = new Set();
            const invalidReasons = [];
            let duplicateCount = 0;

            payload.forEach((item, index) => {
                const normalized = normalizeImportedResourceSourceItem(item, index);
                if (!normalized.source) {
                    invalidReasons.push(normalized.reason || `第 ${index + 1} 项无效`);
                    return;
                }
                const channelId = getResourceSourceChannelId(normalized.source);
                if (!channelId) {
                    invalidReasons.push(`第 ${index + 1} 项无法提取频道 ID`);
                    return;
                }
                if (seen.has(channelId)) {
                    duplicateCount += 1;
                    return;
                }
                seen.add(channelId);
                parsed.push(normalized.source);
            });

            return {
                total: payload.length,
                sources: parsed,
                duplicateCount,
                invalidReasons,
                detectedFormat,
            };
        }

        function mergeResourceSourcesByChannel(existingSources, importedSources) {
            const merged = [...(Array.isArray(existingSources) ? existingSources : [])];
            const channelIndexMap = new Map();
            merged.forEach((source, index) => {
                const channelId = getResourceSourceChannelId(source);
                if (!channelId || channelIndexMap.has(channelId)) return;
                channelIndexMap.set(channelId, index);
            });

            (Array.isArray(importedSources) ? importedSources : []).forEach(source => {
                const channelId = getResourceSourceChannelId(source);
                if (!channelId) return;
                if (channelIndexMap.has(channelId)) {
                    const hitIndex = channelIndexMap.get(channelId);
                    merged[hitIndex] = {
                        ...merged[hitIndex],
                        ...source,
                        channel_id: channelId,
                    };
                    return;
                }
                channelIndexMap.set(channelId, merged.length);
                merged.push(source);
            });
            return merged;
        }

        function setResourceSourceImportBusy(loading = false) {
            const btn = document.getElementById('resource-source-import-submit-btn');
            const input = document.getElementById('resource_source_import_json');
            const replaceEl = document.getElementById('resource_source_import_replace');
            const busy = !!loading;
            if (btn) {
                btn.disabled = busy;
                btn.classList.toggle('btn-disabled', busy);
                btn.innerText = busy ? '导入中...' : '开始导入';
            }
            if (input) input.disabled = busy;
            if (replaceEl) replaceEl.disabled = busy;
        }

        async function importResourceSources() {
            const input = document.getElementById('resource_source_import_json');
            const replaceEl = document.getElementById('resource_source_import_replace');
            if (!input) return;

            let parsed = null;
            try {
                parsed = parseResourceSourceImportText(input.value);
            } catch (e) {
                void showAppAlert(e.message || '导入内容解析失败', { title: '导入失败', tone: 'error' });
                return;
            }

            if (!parsed.sources.length) {
                const firstReasons = parsed.invalidReasons.slice(0, 5).join('\n');
                const reasonHint = firstReasons ? `\n\n示例问题：\n${firstReasons}` : '';
                void showAppAlert(`没有识别到可导入的频道 ID${reasonHint}`, { title: '导入失败', tone: 'error' });
                return;
            }

            const currentSources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            const replaceExisting = !!replaceEl?.checked;
            if (replaceExisting && currentSources.length) {
                const ok = await showAppConfirm(`将覆盖当前 ${currentSources.length} 个频道源，继续导入吗？`);
                if (!ok) return;
            }

            const nextSources = replaceExisting
                ? parsed.sources
                : mergeResourceSourcesByChannel(currentSources, parsed.sources);

            setResourceSourceImportBusy(true);
            try {
                const saveTask = persistResourceSources(nextSources, { immediate: true });
                closeResourceSourceImportModal();
                const notes = [
                    `已导入 ${parsed.sources.length} 个频道`,
                    `识别格式：${parsed.detectedFormat || '自动'}`,
                ];
                if (replaceExisting) notes.push('已覆盖旧配置');
                else notes.push(`当前频道总数 ${nextSources.length}`);
                if (parsed.duplicateCount > 0) notes.push(`导入数据内重复 ${parsed.duplicateCount} 项已自动去重`);
                if (parsed.invalidReasons.length > 0) notes.push(`无效数据 ${parsed.invalidReasons.length} 项已跳过`);
                showToast(notes.join('，'), { tone: 'success', duration: 3200, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, '导入');
            } catch (e) {
                showToast(`导入失败：${e.message}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            } finally {
                setResourceSourceImportBusy(false);
            }
        }

        const RESOURCE_SOURCE_SAVE_DEBOUNCE_MS = 120;

        function settleResourceSourcePersistPromises(token, error, payload) {
            const ready = [];
            const pending = [];
            (resourceSourcePersistPending || []).forEach(entry => {
                if (Number(entry?.token || 0) <= token) ready.push(entry);
                else pending.push(entry);
            });
            resourceSourcePersistPending = pending;
            ready.forEach(entry => {
                if (error) entry.reject(error);
                else entry.resolve(payload);
            });
        }

        function scheduleResourceSourcePersistFlush(delayMs = RESOURCE_SOURCE_SAVE_DEBOUNCE_MS) {
            if (resourceSourcePersistTimer) {
                window.clearTimeout(resourceSourcePersistTimer);
                resourceSourcePersistTimer = null;
            }
            resourceSourcePersistTimer = window.setTimeout(() => {
                resourceSourcePersistTimer = null;
                void flushResourceSourcePersistQueue();
            }, Math.max(0, delayMs));
        }

        async function flushResourceSourcePersistQueue() {
            if (resourceSourcePersistInFlight || !resourceSourcePersistQueuedSources) return;
            const sourcesToSave = cloneJsonValue(resourceSourcePersistQueuedSources, []);
            const token = Number(resourceSourcePersistQueuedToken || 0);
            resourceSourcePersistQueuedSources = null;
            resourceSourcePersistQueuedToken = 0;
            resourceSourcePersistInFlight = true;
            try {
                const data = await window.MediaHubApi.postJson('/resource/sources/save', { sources: sourcesToSave });
                const committedSources = cloneJsonValue(data.sources || sourcesToSave, sourcesToSave);
                settleResourceSourcePersistPromises(token, null, data);
                if (token === resourceSourcePersistToken) {
                    resourceSourcePersistRollbackSources = null;
                    applyResourceSourcesLocal(committedSources, { deferHeavyRender: true });
                } else {
                    resourceSourcePersistRollbackSources = committedSources;
                }
            } catch (error) {
                if (token === resourceSourcePersistToken) {
                    settleResourceSourcePersistPromises(token, error);
                    const rollbackSources = cloneJsonValue(resourceSourcePersistRollbackSources || [], []);
                    resourceSourcePersistRollbackSources = null;
                    applyResourceSourcesLocal(rollbackSources, { deferHeavyRender: true });
                } else {
                    settleResourceSourcePersistPromises(token, null, { ok: false, stale: true });
                }
            } finally {
                resourceSourcePersistInFlight = false;
                if (resourceSourcePersistQueuedSources) {
                    scheduleResourceSourcePersistFlush(0);
                }
            }
        }

        function queueResourceSourcePersist(nextSources, rollbackSources, options = {}) {
            const token = Number(options.token || resourceSourcePersistToken || 0);
            if (!resourceSourcePersistRollbackSources) {
                resourceSourcePersistRollbackSources = cloneJsonValue(rollbackSources || [], []);
            }
            resourceSourcePersistQueuedSources = cloneJsonValue(nextSources, []);
            resourceSourcePersistQueuedToken = token;
            const promise = new Promise((resolve, reject) => {
                resourceSourcePersistPending.push({ token, resolve, reject });
            });
            scheduleResourceSourcePersistFlush(options.immediate ? 0 : RESOURCE_SOURCE_SAVE_DEBOUNCE_MS);
            return promise;
        }

        function persistResourceSources(sources, options = {}) {
            const nextSources = cloneJsonValue(Array.isArray(sources) ? sources : [], []);
            const previousSources = cloneJsonValue(resourceState.sources || [], []);
            const persistToken = ++resourceSourcePersistToken;
            applyResourceSourcesLocal(nextSources, { deferHeavyRender: true });
            return queueResourceSourcePersist(nextSources, previousSources, {
                token: persistToken,
                immediate: !!options.immediate,
            });
        }

        function reportResourceSourcePersistFailure(saveTask, actionLabel = '保存') {
            void Promise.resolve(saveTask).catch(error => {
                showToast(`${actionLabel}失败：${error?.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            });
        }

        async function moveResourceSource(index, offset) {
            const sources = [...(resourceState.sources || [])];
            const nextIndex = index + offset;
            if (index < 0 || nextIndex < 0 || nextIndex >= sources.length) return;
            [sources[index], sources[nextIndex]] = [sources[nextIndex], sources[index]];
            try {
                const saveTask = persistResourceSources(sources);
                reportResourceSourcePersistFailure(saveTask, '排序');
            } catch (e) {
                showToast(`排序失败：${e.message}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        async function toggleResourceSourceEnabled(index, enabled) {
            const sources = [...(resourceState.sources || [])];
            if (index < 0 || index >= sources.length) return false;
            sources[index] = {
                ...sources[index],
                enabled: !!enabled
            };
            try {
                const saveTask = persistResourceSources(sources);
                reportResourceSourcePersistFailure(saveTask, enabled ? '启用' : '停用');
                return true;
            } catch (e) {
                showToast(`操作失败：${e.message}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return false;
            }
        }

        async function saveResourceSource() {
            const source = currentResourceSourceFormData();
            const isEditing = editingResourceSourceIndex !== null && editingResourceSourceIndex >= 0;
            if (!source.name && !source.channel_id) return showToast('请至少填写频道名称或频道 ID', { tone: 'warn', duration: 2600, placement: 'top-center' });
            if (!source.channel_id) return showToast('频道 ID 不能为空，例如 QukanMovie', { tone: 'warn', duration: 2600, placement: 'top-center' });
            if (!isLikelyTelegramChannelId(source.channel_id)) {
                return showToast('频道 ID 看起来不是有效的公开频道用户名，请填写 t.me 后面的标识', { tone: 'warn', duration: 3800, placement: 'top-center' });
            }
            const sources = [...(resourceState.sources || [])];
            if (editingResourceSourceIndex !== null && editingResourceSourceIndex >= 0) sources[editingResourceSourceIndex] = source;
            else sources.push(source);
            try {
                const saveTask = persistResourceSources(sources, { immediate: true });
                closeResourceSourceModal();
                showToast(isEditing ? '频道订阅已更新' : '频道订阅已添加', { tone: 'success', duration: 2400, placement: 'top-center' });
                reportResourceSourcePersistFailure(saveTask, isEditing ? '更新' : '添加');
            } catch (e) {
                showToast(`保存失败：${e.message}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        function editResourceSource(index) {
            openResourceSourceModal(index);
        }

        async function deleteResourceSource(index, options = {}) {
            const source = (resourceState.sources || [])[index];
            if (!source) return;
            const channelId = getResourceSourceChannelId(source);
            const shouldConfirm = options.confirm !== false;
            if (shouldConfirm && !(await showAppConfirm(`确定删除频道源“${source.name || channelId || '未命名频道'}”吗？`))) return false;
            const sources = [...(resourceState.sources || [])];
            sources.splice(index, 1);
            try {
                const saveTask = persistResourceSources(sources);
                if (editingResourceSourceIndex === index) closeResourceSourceModal();
                reportResourceSourcePersistFailure(saveTask, '删除');
                return true;
            } catch (e) {
                showToast(`删除失败：${e.message}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return false;
            }
        }

        function renderResourceSources() {
            const container = document.getElementById('resource-source-list');
            syncResourceSourceSummary();
            if (container) container.innerHTML = '';
            renderResourceSourceManagerModal();
        }
