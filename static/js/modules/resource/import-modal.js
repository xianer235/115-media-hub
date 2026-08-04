        function createEmptyResourceEd2kState(requestToken = 0) {
            return {
                active: false,
                loading: false,
                error: '',
                requestToken,
                sourceUrl: '',
                pageTitle: '',
                titleText: '',
                titleTokens: [],
                selectedTitleIndexes: [],
                titleExpanded: true,
                items: [],
                selectedItemIds: [],
                createFolder: true,
                folderName: '',
            };
        }

        function resetResourceEd2kState() {
            const nextToken = Number(resourceEd2kState?.requestToken || 0) + 1;
            resourceEd2kState = createEmptyResourceEd2kState(nextToken);
            resourceEd2kTitleGesture = null;
        }

        function isResourceEd2kImportCandidate(item) {
            const importMode = getResourceImportMode(item);
            return importMode === 'ed2k-direct' || importMode === 'ed2k-page';
        }

        function isResourceEd2kReady() {
            if (!isResourceEd2kImportActive() || resourceEd2kState.loading || resourceEd2kState.error) return false;
            if (!Array.isArray(resourceEd2kState.selectedItemIds) || !resourceEd2kState.selectedItemIds.length) return false;
            return resourceEd2kState.createFolder === false
                || !!window.ResourceEd2kImport?.normalizeFolderName(resourceEd2kState.folderName);
        }

        function formatResourceEd2kSize(value) {
            let size = Number(value || 0);
            if (!Number.isFinite(size) || size <= 0) return '--';
            const units = ['B', 'KB', 'MB', 'GB', 'TB'];
            let unitIndex = 0;
            while (size >= 1024 && unitIndex < units.length - 1) {
                size /= 1024;
                unitIndex += 1;
            }
            const digits = unitIndex >= 3 ? 2 : (unitIndex >= 1 ? 1 : 0);
            return `${size.toFixed(digits)} ${units[unitIndex]}`;
        }

        function applyResourceEd2kResolvedData(item, data) {
            const items = Array.isArray(data?.items) ? data.items.filter(entry => entry && entry.link_url) : [];
            const titleText = String(item?.title || data?.title || 'ED2K 资源').trim() || 'ED2K 资源';
            resourceEd2kState.loading = false;
            resourceEd2kState.error = '';
            resourceEd2kState.pageTitle = String(data?.title || '').trim();
            resourceEd2kState.titleText = titleText;
            resourceEd2kState.titleTokens = window.ResourceEd2kImport?.tokenizeTitle(titleText) || [];
            resourceEd2kState.selectedTitleIndexes = [];
            resourceEd2kState.titleExpanded = true;
            resourceEd2kState.items = items;
            resourceEd2kState.selectedItemIds = items.map(entry => String(entry.id || entry.link_url));
            resourceEd2kState.createFolder = true;
            resourceEd2kState.folderName = '';
            const folderNameInput = document.getElementById('resource-ed2k-folder-name');
            const createFolderInput = document.getElementById('resource-ed2k-create-folder');
            if (folderNameInput) folderNameInput.value = '';
            if (createFolderInput) createFolderInput.checked = true;
        }

        async function initializeResourceEd2kImport(item) {
            if (resourceModalMode !== 'import' || !isResourceEd2kImportCandidate(item)) return;
            resetResourceEd2kState();
            const requestToken = resourceEd2kState.requestToken;
            const linkUrl = String(item?.link_url || '').trim();
            resourceEd2kState.active = true;
            resourceEd2kState.loading = true;
            resourceEd2kState.sourceUrl = linkUrl;
            renderResourceModalLayout(item);
            try {
                const importMode = getResourceImportMode(item);
                const data = importMode === 'ed2k-direct'
                    ? {
                        title: String(item?.title || '').trim(),
                        source_url: linkUrl,
                        final_url: linkUrl,
                        items: [window.ResourceEd2kImport.parseEd2kLink(linkUrl)],
                    }
                    : await window.MediaHubApi.postJson('/resource/ed2k/resolve', {
                        url: linkUrl,
                        resource_title: String(item?.title || '').trim(),
                    });
                if (requestToken !== resourceEd2kState.requestToken || selectedResourceItem !== item) return;
                applyResourceEd2kResolvedData(item, data);
            } catch (error) {
                if (requestToken !== resourceEd2kState.requestToken || selectedResourceItem !== item) return;
                resourceEd2kState.loading = false;
                resourceEd2kState.error = String(error?.message || '资源外链解析失败').trim() || '资源外链解析失败';
            }
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceModalLayout(item);
        }

        function renderResourceEd2kTitleTokens() {
            const container = document.getElementById('resource-ed2k-title-tokens');
            if (!container) return;
            const selected = new Set(resourceEd2kState.selectedTitleIndexes || []);
            container.innerHTML = (resourceEd2kState.titleTokens || []).map((token, index) => `
                <button
                    type="button"
                    class="resource-ed2k-title-token ${selected.has(index) ? 'is-selected' : ''}"
                    data-ed2k-title-index="${index}"
                    role="option"
                    aria-selected="${selected.has(index) ? 'true' : 'false'}"
                    onpointerdown="beginResourceEd2kTitleSelection(event, ${index})"
                    onpointerenter="continueResourceEd2kTitleSelection(event, ${index})"
                >${escapeHtml(token.text)}</button>
            `).join('');
            const doneBtn = document.getElementById('resource-ed2k-title-done');
            if (doneBtn) doneBtn.disabled = !(resourceEd2kState.selectedTitleIndexes || []).length;
        }

        function syncResourceEd2kSubmitButton() {
            if (!isResourceEd2kImportActive()) return;
            const submitBtn = document.getElementById('resource-submit-btn');
            if (!submitBtn) return;
            const canSubmit = isLinkTypeCookieConfigured('ed2k') && isResourceEd2kReady() && !resourceSubmitBusy;
            submitBtn.disabled = !canSubmit;
            submitBtn.className = canSubmit
                ? 'resource-import-submit-btn'
                : 'resource-import-submit-btn resource-import-submit-btn-disabled';
            if (resourceSubmitBusy) {
                submitBtn.textContent = '正在创建保存任务...';
                return;
            }
            const selectedCount = Array.isArray(resourceEd2kState.selectedItemIds)
                ? resourceEd2kState.selectedItemIds.length
                : 0;
            submitBtn.textContent = resourceEd2kState.loading ? '正在解析资源外链...' : `保存 ${selectedCount} 个文件`;
        }

        function syncResourceEd2kFileSelectionControls() {
            const selectedIds = new Set(resourceEd2kState.selectedItemIds || []);
            document.querySelectorAll('#resource-ed2k-file-list [data-ed2k-file-index]').forEach(input => {
                const entry = resourceEd2kState.items?.[Number(input.dataset.ed2kFileIndex)];
                input.checked = !!entry && selectedIds.has(String(entry.id || entry.link_url));
            });
            const checkAll = document.getElementById('resource-ed2k-check-all');
            if (checkAll) {
                checkAll.checked = !!resourceEd2kState.items.length && selectedIds.size === resourceEd2kState.items.length;
                checkAll.indeterminate = selectedIds.size > 0 && selectedIds.size < resourceEd2kState.items.length;
            }
        }

        function syncResourceEd2kFolderControls() {
            const createFolderInput = document.getElementById('resource-ed2k-create-folder');
            const folderNameInput = document.getElementById('resource-ed2k-folder-name');
            const reselectBtn = document.querySelector('.resource-ed2k-reselect-btn');
            if (createFolderInput) createFolderInput.checked = resourceEd2kState.createFolder !== false;
            if (folderNameInput) {
                if (document.activeElement !== folderNameInput && folderNameInput.value !== resourceEd2kState.folderName) {
                    folderNameInput.value = resourceEd2kState.folderName || '';
                }
                folderNameInput.disabled = resourceEd2kState.createFolder === false;
            }
            if (reselectBtn) reselectBtn.disabled = resourceEd2kState.createFolder === false || !resourceEd2kState.titleTokens.length;
        }

        function renderResourceEd2kImport() {
            const card = document.getElementById('resource-ed2k-card');
            const folderSection = document.getElementById('resource-ed2k-folder-section');
            if (!card || !folderSection) return;
            const active = isResourceEd2kImportActive();
            card.classList.toggle('hidden', !active);
            folderSection.classList.toggle('hidden', !active);
            if (!active) return;

            const statusEl = document.getElementById('resource-ed2k-status');
            const titleSection = document.getElementById('resource-ed2k-title-section');
            const filesSection = document.getElementById('resource-ed2k-files-section');
            const ready = !resourceEd2kState.loading && !resourceEd2kState.error && resourceEd2kState.items.length > 0;
            const showTitleSelector = window.ResourceEd2kImport.shouldShowTitleSelector(
                active,
                ready,
                resourceEd2kState.createFolder !== false
            );
            statusEl.classList.toggle('hidden', ready);
            if (resourceEd2kState.loading) {
                statusEl.className = 'resource-ed2k-status is-loading';
                statusEl.textContent = '正在解析资源外链...';
            } else if (resourceEd2kState.error) {
                statusEl.className = 'resource-ed2k-status is-error';
                statusEl.innerHTML = `<span>${escapeHtml(resourceEd2kState.error)}</span><button type="button" onclick="retryResourceEd2kResolve()">重试</button>`;
            }
            titleSection.classList.toggle('hidden', !showTitleSelector);
            filesSection.classList.toggle('hidden', !ready);

            const titleSource = document.getElementById('resource-ed2k-title-source');
            const selector = document.getElementById('resource-ed2k-title-selector');
            const collapseBtn = document.getElementById('resource-ed2k-title-collapse');
            const doneBtn = document.getElementById('resource-ed2k-title-done');
            if (titleSource) titleSource.textContent = resourceEd2kState.titleText || resourceEd2kState.pageTitle || '--';
            if (selector) selector.classList.toggle('hidden', !resourceEd2kState.titleExpanded);
            if (collapseBtn) collapseBtn.textContent = resourceEd2kState.titleExpanded ? '收起' : '展开';
            if (doneBtn) doneBtn.disabled = !(resourceEd2kState.selectedTitleIndexes || []).length;
            renderResourceEd2kTitleTokens();

            const selectedIds = new Set(resourceEd2kState.selectedItemIds || []);
            const fileList = document.getElementById('resource-ed2k-file-list');
            if (fileList) {
                const previousScrollTop = fileList.scrollTop;
                fileList.innerHTML = resourceEd2kState.items.map((entry, index) => {
                    const identity = String(entry.id || entry.link_url);
                    return `
                        <label class="resource-ed2k-file-row">
                            <span class="resource-ed2k-file-main">
                                <input type="checkbox" class="ui-checkbox ui-checkbox-sm" data-ed2k-file-index="${index}" ${selectedIds.has(identity) ? 'checked' : ''} onchange="setResourceEd2kFileChecked(${index}, this.checked)">
                                <span class="resource-ed2k-file-name">${escapeHtml(entry.filename || entry.title || '未命名文件')}</span>
                            </span>
                            <span class="resource-ed2k-file-size">${escapeHtml(formatResourceEd2kSize(entry.size_bytes))}</span>
                        </label>
                    `;
                }).join('');
                fileList.scrollTop = previousScrollTop;
            }
            syncResourceEd2kFileSelectionControls();
            syncResourceEd2kFolderControls();
            syncResourceEd2kSubmitButton();
        }

        function beginResourceEd2kTitleSelection(event, index) {
            if (!isResourceEd2kImportActive()) return;
            event.preventDefault();
            const selected = resourceEd2kState.selectedTitleIndexes || [];
            resourceEd2kTitleGesture = {
                pointerId: event.pointerId,
                startIndex: index,
                baseSelection: selected.slice(),
                shouldSelect: !selected.includes(index),
            };
            resourceEd2kState.selectedTitleIndexes = window.ResourceEd2kImport.applySelectionRange(
                resourceEd2kTitleGesture.baseSelection,
                index,
                index,
                resourceEd2kTitleGesture.shouldSelect
            );
            renderResourceEd2kTitleTokens();
        }

        function continueResourceEd2kTitleSelection(event, index) {
            if (!resourceEd2kTitleGesture || resourceEd2kTitleGesture.pointerId !== event.pointerId) return;
            resourceEd2kState.selectedTitleIndexes = window.ResourceEd2kImport.applySelectionRange(
                resourceEd2kTitleGesture.baseSelection,
                resourceEd2kTitleGesture.startIndex,
                index,
                resourceEd2kTitleGesture.shouldSelect
            );
            renderResourceEd2kTitleTokens();
        }

        function clearResourceEd2kTitleSelection() {
            resourceEd2kState.selectedTitleIndexes = [];
            renderResourceEd2kImport();
        }

        function toggleResourceEd2kTitleSelector() {
            resourceEd2kState.titleExpanded = !resourceEd2kState.titleExpanded;
            renderResourceEd2kImport();
        }

        function completeResourceEd2kTitleSelection() {
            const folderName = window.ResourceEd2kImport.normalizeFolderName(
                window.ResourceEd2kImport.composeFolderName(
                    resourceEd2kState.titleTokens,
                    resourceEd2kState.selectedTitleIndexes
                )
            );
            if (!folderName) return showToast('请先选择文件夹标题文字', { tone: 'warn', duration: 2400, placement: 'top-center' });
            resourceEd2kState.folderName = folderName;
            resourceEd2kState.titleExpanded = false;
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceModalLayout(selectedResourceItem);
        }

        function reopenResourceEd2kTitleSelector() {
            resourceEd2kState.titleExpanded = true;
            renderResourceEd2kImport();
            document.getElementById('resource-ed2k-title-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        function updateResourceEd2kFolderName(value) {
            resourceEd2kState.folderName = String(value || '');
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            syncResourceEd2kSubmitButton();
        }

        function setResourceEd2kCreateFolder(checked) {
            resourceEd2kState.createFolder = !!checked;
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceEd2kImport();
        }

        function setResourceEd2kFileChecked(index, checked) {
            const entry = resourceEd2kState.items?.[Number(index)];
            if (!entry) return;
            const identity = String(entry.id || entry.link_url);
            const selected = new Set(resourceEd2kState.selectedItemIds || []);
            if (checked) selected.add(identity);
            else selected.delete(identity);
            resourceEd2kState.selectedItemIds = Array.from(selected);
            syncResourceEd2kFileSelectionControls();
            renderResourceImportBehaviorHint(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceImportSummary();
            syncResourceEd2kSubmitButton();
        }

        function setAllResourceEd2kFilesChecked(checked) {
            resourceEd2kState.selectedItemIds = checked
                ? resourceEd2kState.items.map(entry => String(entry.id || entry.link_url))
                : [];
            syncResourceEd2kFileSelectionControls();
            renderResourceImportBehaviorHint(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceImportSummary();
            syncResourceEd2kSubmitButton();
        }

        function retryResourceEd2kResolve() {
            if (selectedResourceItem) initializeResourceEd2kImport(selectedResourceItem);
        }

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
            const ed2kMode = importMode && (isResourceEd2kImportCandidate(item) || isResourceEd2kImportActive());
            const batchCount = batchMode ? getResourceBatchMagnetItems().length : 0;
            if (!titleEl || !detailGrid || !rawCard || !savePanel || !saveHintEl || !footer || !submitBtn || !closeBtn) return;

            const currentLinkType = getEffectiveResourceLinkType(item);
            const currentProvider = getResourceProviderForLinkType(currentLinkType);
            const currentProviderLabel = currentProvider ? getResourceProviderLabel(currentProvider) : '下载网盘';
            const currentProviderMeta = (window.providerMeta || []).find(m => m.name === currentProvider);
            const providerSupportsMonitor = !!currentProviderMeta?.supports_monitor;
            syncResourceProviderUI();
            renderResourceFavoriteDirs();

            titleEl.innerText = importMode
                ? (ed2kMode ? '保存 ED2K 资源' : (batchMode ? '批量导入资源' : '导入资源'))
                : '资源详情';
            detailGrid.className = importMode ? 'resource-import-layout' : 'grid grid-cols-1 gap-4';
            renderResourceImportStepper(item, importMode, resourceSubmitBusy);
            rawCard.classList.toggle('hidden', importMode);
            savePanel.classList.toggle('hidden', !importMode);
            closeBtn.innerText = importMode ? '取消' : '关闭';

            const canOpenImport = canOpenResourceImport(item);
            const canSubmitNow = ed2kMode
                ? (isLinkTypeCookieConfigured('ed2k') && isResourceEd2kReady())
                : canImportResource(item);
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
                submitBtn.innerText = ed2kMode
                    ? '正在创建保存任务...'
                    : (batchMode ? `批量提交中（${batchCount} 条）...` : '提交中...');
            } else if (importMode && ed2kMode) {
                const selectedCount = Array.isArray(resourceEd2kState.selectedItemIds)
                    ? resourceEd2kState.selectedItemIds.length
                    : 0;
                submitBtn.innerText = resourceEd2kState.loading ? '正在解析资源外链...' : `保存 ${selectedCount} 个文件`;
            } else if (importMode && batchMode) {
                submitBtn.innerText = `批量下载到 ${currentProviderLabel}（${batchCount} 条）`;
            } else {
                submitBtn.innerText = getResourceImportLabel(item);
            }

            if (!importMode) {
                renderResourceEd2kImport();
                saveHintEl.classList.add('hidden');
                saveHintEl.innerHTML = '';
                return;
            }

            const hints = [];
            if (!canOpenResourceImport(item)) {
                hints.push('当前资源没有可直接导入的 magnet 或已启用网盘分享链接。');
            } else {
                if (batchMode) {
                    hints.push(`已识别 ${batchCount} 条磁力链接，将按同一保存目录和延时设置依次导入。`);
                }
                if (!isLinkTypeCookieConfigured(currentLinkType)) {
                    hints.push(`还没有配置${currentProviderLabel}认证信息。你可以先查看并填写保存资源和保存目录，但真正提交前需要先补上认证信息。`);
                }
                if (!providerSupportsMonitor) {
                    hints.push(`${currentProviderLabel} 链路不会联动文件夹监控，也不会自动触发 strm 刷新。`);
                } else {
                    const taskCount = Array.isArray(resourceState.monitor_tasks) && resourceState.monitor_tasks.length
                        ? resourceState.monitor_tasks.length
                        : ((monitorState.tasks || []).length || 0);
                    if (!taskCount) {
                        hints.push(`当前还没有配置文件夹监控任务。保存到 ${currentProviderLabel} 仍然可用，但不会自动生成 strm。`);
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
            syncResourceProviderUI();
            renderResourceFavoriteDirs();
            renderResourceEd2kImport();
        }

        function openResourceItemModal(item, mode = 'detail') {
            if (!item) return;
            resetResourceEd2kState();
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
            if (resourceModalMode === 'import' && isResourceEd2kImportCandidate(item)) {
                initializeResourceEd2kImport(item);
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
            resetResourceEd2kState();
            setResourceBatchImportItems([]);
            resetResourceShareState();
            hideLockedModal('resource-import-modal');
        }

        function shouldConfirmDuplicateShareJob(error) {
            if (Number(error?.status || 0) !== 409) return false;
            const linkType = String(error?.payload?.link_type || resourceModalLinkType || '').trim().toLowerCase();
            if (!isResourceShareLinkType(linkType)) return false;
            return Boolean(error?.payload?.duplicate_confirm_required ?? true);
        }

        function acquireResourceSubmitLock() {
            if (resourceSubmitBusy) {
                showToast('正在提交中，请勿重复点击', { tone: 'info', duration: 2200, placement: 'top-center' });
                return 0;
            }
            resourceSubmitBusyToken += 1;
            resourceSubmitBusy = true;
            if (selectedResourceItem) renderResourceModalLayout(selectedResourceItem);
            return resourceSubmitBusyToken;
        }

        function releaseResourceSubmitLock(lockToken, { render = true } = {}) {
            if (!lockToken || lockToken !== resourceSubmitBusyToken) return false;
            resourceSubmitBusy = false;
            if (render && resourceModalMode === 'import' && selectedResourceItem) {
                renderResourceModalLayout(selectedResourceItem);
            }
            return true;
        }

        function refreshResourceJobsAfterSubmit() {
            Promise.resolve().then(async () => {
                if (typeof refreshResourceJobsOnly === 'function') {
                    await refreshResourceJobsOnly({ mode: 'window' });
                } else {
                    await refreshResourceState({ allowSearch: false, jobMode: 'window' });
                }
            }).catch(() => {});
        }

        async function createResourceJobWithDuplicateConfirm(payload, { providerLabel = '网盘' } = {}) {
            try {
                return await window.MediaHubApi.postJson('/resource/jobs/create', payload);
            } catch (error) {
                if (!shouldConfirmDuplicateShareJob(error)) throw error;
                const message = String(error?.message || error?.payload?.msg || '该链接在当前保存路径已有导入记录。').trim();
                const jobId = Number(error?.payload?.job_id || 0);
                const status = String(error?.payload?.status || '').trim();
                const detail = [
                    message,
                    jobId ? `已有任务：#${jobId}${status ? `（${status}）` : ''}` : '',
                    `如果你这次是从同一个${providerLabel}分享链接里选择不同文件，可以继续创建新任务。是否继续？`
                ].filter(Boolean).join('\n\n');
                if (!(await showAppConfirm(detail))) return { ok: false, cancelled: true };
                return window.MediaHubApi.postJson('/resource/jobs/create', {
                    ...payload,
                    allow_duplicate: true
                });
            }
        }

        async function submitResourceJob() {
            if (!selectedResourceItem) return showToast('未选择资源', { tone: 'warn', duration: 2400, placement: 'top-center' });
            const submitLockToken = acquireResourceSubmitLock();
            if (!submitLockToken) return;
            try {
                const batchMode = isResourceBatchImportMode();
                const batchItems = batchMode ? getResourceBatchMagnetItems() : [];
                const currentLinkType = getEffectiveResourceLinkType(selectedResourceItem);
                const currentProvider = getCurrentResourceProvider();
                const currentProviderLabel = currentProvider ? getResourceProviderLabel(currentProvider) : '下载网盘';
                const magnetProvider = currentLinkType === 'magnet' ? getResourceSelectedMagnetProvider() : getResourceDefaultMagnetProvider();
                const selectionState = getResourceShareSelectionState();
                const hasLoadedShareSelectableOption = Object.keys(resourceShareEntryIndex || {}).length > 0;
                if (!batchMode && isCurrentResource115Share() && resourceShareRootLoaded && !selectionState.selected_ids.length && hasLoadedShareSelectableOption) {
                    return showToast('请先至少勾选一个要转存的条目', { tone: 'warn', duration: 2800, placement: 'top-center' });
                }
                let receiveCode = '';
                if (!batchMode && isCurrentResource115Share()) {
                    const rawReceiveCode = String(document.getElementById('resource_share_receive_code')?.value || resourceShareReceiveCode || '').trim();
                    receiveCode = normalizeReceiveCodeInput(rawReceiveCode);
                    if (rawReceiveCode && !receiveCode) {
                        return showToast('提取码格式不正确，请输入 1-16 位字母或数字', { tone: 'warn', duration: 3000, placement: 'top-center' });
                    }
                    resourceShareReceiveCode = receiveCode;
                }
                const folderSelectionValid = await ensureResourceFolderSelectionValid({ phase: 'submit' });
                if (!folderSelectionValid) return;
                const savepath = normalizeRelativePathInput(document.getElementById('resource_job_savepath').value.trim());
                if (!savepath) {
                    return showToast(`请先选择一个非根目录的${currentProviderLabel}保存目录`, { tone: 'warn', duration: 3000, placement: 'top-center' });
                }
                const folderId = String(document.getElementById('resource_job_folder_id')?.value || '').trim();
                const refreshDelaySeconds = normalizeResourceRefreshDelaySeconds(
                    document.getElementById('resource_job_refresh_delay_seconds').value,
                    0
                );
                if (isResourceEd2kImportActive()) {
                    if (!isResourceEd2kReady()) {
                        const message = resourceEd2kState.error
                            ? '资源外链解析失败，请重试'
                            : (!resourceEd2kState.selectedItemIds.length ? '请至少选择一个 ED2K 文件' : '请填写新建文件夹名称');
                        showToast(message, { tone: 'warn', duration: 2800, placement: 'top-center' });
                        return;
                    }
                    const selectedIds = new Set(resourceEd2kState.selectedItemIds || []);
                    const selectedItems = resourceEd2kState.items.filter(entry => selectedIds.has(String(entry.id || entry.link_url)));
                    const folderName = resourceEd2kState.createFolder === false
                        ? ''
                        : window.ResourceEd2kImport.normalizeFolderName(resourceEd2kState.folderName);
                    resourceEd2kState.folderName = folderName;
                    const folderNameInput = document.getElementById('resource-ed2k-folder-name');
                    if (folderNameInput) folderNameInput.value = folderName;
                    syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
                    let data = {};
                    try {
                        data = await window.MediaHubApi.postJson('/resource/ed2k/jobs/create-batch', {
                            items: selectedItems.map(entry => ({ link_url: entry.link_url })),
                            parent_savepath: savepath,
                            parent_folder_id: folderId,
                            create_folder: resourceEd2kState.createFolder !== false,
                            folder_name: folderName,
                            refresh_delay_seconds: refreshDelaySeconds,
                            auto_refresh: !!((window.providerMeta || []).find(meta => meta.name === '115')?.supports_monitor),
                            source_url: resourceEd2kState.sourceUrl || selectedResourceItem?.link_url || '',
                            resource_title: String(selectedResourceItem?.title || '').trim(),
                            page_title: resourceEd2kState.pageTitle,
                        });
                    } catch (error) {
                        showToast(`提交失败：${error?.message || '网络请求失败'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
                        return;
                    }
                    if (!data?.ok) {
                        showToast(`提交失败：${data?.msg || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                        return;
                    }
                    rememberResourceRefreshDelaySeconds(refreshDelaySeconds);
                    closeResourceJobModal();
                    releaseResourceSubmitLock(submitLockToken, { render: false });
                    refreshResourceJobsAfterSubmit();
                    const taskCount = Number(data.item_count || selectedItems.length || 0);
                    const targetPath = String(data.savepath || '').trim();
                    const monitorTail = data.monitor_task_name
                        ? (data.auto_refresh ? `，保存后会自动触发“${data.monitor_task_name}”` : `，已匹配“${data.monitor_task_name}”`)
                        : '，当前目录不会自动生成 strm';
                    showToast(`已创建 ${taskCount} 个保存任务${targetPath ? `，目标：${targetPath}` : ''}${monitorTail}`, {
                        tone: 'success',
                        duration: 3800,
                        placement: 'top-center'
                    });
                    return;
                }
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
                            auto_refresh: !!((window.providerMeta || []).find(m => m.name === magnetProvider)?.supports_monitor),
                            magnet_provider: magnetProvider,
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
                    releaseResourceSubmitLock(submitLockToken, { render: false });
                    refreshResourceJobsAfterSubmit();

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
                    auto_refresh: !!((window.providerMeta || []).find(m => m.name === currentProvider)?.supports_monitor),
                    magnet_provider: magnetProvider
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
                    data = await createResourceJobWithDuplicateConfirm(payload, { providerLabel: currentProviderLabel });
                } catch (e) {
                    showToast(`提交失败：${e?.message || '网络请求失败'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                    return;
                }
                if (data?.cancelled) return;
                if (!data.ok) {
                    showToast(`提交失败：${data.msg || '请稍后重试'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
                    return;
                }
                rememberResourceRefreshDelaySeconds(refreshDelaySeconds);
                closeResourceJobModal();
                releaseResourceSubmitLock(submitLockToken, { render: false });
                refreshResourceJobsAfterSubmit();
                const matchedTaskName = String(data.monitor_task_name || '').trim();
                const providerSupportsMonitor = !!((window.providerMeta || []).find(m => m.name === currentProvider)?.supports_monitor);
                const tail = !providerSupportsMonitor
                    ? `，${currentProviderLabel} 链路不联动文件夹监控`
                    : (
                        matchedTaskName
                            ? (data.auto_refresh ? `，保存完成后会自动触发“${matchedTaskName}”` : `，已匹配“${matchedTaskName}”，可稍后手动触发刷新`)
                            : '，当前目录不会自动生成 strm'
                    );
                showToast(`已创建导入任务 #${data.job_id}${tail}`, { tone: 'success', duration: 3000, placement: 'top-center' });
            } finally {
                releaseResourceSubmitLock(submitLockToken);
            }
        }

        async function copyResourceRecord(resourceId) {
            const item = findResourceItem(resourceId) || (selectedResourceItem && Number(selectedResourceItem?.id || 0) === Number(resourceId || 0) ? selectedResourceItem : null);
            if (!item) return;
            const text = getResourceCopyText(item);
            if (!text) return showToast('这条资源没有可复制的内容', { tone: 'warn', duration: 2400, placement: 'top-center' });
            try {
                if (!navigator.clipboard?.writeText) throw new Error('当前浏览器不支持剪贴板接口');
                await navigator.clipboard.writeText(text);
                showToast('已复制到剪贴板', { tone: 'success', duration: 2200, placement: 'top-center' });
            } catch (e) {
                void showAppPrompt('复制失败，请手动复制下面的内容：', text);
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
            const providerLabel = provider ? getResourceProviderLabel(provider) : '下载网盘';
            if (!provider) {
                showToast('当前资源无法确定保存网盘，请重新打开导入窗口', { tone: 'warn', duration: 2800, placement: 'top-center' });
                return;
            }
            if (!isProviderCookieConfigured(provider)) {
                showToast(`请先在参数配置中填写${providerLabel}认证信息`, { tone: 'warn', duration: 2800, placement: 'top-center' });
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

        if (!window.__resourceEd2kPointerHandlersBound) {
            window.__resourceEd2kPointerHandlersBound = true;
            document.addEventListener('pointermove', (event) => {
                if (!resourceEd2kTitleGesture || resourceEd2kTitleGesture.pointerId !== event.pointerId) return;
                const target = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('[data-ed2k-title-index]');
                if (!target) return;
                continueResourceEd2kTitleSelection(event, Number(target.dataset.ed2kTitleIndex));
            }, { passive: true });
            const endGesture = (event) => {
                if (resourceEd2kTitleGesture && resourceEd2kTitleGesture.pointerId === event.pointerId) {
                    resourceEd2kTitleGesture = null;
                }
            };
            document.addEventListener('pointerup', endGesture, { passive: true });
            document.addEventListener('pointercancel', endGesture, { passive: true });
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
            beginResourceEd2kTitleSelection,
            clearResourceEd2kTitleSelection,
            completeResourceEd2kTitleSelection,
            continueResourceEd2kTitleSelection,
            reopenResourceEd2kTitleSelector,
            retryResourceEd2kResolve,
            setAllResourceEd2kFilesChecked,
            setResourceEd2kCreateFolder,
            setResourceEd2kFileChecked,
            toggleResourceEd2kTitleSelector,
            updateResourceEd2kFolderName,
        });
