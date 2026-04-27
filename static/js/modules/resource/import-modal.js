        function buildResourceImportLinkActions(item) {
            const actions = [];
            const messageUrl = String(item?.message_url || '').trim();
            const linkUrl = String(item?.link_url || '').trim();
            if (messageUrl) {
                actions.push(`<a href="${escapeHtml(messageUrl)}" target="_blank" rel="noopener noreferrer" class="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-[11px] font-bold border border-slate-700">在 TG 中打开</a>`);
            }
            if (linkUrl && !/^magnet:\?/i.test(linkUrl)) {
                actions.push(`<a href="${escapeHtml(linkUrl)}" target="_blank" rel="noopener noreferrer" class="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-[11px] font-bold border border-slate-700">资源链接</a>`);
            }
            if (linkUrl) {
                actions.push(`<button type="button" onclick="copyResourceRecord(${Number(item?.id || 0)})" class="px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-[11px] font-bold">复制链接</button>`);
            }
            if (Number(item?.id || 0)) {
                actions.push(`<button type="button" onclick="openSubscriptionFromResource(${Number(item?.id || 0)})" class="px-3 py-2 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 text-[11px] font-bold border border-amber-500/35">转订阅任务</button>`);
            }
            if (!actions.length) {
                actions.push('<span class="text-[11px] text-slate-400">暂无外部链接</span>');
            }
            return actions.join('');
        }

        function renderResourceModalLayout(item) {
            const titleEl = document.getElementById('resource-import-modal-title');
            const detailGrid = document.getElementById('resource-import-detail-grid');
            const rawCard = document.getElementById('resource-import-raw-card');
            const savePanel = document.getElementById('resource-import-save-panel');
            const saveHintEl = document.getElementById('resource-import-save-hint');
            const footer = document.getElementById('resource-import-footer');
            const submitBtn = document.getElementById('resource-submit-btn');
            const closeBtn = document.getElementById('resource-close-btn');
            const importMode = resourceModalMode === 'import';
            const batchMode = importMode && isResourceBatchImportMode();
            const batchCount = batchMode ? getResourceBatchMagnetItems().length : 0;
            if (!titleEl || !detailGrid || !rawCard || !savePanel || !saveHintEl || !footer || !submitBtn || !closeBtn) return;
            syncResourceProviderUI();

            titleEl.innerText = importMode ? (batchMode ? '批量导入资源' : '导入资源') : '资源详情';
            detailGrid.className = importMode ? 'resource-import-layout' : 'grid grid-cols-1 gap-4';
            renderResourceImportStepper(item, importMode, resourceSubmitBusy);
            rawCard.classList.toggle('hidden', importMode);
            savePanel.classList.toggle('hidden', !importMode);
            closeBtn.innerText = importMode ? '取消' : '关闭';

            const canOpenImport = canOpenResourceImport(item);
            const canSubmitNow = canImportResource(item);
            const canSubmit = canSubmitNow && !resourceSubmitBusy;
            const showPrimaryAction = importMode ? true : canOpenImport;
            footer.className = showPrimaryAction
                ? 'resource-import-footer-shell grid grid-cols-1 md:grid-cols-2 gap-3 pt-2'
                : 'resource-import-footer-shell grid grid-cols-1 gap-3 pt-2';
            submitBtn.classList.toggle('hidden', !showPrimaryAction);
            submitBtn.onclick = importMode
                ? submitResourceJob
                : (() => openResourceImportModal(item?.id));
            if (importMode) {
                submitBtn.disabled = !canSubmit;
                submitBtn.className = canSubmit
                    ? 'resource-import-submit-btn'
                    : 'resource-import-submit-btn resource-import-submit-btn-disabled';
            } else {
                submitBtn.disabled = !canOpenImport;
                submitBtn.className = canOpenImport
                    ? 'resource-import-submit-btn'
                    : 'resource-import-submit-btn resource-import-submit-btn-disabled';
            }
            if (importMode && resourceSubmitBusy) {
                submitBtn.innerText = batchMode ? `批量提交中（${batchCount} 条）...` : '提交中...';
            } else if (importMode && batchMode) {
                submitBtn.innerText = `批量下载到 115（${batchCount} 条）`;
            } else {
                submitBtn.innerText = getResourceImportLabel(item);
            }

            if (!importMode) {
                saveHintEl.classList.add('hidden');
                saveHintEl.innerHTML = '';
                return;
            }

            const hints = [];
            const currentLinkType = getEffectiveResourceLinkType(item);
            const currentProvider = getResourceProviderByLinkType(currentLinkType);
            const currentProviderLabel = getResourceProviderLabel(currentProvider);
            if (!canOpenResourceImport(item)) {
                hints.push('当前资源没有可直接导入的 magnet / 115 / quark 分享链接。');
            } else {
                if (batchMode) {
                    hints.push(`已识别 ${batchCount} 条磁力链接，将按同一保存目录和延时设置依次导入。`);
                }
                if (!isLinkTypeCookieConfigured(currentLinkType)) {
                    hints.push(`还没有配置${currentProviderLabel} Cookie。你可以先查看并填写保存资源和保存目录，但真正提交前需要先补上 Cookie。`);
                }
                if (currentProvider === 'quark') {
                    hints.push('夸克链路不会联动监控任务，也不会自动触发 strm 刷新。');
                } else {
                    const taskCount = Array.isArray(resourceState.monitor_tasks) && resourceState.monitor_tasks.length
                        ? resourceState.monitor_tasks.length
                        : ((monitorState.tasks || []).length || 0);
                    if (!taskCount) {
                        hints.push('当前还没有配置文件夹监控任务。保存到 115 仍然可用，但不会自动生成 strm。');
                    }
                }
            }
            if (hints.length) {
                saveHintEl.classList.remove('hidden');
                saveHintEl.innerHTML = hints.map(line => `<div>${escapeHtml(line)}</div>`).join('');
            } else {
                saveHintEl.classList.add('hidden');
                saveHintEl.innerHTML = '';
            }

            renderResourceImportSummary();
        }

        function openResourceItemModal(item, mode = 'detail') {
            if (!item) return;
            selectedResourceId = Number(item?.id || 0);
            selectedResourceItem = item;
            resourceModalMode = mode === 'import' ? 'import' : 'detail';
            resourceModalLinkType = getEffectiveResourceLinkType(item);
            document.getElementById('resource-import-poster').innerHTML = buildResourcePoster(item);
            document.getElementById('resource-import-title').innerText = item.title || '未命名资源';
            document.getElementById('resource-import-subtitle').innerText = `来源：${item.source_name || item.channel_name || '手动录入'} / 时间：${item.published_at ? formatTimeText(item.published_at) : formatTimeText(item.created_at)}`;
            document.getElementById('resource-import-meta').innerHTML = [
                buildResourceStatusBadge(getResourceDisplayStatus(item)),
                item?.quality ? `<span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/20">${escapeHtml(item.quality)}</span>` : '',
                item?.year ? `<span class="text-[10px] px-3 py-1 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/20">${escapeHtml(item.year)}</span>` : ''
            ].filter(Boolean).join('');
            document.getElementById('resource-import-link-actions').innerHTML = buildResourceImportLinkActions(item);
            document.getElementById('resource-import-raw-text').textContent = String(item.raw_text || item.title || '暂无可预览内容').trim();
            const rememberedFolder = getRememberedResourceFolderSelection();
            resourceFolderTrail = normalizeResourceFolderTrail(rememberedFolder.trail);
            resourceFolderEntries = [];
            resourceFolderSummary = { folder_count: 0, file_count: 0 };
            resourceFolderFilesLoading = false;
            resourceFolderEntriesComplete = false;
            resourceFolderShowAllFiles = false;
            resourceTargetPreviewEntries = [];
            resourceTargetPreviewSummary = { folder_count: 0, file_count: 0 };
            resourceTargetPreviewLoading = false;
            resourceTargetPreviewError = '';
            resetResourceShareState();
            resourceShareReceiveCode = normalizeReceiveCodeInput(
                item?.receive_code
                || item?.extra?.receive_code
                || extractReceiveCodeFromShareUrl(item?.link_url || '')
                || extractReceiveCodeFromText(item?.raw_text || '')
            );
            const shareCacheRestored = (
                resourceModalMode === 'import'
                && isCurrentResource115Share()
                && isLinkTypeCookieConfigured(resourceModalLinkType)
                && restoreResourceShareBranchCache(selectedResourceId, item, resourceShareReceiveCode)
            );
            setSelectedResourceFolder(
                rememberedFolder.folder_id || '0',
                rememberedFolder.display_path || '',
                {
                    loadPreview: resourceModalMode === 'import',
                    persist: false,
                    trail: resourceFolderTrail
                }
            );
            document.getElementById('resource_job_refresh_delay_seconds').value = String(getRememberedResourceRefreshDelaySeconds());
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceModalLayout(item);
            renderResourceShareBrowser();
            renderResourceImportSummary();
            showLockedModal('resource-import-modal');
            if (shareCacheRestored) {
                syncResourceSharetitleFromSelection();
                renderResourceShareBrowser();
            } else if (resourceModalMode === 'import' && isCurrentResource115Share() && isLinkTypeCookieConfigured(resourceModalLinkType)) {
                loadResourceShareBranch(selectedResourceId, '0', { resetSelection: true });
            }
        }

        function openResourceModal(resourceId, mode = 'detail') {
            const item = findResourceItem(resourceId);
            if (!item) return;
            setResourceBatchImportItems([]);
            openResourceItemModal(item, mode);
        }

        function openResourceDetailModal(resourceId) {
            openResourceModal(resourceId, 'detail');
        }

        function openResourceImportModal(resourceId) {
            openResourceModal(resourceId, 'import');
        }

        function closeResourceJobModal() {
            closeResourceFolderModal();
            selectedResourceId = null;
            selectedResourceItem = null;
            resourceModalMode = 'detail';
            resourceModalLinkType = '';
            setResourceBatchImportItems([]);
            resetResourceShareState();
            hideLockedModal('resource-import-modal');
        }

        async function submitResourceJob() {
            if (resourceSubmitBusy) {
                showToast('正在提交中，请勿重复点击', { tone: 'info', duration: 2200, placement: 'top-center' });
                return;
            }
            if (!selectedResourceItem) return alert('未选择资源');
            resourceSubmitBusy = true;
            renderResourceModalLayout(selectedResourceItem);
            try {
                const batchMode = isResourceBatchImportMode();
                const batchItems = batchMode ? getResourceBatchMagnetItems() : [];
                const currentProvider = getCurrentResourceProvider();
                const currentProviderLabel = getResourceProviderLabel(currentProvider);
                const selectionState = getResourceShareSelectionState();
                const hasLoadedShareSelectableOption = Object.keys(resourceShareEntryIndex || {}).length > 0;
                if (!batchMode && isCurrentResource115Share() && resourceShareRootLoaded && !selectionState.selected_ids.length && hasLoadedShareSelectableOption) {
                    return alert('请先至少勾选一个要转存的条目');
                }
                let receiveCode = '';
                if (!batchMode && isCurrentResource115Share()) {
                    const rawReceiveCode = String(document.getElementById('resource_share_receive_code')?.value || resourceShareReceiveCode || '').trim();
                    receiveCode = normalizeReceiveCodeInput(rawReceiveCode);
                    if (rawReceiveCode && !receiveCode) {
                        return alert('提取码格式不正确，请输入 1-16 位字母或数字');
                    }
                    resourceShareReceiveCode = receiveCode;
                }
                const folderSelectionValid = await ensureResourceFolderSelectionValid({ phase: 'submit' });
                if (!folderSelectionValid) return;
                const savepath = normalizeRelativePathInput(document.getElementById('resource_job_savepath').value.trim());
                if (!savepath) {
                    return alert(`请先选择一个非根目录的${currentProviderLabel}保存目录`);
                }
                const folderId = String(document.getElementById('resource_job_folder_id')?.value || '').trim();
                const refreshDelaySeconds = normalizeResourceRefreshDelaySeconds(
                    document.getElementById('resource_job_refresh_delay_seconds').value,
                    0
                );
                if (batchMode) {
                    if (!batchItems.length) {
                        showToast('批量导入队列为空，请重新粘贴磁力链接后再试', { tone: 'warn', duration: 3200, placement: 'top-center' });
                        return;
                    }
                    const createdJobIds = [];
                    let duplicatedCount = 0;
                    let failedCount = 0;
                    let firstFailedMsg = '';
                    let matchedTaskName = '';
                    let autoRefreshMatched = false;

                    for (const batchItem of batchItems) {
                        const payload = {
                            savepath,
                            refresh_delay_seconds: refreshDelaySeconds,
                            auto_refresh: true,
                            resource: serializeTransientResourceForJob(batchItem)
                        };
                        if (folderId && folderId !== '0') payload.folder_id = folderId;
                        let data = {};
                        try {
                            data = await window.MediaHubApi.postJson('/resource/jobs/create', payload);
                        } catch (e) {
                            if (Number(e?.status || 0) === 409) {
                                duplicatedCount += 1;
                                continue;
                            }
                            failedCount += 1;
                            if (!firstFailedMsg) {
                                firstFailedMsg = String(e?.message || '网络请求失败').trim() || '请稍后重试';
                            }
                            continue;
                        }
                        if (data?.ok) {
                            createdJobIds.push(Number(data.job_id || 0));
                            const currentTaskName = String(data.monitor_task_name || '').trim();
                            if (!matchedTaskName && currentTaskName) matchedTaskName = currentTaskName;
                            if (currentTaskName && data.auto_refresh) autoRefreshMatched = true;
                            continue;
                        }
                        failedCount += 1;
                        if (!firstFailedMsg) {
                            firstFailedMsg = String(data.msg || '创建任务失败').trim() || '请稍后重试';
                        }
                    }

                    if (!createdJobIds.length && duplicatedCount <= 0 && failedCount > 0) {
                        showToast(`批量导入失败：${firstFailedMsg || '请稍后重试'}`, {
                            tone: 'error',
                            duration: 3800,
                            placement: 'top-center'
                        });
                        return;
                    }

                    rememberResourceRefreshDelaySeconds(refreshDelaySeconds);
                    closeResourceJobModal();
                    await refreshResourceState();

                    const summaryParts = [];
                    if (createdJobIds.length) summaryParts.push(`已创建 ${createdJobIds.length} 条任务`);
                    if (duplicatedCount > 0) summaryParts.push(`跳过 ${duplicatedCount} 条重复任务`);
                    if (failedCount > 0) summaryParts.push(`失败 ${failedCount} 条`);
                    if (createdJobIds.length) {
                        if (matchedTaskName) {
                            summaryParts.push(
                                autoRefreshMatched
                                    ? `保存完成后会自动触发“${matchedTaskName}”`
                                    : `已匹配“${matchedTaskName}”，可稍后手动触发刷新`
                            );
                        } else {
                            summaryParts.push('当前目录不会自动生成 strm');
                        }
                    }
                    const summaryText = summaryParts.join('，');
                    const tone = failedCount > 0 ? (createdJobIds.length > 0 || duplicatedCount > 0 ? 'warn' : 'error') : 'success';
                    showToast(summaryText || '批量导入已处理完成', {
                        tone,
                        duration: failedCount > 0 ? 5200 : 3600,
                        placement: 'top-center'
                    });
                    if (failedCount > 0 && firstFailedMsg) {
                        showToast(`失败原因示例：${firstFailedMsg}`, {
                            tone: 'error',
                            duration: 4200,
                            placement: 'top-center'
                        });
                    }
                    return;
                }

                const payload = {
                    savepath,
                    refresh_delay_seconds: refreshDelaySeconds,
                    auto_refresh: currentProvider !== 'quark'
                };
                if (folderId && folderId !== '0') payload.folder_id = folderId;
                if (Number(selectedResourceId || 0) > 0) payload.resource_id = selectedResourceId;
                else payload.resource = serializeTransientResourceForJob(selectedResourceItem);
                if (isCurrentResource115Share()) {
                    payload.share_selection = selectionState;
                    if (receiveCode) payload.receive_code = receiveCode;
                }
                let data = {};
                try {
                    data = await window.MediaHubApi.postJson('/resource/jobs/create', payload);
                } catch (e) {
                    showToast(`提交失败：${e?.message || '网络请求失败'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                    return;
                }
                if (!data.ok) {
                    showToast(`提交失败：${data.msg || '请稍后重试'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
                    return;
                }
                rememberResourceRefreshDelaySeconds(refreshDelaySeconds);
                closeResourceJobModal();
                await refreshResourceState();
                const matchedTaskName = String(data.monitor_task_name || '').trim();
                const tail = currentProvider === 'quark'
                    ? '，夸克链路不联动文件夹监控'
                    : (
                        matchedTaskName
                            ? (data.auto_refresh ? `，保存完成后会自动触发“${matchedTaskName}”` : `，已匹配“${matchedTaskName}”，可稍后手动触发刷新`)
                            : '，当前目录不会自动生成 strm'
                    );
                showToast(`已创建导入任务 #${data.job_id}${tail}`, { tone: 'success', duration: 3000, placement: 'top-center' });
            } finally {
                resourceSubmitBusy = false;
                if (resourceModalMode === 'import' && selectedResourceItem) {
                    renderResourceModalLayout(selectedResourceItem);
                }
            }
        }

        async function copyResourceRecord(resourceId) {
            const item = findResourceItem(resourceId) || (selectedResourceItem && Number(selectedResourceItem?.id || 0) === Number(resourceId || 0) ? selectedResourceItem : null);
            if (!item) return;
            const text = getResourceCopyText(item);
            if (!text) return alert('这条资源没有可复制的内容');
            try {
                if (!navigator.clipboard?.writeText) throw new Error('当前浏览器不支持剪贴板接口');
                await navigator.clipboard.writeText(text);
                alert('✅ 已复制到剪贴板');
            } catch (e) {
                window.prompt('复制失败，请手动复制下面的内容：', text);
            }
        }

        function renderResourceFolderList() {
            window.ResourceBrowser?.renderResourceFolderList(getResourceBrowserContext());
        }

        function setResourceFolderCreateBusy(loading = false) {
            resourceFolderCreateBusy = !!loading;
            const createBtn = document.getElementById('resource-folder-create-btn');
            const nameInput = document.getElementById('resource-folder-create-name');
            if (createBtn) {
                createBtn.disabled = resourceFolderCreateBusy;
                createBtn.classList.toggle('btn-disabled', resourceFolderCreateBusy);
                createBtn.innerText = resourceFolderCreateBusy ? '新建中...' : '新建文件夹';
            }
            if (nameInput) nameInput.disabled = resourceFolderCreateBusy;
        }

        function renderResourceFolderBreadcrumbs() {
            window.ResourceBrowser?.renderResourceFolderBreadcrumbs(getResourceBrowserContext());
        }

        async function loadResourceFolderFiles(cid = '0', { forceRefresh = false, requestToken = 0, silent = false } = {}) {
            const targetCid = String(cid || '0').trim() || '0';
            const provider = getCurrentResourceProvider();
            const cacheOptions = { provider, foldersOnly: false };
            const cachedBranch = forceRefresh ? null : getResourceFolderBranchCache(targetCid, cacheOptions);
            if (cachedBranch) {
                if (requestToken && requestToken !== resourceFolderRequestToken) return;
                resourceFolderEntries = Array.isArray(cachedBranch.entries) ? cachedBranch.entries : [];
                resourceFolderSummary = cachedBranch.summary || { folder_count: 0, file_count: 0 };
                resourceFolderEntriesComplete = cachedBranch.entries_complete !== false;
                resourceFolderFilesLoading = false;
                renderResourceFolderList();
                return;
            }
            resourceFolderFilesLoading = true;
            renderResourceFolderList();
            try {
                const result = await fetchResourceFolderData(targetCid, { provider, forceRefresh });
                if (requestToken && requestToken !== resourceFolderRequestToken) return;
                resourceFolderEntries = Array.isArray(result.entries) ? result.entries : [];
                resourceFolderSummary = result.summary || { folder_count: 0, file_count: 0 };
                resourceFolderEntriesComplete = result.entries_complete !== false;
            } catch (e) {
                if (requestToken && requestToken !== resourceFolderRequestToken) return;
                if (!silent) {
                    showToast(`文件列表刷新失败：${e.message || '请稍后重试'}`, { tone: 'warn', duration: 3200 });
                }
            } finally {
                if (requestToken && requestToken !== resourceFolderRequestToken) return;
                resourceFolderFilesLoading = false;
                renderResourceFolderList();
            }
        }

        async function loadResourceFolders(cid = '0', { forceRefresh = false } = {}) {
            const targetCid = String(cid || '0').trim() || '0';
            const provider = getCurrentResourceProvider();
            const fullCacheOptions = { provider, foldersOnly: false };
            const foldersOnlyCacheOptions = { provider, foldersOnly: true };
            const cachedBranch = forceRefresh ? null : getResourceFolderBranchCache(targetCid, fullCacheOptions);
            const cachedFoldersOnlyBranch = (forceRefresh || cachedBranch)
                ? null
                : getResourceFolderBranchCache(targetCid, foldersOnlyCacheOptions);
            const requestToken = ++resourceFolderRequestToken;
            resourceFolderShowAllFiles = false;

            if (cachedBranch) {
                resourceFolderEntries = Array.isArray(cachedBranch.entries) ? cachedBranch.entries : [];
                resourceFolderSummary = cachedBranch.summary || { folder_count: 0, file_count: 0 };
                resourceFolderEntriesComplete = cachedBranch.entries_complete !== false;
                resourceFolderLoading = false;
                resourceFolderFilesLoading = false;
                renderResourceFolderBreadcrumbs();
                renderResourceFolderList();
                return true;
            }

            if (cachedFoldersOnlyBranch) {
                resourceFolderEntries = Array.isArray(cachedFoldersOnlyBranch.entries) ? cachedFoldersOnlyBranch.entries : [];
                resourceFolderSummary = cachedFoldersOnlyBranch.summary || { folder_count: 0, file_count: 0 };
                resourceFolderEntriesComplete = cachedFoldersOnlyBranch.entries_complete !== false;
                resourceFolderLoading = false;
                resourceFolderFilesLoading = !resourceFolderEntriesComplete;
            } else {
                resourceFolderEntries = [];
                resourceFolderSummary = { folder_count: 0, file_count: 0 };
                resourceFolderEntriesComplete = false;
                resourceFolderLoading = true;
                resourceFolderFilesLoading = false;
            }
            renderResourceFolderBreadcrumbs();
            renderResourceFolderList();

            try {
                const result = cachedFoldersOnlyBranch
                    ? cachedFoldersOnlyBranch
                    : await fetchResourceFolderData(targetCid, { ...foldersOnlyCacheOptions, forceRefresh });
                if (requestToken !== resourceFolderRequestToken) return;
                resourceFolderEntries = Array.isArray(result.entries) ? result.entries : [];
                resourceFolderSummary = result.summary || { folder_count: 0, file_count: 0 };
                resourceFolderEntriesComplete = result.entries_complete !== false;
                return true;
            } catch (e) {
                if (requestToken !== resourceFolderRequestToken) return;
                resourceFolderEntries = [];
                resourceFolderSummary = { folder_count: 0, file_count: 0 };
                resourceFolderEntriesComplete = false;
                showToast(`目录读取失败：${e.message || '请稍后重试'}`, { tone: 'error', duration: 3200 });
                return false;
            } finally {
                if (requestToken !== resourceFolderRequestToken) return;
                resourceFolderLoading = false;
                resourceFolderFilesLoading = false;
                renderResourceFolderBreadcrumbs();
                renderResourceFolderList();
            }
        }

        async function refreshCurrentResourceFolder() {
            if (resourceFolderLoading || resourceFolderFilesLoading) return;
            const currentCid = resourceFolderTrail[resourceFolderTrail.length - 1]?.id || '0';
            const refreshed = await loadResourceFolders(currentCid, { forceRefresh: true });
            if (refreshed) {
                showToast('已刷新当前目录', { tone: 'success', duration: 2200, placement: 'top-center' });
            }
        }

        async function createResourceFolderInCurrent() {
            if (resourceFolderLoading || resourceFolderCreateBusy) return;
            const nameInput = document.getElementById('resource-folder-create-name');
            const folderName = String(nameInput?.value || '').trim();
            if (!folderName) {
                showToast('请输入新文件夹名称', { tone: 'warn', duration: 2200, placement: 'top-center' });
                return;
            }

            const current = resourceFolderTrail[resourceFolderTrail.length - 1] || { id: '0', name: '根目录' };
            const currentCid = String(current.id || '0').trim() || '0';
            try {
                setResourceFolderCreateBusy(true);
                const result = await createResourceFolder(currentCid, folderName, { provider: getCurrentResourceProvider() });
                const folder = result.folder || {};
                const createdFolderId = String(folder.id || '').trim();
                const createdFolderName = String(folder.name || folderName).trim() || folderName;
                if (nameInput) nameInput.value = '';

                invalidateResourceFolderBranchCache(getCurrentResourceProvider());
                await loadResourceFolders(currentCid);

                if (createdFolderId) {
                    const selectedTrail = normalizeResourceFolderTrail(resourceFolderTrail.concat([{ id: createdFolderId, name: createdFolderName }]));
                    resourceFolderTrail = selectedTrail;
                    await loadResourceFolders(createdFolderId);
                    setSelectedResourceFolder(
                        createdFolderId,
                        buildResourceFolderDisplayPathFromTrail(selectedTrail),
                        { loadPreview: true, trail: selectedTrail }
                    );
                }
                showToast(`已创建并进入文件夹：${createdFolderName}`, { tone: 'success', duration: 3000, placement: 'top-center' });
            } catch (e) {
                showToast(`新建文件夹失败：${e.message || '请稍后重试'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
            } finally {
                setResourceFolderCreateBusy(false);
            }
        }

        async function openResourceFolderModal() {
            syncResourceProviderUI();
            const provider = getCurrentResourceProvider();
            const providerLabel = getResourceProviderLabel(provider);
            if (!isProviderCookieConfigured(provider)) {
                showToast(`请先在参数配置中填写${providerLabel} Cookie`, { tone: 'warn', duration: 2800, placement: 'top-center' });
                return;
            }
            showLockedModal('resource-folder-modal');
            const createInput = document.getElementById('resource-folder-create-name');
            if (createInput) createInput.value = '';
            setResourceFolderCreateBusy(false);
            renderResourceFolderBreadcrumbs();
            await loadResourceFolders(resourceFolderTrail[resourceFolderTrail.length - 1]?.id || '0');
        }

        function closeResourceFolderModal() {
            hideLockedModal('resource-folder-modal');
            setResourceFolderCreateBusy(false);
        }

        async function goResourceFolderBack() {
            if (resourceFolderTrail.length <= 1) return;
            resourceFolderTrail = resourceFolderTrail.slice(0, -1);
            await loadResourceFolders(resourceFolderTrail[resourceFolderTrail.length - 1]?.id || '0');
        }

        async function openResourceFolderTrail(index) {
            const targetIndex = Math.max(0, Math.min(Number(index || 0), resourceFolderTrail.length - 1));
            resourceFolderTrail = resourceFolderTrail.slice(0, targetIndex + 1);
            await loadResourceFolders(resourceFolderTrail[resourceFolderTrail.length - 1]?.id || '0');
        }

        async function openResourceFolderChild(folderId, folderName) {
            resourceFolderTrail = resourceFolderTrail.concat([{ id: String(folderId || '0'), name: String(folderName || '--') }]);
            await loadResourceFolders(folderId);
        }

        function selectCurrentResourceFolder() {
            const current = resourceFolderTrail[resourceFolderTrail.length - 1] || { id: '0', name: '根目录' };
            const displayPath = resourceFolderTrail.slice(1).map(item => item.name).join('/');
            setSelectedResourceFolder(current.id || '0', displayPath, { trail: resourceFolderTrail });
            closeResourceFolderModal();
        }

        Object.assign(window, {
            openResourceModal,
            openResourceDetailModal,
            openResourceImportModal,
            closeResourceJobModal,
            submitResourceJob,
            copyResourceRecord,
            renderResourceFolderList,
            loadResourceFolderFiles,
            refreshCurrentResourceFolder,
            openResourceFolderModal,
            closeResourceFolderModal,
            goResourceFolderBack,
            openResourceFolderTrail,
            openResourceFolderChild,
            createResourceFolderInCurrent,
            selectCurrentResourceFolder,
        });
