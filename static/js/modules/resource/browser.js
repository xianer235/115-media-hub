(function (global) {
    function buildResourceShareRows(ctx, entries) {
        return (Array.isArray(entries) ? entries : []).map(entry => {
            const normalized = ctx.buildResourceShareSelectableEntry(entry);
            const directSelected = !!ctx.resourceShareSelected[normalized.id];
            const coveredByAncestor = !directSelected ? ctx.getResourceShareCoveredAncestor(normalized) : null;
            const effectiveSelected = directSelected || !!coveredByAncestor;
            const noteText = coveredByAncestor
                ? `已由上级目录“${coveredByAncestor.name}”一并选择`
                : '';
            return `
                <div class="resource-browser-row">
                    <div class="resource-browser-name-cell">
                        <input
                            type="checkbox"
                            data-resource-share-check="1"
                            data-resource-share-id="${ctx.escapeHtml(normalized.id)}"
                            class="ui-checkbox ui-checkbox-sm"
                            ${effectiveSelected ? 'checked' : ''}
                            ${coveredByAncestor ? 'disabled' : ''}
                        >
                        <div class="resource-browser-entry-main">
                            <span class="${normalized.is_dir ? 'resource-browser-folder-icon' : 'resource-browser-file-icon'}">${ctx.getResourceIconSvg(normalized.is_dir ? 'folder' : 'file')}</span>
                            <div class="min-w-0">
                                ${normalized.is_dir
                                    ? `<button type="button" data-resource-share-action="enter" data-resource-share-id="${ctx.escapeHtml(normalized.id)}" class="resource-browser-link resource-browser-entry-name">${ctx.escapeHtml(normalized.name || '--')}</button>`
                                    : `<div class="resource-browser-entry-name">${ctx.escapeHtml(normalized.name || '--')}</div>`
                                }
                                ${noteText ? `<div class="resource-browser-entry-sub">${ctx.escapeHtml(noteText)}</div>` : ''}
                            </div>
                        </div>
                    </div>
                    <div class="resource-browser-col-size">${normalized.is_dir ? '--' : ctx.escapeHtml(ctx.formatFileSizeText(entry?.size || 0))}</div>
                </div>
            `;
        }).join('');
    }

    function renderResourceShareBrowser(ctx) {
        const card = document.getElementById('resource-share-browser-card');
        const treeEl = document.getElementById('resource-share-tree');
        const rootTitleEl = document.getElementById('resource-share-root-title');
        const timingEl = document.getElementById('resource-share-stage-timing');
        const searchInputEl = document.getElementById('resource-share-search-input');
        const currentCheckAllEl = document.getElementById('resource-share-current-check-all');
        const selectedCountEl = document.getElementById('resource-share-selected-count');
        if (!card || !treeEl || !rootTitleEl) return;
        const formatTimingMs = (value) => {
            const ms = Math.max(0, Math.round(Number(value || 0)));
            if (ms >= 10000) return `${(ms / 1000).toFixed(1)}s`;
            if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
            return `${ms}ms`;
        };

        const importMode = ctx.resourceModalMode === 'import';
        const isShare = ctx.isCurrentResource115Share();
        const providerLabel = ctx.getResourceProviderLabel(ctx.getCurrentResourceProvider());
        const selectionState = typeof window.getResourceShareSelectionState === 'function'
            ? window.getResourceShareSelectionState()
            : { selected_entries: [] };
        const selectedCount = Array.isArray(selectionState.selected_entries) ? selectionState.selected_entries.length : 0;
        const selectedLabel = selectedCount > 0 ? `已选 ${selectedCount} 项` : '未选择';
        card.classList.toggle('hidden', !importMode);
        if (selectedCountEl) {
            selectedCountEl.classList.toggle('hidden', !importMode || !isShare);
            selectedCountEl.textContent = selectedLabel;
        }
        ctx.syncResourceShareReceiveCodeSection();
        if (!importMode) {
            ctx.renderResourceImportBehaviorHint();
            ctx.renderResourceImportSummary();
            return;
        }

        if (!isShare) {
            rootTitleEl.innerHTML = '<span class="text-slate-400">当前路径</span><span class="resource-browser-sep">/</span><span class="resource-browser-crumb resource-browser-crumb-active">当前资源不支持浏览分享目录</span>';
            treeEl.innerHTML = '<div class="resource-browser-empty">当前链接不支持浏览分享目录。</div>';
            if (currentCheckAllEl) {
                currentCheckAllEl.checked = false;
                currentCheckAllEl.indeterminate = false;
                currentCheckAllEl.disabled = true;
            }
            ctx.renderResourceImportBehaviorHint();
            ctx.renderResourceImportSummary();
            return;
        }

        const currentEntries = ctx.getCurrentResourceShareEntries();
        const filteredEntries = ctx.getFilteredCurrentResourceShareEntries();
        const searchKeyword = String(ctx.resourceShareSearchKeyword || '').trim();
        const currentFolderLoading = !!ctx.resourceShareLoadingParents[ctx.resourceShareCurrentCid];
        const currentFolderLoadingMore = !!ctx.resourceShareLoadingMoreParents[ctx.resourceShareCurrentCid];
        const currentFolderHasMore = !!ctx.resourceShareHasMoreByParent[ctx.resourceShareCurrentCid];
        const breadcrumbHtml = [
            '<span class="text-slate-400">当前路径</span>',
            '<span class="resource-browser-sep">/</span>',
            ctx.resourceShareTrail.length
                ? '<button type="button" onclick="goResourceShareRoot()" class="resource-browser-crumb">根目录</button>'
                : '<span class="resource-browser-crumb resource-browser-crumb-active">根目录</span>',
            ...ctx.resourceShareTrail.map((item, index) => {
                const label = ctx.escapeHtml(item?.name || '分享根目录');
                const sep = '<span class="resource-browser-sep">/</span>';
                if (index === ctx.resourceShareTrail.length - 1) {
                    return `${sep}<span class="resource-browser-crumb resource-browser-crumb-active">${label}</span>`;
                }
                return `${sep}<button type="button" data-resource-share-action="trail" data-resource-share-index="${index}" class="resource-browser-crumb">${label}</button>`;
            })
        ].join(' ');
        rootTitleEl.innerHTML = breadcrumbHtml;
        if (searchInputEl && searchInputEl.value !== searchKeyword) searchInputEl.value = searchKeyword;

        if (timingEl) {
            const diagnostics = ctx.resourceShareDiagnosticsByParent?.[ctx.resourceShareCurrentCid] || {};
            const totalMs = Number(diagnostics?.elapsed_ms || 0);
            const clientMs = Number(diagnostics?.client_elapsed_ms || 0);
            const overheadMs = Number(diagnostics?.client_overhead_ms || 0);
            const backendQueueMs = Number(diagnostics?.backend_queue_ms || 0);
            const timings = Array.isArray(diagnostics?.timings) ? diagnostics.timings : [];
            if (clientMs > 0 || totalMs > 0 || timings.length) {
                const cacheText = diagnostics?.cache_derived ? ' · 缓存' : '';
                const summaryParts = [];
                if (clientMs > 0) summaryParts.push(`总 ${ctx.escapeHtml(formatTimingMs(clientMs))}`);
                if (backendQueueMs > 20) summaryParts.push(`排队 ${ctx.escapeHtml(formatTimingMs(backendQueueMs))}`);
                if (totalMs > 0) summaryParts.push(`解析 ${ctx.escapeHtml(formatTimingMs(totalMs))}`);
                if (overheadMs > 20) summaryParts.push(`传输 ${ctx.escapeHtml(formatTimingMs(overheadMs))}`);
                timingEl.classList.remove('hidden');
                timingEl.innerHTML = `${summaryParts.join(' · ')}${cacheText}`;
            } else {
                timingEl.classList.add('hidden');
                timingEl.innerHTML = '';
            }
        }

        if (ctx.resourceShareLoading || currentFolderLoading) {
            treeEl.innerHTML = `<div class="resource-browser-empty">正在读取${ctx.escapeHtml(providerLabel)}分享目录，请稍候...</div>`;
        } else if (!ctx.isLinkTypeCookieConfigured(ctx.resourceModalLinkType)) {
            treeEl.innerHTML = `<div class="resource-browser-empty">当前未配置${ctx.escapeHtml(providerLabel)} Cookie，暂时无法读取分享目录。</div>`;
        } else if (ctx.resourceShareError) {
            treeEl.innerHTML = `<div class="resource-browser-empty text-red-300">${ctx.escapeHtml(ctx.resourceShareError)}</div>`;
        } else if (!ctx.resourceShareRootLoaded) {
            treeEl.innerHTML = '<div class="resource-browser-empty">这里会显示分享里的目录和文件列表，你可以进入文件夹后再勾选具体内容。</div>';
        } else if (!currentEntries.length) {
            treeEl.innerHTML = '<div class="resource-browser-empty">这个目录下暂时没有可转存的内容。</div>';
        } else if (!filteredEntries.length) {
            treeEl.innerHTML = `<div class="resource-browser-empty">当前已加载的 ${ctx.escapeHtml(String(currentEntries.length))} 个条目中没有匹配“${ctx.escapeHtml(searchKeyword)}”。</div>`;
        } else {
            const loadMoreHtml = currentFolderHasMore
                ? `
                    <div class="resource-browser-load-more-row">
                        <button
                            type="button"
                            data-resource-share-action="load-more"
                            class="resource-browser-load-more-btn ${currentFolderLoadingMore ? 'btn-disabled' : ''}"
                            ${currentFolderLoadingMore ? 'disabled' : ''}
                        >${currentFolderLoadingMore ? '加载中...' : '加载更多条目'}</button>
                    </div>
                `
                : '';
            const filterNoteHtml = searchKeyword
                ? `<div class="resource-browser-filter-note">已过滤 ${ctx.escapeHtml(String(filteredEntries.length))} / ${ctx.escapeHtml(String(currentEntries.length))} 个当前目录条目</div>`
                : '';
            treeEl.innerHTML = `${filterNoteHtml}${buildResourceShareRows(ctx, filteredEntries)}${loadMoreHtml}`;
        }

        const selectedInCurrentCount = currentEntries.filter(entry => ctx.isResourceShareEntryEffectivelySelected(entry)).length;
        if (currentCheckAllEl) {
            currentCheckAllEl.disabled = !currentEntries.length || !ctx.isLinkTypeCookieConfigured(ctx.resourceModalLinkType) || !!ctx.resourceShareError || ctx.resourceShareLoading || currentFolderLoading || currentFolderLoadingMore;
            currentCheckAllEl.checked = !!currentEntries.length && selectedInCurrentCount === currentEntries.length;
            currentCheckAllEl.indeterminate = selectedInCurrentCount > 0 && selectedInCurrentCount < currentEntries.length;
        }

        ctx.renderResourceImportBehaviorHint();
        ctx.renderResourceImportSummary();
    }

    function renderResourceFolderList(ctx) {
        const container = document.getElementById('resource-folder-list');
        const summary = document.getElementById('resource-folder-summary');
        const refreshBtn = document.getElementById('resource-folder-refresh-btn');
        if (!container) return;
        const providerLabel = ctx.getResourceProviderLabel(ctx.getCurrentResourceProvider());
        if (refreshBtn) {
            const refreshing = !!ctx.resourceFolderLoading;
            const readingFiles = !!ctx.resourceFolderFilesLoading;
            const busy = refreshing || readingFiles;
            refreshBtn.disabled = busy;
            refreshBtn.classList.toggle('btn-disabled', busy);
            refreshBtn.innerText = refreshing ? '刷新中...' : (readingFiles ? '读取中...' : '刷新当前目录');
        }
        if (summary) {
            const folderCount = Number(ctx.resourceFolderSummary?.folder_count || 0);
            const fileCount = Number(ctx.resourceFolderSummary?.file_count || 0);
            if (ctx.resourceFolderEntriesComplete) {
                summary.innerText = `当前目录下共有 ${folderCount} 个文件夹 / ${fileCount} 个文件。`;
            } else if (fileCount > 0) {
                summary.innerText = `当前目录下共有 ${folderCount} 个文件夹 / ${fileCount} 个文件，默认优先加载文件夹以提升打开速度。`;
            } else {
                summary.innerText = `已优先加载 ${folderCount} 个文件夹，文件列表默认延后加载以提升打开速度。`;
            }
        }
        if (ctx.resourceFolderLoading && !ctx.resourceFolderEntries.length) {
            container.innerHTML = `<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在读取${ctx.escapeHtml(providerLabel)}目录...</div>`;
            return;
        }
        const entries = Array.isArray(ctx.resourceFolderEntries) ? ctx.resourceFolderEntries : [];
        if (!entries.length && Number(ctx.resourceFolderSummary?.file_count || 0) <= 0) {
            container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前目录为空，可以直接选择这里作为保存位置。</div>';
            return;
        }
        const folders = [];
        const files = [];
        for (const entry of entries) {
            if (entry?.is_dir) folders.push(entry);
            else files.push(entry);
        }
        if (!ctx.resourceFolderEntriesComplete) {
            const lines = folders.map(entry => ctx.buildResourceEntryRow(entry, { showOpenButton: true }));
            const fileCount = Number(ctx.resourceFolderSummary?.file_count || 0);
            if (ctx.resourceFolderFilesLoading) {
                lines.push('<div class="rounded-2xl border border-dashed border-slate-700 px-4 py-3 text-[12px] text-slate-400">目录已可操作，正在后台补充文件预览...</div>');
            } else {
                const fileCountLabel = fileCount > 0 ? `（共 ${ctx.escapeHtml(String(fileCount))} 个）` : '';
                lines.push(
                    `<div class="resource-browser-hint-card rounded-2xl border border-slate-700/60 bg-slate-900/40 px-4 py-3 text-[12px] text-slate-300">` +
                    `为保证目录打开速度，文件列表默认延后加载。` +
                    `<button type="button" data-resource-folder-action="load-files" class="ml-2 resource-entry-action">加载文件预览${fileCountLabel}</button>` +
                    `</div>`
                );
            }
            container.innerHTML = lines.length
                ? lines.join('')
                : '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前目录仅包含文件，点击下方按钮后会加载文件预览。</div>';
            return;
        }
        const shouldTrimFiles = !ctx.resourceFolderShowAllFiles && files.length > ctx.RESOURCE_FOLDER_FILE_PREVIEW_LIMIT;
        const visibleFiles = shouldTrimFiles ? files.slice(0, ctx.RESOURCE_FOLDER_FILE_PREVIEW_LIMIT) : files;
        const visibleEntries = folders.concat(visibleFiles);
        const lines = visibleEntries.map(entry => ctx.buildResourceEntryRow(entry, { showOpenButton: true }));
        if (ctx.resourceFolderFilesLoading) {
            lines.push('<div class="rounded-2xl border border-dashed border-slate-700 px-4 py-3 text-[12px] text-slate-400">目录已可操作，正在后台补充文件列表...</div>');
        }
        if (files.length > ctx.RESOURCE_FOLDER_FILE_PREVIEW_LIMIT) {
            const label = shouldTrimFiles
                ? `显示全部文件（共 ${files.length} 个）`
                : `仅显示前 ${ctx.RESOURCE_FOLDER_FILE_PREVIEW_LIMIT} 个文件`;
            lines.push(
                `<div class="resource-browser-hint-card rounded-2xl border border-slate-700/60 bg-slate-900/40 px-4 py-3 text-[12px] text-slate-300">` +
                `为保证目录打开速度，默认仅渲染前 ${ctx.RESOURCE_FOLDER_FILE_PREVIEW_LIMIT} 个文件。` +
                `<button type="button" data-resource-folder-action="toggle-files" class="ml-2 resource-entry-action">${ctx.escapeHtml(label)}</button>` +
                `</div>`
            );
        }
        container.innerHTML = lines.join('');
    }

    function renderResourceFolderBreadcrumbs(ctx) {
        const container = document.getElementById('resource-folder-breadcrumbs');
        if (!container) return;
        container.innerHTML = ctx.resourceFolderTrail.map((item, index) => {
            const isLast = index === ctx.resourceFolderTrail.length - 1;
            return `
                ${index > 0 ? '<span class="resource-folder-sep">›</span>' : ''}
                <button
                    type="button"
                    data-resource-folder-action="trail"
                    data-resource-folder-index="${index}"
                    class="resource-folder-crumb ${isLast ? 'resource-folder-crumb-active' : ''}"
                    ${isLast ? 'disabled' : ''}
                >${ctx.escapeHtml(item?.name || '根目录')}</button>
            `;
        }).join('');
    }

    function renderResourceTargetPreview(ctx) {
        const pathEl = document.getElementById('resource-target-preview-path');
        const summaryEl = document.getElementById('resource-target-preview-summary');
        const listEl = document.getElementById('resource-target-preview-list');
        if (!pathEl || !summaryEl || !listEl) return;
        const provider = ctx.getCurrentResourceProvider();
        const providerLabel = ctx.getResourceProviderLabel(provider);

        pathEl.innerText = document.getElementById('resource_job_folder_path')?.value?.trim() || '根目录';
        if (!ctx.isProviderCookieConfigured(provider)) {
            summaryEl.innerText = `配置${providerLabel} Cookie 后可预览目标目录下的文件夹和文件内容。`;
            listEl.innerHTML = `<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前未配置${ctx.escapeHtml(providerLabel)} Cookie，暂时无法读取目标目录内容。</div>`;
            return;
        }
        if (ctx.resourceTargetPreviewLoading) {
            summaryEl.innerText = '正在读取目标目录内容...';
            listEl.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在加载目标目录内容...</div>';
            return;
        }
        if (ctx.resourceTargetPreviewError) {
            summaryEl.innerText = '目标目录内容读取失败';
            listEl.innerHTML = `<div class="rounded-2xl border border-dashed border-red-500/20 bg-red-500/10 p-6 text-center text-red-300 text-sm">${ctx.escapeHtml(ctx.resourceTargetPreviewError)}</div>`;
            return;
        }
        const folderCount = Number(ctx.resourceTargetPreviewSummary?.folder_count || 0);
        const fileCount = Number(ctx.resourceTargetPreviewSummary?.file_count || 0);
        summaryEl.innerText = `当前目录下共有 ${folderCount} 个文件夹 / ${fileCount} 个文件。`;
        if (!ctx.resourceTargetPreviewEntries.length) {
            listEl.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前目录为空，你可以直接把资源保存到这里。</div>';
            return;
        }
        const entries = Array.isArray(ctx.resourceTargetPreviewEntries) ? ctx.resourceTargetPreviewEntries : [];
        const folders = entries.filter(entry => !!entry?.is_dir);
        const files = entries.filter(entry => !entry?.is_dir);
        const visibleEntries = folders.concat(files.slice(0, ctx.RESOURCE_FOLDER_FILE_PREVIEW_LIMIT));
        let html = visibleEntries.map(entry => ctx.buildResourceEntryRow(entry)).join('');
        if (files.length > ctx.RESOURCE_FOLDER_FILE_PREVIEW_LIMIT) {
            html += `<div class="resource-browser-hint-card rounded-2xl border border-slate-700/60 bg-slate-900/40 px-4 py-3 text-[12px] text-slate-300">为保证加载速度，预览默认仅显示前 ${ctx.RESOURCE_FOLDER_FILE_PREVIEW_LIMIT} 个文件。</div>`;
        }
        listEl.innerHTML = html;
    }

    global.ResourceBrowser = {
        buildResourceShareRows,
        renderResourceShareBrowser,
        renderResourceFolderList,
        renderResourceFolderBreadcrumbs,
        renderResourceTargetPreview,
    };
})(window);
