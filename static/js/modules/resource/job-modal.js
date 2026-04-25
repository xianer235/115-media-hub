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

        function renderResourceJobFilters(counts) {
            const container = document.getElementById('resource-job-filter-tabs');
            if (!container) return;
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
            return '还没有导入任务，资源卡片里的“下载到 115 / 转存到 115”会在这里留下记录。';
        }

        function renderResourceJobs() {
            const container = document.getElementById('resource-job-list');
            const jobs = Array.isArray(resourceState.jobs) ? resourceState.jobs : [];
            const counts = getResourceJobDisplayCounts(jobs);
            if (!container) return;

            renderResourceJobFilters(counts);

            const normalizedFilter = normalizeResourceJobFilter(resourceJobFilter);
            const pageStatus = normalizeResourceJobFilter(resourceState?.job_pagination?.status || 'all');
            const visibleJobs = pageStatus === normalizedFilter
                ? jobs
                : jobs.filter(job => isResourceJobVisible(job, normalizedFilter));
            if (!visibleJobs.length) {
                container.innerHTML = `<div class="resource-job-card-empty">${escapeHtml(getResourceJobEmptyText(resourceJobFilter))}</div>`;
                return;
            }

            const rowsHtml = visibleJobs.map(job => {
                const hasMonitorTask = !!String(job.monitor_task_name || '').trim();
                const canManualRefresh = hasMonitorTask && !job.last_triggered_at && String(job.status || '').toLowerCase() === 'submitted';
                const normalizedStatus = String(job.status || '').toLowerCase();
                const canCancel = ['pending', 'running', 'submitted'].includes(normalizedStatus);
                const canRetry = normalizedStatus === 'failed';
                const manualRefreshLabel = !hasMonitorTask ? '当前目录不触发' : (canManualRefresh ? '立即触发刷新' : '无需手动刷新');
                const cancelLabel = canCancel ? '取消任务' : '不可取消';
                const retryLabel = canRetry ? '重试任务' : '不可重试';
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
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/10 text-sky-200 border border-sky-500/20">${escapeHtml(linkTypeLabel)}</span>
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-violet-500/10 text-violet-200 border border-violet-500/20">${escapeHtml(sourceLabel)}</span>
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
                                <div class="resource-job-card-meta">
                                    <span class="resource-job-meta-chip">创建于 ${escapeHtml(job.created_at || '--')}</span>
                                    <span class="resource-job-meta-chip">${autoRefreshText}</span>
                                </div>
                            </div>
                        </div>
                        <div class="resource-job-card-actions">
                            <div class="flex flex-wrap gap-2 shrink-0">
                                <button type="button" data-resource-job-action="cancel" data-resource-job-id="${job.id}" class="px-4 py-2 rounded-xl text-sm font-bold ${canCancel ? 'bg-amber-600 hover:bg-amber-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canCancel ? '' : 'disabled'}>${cancelLabel}</button>
                                <button type="button" data-resource-job-action="retry" data-resource-job-id="${job.id}" class="px-4 py-2 rounded-xl text-sm font-bold ${canRetry ? 'bg-emerald-600 hover:bg-emerald-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canRetry ? '' : 'disabled'}>${retryLabel}</button>
                                <button type="button" data-resource-job-action="refresh" data-resource-job-id="${job.id}" class="px-4 py-2 rounded-xl text-sm font-bold ${canManualRefresh ? 'bg-sky-600 hover:bg-sky-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canManualRefresh ? '' : 'disabled'}>${manualRefreshLabel}</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
            const pagination = resourceState?.job_pagination && typeof resourceState.job_pagination === 'object'
                ? resourceState.job_pagination
                : {};
            const loadedCount = Number(pagination.next_offset ?? visibleJobs.length) || visibleJobs.length;
            const totalCount = Number(pagination.total ?? counts.total) || 0;
            const loadMoreHtml = pagination.has_more && pageStatus === normalizedFilter
                ? `
                    <div class="resource-browser-load-more-row">
                        <button
                            type="button"
                            data-resource-job-action="load-more"
                            class="resource-browser-load-more-btn ${resourceJobLoadingMore ? 'btn-disabled' : ''}"
                            ${resourceJobLoadingMore ? 'disabled' : ''}
                        >${resourceJobLoadingMore ? '加载中...' : `加载更多任务（${escapeHtml(String(loadedCount))}/${escapeHtml(String(totalCount))}）`}</button>
                    </div>
                `
                : '';
            container.innerHTML = `${rowsHtml}${loadMoreHtml}`;
        }

        function syncResourceJobModalTrigger() {
            const btn = document.getElementById('resource-job-modal-toggle');
            const badge = document.getElementById('resource-job-modal-badge');
            if (!btn || !badge) return;
            const jobs = Array.isArray(resourceState.jobs) ? resourceState.jobs : [];
            const pageActiveCount = jobs.filter(job => ['pending', 'running', 'submitted'].includes(String(job?.status || '').toLowerCase())).length;
            const activeCount = Number(resourceState?.job_counts?.active ?? resourceState?.stats?.active_job_count ?? pageActiveCount) || 0;
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
            const jobCounts = getResourceJobCounts(resourceState.jobs || []);
            const completedCount = Number(resourceState?.stats?.completed_job_count ?? jobCounts.completed ?? 0);
            const failedCount = Number(resourceState?.stats?.failed_job_count ?? jobCounts.failed ?? 0);
            const terminalCount = completedCount + failedCount;

            const toggleBtn = document.getElementById('resource-job-clear-toggle');
            if (toggleBtn) {
                toggleBtn.textContent = terminalCount > 0 ? `清空（${terminalCount}）` : '清空';
                toggleBtn.disabled = terminalCount <= 0;
                toggleBtn.classList.toggle('btn-disabled', terminalCount <= 0);
            }

            const completedBtn = document.getElementById('resource-clear-completed-btn');
            if (completedBtn) {
                completedBtn.textContent = completedCount > 0 ? `清空已完成（${completedCount}）` : '清空已完成';
                completedBtn.disabled = completedCount <= 0;
                completedBtn.classList.toggle('btn-disabled', completedCount <= 0);
            }
            const failedBtn = document.getElementById('resource-clear-failed-btn');
            if (failedBtn) {
                failedBtn.textContent = failedCount > 0 ? `清空失败（${failedCount}）` : '清空失败';
                failedBtn.disabled = failedCount <= 0;
                failedBtn.classList.toggle('btn-disabled', failedCount <= 0);
            }
            const terminalBtn = document.getElementById('resource-clear-terminal-btn');
            if (terminalBtn) {
                terminalBtn.textContent = terminalCount > 0 ? `清空完成+失败（${terminalCount}）` : '清空完成+失败';
                terminalBtn.disabled = terminalCount <= 0;
                terminalBtn.classList.toggle('btn-disabled', terminalCount <= 0);
            }

            if (terminalCount <= 0) closeResourceJobClearMenu();
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
                void fetchResourceJobsPage({ status: resourceJobFilter, offset: 0 });
            } else {
                closeResourceJobClearMenu();
                unlockPageScroll();
            }
            syncResourceJobModalTrigger();
        }
