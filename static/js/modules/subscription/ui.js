        function buildSubscriptionRenderKey(state) {
            return JSON.stringify({
                running: !!state?.running,
                current_task: state?.current_task || '',
                queued: Array.isArray(state?.queued) ? state.queued : [],
                next_runs: state?.next_runs || {},
                tasks: Array.isArray(state?.tasks) ? state.tasks : []
            });
        }

        function mergeSubscriptionTaskUpdates(tasks = [], updates = []) {
            const sourceTasks = Array.isArray(tasks) ? tasks : [];
            const updateMap = new Map();
            (Array.isArray(updates) ? updates : []).forEach((item) => {
                const name = String(item?.name || item?.task_name || '').trim();
                if (!name) return;
                updateMap.set(name, item);
            });
            if (!updateMap.size) return sourceTasks;
            return sourceTasks.map((task) => {
                const name = String(task?.name || task?.task_name || '').trim();
                if (!name || !updateMap.has(name)) return task;
                const update = updateMap.get(name) || {};
                return {
                    ...task,
                    ...update,
                    name: task?.name || update.name || name,
                };
            });
        }

        const SUBSCRIPTION_LOG_RECENT_TASK_LIMIT = 1;
        const SUBSCRIPTION_LOG_PAGE_TASK_LIMIT = 1;
        const SUBSCRIPTION_DEFAULT_EXCLUDE_FILE_EXTENSIONS = ['zip', 'rar'];
        const SUBSCRIPTION_SCAN_RECOMMENDED_DEFAULTS = {
            '115': {
                candidate_scan_prefetch_limit: 3,
                candidate_scan_concurrency: 1,
                share_scan_concurrency: 1,
                share_scan_rate_limit_seconds: 1.0,
            },
            quark: {
                candidate_scan_prefetch_limit: 8,
                candidate_scan_concurrency: 2,
                share_scan_concurrency: 2,
                share_scan_rate_limit_seconds: 0.35,
            },
        };
        let subscriptionLogRows = [];
        let subscriptionLogOldestSeq = 0;
        let subscriptionLogNewestSeq = 0;
        let subscriptionLogHasMoreBefore = false;
        let subscriptionLogLoading = false;
        let subscriptionLogFollowTail = true;
        let subscriptionLogRefreshTimer = null;
        let subscriptionLogPendingLatestSeq = 0;
        let subscriptionLogHydrated = false;
        let subscriptionLogLastPullAt = 0;
        let subscriptionLogTaskTotal = 0;
        let subscriptionLogManualHistoryLoaded = false;

        function getSubscriptionStatusLabel(status) {
            const normalized = String(status || 'idle').trim().toLowerCase();
            const map = {
                idle: '待命',
                running: '运行中',
                waiting: '等待资源',
                completed: '已完成',
                failed: '失败',
                cancelled: '已中断'
            };
            return map[normalized] || (normalized || '待命');
        }

        function buildSubscriptionStatusBadge(status) {
            const normalized = String(status || 'idle').trim().toLowerCase();
            const map = {
                idle: 'bg-slate-700 text-slate-300',
                running: 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20',
                waiting: 'bg-amber-500/15 text-amber-300 border border-amber-500/20',
                completed: 'bg-sky-500/15 text-sky-300 border border-sky-500/20',
                failed: 'bg-red-500/10 text-red-300 border border-red-500/20',
                cancelled: 'bg-violet-500/15 text-violet-300 border border-violet-500/20'
            };
            const cls = map[normalized] || map.idle;
            return `<span class="text-[10px] px-3 py-1 rounded-full ${cls}">${escapeHtml(getSubscriptionStatusLabel(normalized))}</span>`;
        }

        function applySubscriptionState(data, { forceRender = false } = {}) {
            const subscriptionModule = tabRuntimeState.tabModuleCache.subscription;
            if (subscriptionModule?.applySubscriptionState) {
                subscriptionModule.applySubscriptionState(data, {
                    forceRender,
                    getSubscriptionState: () => subscriptionState,
                    setSubscriptionState: (nextValue) => {
                        subscriptionState = { ...nextValue };
                    },
                    getIntroExpanded: () => subscriptionTaskIntroExpanded,
                    setIntroExpanded: (nextValue) => {
                        subscriptionTaskIntroExpanded = { ...(nextValue || {}) };
                    },
                    pruneTaskIntroExpanded,
                    buildSubscriptionRenderKey,
                    getLastSubscriptionRenderKey: () => lastSubscriptionRenderKey,
                    setLastSubscriptionRenderKey: (nextValue) => {
                        lastSubscriptionRenderKey = String(nextValue || '');
                    },
                    renderSubscriptionTasks,
                    renderSubscriptionLogs,
                    applySubscriptionLogs,
                    applySubscriptionLogMeta,
                });
                return;
            }
            if (!data) return;
            const nextTasks = Array.isArray(data.tasks)
                ? data.tasks
                : mergeSubscriptionTaskUpdates(subscriptionState.tasks || [], data.task_updates || []);
            subscriptionState = {
                ...subscriptionState,
                ...data,
                tasks: nextTasks,
                logs: Array.isArray(data.logs) ? data.logs : [],
                queued: Array.isArray(data.queued) ? data.queued : (subscriptionState.queued || []),
                next_runs: data.next_runs || subscriptionState.next_runs || {},
                summary: data.summary || subscriptionState.summary || { step: '空闲', detail: '等待订阅任务' }
            };
            subscriptionTaskIntroExpanded = pruneTaskIntroExpanded(subscriptionTaskIntroExpanded, subscriptionState.tasks);

            const stepEl = document.getElementById('subscription-summary-step');
            const detailEl = document.getElementById('subscription-summary-detail');
            if (stepEl) stepEl.innerText = subscriptionState.summary?.step || '空闲';
            if (detailEl) detailEl.innerText = subscriptionState.summary?.detail || '等待订阅任务';

            const renderKey = buildSubscriptionRenderKey(subscriptionState);
            if (forceRender || renderKey !== lastSubscriptionRenderKey) {
                renderSubscriptionTasks();
                lastSubscriptionRenderKey = renderKey;
            }
            if (Array.isArray(data.logs)) applySubscriptionLogs(data.logs);
            applySubscriptionLogMeta(data.log_meta || { latest_seq: data.log_total || 0 });
        }

        function buildSubscriptionTaskIntro(task, {
            status = 'idle',
            queued = false,
            nextRun = '',
            isTv = false,
            episodeText = '',
            multiSeasonMode = false,
        } = {}) {
            const statusText = queued ? '已排队' : getSubscriptionStatusLabel(status);
            const enabledText = task?.enabled === false ? '已停用' : '已启用';
            const mediaText = isTv ? '电视剧' : '电影';
            const provider = normalizeSubscriptionProvider(task?.provider || '115', '115');
            const _pMeta = (window.providerMeta || []).find(m => m.name === provider);
            const providerText = _pMeta ? _pMeta.label : (provider === 'quark' ? '夸克' : '115');
            const titleText = String(task?.title || task?.name || '').trim() || '未命名影视';
            const savepath = String(task?.savepath || '').trim() || '--';
            const fixedShareLink = String(task?.share_link_url || '').trim();
            const fixedLinkChannelSearch = !!task?.fixed_link_channel_search;
            const shareSubdir = normalizeRelativePathInput(task?.share_subdir || '');
            const shareSubdirCid = normalizeShareCidInput(task?.share_subdir_cid || '');
            const excludeKeywords = parseSubscriptionExcludeKeywords(
                Array.isArray(task?.exclude_keywords)
                    ? task.exclude_keywords.join(',')
                    : (task?.exclude_keywords || task?.exclude_words || '')
            );
            const excludeFileExtensions = parseSubscriptionExcludeFileExtensions(
                Array.isArray(task?.exclude_file_extensions)
                    ? task.exclude_file_extensions.join(',')
                    : (task?.exclude_file_extensions || '')
            );
            const scheduleWeekdays = normalizeSubscriptionWeekdays(task?.schedule_weekdays || []);
            const scheduleStartTime = normalizeSubscriptionScheduleTime(task?.schedule_start_time || '00:00', '00:00');
            const scheduleEndTime = normalizeSubscriptionScheduleTime(task?.schedule_end_time || '23:59', '23:59');
            const scheduleIntervalMinutes = Math.max(
                1,
                Number(task?.schedule_interval_minutes || task?.cron_minutes || SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES)
                    || SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES
            );
            const weekdayText = formatSubscriptionWeekdayText(scheduleWeekdays);
            const isCrossDayWindow = scheduleStartTime > scheduleEndTime;
            const windowText = isCrossDayWindow
                ? `${scheduleStartTime} - 次日 ${scheduleEndTime}`
                : `${scheduleStartTime} - ${scheduleEndTime}`;
            let scheduleText = '';
            if (task?.enabled === false) {
                scheduleText = '自动查询已停用，仅支持手动运行';
            } else if (!scheduleWeekdays.length) {
                scheduleText = '未选择查询星期，仅支持手动运行';
            } else {
                scheduleText = `${weekdayText} ${windowText} 每 ${scheduleIntervalMinutes} 分钟查询一次，下次执行 ${String(nextRun || '计算中')}`;
            }
            const latestText = buildSubscriptionLatestMatchText(task);
            const modeText = isTv ? (multiSeasonMode ? '多季合一追更' : '单季追更') : '命中资源后即执行';
            const fixedShareText = fixedShareLink
                ? (fixedLinkChannelSearch ? '，固定分享链接兜底' : '，固定分享链接已填写（未启用兜底）')
                : '';
            const shareScopeText = shareSubdir
                ? `，分享子目录 ${shareSubdir}${shareSubdirCid ? `（CID ${shareSubdirCid}）` : ''}`
                : (shareSubdirCid ? `，分享子目录 CID ${shareSubdirCid}` : '');
            const providerRuleText = (!_pMeta?.supports_fixed_share_link) ? '，仅频道自动匹配（不使用固定分享链接）' : '';
            const excludeText = excludeKeywords.length ? `，排除 ${excludeKeywords.slice(0, 4).join('、')}` : '';
            const excludeFileText = excludeFileExtensions.length ? `，排除文件类型 ${excludeFileExtensions.slice(0, 5).join('/')}` : '';
            const minFileSizeMb = normalizeSubscriptionMinFileSizeMb(task?.min_file_size_mb ?? 0);
            const sizeFilterText = minFileSizeMb > 0 ? `，小于 ${formatSubscriptionMinFileSizeMb(minFileSizeMb)}MB 不导入` : '';
            const strictMatchText = task?.strict_title_match ? '，精准匹配：简介命中不算同剧证据' : '';
            return `状态：${statusText}（${enabledText}）。${providerText} · ${mediaText}《${titleText}》保存到 ${savepath}${fixedShareText}${shareScopeText}${providerRuleText}${excludeText}${excludeFileText}${sizeFilterText}${strictMatchText}，${modeText}，${episodeText}；${scheduleText}；${latestText}。`;
        }

        function buildSubscriptionTaskProgressBar({ progress = 0, detail = '' } = {}) {
            const progressValue = Math.max(0, Math.min(100, Number(progress || 0) || 0));
            const progressWidth = progressValue <= 0 ? 2 : progressValue;
            const detailText = String(detail || '').trim();
            const detailLine = detailText ? `<div class="mt-1 text-[11px] text-slate-300 break-all">${escapeHtml(detailText)}</div>` : '';
            return `
                <div class="mt-2 rounded-xl border border-sky-500/25 bg-sky-500/10 px-3 py-2">
                    <div class="flex items-center justify-between text-[11px] text-sky-200">
                        <span>运行进度</span>
                        <span class="font-bold">${progressValue}%</span>
                    </div>
                    <div class="mt-1.5 h-2 rounded-full bg-slate-800/80 overflow-hidden">
                        <div class="h-full rounded-full bg-gradient-to-r from-sky-400 to-emerald-400 transition-width prog-glow" style="width: ${progressWidth}%"></div>
                    </div>
                    ${detailLine}
                </div>
            `;
        }

        function toggleSubscriptionTaskIntro(taskName) {
            subscriptionTaskIntroExpanded = toggleTaskIntroExpanded(subscriptionTaskIntroExpanded, taskName);
            renderSubscriptionTasks();
        }

        function renderSubscriptionLogs() {
            const box = document.getElementById('subscription-log-box');
            if (!box) return;
            const logs = subscriptionState.logs || [];
            const logSignature = buildLogSignature(logs, (item) => `${item?.signature || ''}:${item?.level || 'info'}:${item?.text || ''}`);
            if (logSignature === lastSubscriptionLogSignature) return;
            box.innerHTML = logs.map(item => {
                const displayItem = {
                    ...item,
                    text: String(item?.text || item?.raw_text || item?.display_text || ''),
                };
                return `<div class="${getLogEntryClass(displayItem)}">${formatMonitorLogHtml(displayItem)}</div>`;
            }).join('');
            box.scrollTop = box.scrollHeight;
            lastSubscriptionLogSignature = logSignature;
        }

        function normalizeSubscriptionLogRow(item) {
            const row = item && typeof item === 'object' ? item : {};
            return {
                ...row,
                seq: Number(row.seq || 0),
                text: String(row.text || row.raw_text || row.display_text || ''),
                display_text: String(row.display_text || row.text || ''),
                raw_text: String(row.raw_text || ''),
                level: String(row.level || 'info'),
                signature: String(row.signature || '')
            };
        }

        function syncSubscriptionLogBounds() {
            subscriptionLogOldestSeq = subscriptionLogRows.length ? subscriptionLogRows[0].seq : 0;
            subscriptionLogNewestSeq = subscriptionLogRows.length ? subscriptionLogRows[subscriptionLogRows.length - 1].seq : 0;
        }

        function getSubscriptionLogBoundaryText(row) {
            return String(row?.raw_text || row?.display_text || row?.text || '').trim();
        }

        function isSubscriptionTaskLogStart(row) {
            return getSubscriptionLogBoundaryText(row).includes('订阅开始');
        }

        function isSubscriptionTaskLogEnd(row) {
            return getSubscriptionLogBoundaryText(row).includes('订阅结束');
        }

        function buildSubscriptionLogBlocks(rows) {
            const blocks = [];
            let activeTaskBlock = null;
            const appendEntryToBlock = (block, entry) => {
                block.entries.push(entry);
                if (!block.startSeq || entry.seq < block.startSeq) block.startSeq = entry.seq;
                if (!block.endSeq || entry.seq > block.endSeq) block.endSeq = entry.seq;
            };
            (Array.isArray(rows) ? rows : []).forEach((entry) => {
                if (!entry || entry.seq <= 0) return;
                if (isSubscriptionTaskLogStart(entry)) {
                    activeTaskBlock = { task: true, startSeq: 0, endSeq: 0, entries: [] };
                    blocks.push(activeTaskBlock);
                    appendEntryToBlock(activeTaskBlock, entry);
                    if (isSubscriptionTaskLogEnd(entry)) activeTaskBlock = null;
                    return;
                }
                if (activeTaskBlock) {
                    appendEntryToBlock(activeTaskBlock, entry);
                    if (isSubscriptionTaskLogEnd(entry)) activeTaskBlock = null;
                    return;
                }
                if (!blocks.length || blocks[blocks.length - 1].task) {
                    blocks.push({ task: false, startSeq: 0, endSeq: 0, entries: [] });
                }
                appendEntryToBlock(blocks[blocks.length - 1], entry);
            });
            return blocks.filter(block => Array.isArray(block.entries) && block.entries.length);
        }

        function flattenSubscriptionLogBlocks(blocks) {
            return (Array.isArray(blocks) ? blocks : [])
                .flatMap(block => Array.isArray(block?.entries) ? block.entries : []);
        }

        function countSubscriptionLogTaskBlocks(rows = subscriptionLogRows) {
            const blocks = buildSubscriptionLogBlocks(rows);
            return blocks.filter(block => !!block.task).length;
        }

        function tailSubscriptionLogBlocksByTaskCount(blocks, limit = SUBSCRIPTION_LOG_RECENT_TASK_LIMIT) {
            const list = Array.isArray(blocks) ? blocks : [];
            const normalizedLimit = Math.max(1, Number(limit || SUBSCRIPTION_LOG_RECENT_TASK_LIMIT) || SUBSCRIPTION_LOG_RECENT_TASK_LIMIT);
            if (!list.length) return [];
            const taskCount = list.filter(block => !!block.task).length;
            if (taskCount <= 0) return list.slice(-normalizedLimit);
            let remaining = normalizedLimit;
            let startIndex = 0;
            for (let index = list.length - 1; index >= 0; index -= 1) {
                if (list[index].task) remaining -= 1;
                if (remaining <= 0) {
                    startIndex = index;
                    break;
                }
            }
            return list.slice(startIndex);
        }

        function mergeSubscriptionLogRows(rows, { prepend = false } = {}) {
            const incoming = Array.isArray(rows) ? rows.map(normalizeSubscriptionLogRow).filter(item => item.seq > 0) : [];
            if (!incoming.length) return;
            const merged = new Map();
            const first = prepend ? incoming.concat(subscriptionLogRows) : subscriptionLogRows.concat(incoming);
            first.forEach(item => {
                if (item.seq > 0) merged.set(item.seq, item);
            });
            subscriptionLogRows = Array.from(merged.values()).sort((a, b) => a.seq - b.seq);
            syncSubscriptionLogBounds();
        }

        function applySubscriptionLogs(logs) {
            mergeSubscriptionLogRows(logs);
            trimSubscriptionLogWindow();
            subscriptionLogHydrated = true;
            renderSubscriptionLogRows();
        }

        function resetSubscriptionLogWindow() {
            if (subscriptionLogRefreshTimer) {
                window.clearTimeout(subscriptionLogRefreshTimer);
                subscriptionLogRefreshTimer = null;
            }
            subscriptionLogRows = [];
            subscriptionLogOldestSeq = 0;
            subscriptionLogNewestSeq = 0;
            subscriptionLogHasMoreBefore = false;
            subscriptionLogLoading = false;
            subscriptionLogFollowTail = true;
            subscriptionLogPendingLatestSeq = 0;
            subscriptionLogHydrated = false;
            subscriptionLogLastPullAt = 0;
            subscriptionLogTaskTotal = 0;
            subscriptionLogManualHistoryLoaded = false;
            lastSubscriptionLogSignature = '';
        }

        function trimSubscriptionLogWindow() {
            if (!subscriptionLogFollowTail) return;
            if (subscriptionLogManualHistoryLoaded) return;
            const previousOldestSeq = subscriptionLogRows.length ? subscriptionLogRows[0].seq : 0;
            const blocks = buildSubscriptionLogBlocks(subscriptionLogRows);
            const nextRows = flattenSubscriptionLogBlocks(
                tailSubscriptionLogBlocksByTaskCount(blocks, SUBSCRIPTION_LOG_RECENT_TASK_LIMIT)
            );
            if (nextRows.length === subscriptionLogRows.length) return;
            subscriptionLogRows = nextRows;
            syncSubscriptionLogBounds();
            if (previousOldestSeq > 0 && subscriptionLogOldestSeq > previousOldestSeq) {
                subscriptionLogHasMoreBefore = true;
            }
        }

        function updateSubscriptionLogLoadControl() {
            const loadMoreBtn = document.getElementById('subscription-log-load-more');
            if (!loadMoreBtn) return;
            const hasMore = !!subscriptionLogHasMoreBefore;
            loadMoreBtn.disabled = !hasMore || subscriptionLogLoading;
            loadMoreBtn.classList.toggle('btn-disabled', !hasMore && !subscriptionLogLoading);
            if (subscriptionLogLoading) {
                loadMoreBtn.innerText = '加载中...';
            } else if (hasMore) {
                loadMoreBtn.innerText = `加载更早 ${SUBSCRIPTION_LOG_PAGE_TASK_LIMIT} 条`;
            } else if (subscriptionLogRows.length) {
                loadMoreBtn.innerText = '已到最早日志';
            } else {
                loadMoreBtn.innerText = '暂无历史日志';
            }
        }

        function renderSubscriptionLogLoadSummary() {
            const summary = document.getElementById('subscription-log-load-summary');
            if (!summary) return;
            const loaded = countSubscriptionLogTaskBlocks();
            const total = Math.max(Number(subscriptionLogTaskTotal || 0) || 0, loaded);
            if (total > 0) {
                summary.innerText = `已加载 ${loaded} / ${total} 条`;
            } else {
                summary.innerText = '暂无任务日志';
            }
        }

        function renderSubscriptionLogRows({ keepScroll = false } = {}) {
            const box = document.getElementById('subscription-log-box');
            if (!box) return;
            const previousScrollHeight = box.scrollHeight;
            const previousScrollTop = box.scrollTop;
            const wasAtBottom = (previousScrollHeight - previousScrollTop - box.clientHeight) < 24;
            const logSignature = buildLogSignature(subscriptionLogRows, (item) => `${item?.seq || ''}:${item?.signature || ''}:${item?.level || 'info'}:${item?.text || ''}`);
            if (logSignature !== lastSubscriptionLogSignature) {
                box.innerHTML = subscriptionLogRows.map(item => {
                    const displayItem = {
                        ...item,
                        text: String(item?.text || item?.raw_text || item?.display_text || ''),
                    };
                    return `<div class="${getLogEntryClass(displayItem)}">${formatMonitorLogHtml(displayItem)}</div>`;
                }).join('');
                lastSubscriptionLogSignature = logSignature;
            }
            updateSubscriptionLogLoadControl();
            renderSubscriptionLogLoadSummary();
            if (keepScroll) {
                box.scrollTop = previousScrollTop + Math.max(0, box.scrollHeight - previousScrollHeight);
            } else if (subscriptionLogFollowTail && wasAtBottom) {
                box.scrollTop = box.scrollHeight;
            } else if (!subscriptionLogFollowTail) {
                box.scrollTop = previousScrollTop;
            }
        }

        async function fetchSubscriptionLogs({ after = 0, before = 0, limit = SUBSCRIPTION_LOG_PAGE_TASK_LIMIT, prepend = false } = {}) {
            if (subscriptionLogLoading) return;
            subscriptionLogLoading = true;
            updateSubscriptionLogLoadControl();
            try {
                const params = new URLSearchParams();
                if (after > 0) params.set('after', String(after));
                if (before > 0) params.set('before', String(before));
                params.set('limit', String(limit));
                const payload = await window.MediaHubApi.getJson(`/subscription/logs?${params.toString()}`);
                const rows = Array.isArray(payload.logs) ? payload.logs : [];
                if (prepend || before > 0) {
                    subscriptionLogManualHistoryLoaded = true;
                    subscriptionLogFollowTail = false;
                }
                mergeSubscriptionLogRows(rows, { prepend });
                subscriptionLogTaskTotal = Math.max(
                    Number(payload.task_block_total || 0) || 0,
                    countSubscriptionLogTaskBlocks(),
                );
                if (prepend || before > 0 || after <= 0) {
                    subscriptionLogHasMoreBefore = !!payload.has_more_before;
                } else {
                    subscriptionLogHasMoreBefore = subscriptionLogHasMoreBefore || !!payload.has_more_before;
                }
                subscriptionLogHydrated = true;
                if (!prepend) trimSubscriptionLogWindow();
                renderSubscriptionLogRows({ keepScroll: prepend });
            } catch (e) {
                updateSubscriptionLogLoadControl();
                renderSubscriptionLogLoadSummary();
            } finally {
                subscriptionLogLoading = false;
                updateSubscriptionLogLoadControl();
                renderSubscriptionLogLoadSummary();
            }
        }

        function scheduleSubscriptionLogRefresh(latestSeq = 0) {
            const normalizedLatestSeq = Number(latestSeq || 0);
            if (normalizedLatestSeq > subscriptionLogPendingLatestSeq) {
                subscriptionLogPendingLatestSeq = normalizedLatestSeq;
            }
            if (subscriptionLogRefreshTimer) return;
            subscriptionLogRefreshTimer = window.setTimeout(async () => {
                subscriptionLogRefreshTimer = null;
                if (subscriptionLogLoading) {
                    scheduleSubscriptionLogRefresh(subscriptionLogPendingLatestSeq);
                    return;
                }
                const now = Date.now();
                if (now - subscriptionLogLastPullAt < 600) {
                    scheduleSubscriptionLogRefresh(subscriptionLogPendingLatestSeq);
                    return;
                }
                subscriptionLogLastPullAt = now;
                if (!subscriptionLogHydrated) {
                    await fetchSubscriptionLogs({ limit: SUBSCRIPTION_LOG_RECENT_TASK_LIMIT });
                    return;
                }
                if (subscriptionLogPendingLatestSeq > subscriptionLogNewestSeq) {
                    await fetchSubscriptionLogs({ limit: SUBSCRIPTION_LOG_RECENT_TASK_LIMIT });
                    if (subscriptionLogPendingLatestSeq > subscriptionLogNewestSeq) {
                        scheduleSubscriptionLogRefresh(subscriptionLogPendingLatestSeq);
                    }
                }
            }, 500);
        }

        function applySubscriptionLogMeta(logMeta) {
            const meta = logMeta && typeof logMeta === 'object' ? logMeta : {};
            const latestSeq = Number(meta.latest_seq || meta.total || meta.latest?.seq || 0);
            if (latestSeq > 0 && subscriptionLogNewestSeq > latestSeq) {
                resetSubscriptionLogWindow();
            }
            subscriptionLogTaskTotal = Math.max(
                Number(meta.task_block_total || 0) || 0,
                countSubscriptionLogTaskBlocks(),
            );
            if (subscriptionLogHydrated && subscriptionLogTaskTotal > countSubscriptionLogTaskBlocks()) {
                subscriptionLogHasMoreBefore = true;
            }
            renderSubscriptionLogLoadSummary();
            updateSubscriptionLogLoadControl();
            subscriptionLogPendingLatestSeq = Math.max(subscriptionLogPendingLatestSeq, latestSeq);
            if (!subscriptionLogHydrated) {
                scheduleSubscriptionLogRefresh(latestSeq);
                return;
            }
            if (latestSeq > subscriptionLogNewestSeq) {
                scheduleSubscriptionLogRefresh(latestSeq);
            }
        }

        function handleSubscriptionLogScroll() {
            const box = document.getElementById('subscription-log-box');
            if (!box) return;
            const nearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 24;
            subscriptionLogFollowTail = nearBottom;
        }

        function loadEarlierSubscriptionLogs() {
            if (!subscriptionLogHasMoreBefore || subscriptionLogLoading) return;
            subscriptionLogManualHistoryLoaded = true;
            subscriptionLogFollowTail = false;
            void fetchSubscriptionLogs({ before: subscriptionLogOldestSeq, limit: SUBSCRIPTION_LOG_PAGE_TASK_LIMIT, prepend: true });
        }

        function normalizeSubscriptionMediaType(value) {
            const normalized = String(value || 'movie').trim().toLowerCase();
            return normalized === 'tv' ? 'tv' : 'movie';
        }

        function normalizeSubscriptionProvider(value, fallback = '115') {
            const normalized = String(value || '').trim().toLowerCase();
            const byName = (window.providerMeta || []).find(m => m.name === normalized);
            if (byName) return byName.name;
            const byLinkType = (window.providerMeta || []).find(m => m.link_type === normalized);
            if (byLinkType) return byLinkType.name;
            const fallbackNormalized = String(fallback || '115').trim().toLowerCase();
            const _fbP = (window.providerMeta || []).find(m => m.name === fallbackNormalized);
            return _fbP ? _fbP.name : '115';
        }

        function getSubscriptionProviderLabel(provider) {
            const _pMeta = (window.providerMeta || []).find(m => m.name === provider);
            return _pMeta ? _pMeta.label : (normalizeSubscriptionProvider(provider, '115') === 'quark' ? 'Quark' : '115');
        }

        function getSubscriptionProviderBadgeLabel(provider) {
            return getSubscriptionProviderLabel(provider);
        }

        function normalizeSubscriptionDate(value) {
            if (!value) return null;
            const date = value instanceof Date ? new Date(value.getTime()) : new Date(value);
            return Number.isNaN(date.getTime()) ? null : date;
        }

        function formatSubscriptionDateParts(date, includeYear = false) {
            const normalized = normalizeSubscriptionDate(date);
            if (!normalized) return '';
            const year = String(normalized.getFullYear()).padStart(4, '0');
            const month = String(normalized.getMonth() + 1).padStart(2, '0');
            const day = String(normalized.getDate()).padStart(2, '0');
            return includeYear ? `${year}-${month}-${day}` : `${month}-${day}`;
        }

        function getSubscriptionCalendarDayNumber(date) {
            const normalized = normalizeSubscriptionDate(date);
            if (!normalized) return NaN;
            return Date.UTC(normalized.getFullYear(), normalized.getMonth(), normalized.getDate()) / 86400000;
        }

        function formatSubscriptionLastHitAge(value, nowValue = new Date()) {
            const hitDate = normalizeSubscriptionDate(value);
            const nowDate = normalizeSubscriptionDate(nowValue) || new Date();
            if (!hitDate) return '';
            const dayDiff = getSubscriptionCalendarDayNumber(nowDate) - getSubscriptionCalendarDayNumber(hitDate);
            if (dayDiff === 0) return '今天';
            if (dayDiff === 1) return '昨天';
            if (dayDiff >= 2 && dayDiff < 30) return `${dayDiff}天前`;
            return formatSubscriptionDateParts(hitDate, hitDate.getFullYear() !== nowDate.getFullYear());
        }

        function formatSubscriptionLastHitDateTime(value) {
            const date = normalizeSubscriptionDate(value);
            if (!date) return '';
            const dateText = formatSubscriptionDateParts(date, true);
            const hours = String(date.getHours()).padStart(2, '0');
            const minutes = String(date.getMinutes()).padStart(2, '0');
            return `${dateText} ${hours}:${minutes}`;
        }

        function buildSubscriptionLastHitBadge(task) {
            const payload = task && typeof task === 'object' ? task : {};
            const matchedTitle = String(payload.matched_resource_title || '').trim();
            const timestamp = String(payload.last_success_at || '').trim();
            const dateText = formatSubscriptionLastHitDateTime(timestamp);
            const hasDate = !!dateText;
            const label = hasDate
                ? `最近命中 · ${formatSubscriptionLastHitAge(timestamp)}`
                : (matchedTitle ? '命中日期未知' : '尚未命中');
            const className = `subscription-last-hit-badge${hasDate ? '' : ' subscription-last-hit-badge-empty'}`;
            const title = hasDate ? `最近命中：${dateText}` : label;
            return `<span class="${className}" title="${escapeHtml(title)}">${escapeHtml(label)}</span>`;
        }

        function buildSubscriptionLatestMatchText(task) {
            const payload = task && typeof task === 'object' ? task : {};
            const matchedTitle = String(payload.matched_resource_title || '').trim();
            const dateText = formatSubscriptionLastHitDateTime(payload.last_success_at);
            if (matchedTitle && dateText) return `最近命中：${matchedTitle} · ${dateText}`;
            if (matchedTitle) return `最近命中：${matchedTitle}（日期未记录）`;
            if (dateText) return `最近命中时间：${dateText}`;
            return '最近尚未命中资源';
        }

        function getSubscriptionProviderBadgeMeta(provider) {
            const normalized = normalizeSubscriptionProvider(provider, '115');
            const providerMeta = (window.providerMeta || []).find(m => m.name === normalized) || {};
            const linkType = String(providerMeta.link_type || '').trim().toLowerCase();
            const tagMeta = window.ResourceLinkTags?.getTagMeta
                ? window.ResourceLinkTags.getTagMeta(linkType)
                : { tone: 'neutral' };
            const tone = String(tagMeta?.tone || 'neutral').trim() || 'neutral';
            return {
                label: getSubscriptionProviderBadgeLabel(normalized),
                className: `resource-link-tag resource-link-tag--${tone}`,
            };
        }

        function buildSubscriptionProviderBadge(provider) {
            const meta = getSubscriptionProviderBadgeMeta(provider);
            return `<span class="${meta.className}">${escapeHtml(meta.label)}</span>`;
        }

        function getCurrentSubscriptionProvider() {
            return normalizeSubscriptionProvider(document.getElementById('subscription_provider')?.value || '115', '115');
        }

        function populateSubscriptionProviderSelect() {
            const select = document.getElementById('subscription_provider');
            if (!select) return;
            const meta = window.providerMeta || [];
            const enabled = meta.filter(p => p.enabled && p.supports_subscription);
            select.innerHTML = enabled.map(p => '<option value="' + p.name + '">' + p.label + '</option>').join('');
            if (enabled.length && !enabled.some(p => p.name === select.value)) select.value = enabled[0].name;
        }

        function getSubscriptionScanRecommendedDefaults(provider = '115') {
            const normalizedProvider = normalizeSubscriptionProvider(provider, '115');
            return { ...(SUBSCRIPTION_SCAN_RECOMMENDED_DEFAULTS[normalizedProvider] || SUBSCRIPTION_SCAN_RECOMMENDED_DEFAULTS['115']) };
        }

        function normalizeSubscriptionScanInteger(value, fallback, minValue, maxValue) {
            const parsed = parseInt(String(value ?? '').trim(), 10);
            const normalized = Number.isFinite(parsed) ? parsed : fallback;
            return Math.max(minValue, Math.min(maxValue, normalized));
        }

        function normalizeSubscriptionScanFloat(value, fallback, minValue, maxValue) {
            const parsed = Number.parseFloat(String(value ?? '').trim());
            const normalized = Number.isFinite(parsed) ? parsed : fallback;
            return Math.round(Math.max(minValue, Math.min(maxValue, normalized)) * 100) / 100;
        }

        function normalizeSubscriptionScanSettings(value = {}, provider = '115') {
            const payload = value && typeof value === 'object' ? value : {};
            const defaults = getSubscriptionScanRecommendedDefaults(provider);
            return {
                candidate_scan_prefetch_limit: normalizeSubscriptionScanInteger(
                    payload.candidate_scan_prefetch_limit ?? payload.candidate_scan_prewarm_limit ?? payload.scan_prewarm_limit,
                    defaults.candidate_scan_prefetch_limit,
                    0,
                    80
                ),
                candidate_scan_concurrency: normalizeSubscriptionScanInteger(
                    payload.candidate_scan_concurrency ?? payload.candidate_prewarm_concurrency,
                    defaults.candidate_scan_concurrency,
                    1,
                    6
                ),
                share_scan_concurrency: normalizeSubscriptionScanInteger(
                    payload.share_scan_concurrency ?? payload.scan_concurrency,
                    defaults.share_scan_concurrency,
                    1,
                    6
                ),
                share_scan_rate_limit_seconds: normalizeSubscriptionScanFloat(
                    payload.share_scan_rate_limit_seconds ?? payload.scan_rate_limit_seconds,
                    defaults.share_scan_rate_limit_seconds,
                    0.05,
                    5
                ),
            };
        }

        function setSubscriptionScanSettingsToForm(settings = {}, provider = getCurrentSubscriptionProvider()) {
            const normalized = normalizeSubscriptionScanSettings(settings, provider);
            const prefetchEl = document.getElementById('subscription_candidate_scan_prefetch_limit');
            const candidateConcurrencyEl = document.getElementById('subscription_candidate_scan_concurrency');
            const shareConcurrencyEl = document.getElementById('subscription_share_scan_concurrency');
            const rateLimitEl = document.getElementById('subscription_share_scan_rate_limit_seconds');
            if (prefetchEl) prefetchEl.value = normalized.candidate_scan_prefetch_limit;
            if (candidateConcurrencyEl) candidateConcurrencyEl.value = normalized.candidate_scan_concurrency;
            if (shareConcurrencyEl) shareConcurrencyEl.value = normalized.share_scan_concurrency;
            if (rateLimitEl) rateLimitEl.value = normalized.share_scan_rate_limit_seconds;
            syncSubscriptionScanTuningHint(provider);
        }

        function readSubscriptionScanSettingsFromForm(provider = getCurrentSubscriptionProvider()) {
            return normalizeSubscriptionScanSettings({
                candidate_scan_prefetch_limit: document.getElementById('subscription_candidate_scan_prefetch_limit')?.value,
                candidate_scan_concurrency: document.getElementById('subscription_candidate_scan_concurrency')?.value,
                share_scan_concurrency: document.getElementById('subscription_share_scan_concurrency')?.value,
                share_scan_rate_limit_seconds: document.getElementById('subscription_share_scan_rate_limit_seconds')?.value,
            }, provider);
        }

        function syncSubscriptionScanTuningHint(provider = getCurrentSubscriptionProvider()) {
            const normalizedProvider = normalizeSubscriptionProvider(provider, '115');
            const defaults = getSubscriptionScanRecommendedDefaults(normalizedProvider);
            const hintEl = document.getElementById('subscription-scan-tuning-hint');
            if (!hintEl) return;
            const providerLabel = getSubscriptionProviderLabel(normalizedProvider);
            const reasonText = normalizedProvider === '115'
                ? '115 建议保守一点，避免连续读取 share/snap 时触发 405 或 IP 限制。'
                : 'Quark 可略高一些，但多设备或代理出口不稳定时也建议降低。';
            hintEl.textContent = `${providerLabel} 建议：候选上限 ${defaults.candidate_scan_prefetch_limit}，候选并发 ${defaults.candidate_scan_concurrency}，目录并发 ${defaults.share_scan_concurrency}，请求间隔 ${defaults.share_scan_rate_limit_seconds}s。${reasonText}`;
        }

        function fillSubscriptionScanTuningDefaults() {
            const provider = getCurrentSubscriptionProvider();
            setSubscriptionScanSettingsToForm(getSubscriptionScanRecommendedDefaults(provider), provider);
        }

        function normalizeSubscriptionQualityPriority(value) {
            const normalized = String(value || 'balanced').trim().toLowerCase();
            if (['balanced', 'ultra', 'fhd', 'hd', 'sd'].includes(normalized)) return normalized;
            return 'balanced';
        }

        function normalizeSubscriptionMinFileSizeMb(value) {
            const raw = String(value ?? '0').trim().toLowerCase().replace(/\s+/g, '');
            if (!raw) return 0;
            let normalized = raw;
            let multiplier = 1;
            if (normalized.endsWith('gb')) {
                multiplier = 1024;
                normalized = normalized.slice(0, -2);
            } else if (normalized.endsWith('g')) {
                multiplier = 1024;
                normalized = normalized.slice(0, -1);
            } else if (normalized.endsWith('mb')) {
                normalized = normalized.slice(0, -2);
            } else if (normalized.endsWith('m')) {
                normalized = normalized.slice(0, -1);
            } else if (normalized.endsWith('kb')) {
                multiplier = 1 / 1024;
                normalized = normalized.slice(0, -2);
            } else if (normalized.endsWith('k')) {
                multiplier = 1 / 1024;
                normalized = normalized.slice(0, -1);
            }
            const parsed = Number.parseFloat(normalized || '0') * multiplier;
            if (!Number.isFinite(parsed)) return 0;
            return Math.max(0, Math.round(parsed * 1000) / 1000);
        }

        function formatSubscriptionMinFileSizeMb(value) {
            const normalized = normalizeSubscriptionMinFileSizeMb(value);
            if (normalized <= 0) return '0';
            const text = String(normalized);
            return text.replace(/(\.\d*?[1-9])0+$/u, '$1').replace(/\.0+$/u, '');
        }

        function normalizeSubscriptionWeekdays(values) {
            let payload = values;
            if (typeof payload === 'string') {
                payload = payload.split(/[\s,，|/]+/).map((item) => item.trim()).filter(Boolean);
            }
            const source = Array.isArray(payload) ? payload : [];
            const seen = new Set();
            const normalized = [];
            source.forEach((item) => {
                const weekday = parseInt(item || '0', 10) || 0;
                if (weekday < 1 || weekday > 7 || seen.has(weekday)) return;
                seen.add(weekday);
                normalized.push(weekday);
            });
            normalized.sort((a, b) => a - b);
            return normalized;
        }

        function normalizeSubscriptionScheduleTime(value, fallback = '00:00') {
            const raw = String(value || '').trim() || String(fallback || '00:00').trim();
            const matched = raw.match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
            if (!matched) {
                const fallbackMatched = String(fallback || '00:00').trim().match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
                if (!fallbackMatched) return '00:00';
                return `${String(parseInt(fallbackMatched[1], 10)).padStart(2, '0')}:${String(parseInt(fallbackMatched[2], 10)).padStart(2, '0')}`;
            }
            return `${String(parseInt(matched[1], 10)).padStart(2, '0')}:${String(parseInt(matched[2], 10)).padStart(2, '0')}`;
        }

        function formatSubscriptionWeekdayText(values) {
            const weekdays = normalizeSubscriptionWeekdays(values);
            if (!weekdays.length) return '未选择更新日';
            return weekdays.map((weekday) => SUBSCRIPTION_WEEKDAY_LABELS[weekday] || `周${weekday}`).join('、');
        }

        function setSubscriptionWeekdaysToForm(values) {
            const weekdays = new Set(normalizeSubscriptionWeekdays(values));
            const checkboxList = document.querySelectorAll('[data-subscription-weekday]');
            checkboxList.forEach((checkbox) => {
                const weekday = parseInt(checkbox?.dataset?.subscriptionWeekday || '0', 10) || 0;
                checkbox.checked = weekdays.has(weekday);
            });
        }

        function getSubscriptionWeekdaysFromForm() {
            const selected = [];
            const checkboxList = document.querySelectorAll('[data-subscription-weekday]');
            checkboxList.forEach((checkbox) => {
                const weekday = parseInt(checkbox?.dataset?.subscriptionWeekday || '0', 10) || 0;
                if (weekday <= 0 || weekday > 7 || !checkbox.checked) return;
                selected.push(weekday);
            });
            return normalizeSubscriptionWeekdays(selected);
        }

        function getSubscriptionQualityPriorityLabel(value) {
            const normalized = normalizeSubscriptionQualityPriority(value);
            const map = {
                balanced: '均衡',
                ultra: '超清优先',
                fhd: '高清优先',
                hd: '流畅优先',
                sd: '小体积优先'
            };
            return map[normalized] || '均衡';
        }

        function normalizeTmdbMediaType(value, fallback = '') {
            const normalized = String(value || '').trim().toLowerCase();
            if (normalized === 'movie' || normalized === 'tv') return normalized;
            const fallbackNormalized = String(fallback || '').trim().toLowerCase();
            if (fallbackNormalized === 'movie' || fallbackNormalized === 'tv') return fallbackNormalized;
            return '';
        }

        function normalizeTmdbEpisodeMode(value) {
            const normalized = String(value || '').trim().toLowerCase();
            return normalized === 'absolute' ? 'absolute' : 'seasonal';
        }

        function normalizeTmdbSeasonEpisodeMap(value) {
            const result = {};
            const assign = (seasonValue, episodeValue) => {
                const seasonNo = parseInt(seasonValue || '0', 10) || 0;
                const episodeCount = parseInt(episodeValue || '0', 10) || 0;
                if (seasonNo <= 0 || episodeCount <= 0) return;
                result[String(seasonNo)] = episodeCount;
            };
            let payload = value;
            if (typeof payload === 'string') {
                const text = payload.trim();
                if (!text) payload = {};
                else {
                    try {
                        payload = JSON.parse(text);
                    } catch (_) {
                        payload = {};
                    }
                }
            }
            if (Array.isArray(payload)) {
                payload.forEach((item) => {
                    if (!item || typeof item !== 'object') return;
                    assign(item.season_number ?? item.season ?? item.number, item.episode_count ?? item.episodes ?? item.total_episodes);
                });
                return result;
            }
            if (!payload || typeof payload !== 'object') return result;
            Object.entries(payload).forEach(([seasonKey, episodeValue]) => {
                assign(seasonKey, episodeValue);
            });
            return result;
        }

        function getTmdbSeasonEpisodeTotal(seasonMap, season) {
            const normalizedMap = normalizeTmdbSeasonEpisodeMap(seasonMap);
            const targetSeason = Math.max(1, parseInt(season || '1', 10) || 1);
            return Math.max(0, parseInt(normalizedMap[String(targetSeason)] || '0', 10) || 0);
        }

        function resolveTaskMultiSeasonMode(task) {
            return !!(task?.multi_season_mode ?? task?.anime_mode);
        }

        function normalizeTmdbYear(value) {
            const normalized = String(value || '').trim();
            return /^(19|20)\d{2}$/.test(normalized) ? normalized : '';
        }

        function parseSmallCjkNumber(value, fallback = 0) {
            const raw = String(value || '').trim();
            if (!raw) return fallback;
            if (/^\d{1,4}$/.test(raw)) {
                const parsed = parseInt(raw, 10);
                return Number.isFinite(parsed) ? parsed : fallback;
            }
            if (!/^[零〇一二三四五六七八九十两兩]+$/.test(raw)) return fallback;
            const digits = {
                '零': 0,
                '〇': 0,
                '一': 1,
                '二': 2,
                '三': 3,
                '四': 4,
                '五': 5,
                '六': 6,
                '七': 7,
                '八': 8,
                '九': 9,
                '两': 2,
                '兩': 2,
            };
            if (raw === '十') return 10;
            if (raw.includes('十')) {
                const [head, tail] = raw.split('十');
                const tens = head ? (digits[head] ?? -1) : 1;
                const ones = tail ? (digits[tail] ?? -1) : 0;
                if (tens < 0 || ones < 0) return fallback;
                return tens * 10 + ones;
            }
            const single = digits[raw];
            return Number.isFinite(single) ? single : fallback;
        }

        function extractYearFromResourceText(item) {
            const knownYear = normalizeTmdbYear(item?.year || '');
            if (knownYear) return knownYear;
            const text = `${String(item?.title || '')} ${String(item?.raw_text || '')}`;
            const matched = text.match(/\b(19|20)\d{2}\b/);
            return normalizeTmdbYear(matched?.[0] || '');
        }

        function buildSubscriptionTitleFromResource(item) {
            const fallback = String(item?.title || item?.normalized_title || '未命名资源').trim() || '未命名资源';
            let title = String(item?.title || '').trim() || fallback;

            title = title.split(/\s*[|｜丨]+\s*/)[0].trim() || title;
            title = title
                .replace(/[._]+/g, ' ')
                .replace(/[\[\【(（][^\]\】)）]{0,90}(?:2160p|1080p|720p|4k|uhd|hdr|web(?:-|\s)?dl|bluray|x26[45]|h\.?26[45]|aac|ddp|atmos|中字|双语|國語|国语|粤语|简繁|完结|全集|更新|s\d{1,2}\s*e?\d{0,4}|第\s*[零〇一二三四五六七八九十两兩0-9]+\s*(?:季|集|话|話))[^\]\】)）]*[\]\】)）]/gi, ' ')
                .replace(/\b(19|20)\d{2}\b/g, ' ')
                .replace(/\b(?:S\d{1,2}\s*E?\d{0,4}|E\d{1,4}|EP?\s*\d{1,4})\b/gi, ' ')
                .replace(/第\s*[零〇一二三四五六七八九十两兩0-9]{1,4}\s*(?:季|集|话|話)/g, ' ')
                .replace(/(?:全|共)\s*\d{1,4}\s*(?:集|话|話)/g, ' ')
                .replace(/\d{1,4}\s*(?:集|话|話)\s*(?:全|完|完结|完結)?/g, ' ')
                .replace(/\s{2,}/g, ' ')
                .trim();
            return title || fallback;
        }

        function inferSubscriptionDraftFromResource(item) {
            const payload = item && typeof item === 'object' ? item : {};
            const text = `${String(payload?.title || '')} ${String(payload?.raw_text || '')}`;
            const seasonMatch = text.match(/\bS(?:eason)?\s*0?(\d{1,2})\b/i);
            const seasonCnMatch = text.match(/第\s*([零〇一二三四五六七八九十两兩0-9]{1,3})\s*季/i);
            const rangeMatch = text.match(/(?:EP?|E)?\s*(\d{1,4})\s*[-~～—–至到]+\s*(?:EP?|E)?\s*(\d{1,4})/i)
                || text.match(/第?\s*(\d{1,4})\s*[-~～—–至到]+\s*(\d{1,4})\s*(?:集|话|話)/i);
            const totalMatch = text.match(/(?:全|共)\s*(\d{1,4})\s*(?:集|话|話)/i)
                || text.match(/(\d{1,4})\s*(?:集|话|話)\s*(?:全|完|完结|完結)/i);
            const episodeMatch = text.match(/\bS\d{1,2}\s*E(?:P)?\s*0?(\d{1,4})\b/i)
                || text.match(/\bEP?\s*0?(\d{1,4})\b/i)
                || text.match(/第\s*(\d{1,4})\s*(?:集|话|話)/i);

            let season = Math.max(0, parseInt(seasonMatch?.[1] || '0', 10) || 0);
            if (season <= 0 && seasonCnMatch) season = Math.max(0, parseSmallCjkNumber(seasonCnMatch[1], 0));
            let episode = Math.max(0, parseInt(episodeMatch?.[1] || '0', 10) || 0);
            let totalEpisodes = Math.max(0, parseInt(totalMatch?.[1] || '0', 10) || 0);
            let rangeStart = Math.max(0, parseInt(rangeMatch?.[1] || '0', 10) || 0);
            let rangeEnd = Math.max(0, parseInt(rangeMatch?.[2] || '0', 10) || 0);
            if (rangeEnd > 0 && rangeStart > rangeEnd) [rangeStart, rangeEnd] = [rangeEnd, rangeStart];
            if (rangeEnd > 0) {
                episode = Math.max(episode, rangeEnd);
                if (totalEpisodes <= 0 && rangeStart <= 1) totalEpisodes = rangeEnd;
            }
            if (totalEpisodes <= 0 && episode > 0 && /(?:完结|完結|全集|全\d{1,4}集)/i.test(text)) {
                totalEpisodes = episode;
            }

            const hasEpisodeMeta = season > 0 || episode > 0 || totalEpisodes > 0 || rangeEnd > 0;
            const tvHint = /(电视剧|剧集|番剧|动漫|第\s*[零〇一二三四五六七八九十两兩0-9]+\s*(?:季|集|话|話)|season\s*\d+|s\d{1,2}\s*e?\d{0,4}|ep\s*\d{1,4}|更新至\s*\d+\s*(?:集|话|話)|全\s*\d+\s*(?:集|话|話)|完结|完結)/i.test(text);
            const movieHint = /(电影|movie|film|剧场版|電影)/i.test(text);
            const animeMode = /(番剧|动漫|新番|动画|動畫|anime)/i.test(text);
            const mediaType = (hasEpisodeMeta || tvHint) && !movieHint ? 'tv' : 'movie';
            const linkType = getEffectiveResourceLinkType(payload);
            const _lp = (window.providerMeta || []).find(m => m.link_type === linkType);
            const provider = normalizeSubscriptionProvider(
                _lp ? _lp.name : (linkType === 'quark' ? 'quark' : '115'),
                '115'
            );

            return {
                provider,
                media_type: mediaType,
                title: buildSubscriptionTitleFromResource(payload),
                year: extractYearFromResourceText(payload),
                season: mediaType === 'tv' ? Math.max(1, season || 1) : 1,
                total_episodes: mediaType === 'tv' ? Math.max(0, totalEpisodes || 0) : 0,
                anime_mode: mediaType === 'tv' ? animeMode : false,
                multi_season_mode: mediaType === 'tv' ? animeMode : false,
            };
        }

        function applySubscriptionPrefill(prefill = {}) {
            const payload = prefill && typeof prefill === 'object' ? prefill : {};
            const mediaType = normalizeSubscriptionMediaType(payload.media_type || 'movie');
            const provider = normalizeSubscriptionProvider(payload.provider || '115', '115');
            const providerInput = document.getElementById('subscription_provider');
            if (providerInput) providerInput.value = provider;
            document.getElementById('subscription_media_type').value = mediaType;
            document.getElementById('subscription_title').value = String(payload.title || '').trim();
            document.getElementById('subscription_year').value = normalizeTmdbYear(payload.year || '');
            document.getElementById('subscription_season').value = Math.max(1, parseInt(payload.season || '1', 10) || 1);
            document.getElementById('subscription_total_episodes').value = Math.max(0, parseInt(payload.total_episodes || '0', 10) || 0);
            document.getElementById('subscription_anime_mode').checked = mediaType === 'tv'
                ? !!(payload.multi_season_mode ?? payload.anime_mode)
                : false;
            const tmdbKeywordInput = document.getElementById('subscription_tmdb_search_keyword');
            if (tmdbKeywordInput) tmdbKeywordInput.value = String(payload.title || '').trim();
            syncSubscriptionProviderUI();
            syncSubscriptionTypeUI();
            setSubscriptionScanSettingsToForm(getSubscriptionScanRecommendedDefaults(provider), provider);
        }

        function parseSubscriptionAliases(value) {
            return uniquePreserveOrder(String(value || '')
                .split(/[,\n，|/]+/)
                .map(item => item.trim())
                .filter(Boolean));
        }

        function parseSubscriptionExcludeKeywords(value) {
            return uniquePreserveOrder(String(value || '')
                .split(/[,\n，]+/)
                .map(item => item.trim())
                .filter(Boolean));
        }

        function formatSubscriptionExcludeKeywords(value) {
            const values = Array.isArray(value)
                ? value
                : parseSubscriptionExcludeKeywords(value);
            return parseSubscriptionExcludeKeywords(values.join(',')).join(', ');
        }

        function parseSubscriptionExcludeFileExtensions(value) {
            return uniquePreserveOrder(String(value || '')
                .split(/[,\n，]+/)
                .map(item => item.trim().toLowerCase().replace(/^\.+/, '').replace(/\s+/g, ''))
                .filter(item => /^[a-z0-9][a-z0-9_+-]{0,29}$/.test(item)))
                .slice(0, 50);
        }

        function formatSubscriptionExcludeFileExtensions(value) {
            const values = Array.isArray(value)
                ? value
                : parseSubscriptionExcludeFileExtensions(value);
            return parseSubscriptionExcludeFileExtensions(values.join(',')).join(', ');
        }

        function getSubscriptionTmdbBindingFromForm() {
            const tmdbId = parseInt(document.getElementById('subscription_tmdb_id')?.value || '0', 10) || 0;
            const tmdbMediaType = normalizeTmdbMediaType(document.getElementById('subscription_tmdb_media_type')?.value || '');
            const tmdbAliases = parseSubscriptionAliases(document.getElementById('subscription_tmdb_aliases')?.value || '');
            return {
                tmdb_id: Math.max(0, tmdbId),
                tmdb_media_type: tmdbMediaType,
                tmdb_title: String(document.getElementById('subscription_tmdb_title')?.value || '').trim(),
                tmdb_original_title: String(document.getElementById('subscription_tmdb_original_title')?.value || '').trim(),
                tmdb_year: normalizeTmdbYear(document.getElementById('subscription_tmdb_year')?.value || ''),
                tmdb_aliases: tmdbAliases,
                tmdb_total_episodes: Math.max(0, parseInt(document.getElementById('subscription_tmdb_total_episodes')?.value || '0', 10) || 0),
                tmdb_total_seasons: Math.max(0, parseInt(document.getElementById('subscription_tmdb_total_seasons')?.value || '0', 10) || 0),
                tmdb_season_episode_map: normalizeTmdbSeasonEpisodeMap(document.getElementById('subscription_tmdb_season_episode_map')?.value || ''),
                tmdb_episode_mode: normalizeTmdbEpisodeMode(document.getElementById('subscription_tmdb_episode_mode')?.value || 'seasonal'),
            };
        }

        function setSubscriptionTmdbBinding(binding = {}) {
            const normalized = {
                tmdb_id: Math.max(0, parseInt(binding.tmdb_id || binding.id || '0', 10) || 0),
                tmdb_media_type: normalizeTmdbMediaType(
                    binding.tmdb_media_type || binding.media_type || '',
                    normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie')
                ),
                tmdb_title: String(binding.tmdb_title || binding.title || '').trim(),
                tmdb_original_title: String(binding.tmdb_original_title || binding.original_title || '').trim(),
                tmdb_year: normalizeTmdbYear(binding.tmdb_year || binding.year || ''),
                tmdb_aliases: parseSubscriptionAliases(Array.isArray(binding.tmdb_aliases) ? binding.tmdb_aliases.join(',') : (binding.tmdb_aliases || binding.aliases || '')),
                tmdb_total_episodes: Math.max(0, parseInt(binding.tmdb_total_episodes || binding.total_episodes || '0', 10) || 0),
                tmdb_total_seasons: Math.max(0, parseInt(binding.tmdb_total_seasons || binding.total_seasons || '0', 10) || 0),
                tmdb_season_episode_map: normalizeTmdbSeasonEpisodeMap(binding.tmdb_season_episode_map || binding.season_episode_map || {}),
                tmdb_episode_mode: normalizeTmdbEpisodeMode(binding.tmdb_episode_mode || binding.episode_mode || 'seasonal'),
            };
            const useBinding = normalized.tmdb_id > 0;
            document.getElementById('subscription_tmdb_id').value = useBinding ? String(normalized.tmdb_id) : '0';
            document.getElementById('subscription_tmdb_media_type').value = useBinding ? normalized.tmdb_media_type : '';
            document.getElementById('subscription_tmdb_title').value = useBinding ? normalized.tmdb_title : '';
            document.getElementById('subscription_tmdb_original_title').value = useBinding ? normalized.tmdb_original_title : '';
            document.getElementById('subscription_tmdb_year').value = useBinding ? normalized.tmdb_year : '';
            document.getElementById('subscription_tmdb_aliases').value = useBinding ? normalized.tmdb_aliases.join(', ') : '';
            document.getElementById('subscription_tmdb_total_episodes').value = useBinding ? String(normalized.tmdb_total_episodes) : '0';
            document.getElementById('subscription_tmdb_total_seasons').value = useBinding ? String(normalized.tmdb_total_seasons) : '0';
            document.getElementById('subscription_tmdb_season_episode_map').value = useBinding ? JSON.stringify(normalized.tmdb_season_episode_map) : '';
            document.getElementById('subscription_tmdb_episode_mode').value = useBinding ? normalized.tmdb_episode_mode : 'seasonal';
            renderSubscriptionTmdbBinding();
        }

        function clearSubscriptionTmdbBinding({ silent = false } = {}) {
            setSubscriptionTmdbBinding({});
            if (!silent) showToast('已清除 TMDB 绑定', { tone: 'info', duration: 2200, placement: 'top-center' });
        }

        function renderSubscriptionTmdbBinding() {
            const summaryEl = document.getElementById('subscription_tmdb_summary');
            if (!summaryEl) return;
            const binding = getSubscriptionTmdbBindingFromForm();
            if (binding.tmdb_id <= 0) {
                summaryEl.innerHTML = '未绑定 TMDB。绑定后会自动补充别名/年份/总集数并增强匹配稳定性。';
                return;
            }
            const mediaLabel = binding.tmdb_media_type === 'tv' ? '电视剧' : '电影';
            const yearSuffix = binding.tmdb_year ? ` (${escapeHtml(binding.tmdb_year)})` : '';
            const aliasText = binding.tmdb_aliases.length > 0 ? `别名 ${escapeHtml(String(binding.tmdb_aliases.length))} 个` : '无别名';
            const episodeModeText = binding.tmdb_episode_mode === 'absolute' ? '绝对集序' : '按季集序';
            const selectedSeason = Math.max(1, parseInt(document.getElementById('subscription_season')?.value || '1', 10) || 1);
            const seasonEpisodeTotal = getTmdbSeasonEpisodeTotal(binding.tmdb_season_episode_map, selectedSeason);
            const multiSeasonMode = !!document.getElementById('subscription_anime_mode')?.checked;
            const totalText = binding.tmdb_media_type === 'tv'
                ? `总集数 ${escapeHtml(String(binding.tmdb_total_episodes || 0))} / 季数 ${escapeHtml(String(binding.tmdb_total_seasons || 0))} / S${escapeHtml(String(selectedSeason))}集数 ${escapeHtml(String(seasonEpisodeTotal || 0))} / ${episodeModeText}`
                : '电影元数据';
            const totalHint = binding.tmdb_media_type === 'tv'
                ? (multiSeasonMode ? '当前模式：多季合一（默认采用 TMDB 总集数）' : '当前模式：单季订阅（优先采用所选季集数）')
                : '';
            const subscriptionMediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            const mismatch = binding.tmdb_media_type && binding.tmdb_media_type !== subscriptionMediaType;
            summaryEl.innerHTML = `
                <div>已绑定 <span class="text-sky-300">${mediaLabel} #${escapeHtml(String(binding.tmdb_id))}</span>：${escapeHtml(binding.tmdb_title || '--')}${yearSuffix}</div>
                <div class="text-[11px] mt-1">${escapeHtml(aliasText)} / ${escapeHtml(totalText)}</div>
                ${totalHint ? `<div class="text-[11px] mt-1">${escapeHtml(totalHint)}</div>` : ''}
                ${mismatch ? '<div class="text-[11px] mt-1 text-red-300">当前绑定类型与订阅类型不一致，保存前请重新绑定。</div>' : ''}
            `;
        }

        function setSubscriptionTmdbSearchBusy(loading) {
            subscriptionTmdbSearchBusy = !!loading;
            const btn = document.getElementById('subscription_tmdb_search_btn');
            if (!btn) return;
            btn.disabled = subscriptionTmdbSearchBusy;
            btn.classList.toggle('btn-disabled', subscriptionTmdbSearchBusy);
            btn.innerText = subscriptionTmdbSearchBusy ? '搜索中...' : '搜索';
        }

        function renderSubscriptionTmdbResults() {
            const listEl = document.getElementById('subscription_tmdb_result_list');
            if (!listEl) return;
            if (subscriptionTmdbSearchBusy) {
                listEl.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在搜索 TMDB，请稍候...</div>';
                return;
            }
            if (!subscriptionTmdbResults.length) {
                listEl.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">暂无结果，请尝试更换关键词或年份。</div>';
                return;
            }
            listEl.innerHTML = subscriptionTmdbResults.map((item, index) => {
                const mediaLabel = normalizeTmdbMediaType(item.media_type, 'movie') === 'tv' ? '电视剧' : '电影';
                const poster = item.poster_url
                    ? `<img src="${escapeHtml(item.poster_url)}" alt="${escapeHtml(item.title || '--')}" class="w-14 h-20 rounded-lg object-cover border border-slate-700 bg-slate-900">`
                    : '<div class="w-14 h-20 rounded-lg border border-dashed border-slate-700 text-[10px] text-slate-500 flex items-center justify-center bg-slate-900">无封面</div>';
                const yearText = item.year ? ` / ${escapeHtml(item.year)}` : '';
                const voteText = Number(item.vote_average || 0) > 0 ? ` / 评分 ${escapeHtml(String(item.vote_average))}` : '';
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-3">
                        <div class="flex items-start gap-3">
                            ${poster}
                            <div class="min-w-0 flex-1 text-xs text-slate-400 leading-6">
                                <div class="text-sm font-bold text-white break-words">${escapeHtml(item.title || '--')}</div>
                                <div>${escapeHtml(mediaLabel)}${yearText}${voteText}</div>
                                <div>原名：${escapeHtml(item.original_title || '--')}</div>
                                <div class="line-clamp-2">${escapeHtml(item.overview || '暂无简介')}</div>
                            </div>
                            <button
                                type="button"
                                data-subscription-tmdb-action="select"
                                data-subscription-tmdb-index="${index}"
                                class="px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shrink-0"
                            >绑定</button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function searchSubscriptionTmdbBinding() {
            const searchInput = document.getElementById('subscription_tmdb_search_keyword');
            const hintEl = document.getElementById('subscription_tmdb_search_hint');
            const fallbackQuery = document.getElementById('subscription_title')?.value || '';
            const query = String(searchInput?.value || fallbackQuery || '').trim();
            if (!query) {
                showToast('请先输入影视名称，再搜索 TMDB', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const mediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            const year = normalizeTmdbYear(document.getElementById('subscription_year')?.value || '');
            const requestToken = ++subscriptionTmdbSearchToken;
            setSubscriptionTmdbSearchBusy(true);
            subscriptionTmdbResults = [];
            renderSubscriptionTmdbResults();
            if (hintEl) hintEl.innerText = `正在按 ${mediaType === 'tv' ? '电视剧' : '电影'} 搜索：${query}`;
            try {
                const qs = new URLSearchParams({ q: query, media_type: mediaType });
                if (year) qs.set('year', year);
                const data = await window.MediaHubApi.getJson(`/tmdb/search?${qs.toString()}`);
                if (requestToken !== subscriptionTmdbSearchToken) return;
                subscriptionTmdbResults = Array.isArray(data.items) ? data.items : [];
                renderSubscriptionTmdbResults();
                if (hintEl) {
                    hintEl.innerText = subscriptionTmdbResults.length
                        ? `已找到 ${subscriptionTmdbResults.length} 条结果，请选择要绑定的条目。`
                        : '未找到可绑定条目，请调整关键词后重试。';
                }
            } catch (e) {
                subscriptionTmdbResults = [];
                renderSubscriptionTmdbResults();
                if (hintEl) hintEl.innerText = `TMDB 搜索失败：${e.message || '未知错误'}`;
            } finally {
                if (requestToken === subscriptionTmdbSearchToken) {
                    setSubscriptionTmdbSearchBusy(false);
                    renderSubscriptionTmdbResults();
                }
            }
        }

        async function selectSubscriptionTmdbResult(index) {
            const target = subscriptionTmdbResults[Number(index)];
            if (!target) return;
            const hintEl = document.getElementById('subscription_tmdb_search_hint');
            const mediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            if (hintEl) hintEl.innerText = `正在读取 TMDB 详情：${target.title || '--'}`;
            try {
                const qs = new URLSearchParams({
                    tmdb_id: String(target.id || 0),
                    media_type: normalizeTmdbMediaType(target.media_type, mediaType) || mediaType
                });
                const data = await window.MediaHubApi.getJson(`/tmdb/detail?${qs.toString()}`);
                const binding = data.task_binding || {};
                const bindingMediaType = normalizeTmdbMediaType(binding.tmdb_media_type, mediaType);
                if (bindingMediaType && bindingMediaType !== mediaType) {
                    throw new Error('TMDB 类型与当前订阅类型不一致，请切换类型后再绑定');
                }
                setSubscriptionTmdbBinding(binding);
                const titleInput = document.getElementById('subscription_title');
                if (titleInput && !String(titleInput.value || '').trim()) {
                    titleInput.value = String(binding.tmdb_title || target.title || '').trim();
                }
                const yearInput = document.getElementById('subscription_year');
                if (yearInput && !normalizeTmdbYear(yearInput.value || '') && normalizeTmdbYear(binding.tmdb_year || '')) {
                    yearInput.value = normalizeTmdbYear(binding.tmdb_year || '');
                }
                const aliasesInput = document.getElementById('subscription_aliases');
                if (aliasesInput && !String(aliasesInput.value || '').trim()) {
                    const defaultAliases = Array.isArray(binding.tmdb_aliases) ? binding.tmdb_aliases.slice(0, 4) : [];
                    aliasesInput.value = defaultAliases.join(', ');
                }
                if (mediaType === 'tv') {
                    // 绑定 TMDB 后应以 TMDB 详情刷新总集数，避免旧值残留。
                    suggestSubscriptionTotalEpisodesFromTmdb({ force: true });
                }
                closeSubscriptionTmdbSearchModal();
                showToast(`已绑定 TMDB：${binding.tmdb_title || target.title || '--'}`, { tone: 'success', duration: 2600, placement: 'top-center' });
            } catch (e) {
                if (hintEl) hintEl.innerText = `读取详情失败：${e.message || '未知错误'}`;
            }
        }

        function openSubscriptionTmdbSearchModal() {
            const keywordInput = document.getElementById('subscription_tmdb_search_keyword');
            const title = String(document.getElementById('subscription_title')?.value || '').trim();
            if (keywordInput) keywordInput.value = title || keywordInput.value || '';
            subscriptionTmdbResults = [];
            renderSubscriptionTmdbResults();
            showLockedModal('subscription-tmdb-modal');
            if (keywordInput && String(keywordInput.value || '').trim()) {
                searchSubscriptionTmdbBinding();
            }
        }

        function closeSubscriptionTmdbSearchModal() {
            hideLockedModal('subscription-tmdb-modal');
        }

        function suggestSubscriptionTotalEpisodesFromTmdb({ force = false } = {}) {
            const mediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            if (mediaType !== 'tv') return;
            const totalInput = document.getElementById('subscription_total_episodes');
            if (!totalInput) return;
            const currentTotal = parseInt(totalInput.value || '0', 10) || 0;
            if (!force && currentTotal > 0) return;
            const binding = getSubscriptionTmdbBindingFromForm();
            if ((parseInt(binding.tmdb_id || '0', 10) || 0) <= 0) return;
            const selectedSeason = Math.max(1, parseInt(document.getElementById('subscription_season')?.value || '1', 10) || 1);
            const seasonTotal = getTmdbSeasonEpisodeTotal(binding.tmdb_season_episode_map, selectedSeason);
            const multiSeasonMode = !!document.getElementById('subscription_anime_mode')?.checked;
            const tmdbTotal = Math.max(0, parseInt(binding.tmdb_total_episodes || '0', 10) || 0);
            const suggestedTotal = multiSeasonMode
                ? (tmdbTotal > 0 ? tmdbTotal : seasonTotal)
                : (seasonTotal > 0 ? seasonTotal : 0);
            if (suggestedTotal > 0 && (force || currentTotal <= 0)) totalInput.value = String(suggestedTotal);
        }

        function syncSubscriptionProviderUI() {
            const provider = getCurrentSubscriptionProvider();
            const meta = window.providerMeta || [];
            const p = meta.find(m => m.name === provider);
            const hasFixedShare = p && p.supports_fixed_share_link;
            const hasMinScore = p && p.supports_subscription;
            const providerLabel = getSubscriptionProviderLabel(provider);
            const savepathProviderLabelEl = document.getElementById('subscription-savepath-provider-label');
            const fixedLinkBlockEl = document.getElementById('subscription-115-fixed-link-block');
            const quarkHintEl = document.getElementById('subscription-quark-provider-hint');
            const minScoreWrapEl = document.getElementById('subscription-min-score-wrap');
            const minScoreInputEl = document.getElementById('subscription_min_score');
            const strategyHintEl = document.getElementById('subscription-provider-strategy-hint');
            const shareLinkInputEl = document.getElementById('subscription_share_link_url');
            const fixedLinkTitleEl = document.getElementById('subscription-fixed-link-title');
            const fixedLinkHintEl = document.getElementById('subscription-fixed-link-hint');
            const shareSubdirLabelEl = document.getElementById('subscription-share-subdir-label');

            if (savepathProviderLabelEl) savepathProviderLabelEl.textContent = `${providerLabel} 保存目录`;
            if (fixedLinkBlockEl) fixedLinkBlockEl.classList.toggle('hidden', !hasFixedShare);
            if (quarkHintEl) quarkHintEl.classList.toggle('hidden', hasFixedShare);
            if (minScoreWrapEl) minScoreWrapEl.classList.toggle('hidden', !hasMinScore);
            if (minScoreInputEl) minScoreInputEl.disabled = !hasMinScore;
            if (strategyHintEl) {
                const baseHint = '匹配策略：默认先执行资源搜索（TG 频道搜索，及启用时的 PanSou 搜索）';
                if (hasFixedShare) {
                    strategyHintEl.textContent = baseHint + '；可开启固定分享链接兜底，把固定链接候选排在资源搜索候选之后。';
                } else {
                    strategyHintEl.textContent = baseHint + '，也可手动扫描单个分享链接。';
                }
            }
            if (fixedLinkTitleEl) fixedLinkTitleEl.textContent = '固定分享链接（可选）';
            if (fixedLinkHintEl) fixedLinkHintEl.textContent = `资源搜索会优先执行（TG 频道搜索，及启用时的 PanSou 搜索）；下方开关开启后，这个固定 ${providerLabel} 分享链接会作为备选候选排在资源搜索候选之后。`;
            if (shareSubdirLabelEl) shareSubdirLabelEl.textContent = `${providerLabel} 分享子目录（可选）`;
            if (shareLinkInputEl) {
                const exampleMap = {
                    '115': 'https://115.com/s/xxxxxxx?password=abcd',
                    quark: 'https://pan.quark.cn/s/xxxxxx',
                    aliyun: 'https://www.alipan.com/s/xxxxxx',
                    '123pan': 'https://www.123pan.com/s/xxxxxx',
                    tianyi: 'https://cloud.189.cn/t/xxxxxx',
                };
                shareLinkInputEl.placeholder = `例如：${exampleMap[provider] || 'https://example.com/s/xxxxxx'}`;
            }
            syncSubscriptionScanTuningHint(provider);

            if (!hasFixedShare) {
                const shareLinkInput = document.getElementById('subscription_share_link_url');
                const shareReceiveInput = document.getElementById('subscription_share_receive_code');
                const fixedLinkSearchInput = document.getElementById('subscription_fixed_link_channel_search');
                if (shareLinkInput) shareLinkInput.value = '';
                if (shareReceiveInput) shareReceiveInput.value = '';
                if (fixedLinkSearchInput) fixedLinkSearchInput.checked = false;
                setSubscriptionShareSubdirSelection('', '');
                resetSubscriptionShareFolderBrowser();
            }
        }

        function syncSubscriptionTypeUI({ forceSuggestTotal = false } = {}) {
            const mediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            const tvFields = document.getElementById('subscription-tv-fields');
            if (tvFields) tvFields.classList.toggle('hidden', mediaType !== 'tv');
            const animeModeWrap = document.getElementById('subscription-anime-mode-wrap');
            if (animeModeWrap) animeModeWrap.classList.toggle('hidden', mediaType !== 'tv');
            const seasonInput = document.getElementById('subscription_season');
            const multiSeasonMode = !!document.getElementById('subscription_anime_mode')?.checked;
            if (seasonInput) {
                const disableSeason = mediaType !== 'tv' || multiSeasonMode;
                seasonInput.disabled = disableSeason;
                if (disableSeason) seasonInput.setAttribute('title', '多季合一已开启时，季数不参与订阅过滤');
                else seasonInput.removeAttribute('title');
            }
            const hintEl = document.getElementById('subscription-savepath-hint');
            if (hintEl) {
                hintEl.innerText = mediaType === 'movie'
                    ? '电影会自动保存到“目标目录/影片名”子文件夹；电视剧保存到所选目录。'
                    : '电视剧会直接保存到所选目录；请把目录设在剧集父文件夹下。';
            }
            syncSubscriptionProviderUI();
            suggestSubscriptionTotalEpisodesFromTmdb({ force: !!forceSuggestTotal });
            renderSubscriptionTmdbBinding();
        }

        function setSubscriptionSavepath(folderId = '0', displayPath = '', { trail = null } = {}) {
            const normalizedFolderId = String(folderId || '0').trim() || '0';
            const normalizedPath = normalizeRelativePathInput(displayPath || '');
            const hiddenFolderEl = document.getElementById('subscription_folder_id');
            const hiddenSavepathEl = document.getElementById('subscription_savepath');
            const displayEl = document.getElementById('subscription_savepath_display');
            if (hiddenFolderEl) hiddenFolderEl.value = normalizedFolderId;
            if (hiddenSavepathEl) hiddenSavepathEl.value = normalizedPath;
            if (displayEl) displayEl.value = normalizedPath || '请选择保存目录';
            if (Array.isArray(trail) && trail.length) {
                subscriptionFolderTrail = trail;
            }
        }

        function currentSubscriptionFormData() {
            const title = document.getElementById('subscription_title').value.trim();
            const provider = getCurrentSubscriptionProvider();
            const tmdbBinding = getSubscriptionTmdbBindingFromForm();
            const multiSeasonMode = !!document.getElementById('subscription_anime_mode').checked;
            const scheduleWeekdays = getSubscriptionWeekdaysFromForm();
            const scheduleStartTime = normalizeSubscriptionScheduleTime(
                document.getElementById('subscription_schedule_start_time')?.value || '00:00',
                '00:00'
            );
            const scheduleEndTime = normalizeSubscriptionScheduleTime(
                document.getElementById('subscription_schedule_end_time')?.value || '23:59',
                '23:59'
            );
            const scheduleIntervalMinutes = Math.max(
                1,
                parseInt(
                    document.getElementById('subscription_schedule_interval_minutes')?.value || String(SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES),
                    10
                ) || SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES
            );
            const shareLinkRaw = String(document.getElementById('subscription_share_link_url')?.value || '').trim();
            const shareLinkType = detectResourceLinkTypeByUrl(shareLinkRaw);
            const providerMeta = (window.providerMeta || []).find(m => m.name === provider);
            const providerLinkType = String(providerMeta?.link_type || '').trim().toLowerCase();
            const normalizedShareLink = providerLinkType && shareLinkType === providerLinkType ? shareLinkRaw : '';
            const receiveCodeRaw = String(document.getElementById('subscription_share_receive_code')?.value || '').trim();
            const normalizedReceiveCode = normalizeReceiveCodeInput(receiveCodeRaw);
            const shareSubdir = normalizeRelativePathInput(document.getElementById('subscription_share_subdir')?.value || '');
            const shareSubdirCid = shareSubdir
                ? normalizeShareCidInput(document.getElementById('subscription_share_subdir_cid')?.value || '')
                : '';
            const fixedLinkChannelSearch = !!normalizedShareLink && !!document.getElementById('subscription_fixed_link_channel_search')?.checked;
            const excludeKeywords = parseSubscriptionExcludeKeywords(document.getElementById('subscription_exclude_keywords')?.value || '');
            const excludeInput = document.getElementById('subscription_exclude_keywords');
            if (excludeInput) excludeInput.value = excludeKeywords.join(', ');
            const excludeFileExtensions = parseSubscriptionExcludeFileExtensions(document.getElementById('subscription_exclude_file_extensions')?.value || '');
            const excludeFileInput = document.getElementById('subscription_exclude_file_extensions');
            if (excludeFileInput) excludeFileInput.value = excludeFileExtensions.join(', ');
            const minFileSizeInput = document.getElementById('subscription_min_file_size_mb');
            const minFileSizeMb = normalizeSubscriptionMinFileSizeMb(minFileSizeInput?.value || '0');
            if (minFileSizeInput) minFileSizeInput.value = formatSubscriptionMinFileSizeMb(minFileSizeMb);
            const scanSettings = readSubscriptionScanSettingsFromForm(provider);
            return {
                name: title,
                provider,
                media_type: normalizeSubscriptionMediaType(document.getElementById('subscription_media_type').value),
                title,
                aliases: document.getElementById('subscription_aliases').value.trim(),
                exclude_keywords: excludeKeywords,
                exclude_file_extensions: excludeFileExtensions,
                year: document.getElementById('subscription_year').value.trim(),
                season: parseInt(document.getElementById('subscription_season').value || '1', 10) || 1,
                total_episodes: parseInt(document.getElementById('subscription_total_episodes').value || '0', 10) || 0,
                anime_mode: multiSeasonMode,
                multi_season_mode: multiSeasonMode,
                savepath: normalizeRelativePathInput(document.getElementById('subscription_savepath').value.trim()),
                share_link_url: normalizedShareLink,
                share_link_receive_code: normalizedReceiveCode,
                share_subdir: shareSubdir,
                share_subdir_cid: shareSubdirCid,
                fixed_link_channel_search: fixedLinkChannelSearch,
                schedule_weekdays: scheduleWeekdays,
                schedule_start_time: scheduleStartTime,
                schedule_end_time: scheduleEndTime,
                schedule_interval_minutes: scheduleIntervalMinutes,
                min_score: parseInt(document.getElementById('subscription_min_score').value || '55', 10) || 55,
                quality_priority: normalizeSubscriptionQualityPriority(document.getElementById('subscription_quality_priority').value || 'ultra'),
                min_file_size_mb: minFileSizeMb,
                strict_title_match: !!document.getElementById('subscription_strict_title_match')?.checked,
                candidate_scan_prefetch_limit: scanSettings.candidate_scan_prefetch_limit,
                candidate_scan_concurrency: scanSettings.candidate_scan_concurrency,
                share_scan_concurrency: scanSettings.share_scan_concurrency,
                share_scan_rate_limit_seconds: scanSettings.share_scan_rate_limit_seconds,
                enabled: document.getElementById('subscription_enabled').checked,
                tmdb_id: tmdbBinding.tmdb_id,
                tmdb_media_type: tmdbBinding.tmdb_media_type,
                tmdb_title: tmdbBinding.tmdb_title,
                tmdb_original_title: tmdbBinding.tmdb_original_title,
                tmdb_year: tmdbBinding.tmdb_year,
                tmdb_aliases: tmdbBinding.tmdb_aliases,
                tmdb_total_episodes: tmdbBinding.tmdb_total_episodes,
                tmdb_total_seasons: tmdbBinding.tmdb_total_seasons,
                tmdb_season_episode_map: tmdbBinding.tmdb_season_episode_map,
                tmdb_episode_mode: tmdbBinding.tmdb_episode_mode,
            };
        }

        function resetSubscriptionForm() {
            editingSubscriptionName = null;
            const titleEl = document.getElementById('subscription-modal-title');
            if (titleEl) titleEl.innerText = '新增订阅任务';
            document.getElementById('subscription_media_type').value = 'tv';
            const providerInput = document.getElementById('subscription_provider');
            if (providerInput) {
                const firstProvider = (window.providerMeta || []).find(p => p.enabled && p.supports_subscription)?.name || '115';
                providerInput.value = firstProvider;
            }
            document.getElementById('subscription_title').value = '';
            document.getElementById('subscription_aliases').value = '';
            const excludeInput = document.getElementById('subscription_exclude_keywords');
            if (excludeInput) excludeInput.value = '';
            const excludeFileInput = document.getElementById('subscription_exclude_file_extensions');
            if (excludeFileInput) excludeFileInput.value = SUBSCRIPTION_DEFAULT_EXCLUDE_FILE_EXTENSIONS.join(', ');
            document.getElementById('subscription_year').value = '';
            document.getElementById('subscription_season').value = 1;
            document.getElementById('subscription_total_episodes').value = 0;
            document.getElementById('subscription_anime_mode').checked = false;
            setSubscriptionSavepath('0', '');
            const shareLinkInput = document.getElementById('subscription_share_link_url');
            if (shareLinkInput) shareLinkInput.value = '';
            const shareReceiveInput = document.getElementById('subscription_share_receive_code');
            if (shareReceiveInput) shareReceiveInput.value = '';
            const fixedLinkChannelSearchInput = document.getElementById('subscription_fixed_link_channel_search');
            if (fixedLinkChannelSearchInput) fixedLinkChannelSearchInput.checked = false;
            setSubscriptionShareSubdirSelection('', '');
            resetSubscriptionShareFolderBrowser();
            subscriptionFolderTrail = [{ id: '0', name: '根目录' }];
            subscriptionFolderEntries = [];
            subscriptionFolderSummary = { folder_count: 0, file_count: 0 };
            subscriptionFolderLoading = false;
            subscriptionFolderCreateBusy = false;
            setSubscriptionWeekdaysToForm(SUBSCRIPTION_DEFAULT_WEEKDAYS);
            document.getElementById('subscription_schedule_start_time').value = '00:00';
            document.getElementById('subscription_schedule_end_time').value = '23:59';
            document.getElementById('subscription_schedule_interval_minutes').value = SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES;
            document.getElementById('subscription_min_score').value = 55;
            document.getElementById('subscription_min_file_size_mb').value = 0;
            const strictTitleInput = document.getElementById('subscription_strict_title_match');
            if (strictTitleInput) strictTitleInput.checked = false;
            document.getElementById('subscription_quality_priority').value = 'ultra';
            setSubscriptionScanSettingsToForm(getSubscriptionScanRecommendedDefaults(providerInput?.value || '115'), providerInput?.value || '115');
            document.getElementById('subscription_enabled').checked = true;
            clearSubscriptionTmdbBinding({ silent: true });
            subscriptionTmdbResults = [];
            subscriptionTmdbSearchToken += 1;
            setSubscriptionTmdbSearchBusy(false);
            const tmdbKeywordInput = document.getElementById('subscription_tmdb_search_keyword');
            if (tmdbKeywordInput) tmdbKeywordInput.value = '';
            const tmdbHintEl = document.getElementById('subscription_tmdb_search_hint');
            if (tmdbHintEl) tmdbHintEl.innerText = '按当前订阅类型（电影/电视剧）检索 TMDB，选择后会写入任务绑定信息。';
            renderSubscriptionTmdbResults();
            syncSubscriptionTypeUI();
        }

        function openNewSubscriptionTask(prefill = null) {
            resetSubscriptionForm();
            if (prefill && typeof prefill === 'object') applySubscriptionPrefill(prefill);
            showLockedModal('subscription-modal');
            switchTab('subscription');
        }

        function openSubscriptionFromResource(resourceOrId) {
            const directItem = resourceOrId && typeof resourceOrId === 'object' ? resourceOrId : null;
            const resourceId = Number(directItem ? directItem.id : resourceOrId || 0);
            let item = directItem;
            if (!item && resourceId) item = findResourceItem(resourceId);
            if (!item && selectedResourceItem && Number(selectedResourceItem?.id || 0) === resourceId) item = selectedResourceItem;
            if (!item) {
                showToast('未找到资源，无法转订阅', { tone: 'error', duration: 2600, placement: 'top-center' });
                return;
            }
            const resourceModal = document.getElementById('resource-import-modal');
            if (resourceModal && !resourceModal.classList.contains('hidden')) {
                closeResourceJobModal();
            }
            openNewSubscriptionTask(inferSubscriptionDraftFromResource(item));
            showToast('已预填订阅信息，请继续补充保存目录等配置后保存任务', {
                tone: 'success',
                duration: 3200,
                placement: 'top-center'
            });
        }

        function closeSubscriptionModal() {
            hideLockedModal('subscription-modal');
        }

        async function persistSubscriptionTasks(tasks) {
            const data = await window.MediaHubApi.postJson('/subscription/save', { tasks });
            applySubscriptionState({ ...subscriptionState, tasks: data.tasks || [] }, { forceRender: true });
        }

        function buildSubscriptionProviderTaskName(title, provider) {
            const normalizedTitle = String(title || '').trim();
            if (!normalizedTitle) return '';
            const suffix = getSubscriptionProviderBadgeLabel(provider);
            return `${normalizedTitle} (${suffix})`;
        }

        async function saveSubscriptionTask() {
            const task = currentSubscriptionFormData();
            task.provider = normalizeSubscriptionProvider(task.provider, '115');
            const _taskP = (window.providerMeta || []).find(m => m.name === task.provider);
            const _hasFixedShare = _taskP && _taskP.supports_fixed_share_link;
            const _hasOffline = _taskP && _taskP.supports_offline;
            if (!task.title) return showToast('订阅影视名称不能为空', { tone: 'warn', duration: 2600, placement: 'top-center' });
            if (!task.savepath) return showToast('请先从网盘选择保存目录', { tone: 'warn', duration: 2800, placement: 'top-center' });
            const rawShareLink = String(document.getElementById('subscription_share_link_url')?.value || '').trim();
            if (_hasFixedShare && rawShareLink && !task.share_link_url) {
                const providerLabel = getSubscriptionProviderLabel(task.provider);
                return showToast(`固定分享链接仅支持当前 ${providerLabel} 分享链接格式`, { tone: 'warn', duration: 3000, placement: 'top-center' });
            }
            const rawReceiveCode = String(document.getElementById('subscription_share_receive_code')?.value || '').trim();
            if (_hasFixedShare && rawReceiveCode && !task.share_link_receive_code) return showToast('提取码格式不正确，请输入 1-16 位字母或数字', { tone: 'warn', duration: 3000, placement: 'top-center' });
            if (!_hasFixedShare || !task.share_link_url) {
                task.share_link_url = '';
                task.share_link_receive_code = '';
                task.share_subdir = '';
                task.share_subdir_cid = '';
                task.fixed_link_channel_search = false;
            }
            if (!task.share_subdir) task.share_subdir_cid = '';
            if (task.year && !/^(19|20)\d{2}$/.test(task.year)) return showToast('年份格式不正确，请输入四位年份', { tone: 'warn', duration: 2800, placement: 'top-center' });
            if (task.schedule_start_time === task.schedule_end_time) return showToast('开始时间和结束时间不能相同', { tone: 'warn', duration: 2800, placement: 'top-center' });
            if (task.schedule_interval_minutes < 1) return showToast('时段内查询间隔不能小于 1 分钟', { tone: 'warn', duration: 3000, placement: 'top-center' });
            if (task.enabled && (!Array.isArray(task.schedule_weekdays) || task.schedule_weekdays.length <= 0)) {
                return showToast('请至少选择一个查询星期，或先关闭任务启用状态', { tone: 'warn', duration: 3400, placement: 'top-center' });
            }
            if (_hasFixedShare || _taskP?.supports_subscription) {
                if (task.min_score < 30 || task.min_score > 100) return showToast('匹配阈值需在 30-100 之间', { tone: 'warn', duration: 2800, placement: 'top-center' });
            }
            if (!['balanced', 'ultra', 'fhd', 'hd', 'sd'].includes(task.quality_priority)) return showToast('清晰度优先级配置无效', { tone: 'warn', duration: 2800, placement: 'top-center' });
            if (task.tmdb_id > 0 && task.tmdb_media_type && task.tmdb_media_type !== task.media_type) {
                return showToast('TMDB 绑定类型与订阅类型不一致，请重新绑定', { tone: 'warn', duration: 3200, placement: 'top-center' });
            }
            if (task.media_type !== 'tv') {
                task.season = 1;
                task.total_episodes = 0;
                task.anime_mode = false;
                task.multi_season_mode = false;
                task.tmdb_total_episodes = 0;
                task.tmdb_total_seasons = 0;
                task.tmdb_season_episode_map = {};
                task.tmdb_episode_mode = 'seasonal';
            } else {
                task.multi_season_mode = !!(task.multi_season_mode ?? task.anime_mode);
                task.anime_mode = !!task.multi_season_mode;
                task.tmdb_episode_mode = normalizeTmdbEpisodeMode(task.tmdb_episode_mode || 'seasonal');
                if (!task.multi_season_mode) {
                    const seasonTotal = getTmdbSeasonEpisodeTotal(task.tmdb_season_episode_map || {}, task.season);
                    const tmdbTotal = Math.max(0, parseInt(task.tmdb_total_episodes || '0', 10) || 0);
                    if (seasonTotal > 0 && (task.total_episodes <= 0 || (tmdbTotal > 0 && task.total_episodes === tmdbTotal && seasonTotal !== tmdbTotal))) {
                        task.total_episodes = seasonTotal;
                    }
                }
            }
            if (task.tmdb_id <= 0) {
                task.tmdb_media_type = '';
                task.tmdb_title = '';
                task.tmdb_original_title = '';
                task.tmdb_year = '';
                task.tmdb_aliases = [];
                task.tmdb_total_episodes = 0;
                task.tmdb_total_seasons = 0;
                task.tmdb_season_episode_map = {};
                task.tmdb_episode_mode = 'seasonal';
            }

            const tasks = [...(subscriptionState.tasks || [])].map(item => ({
                ...item,
                aliases: Array.isArray(item.aliases) ? item.aliases.join(', ') : (item.aliases || '')
            }));
            const normalizedTitle = String(task.title || '').trim();
            const editingTask = tasks.find((item) => String(item?.name || '').trim() === String(editingSubscriptionName || '').trim()) || null;
            const editingName = String(editingSubscriptionName || '').trim();
            const keepsProviderSuffix = /\s\((?:115|quark)\)$/i.test(editingName);
            if (editingTask && keepsProviderSuffix && String(task.name || '').trim() === normalizedTitle) {
                task.name = buildSubscriptionProviderTaskName(normalizedTitle, task.provider);
            }
            const hasSameTitleOtherProvider = tasks.some((item) => {
                if (String(item?.name || '').trim() === String(editingSubscriptionName || '').trim()) return false;
                const itemTitle = String(item?.title || '').trim();
                if (!itemTitle || itemTitle !== normalizedTitle) return false;
                const itemProvider = normalizeSubscriptionProvider(item?.provider || '115', '115');
                return itemProvider !== task.provider;
            });
            if (hasSameTitleOtherProvider && String(task.name || '').trim() === normalizedTitle) {
                task.name = buildSubscriptionProviderTaskName(normalizedTitle, task.provider);
            }
            const dup = tasks.find(item => item.name === task.name && item.name !== editingSubscriptionName);
            if (dup) return showToast(`任务名称重复（${task.name}），请修改标题或网盘提供方后再保存`, { tone: 'warn', duration: 3600, placement: 'top-center' });
            const idx = tasks.findIndex(item => item.name === editingSubscriptionName);
            if (idx >= 0) tasks[idx] = task;
            else tasks.push(task);

            try {
                await persistSubscriptionTasks(tasks);
                closeSubscriptionModal();
                resetSubscriptionForm();
                showToast('订阅任务已保存', { tone: 'success', duration: 2400, placement: 'top-center' });
            } catch (e) {
                showToast(`保存失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        function editSubscriptionTask(name) {
            const task = (subscriptionState.tasks || []).find(item => item.name === name);
            if (!task) return;
            editingSubscriptionName = task.name;
            const titleEl = document.getElementById('subscription-modal-title');
            if (titleEl) titleEl.innerText = `编辑订阅任务：${task.name}`;
            const providerInput = document.getElementById('subscription_provider');
            if (providerInput) providerInput.value = normalizeSubscriptionProvider(task.provider || '115', '115');
            document.getElementById('subscription_media_type').value = normalizeSubscriptionMediaType(task.media_type || 'movie');
            document.getElementById('subscription_title').value = task.title || '';
            document.getElementById('subscription_aliases').value = Array.isArray(task.aliases) ? task.aliases.join(', ') : (task.aliases || '');
            const excludeInput = document.getElementById('subscription_exclude_keywords');
            if (excludeInput) excludeInput.value = formatSubscriptionExcludeKeywords(task.exclude_keywords || task.exclude_words || '');
            const excludeFileInput = document.getElementById('subscription_exclude_file_extensions');
            if (excludeFileInput) excludeFileInput.value = formatSubscriptionExcludeFileExtensions(
                Array.isArray(task.exclude_file_extensions)
                    ? task.exclude_file_extensions
                    : SUBSCRIPTION_DEFAULT_EXCLUDE_FILE_EXTENSIONS
            );
            document.getElementById('subscription_year').value = task.year || '';
            document.getElementById('subscription_season').value = task.season || 1;
            document.getElementById('subscription_total_episodes').value = task.total_episodes || 0;
            document.getElementById('subscription_anime_mode').checked = resolveTaskMultiSeasonMode(task);
            subscriptionFolderTrail = [{ id: '0', name: '根目录' }];
            setSubscriptionSavepath('0', task.savepath || '');
            const shareLinkInput = document.getElementById('subscription_share_link_url');
            if (shareLinkInput) shareLinkInput.value = String(task.share_link_url || '').trim();
            const shareReceiveInput = document.getElementById('subscription_share_receive_code');
            if (shareReceiveInput) shareReceiveInput.value = normalizeReceiveCodeInput(task.share_link_receive_code || '');
            const fixedLinkChannelSearchInput = document.getElementById('subscription_fixed_link_channel_search');
            if (fixedLinkChannelSearchInput) fixedLinkChannelSearchInput.checked = !!task.fixed_link_channel_search;
            setSubscriptionShareSubdirSelection(task.share_subdir || '', task.share_subdir_cid || '');
            resetSubscriptionShareFolderBrowser();
            setSubscriptionWeekdaysToForm(task.schedule_weekdays || SUBSCRIPTION_DEFAULT_WEEKDAYS);
            document.getElementById('subscription_schedule_start_time').value = normalizeSubscriptionScheduleTime(task.schedule_start_time || '00:00', '00:00');
            document.getElementById('subscription_schedule_end_time').value = normalizeSubscriptionScheduleTime(task.schedule_end_time || '23:59', '23:59');
            document.getElementById('subscription_schedule_interval_minutes').value = Math.max(
                1,
                parseInt(
                    task.schedule_interval_minutes ?? task.cron_minutes ?? SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES,
                    10
                ) || SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES
            );
            document.getElementById('subscription_min_score').value = task.min_score ?? 55;
            document.getElementById('subscription_min_file_size_mb').value = formatSubscriptionMinFileSizeMb(task.min_file_size_mb ?? 0);
            const strictTitleInput = document.getElementById('subscription_strict_title_match');
            if (strictTitleInput) strictTitleInput.checked = !!task.strict_title_match;
            document.getElementById('subscription_quality_priority').value = normalizeSubscriptionQualityPriority(task.quality_priority || 'balanced');
            setSubscriptionScanSettingsToForm(task, normalizeSubscriptionProvider(task.provider || '115', '115'));
            document.getElementById('subscription_enabled').checked = task.enabled !== false;
            setSubscriptionTmdbBinding({
                tmdb_id: task.tmdb_id || 0,
                tmdb_media_type: task.tmdb_media_type || '',
                tmdb_title: task.tmdb_title || '',
                tmdb_original_title: task.tmdb_original_title || '',
                tmdb_year: task.tmdb_year || '',
                tmdb_aliases: Array.isArray(task.tmdb_aliases) ? task.tmdb_aliases : [],
                tmdb_total_episodes: task.tmdb_total_episodes || 0,
                tmdb_total_seasons: task.tmdb_total_seasons || 0,
                tmdb_season_episode_map: task.tmdb_season_episode_map || {},
                tmdb_episode_mode: task.tmdb_episode_mode || 'seasonal',
            });
            syncSubscriptionTypeUI();
            showLockedModal('subscription-modal');
            switchTab('subscription');
        }

        async function deleteSubscriptionTask(name) {
            if (!(await showAppConfirm(`确定删除订阅任务“${name}”吗？`))) return;
            try {
                await window.MediaHubApi.postJson('/subscription/delete', { name });
            } catch (error) {
                showToast(`删除失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return;
            }
            await refreshSubscriptionState();
            if (editingSubscriptionName === name) resetSubscriptionForm();
        }

        async function startSubscriptionTask(name) {
            let data = {};
            try {
                data = await window.MediaHubApi.postJson('/subscription/start', { name });
            } catch (error) {
                showToast(`启动失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return;
            }
            if (data.status === 'queued') {
                const queued = Array.isArray(subscriptionState.queued) ? [...subscriptionState.queued] : [];
                if (!queued.includes(name)) queued.push(name);
                applySubscriptionState({ ...subscriptionState, queued }, { forceRender: true });
            } else {
                applySubscriptionState({
                    ...subscriptionState,
                    running: true,
                    current_task: name,
                    summary: { step: '准备执行', detail: `${name} (manual)` }
                }, { forceRender: true });
            }
            await refreshSubscriptionState();
        }

        function extractFirstHttpUrl(text = '') {
            const raw = String(text || '').trim();
            if (!raw) return '';
            const links = raw.match(/https?:\/\/[^\s<>'"]+/gi) || [];
            if (links.length) return String(links[0] || '').replace(/[，。；、]+$/g, '');
            const compact = raw.replace(/\s+/g, '');
            if (/^[a-z0-9.-]+\.[a-z]{2,}(?:\/[^\s]*)?$/i.test(compact)) return compact;
            return '';
        }

        function extractFirstSubscriptionShareUrl(text = '', provider = 'quark') {
            const raw = String(text || '').trim();
            if (!raw) return '';
            const normalizedProvider = normalizeSubscriptionProvider(provider, '115');
            const providerMeta = (window.providerMeta || []).find(m => m.name === normalizedProvider);
            const providerLinkType = String(providerMeta?.link_type || '').trim().toLowerCase();
            const allowedTypes = new Set([providerLinkType]);
            if (normalizedProvider === '115') {
                allowedTypes.add('magnet');
                allowedTypes.add('ed2k');
            }
            const links = raw.match(/(?:https?:\/\/)?[^\s<>'"]+/gi) || [];
            for (const link of links) {
                const candidate = String(link || '').replace(/[，。；、]+$/g, '');
                if (!candidate) continue;
                if (allowedTypes.has(detectResourceLinkTypeByUrl(candidate))) return candidate;
            }
            return extractFirstHttpUrl(raw);
        }

        function setSubscriptionLinkScanError(message = '') {
            const errorEl = document.getElementById('subscription-link-scan-error');
            if (!errorEl) return;
            const text = String(message || '').trim();
            errorEl.textContent = text;
            errorEl.classList.toggle('hidden', !text);
        }

        async function pasteSubscriptionLinkScan() {
            const textEl = document.getElementById('subscription-link-scan-text');
            if (!textEl) return;
            if (!navigator.clipboard?.readText) {
                showToast('当前环境不支持一键粘贴，请直接使用 Ctrl/Cmd + V', { tone: 'warn', duration: 2800, placement: 'top-center' });
                return;
            }
            let text = '';
            try {
                text = String(await navigator.clipboard.readText() || '').trim();
            } catch (e) {
                showToast(`读取剪贴板失败：${e?.message || '请检查浏览器权限'}`, { tone: 'warn', duration: 3200, placement: 'top-center' });
                return;
            }
            if (!text) {
                showToast('剪贴板里暂无可粘贴内容', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            textEl.value = text;
            setSubscriptionLinkScanError('');
            textEl.focus();
            textEl.setSelectionRange?.(text.length, text.length);
            showToast('已粘贴剪贴板内容，可直接开始扫描', { tone: 'info', duration: 2200, placement: 'top-center' });
        }

        function openSubscriptionLinkScanModal(name) {
            const task = getSubscriptionTaskByName(name);
            if (!task) {
                showToast('任务不存在或已被删除', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const provider = normalizeSubscriptionProvider(task.provider || '115', '115');
            const providerMeta = (window.providerMeta || []).find(m => m.name === provider);
            if (!providerMeta?.supports_subscription) {
                showToast('当前订阅任务不支持扫描链接', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const providerLabel = getSubscriptionProviderLabel(provider);
            const exampleMap = {
                '115': 'https://115.com/s/xxxxxxx?password=abcd',
                quark: 'https://pan.quark.cn/s/xxxxxx',
                aliyun: 'https://www.alipan.com/s/xxxxxx',
                '123pan': 'https://www.123pan.com/s/xxxxxx',
                tianyi: 'https://cloud.189.cn/t/xxxxxx',
            };
            const example = exampleMap[provider] || 'https://example.com/s/xxxxxx';
            const titleEl = document.getElementById('subscription-link-scan-title');
            const eyebrowEl = document.getElementById('subscription-link-scan-eyebrow');
            const taskNameEl = document.getElementById('subscription-link-scan-task-name');
            const taskLabelEl = document.getElementById('subscription-link-scan-task-label');
            const inputLabelEl = document.getElementById('subscription-link-scan-input-label');
            const textEl = document.getElementById('subscription-link-scan-text');
            const noteEl = document.getElementById('subscription-link-scan-note');
            const submitBtn = document.getElementById('subscription-link-scan-submit-btn');
            if (titleEl) titleEl.textContent = '扫描链接';
            if (eyebrowEl) eyebrowEl.textContent = `${providerLabel} Link Scan`;
            if (taskNameEl) taskNameEl.value = name;
            if (taskLabelEl) taskLabelEl.textContent = `任务：${providerLabel} · ${String(task.title || name || '').trim() || name}`;
            if (inputLabelEl) inputLabelEl.textContent = `${providerLabel} 分享链接或完整分享文本`;
            if (textEl) {
                textEl.value = '';
                if (provider === '115') {
                    textEl.placeholder = '粘贴 115 分享链接、磁力或电驴链接；磁力/电驴会离线下载到 115 中转目录后自动挑选入库';
                } else {
                    textEl.placeholder = `粘贴 ${example}，或包含链接与提取码的整段分享文本`;
                }
            }
            if (noteEl) {
                if (provider === '115') {
                    noteEl.textContent = '提交后会跳过资源搜索；磁力/电驴链接会先离线下载到 115 中转目录（云下载/磁力中转/任务名），下载完成后自动挑选命中文件入库并触发监控。';
                } else {
                    noteEl.textContent = '提交后会跳过资源搜索，把这个链接当作已命中标题的候选资源，继续走订阅的集数识别、缺失判断和导入流程。';
                }
            }
            if (submitBtn) submitBtn.disabled = false;
            setSubscriptionLinkScanError('');
            showLockedModal('subscription-link-scan-modal');
            window.setTimeout(() => textEl?.focus(), 30);
        }

        function closeSubscriptionLinkScanModal() {
            hideLockedModal('subscription-link-scan-modal');
            setSubscriptionLinkScanError('');
        }

        async function submitSubscriptionLinkScan() {
            const name = String(document.getElementById('subscription-link-scan-task-name')?.value || '').trim();
            const rawText = String(document.getElementById('subscription-link-scan-text')?.value || '').trim();
            const submitBtn = document.getElementById('subscription-link-scan-submit-btn');
            if (!name) {
                setSubscriptionLinkScanError('任务名称为空，请关闭后重新从任务卡片进入。');
                return;
            }
            const normalizedRaw = String(rawText || '').trim();
            const task = getSubscriptionTaskByName(name);
            const provider = normalizeSubscriptionProvider(task?.provider || '115', '115');
            const providerMeta = (window.providerMeta || []).find(m => m.name === provider);
            const providerLinkType = String(providerMeta?.link_type || '').trim().toLowerCase();
            const allowedTypes = new Set([providerLinkType]);
            if (provider === '115') {
                allowedTypes.add('magnet');
                allowedTypes.add('ed2k');
            }
            const linkUrl = extractFirstSubscriptionShareUrl(normalizedRaw, provider);
            const validLink = !!providerLinkType && allowedTypes.has(detectResourceLinkTypeByUrl(linkUrl));
            if (!linkUrl || !validLink) {
                const exampleMap = {
                    '115': 'https://115.com/s/xxxxxxx?password=abcd',
                    quark: 'https://pan.quark.cn/s/xxxxxx',
                    aliyun: 'https://www.alipan.com/s/xxxxxx',
                    '123pan': 'https://www.123pan.com/s/xxxxxx',
                    tianyi: 'https://cloud.189.cn/t/xxxxxx',
                };
                const example = exampleMap[provider] || 'https://example.com/s/xxxxxx';
                const providerText =
                    provider === '115'
                        ? `${getSubscriptionProviderLabel(provider)} 分享/磁力/电驴链接`
                        : `${getSubscriptionProviderLabel(provider)} 分享链接`;
                const exampleText = provider === '115' ? '分享链接、磁力或电驴链接' : example;
                setSubscriptionLinkScanError(`请粘贴有效的${providerText}，例如 ${exampleText}`);
                return;
            }
            let data = {};
            try {
                if (submitBtn) submitBtn.disabled = true;
                setSubscriptionLinkScanError('');
                data = await window.MediaHubApi.postJson('/subscription/start_with_link', {
                    name,
                    link_url: linkUrl,
                    raw_text: normalizedRaw,
                });
            } catch (error) {
                setSubscriptionLinkScanError(error?.message || '启动扫描链接失败');
                if (submitBtn) submitBtn.disabled = false;
                return;
            }
            closeSubscriptionLinkScanModal();
            if (data.status === 'queued') {
                const queued = Array.isArray(subscriptionState.queued) ? [...subscriptionState.queued] : [];
                if (!queued.includes(name)) queued.push(name);
                applySubscriptionState({ ...subscriptionState, queued }, { forceRender: true });
            } else {
                applySubscriptionState({
                    ...subscriptionState,
                    running: true,
                    current_task: name,
                    summary: { step: '准备执行', detail: `${name} (manual_link)` }
                }, { forceRender: true });
            }
            showToast('已提交扫描链接', { tone: 'success', duration: 2600, placement: 'top-center' });
            await refreshSubscriptionState();
        }

        async function startSubscriptionTaskWithLink(name) {
            openSubscriptionLinkScanModal(name);
        }

        async function stopSubscriptionTask(name) {
            const data = await window.MediaHubApi.postJson('/subscription/stop', { name }).catch(() => ({ ok: false }));
            if (!data.ok) {
                showToast('当前没有这个订阅任务在运行', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            applySubscriptionState({
                ...subscriptionState,
                summary: { step: '正在中断', detail: `${name} 已发送中断请求` }
            }, { forceRender: true });
            await refreshSubscriptionState();
        }

        async function rebuildSubscriptionTask(name, { refreshEpisodeModal = false } = {}) {
            const normalizedName = String(name || '').trim();
            if (!normalizedName) return;
            if (!(await showAppConfirm(`按当前保存目录重建“${normalizedName}”的追更进度和集数账本吗？`))) return;
            try {
                const data = await window.MediaHubApi.postJson('/subscription/rebuild', { name: normalizedName });
                const episodeView = data.episode_view && typeof data.episode_view === 'object' ? data.episode_view : null;
                if (episodeView) {
                    subscriptionEpisodeViewCache[normalizedName] = {
                        fetched_at: Date.now(),
                        data: episodeView,
                    };
                    if (subscriptionEpisodeViewTaskName === normalizedName) {
                        subscriptionEpisodeViewData = episodeView;
                        subscriptionEpisodeViewError = '';
                        subscriptionEpisodeViewLoading = false;
                        if (refreshEpisodeModal) renderSubscriptionEpisodeModal();
                    }
                } else {
                    delete subscriptionEpisodeViewCache[normalizedName];
                }
                delete subscriptionIntroEpisodeLookupFailedAt[normalizedName];
                showToast(data.msg || '已完成目录重建', { tone: 'success', duration: 3200, placement: 'top-center' });
                await refreshSubscriptionState();
                if (refreshEpisodeModal && subscriptionEpisodeViewTaskName === normalizedName) {
                    await refreshSubscriptionEpisodeView(true);
                }
            } catch (error) {
                showToast(`重建失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
            }
        }

        async function rebuildCurrentSubscriptionEpisodeView() {
            const taskName = String(subscriptionEpisodeViewTaskName || '').trim();
            if (!taskName) return;
            await rebuildSubscriptionTask(taskName, { refreshEpisodeModal: true });
        }

        function buildSubscriptionQuickSearchKeyword(task) {
            const payload = task && typeof task === 'object' ? task : {};
            const title = String(payload.title || payload.tmdb_title || payload.name || '').trim();
            if (!title) return '';
            const mediaType = normalizeSubscriptionMediaType(payload.media_type || 'movie');
            const season = Math.max(1, parseInt(payload.season || '1', 10) || 1);
            const multiSeasonMode = resolveTaskMultiSeasonMode(payload);
            if (mediaType === 'tv' && !multiSeasonMode && season > 1) {
                return `${title} 第${season}季`;
            }
            return title;
        }

        async function quickSearchSubscriptionTask(taskName) {
            const task = getSubscriptionTaskByName(taskName);
            if (!task) {
                showToast('任务不存在或已被删除', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            const keyword = buildSubscriptionQuickSearchKeyword(task);
            if (!keyword) {
                showToast('订阅任务缺少可搜索标题', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }

            if (typeof switchTab === 'function') {
                await switchTab('resource');
            }
            const input = document.getElementById('resource-search-input');
            if (input) {
                input.value = keyword;
                input.focus();
                input.setSelectionRange?.(keyword.length, keyword.length);
            }
            if (typeof syncResourceSearchInputActions === 'function') syncResourceSearchInputActions();
            if (typeof searchResources === 'function') {
                await searchResources();
                return;
            }
            showToast(`已跳转资源搜索：${keyword}`, { tone: 'info', duration: 2400, placement: 'top-center' });
        }

        function buildSubscriptionTaskActionIcon(icon) {
            const icons = {
                run: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M8 5.75V18.25L17.5 12L8 5.75Z" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
                stop: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7.25 7.25H16.75V16.75H7.25V7.25Z" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
                queued: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 19.25A7.25 7.25 0 1 0 12 4.75A7.25 7.25 0 0 0 12 19.25Z" stroke="currentColor" stroke-width="1.8"/><path d="M12 8.25V12.25L14.75 14.25" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
                search: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M10.75 17.25A6.5 6.5 0 1 0 10.75 4.25A6.5 6.5 0 0 0 10.75 17.25Z" stroke="currentColor" stroke-width="1.85"/><path d="M15.5 15.5L20 20" stroke="currentColor" stroke-width="1.85" stroke-linecap="round"/></svg>',
                scan: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M8.5 12.75L7.25 14A3 3 0 0 0 11.5 18.25L13 16.75" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M15.5 11.25L16.75 10A3 3 0 0 0 12.5 5.75L11 7.25" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M9.75 14.25L14.25 9.75" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
                edit: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5.25 18.75L9.1 17.9L18.45 8.55A2.05 2.05 0 0 0 15.55 5.65L6.2 15L5.25 18.75Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M14.35 6.85L17.15 9.65" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
                delete: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 7.5H19" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M9.25 7.5V5.75H14.75V7.5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M8 10V18.25H16V10" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M10.5 11.5V16.5M13.5 11.5V16.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
                rebuild: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M18.6 11.75A6.6 6.6 0 1 1 16.65 7.05" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M19.25 5.25V9.35H15.15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
                episodes: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5.25 6.25H10V11H5.25V6.25ZM14 6.25H18.75V11H14V6.25ZM5.25 14H10V18.75H5.25V14ZM14 14H18.75V18.75H14V14Z" stroke="currentColor" stroke-width="1.65" stroke-linejoin="round"/></svg>',
                collapse: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 14L12 9L17 14" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
                expand: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 10L12 15L17 10" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            };
            return icons[icon] || icons.edit;
        }

        function buildSubscriptionTaskIconButton({
            action,
            taskName,
            label,
            icon,
            tone = 'neutral',
            disabled = false,
            extraAttrs = '',
        } = {}) {
            const normalizedAction = String(action || '').trim();
            const normalizedLabel = String(label || '').trim();
            if (!normalizedAction || !normalizedLabel) return '';
            const attrText = String(extraAttrs || '').trim();
            const disabledAttrs = disabled ? ' disabled aria-disabled="true"' : '';
            return `
                <button
                    type="button"
                    data-subscription-action="${escapeHtml(normalizedAction)}"
                    data-task-name="${encodeURIComponent(taskName)}"
                    class="subscription-task-icon-btn subscription-task-icon-btn-${escapeHtml(tone)} ${disabled ? 'btn-disabled' : ''}"
                    title="${escapeHtml(normalizedLabel)}"
                    aria-label="${escapeHtml(normalizedLabel)}"
                    ${attrText ? `${attrText} ` : ''}${disabledAttrs}
                >
                    ${buildSubscriptionTaskActionIcon(icon)}
                </button>
            `;
        }

        function renderSubscriptionTasks() {
            const container = document.getElementById('subscription-task-list');
            if (!container) return;
            const tasks = subscriptionState.tasks || [];
            if (!tasks.length) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">还没有订阅任务，点击“新增订阅任务”即可创建。</div>';
                return;
            }
            container.innerHTML = tasks.map(task => {
                const taskName = String(task.name || '').trim();
                const displayTitle = String(task.title || taskName || '').trim() || taskName;
                const provider = normalizeSubscriptionProvider(task.provider || '115', '115');
                const providerBadgeHtml = buildSubscriptionProviderBadge(provider);
                const strictBadgeHtml = task?.strict_title_match
                    ? '<span class="subscription-strict-match-badge">精准</span>'
                    : '';
                const lastHitBadgeHtml = buildSubscriptionLastHitBadge(task);
                const running = subscriptionState.running && subscriptionState.current_task === taskName;
                const queued = (subscriptionState.queued || []).includes(taskName);
                const status = running ? 'running' : (task.status || 'idle');
                const nextRun = (subscriptionState.next_runs || {})[taskName];
                const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
                const isTv = normalizeSubscriptionMediaType(task.media_type || 'movie') === 'tv';
                const multiSeasonMode = resolveTaskMultiSeasonMode(task);
                const introExpanded = isTaskIntroExpanded(subscriptionTaskIntroExpanded, taskName);
                if (isTv && introExpanded) ensureSubscriptionIntroEpisode(taskName);
                const episodeText = isTv
                    ? buildSubscriptionTaskEpisodeText(task, taskName, { introExpanded })
                    : '电影订阅：命中资源即执行';
                const progressBarHtml = status === 'running'
                    ? buildSubscriptionTaskProgressBar({
                        progress,
                        detail: String(task?.detail || '').trim(),
                    })
                    : '';
                const toggleRunLabel = running ? '中断' : (queued ? '排队中' : '运行');
                const toggleRunAction = running ? 'stop' : 'start';
                const toggleRunDisabled = queued || (subscriptionState.running && !running);
                const toggleRunTone = running ? 'stop' : (queued ? 'queued' : 'run');
                const toggleRunIcon = running ? 'stop' : (queued ? 'queued' : 'run');
                const rebuildDisabled = running;
                const actionBarClass = isTv
                    ? 'subscription-task-actions subscription-task-actions-tv subscription-task-actionbar'
                    : 'subscription-task-actions subscription-task-actions-movie subscription-task-actionbar';
                const toggleRunButton = buildSubscriptionTaskIconButton({
                    action: 'toggle-run',
                    taskName,
                    label: toggleRunLabel,
                    icon: toggleRunIcon,
                    tone: toggleRunTone,
                    disabled: toggleRunDisabled,
                    extraAttrs: `data-subscription-run-action="${escapeHtml(toggleRunAction)}"`,
                });
                const searchButton = buildSubscriptionTaskIconButton({
                    action: 'search',
                    taskName,
                    label: '搜索',
                    icon: 'search',
                    tone: 'search',
                });
                const rebuildButton = isTv
                    ? buildSubscriptionTaskIconButton({
                        action: 'rebuild',
                        taskName,
                        label: '校准',
                        icon: 'rebuild',
                        tone: 'rebuild',
                        disabled: rebuildDisabled,
                    })
                    : '';
                const episodeViewButton = isTv
                    ? buildSubscriptionTaskIconButton({
                        action: 'episodes',
                        taskName,
                        label: '集数视图',
                        icon: 'episodes',
                        tone: 'episodes',
                    })
                    : '';
                const providerMeta = (window.providerMeta || []).find(m => m.name === provider);
                const linkScanButton = providerMeta?.supports_subscription
                    ? buildSubscriptionTaskIconButton({
                        action: 'scan-link',
                        taskName,
                        label: '扫描链接',
                        icon: 'scan',
                        tone: 'scan',
                        disabled: toggleRunDisabled,
                    })
                    : '';
                const editButton = buildSubscriptionTaskIconButton({
                    action: 'edit',
                    taskName,
                    label: '编辑',
                    icon: 'edit',
                    tone: 'edit',
                });
                const deleteButton = buildSubscriptionTaskIconButton({
                    action: 'delete',
                    taskName,
                    label: '删除',
                    icon: 'delete',
                    tone: 'delete',
                });
                const introText = buildSubscriptionTaskIntro(task, { status, queued, nextRun, progress, isTv, episodeText, multiSeasonMode });
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-3 sm:p-4">
                        <div class="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
                            <div class="min-w-0 flex-1 flex items-center justify-between gap-3">
                                <button
                                    type="button"
                                    data-subscription-toggle-intro="${encodeURIComponent(taskName)}"
                                    aria-expanded="${introExpanded ? 'true' : 'false'}"
                                    class="min-w-0 flex-1 text-left rounded-lg border border-transparent hover:border-slate-700/75 focus:outline-none focus:ring-2 focus:ring-sky-500/45 px-1 py-0.5"
                                >
                                    <div class="flex flex-wrap items-center gap-2">
                                        <span class="text-lg font-black text-white break-all leading-tight">${escapeHtml(displayTitle)}</span>
                                        ${providerBadgeHtml}
                                        ${strictBadgeHtml}
                                        ${lastHitBadgeHtml}
                                    </div>
                                </button>
                                <button
                                    type="button"
                                    data-subscription-toggle-intro="${encodeURIComponent(taskName)}"
                                    aria-expanded="${introExpanded ? 'true' : 'false'}"
                                    class="subscription-intro-toggle-btn"
                                    title="${introExpanded ? '收起简介' : '展开简介'}"
                                    aria-label="${introExpanded ? '收起简介' : '展开简介'}"
                                >${buildSubscriptionTaskActionIcon(introExpanded ? 'collapse' : 'expand')}</button>
                            </div>
                            <div class="${actionBarClass}" aria-label="订阅任务操作">
                                ${toggleRunButton}
                                ${searchButton}
                                ${linkScanButton}
                                ${editButton}
                                ${deleteButton}
                                ${rebuildButton}
                                ${episodeViewButton}
                            </div>
                        </div>
                        ${progressBarHtml}
                        ${introExpanded ? `<div class="mt-3 text-xs text-slate-300 leading-6 rounded-xl border border-slate-700/90 bg-slate-950/45 px-3 py-2">${escapeHtml(introText)}</div>` : ''}
                    </div>
                `;
            }).join('');
        }

        function getSubscriptionTaskByName(taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return null;
            return (subscriptionState.tasks || []).find(item => String(item?.name || '').trim() === normalizedName) || null;
        }

        function normalizeEpisodeList(values) {
            const result = [];
            const seen = new Set();
            (Array.isArray(values) ? values : []).forEach((item) => {
                const episodeNo = parseInt(item || '0', 10) || 0;
                if (episodeNo <= 0 || episodeNo > 5000 || seen.has(episodeNo)) return;
                seen.add(episodeNo);
                result.push(episodeNo);
            });
            result.sort((a, b) => a - b);
            return result;
        }

        function getCachedSubscriptionEpisodePayload(taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return null;
            const cached = subscriptionEpisodeViewCache[normalizedName];
            if (!cached) return null;
            const fetchedAt = Number(cached.fetched_at || 0) || 0;
            if (fetchedAt <= 0) return null;
            if ((Date.now() - fetchedAt) >= SUBSCRIPTION_EPISODE_CACHE_TTL_MS) return null;
            return cached.data || null;
        }

        function resolveSubscriptionTaskSavedEpisode(taskName, task) {
            const cachedPayload = getCachedSubscriptionEpisodePayload(taskName);
            if (cachedPayload && typeof cachedPayload === 'object') {
                return {
                    episode: Math.max(0, parseInt(cachedPayload?.max_episode || '0', 10) || 0),
                    confirmed: true,
                };
            }
            const stats = task?.stats && typeof task.stats === 'object' ? task.stats : {};
            const statsMaxEpisode = Math.max(0, parseInt(stats?.existing_episode_max || '0', 10) || 0);
            return {
                episode: statsMaxEpisode,
                confirmed: statsMaxEpisode > 0,
            };
        }

        function buildSubscriptionTaskEpisodeText(task, taskName, { introExpanded = false } = {}) {
            const totalEpisodes = Math.max(0, parseInt(task?.total_episodes || '0', 10) || 0);
            const stateEpisode = Math.max(0, parseInt(task?.last_episode || '0', 10) || 0);
            const savedEpisode = resolveSubscriptionTaskSavedEpisode(taskName, task);
            const progressEpisode = savedEpisode.confirmed ? savedEpisode.episode : stateEpisode;
            let suffix = '';
            if (savedEpisode.confirmed) suffix = '（按保存文件确认）';
            else if (introExpanded && subscriptionIntroEpisodeLookupLoading[taskName]) suffix = '（正在按保存文件核对）';
            return `追更进度：E${progressEpisode}${totalEpisodes > 0 ? ` / E${totalEpisodes}` : ''}${suffix}`;
        }

        async function ensureSubscriptionIntroEpisode(taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return;
            const task = getSubscriptionTaskByName(normalizedName);
            if (!task || normalizeSubscriptionMediaType(task.media_type || 'movie') !== 'tv') return;
            if (getCachedSubscriptionEpisodePayload(normalizedName)) return;
            if (subscriptionIntroEpisodeLookupLoading[normalizedName]) return;
            const failedAt = Number(subscriptionIntroEpisodeLookupFailedAt[normalizedName] || 0) || 0;
            if (failedAt > 0 && (Date.now() - failedAt) < SUBSCRIPTION_INTRO_EPISODE_RETRY_MS) return;

            subscriptionIntroEpisodeLookupLoading[normalizedName] = true;
            try {
                const data = await window.MediaHubApi.getJson(`/subscription/episodes?name=${encodeURIComponent(normalizedName)}`);
                subscriptionEpisodeViewCache[normalizedName] = {
                    fetched_at: Date.now(),
                    data,
                };
                delete subscriptionIntroEpisodeLookupFailedAt[normalizedName];
            } catch (_) {
                subscriptionIntroEpisodeLookupFailedAt[normalizedName] = Date.now();
            } finally {
                delete subscriptionIntroEpisodeLookupLoading[normalizedName];
                if (isTaskIntroExpanded(subscriptionTaskIntroExpanded, normalizedName)) {
                    renderSubscriptionTasks();
                }
            }
        }

        function convertAbsoluteEpisodeToSeasonEpisode(seasonEpisodeMap, absoluteEpisode) {
            const target = Math.max(0, parseInt(absoluteEpisode || '0', 10) || 0);
            if (target <= 0) return { season: 0, episode: 0 };
            const normalizedMap = normalizeTmdbSeasonEpisodeMap(seasonEpisodeMap || {});
            const seasonList = Object.entries(normalizedMap)
                .map(([season, total]) => ({
                    season: Math.max(0, parseInt(season || '0', 10) || 0),
                    total: Math.max(0, parseInt(total || '0', 10) || 0),
                }))
                .filter((item) => item.season > 0 && item.total > 0)
                .sort((a, b) => a.season - b.season);
            if (!seasonList.length) return { season: 0, episode: target };

            let remaining = target;
            for (const item of seasonList) {
                if (remaining <= item.total) {
                    return { season: item.season, episode: remaining };
                }
                remaining -= item.total;
            }
            return { season: 0, episode: target };
        }

        function toggleSubscriptionEpisodeViewModeSwitch(task, payload) {
            const switchWrap = document.getElementById('subscription-episode-view-mode-switch');
            const absoluteBtn = document.getElementById('subscription-episode-mode-absolute');
            const seasonBtn = document.getElementById('subscription-episode-mode-season');
            if (!switchWrap || !absoluteBtn || !seasonBtn) return;

            const multiSeason = !!(task?.multi_season_mode ?? task?.anime_mode ?? payload?.multi_season_mode);
            if (multiSeason) {
                switchWrap.classList.remove('hidden');
                switchWrap.classList.add('inline-flex');
            } else {
                switchWrap.classList.add('hidden');
                switchWrap.classList.remove('inline-flex');
                subscriptionEpisodeViewMode = 'absolute';
            }

            const activeAbsolute = subscriptionEpisodeViewMode !== 'season';
            absoluteBtn.classList.toggle('is-active', activeAbsolute);
            seasonBtn.classList.toggle('is-active', !activeAbsolute);
            absoluteBtn.setAttribute('aria-pressed', activeAbsolute ? 'true' : 'false');
            seasonBtn.setAttribute('aria-pressed', !activeAbsolute ? 'true' : 'false');
        }

        function setSubscriptionEpisodeViewMode(mode) {
            const normalized = String(mode || '').trim().toLowerCase();
            subscriptionEpisodeViewMode = normalized === 'season' ? 'season' : 'absolute';
            renderSubscriptionEpisodeModal();
        }

        function renderSubscriptionEpisodeModal() {
            const titleEl = document.getElementById('subscription-episode-modal-title');
            const summaryEl = document.getElementById('subscription-episode-modal-summary');
            const noteEl = document.getElementById('subscription-episode-modal-note');
            const gridEl = document.getElementById('subscription-episode-grid');
            if (!titleEl || !summaryEl || !noteEl || !gridEl) return;

            const taskName = String(subscriptionEpisodeViewTaskName || '').trim();
            if (!taskName) {
                titleEl.innerText = '集数视图';
                summaryEl.className = 'text-xs text-slate-400 mt-2';
                summaryEl.innerText = '点击任务卡片里的“集数视图”查看。';
                noteEl.innerText = '-';
                gridEl.innerHTML = '<div class="subscription-episode-empty">暂无任务数据</div>';
                return;
            }

            const task = getSubscriptionTaskByName(taskName);
            titleEl.innerText = `${taskName} · 集数视图`;
            if (subscriptionEpisodeViewLoading) {
                summaryEl.className = 'text-xs text-slate-400 mt-2';
                summaryEl.innerText = '正在读取目录集数，请稍候...';
                noteEl.innerText = `保存路径：${task?.savepath || '--'}`;
                gridEl.innerHTML = '<div class="subscription-episode-empty">正在扫描目录中的剧集文件...</div>';
                return;
            }

            if (subscriptionEpisodeViewError) {
                summaryEl.className = 'text-xs text-red-300 mt-2';
                summaryEl.innerText = `读取失败：${subscriptionEpisodeViewError}`;
                noteEl.innerText = `保存路径：${task?.savepath || '--'}`;
                gridEl.innerHTML = '<div class="subscription-episode-empty">暂时无法加载集数视图，请点击“刷新”重试。</div>';
                return;
            }

            const payload = subscriptionEpisodeViewData || {};
            toggleSubscriptionEpisodeViewModeSwitch(task, payload);
            const existingEpisodes = normalizeEpisodeList(payload.existing_episodes);
            const existingSet = new Set(existingEpisodes);
            let displayTotal = parseInt(payload.display_total_episodes || '0', 10) || 0;
            if (displayTotal <= 0) {
                displayTotal = Math.max(
                    parseInt(payload.total_episodes || '0', 10) || 0,
                    parseInt(payload.last_episode || '0', 10) || 0,
                    parseInt(payload.max_episode || '0', 10) || 0,
                );
            }
            if (displayTotal <= 0) displayTotal = 60;
            displayTotal = Math.max(1, Math.min(1200, displayTotal));

            const presentInRange = existingEpisodes.filter((episodeNo) => episodeNo <= displayTotal).length;
            const missingCount = Math.max(0, displayTotal - presentInRange);
            const totalEpisodes = parseInt(payload.total_episodes || '0', 10) || 0;
            const scanStats = payload.scan_stats && typeof payload.scan_stats === 'object' ? payload.scan_stats : {};
            const scanDirs = parseInt(scanStats.scanned_dirs || '0', 10) || 0;
            const scanEntries = parseInt(scanStats.scanned_entries || '0', 10) || 0;
            const scanFailed = parseInt(scanStats.failed_dirs || '0', 10) || 0;
            const scanTruncated = !!scanStats.truncated;
            const seasonEpisodeMap = normalizeTmdbSeasonEpisodeMap(task?.tmdb_season_episode_map || {});
            const useSeasonView = subscriptionEpisodeViewMode === 'season' && !!(task?.multi_season_mode ?? task?.anime_mode);

            summaryEl.className = 'text-xs text-slate-300 mt-2';

            if (!useSeasonView) {
                summaryEl.innerText = `已存在 ${presentInRange} 集 / 展示 ${displayTotal} 集（缺失 ${missingCount} 集）`;
                noteEl.innerText = [
                    `视图：绝对集数`,
                    `保存路径：${payload.savepath || task?.savepath || '--'}`,
                    totalEpisodes > 0 ? `总集数：E${totalEpisodes}` : '总集数：未配置（按已识别范围展示）',
                    `扫描目录 ${scanDirs} 个 / 条目 ${scanEntries} 条${scanFailed > 0 ? ` / 失败 ${scanFailed}` : ''}${scanTruncated ? ' / 已截断' : ''}`,
                ].join('；');

                const cells = [];
                for (let episodeNo = 1; episodeNo <= displayTotal; episodeNo += 1) {
                    const present = existingSet.has(episodeNo);
                    cells.push(
                        `<div class="subscription-episode-cell ${present ? 'is-present' : 'is-missing'}" title="E${episodeNo}${present ? ' 已存在资源' : ' 缺失资源'}"><span class="subscription-episode-cell-no">${episodeNo}</span></div>`
                    );
                }
                gridEl.innerHTML = cells.length ? cells.join('') : '<div class="subscription-episode-empty">没有可展示的集数</div>';
                return;
            }

            const seasonBuckets = [];
            const sortedSeasons = Object.keys(seasonEpisodeMap)
                .map((seasonNo) => Math.max(0, parseInt(seasonNo || '0', 10) || 0))
                .filter((seasonNo) => seasonNo > 0)
                .sort((a, b) => a - b);

            if (sortedSeasons.length) {
                let absoluteStart = 1;
                sortedSeasons.forEach((seasonNo) => {
                    const seasonTotal = Math.max(0, parseInt(seasonEpisodeMap[String(seasonNo)] || '0', 10) || 0);
                    if (seasonTotal <= 0) return;
                    const absoluteEnd = absoluteStart + seasonTotal - 1;
                    seasonBuckets.push({ seasonNo, seasonTotal, absoluteStart, absoluteEnd, episodes: [] });
                    absoluteStart = absoluteEnd + 1;
                });
            }

            if (!seasonBuckets.length) {
                summaryEl.className = 'text-xs text-amber-300 mt-2';
                summaryEl.innerText = '当前任务缺少 TMDB 分季集数映射，暂时无法切换分季视图。';
                noteEl.innerText = [
                    `视图：分季视图`,
                    `保存路径：${payload.savepath || task?.savepath || '--'}`,
                    '提示：请先绑定 TMDB 并确保“季集映射”有效',
                ].join('；');
                gridEl.innerHTML = '<div class="subscription-episode-empty">暂无可用分季映射，请改用“绝对集数”查看。</div>';
                return;
            }

            existingEpisodes.forEach((absoluteEpisode) => {
                const mapped = convertAbsoluteEpisodeToSeasonEpisode(seasonEpisodeMap, absoluteEpisode);
                if (!mapped.season || !mapped.episode) return;
                const bucket = seasonBuckets.find((item) => item.seasonNo === mapped.season);
                if (!bucket) return;
                bucket.episodes.push(mapped.episode);
            });

            const seasonBlocks = seasonBuckets.map((bucket) => {
                const seasonSet = new Set(bucket.episodes);
                const presentCount = seasonSet.size;
                const missingSeasonCount = Math.max(0, bucket.seasonTotal - presentCount);
                const seasonCells = [];
                for (let ep = 1; ep <= bucket.seasonTotal; ep += 1) {
                    const present = seasonSet.has(ep);
                    seasonCells.push(`<div class="subscription-episode-cell ${present ? 'is-present' : 'is-missing'}" title="S${String(bucket.seasonNo).padStart(2, '0')}E${String(ep).padStart(2, '0')}${present ? ' 已存在资源' : ' 缺失资源'}"><span class="subscription-episode-cell-no">${ep}</span></div>`);
                }
                return `
                    <div class="subscription-episode-season-block">
                        <div class="subscription-episode-season-title">Season ${String(bucket.seasonNo).padStart(2, '0')} · 已存在 ${presentCount}/${bucket.seasonTotal}（缺失 ${missingSeasonCount}）</div>
                        <div class="subscription-episode-grid">${seasonCells.join('')}</div>
                    </div>
                `;
            });

            summaryEl.innerText = `多季合一 · 分季视图（总已存在 ${presentInRange} 集，绝对集数范围展示 ${displayTotal}）`;
            noteEl.innerText = [
                `视图：分季视图`,
                `保存路径：${payload.savepath || task?.savepath || '--'}`,
                `映射季数：${seasonBuckets.length} 季`,
                `扫描目录 ${scanDirs} 个 / 条目 ${scanEntries} 条${scanFailed > 0 ? ` / 失败 ${scanFailed}` : ''}${scanTruncated ? ' / 已截断' : ''}`,
            ].join('；');
            gridEl.innerHTML = seasonBlocks.join('');
        }

        async function refreshSubscriptionEpisodeView(force = false) {
            const taskName = String(subscriptionEpisodeViewTaskName || '').trim();
            if (!taskName) return;

            const cached = subscriptionEpisodeViewCache[taskName];
            const nowTs = Date.now();
            if (!force && cached && (nowTs - Number(cached.fetched_at || 0)) < SUBSCRIPTION_EPISODE_CACHE_TTL_MS) {
                subscriptionEpisodeViewData = cached.data || null;
                subscriptionEpisodeViewError = '';
                subscriptionEpisodeViewLoading = false;
                renderSubscriptionEpisodeModal();
                return;
            }

            subscriptionEpisodeViewLoading = true;
            subscriptionEpisodeViewError = '';
            renderSubscriptionEpisodeModal();

            const requestedTaskName = taskName;
            try {
                const data = await window.MediaHubApi.getJson(`/subscription/episodes?name=${encodeURIComponent(requestedTaskName)}`);
                if (subscriptionEpisodeViewTaskName !== requestedTaskName) return;
                subscriptionEpisodeViewData = data;
                subscriptionEpisodeViewCache[requestedTaskName] = {
                    fetched_at: Date.now(),
                    data,
                };
            } catch (error) {
                if (subscriptionEpisodeViewTaskName !== requestedTaskName) return;
                subscriptionEpisodeViewData = null;
                subscriptionEpisodeViewError = error?.message || '读取集数视图失败';
            } finally {
                if (subscriptionEpisodeViewTaskName === requestedTaskName) {
                    subscriptionEpisodeViewLoading = false;
                    renderSubscriptionEpisodeModal();
                }
            }
        }

        async function openSubscriptionEpisodeModal(taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return;
            const task = getSubscriptionTaskByName(normalizedName);
            if (!task) {
                showToast('任务不存在或已被删除', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            if (normalizeSubscriptionMediaType(task.media_type || 'movie') !== 'tv') {
                showToast('仅电视剧任务支持集数视图', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }

            subscriptionEpisodeViewTaskName = normalizedName;
            subscriptionEpisodeViewData = null;
            subscriptionEpisodeViewError = '';
            subscriptionEpisodeViewLoading = true;
            showLockedModal('subscription-episode-modal');
            renderSubscriptionEpisodeModal();
            await refreshSubscriptionEpisodeView(false);
        }

        function closeSubscriptionEpisodeModal() {
            hideLockedModal('subscription-episode-modal');
        }

        async function refreshSubscriptionState({ compact = false } = {}) {
            const subscriptionModule = await loadSubscriptionTabModule();
            if (subscriptionModule?.refreshSubscriptionState) {
                await subscriptionModule.refreshSubscriptionState({
                    applySubscriptionState,
                    compact,
                });
                return;
            }
            try {
                const endpoint = compact ? '/subscription/status?compact=1' : '/subscription/status';
                applySubscriptionState(await window.MediaHubApi.getJson(endpoint));
            } catch (e) {}
        }

        async function clearSubscriptionLogs() {
            const subscriptionModule = await loadSubscriptionTabModule();
            if (subscriptionModule?.clearSubscriptionLogs) {
                await subscriptionModule.clearSubscriptionLogs({
                    setLastSubscriptionLogSignature: (nextValue) => {
                        lastSubscriptionLogSignature = String(nextValue || '');
                    },
                });
                resetSubscriptionLogWindow();
                await fetchSubscriptionLogs({ limit: SUBSCRIPTION_LOG_RECENT_TASK_LIMIT });
                return;
            }
            try {
                await window.MediaHubApi.postJson('/subscription/logs/clear');
                resetSubscriptionLogWindow();
                await fetchSubscriptionLogs({ limit: SUBSCRIPTION_LOG_RECENT_TASK_LIMIT });
            } catch (e) {}
        }
