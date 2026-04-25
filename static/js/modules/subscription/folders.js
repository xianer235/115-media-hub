        function renderSubscriptionFolderBreadcrumbs() {
            const container = document.getElementById('subscription-folder-breadcrumbs');
            if (!container) return;
            container.innerHTML = subscriptionFolderTrail.map((item, index) => {
                const isLast = index === subscriptionFolderTrail.length - 1;
                return `
                    ${index > 0 ? '<span class="resource-folder-sep">›</span>' : ''}
                    <button
                        type="button"
                        data-subscription-folder-action="trail"
                        data-subscription-folder-index="${index}"
                        class="resource-folder-crumb ${isLast ? 'resource-folder-crumb-active' : ''}"
                        ${isLast ? 'disabled' : ''}
                    >${escapeHtml(item?.name || '根目录')}</button>
                `;
            }).join('');
        }

        function setSubscriptionFolderCreateBusy(loading = false) {
            subscriptionFolderCreateBusy = !!loading;
            const createBtn = document.getElementById('subscription-folder-create-btn');
            const nameInput = document.getElementById('subscription-folder-create-name');
            if (createBtn) {
                createBtn.disabled = subscriptionFolderCreateBusy;
                createBtn.classList.toggle('btn-disabled', subscriptionFolderCreateBusy);
                createBtn.innerText = subscriptionFolderCreateBusy ? '新建中...' : '新建文件夹';
            }
            if (nameInput) nameInput.disabled = subscriptionFolderCreateBusy;
        }

        function renderSubscriptionFolderList() {
            const container = document.getElementById('subscription-folder-list');
            const summary = document.getElementById('subscription-folder-summary');
            const refreshBtn = document.getElementById('subscription-folder-refresh-btn');
            if (!container) return;
            const providerLabel = getResourceProviderLabel(getCurrentSubscriptionProvider());
            if (refreshBtn) {
                refreshBtn.disabled = subscriptionFolderLoading;
                refreshBtn.classList.toggle('btn-disabled', subscriptionFolderLoading);
                refreshBtn.innerText = subscriptionFolderLoading ? '刷新中...' : '刷新当前目录';
            }
            if (summary) {
                summary.innerText = `当前目录下共有 ${Number(subscriptionFolderSummary?.folder_count || 0)} 个文件夹 / ${Number(subscriptionFolderSummary?.file_count || 0)} 个文件。`;
            }
            if (subscriptionFolderLoading) {
                container.innerHTML = `<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在读取${escapeHtml(providerLabel)}目录...</div>`;
                return;
            }
            const folders = (subscriptionFolderEntries || []).filter(entry => !!entry?.is_dir);
            if (!folders.length) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前目录没有子文件夹，可以直接选择这里作为保存位置。</div>';
                return;
            }
            container.innerHTML = folders.map(entry => buildResourceEntryRow(entry, {
                showOpenButton: true,
                openActionPrefix: 'subscription-folder'
            })).join('');
        }

        async function loadSubscriptionFolders(cid = '0', { forceRefresh = false } = {}) {
            subscriptionFolderLoading = true;
            renderSubscriptionFolderBreadcrumbs();
            renderSubscriptionFolderList();
            try {
                const result = await fetchResourceFolderData(cid, {
                    provider: getCurrentSubscriptionProvider(),
                    foldersOnly: true,
                    forceRefresh: !!forceRefresh
                });
                subscriptionFolderEntries = result.entries;
                subscriptionFolderSummary = result.summary;
            } catch (e) {
                subscriptionFolderEntries = [];
                subscriptionFolderSummary = { folder_count: 0, file_count: 0 };
                showToast(`目录读取失败：${e.message || '请稍后重试'}`, { tone: 'error', duration: 3200 });
            } finally {
                subscriptionFolderLoading = false;
                renderSubscriptionFolderBreadcrumbs();
                renderSubscriptionFolderList();
            }
        }

        async function refreshCurrentSubscriptionFolder() {
            if (subscriptionFolderLoading) return;
            const currentCid = subscriptionFolderTrail[subscriptionFolderTrail.length - 1]?.id || '0';
            await loadSubscriptionFolders(currentCid, { forceRefresh: true });
            showToast('已刷新当前目录', { tone: 'success', duration: 2200, placement: 'top-center' });
        }

        async function openSubscriptionFolderModal() {
            const provider = getCurrentSubscriptionProvider();
            const providerLabel = getResourceProviderLabel(provider);
            if (!isProviderCookieConfigured(provider)) {
                showToast(`请先在参数配置中填写${providerLabel} Cookie`, { tone: 'warn', duration: 2800, placement: 'top-center' });
                return;
            }
            showLockedModal('subscription-folder-modal');
            const createInput = document.getElementById('subscription-folder-create-name');
            if (createInput) createInput.value = '';
            setSubscriptionFolderCreateBusy(false);
            renderSubscriptionFolderBreadcrumbs();
            await loadSubscriptionFolders(subscriptionFolderTrail[subscriptionFolderTrail.length - 1]?.id || '0');
        }

        function closeSubscriptionFolderModal() {
            hideLockedModal('subscription-folder-modal');
            setSubscriptionFolderCreateBusy(false);
        }

        async function goSubscriptionFolderBack() {
            if (subscriptionFolderTrail.length <= 1) return;
            subscriptionFolderTrail = subscriptionFolderTrail.slice(0, -1);
            await loadSubscriptionFolders(subscriptionFolderTrail[subscriptionFolderTrail.length - 1]?.id || '0');
        }

        async function openSubscriptionFolderTrail(index) {
            const targetIndex = Math.max(0, Math.min(Number(index || 0), subscriptionFolderTrail.length - 1));
            subscriptionFolderTrail = subscriptionFolderTrail.slice(0, targetIndex + 1);
            await loadSubscriptionFolders(subscriptionFolderTrail[subscriptionFolderTrail.length - 1]?.id || '0');
        }

        async function openSubscriptionFolderChild(folderId, folderName) {
            subscriptionFolderTrail = subscriptionFolderTrail.concat([{ id: String(folderId || '0'), name: String(folderName || '--') }]);
            await loadSubscriptionFolders(folderId);
        }

        async function createSubscriptionFolderInCurrent() {
            if (subscriptionFolderLoading || subscriptionFolderCreateBusy) return;
            const nameInput = document.getElementById('subscription-folder-create-name');
            const folderName = String(nameInput?.value || '').trim();
            if (!folderName) {
                showToast('请输入新文件夹名称', { tone: 'warn', duration: 2200, placement: 'top-center' });
                return;
            }

            const current = subscriptionFolderTrail[subscriptionFolderTrail.length - 1] || { id: '0', name: '根目录' };
            const currentCid = String(current.id || '0').trim() || '0';
            try {
                setSubscriptionFolderCreateBusy(true);
                const result = await createResourceFolder(currentCid, folderName, { provider: getCurrentSubscriptionProvider() });
                const folder = result.folder || {};
                const createdFolderId = String(folder.id || '').trim();
                const createdFolderName = String(folder.name || folderName).trim() || folderName;
                if (nameInput) nameInput.value = '';

                invalidateResourceFolderBranchCache(getCurrentSubscriptionProvider());
                await loadSubscriptionFolders(currentCid);
                if (createdFolderId) {
                    const selectedTrail = normalizeResourceFolderTrail(subscriptionFolderTrail.concat([{ id: createdFolderId, name: createdFolderName }]));
                    subscriptionFolderTrail = selectedTrail;
                    await loadSubscriptionFolders(createdFolderId);
                    setSubscriptionSavepath(
                        createdFolderId,
                        buildResourceFolderDisplayPathFromTrail(selectedTrail),
                        { trail: selectedTrail }
                    );
                }
                showToast(`已创建并进入文件夹：${createdFolderName}`, { tone: 'success', duration: 3000, placement: 'top-center' });
            } catch (e) {
                showToast(`新建文件夹失败：${e.message || '请稍后重试'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
            } finally {
                setSubscriptionFolderCreateBusy(false);
            }
        }

        function selectCurrentSubscriptionFolder() {
            const current = subscriptionFolderTrail[subscriptionFolderTrail.length - 1] || { id: '0', name: '根目录' };
            const displayPath = subscriptionFolderTrail.slice(1).map(item => item.name).join('/');
            setSubscriptionSavepath(current.id || '0', displayPath, { trail: subscriptionFolderTrail });
            closeSubscriptionFolderModal();
        }

        function setSubscriptionShareSubdirSelection(path = '', cid = '') {
            const normalizedPath = normalizeRelativePathInput(path || '');
            const normalizedCid = normalizedPath ? normalizeShareCidInput(cid || '') : '';
            const subdirInput = document.getElementById('subscription_share_subdir');
            if (subdirInput) subdirInput.value = normalizedPath;
            const cidInput = document.getElementById('subscription_share_subdir_cid');
            if (cidInput) cidInput.value = normalizedCid;
        }

        function resetSubscriptionShareFolderBrowser() {
            subscriptionShareFolderTrail = [{ cid: '0', name: '分享根目录' }];
            subscriptionShareFolderEntriesByParent = { '0': [] };
            subscriptionShareFolderCurrentCid = '0';
            subscriptionShareFolderLoading = false;
            subscriptionShareFolderLoadingParents = {};
            subscriptionShareFolderLoadingMoreParents = {};
            subscriptionShareFolderNextOffsetByParent = { '0': 0 };
            subscriptionShareFolderHasMoreByParent = {};
            subscriptionShareFolderError = '';
            subscriptionShareFolderInfo = { title: '', count: 0, share_code: '', receive_code: '' };
            subscriptionShareFolderRootLoaded = false;
            subscriptionShareFolderRequestToken = 0;
            subscriptionShareFolderLinkFingerprint = '';
        }

        function getSubscriptionShareLinkPayload() {
            if (getCurrentSubscriptionProvider() !== '115') {
                throw new Error('当前网盘提供方不是 115，固定分享链接模式不可用');
            }
            const linkInput = document.getElementById('subscription_share_link_url');
            const receiveInput = document.getElementById('subscription_share_receive_code');
            const linkUrl = String(linkInput?.value || '').trim();
            const linkType = detectResourceLinkTypeByUrl(linkUrl);
            if (!linkUrl) throw new Error('请先填写固定 115 分享链接');
            if (linkType !== '115share') throw new Error('仅支持 115 分享链接');
            const rawReceiveCode = String(receiveInput?.value || '').trim();
            let receiveCode = normalizeReceiveCodeInput(rawReceiveCode);
            if (rawReceiveCode && !receiveCode) throw new Error('提取码格式不正确，请输入 1-16 位字母或数字');
            if (!receiveCode) receiveCode = extractReceiveCodeFromShareUrl(linkUrl);
            if (receiveInput) receiveInput.value = receiveCode;
            if (linkInput) linkInput.value = linkUrl;
            return {
                link_url: linkUrl,
                raw_text: linkUrl,
                receive_code: receiveCode,
            };
        }

        async function fetchSubscriptionShareFolderData(
            cid = '0',
            {
                offset = 0,
                limit = RESOURCE_SHARE_BROWSE_PAGE_LIMIT,
                paged = true
            } = {}
        ) {
            const payload = getSubscriptionShareLinkPayload();
            const normalizedOffset = Math.max(0, Number(offset || 0));
            const normalizedLimit = Math.max(20, Math.min(Number(limit || RESOURCE_SHARE_BROWSE_PAGE_LIMIT), 400));
            const normalizedCid = String(cid || '0').trim() || '0';
            const requestKey = [
                payload.link_url,
                payload.receive_code || '-',
                normalizedCid,
                normalizedOffset,
                normalizedLimit,
                paged ? '1' : '0'
            ].join('|');
            const inFlight = subscriptionShareFolderFetchInFlight[requestKey];
            if (inFlight) {
                return cloneJsonValue(await inFlight, {
                    entries: [],
                    summary: { folder_count: 0, file_count: 0 },
                    share: { title: '', share_code: '', receive_code: '', count: 0 },
                    paging: { offset: normalizedOffset, next_offset: normalizedOffset, has_more: false }
                });
            }
            const requestPromise = (async () => {
                const data = await fetchResourceBrowserJson('/resource/115/share_entries_preview', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        cid: normalizedCid,
                        link_url: payload.link_url,
                        raw_text: payload.raw_text,
                        receive_code: payload.receive_code,
                        paged: !!paged,
                        offset: normalizedOffset,
                        limit: normalizedLimit,
                    }),
                });
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
            })();
            subscriptionShareFolderFetchInFlight[requestKey] = requestPromise;
            try {
                return cloneJsonValue(await requestPromise, {
                    entries: [],
                    summary: { folder_count: 0, file_count: 0 },
                    share: { title: '', share_code: '', receive_code: '', count: 0 },
                    paging: { offset: normalizedOffset, next_offset: normalizedOffset, has_more: false }
                });
            } finally {
                if (subscriptionShareFolderFetchInFlight[requestKey] === requestPromise) {
                    delete subscriptionShareFolderFetchInFlight[requestKey];
                }
            }
        }

        function renderSubscriptionShareFolderBreadcrumbs() {
            const container = document.getElementById('subscription-share-folder-breadcrumbs');
            if (!container) return;
            container.innerHTML = subscriptionShareFolderTrail.map((item, index) => {
                const isLast = index === subscriptionShareFolderTrail.length - 1;
                return `
                    ${index > 0 ? '<span class="resource-folder-sep">›</span>' : ''}
                    <button
                        type="button"
                        data-subscription-share-folder-action="trail"
                        data-subscription-share-folder-index="${index}"
                        class="resource-folder-crumb ${isLast ? 'resource-folder-crumb-active' : ''}"
                        ${isLast ? 'disabled' : ''}
                    >${escapeHtml(item?.name || '分享根目录')}</button>
                `;
            }).join('');
        }

        function getCurrentSubscriptionShareFolderEntries() {
            return Array.isArray(subscriptionShareFolderEntriesByParent?.[subscriptionShareFolderCurrentCid])
                ? subscriptionShareFolderEntriesByParent[subscriptionShareFolderCurrentCid]
                : [];
        }

        function renderSubscriptionShareFolderList() {
            const container = document.getElementById('subscription-share-folder-list');
            const summary = document.getElementById('subscription-share-folder-summary');
            if (!container) return;
            const currentEntries = getCurrentSubscriptionShareFolderEntries();
            const currentFolderLoading = !!subscriptionShareFolderLoadingParents[subscriptionShareFolderCurrentCid];
            const currentFolderLoadingMore = !!subscriptionShareFolderLoadingMoreParents[subscriptionShareFolderCurrentCid];
            const currentFolderHasMore = !!subscriptionShareFolderHasMoreByParent[subscriptionShareFolderCurrentCid];
            if (summary) {
                const rootTitle = String(subscriptionShareFolderInfo?.title || '').trim();
                const folderCount = Number(currentEntries.filter(entry => !!entry?.is_dir).length);
                const fileCount = Math.max(0, Number(currentEntries.length) - folderCount);
                const counts = subscriptionShareFolderRootLoaded
                    ? `当前目录已加载 ${folderCount} 个子文件夹 / ${fileCount} 个文件。`
                    : '先填写固定分享链接，再浏览并选择链接中的目标子目录。';
                summary.innerText = rootTitle
                    ? `分享标题：${rootTitle}。${counts}`
                    : counts;
            }
            if (subscriptionShareFolderLoading || currentFolderLoading) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在读取分享目录...</div>';
                return;
            }
            if (subscriptionShareFolderError) {
                container.innerHTML = `<div class="rounded-2xl border border-dashed border-red-500/40 p-6 text-center text-red-300 text-sm">${escapeHtml(subscriptionShareFolderError)}</div>`;
                return;
            }
            if (!subscriptionShareFolderRootLoaded) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">点击“浏览链接目录”后，这里会显示分享内当前层级的目录和文件。</div>';
                return;
            }
            if (!currentEntries.length) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前目录没有可用条目，可以直接选择这里。</div>';
                return;
            }
            const loadMoreHtml = currentFolderHasMore
                ? `
                    <div class="resource-browser-load-more-row">
                        <button
                            type="button"
                            data-subscription-share-folder-action="load-more"
                            class="resource-browser-load-more-btn ${currentFolderLoadingMore ? 'btn-disabled' : ''}"
                            ${currentFolderLoadingMore ? 'disabled' : ''}
                        >${currentFolderLoadingMore ? '加载中...' : '加载更多条目'}</button>
                    </div>
                `
                : '';
            container.innerHTML = `${currentEntries.map(entry => buildResourceEntryRow(entry, {
                showOpenButton: true,
                openActionPrefix: 'subscription-share-folder',
            })).join('')}${loadMoreHtml}`;
        }

        async function loadSubscriptionShareFolderBranch(
            cid = '0',
            {
                append = false,
                forceRefresh = false
            } = {}
        ) {
            const normalizedCid = String(cid || '0').trim() || '0';
            const appendMode = !!append;
            const forceMode = !!forceRefresh;
            const hasCachedBranch = Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, normalizedCid);
            if (!appendMode && hasCachedBranch && !forceMode) {
                subscriptionShareFolderError = '';
                renderSubscriptionShareFolderBreadcrumbs();
                renderSubscriptionShareFolderList();
                return;
            }
            if (!appendMode) {
                subscriptionShareFolderError = '';
                if (normalizedCid === '0') subscriptionShareFolderLoading = true;
            }
            if (appendMode) subscriptionShareFolderLoadingMoreParents[normalizedCid] = true;
            else subscriptionShareFolderLoadingParents[normalizedCid] = true;
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
            const requestToken = ++subscriptionShareFolderRequestToken;
            try {
                const requestOffset = appendMode
                    ? Math.max(0, Number(subscriptionShareFolderNextOffsetByParent[normalizedCid] || 0))
                    : 0;
                if (!appendMode && forceMode) {
                    subscriptionShareFolderEntriesByParent[normalizedCid] = [];
                    subscriptionShareFolderNextOffsetByParent[normalizedCid] = 0;
                    subscriptionShareFolderHasMoreByParent[normalizedCid] = false;
                }
                const result = await fetchSubscriptionShareFolderData(normalizedCid, {
                    offset: requestOffset,
                    limit: RESOURCE_SHARE_BROWSE_PAGE_LIMIT,
                    paged: true,
                });
                if (requestToken !== subscriptionShareFolderRequestToken) return;
                const incomingEntries = Array.isArray(result.entries) ? result.entries : [];
                const existingEntries = Array.isArray(subscriptionShareFolderEntriesByParent?.[normalizedCid]) ? subscriptionShareFolderEntriesByParent[normalizedCid] : [];
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
                subscriptionShareFolderEntriesByParent[normalizedCid] = mergedEntries;
                const nextOffset = Math.max(
                    requestOffset + incomingEntries.length,
                    Number(result?.paging?.next_offset ?? (requestOffset + incomingEntries.length)) || (requestOffset + incomingEntries.length)
                );
                subscriptionShareFolderNextOffsetByParent[normalizedCid] = nextOffset;
                subscriptionShareFolderHasMoreByParent[normalizedCid] = !!result?.paging?.has_more;
                subscriptionShareFolderInfo = result.share;
                subscriptionShareFolderRootLoaded = true;
                subscriptionShareFolderError = '';
            } catch (e) {
                if (requestToken !== subscriptionShareFolderRequestToken) return;
                if (!appendMode) subscriptionShareFolderEntriesByParent[normalizedCid] = [];
                subscriptionShareFolderError = e?.message || '读取分享目录失败';
                subscriptionShareFolderRootLoaded = false;
            } finally {
                if (requestToken !== subscriptionShareFolderRequestToken) return;
                if (appendMode) delete subscriptionShareFolderLoadingMoreParents[normalizedCid];
                else delete subscriptionShareFolderLoadingParents[normalizedCid];
                if (!appendMode && normalizedCid === '0') subscriptionShareFolderLoading = false;
                renderSubscriptionShareFolderBreadcrumbs();
                renderSubscriptionShareFolderList();
            }
        }

        async function loadMoreSubscriptionShareCurrentFolder() {
            const branchId = String(subscriptionShareFolderCurrentCid || '0').trim() || '0';
            if (!subscriptionShareFolderHasMoreByParent[branchId]) return;
            if (subscriptionShareFolderLoadingMoreParents[branchId]) return;
            await loadSubscriptionShareFolderBranch(branchId, { append: true });
        }

        async function openSubscriptionShareFolderModal() {
            if (getCurrentSubscriptionProvider() !== '115') {
                showToast('Quark 模式不支持固定分享链接目录浏览', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            let payload;
            try {
                payload = getSubscriptionShareLinkPayload();
            } catch (e) {
                showToast(e?.message || '请先填写固定 115 分享链接', { tone: 'warn', duration: 2800, placement: 'top-center' });
                return;
            }
            const fingerprint = `${payload.link_url}#${payload.receive_code || ''}`;
            if (!subscriptionShareFolderLinkFingerprint || subscriptionShareFolderLinkFingerprint !== fingerprint) {
                resetSubscriptionShareFolderBrowser();
                subscriptionShareFolderLinkFingerprint = fingerprint;
            }
            showLockedModal('subscription-share-folder-modal');
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
            const targetCid = String(subscriptionShareFolderCurrentCid || '0').trim() || '0';
            const hasBranchCache = Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, targetCid);
            const shouldForceRefresh = !hasBranchCache || (targetCid === '0' && !subscriptionShareFolderRootLoaded);
            await loadSubscriptionShareFolderBranch(targetCid, { forceRefresh: shouldForceRefresh });
        }

        function closeSubscriptionShareFolderModal() {
            hideLockedModal('subscription-share-folder-modal');
        }

        async function goSubscriptionShareFolderBack() {
            if (subscriptionShareFolderTrail.length <= 1) return;
            subscriptionShareFolderTrail = subscriptionShareFolderTrail.slice(0, -1);
            subscriptionShareFolderCurrentCid = String(subscriptionShareFolderTrail[subscriptionShareFolderTrail.length - 1]?.cid || '0');
            const branchId = String(subscriptionShareFolderCurrentCid || '0').trim() || '0';
            if (!Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, branchId)) {
                await loadSubscriptionShareFolderBranch(branchId);
                return;
            }
            subscriptionShareFolderError = '';
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
        }

        async function goSubscriptionShareFolderRoot() {
            subscriptionShareFolderTrail = [{ cid: '0', name: '分享根目录' }];
            subscriptionShareFolderCurrentCid = '0';
            if (!Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, '0') || !subscriptionShareFolderRootLoaded) {
                await loadSubscriptionShareFolderBranch('0');
                return;
            }
            subscriptionShareFolderError = '';
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
        }

        async function openSubscriptionShareFolderTrail(index) {
            const targetIndex = Math.max(0, Math.min(Number(index || 0), subscriptionShareFolderTrail.length - 1));
            subscriptionShareFolderTrail = subscriptionShareFolderTrail.slice(0, targetIndex + 1);
            subscriptionShareFolderCurrentCid = String(subscriptionShareFolderTrail[targetIndex]?.cid || '0');
            const branchId = String(subscriptionShareFolderCurrentCid || '0').trim() || '0';
            if (!Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, branchId)) {
                await loadSubscriptionShareFolderBranch(branchId);
                return;
            }
            subscriptionShareFolderError = '';
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
        }

        async function openSubscriptionShareFolderChild(folderId, folderName) {
            const nextCid = String(folderId || '0').trim() || '0';
            subscriptionShareFolderCurrentCid = nextCid;
            subscriptionShareFolderTrail = subscriptionShareFolderTrail.concat([{ cid: nextCid, name: String(folderName || '--') }]);
            if (!Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, nextCid)) {
                await loadSubscriptionShareFolderBranch(nextCid);
                return;
            }
            subscriptionShareFolderError = '';
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
        }

        function selectCurrentSubscriptionShareFolder() {
            const current = subscriptionShareFolderTrail[subscriptionShareFolderTrail.length - 1] || { cid: '0', name: '分享根目录' };
            const subdir = normalizeRelativePathInput(subscriptionShareFolderTrail.slice(1).map(item => item.name).join('/'));
            const subdirCid = subdir ? normalizeShareCidInput(current?.cid || '') : '';
            setSubscriptionShareSubdirSelection(subdir, subdirCid);
            closeSubscriptionShareFolderModal();
            showToast(
                subdir
                    ? `已选择分享子目录：${subdir}${subdirCid ? `（CID ${subdirCid}）` : ''}`
                    : '已选择分享根目录（留空）',
                { tone: 'success', duration: 2600, placement: 'top-center' }
            );
        }
