        function cloneJsonValue(value, fallback = null) {
            try {
                return JSON.parse(JSON.stringify(value));
            } catch (e) {
                return fallback;
            }
        }

        function normalizeResourceProviderCacheKey(provider = '115') {
            return normalizeSubscriptionProvider(provider, '115') === 'quark' ? 'quark' : '115';
        }

        function buildResourceFolderBranchCacheKey(cid = '0', { provider = '115', foldersOnly = false } = {}) {
            const normalizedCid = String(cid || '0').trim() || '0';
            const providerKey = normalizeResourceProviderCacheKey(provider);
            return `${providerKey}|${foldersOnly ? '1' : '0'}|${normalizedCid}`;
        }

        function pruneResourceFolderBranchCache() {
            const now = Date.now();
            Object.keys(resourceFolderBranchCache || {}).forEach((key) => {
                const cached = resourceFolderBranchCache[key];
                const cachedAt = Number(cached?.cached_at || 0);
                if (!cached || !cachedAt || (now - cachedAt) > RESOURCE_FOLDER_BRANCH_CACHE_TTL_MS) {
                    delete resourceFolderBranchCache[key];
                }
            });
        }

        function getResourceFolderBranchCache(cid = '0', options = {}) {
            pruneResourceFolderBranchCache();
            const cacheKey = buildResourceFolderBranchCacheKey(cid, options);
            const cached = resourceFolderBranchCache[cacheKey];
            if (!cached) return null;
            return {
                entries: cloneJsonValue(cached.entries, []),
                summary: cloneJsonValue(cached.summary, { folder_count: 0, file_count: 0 })
            };
        }

        function setResourceFolderBranchCache(cid = '0', payload = {}, options = {}) {
            const entries = Array.isArray(payload?.entries) ? payload.entries : [];
            const summary = payload?.summary || { folder_count: 0, file_count: 0 };
            const cacheKey = buildResourceFolderBranchCacheKey(cid, options);
            resourceFolderBranchCache[cacheKey] = {
                entries: cloneJsonValue(entries, []),
                summary: cloneJsonValue(summary, { folder_count: 0, file_count: 0 }),
                cached_at: Date.now()
            };
            pruneResourceFolderBranchCache();
        }

        function buildResourceFolderSummaryFromEntries(entries = []) {
            const normalizedEntries = Array.isArray(entries) ? entries : [];
            let folderCount = 0;
            for (const entry of normalizedEntries) {
                if (entry?.is_dir) folderCount += 1;
            }
            return {
                folder_count: folderCount,
                file_count: Math.max(0, normalizedEntries.length - folderCount)
            };
        }

        function buildResourceFoldersOnlyPayload(payload = {}) {
            const sourceEntries = Array.isArray(payload?.entries) ? payload.entries : [];
            const folderEntries = sourceEntries.filter(entry => !!entry?.is_dir);
            const sourceSummary = payload?.summary && typeof payload.summary === 'object'
                ? payload.summary
                : buildResourceFolderSummaryFromEntries(sourceEntries);
            return {
                entries: folderEntries,
                summary: {
                    folder_count: Number(sourceSummary.folder_count || folderEntries.length),
                    file_count: Number(sourceSummary.file_count || 0)
                }
            };
        }

        function setResourceFolderBranchCaches(cid = '0', payload = {}, { provider = '115' } = {}) {
            const fullPayload = {
                entries: Array.isArray(payload?.entries) ? payload.entries : [],
                summary: payload?.summary || buildResourceFolderSummaryFromEntries(payload?.entries || [])
            };
            setResourceFolderBranchCache(cid, fullPayload, { provider, foldersOnly: false });
            setResourceFolderBranchCache(cid, buildResourceFoldersOnlyPayload(fullPayload), { provider, foldersOnly: true });
        }

        function invalidateResourceFolderBranchCache(provider = '') {
            const providerKey = String(provider || '').trim()
                ? normalizeResourceProviderCacheKey(provider)
                : '';
            if (!providerKey) {
                resourceFolderBranchCache = {};
                resourceFolderFetchInFlight = {};
                return;
            }
            Object.keys(resourceFolderBranchCache || {}).forEach((key) => {
                if (key.startsWith(`${providerKey}|`)) delete resourceFolderBranchCache[key];
            });
            Object.keys(resourceFolderFetchInFlight || {}).forEach((key) => {
                if (key.startsWith(`${providerKey}|`)) delete resourceFolderFetchInFlight[key];
            });
        }

        async function fetchResourceFolderData(
            cid = '0',
            { provider = '115', foldersOnly = false, forceRefresh = false } = {}
        ) {
            const normalizedProvider = normalizeResourceProviderCacheKey(provider);
            const normalizedCid = String(cid || '0').trim() || '0';
            const normalizedFoldersOnly = !!foldersOnly;
            const cacheOptions = {
                provider: normalizedProvider,
                foldersOnly: normalizedFoldersOnly
            };
            if (!forceRefresh) {
                const cached = getResourceFolderBranchCache(normalizedCid, cacheOptions);
                if (cached) {
                    return {
                        entries: Array.isArray(cached.entries) ? cached.entries : [],
                        summary: cached.summary || { folder_count: 0, file_count: 0 }
                    };
                }
            }
            const cacheKey = buildResourceFolderBranchCacheKey(normalizedCid, {
                provider: normalizedProvider,
                foldersOnly: normalizedFoldersOnly
            });
            const inFlight = resourceFolderFetchInFlight[cacheKey];
            if (inFlight) {
                const sharedPayload = await inFlight;
                return {
                    entries: cloneJsonValue(sharedPayload.entries, []),
                    summary: cloneJsonValue(sharedPayload.summary, { folder_count: 0, file_count: 0 })
                };
            }
            const requestPromise = (async () => {
                const apiPrefix = getResourceFolderApiPrefix(normalizedProvider);
                const params = new URLSearchParams({ cid: normalizedCid });
                params.set('compact', '1');
                if (normalizedFoldersOnly) params.set('folders_only', '1');
                const res = await fetch(`${apiPrefix}/folders?${params.toString()}`);
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '读取目录失败');
                const entries = Array.isArray(data.entries) ? data.entries : [];
                const summary = data.summary && typeof data.summary === 'object'
                    ? data.summary
                    : buildResourceFolderSummaryFromEntries(entries);
                const payload = {
                    entries,
                    summary: {
                        folder_count: Number(summary.folder_count || 0),
                        file_count: Number(summary.file_count || 0)
                    }
                };
                if (normalizedFoldersOnly) {
                    setResourceFolderBranchCache(normalizedCid, payload, cacheOptions);
                } else {
                    setResourceFolderBranchCaches(normalizedCid, payload, { provider: normalizedProvider });
                }
                return payload;
            })();
            resourceFolderFetchInFlight[cacheKey] = requestPromise;
            try {
                const payload = await requestPromise;
                return {
                    entries: cloneJsonValue(payload.entries, []),
                    summary: cloneJsonValue(payload.summary, { folder_count: 0, file_count: 0 })
                };
            } finally {
                if (resourceFolderFetchInFlight[cacheKey] === requestPromise) {
                    delete resourceFolderFetchInFlight[cacheKey];
                }
            }
        }

        async function createResourceFolder(cid = '0', name = '', { provider = '115' } = {}) {
            const apiPrefix = getResourceFolderApiPrefix(provider);
            const res = await fetch(`${apiPrefix}/folders/create`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    cid: String(cid || '0'),
                    name: String(name || '')
                })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.msg || '新建文件夹失败');
            return data;
        }

        function buildResourceShareBranchCacheKey(resourceId, item, receiveCode = '') {
            const resolvedId = Math.max(0, Number(resourceId || item?.id || 0));
            const linkUrl = String(item?.link_url || '').trim();
            if (!linkUrl) return '';
            const normalizedCode = normalizeReceiveCodeInput(receiveCode);
            return `${resolvedId}|${linkUrl}|${normalizedCode || '-'}`;
        }

        function pruneResourceShareBranchCache() {
            const now = Date.now();
            Object.keys(resourceShareBranchCache || {}).forEach((key) => {
                const cached = resourceShareBranchCache[key];
                const cachedAt = Number(cached?.cached_at || 0);
                if (!cached || !cachedAt || (now - cachedAt) > RESOURCE_SHARE_BRANCH_CACHE_TTL_MS) {
                    delete resourceShareBranchCache[key];
                }
            });
        }

        function saveResourceShareBranchCache(resourceId, item, receiveCode = '') {
            if (!resourceShareRootLoaded) return;
            const cacheKey = buildResourceShareBranchCacheKey(resourceId, item, receiveCode);
            if (!cacheKey) return;
            resourceShareBranchCache[cacheKey] = {
                entriesByParent: cloneJsonValue(resourceShareEntriesByParent, { '0': [] }),
                nextOffsetByParent: cloneJsonValue(resourceShareNextOffsetByParent, { '0': 0 }),
                hasMoreByParent: cloneJsonValue(resourceShareHasMoreByParent, {}),
                info: cloneJsonValue(resourceShareInfo, { title: '', count: 0, share_code: '', receive_code: '' }),
                rootLoaded: !!resourceShareRootLoaded,
                cached_at: Date.now()
            };
            pruneResourceShareBranchCache();
        }

        function restoreResourceShareBranchCache(resourceId, item, receiveCode = '') {
            pruneResourceShareBranchCache();
            const cacheKey = buildResourceShareBranchCacheKey(resourceId, item, receiveCode);
            if (!cacheKey) return false;
            const cached = resourceShareBranchCache[cacheKey];
            if (!cached) return false;

            resourceShareEntriesByParent = cloneJsonValue(cached.entriesByParent, { '0': [] }) || { '0': [] };
            resourceShareNextOffsetByParent = cloneJsonValue(cached.nextOffsetByParent, { '0': 0 }) || { '0': 0 };
            resourceShareHasMoreByParent = cloneJsonValue(cached.hasMoreByParent, {}) || {};
            resourceShareInfo = cloneJsonValue(
                cached.info,
                { title: '', count: 0, share_code: '', receive_code: '' }
            ) || { title: '', count: 0, share_code: '', receive_code: '' };
            resourceShareRootLoaded = !!cached.rootLoaded;
            resourceShareEntryIndex = {};

            Object.keys(resourceShareEntriesByParent || {}).forEach((parentId) => {
                const branchEntries = Array.isArray(resourceShareEntriesByParent[parentId])
                    ? resourceShareEntriesByParent[parentId]
                    : [];
                resourceShareEntriesByParent[parentId] = branchEntries;
                branchEntries.forEach((entry) => {
                    const normalized = buildResourceShareSelectableEntry(entry);
                    if (normalized.id) resourceShareEntryIndex[normalized.id] = { ...entry, ...normalized };
                });
            });

            resourceShareExpanded = {};
            resourceShareLoadingParents = {};
            resourceShareLoadingMoreParents = {};
            resourceShareLoading = false;
            resourceShareError = '';
            resourceShareCurrentCid = '0';
            resourceShareTrail = [{ cid: '0', name: resourceShareInfo?.title || '分享根目录' }];
            resourceShareSelected = {};
            if (resourceShareRootLoaded) {
                selectAllResourceShareRoot({ renderAfter: false });
            }
            return resourceShareRootLoaded;
        }

        function resetResourceShareState() {
            resourceShareEntriesByParent = { '0': [] };
            resourceShareEntryIndex = {};
            resourceShareExpanded = {};
            resourceShareLoadingParents = {};
            resourceShareLoadingMoreParents = {};
            resourceShareNextOffsetByParent = { '0': 0 };
            resourceShareHasMoreByParent = {};
            resourceShareSelected = {};
            resourceShareLoading = false;
            resourceShareError = '';
            resourceShareRootLoaded = false;
            resourceShareInfo = { title: '', count: 0, share_code: '', receive_code: '' };
            resourceShareReceiveCode = '';
            resourceShareTrail = [{ cid: '0', name: '分享根目录' }];
            resourceShareCurrentCid = '0';
        }

        function buildResourceShareSelectableEntry(entry) {
            return {
                id: String(entry?.id || '').trim(),
                name: String(entry?.name || '').trim(),
                is_dir: !!entry?.is_dir,
                parent_id: String(entry?.parent_id || '0').trim() || '0',
                cid: String(entry?.cid || '').trim(),
                fid: String(entry?.fid || '').trim()
            };
        }

        function isCurrentResource115Share() {
            return isResourceShareLinkType(resourceModalLinkType);
        }

        function syncResourceShareReceiveCodeSection() {
            const sectionEl = document.getElementById('resource-share-receive-code-section');
            const inputEl = document.getElementById('resource_share_receive_code');
            const applyBtnEl = document.getElementById('resource-share-receive-code-apply');
            const labelEl = document.getElementById('resource-share-receive-code-label');
            const shouldShow = resourceModalMode === 'import' && isCurrentResource115Share();
            const providerLabel = getResourceProviderLabel(getCurrentResourceProvider());

            if (sectionEl) sectionEl.classList.toggle('hidden', !shouldShow);
            if (!shouldShow) return;
            if (labelEl) labelEl.textContent = `${providerLabel} 提取码`;

            if (inputEl) {
                inputEl.value = resourceShareReceiveCode || '';
                inputEl.disabled = resourceShareLoading;
            }
            if (applyBtnEl) {
                applyBtnEl.disabled = resourceShareLoading;
                applyBtnEl.classList.toggle('btn-disabled', resourceShareLoading);
                applyBtnEl.textContent = resourceShareLoading ? '读取中...' : '应用并刷新';
            }
        }

        async function applyResourceShareReceiveCode() {
            if (resourceModalMode !== 'import' || !isCurrentResource115Share()) return;
            const inputEl = document.getElementById('resource_share_receive_code');
            const rawCode = String(inputEl?.value || '').trim();
            const normalizedCode = normalizeReceiveCodeInput(rawCode);
            if (rawCode && !normalizedCode) {
                alert('提取码格式不正确，请输入 1-16 位字母或数字');
                return;
            }
            resourceShareReceiveCode = normalizedCode;
            syncResourceShareReceiveCodeSection();
            if (!isLinkTypeCookieConfigured(resourceModalLinkType) || !selectedResourceItem) return;
            if (restoreResourceShareBranchCache(selectedResourceId, selectedResourceItem, resourceShareReceiveCode)) {
                syncResourceSharetitleFromSelection();
                renderResourceShareBrowser();
                return;
            }
            await loadResourceShareBranch(selectedResourceId, '0', { resetSelection: true });
        }

        async function fetchResourceShareData(
            resourceId,
            cid = '0',
            {
                offset = 0,
                limit = RESOURCE_SHARE_BROWSE_PAGE_LIMIT,
                paged = true
            } = {}
        ) {
            const receiveCode = normalizeReceiveCodeInput(resourceShareReceiveCode);
            const normalizedOffset = Math.max(0, Number(offset || 0));
            const normalizedLimit = Math.max(20, Math.min(Number(limit || RESOURCE_SHARE_BROWSE_PAGE_LIMIT), 400));
            const shareApiPrefix = getResourceShareApiPrefix(resourceModalLinkType);
            let res;
            if (Number(resourceId || 0) > 0) {
                const params = new URLSearchParams({
                    resource_id: String(resourceId || 0),
                    cid: String(cid || '0')
                });
                if (receiveCode) params.set('receive_code', receiveCode);
                if (paged) params.set('paged', '1');
                params.set('offset', String(normalizedOffset));
                params.set('limit', String(normalizedLimit));
                res = await fetch(`${shareApiPrefix}/share_entries?${params.toString()}`);
            } else {
                res = await fetch(`${shareApiPrefix}/share_entries_preview`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        cid,
                        link_url: String(selectedResourceItem?.link_url || '').trim(),
                        raw_text: String(selectedResourceItem?.raw_text || '').trim(),
                        receive_code: receiveCode,
                        paged: !!paged,
                        offset: normalizedOffset,
                        limit: normalizedLimit
                    })
                });
            }
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.msg || '读取分享内容失败');
            const entries = Array.isArray(data.entries) ? data.entries : [];
            const paging = data.paging && typeof data.paging === 'object' ? data.paging : {};
            const nextOffset = Math.max(
                normalizedOffset + entries.length,
                Number(paging.next_offset ?? (normalizedOffset + entries.length)) || (normalizedOffset + entries.length)
            );
            return {
                entries,
                summary: data.summary || { folder_count: 0, file_count: 0 },
                share: data.share || { title: '', share_code: '', receive_code: '', count: 0 },
                paging: {
                    offset: Math.max(0, Number(paging.offset ?? normalizedOffset) || normalizedOffset),
                    next_offset: nextOffset,
                    has_more: !!paging.has_more
                }
            };
        }

        function getResourceShareSelectedEntries() {
            return Object.values(resourceShareSelected || {}).sort((a, b) => String(a?.name || '').localeCompare(String(b?.name || '')));
        }

        function getResourceShareSelectionState() {
            const selectedEntries = getResourceShareSelectedEntries();
            const selectedIds = selectedEntries.map(entry => String(entry.id || '').trim()).filter(Boolean);
            let refreshTargetType = '';
            let autoSharetitle = '';
            if (selectedEntries.length === 1) {
                refreshTargetType = selectedEntries[0].is_dir ? 'folder' : 'file';
                autoSharetitle = normalizeRelativePathInput(selectedEntries[0].name || '');
            } else if (selectedEntries.length > 1) {
                refreshTargetType = 'mixed';
            }
            return {
                selected_entries: selectedEntries,
                selected_ids: selectedIds,
                refresh_target_type: refreshTargetType,
                auto_sharetitle: autoSharetitle,
                share_root_title: normalizeRelativePathInput(resourceShareInfo?.title || '')
            };
        }

        function getResourceShareCoveredAncestor(entry) {
            let parentId = String(entry?.parent_id || '0').trim() || '0';
            while (parentId && parentId !== '0') {
                const ancestor = resourceShareSelected[parentId];
                if (ancestor?.is_dir) return ancestor;
                const parentEntry = resourceShareEntryIndex[parentId];
                parentId = String(parentEntry?.parent_id || '0').trim() || '0';
            }
            return null;
        }

        function isResourceShareDescendantOf(entry, ancestorId) {
            let parentId = String(entry?.parent_id || '0').trim() || '0';
            const targetId = String(ancestorId || '').trim();
            while (parentId && parentId !== '0') {
                if (parentId === targetId) return true;
                const parentEntry = resourceShareEntryIndex[parentId];
                parentId = String(parentEntry?.parent_id || '0').trim() || '0';
            }
            return false;
        }

        function syncResourceSharetitleFromSelection() {
            return;
        }

        function getCurrentResourceShareEntries() {
            return Array.isArray(resourceShareEntriesByParent?.[resourceShareCurrentCid]) ? resourceShareEntriesByParent[resourceShareCurrentCid] : [];
        }

        function isResourceShareEntryEffectivelySelected(entry) {
            const normalized = buildResourceShareSelectableEntry(entry);
            return !!resourceShareSelected[normalized.id] || !!getResourceShareCoveredAncestor(normalized);
        }

        function clearResourceShareSelection() {
            resourceShareSelected = {};
            syncResourceSharetitleFromSelection();
            renderResourceShareBrowser();
        }

        function selectAllResourceShareRoot({ renderAfter = true } = {}) {
            const rootEntries = Array.isArray(resourceShareEntriesByParent?.['0']) ? resourceShareEntriesByParent['0'] : [];
            resourceShareSelected = {};
            rootEntries.forEach(entry => {
                const normalized = buildResourceShareSelectableEntry(entry);
                if (!normalized.id) return;
                resourceShareSelected[normalized.id] = normalized;
            });
            resourceShareCurrentCid = '0';
            resourceShareTrail = [{ cid: '0', name: resourceShareInfo?.title || '分享根目录' }];
            syncResourceSharetitleFromSelection();
            if (renderAfter) renderResourceShareBrowser();
        }

        function setCurrentResourceShareEntriesChecked(checked) {
            const entries = getCurrentResourceShareEntries();
            if (!entries.length) return;
            if (!checked) {
                const coveredAncestorIds = new Set();
                entries.forEach(entry => {
                    const ancestor = getResourceShareCoveredAncestor(buildResourceShareSelectableEntry(entry));
                    if (ancestor?.id) coveredAncestorIds.add(String(ancestor.id));
                });
                coveredAncestorIds.forEach(ancestorId => {
                    delete resourceShareSelected[ancestorId];
                });
            }
            entries.forEach(entry => applyResourceShareSelection(entry, checked, { renderAfter: false }));
            syncResourceSharetitleFromSelection();
            renderResourceShareBrowser();
        }

        function autoSelectCurrentResourceShareEntries({ clearEntryId = '' } = {}) {
            const normalizedClearId = String(clearEntryId || '').trim();
            if (normalizedClearId) delete resourceShareSelected[normalizedClearId];
            const entries = getCurrentResourceShareEntries();
            if (!entries.length) {
                syncResourceSharetitleFromSelection();
                renderResourceShareBrowser();
                return;
            }
            entries.forEach(entry => applyResourceShareSelection(entry, true, { renderAfter: false }));
            syncResourceSharetitleFromSelection();
            renderResourceShareBrowser();
        }

        function narrowResourceShareSelectionToBranch(branchId) {
            const normalizedBranchId = String(branchId || '').trim();
            if (!normalizedBranchId) return;
            Object.keys(resourceShareSelected || {}).forEach(selectedId => {
                const selectedEntry = buildResourceShareSelectableEntry(resourceShareSelected[selectedId] || {});
                const currentId = String(selectedEntry.id || selectedId || '').trim();
                if (!currentId) {
                    delete resourceShareSelected[selectedId];
                    return;
                }
                const keepInBranch = currentId === normalizedBranchId || isResourceShareDescendantOf(selectedEntry, normalizedBranchId);
                if (!keepInBranch) {
                    delete resourceShareSelected[currentId];
                }
            });
        }

        async function reloadResourceShareRoot() {
            if (!selectedResourceItem || !isCurrentResource115Share()) return;
            await loadResourceShareBranch(selectedResourceId, '0', { resetSelection: true });
        }

        function applyResourceShareSelection(entry, checked, { renderAfter = true } = {}) {
            const normalized = buildResourceShareSelectableEntry(entry);
            if (!normalized.id) return;
            if (checked) {
                let parentId = normalized.parent_id;
                while (parentId && parentId !== '0') {
                    const ancestor = resourceShareSelected[parentId];
                    if (ancestor?.is_dir) delete resourceShareSelected[parentId];
                    const parentEntry = resourceShareEntryIndex[parentId];
                    parentId = String(parentEntry?.parent_id || '0').trim() || '0';
                }
                if (normalized.is_dir) {
                    Object.keys(resourceShareSelected).forEach(selectedId => {
                        const selectedEntry = resourceShareSelected[selectedId];
                        if (isResourceShareDescendantOf(selectedEntry, normalized.id)) {
                            delete resourceShareSelected[selectedId];
                        }
                    });
                }
                resourceShareSelected[normalized.id] = normalized;
            } else {
                delete resourceShareSelected[normalized.id];
            }
            if (renderAfter) {
                syncResourceSharetitleFromSelection();
                renderResourceShareBrowser();
            }
        }

        async function loadResourceShareBranch(resourceId, cid = '0', { resetSelection = false, append = false } = {}) {
            if (!isLinkTypeCookieConfigured(resourceModalLinkType) || !isCurrentResource115Share()) {
                renderResourceShareBrowser();
                return;
            }
            const branchId = String(cid || '0');
            const isRoot = branchId === '0';
            const appendMode = !!append;
            let currentToken = resourceShareRequestToken;
            if (isRoot) {
                if (resetSelection && !appendMode) {
                    resourceShareEntriesByParent = { '0': [] };
                    resourceShareEntryIndex = {};
                    resourceShareExpanded = {};
                    resourceShareLoadingParents = {};
                    resourceShareLoadingMoreParents = {};
                    resourceShareNextOffsetByParent = { '0': 0 };
                    resourceShareHasMoreByParent = {};
                    resourceShareSelected = {};
                }
                if (!appendMode) {
                    resourceShareLoading = true;
                    resourceShareError = '';
                    resourceShareRequestToken += 1;
                    currentToken = resourceShareRequestToken;
                    resourceShareCurrentCid = '0';
                    resourceShareTrail = [{ cid: '0', name: resourceShareInfo?.title || '分享根目录' }];
                }
            }
            if (appendMode) resourceShareLoadingMoreParents[branchId] = true;
            else resourceShareLoadingParents[branchId] = true;
            renderResourceShareBrowser();
            try {
                const requestOffset = appendMode
                    ? Math.max(0, Number(resourceShareNextOffsetByParent[branchId] || 0))
                    : 0;
                const result = await fetchResourceShareData(resourceId, branchId, {
                    offset: requestOffset,
                    limit: RESOURCE_SHARE_BROWSE_PAGE_LIMIT,
                    paged: true
                });
                if (selectedResourceId !== Number(resourceId)) return;
                if (isRoot && !appendMode && currentToken !== resourceShareRequestToken) return;
                const incomingEntries = Array.isArray(result.entries) ? result.entries : [];
                const existingEntries = Array.isArray(resourceShareEntriesByParent?.[branchId]) ? resourceShareEntriesByParent[branchId] : [];
                let mergedEntries = incomingEntries;
                if (appendMode) {
                    const seen = new Set(existingEntries.map(item => String(item?.id || '').trim()).filter(Boolean));
                    const appended = incomingEntries.filter(item => {
                        const id = String(item?.id || '').trim();
                        if (!id || seen.has(id)) return false;
                        seen.add(id);
                        return true;
                    });
                    mergedEntries = existingEntries.concat(appended);
                }
                resourceShareEntriesByParent[branchId] = mergedEntries;
                mergedEntries.forEach(entry => {
                    const normalized = buildResourceShareSelectableEntry(entry);
                    if (normalized.id) resourceShareEntryIndex[normalized.id] = { ...entry, ...normalized };
                });
                const nextOffset = Math.max(
                    requestOffset + incomingEntries.length,
                    Number(result?.paging?.next_offset ?? (requestOffset + incomingEntries.length)) || (requestOffset + incomingEntries.length)
                );
                resourceShareNextOffsetByParent[branchId] = nextOffset;
                resourceShareHasMoreByParent[branchId] = !!result?.paging?.has_more;
                if (isRoot) {
                    if (!appendMode) {
                        resourceShareRootLoaded = true;
                        resourceShareInfo = result.share || { title: '', share_code: '', receive_code: '', count: 0 };
                        const serverReceiveCode = normalizeReceiveCodeInput(resourceShareInfo?.receive_code || '');
                        if (serverReceiveCode && !resourceShareReceiveCode) {
                            resourceShareReceiveCode = serverReceiveCode;
                        }
                        resourceShareTrail = [{ cid: '0', name: resourceShareInfo?.title || '分享根目录' }];
                        if (resetSelection || !getResourceShareSelectedEntries().length) {
                            selectAllResourceShareRoot({ renderAfter: false });
                        } else {
                            syncResourceSharetitleFromSelection();
                        }
                    } else {
                        syncResourceSharetitleFromSelection();
                    }
                }
                saveResourceShareBranchCache(resourceId, selectedResourceItem, resourceShareReceiveCode);
            } catch (e) {
                if (selectedResourceId !== Number(resourceId)) return;
                if (isRoot && !appendMode) {
                    resourceShareEntriesByParent = { '0': [] };
                    resourceShareEntryIndex = {};
                    resourceShareLoadingMoreParents = {};
                    resourceShareNextOffsetByParent = { '0': 0 };
                    resourceShareHasMoreByParent = {};
                    resourceShareSelected = {};
                    resourceShareRootLoaded = false;
                    resourceShareInfo = { title: '', count: 0, share_code: '', receive_code: '' };
                    resourceShareTrail = [{ cid: '0', name: '分享根目录' }];
                    resourceShareCurrentCid = '0';
                    resourceShareError = e.message || '读取分享内容失败';
                    syncResourceSharetitleFromSelection({ force: true });
                } else {
                    alert(`❌ ${e.message || '读取子目录失败'}`);
                }
            } finally {
                if (appendMode) delete resourceShareLoadingMoreParents[branchId];
                else delete resourceShareLoadingParents[branchId];
                if (isRoot && !appendMode) resourceShareLoading = false;
                if (isRoot && !appendMode) syncResourceShareReceiveCodeSection();
                renderResourceShareBrowser();
            }
        }

        async function loadMoreResourceShareCurrentFolder() {
            if (!selectedResourceItem || !isCurrentResource115Share()) return;
            const branchId = String(resourceShareCurrentCid || '0').trim() || '0';
            if (!resourceShareHasMoreByParent[branchId]) return;
            if (resourceShareLoadingMoreParents[branchId]) return;
            await loadResourceShareBranch(selectedResourceId, branchId, { append: true });
        }

        async function goResourceShareRoot() {
            if (!selectedResourceItem || !isCurrentResource115Share()) return;
            resourceShareTrail = [{ cid: '0', name: resourceShareInfo?.title || '分享根目录' }];
            resourceShareCurrentCid = '0';
            if (!Object.prototype.hasOwnProperty.call(resourceShareEntriesByParent, '0') || !resourceShareRootLoaded) {
                await loadResourceShareBranch(selectedResourceId, '0');
                return;
            }
            renderResourceShareBrowser();
        }

        async function goResourceShareBack() {
            if (!selectedResourceItem || !isCurrentResource115Share()) return;
            if (resourceShareTrail.length <= 1) {
                await goResourceShareRoot();
                return;
            }
            resourceShareTrail = resourceShareTrail.slice(0, -1);
            resourceShareCurrentCid = String(resourceShareTrail[resourceShareTrail.length - 1]?.cid || '0');
            if (!Object.prototype.hasOwnProperty.call(resourceShareEntriesByParent, resourceShareCurrentCid)) {
                await loadResourceShareBranch(selectedResourceId, resourceShareCurrentCid);
                return;
            }
            renderResourceShareBrowser();
        }

        async function openResourceShareFolder(entryId) {
            if (!selectedResourceItem || !isCurrentResource115Share()) return;
            const entry = resourceShareEntryIndex[String(entryId || '').trim()];
            if (!entry || !entry.is_dir) return;
            const normalizedEntryId = String(entry.id || '').trim();
            if (normalizedEntryId) {
                // 进入子目录后，仅保留该子树内的选择，避免误带上级目录文件一起转存。
                narrowResourceShareSelectionToBranch(normalizedEntryId);
                delete resourceShareSelected[normalizedEntryId];
            }
            const branchId = String(entry.cid || entry.id || '').trim();
            if (!branchId) return;
            resourceShareCurrentCid = branchId;
            resourceShareTrail = resourceShareTrail.concat([{ cid: branchId, name: String(entry.name || '未命名目录') }]);
            if (!Object.prototype.hasOwnProperty.call(resourceShareEntriesByParent, branchId)) {
                await loadResourceShareBranch(selectedResourceId, branchId);
                if (!Object.prototype.hasOwnProperty.call(resourceShareEntriesByParent, branchId)) return;
                autoSelectCurrentResourceShareEntries({ clearEntryId: normalizedEntryId });
                return;
            }
            autoSelectCurrentResourceShareEntries({ clearEntryId: normalizedEntryId });
        }

        async function openResourceShareTrail(index) {
            if (!selectedResourceItem || !isCurrentResource115Share()) return;
            const targetIndex = Math.max(0, Math.min(Number(index || 0), resourceShareTrail.length - 1));
            resourceShareTrail = resourceShareTrail.slice(0, targetIndex + 1);
            resourceShareCurrentCid = String(resourceShareTrail[targetIndex]?.cid || '0');
            if (!Object.prototype.hasOwnProperty.call(resourceShareEntriesByParent, resourceShareCurrentCid)) {
                await loadResourceShareBranch(selectedResourceId, resourceShareCurrentCid);
                return;
            }
            renderResourceShareBrowser();
        }

        function getResourceBrowserContext() {
            return {
                RESOURCE_FOLDER_FILE_PREVIEW_LIMIT,
                get resourceModalMode() { return resourceModalMode; },
                get resourceModalLinkType() { return resourceModalLinkType; },
                get resourceShareSelected() { return resourceShareSelected || {}; },
                get resourceShareLoading() { return resourceShareLoading; },
                get resourceShareError() { return resourceShareError; },
                get resourceShareRootLoaded() { return resourceShareRootLoaded; },
                get resourceShareTrail() { return resourceShareTrail || []; },
                get resourceShareCurrentCid() { return resourceShareCurrentCid; },
                get resourceShareLoadingParents() { return resourceShareLoadingParents || {}; },
                get resourceShareLoadingMoreParents() { return resourceShareLoadingMoreParents || {}; },
                get resourceShareHasMoreByParent() { return resourceShareHasMoreByParent || {}; },
                get resourceFolderEntries() { return resourceFolderEntries || []; },
                get resourceFolderSummary() { return resourceFolderSummary || {}; },
                get resourceFolderLoading() { return resourceFolderLoading; },
                get resourceFolderFilesLoading() { return resourceFolderFilesLoading; },
                get resourceFolderEntriesComplete() { return resourceFolderEntriesComplete; },
                get resourceFolderShowAllFiles() { return resourceFolderShowAllFiles; },
                get resourceFolderTrail() { return resourceFolderTrail || []; },
                get resourceTargetPreviewEntries() { return resourceTargetPreviewEntries || []; },
                get resourceTargetPreviewSummary() { return resourceTargetPreviewSummary || {}; },
                get resourceTargetPreviewLoading() { return resourceTargetPreviewLoading; },
                get resourceTargetPreviewError() { return resourceTargetPreviewError; },
                escapeHtml,
                formatFileSizeText,
                getResourceIconSvg,
                buildResourceEntryRow,
                buildResourceShareSelectableEntry,
                getResourceShareCoveredAncestor,
                getCurrentResourceShareEntries,
                isResourceShareEntryEffectivelySelected,
                isCurrentResource115Share,
                getResourceProviderLabel,
                getCurrentResourceProvider,
                isLinkTypeCookieConfigured,
                isProviderCookieConfigured,
                syncResourceShareReceiveCodeSection,
                renderResourceImportBehaviorHint,
                renderResourceImportSummary,
            };
        }

        function buildResourceShareRows(entries) {
            return window.ResourceBrowser?.buildResourceShareRows(getResourceBrowserContext(), entries) || '';
        }

        function renderResourceShareBrowser() {
            window.ResourceBrowser?.renderResourceShareBrowser(getResourceBrowserContext());
        }

        function normalizeResourceFolderTrail(trail = []) {
            const normalized = [{ id: '0', name: '根目录' }];
            (Array.isArray(trail) ? trail : []).forEach((item, index) => {
                if (index === 0) return;
                const id = String(item?.id || '').trim();
                const name = String(item?.name || '').trim();
                if (!id || !name) return;
                normalized.push({ id, name });
            });
            return normalized;
        }

        function buildResourceFolderDisplayPathFromTrail(trail = []) {
            return normalizeResourceFolderTrail(trail)
                .slice(1)
                .map(item => normalizeRelativePathInput(item?.name || ''))
                .filter(Boolean)
                .join('/');
        }

        function normalizeResourceRefreshDelaySeconds(value, fallback = 4) {
            const parsed = parseInt(String(value ?? '').trim(), 10);
            if (Number.isFinite(parsed) && parsed >= 0) return parsed;
            const fallbackParsed = parseInt(String(fallback ?? '').trim(), 10);
            if (Number.isFinite(fallbackParsed) && fallbackParsed >= 0) return fallbackParsed;
            return 4;
        }

        function getRememberedResourceRefreshDelaySeconds() {
            try {
                const raw = localStorage.getItem(RESOURCE_IMPORT_DELAY_MEMORY_KEY);
                return normalizeResourceRefreshDelaySeconds(raw, 4);
            } catch (e) {
                return 4;
            }
        }

        function rememberResourceRefreshDelaySeconds(value) {
            try {
                localStorage.setItem(
                    RESOURCE_IMPORT_DELAY_MEMORY_KEY,
                    String(normalizeResourceRefreshDelaySeconds(value, 4))
                );
            } catch (e) {}
        }

        function getRememberedResourceFolderSelection() {
            const fallback = {
                folder_id: '0',
                display_path: '',
                trail: [{ id: '0', name: '根目录' }]
            };
            try {
                const raw = localStorage.getItem(RESOURCE_FOLDER_MEMORY_KEY);
                if (!raw) return fallback;
                const data = JSON.parse(raw || '{}');
                const folderId = String(data?.folder_id || '').trim();
                let trail = normalizeResourceFolderTrail(data?.trail || []);
                let displayPath = normalizeRelativePathInput(data?.display_path || '');
                if (!displayPath) displayPath = buildResourceFolderDisplayPathFromTrail(trail);
                if (!folderId || folderId === '0' || !displayPath) return fallback;

                const currentTrailLastId = String(trail[trail.length - 1]?.id || '0').trim() || '0';
                if (currentTrailLastId !== folderId) {
                    const tailName = displayPath.split('/').filter(Boolean).pop() || '目录';
                    trail = normalizeResourceFolderTrail(trail.concat([{ id: folderId, name: tailName }]));
                }
                return {
                    folder_id: folderId,
                    display_path: displayPath,
                    trail
                };
            } catch (e) {
                return fallback;
            }
        }

        function rememberResourceFolderSelection(folderId, displayPath, trail = []) {
            const normalizedFolderId = String(folderId || '0').trim() || '0';
            const normalizedPath = normalizeRelativePathInput(displayPath || '');
            if (!normalizedPath || normalizedFolderId === '0') return;
            const normalizedTrail = normalizeResourceFolderTrail(trail);
            try {
                localStorage.setItem(RESOURCE_FOLDER_MEMORY_KEY, JSON.stringify({
                    folder_id: normalizedFolderId,
                    display_path: normalizedPath,
                    trail: normalizedTrail
                }));
            } catch (e) {}
        }

        function setSelectedResourceFolder(folderId, displayPath, { loadPreview = false, persist = true, trail = [] } = {}) {
            const resolvedTrail = normalizeResourceFolderTrail(Array.isArray(trail) && trail.length ? trail : resourceFolderTrail);
            const fallbackPath = buildResourceFolderDisplayPathFromTrail(resolvedTrail);
            const normalizedPath = normalizeRelativePathInput(displayPath || fallbackPath);
            const normalizedFolderId = String(folderId || '0').trim() || '0';
            document.getElementById('resource_job_folder_id').value = normalizedFolderId;
            document.getElementById('resource_job_folder_path').value = normalizedPath || '根目录';
            document.getElementById('resource_job_savepath').value = normalizedPath;
            syncResourceMonitorTaskOptions(normalizedPath);
            if (persist) rememberResourceFolderSelection(normalizedFolderId, normalizedPath, resolvedTrail);
            if (loadPreview) loadResourceTargetPreview(normalizedFolderId || '0');
        }

        async function resolveResourceFolderTrailByIds(trail = []) {
            const normalizedTrail = normalizeResourceFolderTrail(trail);
            if (normalizedTrail.length <= 1) {
                return { valid: true, trail: normalizedTrail };
            }

            const resolvedTrail = [{ id: '0', name: '根目录' }];
            let parentCid = '0';
            for (let i = 1; i < normalizedTrail.length; i += 1) {
                const expected = normalizedTrail[i] || {};
                const expectedId = String(expected.id || '').trim();
                if (!expectedId || expectedId === '0') break;
                const result = await fetchResourceFolderData(parentCid, {
                    provider: getCurrentResourceProvider(),
                    foldersOnly: true
                });
                const entries = Array.isArray(result.entries) ? result.entries : [];
                const matched = entries.find(entry => {
                    if (!entry?.is_dir) return false;
                    const entryId = String(entry?.id || entry?.cid || '').trim();
                    return entryId && entryId === expectedId;
                });
                if (!matched) {
                    return { valid: false, trail: resolvedTrail };
                }
                const matchedId = String(matched.id || matched.cid || '').trim() || expectedId;
                const matchedName = String(matched.name || expected.name || '目录').trim() || '目录';
                resolvedTrail.push({ id: matchedId, name: matchedName });
                parentCid = matchedId;
            }
            return { valid: true, trail: normalizeResourceFolderTrail(resolvedTrail) };
        }

        async function resolveResourceFolderTrailByPath(displayPath = '') {
            const normalizedPath = normalizeRelativePathInput(displayPath || '');
            if (!normalizedPath) {
                return { valid: true, trail: [{ id: '0', name: '根目录' }] };
            }

            const resolvedTrail = [{ id: '0', name: '根目录' }];
            let parentCid = '0';
            const parts = normalizedPath.split('/').filter(Boolean);
            for (const part of parts) {
                const result = await fetchResourceFolderData(parentCid, {
                    provider: getCurrentResourceProvider(),
                    foldersOnly: true
                });
                const entries = Array.isArray(result.entries) ? result.entries : [];
                const matched = entries.find(entry => !!entry?.is_dir && String(entry?.name || '').trim() === part);
                if (!matched) {
                    return { valid: false, trail: normalizeResourceFolderTrail(resolvedTrail) };
                }
                const matchedId = String(matched.id || matched.cid || '').trim();
                if (!matchedId) {
                    return { valid: false, trail: normalizeResourceFolderTrail(resolvedTrail) };
                }
                const matchedName = String(matched.name || part).trim() || part;
                resolvedTrail.push({ id: matchedId, name: matchedName });
                parentCid = matchedId;
            }
            return { valid: true, trail: normalizeResourceFolderTrail(resolvedTrail) };
        }

        async function ensureResourceFolderSelectionValid({ phase = 'submit' } = {}) {
            const provider = getCurrentResourceProvider();
            const providerLabel = getResourceProviderLabel(provider);
            if (!isProviderCookieConfigured(provider)) return true;
            if (resourceFolderValidationPromise) return resourceFolderValidationPromise;

            resourceFolderValidationPromise = (async () => {
                const currentTrail = normalizeResourceFolderTrail(resourceFolderTrail);
                const currentPath = normalizeRelativePathInput(document.getElementById('resource_job_savepath')?.value || '');
                if (currentTrail.length <= 1) return true;

                let resolved;
                try {
                    resolved = await resolveResourceFolderTrailByIds(currentTrail);
                    if (!resolved.valid && currentPath) {
                        resolved = await resolveResourceFolderTrailByPath(currentPath);
                    }
                } catch (e) {
                    const detail = e?.message || `读取${providerLabel}目录失败`;
                    showToast(`目录合法性检查失败：${detail}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                    return phase !== 'submit';
                }

                if (!resolved.valid) {
                    const rootTrail = [{ id: '0', name: '根目录' }];
                    resourceFolderTrail = rootTrail;
                    setSelectedResourceFolder('0', '', { loadPreview: false, persist: false, trail: rootTrail });
                    try {
                        localStorage.removeItem(RESOURCE_FOLDER_MEMORY_KEY);
                    } catch (e) {}
                    showToast('上次选择的目录已不存在，请重新选择保存目录', { tone: 'warn', duration: 3200, placement: 'top-center' });
                    return false;
                }

                const resolvedTrail = normalizeResourceFolderTrail(resolved.trail);
                const resolvedFolderId = String(resolvedTrail[resolvedTrail.length - 1]?.id || '0').trim() || '0';
                const resolvedPath = buildResourceFolderDisplayPathFromTrail(resolvedTrail);
                const currentFolderId = String(document.getElementById('resource_job_folder_id')?.value || '0').trim() || '0';
                const needsSync = currentFolderId !== resolvedFolderId || currentPath !== resolvedPath;
                resourceFolderTrail = resolvedTrail;
                if (needsSync) {
                    setSelectedResourceFolder(resolvedFolderId, resolvedPath, { loadPreview: false, trail: resolvedTrail });
                    if (phase === 'open') {
                        showToast(`已同步目录路径：${resolvedPath || '根目录'}`, { tone: 'info', duration: 2200, placement: 'top-center' });
                    }
                }
                return true;
            })();

            try {
                return await resourceFolderValidationPromise;
            } finally {
                resourceFolderValidationPromise = null;
            }
        }

        function renderResourceTargetPreview() {
            window.ResourceBrowser?.renderResourceTargetPreview(getResourceBrowserContext());
        }

        async function loadResourceTargetPreview(folderId = '0', { force = false } = {}) {
            const provider = getCurrentResourceProvider();
            const normalizedFolderId = String(folderId || '0').trim() || '0';
            if (!isProviderCookieConfigured(provider)) {
                resourceTargetPreviewEntries = [];
                resourceTargetPreviewSummary = { folder_count: 0, file_count: 0 };
                resourceTargetPreviewLoading = false;
                resourceTargetPreviewError = '';
                renderResourceTargetPreview();
                return;
            }
            if (!force && resourceTargetPreviewLoading) return;
            const cacheOptions = { provider, foldersOnly: false };
            const cachedBranch = force ? null : getResourceFolderBranchCache(normalizedFolderId, cacheOptions);
            if (cachedBranch) {
                resourceTargetPreviewEntries = Array.isArray(cachedBranch.entries) ? cachedBranch.entries : [];
                resourceTargetPreviewSummary = cachedBranch.summary || { folder_count: 0, file_count: 0 };
                resourceTargetPreviewLoading = false;
                resourceTargetPreviewError = '';
                renderResourceTargetPreview();
                return;
            }
            resourceTargetPreviewLoading = true;
            resourceTargetPreviewError = '';
            renderResourceTargetPreview();
            try {
                const result = await fetchResourceFolderData(normalizedFolderId, { provider, forceRefresh: force });
                resourceTargetPreviewEntries = result.entries;
                resourceTargetPreviewSummary = result.summary;
            } catch (e) {
                resourceTargetPreviewEntries = [];
                resourceTargetPreviewSummary = { folder_count: 0, file_count: 0 };
                resourceTargetPreviewError = e.message || '读取目录失败';
            } finally {
                resourceTargetPreviewLoading = false;
                renderResourceTargetPreview();
            }
        }

        Object.assign(window, {
            fetchResourceFolderData,
            createResourceFolder,
            invalidateResourceFolderBranchCache,
            getResourceFolderBranchCache,
            resetResourceShareState,
            isCurrentResource115Share,
            applyResourceShareReceiveCode,
            getResourceShareSelectionState,
            clearResourceShareSelection,
            setCurrentResourceShareEntriesChecked,
            loadResourceShareBranch,
            loadMoreResourceShareCurrentFolder,
            goResourceShareRoot,
            goResourceShareBack,
            openResourceShareFolder,
            openResourceShareTrail,
            getResourceBrowserContext,
            renderResourceShareBrowser,
            normalizeResourceFolderTrail,
            buildResourceFolderDisplayPathFromTrail,
            normalizeResourceRefreshDelaySeconds,
            getRememberedResourceRefreshDelaySeconds,
            rememberResourceRefreshDelaySeconds,
            getRememberedResourceFolderSelection,
            setSelectedResourceFolder,
            ensureResourceFolderSelectionValid,
            renderResourceTargetPreview,
            loadResourceTargetPreview,
        });
