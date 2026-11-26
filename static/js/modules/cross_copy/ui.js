(function (global) {
    'use strict';

    const STATUS_LABELS = {
        pending: '排队中',
        running: '复制中',
        completed: '已完成',
        partial: '部分完成',
        failed: '失败',
        cancelled: '已取消',
        skipped: '已跳过',
        paused: '已暂停',
    };

    const PHASE_LABELS = {
        pending: '排队中',
        resolving: '获取下载地址',
        download: '下载',
        downloading: '下载',
        hashing: '校验',
        rapid: '秒传尝试',
        upload: '上传',
        uploading: '上传',
        verifying: '校验',
        done: '完成',
        skipped: '已跳过',
    };

    const FILTERS = [
        { value: 'all', label: '全部' },
        { value: 'active', label: '处理中' },
        { value: 'completed', label: '已完成' },
        { value: 'failed', label: '失败' },
        { value: 'cancelled', label: '已取消' },
    ];

    const state = {
        jobs: [],
        loading: false,
        loaded: false,
        error: '',
        capabilities: null,
        capabilitiesError: '',
        capabilitiesPromise: null,
        filter: 'all',
        modalOpen: false,
        submitting: false,
        submitProgress: null,
        summaryNote: '',
        // 整表计数（服务端给）：列表只回最近 100 条，而「清空」清的是整表，
        // 菜单角标必须用整表数字，不然会出现"显示还有 N 条却清不掉"。
        counts: null,
        source: createPane('source'),
        target: createPane('target'),
    };

    function createPane(side) {
        return {
            side,
            provider: '',
            cid: '0',
            trail: [{ cid: '0', name: '根目录' }],
            entries: [],
            loading: false,
            error: '',
            // 源侧勾选的文件（可多选）与「整个文件夹」二选一，互斥
            selectedItems: [],
            selectedFolder: null,
            requestTicket: 0,
        };
    }

    function escapeHtml(value) {
        if (typeof global.escapeHtml === 'function') return global.escapeHtml(value);
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatSize(value) {
        const size = Number(value || 0) || 0;
        if (size <= 0) return '--';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let next = size;
        let unit = 0;
        while (next >= 1024 && unit < units.length - 1) {
            next /= 1024;
            unit += 1;
        }
        return `${next >= 100 || unit === 0 ? Math.round(next) : next.toFixed(1)}${units[unit]}`;
    }

    function currentTaskCenterTab() {
        try {
            return typeof taskCenterTab === 'string' ? taskCenterTab : '';
        } catch (error) {
            return '';
        }
    }

    function providerLabel(name) {
        const key = String(name || '').trim();
        const providers = Array.isArray(state.capabilities?.providers) ? state.capabilities.providers : [];
        const matched = providers.find(item => String(item?.name || '') === key);
        if (matched?.label) return String(matched.label);
        // capabilities 只覆盖能做跨盘复制的网盘（115/夸克/阿里）。任务里的来源网盘
        // 可能是别的（天翼、123），这时退到全量 providerMeta，最后才用静态表，
        // 避免把内部代号 tianyi 这种直接显示给用户。
        const meta = (window.providerMeta || []).find(item => String(item?.name || '') === key);
        if (meta && meta.label) return String(meta.label);
        const fallback = {
            '115': '115网盘',
            quark: '夸克网盘',
            aliyun: '阿里云盘',
            tianyi: '天翼云盘',
            '123pan': '123 网盘',
        };
        return fallback[key] || key || '未知网盘';
    }

    function getJobCounts(jobs) {
        const list = Array.isArray(jobs) ? jobs : [];
        const statusOf = job => String(job?.status || '').toLowerCase();
        return {
            total: list.length,
            active: list.filter(job => ['pending', 'running'].includes(statusOf(job))).length,
            completed: list.filter(job => statusOf(job) === 'completed').length,
            failed: list.filter(job => statusOf(job) === 'failed').length,
            cancelled: list.filter(job => statusOf(job) === 'cancelled').length,
            skipped: list.filter(job => statusOf(job) === 'skipped').length,
        };
    }

    function fetchJobCounts() {
        // 服务端数字优先；拿不到就按当前列表估算（只影响角标，不影响能否清空）
        return state.counts || getJobCounts(state.jobs);
    }

    function getActiveCount() {
        return getJobCounts(state.jobs).active;
    }

    function isJobVisible(job, filter) {
        const status = String(job?.status || '').toLowerCase();
        if (filter === 'active') return ['pending', 'running'].includes(status);
        if (filter === 'completed') return status === 'completed';
        if (filter === 'failed') return status === 'failed';
        if (filter === 'cancelled') return status === 'cancelled';
        return true;
    }

    function getProgressPercent(job) {
        const raw = Number(job?.progress_percent ?? job?.progress?.percent ?? 0) || 0;
        return Math.max(0, Math.min(100, Math.round(raw)));
    }

    function joinPanPath(dir, name) {
        const segments = [];
        [dir, name].forEach(part => {
            const text = String(part == null ? '' : part).trim().replace(/^\/+|\/+$/g, '');
            if (text) segments.push(text);
        });
        return segments.length ? `/${segments.join('/')}` : '';
    }

    // 传输量按两位小数显示（1.12GB / 2.61GB），比文件大小的取整更适合看进度
    function formatTransferSize(value) {
        const size = Number(value || 0) || 0;
        if (size <= 0) return '0B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let next = size;
        let unit = 0;
        while (next >= 1024 && unit < units.length - 1) {
            next /= 1024;
            unit += 1;
        }
        return unit === 0 ? `${Math.round(next)}B` : `${next.toFixed(2)}${units[unit]}`;
    }

    function formatSpeed(value) {
        const speed = Number(value || 0) || 0;
        if (speed <= 0) return '';
        return `${formatTransferSize(speed)}/s`;
    }

    function formatTransfer(sent, total) {
        const done = Number(sent || 0) || 0;
        const all = Number(total || 0) || 0;
        if (all > 0) return `${formatTransferSize(done)} / ${formatTransferSize(all)}`;
        return done > 0 ? formatTransferSize(done) : '';
    }

    function getTransferInfo(job) {
        const progress = job && typeof job.progress === 'object' && job.progress ? job.progress : {};
        const phase = String(job?.phase || progress.phase || '').toLowerCase();
        return {
            phase,
            sent: Number(progress.sent ?? 0) || 0,
            total: Number(progress.total ?? job?.file_size ?? 0) || 0,
            speed: Number(progress.speed ?? 0) || 0,
        };
    }

    function getTransferLine(job) {
        const info = getTransferInfo(job);
        if (!['download', 'downloading', 'upload', 'uploading', 'hashing', 'verifying'].includes(info.phase)) return '';
        const action = info.phase.startsWith('up') ? '已上传' : (info.phase.startsWith('down') ? '已下载' : '已处理');
        const amount = formatTransfer(info.sent, info.total);
        const speed = formatSpeed(info.speed);
        if (!amount && !speed) return '';
        return [amount ? `${action} ${amount}` : '', speed].filter(Boolean).join(' · ');
    }

    function getStatusText(job) {
        const status = String(job?.status || '').toLowerCase();
        if (status === 'running') {
            const phase = String(job?.phase || job?.progress?.phase || '').toLowerCase();
            const phaseLabel = PHASE_LABELS[phase] || '';
            const percent = getProgressPercent(job);
            if (phaseLabel) return percent > 0 ? `${phaseLabel} ${percent}%` : phaseLabel;
        }
        return STATUS_LABELS[status] || status || '--';
    }

    function getStatusBadgeClass(status) {
        const normalized = String(status || '').toLowerCase();
        if (normalized === 'completed') return 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/25';
        if (normalized === 'partial') return 'bg-amber-500/15 text-amber-200 border border-amber-500/25';
        if (normalized === 'failed') return 'bg-rose-500/15 text-rose-300 border border-rose-500/25';
        if (normalized === 'cancelled') return 'bg-slate-600/40 text-slate-300 border border-slate-500/30';
        if (normalized === 'paused') return 'bg-violet-500/15 text-violet-200 border border-violet-500/25';
        if (normalized === 'skipped') return 'bg-sky-500/15 text-sky-200 border border-sky-500/25';
        if (normalized === 'running') return 'bg-sky-500/15 text-sky-200 border border-sky-500/25';
        return 'bg-amber-500/15 text-amber-200 border border-amber-500/25';
    }

    function renderTypeTabs() {
        if (typeof global.renderTaskCenterTypeTabs === 'function') {
            global.renderTaskCenterTypeTabs();
        }
    }

    function renderFilters(counts) {
        const container = document.getElementById('resource-job-filter-tabs');
        if (!container) return;
        const totals = counts || getJobCounts(state.jobs);
        container.innerHTML = FILTERS.map(option => {
            const count = option.value === 'all' ? totals.total : Number(totals[option.value] || 0);
            return `
                <button
                    type="button"
                    data-cross-copy-filter="${escapeHtml(option.value)}"
                    class="resource-job-filter-tab ${state.filter === option.value ? 'resource-job-filter-tab-active' : ''}"
                >${escapeHtml(option.label)} (${escapeHtml(String(count))})</button>
            `;
        }).join('');
    }

    function buildJobCard(job) {
        const jobId = Number(job?.id || 0) || 0;
        const rawStatus = String(job?.status || '').toLowerCase();
        const result = job?.result && typeof job.result === 'object' ? job.result : {};
        const resultStatus = String(result.status || '').trim();
        const isFolderJob = Number(job?.source_is_dir || 0) === 1;
        // 文件夹任务「部分文件失败」：任务本身算完成，但卡片要如实显示「部分完成」
        const status = rawStatus === 'completed' && resultStatus === 'partial' ? 'partial' : rawStatus;
        const percent = getProgressPercent(job);
        const canCancel = ['pending', 'running'].includes(status);
        const canPause = status === 'running';
        const canResume = status === 'paused';
        const canRetry = ['failed', 'cancelled', 'skipped'].includes(status) || status === 'partial';
        // 已结束的任务才允许删记录（在跑的删了会让进度无处可写）
        const canDelete = !canCancel;
        const source = providerLabel(job?.source_provider);
        const target = providerLabel(job?.target_provider);
        const filename = String(job?.filename || job?.title || `任务 #${jobId}`).trim();
        const detail = String(job?.error_message || job?.status_detail || '').trim();
        // 非 115 目标没有监控任务接手，后端在 result 里带了说明，这里单独一行显示：
        // resultHint 会盖住 status_detail，塞进同一行就看不见了。
        const noMonitorNote = String(result.no_monitor_note || '').trim();
        const targetPath = String(job?.target_savepath || '').trim();
        const sourceFilePath = String(job?.source_path || '').trim() || filename;
        const targetFilePath = String(job?.target_path || '').trim()
            || joinPanPath(targetPath, filename);
        const originLabel = String(job?.origin || 'manual') === 'subscription' ? '订阅补源' : '手动复制';
        const sizeText = formatSize(job?.file_size);
        const created = String(job?.created_at || '').trim();
        const finished = String(job?.finished_at || '').trim();
        const elapsedMs = Number(result.elapsed_ms || 0) || 0;
        const elapsedText = elapsedMs > 0 ? `（${elapsedMs >= 1000 ? `${(elapsedMs / 1000).toFixed(1)} 秒` : `${elapsedMs} 毫秒`}）` : '';
        const filesTotal = Number(result.files_total || 0) || 0;
        const filesSkipped = Number(result.files_skipped || 0) || 0;
        const filesFailed = Number(result.files_failed || 0) || 0;
        let resultHint = '';
        if (status === 'partial') {
            resultHint = `部分完成：共 ${filesTotal} 个文件，${filesFailed} 个失败${elapsedText}`;
        } else if (status === 'completed') {
            if (resultStatus === 'rapid') {
                resultHint = `秒传命中，未消耗上传流量${elapsedText}`;
            } else if (resultStatus === 'skipped') {
                resultHint = `目标已有同名同大小文件，已跳过${elapsedText}`;
            } else if (isFolderJob) {
                resultHint = filesTotal > 0
                    ? `整个文件夹复制完成：共 ${filesTotal} 个文件${filesSkipped ? `（${filesSkipped} 个目标已有、跳过）` : ''}${elapsedText}`
                    : `文件夹里没有文件，已在目标网盘建好目录${elapsedText}`;
            } else {
                resultHint = `复制完成${elapsedText}`;
            }
        }
        const transferLine = getTransferLine(job);
        const progressBlock = ['pending', 'running'].includes(status) || percent > 0
            ? `
                <div class="cc-job-progress">
                    <div class="cc-job-progress-head">
                        <span>${escapeHtml(getStatusText(job))}</span>
                        <span>${escapeHtml(String(percent))}%</span>
                    </div>
                    <div class="cc-job-progress-track"><span style="width:${escapeHtml(String(percent))}%"></span></div>
                    ${transferLine ? `<div class="cc-job-progress-meta">${escapeHtml(transferLine)}</div>` : ''}
                </div>
            `
            : '';
        return `
            <div class="resource-job-card cc-job-card">
                <div class="resource-job-card-head">
                    <div class="min-w-0 flex-1">
                        <div class="flex flex-wrap items-center gap-2">
                            <div class="resource-job-card-title">${escapeHtml(filename)}</div>
                            <span class="text-[10px] px-3 py-1 rounded-full ${getStatusBadgeClass(status)}">${escapeHtml(STATUS_LABELS[status] || status || '--')}</span>
                            ${isFolderJob ? '<span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/15 text-sky-200 border border-sky-500/20">📁 文件夹</span>' : ''}
                            <span class="text-[10px] px-3 py-1 rounded-full bg-violet-500/15 text-violet-200 border border-violet-500/20">${escapeHtml(originLabel)}</span>
                            <span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-100">#${escapeHtml(String(jobId))}</span>
                        </div>
                        ${progressBlock}
                        <div class="resource-job-card-grid">
                            <div class="resource-job-field">
                                <div class="resource-job-field-label">${isFolderJob ? '源文件夹' : '源文件'}</div>
                                <div class="resource-job-field-value" title="${escapeHtml(`${source} · ${sourceFilePath}`)}">${escapeHtml(source)} · ${escapeHtml(sourceFilePath || '--')}</div>
                            </div>
                            <div class="resource-job-field">
                                <div class="resource-job-field-label">${isFolderJob ? '目标文件夹' : '目标文件'}</div>
                                <div class="resource-job-field-value" title="${escapeHtml(`${target} · ${targetFilePath || '根目录'}`)}">${escapeHtml(target)} · ${escapeHtml(targetFilePath || '根目录')}</div>
                            </div>
                            <div class="resource-job-field">
                                <div class="resource-job-field-label">${isFolderJob ? '总大小' : '文件大小'}</div>
                                <div class="resource-job-field-value">${escapeHtml(sizeText)}</div>
                            </div>
                            <div class="resource-job-field">
                                <div class="resource-job-field-label">时间</div>
                                <div class="resource-job-field-value">${escapeHtml(created || '--')}${finished ? ` → ${escapeHtml(finished)}` : ''}</div>
                            </div>
                        </div>
                        <div class="resource-job-status-note">${escapeHtml(resultHint || detail || '--')}</div>
                        ${noMonitorNote ? `<div class="resource-job-status-note">${escapeHtml(noMonitorNote)}</div>` : ''}
                    </div>
                </div>
                <div class="resource-job-card-actions">
                    <div class="flex flex-wrap gap-2 min-w-0 flex-1 justify-end">
                        ${canResume ? `<button type="button" data-cross-copy-action="resume" data-cross-copy-job-id="${escapeHtml(String(jobId))}" class="px-4 py-2 rounded-xl text-sm font-bold bg-emerald-600 hover:bg-emerald-500 text-white">继续</button>` : ''}
                        ${canPause ? `<button type="button" data-cross-copy-action="pause" data-cross-copy-job-id="${escapeHtml(String(jobId))}" class="px-4 py-2 rounded-xl text-sm font-bold bg-violet-600 hover:bg-violet-500 text-white">暂停</button>` : ''}
                        <button type="button" data-cross-copy-action="cancel" data-cross-copy-job-id="${escapeHtml(String(jobId))}" class="px-4 py-2 rounded-xl text-sm font-bold ${canCancel ? 'bg-amber-600 hover:bg-amber-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canCancel ? '' : 'disabled'}>${canCancel ? '取消' : '不可取消'}</button>
                        <button type="button" data-cross-copy-action="retry" data-cross-copy-job-id="${escapeHtml(String(jobId))}" class="px-4 py-2 rounded-xl text-sm font-bold ${canRetry ? 'bg-emerald-600 hover:bg-emerald-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canRetry ? '' : 'disabled'}>${canRetry ? '重试' : '不可重试'}</button>
                        ${canDelete ? `<button type="button" data-cross-copy-action="delete" data-cross-copy-job-id="${escapeHtml(String(jobId))}" class="px-4 py-2 rounded-xl text-sm font-bold bg-slate-700 hover:bg-rose-600 text-slate-100" title="只删除这条任务记录，不删除网盘上的文件">删除记录</button>` : ''}
                    </div>
                </div>
            </div>
        `;
    }

    function renderJobs() {
        const container = document.getElementById('resource-job-list');
        if (!container) return;
        renderTypeTabs();
        const counts = getJobCounts(state.jobs);
        renderFilters(counts);
        if (state.loading && !state.jobs.length) {
            container.innerHTML = '<div class="resource-job-card-empty">正在读取跨盘复制任务...</div>';
            return;
        }
        if (state.error && !state.jobs.length) {
            container.innerHTML = `
                <div class="resource-browser-load-more-row" role="alert">
                    <div class="resource-job-status-note text-red-300">${escapeHtml(state.error)}</div>
                    <button type="button" data-cross-copy-action="reload" class="resource-browser-load-more-btn">重新加载</button>
                </div>
            `;
            return;
        }
        const visible = state.jobs.filter(job => isJobVisible(job, state.filter));
        if (!visible.length) {
            const emptyText = state.filter === 'active'
                ? '当前没有正在复制的任务。'
                : (state.filter === 'all' ? '还没有跨盘复制任务。点右上角「新建复制」从其他网盘挑一个文件复制过来。' : '当前筛选下没有任务。');
            container.innerHTML = `<div class="resource-job-card-empty">${escapeHtml(emptyText)}</div>`;
            return;
        }
        container.innerHTML = visible.map(buildJobCard).join('');
    }

    async function fetchCapabilities() {
        if (state.capabilities) return state.capabilities;
        if (state.capabilitiesPromise) return state.capabilitiesPromise;
        state.capabilitiesPromise = (async () => {
            try {
                const data = await global.MediaHubApi.getJson('/cross_copy/capabilities');
                state.capabilities = data;
                state.capabilitiesError = '';
                return data;
            } catch (error) {
                state.capabilitiesError = error?.message || '读取跨盘复制能力失败';
                return null;
            } finally {
                state.capabilitiesPromise = null;
            }
        })();
        return state.capabilitiesPromise;
    }

    async function fetchJobs(options) {
        const opts = options || {};
        state.loading = true;
        state.error = '';
        if (!opts.silent && currentTaskCenterTab() === 'cross_copy') renderJobs();
        try {
            const data = await global.MediaHubApi.getJson('/cross_copy/jobs?limit=100');
            state.jobs = Array.isArray(data?.jobs) ? data.jobs : [];
            if (data?.counts && typeof data.counts === 'object') state.counts = data.counts;
            state.loaded = true;
        } catch (error) {
            state.error = error?.message || '读取跨盘复制任务失败';
            if (!opts.silent && currentTaskCenterTab() === 'cross_copy') {
                if (typeof global.showToast === 'function') {
                    global.showToast(`读取跨盘复制任务失败：${state.error}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                }
            }
        } finally {
            state.loading = false;
            if (currentTaskCenterTab() === 'cross_copy') renderJobs();
            if (typeof global.syncResourceJobModalTrigger === 'function') {
                global.syncResourceJobModalTrigger();
            }
        }
        return state.jobs;
    }

    function setFilter(value) {
        const normalized = String(value || 'all').trim() || 'all';
        state.filter = FILTERS.some(item => item.value === normalized) ? normalized : 'all';
        renderJobs();
    }

    async function cancelJob(jobId) {
        if (!(await global.showAppConfirm('取消这个复制任务吗？上传中取消可能残留未完成分片；重试时会自动续传。'))) return;
        try {
            await global.MediaHubApi.postJson(`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/cancel`, {});
            if (typeof global.showToast === 'function') {
                global.showToast('已请求取消', { tone: 'info', duration: 2400, placement: 'top-center' });
            }
            await fetchJobs({ silent: true });
        } catch (error) {
            if (typeof global.showToast === 'function') {
                global.showToast(`取消失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }
    }

    async function pauseJob(jobId) {
        if (!(await global.showAppConfirm('暂停这个复制任务吗？会在当前分片结束后停下，已下载的部分会保留，继续时从断点续传。'))) return;
        try {
            await global.MediaHubApi.postJson(`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/pause`, {});
            if (typeof global.showToast === 'function') {
                global.showToast('已请求暂停', { tone: 'info', duration: 2400, placement: 'top-center' });
            }
            await fetchJobs({ silent: true });
        } catch (error) {
            if (typeof global.showToast === 'function') {
                global.showToast(`暂停失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }
    }

    async function resumeJob(jobId) {
        try {
            await global.MediaHubApi.postJson(`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/resume`, {});
            if (typeof global.showToast === 'function') {
                global.showToast('已重新排队，从断点续传', { tone: 'success', duration: 2600, placement: 'top-center' });
            }
            await fetchJobs({ silent: true });
        } catch (error) {
            if (typeof global.showToast === 'function') {
                global.showToast(`继续失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }
    }

    async function retryJob(jobId) {
        try {
            await global.MediaHubApi.postJson(`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/retry`, {});
            if (typeof global.showToast === 'function') {
                global.showToast('已重新排队，进度见任务中心', { tone: 'success', duration: 2600, placement: 'top-center' });
            }
            await fetchJobs({ silent: true });
        } catch (error) {
            if (typeof global.showToast === 'function') {
                global.showToast(`重试失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }
    }

    async function deleteJobRecord(jobId) {
        const ok = await global.showAppConfirm('删除这条任务记录？只删记录，网盘上的文件不受影响。');
        if (!ok) return;
        try {
            await global.MediaHubApi.postJson(`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/delete`, {});
            if (typeof global.showToast === 'function') {
                global.showToast('已删除任务记录', { tone: 'success', duration: 2400, placement: 'top-center' });
            }
            await fetchJobs({ silent: true });
        } catch (error) {
            if (typeof global.showToast === 'function') {
                global.showToast(`删除失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }
    }

    const CLEAR_SCOPE_META = {
        completed: { label: '已完成', emptyText: '当前没有可清空的已完成复制记录' },
        failed: { label: '失败', emptyText: '当前没有可清空的失败复制记录' },
        terminal: { label: '已结束', emptyText: '当前没有可清空的已结束复制记录' },
    };

    function getClearScopeCount(scope) {
        const counts = fetchJobCounts();
        if (scope === 'completed') return Number(counts.completed || 0);
        if (scope === 'failed') return Number(counts.failed || 0);
        return Number(counts.terminal || 0)
            || ['completed', 'failed', 'cancelled', 'skipped'].reduce((sum, key) => sum + Number(counts[key] || 0), 0);
    }

    /** 任务中心「清空」菜单用：按范围批量清除已结束的任务记录。 */
    async function clearJobs(scope) {
        const normalized = CLEAR_SCOPE_META[scope] ? scope : 'terminal';
        const meta = CLEAR_SCOPE_META[normalized];
        const count = getClearScopeCount(normalized);
        if (count <= 0) {
            if (typeof global.showToast === 'function') {
                global.showToast(meta.emptyText, { tone: 'warn', duration: 2600, placement: 'top-center' });
            }
            return 0;
        }
        const ok = await global.showAppConfirm(
            `将清空 ${count} 条${meta.label}的跨盘复制记录。只删除任务记录，网盘上的文件与正在执行的任务不受影响。继续吗？`
        );
        if (!ok) return 0;
        try {
            const data = await global.MediaHubApi.postJson('/cross_copy/jobs/clear', { scope: normalized });
            await fetchJobs({ silent: true });
            const deleted = Number(data?.deleted || 0);
            if (typeof global.showToast === 'function') {
                global.showToast(
                    deleted > 0 ? `已清空 ${deleted} 条${meta.label}记录` : meta.emptyText,
                    { tone: deleted > 0 ? 'success' : 'info', duration: 2600, placement: 'top-center' }
                );
            }
            return deleted;
        } catch (error) {
            if (typeof global.showToast === 'function') {
                global.showToast(`清空失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
            return 0;
        }
    }

    // ---------- 新建复制弹窗 ----------

    function paneEl(side, suffix) {
        return document.getElementById(`cross-copy-${side}-${suffix}`);
    }

    function renderProviderSelects() {
        const providers = Array.isArray(state.capabilities?.providers) ? state.capabilities.providers : [];
        const sourceSelect = paneEl('source', 'provider');
        const targetSelect = paneEl('target', 'provider');
        if (sourceSelect) {
            const sourceOptions = providers.filter(item => item.can_be_source);
            sourceSelect.innerHTML = sourceOptions.length
                ? sourceOptions.map(item => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.label || item.name)}</option>`).join('')
                : '<option value="">暂无可用的源网盘</option>';
            sourceSelect.value = state.source.provider;
        }
        if (targetSelect) {
            const targetOptions = providers.filter(item => item.can_be_target && String(item.name) !== String(state.source.provider));
            targetSelect.innerHTML = targetOptions.length
                ? targetOptions.map(item => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.label || item.name)}</option>`).join('')
                : '<option value="">暂无可用的目标网盘</option>';
            targetSelect.value = state.target.provider;
        }
    }

    function renderTrail(side) {
        const container = paneEl(side, 'trail');
        if (!container) return;
        const pane = state[side];
        container.innerHTML = pane.trail.map((item, index) => {
            const isLast = index === pane.trail.length - 1;
            return `
                <button type="button" data-cc-trail="${side}" data-cc-trail-index="${index}" class="cc-trail-btn ${isLast ? 'is-current' : ''}" ${isLast ? 'disabled' : ''}>${escapeHtml(item.name || '根目录')}</button>
                ${isLast ? '' : '<span class="cc-trail-sep">/</span>'}
            `;
        }).join('');
    }

    function paneEntries(pane) {
        if (pane.side === 'target') {
            return pane.entries.filter(entry => !!entry?.is_dir);
        }
        return pane.entries;
    }

    function entryKey(entry) {
        return String(entry?.id || entry?.cid || '').trim();
    }

    // 当前勾选的文件快照（外部只读，避免直接改到 state 里的数组）
    function getSelectedItems() {
        return Array.isArray(state.source.selectedItems) ? state.source.selectedItems.slice() : [];
    }

    // 当前选中的整个文件夹（与文件勾选互斥，同一时间最多一个）
    function getSelectedFolder() {
        const folder = state.source.selectedFolder;
        return folder && folder.id ? folder : null;
    }

    function sourceSelectedIds() {
        return new Set(getSelectedItems().map(item => String(item?.id || '')));
    }

    function selectedTotalSize() {
        return getSelectedItems().reduce((sum, item) => sum + (Number(item?.size) || 0), 0);
    }

    function renderPaneList(side) {
        const container = paneEl(side, 'list');
        if (!container) return;
        const pane = state[side];
        if (pane.loading) {
            container.innerHTML = '<div class="cc-list-empty">正在读取目录...</div>';
            if (side === 'source') syncSourceSelectionBar();
            return;
        }
        if (pane.error) {
            container.innerHTML = `<div class="cc-list-empty cc-list-error">${escapeHtml(pane.error)}</div>`;
            if (side === 'source') syncSourceSelectionBar();
            return;
        }
        const entries = paneEntries(pane);
        if (!entries.length) {
            container.innerHTML = `<div class="cc-list-empty">${side === 'source' ? '这个目录里没有文件' : '这个目录里没有子目录'}</div>`;
            if (side === 'source') syncSourceSelectionBar();
            return;
        }
        const selectedIds = side === 'source' ? sourceSelectedIds() : new Set();
        const selectedFolder = side === 'source' ? getSelectedFolder() : null;
        container.innerHTML = entries.map(entry => {
            const entryId = entryKey(entry);
            const isDir = !!entry?.is_dir;
            // 源侧文件和文件夹都能选（选文件夹 = 整个文件夹复制），目标侧只用来进入目录
            const selectable = side === 'source' && !!entryId;
            const isSelected = selectable
                && (isDir ? String(selectedFolder?.id || '') === entryId : selectedIds.has(entryId));
            const icon = isDir ? '📁' : '🎬';
            const meta = isDir ? '文件夹' : formatSize(entry?.size);
            const check = selectable
                ? '<span class="cc-entry-check" aria-hidden="true">✓</span>'
                : '';
            // 源侧文件夹：整行是「选中」，右侧单独给一个「进入」小按钮
            const enter = side === 'source' && isDir && entryId
                ? '<span class="cc-entry-enter" data-cc-enter="1" title="进入这个文件夹">进入 ›</span>'
                : '';
            return `
                <button type="button" class="cc-entry ${isSelected ? 'is-selected' : ''}" data-cc-entry="${side}" data-cc-entry-id="${escapeHtml(entryId)}" data-cc-entry-dir="${isDir ? '1' : '0'}"${selectable ? ` aria-pressed="${isSelected ? 'true' : 'false'}"` : ''}>
                    <span class="cc-entry-icon" aria-hidden="true">${icon}</span>
                    <span class="cc-entry-name">${escapeHtml(entry?.name || '未命名')}</span>
                    <span class="cc-entry-meta">${escapeHtml(meta)}</span>
                    ${enter}
                    ${check}
                </button>
            `;
        }).join('');
        if (side === 'source') syncSourceSelectionBar();
    }

    // 源侧顶部：已选数量 / 合计大小 + 全选本页 / 清空选择
    function syncSourceSelectionBar() {
        const countEl = document.getElementById('cross-copy-source-selection');
        const selectAllBtn = document.getElementById('cross-copy-select-all');
        const clearBtn = document.getElementById('cross-copy-clear-selection');
        const items = getSelectedItems();
        const folder = getSelectedFolder();
        const total = selectedTotalSize();
        if (countEl) {
            if (folder) {
                countEl.textContent = `已选文件夹「${folder.name || '未命名'}」· 文件数待统计`;
            } else {
                countEl.textContent = items.length
                    ? `已选 ${items.length} 个${total > 0 ? ` · 合计 ${formatSize(total)}` : ''}`
                    : '还没有选择文件';
            }
        }
        const filesInView = paneEntries(state.source).filter(entry => !entry?.is_dir && entryKey(entry));
        if (selectAllBtn) {
            const canSelectAll = filesInView.length > 0
                && !folder
                && sourceSelectedIds().size < filesInView.length;
            selectAllBtn.disabled = !canSelectAll;
            selectAllBtn.classList.toggle('btn-disabled', !canSelectAll);
        }
        if (clearBtn) {
            const hasAny = items.length > 0 || !!folder;
            clearBtn.disabled = !hasAny;
            clearBtn.classList.toggle('btn-disabled', !hasAny);
        }
    }

    // 点源侧文件是切换勾选（再点一次取消）；选文件时把已选文件夹清掉
    function toggleSourceSelection(entryId) {
        const id = String(entryId || '').trim();
        if (!id) return;
        const entry = paneEntryById('source', id);
        if (!entry || entry.is_dir) return;
        const items = getSelectedItems();
        const index = items.findIndex(item => item.id === id);
        if (index >= 0) {
            items.splice(index, 1);
        } else {
            items.push({
                id,
                name: String(entry?.name || ''),
                size: Number(entry?.size || 0) || 0,
            });
        }
        state.source.selectedItems = items;
        state.source.selectedFolder = null;
        state.summaryNote = '';
        renderPaneList('source');
        syncSummary();
    }

    // 点源侧文件夹是选中整个文件夹（再点一次取消）；选文件夹时把已勾选文件清掉
    function toggleSourceFolder(entryId) {
        const id = String(entryId || '').trim();
        if (!id) return;
        const entry = paneEntryById('source', id);
        if (!entry || !entry.is_dir) return;
        const current = getSelectedFolder();
        if (current && String(current.id) === id) {
            state.source.selectedFolder = null;
        } else {
            state.source.selectedFolder = { id, name: String(entry?.name || '') };
            state.source.selectedItems = [];
        }
        state.summaryNote = '';
        renderPaneList('source');
        syncSummary();
    }

    // 全选本页：把当前目录里的文件都勾上，已经勾上的不重复加（会清掉已选文件夹）
    function selectAllSourceFiles() {
        const items = getSelectedItems();
        const chosen = sourceSelectedIds();
        paneEntries(state.source).forEach(entry => {
            const id = entryKey(entry);
            if (!id || entry?.is_dir || chosen.has(id)) return;
            chosen.add(id);
            items.push({
                id,
                name: String(entry?.name || ''),
                size: Number(entry?.size || 0) || 0,
            });
        });
        state.source.selectedItems = items;
        state.source.selectedFolder = null;
        state.summaryNote = '';
        renderPaneList('source');
        syncSummary();
    }

    function clearSourceSelection() {
        state.source.selectedItems = [];
        state.source.selectedFolder = null;
        state.summaryNote = '';
        renderPaneList('source');
        syncSummary();
    }

    function syncSummary() {
        const summaryEl = document.getElementById('cross-copy-summary');
        const noteEl = document.getElementById('cross-copy-summary-note');
        const submitBtn = document.getElementById('cross-copy-submit');
        const items = getSelectedItems();
        const folder = getSelectedFolder();
        const targetPath = state.target.trail.map(item => item.name).filter((name, index) => index > 0 && name).join('/');
        if (summaryEl) {
            if (!folder && !items.length) {
                summaryEl.textContent = '请选择要复制的文件或文件夹';
            } else if (!state.target.provider) {
                summaryEl.textContent = '请选择目标网盘';
            } else {
                const head = `${providerLabel(state.source.provider)} → ${providerLabel(state.target.provider)}`;
                const tail = `保存到 ${targetPath || '根目录'}`;
                if (folder) {
                    // 文件夹里的文件数要等任务开始列目录才知道，这里不额外发请求统计
                    const meta = `文件夹「${folder.name || '未命名'}」· 待统计`;
                    summaryEl.innerHTML = `${escapeHtml(head)} · ${escapeHtml(meta)} · ${escapeHtml(tail)}`;
                } else if (items.length === 1) {
                    const only = items[0];
                    summaryEl.innerHTML = `${escapeHtml(head)} · ${escapeHtml(only.name || '')} · ${escapeHtml(formatSize(only.size))} · ${escapeHtml(tail)}`;
                } else {
                    const total = selectedTotalSize();
                    const meta = [
                        `已选 ${items.length} 个文件`,
                        total > 0 ? `合计 ${formatSize(total)}` : '',
                    ].filter(Boolean).join(' · ');
                    summaryEl.innerHTML = `${escapeHtml(head)} · ${escapeHtml(meta)} · ${escapeHtml(tail)}`;
                }
            }
        }
        if (noteEl) {
            noteEl.textContent = state.summaryNote || '';
            noteEl.classList.toggle('hidden', !state.summaryNote);
        }
        if (submitBtn) {
            const ready = (items.length > 0 || !!folder) && !!state.target.provider && !state.submitting;
            submitBtn.disabled = !ready;
            submitBtn.classList.toggle('btn-disabled', !ready);
            if (state.submitting) {
                const progress = state.submitProgress;
                submitBtn.textContent = progress
                    ? `正在创建任务 ${progress.index}/${progress.total}…`
                    : '正在创建任务…';
            } else {
                submitBtn.textContent = '开始复制';
            }
        }
    }

    function renderAll() {
        renderProviderSelects();
        renderTrail('source');
        renderTrail('target');
        renderPaneList('source');
        renderPaneList('target');
        syncSummary();
    }

    function resetPane(side, provider) {
        state[side] = createPane(side);
        state[side].provider = provider;
    }

    async function loadPane(side, cid, options) {
        const opts = options || {};
        const pane = state[side];
        const provider = pane.provider;
        if (!provider) {
            pane.entries = [];
            pane.error = '未选择网盘';
            renderAll();
            return;
        }
        pane.requestTicket += 1;
        const ticket = pane.requestTicket;
        pane.loading = true;
        pane.error = '';
        // 换了目录就清空勾选：勾选只对当前目录里的文件有意义（选中的文件夹同理）
        if (!opts.keepSelection) pane.selectedItems = [];
        if (!opts.keepSelection && side === 'source') pane.selectedFolder = null;
        renderPaneList(side);
        renderTrail(side);
        syncSummary();
        try {
            const params = new URLSearchParams({ cid: String(cid || '0'), compact: '1' });
            if (side === 'target') params.set('folders_only', '1');
            const data = await global.MediaHubApi.getJson(`/resource/browse/${encodeURIComponent(provider)}/folders?${params.toString()}`);
            if (ticket !== pane.requestTicket) return;
            pane.entries = Array.isArray(data?.entries) ? data.entries : [];
            pane.cid = String(cid || '0');
            if (opts.trailEntry) {
                pane.trail = pane.trail.slice(0, opts.trailIndex).concat([{ cid: String(cid || '0'), name: opts.trailEntry.name || '目录' }]);
            }
        } catch (error) {
            if (ticket !== pane.requestTicket) return;
            pane.entries = [];
            pane.error = error?.message || '读取目录失败';
        } finally {
            if (ticket === pane.requestTicket) {
                pane.loading = false;
                renderPaneList(side);
                renderTrail(side);
                syncSummary();
            }
        }
    }

    function paneEntryById(side, entryId) {
        const pane = state[side];
        return paneEntries(pane).find(entry => {
            const id = String(entry?.id || entry?.cid || '').trim();
            return id && id === entryId;
        }) || null;
    }

    function enterSourceFolder(entryId) {
        const entry = paneEntryById('source', entryId);
        state.source.trail = state.source.trail.concat([{ cid: entryId, name: entry?.name || '目录' }]);
        void loadPane('source', entryId, { trailEntry: { name: entry?.name }, trailIndex: state.source.trail.length - 1 });
    }

    function onEntryClick(side, entryId, isDir) {
        if (side === 'source') {
            // 源侧文件夹：整行是选中（整个文件夹复制），右侧「进入」才进目录
            if (isDir) {
                toggleSourceFolder(entryId);
                return;
            }
            toggleSourceSelection(entryId);
            return;
        }
        const entry = paneEntryById('target', entryId);
        state.target.trail = state.target.trail.concat([{ cid: entryId, name: entry?.name || '目录' }]);
        void loadPane('target', entryId, { trailEntry: { name: entry?.name }, trailIndex: state.target.trail.length - 1, keepSelection: true });
    }

    function onTrailClick(side, index) {
        const pane = state[side];
        const targetIndex = Math.max(0, Math.min(Number(index || 0), pane.trail.length - 1));
        if (targetIndex === pane.trail.length - 1) return;
        const nextTrail = pane.trail.slice(0, targetIndex + 1);
        pane.trail = nextTrail;
        void loadPane(side, nextTrail[targetIndex].cid, { keepSelection: side === 'target' });
    }

    async function syncProvidersFromCapabilities() {
        await fetchCapabilities();
        const providers = Array.isArray(state.capabilities?.providers) ? state.capabilities.providers : [];
        if (!state.source.provider) {
            const source = providers.find(item => item.can_be_source);
            state.source.provider = source ? String(source.name) : '';
        }
        if (!state.target.provider) {
            const target = providers.find(item => item.can_be_target && String(item.name) !== String(state.source.provider));
            state.target.provider = target ? String(target.name) : '';
        }
        if (state.target.provider && String(state.target.provider) === String(state.source.provider)) {
            const target = providers.find(item => item.can_be_target && String(item.name) !== String(state.source.provider));
            state.target.provider = target ? String(target.name) : '';
        }
    }

    async function openModal() {
        const modal = document.getElementById('cross-copy-modal');
        if (!modal) return;
        state.modalOpen = true;
        state.summaryNote = '';
        state.submitProgress = null;
        modal.classList.remove('hidden');
        if (typeof global.lockPageScroll === 'function') global.lockPageScroll();
        resetPane('source', '');
        resetPane('target', '');
        renderAll();
        const container = paneEl('source', 'list');
        if (container) container.innerHTML = '<div class="cc-list-empty">正在准备网盘信息...</div>';
        await syncProvidersFromCapabilities();
        renderAll();
        if (!state.source.provider) {
            const list = paneEl('source', 'list');
            if (list) list.innerHTML = '<div class="cc-list-empty cc-list-error">没有可用的源网盘（需要已启用并配置的夸克网盘）</div>';
            return;
        }
        await Promise.all([
            loadPane('source', '0'),
            state.target.provider ? loadPane('target', '0') : Promise.resolve(),
        ]);
    }

    function closeModal() {
        const modal = document.getElementById('cross-copy-modal');
        if (!modal) return;
        state.modalOpen = false;
        state.submitting = false;
        state.submitProgress = null;
        modal.classList.add('hidden');
        if (typeof global.unlockPageScroll === 'function') global.unlockPageScroll();
    }

    function onSourceProviderChange(value) {
        const provider = String(value || '').trim();
        if (!provider) return;
        state.source = createPane('source');
        state.source.provider = provider;
        if (String(state.target.provider) === provider) {
            const providers = Array.isArray(state.capabilities?.providers) ? state.capabilities.providers : [];
            const nextTarget = providers.find(item => item.can_be_target && String(item.name) !== provider);
            state.target = createPane('target');
            state.target.provider = nextTarget ? String(nextTarget.name) : '';
        }
        renderAll();
        void loadPane('source', '0');
        if (state.target.provider) void loadPane('target', '0');
    }

    function onTargetProviderChange(value) {
        const provider = String(value || '').trim();
        if (!provider) return;
        state.target = createPane('target');
        state.target.provider = provider;
        renderAll();
        void loadPane('target', '0');
    }

    // 逐个串行建任务：几个文件同时打 115 的秒传接口容易被挡，所以一个成功再发下一个。
    // 文件夹只建一个任务（任务内部逐个文件复制），不会被拆成多个。
    async function submitTask() {
        if (state.submitting) return;
        const folder = getSelectedFolder();
        // 文件夹当成一个「条目」塞进同一个提交循环，进度与失败重试逻辑保持一致
        const items = folder
            ? [{ id: folder.id, name: folder.name, size: 0, isDir: true }]
            : getSelectedItems();
        if (!items.length) {
            if (typeof global.showToast === 'function') global.showToast('请先选择要复制的文件或文件夹', { tone: 'warn', duration: 2600, placement: 'top-center' });
            return;
        }
        if (!state.target.provider) {
            if (typeof global.showToast === 'function') global.showToast('请选择目标网盘', { tone: 'warn', duration: 2600, placement: 'top-center' });
            return;
        }
        // 先取好提交用的快照，避免过程中弹窗状态变化影响后面几个文件
        const sourceProvider = state.source.provider;
        const targetProvider = state.target.provider;
        const targetDirId = state.target.cid || '0';
        const targetPath = state.target.trail.map(item => item.name).filter((name, index) => index > 0 && name).join('/');
        // 勾选只对当前目录有效（换目录会清空），所以这里的目录就是勾选时所在的目录
        const sourceDir = state.source.trail.map(item => item.name).filter((name, index) => index > 0 && name).join('/');
        state.submitting = true;
        state.summaryNote = '';
        state.submitProgress = { index: 1, total: items.length };
        syncSummary();

        let created = 0;
        const failedItems = [];
        let firstError = '';
        let stopped = false;
        try {
            for (let index = 0; index < items.length; index += 1) {
                // 用户关掉弹窗或点了取消，就不再继续发请求
                if (!state.modalOpen || !state.submitting) {
                    stopped = true;
                    break;
                }
                const item = items[index];
                state.submitProgress = { index: index + 1, total: items.length };
                syncSummary();
                try {
                    await global.MediaHubApi.postJson('/cross_copy/jobs', {
                        source_provider: sourceProvider,
                        target_provider: targetProvider,
                        source_file_id: item.id,
                        // 文件夹走整目录复制：一个任务，里面逐个文件处理
                        source_is_dir: !!item.isDir,
                        target_dir_id: targetDirId,
                        target_savepath: targetPath,
                        source_path: joinPanPath(sourceDir, item.name),
                        target_path: joinPanPath(targetPath, item.name),
                        filename: item.name,
                        file_size: item.size,
                        title: item.name,
                    });
                    created += 1;
                } catch (error) {
                    failedItems.push(item);
                    if (!firstError) firstError = `${item.name}：${error?.message || '创建失败'}`;
                }
            }
        } finally {
            state.submitting = false;
            state.submitProgress = null;
        }
        // 提交结束后先把按钮文案/禁用状态收回来，避免关掉弹窗时还停在「正在创建任务 2/3…」
        syncSummary();

        if (stopped) {
            // 弹窗已经被关掉，只把已经提交出去的任务刷出来
            if (created > 0) {
                state.filter = 'all';
                await fetchJobs({ silent: true });
                if (typeof global.showToast === 'function') {
                    global.showToast(`已停止创建，前面 ${created} 个任务已经提交`, { tone: 'info', duration: 3200, placement: 'top-center' });
                }
            }
            syncSummary();
            return;
        }

        if (!failedItems.length) {
            if (typeof global.showToast === 'function') {
                global.showToast(
                    created > 1 ? `已创建 ${created} 个跨盘复制任务，进度见任务中心` : '已创建跨盘复制任务，进度见任务中心',
                    { tone: 'success', duration: 3000, placement: 'top-center' }
                );
            }
            closeModal();
            state.filter = 'all';
            await fetchJobs({ silent: true });
            if (typeof global.syncResourceJobModalTrigger === 'function') global.syncResourceJobModalTrigger();
            return;
        }

        // 有失败：弹窗留着，把失败原因写在摘要下面，选中收缩到失败的那几个，方便再点一次重试
        const note = created > 0
            ? `成功 ${created} 个，失败 ${failedItems.length} 个：${firstError}`
            : `失败 ${failedItems.length} 个：${firstError}`;
        state.summaryNote = note;
        state.source.selectedItems = failedItems
            .filter(item => !item.isDir)
            .map(item => ({ id: item.id, name: item.name, size: item.size }));
        state.source.selectedFolder = failedItems.find(item => item.isDir) || null;
        renderPaneList('source');
        state.filter = 'all';
        await fetchJobs({ silent: true });
        if (typeof global.showToast === 'function') {
            global.showToast(note, { tone: 'error', duration: 5200, placement: 'top-center' });
        }
        syncSummary();
    }

    function handleClick(event) {
        const filterBtn = event.target.closest('[data-cross-copy-filter]');
        if (filterBtn) {
            setFilter(filterBtn.dataset.crossCopyFilter);
            return;
        }
        const actionBtn = event.target.closest('[data-cross-copy-action]');
        if (actionBtn) {
            const action = String(actionBtn.dataset.crossCopyAction || '').trim();
            if (action === 'reload') {
                void fetchJobs({});
                return;
            }
            const jobId = Number(actionBtn.dataset.crossCopyJobId || 0) || 0;
            if (!jobId) return;
            if (action === 'cancel') void cancelJob(jobId);
            if (action === 'pause') void pauseJob(jobId);
            if (action === 'resume') void resumeJob(jobId);
            if (action === 'retry') void retryJob(jobId);
            if (action === 'delete') void deleteJobRecord(jobId);
            return;
        }
        const entryBtn = event.target.closest('[data-cc-entry]');
        if (entryBtn) {
            const side = String(entryBtn.dataset.ccEntry || '');
            const entryId = String(entryBtn.dataset.ccEntryId || '');
            const isDir = String(entryBtn.dataset.ccEntryDir || '') === '1';
            // 源侧文件夹右侧的「进入 ›」才是进目录，点其他地方是选中文件夹
            if (side === 'source' && isDir && event.target.closest('[data-cc-enter]')) {
                enterSourceFolder(entryId);
                return;
            }
            onEntryClick(side, entryId, isDir);
            return;
        }
        const trailBtn = event.target.closest('[data-cc-trail]');
        if (trailBtn) {
            onTrailClick(String(trailBtn.dataset.ccTrail || ''), Number(trailBtn.dataset.ccTrailIndex || 0));
        }
    }

    document.addEventListener('click', handleClick);

    let refreshTimer = 0;
    let badgeTimer = 0;
    function scheduleRefresh() {
        if (refreshTimer) return;
        refreshTimer = global.setInterval(() => {
            if (document.hidden) return;
            if (!state.modalOpen || currentTaskCenterTab() !== 'cross_copy') return;
            void fetchJobs({ silent: true });
        }, 4000);
        badgeTimer = global.setInterval(() => {
            if (document.hidden) return;
            if (state.modalOpen) return;
            void fetchJobs({ silent: true });
        }, 30000);
        void badgeTimer;
    }

    function bootstrap() {
        void fetchJobs({ silent: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootstrap);
    } else {
        bootstrap();
    }

    global.crossCopyState = state;
    Object.assign(global, {
        fetchCrossCopyJobs: fetchJobs,
        fetchCrossCopyCapabilities: fetchCapabilities,
        renderCrossCopyJobs: renderJobs,
        getCrossCopyActiveCount: getActiveCount,
        getCrossCopyJobCounts: () => fetchJobCounts(),
        clearCrossCopyJobs: clearJobs,
        getCrossCopyClearScopeCount: getClearScopeCount,
        setCrossCopyFilter: setFilter,
        openCrossCopyModal: openModal,
        closeCrossCopyModal: closeModal,
        onCrossCopySourceProviderChange: onSourceProviderChange,
        onCrossCopyTargetProviderChange: onTargetProviderChange,
        submitCrossCopyTask: submitTask,
        selectAllCrossCopySources: selectAllSourceFiles,
        clearCrossCopySelection: clearSourceSelection,
        cancelCrossCopyJob: cancelJob,
        pauseCrossCopyJob: pauseJob,
        resumeCrossCopyJob: resumeJob,
        retryCrossCopyJob: retryJob,
        crossCopyFilters: FILTERS,
    });

    scheduleRefresh();
})(window);
