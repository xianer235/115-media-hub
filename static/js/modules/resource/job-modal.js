        function getResourceJobCounts(jobs = []) {
            const list = Array.isArray(jobs) ? jobs : [];
            return {
                total: list.length,
                active: list.filter(job => ['pending', 'running', 'submitted'].includes(String(job?.status || '').toLowerCase())).length,
                submitted: list.filter(job => String(job?.status || '').toLowerCase() === 'submitted').length,
                completed: list.filter(job => String(job?.status || '').toLowerCase() === 'completed').length,
                failed: list.filter(job => String(job?.status || '').toLowerCase() === 'failed').length,
            };
        }

        function normalizeResourceJobFilter(value = 'all') {
            const normalized = String(value || 'all').trim().toLowerCase();
            return ['all', 'active', 'submitted', 'completed', 'failed'].includes(normalized) ? normalized : 'all';
        }

        function normalizeScraperJobFilter(value = 'all') {
            const normalized = String(value || 'all').trim().toLowerCase();
            return ['all', 'active', 'completed', 'failed', 'rollback'].includes(normalized) ? normalized : 'all';
        }

        function isScraperJobActive(job) {
            const status = String(job?.status || '').trim().toLowerCase();
            return ['pending', 'running', 'rollback_running'].includes(status);
        }

        function getScraperJobCounts(jobs = []) {
            const list = Array.isArray(jobs) ? jobs : [];
            return {
                total: list.length,
                active: list.filter(isScraperJobActive).length,
                completed: list.filter(job => String(job?.status || '').toLowerCase() === 'completed').length,
                failed: list.filter(job => ['failed', 'partial', 'rollback_failed'].includes(String(job?.status || '').toLowerCase())).length,
                rollback: list.filter(job => String(job?.status || '').toLowerCase() === 'rolled_back').length,
            };
        }

        function getScraperJobDisplayCounts(jobs = []) {
            const fallbackCounts = getScraperJobCounts(jobs);
            const serverCounts = scraperJobState?.job_counts && typeof scraperJobState.job_counts === 'object'
                ? scraperJobState.job_counts
                : {};
            return {
                total: Number(serverCounts.total ?? fallbackCounts.total ?? 0),
                active: Number(serverCounts.active ?? fallbackCounts.active ?? 0),
                completed: Number(serverCounts.completed ?? fallbackCounts.completed ?? 0),
                failed: Number(serverCounts.failed ?? fallbackCounts.failed ?? 0),
                rollback: Number(serverCounts.rollback ?? fallbackCounts.rollback ?? 0),
            };
        }

        function getTaskCenterActiveCount() {
            const jobs = Array.isArray(resourceState.jobs) ? resourceState.jobs : [];
            const pageActiveCount = jobs.filter(job => ['pending', 'running', 'submitted'].includes(String(job?.status || '').toLowerCase())).length;
            const resourceActive = Number(resourceState?.job_counts?.active ?? resourceState?.stats?.active_job_count ?? pageActiveCount) || 0;
            const scraperJobs = Array.isArray(scraperJobState.jobs) ? scraperJobState.jobs : [];
            const scraperActive = Number(scraperJobState?.job_counts?.active ?? getScraperJobCounts(scraperJobs).active ?? 0) || 0;
            return resourceActive + scraperActive;
        }

        function hasActiveScraperJobs() {
            return Number(scraperJobState?.job_counts?.active ?? getScraperJobCounts(scraperJobState.jobs || []).active ?? 0) > 0;
        }

        function getResourceJobDisplayCounts(jobs = []) {
            const fallbackCounts = getResourceJobCounts(jobs);
            const serverCounts = resourceState?.job_counts && typeof resourceState.job_counts === 'object'
                ? resourceState.job_counts
                : {};
            return {
                total: Number(serverCounts.total ?? fallbackCounts.total ?? 0),
                active: Number(serverCounts.active ?? fallbackCounts.active ?? 0),
                submitted: Number(serverCounts.submitted ?? fallbackCounts.submitted ?? 0),
                completed: Number(serverCounts.completed ?? resourceState?.stats?.completed_job_count ?? fallbackCounts.completed ?? 0),
                failed: Number(serverCounts.failed ?? resourceState?.stats?.failed_job_count ?? fallbackCounts.failed ?? 0),
            };
        }

        function isResourceJobVisible(job, filter = 'all') {
            const status = String(job?.status || '').toLowerCase();
            if (filter === 'active') return ['pending', 'running', 'submitted'].includes(status);
            if (filter === 'submitted') return status === 'submitted';
            if (filter === 'completed') return status === 'completed';
            if (filter === 'failed') return status === 'failed';
            return true;
        }

        function isScraperJobVisible(job, filter = 'all') {
            const status = String(job?.status || '').toLowerCase();
            if (filter === 'active') return ['pending', 'running', 'rollback_running'].includes(status);
            if (filter === 'completed') return status === 'completed';
            if (filter === 'failed') return ['failed', 'partial', 'rollback_failed'].includes(status);
            if (filter === 'rollback') return status === 'rolled_back';
            return true;
        }

        function renderTaskCenterTypeTabs() {
            const container = document.getElementById('resource-job-type-tabs');
            if (!container) return;
            const resourceCounts = getResourceJobDisplayCounts(resourceState.jobs || []);
            const scraperCounts = getScraperJobDisplayCounts(scraperJobState.jobs || []);
            const options = [
                { value: 'resource', label: '导入任务', count: resourceCounts.total },
                { value: 'scraper', label: '刮削任务', count: scraperCounts.total },
            ];
            container.innerHTML = options.map(option => `
                <button
                    type="button"
                    data-task-center-tab="${escapeHtml(option.value)}"
                    class="resource-job-type-tab ${taskCenterTab === option.value ? 'resource-job-type-tab-active' : ''}"
                >${escapeHtml(option.label)} (${escapeHtml(String(option.count))})</button>
            `).join('');
            const clearMenu = document.getElementById('resource-job-clear-menu');
            clearMenu?.classList.toggle('hidden', taskCenterTab !== 'resource' && taskCenterTab !== 'scraper');
            renderTaskCenterClearMenu();
            const note = document.getElementById('resource-job-modal-note');
            if (note) {
                note.textContent = taskCenterTab === 'scraper'
                    ? '刮削任务会记录每次执行的重命名进度；文件列表默认折叠，可展开查看每个文件状态。'
                    : '任务列表按创建时间倒序显示，每页 10 条；筛选后可使用页码翻阅记录。';
            }
        }

        function renderTaskCenterClearMenu() {
            const menu = document.getElementById('resource-job-clear-menu');
            if (!menu) return;
            const isScraperTab = taskCenterTab === 'scraper';
            const isResourceTab = taskCenterTab === 'resource';
            const open = resourceJobClearMenuOpen;
            const label = isScraperTab ? '清空刮削' : '清空';
            const completedLabel = '清空已完成';
            const failedLabel = isScraperTab ? '清空异常' : '清空失败';
            const terminalLabel = isScraperTab ? '清空已回退' : '清空完成+失败';
            const completedAction = isScraperTab ? 'clearCompletedScraperJobs' : 'clearCompletedResourceJobs';
            const failedAction = isScraperTab ? 'clearFailedScraperJobs' : 'clearFailedResourceJobs';
            const terminalAction = isScraperTab ? 'clearRollbackScraperJobs' : 'clearTerminalResourceJobs';
            menu.innerHTML = `
                <button id="resource-job-clear-toggle" type="button" onclick="toggleResourceJobClearMenu()" class="resource-job-modal-action resource-job-clear-toggle" aria-haspopup="menu" aria-expanded="${open ? 'true' : 'false'}">${escapeHtml(label)}</button>
                <div id="resource-job-clear-dropdown" class="resource-job-clear-dropdown ${open ? '' : 'hidden'}" role="menu" aria-label="清理任务记录">
                    <button id="resource-clear-completed-btn" type="button" onclick="${completedAction}()" class="resource-job-clear-item" role="menuitem">${escapeHtml(completedLabel)}</button>
                    <button id="resource-clear-failed-btn" type="button" onclick="${failedAction}()" class="resource-job-clear-item" role="menuitem">${escapeHtml(failedLabel)}</button>
                    <button id="resource-clear-terminal-btn" type="button" onclick="${terminalAction}()" class="resource-job-clear-item" role="menuitem">${escapeHtml(terminalLabel)}</button>
                </div>
            `;
            syncResourceJobClearMenuState();
            if (!isResourceTab && !isScraperTab) closeResourceJobClearMenu();
        }

        function renderResourceJobFilters(counts) {
            const container = document.getElementById('resource-job-filter-tabs');
            if (!container) return;
            if (taskCenterTab === 'scraper') {
                const scraperCounts = counts || getScraperJobDisplayCounts(scraperJobState.jobs || []);
                const options = [
                    { value: 'all', label: '全部', count: scraperCounts.total },
                    { value: 'active', label: '处理中', count: scraperCounts.active },
                    { value: 'completed', label: '已完成', count: scraperCounts.completed },
                    { value: 'failed', label: '异常', count: scraperCounts.failed },
                    { value: 'rollback', label: '已回退', count: scraperCounts.rollback },
                ];
                container.innerHTML = options.map(option => `
                    <button
                        type="button"
                        data-resource-job-filter="${escapeHtml(option.value)}"
                        class="resource-job-filter-tab ${scraperJobFilter === option.value ? 'resource-job-filter-tab-active' : ''}"
                    >${escapeHtml(option.label)} (${escapeHtml(String(option.count))})</button>
                `).join('');
                return;
            }
            const options = [
                { value: 'all', label: '全部', count: counts.total },
                { value: 'active', label: '处理中', count: counts.active },
                { value: 'submitted', label: '待刷新', count: counts.submitted },
                { value: 'completed', label: '已完成', count: counts.completed },
                { value: 'failed', label: '失败', count: counts.failed },
            ];
            container.innerHTML = options.map(option => `
                <button
                    type="button"
                    data-resource-job-filter="${escapeHtml(option.value)}"
                    class="resource-job-filter-tab ${resourceJobFilter === option.value ? 'resource-job-filter-tab-active' : ''}"
                >${escapeHtml(option.label)} (${escapeHtml(String(option.count))})</button>
            `).join('');
        }

        function getResourceJobEmptyText(filter = 'all') {
            if (filter === 'active') return '当前没有正在处理的导入任务。';
            if (filter === 'submitted') return '当前没有等待刷新生成 strm 的任务。';
            if (filter === 'completed') return '当前没有已完成的导入记录。';
            if (filter === 'failed') return '当前没有失败任务。';
            return '还没有导入任务，资源卡片里的“下载 / 转存”会在这里留下记录。';
        }

        function getScraperJobEmptyText(filter = 'all') {
            if (filter === 'active') return '当前没有正在处理的刮削任务。';
            if (filter === 'completed') return '当前没有已完成的刮削记录。';
            if (filter === 'failed') return '当前没有异常刮削任务。';
            if (filter === 'rollback') return '当前没有已回退刮削任务。';
            return '还没有刮削任务，在刮削管理里执行重命名后会出现在这里。';
        }

        function getScraperJobStatusLabel(status) {
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

        function getScraperActionStatusLabel(action = {}) {
            const rollbackStatus = String(action.rollback_status || '').trim();
            const status = rollbackStatus || String(action.status || '').trim();
            const labels = {
                pending: '等待',
                running: '处理中',
                completed: rollbackStatus ? '已回退' : '成功',
                skipped: '跳过',
                failed: rollbackStatus ? '回退失败' : '失败',
            };
            return labels[status] || status || '--';
        }

        function getScraperJobTitle(job = {}) {
            const tmdb = job.tmdb && typeof job.tmdb === 'object' ? job.tmdb : {};
            const title = tmdb.tmdb_title || tmdb.title || tmdb.tmdb_localized_title || tmdb.tmdb_english_title || '';
            const year = tmdb.tmdb_year || tmdb.year || '';
            const mediaTitle = `${title || ''}${year ? ` (${year})` : ''}`.trim();
            return mediaTitle || `刮削任务 #${Number(job.id || 0) || '--'}`;
        }

        function getScraperJobProgress(job = {}) {
            const total = Math.max(0, Number(job.total_actions || 0) || 0);
            const actions = Array.isArray(job.actions) ? job.actions : [];
            const derivedSucceeded = actions.filter(action => ['completed', 'skipped'].includes(String(action?.status || '').toLowerCase())).length;
            const derivedFailed = actions.filter(action => String(action?.status || '').toLowerCase() === 'failed').length;
            const derivedRollbackSucceeded = actions.filter(action => ['completed', 'skipped'].includes(String(action?.rollback_status || '').toLowerCase())).length;
            const derivedRollbackFailed = actions.filter(action => String(action?.rollback_status || '').toLowerCase() === 'failed').length;
            const succeeded = Math.max(0, Number(job.succeeded_actions || 0) || 0, derivedSucceeded);
            const failed = Math.max(0, Number(job.failed_actions || 0) || 0, derivedFailed);
            const rollbackSucceeded = Math.max(0, Number(job.rollback_succeeded_actions || 0) || 0, derivedRollbackSucceeded);
            const rollbackFailed = Math.max(0, Number(job.rollback_failed_actions || 0) || 0, derivedRollbackFailed);
            const rollbackMode = String(job.status || '').toLowerCase().includes('rollback') || String(job.status || '').toLowerCase() === 'rolled_back';
            const done = rollbackMode ? rollbackSucceeded + rollbackFailed : succeeded + failed;
            const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((done / total) * 100))) : 0;
            return { total, succeeded, failed, done, percent, rollbackSucceeded, rollbackFailed, rollbackMode };
        }

        function renderScraperJobActions(job = {}) {
            const actions = Array.isArray(job.actions) ? job.actions : [];
            if (!actions.length) return '<div class="scraper-job-action-empty">暂无文件明细。</div>';
            return actions.map(action => {
                const isFailed = ['failed'].includes(String(action.status || '').toLowerCase()) || ['failed'].includes(String(action.rollback_status || '').toLowerCase());
                const statusLabel = getScraperActionStatusLabel(action);
                return `
                    <div class="scraper-task-file-row ${isFailed ? 'is-failed' : ''}">
                        <span class="scraper-task-file-status">${escapeHtml(statusLabel)}</span>
                        <div class="scraper-task-file-paths">
                            <div><b>旧</b>${escapeHtml(action.old_path || action.old_name || '--')}</div>
                            <div><b>新</b>${escapeHtml(action.new_path || action.new_name || '--')}</div>
                            ${action.status_detail || action.rollback_detail ? `<em>${escapeHtml(action.rollback_detail || action.status_detail || '')}</em>` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }

        function renderScraperJobs() {
            const container = document.getElementById('resource-job-list');
            if (!container) return;
            const jobs = Array.isArray(scraperJobState.jobs) ? scraperJobState.jobs : [];
            const counts = getScraperJobDisplayCounts(jobs);
            renderTaskCenterTypeTabs();
            renderResourceJobFilters(counts);
            if (scraperJobLoading && !jobs.length) {
                container.innerHTML = '<div class="resource-job-card-empty">正在读取刮削任务...</div>';
                return;
            }
            const normalizedFilter = normalizeScraperJobFilter(scraperJobFilter);
            const visibleJobs = jobs.filter(job => isScraperJobVisible(job, normalizedFilter));
            if (!visibleJobs.length) {
                container.innerHTML = `<div class="resource-job-card-empty">${escapeHtml(getScraperJobEmptyText(scraperJobFilter))}</div>`;
                return;
            }
            const rowsHtml = visibleJobs.map(job => {
                const jobId = Number(job.id || 0) || 0;
                const progress = getScraperJobProgress(job);
                const expanded = scraperJobExpanded.has(jobId);
                const providerLabel = String(job.provider || '') === 'quark' ? '夸克' : '115';
                const canRollback = !!job.can_rollback;
                const rollbackLabel = canRollback ? '回退' : '不可回退';
                const actionCount = Array.isArray(job.actions) ? job.actions.length : 0;
                return `
                    <div class="resource-job-card scraper-task-card">
                        <div class="resource-job-card-head">
                            <div class="min-w-0 flex-1">
                                <div class="flex flex-wrap items-center gap-2">
                                    <div class="resource-job-card-title">${escapeHtml(getScraperJobTitle(job))}</div>
                                    ${buildResourceStatusBadge(job.status)}
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/10 text-sky-100 border border-sky-500/20">刮削</span>
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-100">${escapeHtml(providerLabel)}</span>
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-100">#${escapeHtml(String(jobId))}</span>
                                </div>
                                <div class="scraper-task-progress">
                                    <div class="scraper-task-progress-head">
                                        <span>${escapeHtml(getScraperJobStatusLabel(job.status))}</span>
                                        <span>${escapeHtml(String(progress.percent))}% · ${escapeHtml(String(progress.done))}/${escapeHtml(String(progress.total))}</span>
                                    </div>
                                    <div class="scraper-task-progress-track">
                                        <span style="width: ${escapeHtml(String(progress.percent))}%"></span>
                                    </div>
                                </div>
                                <div class="resource-job-card-grid">
                                    <div class="resource-job-field">
                                        <div class="resource-job-field-label">文件数量</div>
                                        <div class="resource-job-field-value">成功 ${escapeHtml(String(progress.succeeded))} / 失败 ${escapeHtml(String(progress.failed))} / 总计 ${escapeHtml(String(progress.total))}</div>
                                    </div>
                                    <div class="resource-job-field">
                                        <div class="resource-job-field-label">回退</div>
                                        <div class="resource-job-field-value">成功 ${escapeHtml(String(progress.rollbackSucceeded))} / 失败 ${escapeHtml(String(progress.rollbackFailed))}</div>
                                    </div>
                                    <div class="resource-job-field">
                                        <div class="resource-job-field-label">创建时间</div>
                                        <div class="resource-job-field-value">${escapeHtml(job.created_at || '--')}</div>
                                    </div>
                                    <div class="resource-job-field">
                                        <div class="resource-job-field-label">更新时间</div>
                                        <div class="resource-job-field-value">${escapeHtml(job.updated_at || job.finished_at || '--')}</div>
                                    </div>
                                </div>
                                <div class="resource-job-status-note">${escapeHtml(job.status_detail || '--')}</div>
                            </div>
                        </div>
                        <div class="resource-job-card-actions">
                            <div class="flex flex-wrap gap-2 min-w-0 flex-1 justify-end">
                                <button type="button" data-scraper-job-action="toggle" data-scraper-job-id="${escapeHtml(String(jobId))}" class="px-4 py-2 rounded-xl text-sm font-bold bg-slate-700 hover:bg-slate-600 text-slate-100">${expanded ? '收起文件' : `展开文件（${escapeHtml(String(actionCount))}）`}</button>
                                <button type="button" data-scraper-job-action="rollback" data-scraper-job-id="${escapeHtml(String(jobId))}" class="px-4 py-2 rounded-xl text-sm font-bold ${canRollback ? 'bg-amber-600 hover:bg-amber-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canRollback ? '' : 'disabled'}>${rollbackLabel}</button>
                            </div>
                        </div>
                        <div class="scraper-task-file-list ${expanded ? '' : 'hidden'}">
                            ${renderScraperJobActions(job)}
                        </div>
                    </div>
                `;
            }).join('');
            const pagination = scraperJobState?.pagination && typeof scraperJobState.pagination === 'object'
                ? scraperJobState.pagination
                : {};
            const pageNumber = Math.max(1, Number(pagination.page || 1) || 1);
            const totalPages = Math.max(1, Number(pagination.total_pages || 1) || 1);
            const totalCount = Number(pagination.total ?? counts.total) || 0;
            const paginationHtml = totalCount > 0
                ? `
                    <div class="resource-browser-load-more-row">
                        <button type="button" data-scraper-job-action="page-prev" class="resource-browser-load-more-btn" ${pageNumber <= 1 ? 'disabled' : ''}>上一页</button>
                        <span class="resource-job-status-note">第 ${escapeHtml(String(pageNumber))} / ${escapeHtml(String(totalPages))} 页，共 ${escapeHtml(String(totalCount))} 条</span>
                        <button type="button" data-scraper-job-action="page-next" class="resource-browser-load-more-btn" ${pageNumber >= totalPages ? 'disabled' : ''}>下一页</button>
                    </div>
                `
                : '';
            container.innerHTML = `${rowsHtml}${paginationHtml}`;
        }

        function formatOfflineSize(bytes) {
            const size = Number(bytes || 0) || 0;
            if (size <= 0) return '0B';
            if (size >= 1073741824) return `${(size / 1073741824).toFixed(1)}GB`;
            if (size >= 1048576) return `${(size / 1048576).toFixed(1)}MB`;
            if (size >= 1024) return `${(size / 1024).toFixed(1)}KB`;
            return `${size}B`;
        }

        function getOfflineJobProgress(job = {}) {
            const linkType = String(job.link_type || '').trim().toLowerCase();
            if (!['magnet', 'ed2k'].includes(linkType)) return null;
            if (String(job.status || '').trim().toLowerCase() !== 'submitted') return null;
            const extra = job.extra && typeof job.extra === 'object' ? job.extra : {};
            const percent = Number(extra.offline_percent || 0) || 0;
            const offlineStatus = Number(extra.offline_status || 0) || 0;
            if (percent <= 0 && offlineStatus !== 1) return null;
            const total = Number(extra.offline_total || 0) || 0;
            const downloaded = Number(extra.offline_downloaded || 0) || 0;
            const clamped = Math.max(0, Math.min(100, Math.round(percent)));
            const sizeText = total > 0 ? `${formatOfflineSize(downloaded)} / ${formatOfflineSize(total)}` : '';
            return { percent: clamped, sizeText };
        }

        function renderOfflineJobProgressRow(job) {
            const progress = getOfflineJobProgress(job);
            if (!progress) return '';
            return `
                    <div class="resource-job-offline-progress">
                        <div class="resource-job-offline-progress-track">
                            <div class="resource-job-offline-progress-bar" style="width:${progress.percent}%"></div>
                        </div>
                        <div class="resource-job-offline-progress-text">115 离线下载 ${progress.percent}%${progress.sizeText ? ` · ${progress.sizeText}` : ''}</div>
                    </div>
                `;
        }

        function renderResourceJobs() {
            const container = document.getElementById('resource-job-list');
            const jobs = Array.isArray(resourceState.jobs) ? resourceState.jobs : [];
            const counts = getResourceJobDisplayCounts(jobs);
            if (!container) return;

            if (taskCenterTab === 'scraper') {
                renderScraperJobs();
                return;
            }
            renderTaskCenterTypeTabs();
            renderResourceJobFilters(counts);

            const normalizedFilter = normalizeResourceJobFilter(resourceJobFilter);
            const pageStatus = normalizeResourceJobFilter(resourceState?.job_pagination?.status || 'all');
            const loadError = String(resourceJobLoadError || '').trim();
            const loadErrorHtml = loadError
                ? `
                    <div class="resource-browser-load-more-row" role="alert">
                        <div class="resource-job-status-note text-red-300">${escapeHtml(loadError)}</div>
                        <button type="button" data-resource-job-action="retry-load" class="resource-browser-load-more-btn">重新加载</button>
                    </div>
                `
                : '';
            const visibleJobs = pageStatus === normalizedFilter
                ? jobs
                : jobs.filter(job => isResourceJobVisible(job, normalizedFilter));
            if (!visibleJobs.length) {
                container.innerHTML = loadErrorHtml || `<div class="resource-job-card-empty">${escapeHtml(getResourceJobEmptyText(resourceJobFilter))}</div>`;
                return;
            }

            const rowsHtml = visibleJobs.map(job => {
                const hasMonitorTask = !!String(job.monitor_task_name || '').trim();
                const canManualRefresh = hasMonitorTask && !job.last_triggered_at && String(job.status || '').toLowerCase() === 'submitted';
                const normalizedStatus = String(job.status || '').toLowerCase();
                const canCancel = ['pending', 'running', 'submitted'].includes(normalizedStatus);
                const canRetry = normalizedStatus === 'failed';
                const canDelete = ['completed', 'failed'].includes(normalizedStatus);
                const manualRefreshLabel = !hasMonitorTask ? '未绑定监控' : (canManualRefresh ? '立即刷新' : '无需刷新');
                const cancelLabel = canCancel ? '取消' : '不可取消';
                const retryLabel = canRetry ? '重试' : '不可重试';
                const autoRefreshText = hasMonitorTask
                    ? (job.auto_refresh ? `自动刷新 ${escapeHtml(String(job.refresh_delay_seconds || 0))} 秒` : '手动刷新')
                    : '未绑定监控';
                const linkTypeLabel = getResourceLinkTypeLabel(job.link_type || '');
                const sourceLabel = getResourceJobSourceLabel(job.job_source || '');
                return `
                    <div class="resource-job-card">
                        <div class="resource-job-card-head">
                            <div class="min-w-0 flex-1">
                                <div class="flex flex-wrap items-center gap-2">
                                    <div class="resource-job-card-title">${escapeHtml(job.title || `任务 #${job.id}`)}</div>
                                    ${buildResourceStatusBadge(job.status)}
                                    <span class="${getResourceLinkTypeBadgeClass(job.link_type || '')}">${escapeHtml(linkTypeLabel)}</span>
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/20">${escapeHtml(sourceLabel)}</span>
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-100">#${job.id}</span>
                                </div>
                                <div class="resource-job-card-grid">
                                    <div class="resource-job-field">
                                        <div class="resource-job-field-label">保存路径</div>
                                        <div class="resource-job-field-value">${escapeHtml(job.savepath || '--')}</div>
                                    </div>
                                    <div class="resource-job-field">
                                        <div class="resource-job-field-label">监控任务</div>
                                        <div class="resource-job-field-value">${escapeHtml(job.monitor_task_name || '当前目录未纳入文件夹监控')}</div>
                                    </div>
                                    <div class="resource-job-field">
                                        <div class="resource-job-field-label">子目录 / 目标</div>
                                        <div class="resource-job-field-value">${escapeHtml(job.sharetitle || job.share_root_title || '--')}</div>
                                    </div>
                                    <div class="resource-job-field">
                                        <div class="resource-job-field-label">刷新策略</div>
                                        <div class="resource-job-field-value">${escapeHtml(getResourceRefreshTargetLabel(job.refresh_target_type))} · ${autoRefreshText}</div>
                                    </div>
                                </div>
                                <div class="resource-job-status-note">${escapeHtml(job.status_detail || '--')}</div>
                                ${renderOfflineJobProgressRow(job)}
                                <div class="resource-job-card-meta">
                                    <span class="resource-job-meta-chip">创建于 ${escapeHtml(job.created_at || '--')}</span>
                                    <span class="resource-job-meta-chip">${autoRefreshText}</span>
                                </div>
                            </div>
                        </div>
                        <div class="resource-job-card-actions">
                            <div class="flex flex-wrap gap-2 min-w-0 flex-1 justify-end">
                                <button type="button" data-resource-job-action="cancel" data-resource-job-id="${job.id}" class="px-4 py-2 rounded-xl text-sm font-bold ${canCancel ? 'bg-amber-600 hover:bg-amber-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canCancel ? '' : 'disabled'}>${cancelLabel}</button>
                                <button type="button" data-resource-job-action="retry" data-resource-job-id="${job.id}" class="px-4 py-2 rounded-xl text-sm font-bold ${canRetry ? 'bg-emerald-600 hover:bg-emerald-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canRetry ? '' : 'disabled'}>${retryLabel}</button>
                                <button type="button" data-resource-job-action="refresh" data-resource-job-id="${job.id}" class="px-4 py-2 rounded-xl text-sm font-bold ${canManualRefresh ? 'bg-sky-600 hover:bg-sky-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canManualRefresh ? '' : 'disabled'}>${manualRefreshLabel}</button>
                                ${canDelete ? `<button type="button" data-resource-job-action="delete" data-resource-job-id="${job.id}" class="px-4 py-2 rounded-xl text-sm font-bold bg-red-600 hover:bg-red-500 text-white">删除记录</button>` : ''}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
            const pagination = resourceState?.job_pagination && typeof resourceState.job_pagination === 'object'
                ? resourceState.job_pagination
                : {};
            const totalCount = Number(pagination.total ?? counts.total) || 0;
            const pageNumber = Math.max(1, Number(pagination.page || 1) || 1);
            const totalPages = Math.max(1, Number(pagination.total_pages || 1) || 1);
            const paginationHtml = totalCount > 0 && pageStatus === normalizedFilter
                ? `
                    <div class="resource-browser-load-more-row">
                        <button type="button" data-resource-job-action="page-prev" class="resource-browser-load-more-btn" ${pageNumber <= 1 ? 'disabled' : ''}>上一页</button>
                        <span class="resource-job-status-note">第 ${escapeHtml(String(pageNumber))} / ${escapeHtml(String(totalPages))} 页，共 ${escapeHtml(String(totalCount))} 条</span>
                        <button type="button" data-resource-job-action="page-next" class="resource-browser-load-more-btn" ${pageNumber >= totalPages ? 'disabled' : ''}>下一页</button>
                    </div>
                `
                : '';
            container.innerHTML = `${rowsHtml}${loadErrorHtml}${paginationHtml}`;
        }

        function syncResourceJobModalTrigger() {
            const btn = document.getElementById('resource-job-modal-toggle');
            const badge = document.getElementById('resource-job-modal-badge');
            if (!btn || !badge) return;
            const activeCount = getTaskCenterActiveCount();
            badge.textContent = String(activeCount);
            badge.classList.toggle('hidden', activeCount <= 0);
            btn.classList.toggle('border-sky-500', activeCount > 0);
            btn.classList.toggle('text-sky-100', activeCount > 0);
            btn.classList.toggle('resource-job-trigger-active', activeCount > 0 || resourceJobModalOpen);
            btn.setAttribute('aria-expanded', resourceJobModalOpen ? 'true' : 'false');
        }

        function closeResourceJobClearMenu() {
            const menu = document.getElementById('resource-job-clear-menu');
            const dropdown = document.getElementById('resource-job-clear-dropdown');
            const toggleBtn = document.getElementById('resource-job-clear-toggle');
            resourceJobClearMenuOpen = false;
            if (!menu || !dropdown || !toggleBtn) return;
            dropdown.classList.add('hidden');
            toggleBtn.setAttribute('aria-expanded', 'false');
        }

        function toggleResourceJobClearMenu(force) {
            const menu = document.getElementById('resource-job-clear-menu');
            const dropdown = document.getElementById('resource-job-clear-dropdown');
            const toggleBtn = document.getElementById('resource-job-clear-toggle');
            if (!menu || !dropdown || !toggleBtn) return;
            if (toggleBtn.disabled) return;
            const nextOpen = typeof force === 'boolean' ? !!force : !resourceJobClearMenuOpen;
            resourceJobClearMenuOpen = nextOpen;
            dropdown.classList.toggle('hidden', !nextOpen);
            toggleBtn.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
        }

        function syncResourceJobClearMenuState() {
            const isScraperTab = taskCenterTab === 'scraper';
            const jobCounts = isScraperTab ? getScraperJobDisplayCounts(scraperJobState.jobs || []) : getResourceJobCounts(resourceState.jobs || []);
            const completedCount = Number(isScraperTab ? jobCounts.completed ?? 0 : resourceState?.stats?.completed_job_count ?? jobCounts.completed ?? 0);
            const failedCount = Number(isScraperTab ? jobCounts.failed ?? 0 : resourceState?.stats?.failed_job_count ?? jobCounts.failed ?? 0);
            const rollbackCount = Number(isScraperTab ? jobCounts.rollback ?? 0 : 0);
            const terminalCount = completedCount + failedCount + rollbackCount;

            const toggleBtn = document.getElementById('resource-job-clear-toggle');
            if (toggleBtn) {
                toggleBtn.textContent = isScraperTab
                    ? (terminalCount > 0 ? `清空刮削（${terminalCount}）` : '清空刮削')
                    : (terminalCount > 0 ? `清空（${terminalCount}）` : '清空');
                toggleBtn.disabled = terminalCount <= 0;
                toggleBtn.classList.toggle('btn-disabled', terminalCount <= 0);
            }

            const completedBtn = document.getElementById('resource-clear-completed-btn');
            if (completedBtn) {
                completedBtn.textContent = completedCount > 0
                    ? `清空已完成（${completedCount}）`
                    : '清空已完成';
                completedBtn.disabled = completedCount <= 0;
                completedBtn.classList.toggle('btn-disabled', completedCount <= 0);
            }
            const failedBtn = document.getElementById('resource-clear-failed-btn');
            if (failedBtn) {
                failedBtn.textContent = failedCount > 0
                    ? (isScraperTab ? `清空异常（${failedCount}）` : `清空失败（${failedCount}）`)
                    : (isScraperTab ? '清空异常' : '清空失败');
                failedBtn.disabled = failedCount <= 0;
                failedBtn.classList.toggle('btn-disabled', failedCount <= 0);
            }
            const terminalBtn = document.getElementById('resource-clear-terminal-btn');
            if (terminalBtn) {
                const terminalButtonCount = isScraperTab ? rollbackCount : terminalCount;
                terminalBtn.textContent = terminalButtonCount > 0
                    ? (isScraperTab ? `清空已回退（${terminalButtonCount}）` : `清空完成+失败（${terminalButtonCount}）`)
                    : (isScraperTab ? '清空已回退' : '清空完成+失败');
                terminalBtn.disabled = terminalButtonCount <= 0;
                terminalBtn.classList.toggle('btn-disabled', terminalButtonCount <= 0);
            }

            if (terminalCount <= 0) closeResourceJobClearMenu();
        }

        function getScraperJobClearMeta(scope = 'completed') {
            const normalized = String(scope || 'completed').trim().toLowerCase();
            const jobCounts = getScraperJobDisplayCounts(scraperJobState.jobs || []);
            const completedCount = Number(jobCounts.completed ?? 0);
            const failedCount = Number(jobCounts.failed ?? 0);
            if (normalized === 'failed') {
                return {
                    scope: 'failed',
                    count: failedCount,
                    label: '异常',
                    emptyText: '当前没有可清空的异常刮削记录',
                    confirmText: '将清空异常刮削记录（只删除任务记录，不会删除网盘文件；执行中任务不会清理）。继续吗？',
                };
            }
            if (normalized === 'rollback') {
                const rollbackCount = Number(jobCounts.rollback ?? 0) || 0;
                return {
                    scope: 'rollback',
                    count: rollbackCount,
                    label: '已回退',
                    emptyText: '当前没有可清空的已回退刮削记录',
                    confirmText: '将清空已回退刮削记录（只删除任务记录，不会删除网盘文件；执行中任务不会清理）。继续吗？',
                };
            }
            return {
                scope: 'completed',
                count: completedCount,
                label: '已完成',
                emptyText: '当前没有可清空的已完成刮削记录',
                confirmText: '将清空已完成刮削记录（只删除任务记录，不会删除网盘文件；执行中任务不会清理）。继续吗？',
            };
        }

        async function clearScraperJobs(scope = 'completed') {
            const meta = getScraperJobClearMeta(scope);
            closeResourceJobClearMenu();
            if (meta.count <= 0) {
                showToast(meta.emptyText, { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            if (!(await showAppConfirm(meta.confirmText))) return;
            try {
                const data = await window.MediaHubApi.postJson('/scraper/jobs/clear', { scope: meta.scope });
                await fetchScraperJobsState({ silent: true });
                if (taskCenterTab === 'scraper') renderResourceJobs();
                const deleted = Number(data.deleted || 0);
                if (deleted > 0) {
                    showToast(`已清空 ${deleted} 条刮削${meta.label}记录`, { tone: 'success', duration: 2600, placement: 'top-center' });
                } else {
                    showToast(meta.emptyText, { tone: 'info', duration: 2600, placement: 'top-center' });
                }
            } catch (error) {
                showToast(`清空失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        async function clearCompletedScraperJobs() {
            await clearScraperJobs('completed');
        }

        async function clearFailedScraperJobs() {
            await clearScraperJobs('failed');
        }

        async function clearRollbackScraperJobs() {
            await clearScraperJobs('rollback');
        }

        function applyScraperJobsState(data) {
            if (!data || typeof data !== 'object') return;
            const jobs = Array.isArray(data.jobs) ? data.jobs : (scraperJobState.jobs || []);
            const counts = getScraperJobCounts(jobs);
            scraperJobState = {
                ...scraperJobState,
                jobs,
                active_jobs: jobs.filter(isScraperJobActive),
                job_counts: data.job_counts && typeof data.job_counts === 'object' ? data.job_counts : counts,
                pagination: data.pagination && typeof data.pagination === 'object' ? data.pagination : (scraperJobState.pagination || {}),
            };
            const validJobIds = new Set(jobs.map(job => Number(job.id || 0) || 0).filter(Boolean));
            scraperJobExpanded = new Set(Array.from(scraperJobExpanded).filter(jobId => validJobIds.has(jobId)));
            syncResourceJobModalTrigger();
            if (taskCenterTab === 'scraper') renderResourceJobs();
        }

        async function fetchScraperJobsState({ silent = false, page = scraperJobState.pagination?.page || 1 } = {}) {
            scraperJobLoading = true;
            if (!silent && taskCenterTab === 'scraper') renderResourceJobs();
            try {
                const normalizedPage = Math.max(1, Number(page || 1) || 1);
                const params = new URLSearchParams({ page: String(normalizedPage), page_size: '10', status: normalizeScraperJobFilter(scraperJobFilter) });
                const data = await window.MediaHubApi.getJson(`/scraper/jobs/state?${params.toString()}`);
                applyScraperJobsState(data);
                return data;
            } catch (error) {
                if (!silent) showToast(`读取刮削任务失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return null;
            } finally {
                scraperJobLoading = false;
                if (taskCenterTab === 'scraper') renderResourceJobs();
            }
        }

        async function refreshTaskCenterJobsOnly({ preferTab = '' } = {}) {
            if (preferTab === 'scraper' || preferTab === 'resource') {
                taskCenterTab = preferTab;
            }
            const tasks = [];
            if (typeof refreshResourceJobsOnly === 'function') {
                tasks.push(refreshResourceJobsOnly());
            }
            tasks.push(fetchScraperJobsState({ silent: true }));
            await Promise.allSettled(tasks);
            syncResourceJobModalTrigger();
            renderResourceJobs();
        }

        function toggleScraperJobExpanded(jobId) {
            const normalizedJobId = Number(jobId || 0) || 0;
            if (!normalizedJobId) return;
            if (scraperJobExpanded.has(normalizedJobId)) {
                scraperJobExpanded.delete(normalizedJobId);
            } else {
                scraperJobExpanded.add(normalizedJobId);
            }
            renderResourceJobs();
        }

        async function rollbackScraperJobFromTaskCenter(jobId) {
            const normalizedJobId = Number(jobId || 0) || 0;
            if (!normalizedJobId) return;
            if (!(await window.showAppConfirm(`回退刮削任务 #${normalizedJobId} 的成功动作吗？`))) return;
            try {
                await window.MediaHubApi.postJson(`/scraper/jobs/${encodeURIComponent(String(normalizedJobId))}/rollback`, {});
                await fetchScraperJobsState({ silent: true });
                showToast('回退任务已提交', { tone: 'success', duration: 2400, placement: 'top-center' });
                if (typeof scheduleResourcePolling === 'function') scheduleResourcePolling(1000);
            } catch (error) {
                showToast(`回退提交失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3400, placement: 'top-center' });
            }
        }

        function toggleResourceJobModal(force) {
            const modal = document.getElementById('resource-job-modal');
            if (!modal) return;
            const nextOpen = typeof force === 'boolean' ? !!force : !resourceJobModalOpen;
            if (nextOpen === resourceJobModalOpen) {
                syncResourceJobModalTrigger();
                return;
            }
            resourceJobModalOpen = nextOpen;
            modal.classList.toggle('hidden', !resourceJobModalOpen);
            if (resourceJobModalOpen) {
                lockPageScroll();
                syncResourceJobClearMenuState();
                renderTaskCenterTypeTabs();
                if (taskCenterTab === 'scraper') {
                    void fetchScraperJobsState();
                } else {
                    void fetchResourceJobsPage({ status: resourceJobFilter, reset: true });
                    void fetchScraperJobsState({ silent: true });
                }
            } else {
                closeResourceJobClearMenu();
                unlockPageScroll();
            }
            syncResourceJobModalTrigger();
        }

        Object.assign(window, {
            applyScraperJobsState,
            fetchScraperJobsState,
            refreshTaskCenterJobsOnly,
            hasActiveScraperJobs,
            toggleScraperJobExpanded,
            rollbackScraperJobFromTaskCenter,
            clearCompletedScraperJobs,
            clearFailedScraperJobs,
            clearRollbackScraperJobs,
        });
