        let isRunning = false;
        let monitorState = { running: false, current_task: '', tasks: [], logs: [], summary: { step: '空闲', detail: '等待监控任务' }, queued: [], next_runs: {} };
        let subscriptionState = { running: false, current_task: '', tasks: [], logs: [], summary: { step: '空闲', detail: '等待订阅任务' }, queued: [], next_runs: {} };
        let resourceState = { sources: [], items: [], jobs: [], channel_sections: [], channel_profiles: {}, search_sections: [], last_syncs: {}, monitor_tasks: [], stats: { source_count: 0, item_count: 0, filtered_item_count: 0, completed_job_count: 0 }, cookie_configured: false, search: '', search_meta: {} };
        let editingMonitorName = null;
        let editingSubscriptionName = null;
        let editingResourceSourceIndex = null;
        let selectedResourceId = null;
        let selectedResourceItem = null;
        let resourceModalMode = 'detail';
        let resourceFolderTrail = [{ id: '0', name: '根目录' }];
        let resourceFolderEntries = [];
        let resourceFolderSummary = { folder_count: 0, file_count: 0 };
        let resourceFolderLoading = false;
        let resourceFolderCreateBusy = false;
        let subscriptionFolderTrail = [{ id: '0', name: '根目录' }];
        let subscriptionFolderEntries = [];
        let subscriptionFolderSummary = { folder_count: 0, file_count: 0 };
        let subscriptionFolderLoading = false;
        let subscriptionFolderCreateBusy = false;
        let subscriptionTmdbSearchBusy = false;
        let subscriptionTmdbSearchToken = 0;
        let subscriptionTmdbResults = [];
        let subscriptionEpisodeViewTaskName = '';
        let subscriptionEpisodeViewLoading = false;
        let subscriptionEpisodeViewError = '';
        let subscriptionEpisodeViewData = null;
        let subscriptionEpisodeViewCache = {};
        let resourceFolderValidationPromise = null;
        let resourceTargetPreviewEntries = [];
        let resourceTargetPreviewSummary = { folder_count: 0, file_count: 0 };
        let resourceTargetPreviewLoading = false;
        let resourceTargetPreviewError = '';
        let resourceModalLinkType = '';
        let resourceShareEntriesByParent = { '0': [] };
        let resourceShareEntryIndex = {};
        let resourceShareExpanded = {};
        let resourceShareLoadingParents = {};
        let resourceShareSelected = {};
        let resourceShareLoading = false;
        let resourceShareError = '';
        let resourceShareRootLoaded = false;
        let resourceShareInfo = { title: '', count: 0, share_code: '', receive_code: '' };
        let resourceShareReceiveCode = '';
        let resourceShareTrail = [{ cid: '0', name: '分享根目录' }];
        let resourceShareCurrentCid = '0';
        let resourceShareRequestToken = 0;
        let resourceSectionCollapsed = {};
        let resourceSearchBusy = false;
        let resourceSyncBusy = false;
        let resourceChannelExtraItems = {};
        let resourceChannelLoadingMore = {};
        let resourceChannelNextBefore = {};
        let resourceChannelNoMore = {};
        let resourceTempIdSeed = -1;
        let resourceClientIdSeed = -100000;
        let resourceClientIdsByIdentity = {};
        let resourceJobModalOpen = false;
        let resourceJobClearMenuOpen = false;
        let resourceSourceModalOpen = false;
        let resourceSourceImportModalOpen = false;
        let resourceSourceManagerOpen = false;
        let resourceSourceFilter = 'all';
        let resourceSourceEnabledFilter = 'all';
        let resourceSourceActivityFilter = 'all';
        let resourceSourceBulkSelected = {};
        let resourceSourceTestBusy = false;
        let resourceSourceTestResult = { total: 0, done: 0, success: 0, failed: 0, running: false, last_name: '', error: '' };
        let resourceJobFilter = 'all';
        let monitorUserscriptJobs = [];
        let monitorUserscriptJobCounts = { total: 0, active: 0, submitted: 0, completed: 0, failed: 0 };
        let monitorUserscriptJobsLoading = false;
        let tgProxyTestState = { loading: false, ok: null, message: '', latency_ms: 0, mode: '', proxy_url: '', target_url: '' };
        let resourceBoardHintText = '';
        let resourceTgHealthState = { visible: false, tone: 'loading', title: '', meta: '', note: '' };
        let resourceTgLastLatencyMs = 0;
        let lastLogSignature = '';
        let lastMonitorLogSignature = '';
        let lastSubscriptionLogSignature = '';
        let lastMonitorRenderKey = '';
        let lastSubscriptionRenderKey = '';
        let statusEventSource = null;
        let statusFallbackTimer = null;
        const monitorActionLocks = new Set();
        let versionInfo = { local: null, latest: null, has_update: false, checked_at: 0, error: '', source: '' };
        let versionBannerDismissed = false;
        let modalScrollLockCount = 0;
        let modalScrollLockY = 0;
        const btnTexts = ["🌐 联网同步更新", "🛠 本地调试解析", "🔥 强制全量重刷"];
        const DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,wmv,flv,webm,vob,mpg,mpeg,ts,m2ts,mts,rmvb,rm,asf,3gp,m4v,f4v,iso";
        const STATUS_FALLBACK_INTERVAL = 15000;
        const RESOURCE_REFRESH_INTERVAL = 15000;
        const VERSION_REFRESH_INTERVAL = 1000 * 60 * 15;
        const VERSION_FALLBACK_PROJECT_URL = 'https://github.com/xianer235/115-strm-web';
        const VERSION_FALLBACK_CHANGELOG_URL = 'https://github.com/xianer235/115-strm-web/blob/main/CHANGELOG.md';
        const RESOURCE_FOLDER_MEMORY_KEY = 'resource-folder-selection-v1';
        const RESOURCE_IMPORT_DELAY_MEMORY_KEY = 'resource-import-delay-seconds-v1';
        const MAIN_TAB_ROW_HINT_MEMORY_KEY = 'main-tab-row-hint-v1';
        const TOAST_DEFAULT_DURATION_MS = 3000;
        const SUBSCRIPTION_EPISODE_CACHE_TTL_MS = 1000 * 60 * 3;
        const MONITOR_USERSCRIPT_JOB_LIMIT = 60;

        function lockPageScroll() {
            if (modalScrollLockCount === 0) {
                modalScrollLockY = Math.max(0, window.scrollY || window.pageYOffset || 0);
                document.body.classList.add('body-scroll-lock');
                document.body.style.top = `-${modalScrollLockY}px`;
            }
            modalScrollLockCount += 1;
            syncResourceBackTopButton();
        }

        function unlockPageScroll() {
            if (modalScrollLockCount <= 0) return;
            modalScrollLockCount -= 1;
            if (modalScrollLockCount > 0) return;

            const restoreY = modalScrollLockY;
            modalScrollLockY = 0;
            document.body.classList.remove('body-scroll-lock');
            document.body.style.top = '';
            window.scrollTo(0, restoreY);
            syncResourceBackTopButton();
        }

        function scrollResourceToTop() {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        function syncResourceBackTopButton() {
            const btn = document.getElementById('resource-back-top-btn');
            const resourcePage = document.getElementById('page-resource');
            if (!btn || !resourcePage) return;
            const isResourceVisible = !resourcePage.classList.contains('hidden');
            const isModalLocked = document.body.classList.contains('body-scroll-lock');
            const scrollTop = Math.max(0, window.scrollY || window.pageYOffset || 0);
            const shouldShow = isResourceVisible && !isModalLocked && scrollTop > 360;
            btn.classList.toggle('hidden', !shouldShow);
        }

        function syncSettingsSaveDock() {
            const dock = document.getElementById('settings-save-dock');
            const settingsPage = document.getElementById('page-settings');
            if (!dock || !settingsPage) return;

            const isSettingsVisible = !settingsPage.classList.contains('hidden');
            if (!isSettingsVisible) {
                dock.classList.remove('is-inline');
                settingsPage.classList.remove('has-inline-save-dock');
                return;
            }

            const viewportHeight = Math.max(0, window.innerHeight || document.documentElement.clientHeight || 0);
            const scrollTop = Math.max(0, window.scrollY || window.pageYOffset || 0);
            const docHeight = Math.max(document.body.scrollHeight || 0, document.documentElement.scrollHeight || 0);
            const footer = document.querySelector('footer.footer-text');
            const nearDocumentEnd = scrollTop + viewportHeight >= docHeight - 4;
            let shouldInline = false;

            if (footer) {
                const footerRect = footer.getBoundingClientRect();
                const footerVisible = footerRect.top < viewportHeight && footerRect.bottom > 0;
                shouldInline = footerVisible || nearDocumentEnd;
            } else {
                shouldInline = nearDocumentEnd;
            }

            dock.classList.toggle('is-inline', shouldInline);
            settingsPage.classList.toggle('has-inline-save-dock', shouldInline);
        }

        function syncMainTabRowState() {
            const shell = document.getElementById('tab-row-shell');
            const row = document.getElementById('tab-row');
            if (!shell || !row) return;
            const maxScrollLeft = Math.max(0, row.scrollWidth - row.clientWidth);
            const canScrollLeft = row.scrollLeft > 2;
            const canScrollRight = row.scrollLeft < maxScrollLeft - 2;
            shell.classList.toggle('can-scroll-left', canScrollLeft);
            shell.classList.toggle('can-scroll-right', canScrollRight);
        }

        function focusMainTab(tab, behavior = 'smooth') {
            const row = document.getElementById('tab-row');
            const button = document.getElementById(`tab-${tab}`);
            if (!row || !button) return;
            button.scrollIntoView({ inline: 'center', block: 'nearest', behavior });
        }

        function scrollMainTabs(direction = 1) {
            const row = document.getElementById('tab-row');
            if (!row) return;
            const dir = Number(direction) < 0 ? -1 : 1;
            const step = Math.max(140, Math.round(row.clientWidth * 0.72));
            row.scrollBy({ left: dir * step, behavior: 'smooth' });
        }

        function nudgeMainTabRowOnFirstVisit() {
            const row = document.getElementById('tab-row');
            if (!row) return;
            const isSmallScreen = window.matchMedia('(max-width: 768px)').matches;
            if (!isSmallScreen) return;
            const canScroll = row.scrollWidth > row.clientWidth + 8;
            if (!canScroll) return;
            if (row.scrollLeft > 1) return;
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
            try {
                if (sessionStorage.getItem(MAIN_TAB_ROW_HINT_MEMORY_KEY) === '1') return;
                sessionStorage.setItem(MAIN_TAB_ROW_HINT_MEMORY_KEY, '1');
            } catch (e) {}
            window.setTimeout(() => {
                row.scrollBy({ left: 28, behavior: 'smooth' });
                window.setTimeout(() => {
                    row.scrollBy({ left: -28, behavior: 'smooth' });
                }, 260);
            }, 260);
        }

        function initMainTabRow() {
            const row = document.getElementById('tab-row');
            if (!row) return;
            row.addEventListener('scroll', syncMainTabRowState, { passive: true });
            window.addEventListener('resize', syncMainTabRowState);
            syncMainTabRowState();
            focusMainTab('resource', 'auto');
            syncMainTabRowState();
            nudgeMainTabRowOnFirstVisit();
        }

        function showLockedModal(modalId) {
            const modal = document.getElementById(modalId);
            if (!modal) return;
            const isHidden = modal.classList.contains('hidden');
            modal.classList.remove('hidden');
            if (isHidden) lockPageScroll();
        }

        function hideLockedModal(modalId) {
            const modal = document.getElementById(modalId);
            if (!modal) return;
            const wasVisible = !modal.classList.contains('hidden');
            modal.classList.add('hidden');
            if (wasVisible) unlockPageScroll();
        }

        function switchTab(tab) {
            ['task', 'resource', 'subscription', 'settings', 'monitor', 'about'].forEach(name => {
                document.getElementById(`page-${name}`).classList.toggle('hidden', tab !== name);
                document.getElementById(`tab-${name}`).className = tab === name ? 'tab-active uppercase' : 'tab-inactive uppercase';
            });
            if (tab !== 'resource') toggleResourceJobModal(false);
            if (tab === 'resource') refreshResourceState();
            if (tab === 'monitor') refreshMonitorUserscriptJobs();
            syncResourceBackTopButton();
            syncSettingsSaveDock();
            focusMainTab(tab);
            syncMainTabRowState();
        }

        function normalizeToastPlacement(placement) {
            const normalized = String(placement || '').trim().toLowerCase();
            if (normalized === 'top-center') return 'top-center';
            return 'bottom-right';
        }

        function randomAlphaNumericSecret(length = 32) {
            const size = Math.max(16, Math.min(Number(length || 32), 96));
            const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
            const chars = alphabet.split('');
            const out = [];
            if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
                const random = new Uint32Array(size);
                window.crypto.getRandomValues(random);
                for (let i = 0; i < size; i += 1) {
                    out.push(chars[random[i] % chars.length]);
                }
            } else {
                for (let i = 0; i < size; i += 1) {
                    out.push(chars[Math.floor(Math.random() * chars.length)]);
                }
            }
            return out.join('');
        }

        function generateWebhookSecret() {
            const input = document.getElementById('webhook_secret');
            if (!input) return;
            const secret = randomAlphaNumericSecret(32);
            input.value = secret;
            input.focus();
            input.select();
            showToast('已生成随机密钥，请记得点击“保存全部配置”', { tone: 'success', duration: 3000, placement: 'top-center' });
        }

        function getGlobalToastStack(placement = 'bottom-right') {
            const normalizedPlacement = normalizeToastPlacement(placement);
            const stackId = `global-toast-stack-${normalizedPlacement}`;
            let stack = document.getElementById(stackId);
            if (stack) return stack;
            stack = document.createElement('div');
            stack.id = stackId;
            stack.className = `global-toast-stack global-toast-stack-${normalizedPlacement}`;
            stack.setAttribute('aria-live', 'polite');
            stack.setAttribute('aria-atomic', 'false');
            document.body.appendChild(stack);
            return stack;
        }

        function showToast(message, { tone = 'info', duration = TOAST_DEFAULT_DURATION_MS, placement = 'bottom-right' } = {}) {
            const text = String(message || '').trim();
            if (!text) return;

            const normalizedTone = ['success', 'error', 'warn', 'info'].includes(String(tone || '').toLowerCase())
                ? String(tone || '').toLowerCase()
                : 'info';
            const stack = getGlobalToastStack(placement);
            const toast = document.createElement('div');
            toast.className = `global-toast global-toast-${normalizedTone}`;
            toast.setAttribute('role', normalizedTone === 'error' ? 'alert' : 'status');
            toast.textContent = text;
            stack.appendChild(toast);

            requestAnimationFrame(() => {
                toast.classList.add('is-visible');
            });

            const removeToast = () => {
                if (!toast.parentNode) return;
                toast.classList.remove('is-visible');
                window.setTimeout(() => {
                    if (toast.parentNode) toast.remove();
                }, 180);
            };

            const ttl = Math.max(1200, Number(duration || TOAST_DEFAULT_DURATION_MS));
            const timer = window.setTimeout(removeToast, ttl);
            toast.addEventListener('click', () => {
                window.clearTimeout(timer);
                removeToast();
            });
        }

        function escapeHtml(str) {
            return String(str || '')
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#39;');
        }

        function uniquePreserveOrder(values) {
            const seen = new Set();
            const result = [];
            (Array.isArray(values) ? values : []).forEach(value => {
                const token = String(value || '').trim();
                if (!token || seen.has(token)) return;
                seen.add(token);
                result.push(token);
            });
            return result;
        }

        function buildLogSignature(logs, formatter) {
            const list = Array.isArray(logs) ? logs : [];
            const tail = list.length ? formatter(list[list.length - 1]) : '';
            return `${list.length}:${tail}`;
        }

        function decorateSummaryMetric(segment) {
            const raw = String(segment || '').trim();
            const match = raw.match(/^(.*?)(\d+)$/);
            if (!match) return escapeHtml(raw);

            const label = match[1].trim();
            const value = Number(match[2]);
            const classMap = {
                '新增/更新': 'summary-positive',
                '跳过文件': 'summary-skip',
                '跳过目录': 'summary-skip',
                '失败目录': 'summary-fail',
                '删除文件': 'summary-delete',
                '删除目录': 'summary-delete'
            };
            const colorClass = classMap[label];
            if (!colorClass) return escapeHtml(raw);

            const zeroClass = value === 0 ? ' summary-zero' : '';
            return `<span class="summary-metric ${colorClass}${zeroClass}">${escapeHtml(raw)}</span>`;
        }

        function decorateMonitorSummaryText(text) {
            const raw = String(text || '');
            const match = raw.match(/^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+)?(生成汇总:|清理汇总:)\s*(.*)$/);
            if (!match) return escapeHtml(raw);

            const timestamp = escapeHtml(match[1] || '');
            const prefix = escapeHtml(match[2]);
            const metrics = String(match[3] || '')
                .split(' | ')
                .map(decorateSummaryMetric)
                .join('<span class="text-slate-500"> | </span>');

            return `${timestamp}${prefix} ${metrics}`;
        }

        function formatMonitorLogHtml(item) {
            const level = item?.level || 'info';
            const text = String(item?.text || '');
            if (level === 'info' && (text.includes('生成汇总:') || text.includes('清理汇总:'))) {
                return decorateMonitorSummaryText(text);
            }
            return escapeHtml(text);
        }

        function monitorActionToken(action, name) {
            return `${action}::${String(name || '').trim()}`;
        }

        function isMonitorActionLocked(action, name) {
            return monitorActionLocks.has(monitorActionToken(action, name));
        }

        function setMonitorActionLock(action, name, locked) {
            const token = monitorActionToken(action, name);
            if (locked) monitorActionLocks.add(token);
            else monitorActionLocks.delete(token);
            renderMonitorTasks();
            lastMonitorRenderKey = buildMonitorRenderKey(monitorState);
        }

        function buildMonitorRenderKey(state) {
            return JSON.stringify({
                running: !!state?.running,
                current_task: state?.current_task || '',
                queued: Array.isArray(state?.queued) ? state.queued : [],
                next_runs: state?.next_runs || {},
                tasks: Array.isArray(state?.tasks) ? state.tasks : [],
                locks: Array.from(monitorActionLocks).sort()
            });
        }

        function applyMainState(data) {
            if (!data) return;
            if (data.running !== isRunning) updateButtonState(!!data.running);

            const logBox = document.getElementById('log-box');
            const logs = Array.isArray(data.logs) ? data.logs : [];
            const logSignature = buildLogSignature(logs, (line) => String(line || ''));
            if (logSignature !== lastLogSignature) {
                logBox.innerHTML = logs.map(line => escapeHtml(line)).join('<br>');
                logBox.scrollTop = logBox.scrollHeight;
                lastLogSignature = logSignature;
            }

            const p = data.progress || {};
            document.getElementById('prog-step').innerText = p.step || '空闲';
            document.getElementById('prog-percent').innerText = `${Number(p.percent || 0)}%`;
            document.getElementById('prog-bar').style.width = `${Number(p.percent || 0)}%`;
            document.getElementById('prog-detail').innerText = p.detail || '等待指令';

            if (data.next_run) {
                document.getElementById('next-run-container').classList.remove('hidden');
                document.getElementById('next-run-time').innerText = data.next_run;
            } else {
                document.getElementById('next-run-container').classList.add('hidden');
            }
        }

        function applyMonitorState(data, { forceRender = false } = {}) {
            if (!data) return;
            monitorState = {
                ...monitorState,
                ...data,
                tasks: Array.isArray(data.tasks) ? data.tasks : (monitorState.tasks || []),
                logs: Array.isArray(data.logs) ? data.logs : (monitorState.logs || []),
                queued: Array.isArray(data.queued) ? data.queued : (monitorState.queued || []),
                next_runs: data.next_runs || monitorState.next_runs || {},
                summary: data.summary || monitorState.summary || { step: '空闲', detail: '等待监控任务' }
            };

            document.getElementById('monitor-summary-step').innerText = monitorState.summary?.step || '空闲';
            document.getElementById('monitor-summary-detail').innerText = monitorState.summary?.detail || '等待监控任务';

            const renderKey = buildMonitorRenderKey(monitorState);
            if (forceRender || renderKey !== lastMonitorRenderKey) {
                renderMonitorTasks();
                lastMonitorRenderKey = renderKey;
            }
            renderMonitorLogs();
            resourceState.monitor_tasks = monitorState.tasks || resourceState.monitor_tasks || [];
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
        }

        function startStatusFallbackPolling() {
            if (statusFallbackTimer) return;
            statusFallbackTimer = window.setInterval(() => {
                refreshMainLogs();
                refreshMonitorState();
                refreshSubscriptionState();
            }, STATUS_FALLBACK_INTERVAL);
        }

        function stopStatusFallbackPolling() {
            if (!statusFallbackTimer) return;
            window.clearInterval(statusFallbackTimer);
            statusFallbackTimer = null;
        }

        function connectStatusStream() {
            if (!window.EventSource) {
                startStatusFallbackPolling();
                return;
            }
            if (statusEventSource) statusEventSource.close();
            statusEventSource = new EventSource('/events');
            statusEventSource.addEventListener('state', (event) => {
                try {
                    const payload = JSON.parse(event.data || '{}');
                    stopStatusFallbackPolling();
                    applyMainState(payload.main);
                    applyMonitorState(payload.monitor);
                    applySubscriptionState(payload.subscription);
                } catch (err) {
                    console.warn('Status stream parse failed', err);
                }
            });
            statusEventSource.onopen = () => {
                stopStatusFallbackPolling();
            };
            statusEventSource.onerror = () => {
                startStatusFallbackPolling();
            };
        }

        function normalizeVersionLabel(rawVersion) {
            const raw = String(rawVersion || 'dev').trim();
            if (!raw) return 'Vdev';
            return raw.startsWith('V') ? raw : `V${raw}`;
        }

        function formatTimeText(value) {
            if (!value) return '--';
            const d = new Date(value);
            if (Number.isNaN(d.getTime())) return String(value);
            return d.toLocaleString();
        }

        function getProjectUrl() {
            return versionInfo?.latest?.projectUrl || versionInfo?.local?.projectUrl || VERSION_FALLBACK_PROJECT_URL;
        }

        function getChangelogUrl() {
            return versionInfo?.latest?.changelogUrl || versionInfo?.local?.changelogUrl || getProjectUrl() || VERSION_FALLBACK_CHANGELOG_URL;
        }

        function getVersionNotes() {
            const latestNotes = Array.isArray(versionInfo?.latest?.notes) ? versionInfo.latest.notes.filter(Boolean) : [];
            if (latestNotes.length) return latestNotes;
            const localNotes = Array.isArray(versionInfo?.local?.notes) ? versionInfo.local.notes.filter(Boolean) : [];
            return localNotes;
        }

        function renderVersionInfoPanel() {
            const localVersion = normalizeVersionLabel(versionInfo?.local?.version || 'dev');
            const latestRaw = versionInfo?.latest?.version || '';
            const latestVersion = latestRaw ? normalizeVersionLabel(latestRaw) : '--';
            const hasUpdate = !!versionInfo?.has_update;
            const hasChecked = Number(versionInfo?.checked_at || 0) > 0;
            const error = String(versionInfo?.error || '').trim();

            const footerVersion = document.getElementById('version-text');
            if (footerVersion) footerVersion.textContent = localVersion;

            const localEl = document.getElementById('about-local-version');
            if (localEl) localEl.textContent = localVersion;
            const buildEl = document.getElementById('about-build-date');
            if (buildEl) buildEl.textContent = formatTimeText(versionInfo?.local?.buildDate);
            const latestEl = document.getElementById('about-latest-version');
            if (latestEl) latestEl.textContent = latestVersion;
            const checkedEl = document.getElementById('about-checked-at');
            if (checkedEl) checkedEl.textContent = versionInfo?.checked_at ? `约 ${formatTimeText(versionInfo.checked_at * 1000)}` : '--';

            const statusEl = document.getElementById('about-version-status');
            if (statusEl) {
                if (error) {
                    statusEl.textContent = '检查失败';
                    statusEl.className = 'text-xs px-3 py-2 rounded-xl border border-red-500/20 bg-red-500/10 text-red-300';
                } else if (!hasChecked) {
                    statusEl.textContent = '尚未检查更新';
                    statusEl.className = 'text-xs px-3 py-2 rounded-xl border border-slate-700 bg-slate-900/80 text-slate-300';
                } else if (hasUpdate) {
                    statusEl.textContent = latestRaw ? `有可用更新：${normalizeVersionLabel(latestRaw)}` : '发现可用更新';
                    statusEl.className = 'text-xs px-3 py-2 rounded-xl border border-amber-500/25 bg-amber-500/15 text-amber-300';
                } else {
                    statusEl.textContent = '当前已是最新版本';
                    statusEl.className = 'text-xs px-3 py-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-300';
                }
            }

            const errorEl = document.getElementById('about-version-error');
            if (errorEl) {
                if (error) {
                    errorEl.textContent = `版本检查失败：${error}`;
                    errorEl.classList.remove('hidden');
                } else {
                    errorEl.classList.add('hidden');
                    errorEl.textContent = '';
                }
            }

            const hintEl = document.getElementById('about-version-hint');
            if (hintEl && !error) {
                if (!hasChecked) {
                    hintEl.textContent = '提示：进入页面后会自动检查远端版本，也可以手动点击“检查更新”。';
                } else {
                    hintEl.textContent = hasUpdate
                        ? `检测到新版本 ${latestVersion}，建议先查看更新说明后再升级。`
                        : '当前版本已和远端同步，后续会自动定时检查。';
                }
            }

            const notesWrap = document.getElementById('about-version-notes');
            if (notesWrap) {
                const notes = getVersionNotes();
                if (notes.length) {
                    notesWrap.innerHTML = `<ul class="list-disc pl-5 space-y-2">${notes.map(note => `<li>${escapeHtml(note)}</li>`).join('')}</ul>`;
                } else {
                    notesWrap.textContent = '暂无更新说明';
                }
            }

            const changelogUrl = getChangelogUrl();
            const projectUrl = getProjectUrl();
            const starUrl = `${projectUrl.replace(/\/+$/, '')}/stargazers`;
            const changelogLink = document.getElementById('about-changelog-link');
            if (changelogLink) changelogLink.href = changelogUrl;
            const projectLink = document.getElementById('about-project-link');
            if (projectLink) projectLink.href = projectUrl;
            const starLink = document.getElementById('about-star-link');
            if (starLink) starLink.href = starUrl;
        }

        function showHelp(text) {
            const normalized = String(text || '').replace(/\\n/g, '\n');
            document.getElementById('help-modal-body').textContent = normalized;
            document.getElementById('help-modal').classList.remove('hidden');
        }

        function closeHelpModal() {
            document.getElementById('help-modal').classList.add('hidden');
        }

        function addTreeRow(data = {url: '', prefix: '', exclude: 1}) {
            const container = document.getElementById('trees-container');
            const row = document.createElement('div');
            row.className = "tree-row grid grid-cols-12 gap-3 items-end bg-slate-900/50 p-4 rounded-2xl border border-slate-800 hover:border-slate-700 transition-colors";
            row.innerHTML = `
                <div class="col-span-12 md:col-span-5">
                    <span class="text-[10px] text-slate-500 ml-1 font-bold uppercase">目录树下载 URL</span>
                    <input class="t-url w-full bg-slate-950 border-slate-700 rounded-lg p-2.5 text-sm mt-1 outline-none focus:border-sky-500" value="${escapeHtml(data.url)}" placeholder="AList/OpenList 中的 tree.txt 下载链接">
                </div>
                <div class="col-span-7 md:col-span-4">
                    <span class="text-[10px] text-slate-500 ml-1 font-bold uppercase">父文件夹路径前缀 (选填)</span>
                    <input class="t-prefix w-full bg-slate-950 border-slate-700 rounded-lg p-2.5 text-sm mt-1 outline-none focus:border-sky-500" value="${escapeHtml(data.prefix)}" placeholder="补全丢失的路径，如: 电影/漫威">
                </div>
                <div class="col-span-3 md:col-span-2">
                    <span class="text-[10px] text-slate-500 ml-1 font-bold uppercase">排除层级</span>
                    <input type="number" min="1" class="t-exclude w-full bg-slate-950 border-slate-700 rounded-lg p-2.5 text-sm mt-1 outline-none focus:border-sky-500" value="${Number(data.exclude || 1)}">
                </div>
                <div class="col-span-2 md:col-span-1">
                    <button onclick="this.parentElement.parentElement.remove()" class="w-full bg-red-500/10 text-red-500 hover:bg-red-500 hover:text-white p-2.5 rounded-lg transition-colors text-sm font-bold">✕</button>
                </div>
            `;
            container.appendChild(row);
        }

        function resetExtensions() {
            if (confirm("确定要恢复默认扫描后缀名吗？\n(恢复后请手动点击下方的保存全部配置)")) {
                document.getElementById('extensions').value = DEFAULT_EXTENSIONS;
            }
        }

        async function triggerTask(local, full) {
            if (isRunning) return;
            const res = await fetch('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({use_local: local, force_full: full})
            });
            if ((await res.json()).status === 'started') updateButtonState(true);
        }

        function updateButtonState(running) {
            isRunning = running;
            document.querySelectorAll('.btn-ctrl').forEach((btn, i) => {
                btn.classList.toggle('btn-disabled', running);
                btn.innerText = running ? "⏳ 任务运行中..." : btnTexts[i];
            });
        }

        function getCurrentTgProxyConfig() {
            return {
                tg_proxy_enabled: document.getElementById('tg_proxy_enabled').checked,
                tg_proxy_protocol: document.getElementById('tg_proxy_protocol').value.trim(),
                tg_proxy_host: document.getElementById('tg_proxy_host').value.trim(),
                tg_proxy_port: document.getElementById('tg_proxy_port').value.trim()
            };
        }

        function getCurrentTgChannelThreads() {
            const inputRaw = parseInt(document.getElementById('tg_channel_threads')?.value || '', 10);
            const stateRaw = parseInt(resourceState?.search_meta?.thread_limit || '', 10);
            const candidate = Number.isFinite(inputRaw)
                ? inputRaw
                : (Number.isFinite(stateRaw) ? stateRaw : 6);
            return Math.min(20, Math.max(1, candidate));
        }

        function formatDurationText(durationMs) {
            const value = Number(durationMs || 0);
            if (!Number.isFinite(value) || value <= 0) return '';
            if (value < 1000) return `总耗时 ${Math.max(1, Math.round(value))} ms`;
            return `总耗时 ${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} s`;
        }

        function formatLatencyText(latencyMs) {
            const value = Number(latencyMs || 0);
            if (!Number.isFinite(value) || value <= 0) return '延迟 --';
            return `延迟 ${Math.max(1, Math.round(value))} ms`;
        }

        async function probeResourceTgLatency() {
            try {
                const res = await fetch('/settings/tg_proxy/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(getCurrentTgProxyConfig())
                });
                const data = await res.json();
                if (!res.ok || !data.ok) return { ok: false, latency_ms: 0 };
                const latencyMs = Number(data.latency_ms || 0);
                if (Number.isFinite(latencyMs) && latencyMs > 0) {
                    resourceTgLastLatencyMs = Math.max(1, Math.round(latencyMs));
                }
                return { ok: true, latency_ms: resourceTgLastLatencyMs };
            } catch (e) {
                return { ok: false, latency_ms: 0 };
            }
        }

        async function resolveResourceTgLatencyMs(probePromise, timeoutMs = 6500) {
            if (!probePromise) return Number(resourceTgLastLatencyMs || 0);
            try {
                const result = await Promise.race([
                    probePromise,
                    new Promise(resolve => setTimeout(() => resolve({ ok: false, latency_ms: 0 }), timeoutMs))
                ]);
                const latencyMs = Number(result?.latency_ms || 0);
                if (Number.isFinite(latencyMs) && latencyMs > 0) {
                    resourceTgLastLatencyMs = Math.max(1, Math.round(latencyMs));
                }
            } catch (e) {}
            return Number(resourceTgLastLatencyMs || 0);
        }

        function renderTgProxyTestStatus() {
            const btn = document.getElementById('tg-proxy-test-btn');
            const statusEl = document.getElementById('tg-proxy-test-status');
            if (btn) {
                btn.disabled = tgProxyTestState.loading;
                btn.classList.toggle('btn-disabled', tgProxyTestState.loading);
                btn.textContent = tgProxyTestState.loading ? '测试中...' : '测试 TG 延迟';
            }
            if (!statusEl) return;

            if (tgProxyTestState.loading) {
                statusEl.className = 'tg-proxy-status tg-proxy-status--loading';
                statusEl.innerHTML = `
                    <div class="tg-proxy-status-title">正在测试 TG 访问链路</div>
                    <div class="tg-proxy-status-meta">正在请求 TG 频道页并测量当前响应时间，请稍候...</div>
                `;
                statusEl.classList.remove('hidden');
                return;
            }

            if (tgProxyTestState.ok === true) {
                const modeLabel = tgProxyTestState.mode === 'proxy'
                    ? `代理模式 ${escapeHtml(tgProxyTestState.proxy_url || '--')}`
                    : '直连模式';
                statusEl.className = 'tg-proxy-status tg-proxy-status--success';
                statusEl.innerHTML = `
                    <div class="tg-proxy-status-title">TG 可达 · ${escapeHtml(formatDurationText(tgProxyTestState.latency_ms) || `总耗时 ${String(tgProxyTestState.latency_ms || 0)} ms`)}</div>
                    <div class="tg-proxy-status-meta">${modeLabel}</div>
                    <div class="tg-proxy-status-note">测试地址：${escapeHtml(tgProxyTestState.target_url || '')}</div>
                `;
                statusEl.classList.remove('hidden');
                return;
            }

            if (tgProxyTestState.ok === false) {
                statusEl.className = 'tg-proxy-status tg-proxy-status--error';
                statusEl.innerHTML = `
                    <div class="tg-proxy-status-title">TG 延迟测试失败</div>
                    <div class="tg-proxy-status-meta">${escapeHtml(tgProxyTestState.message || '未知错误')}</div>
                `;
                statusEl.classList.remove('hidden');
                return;
            }

            statusEl.classList.add('hidden');
            statusEl.textContent = '';
        }

        async function testTgProxyLatency() {
            if (tgProxyTestState.loading) return;
            tgProxyTestState = { loading: true, ok: null, message: '', latency_ms: 0, mode: '', proxy_url: '', target_url: '' };
            renderTgProxyTestStatus();
            try {
                const res = await fetch('/settings/tg_proxy/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(getCurrentTgProxyConfig())
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || 'TG 延迟测试失败');
                tgProxyTestState = {
                    loading: false,
                    ok: true,
                    message: data.msg || '',
                    latency_ms: Number(data.latency_ms || 0),
                    mode: String(data.mode || ''),
                    proxy_url: String(data.proxy_url || ''),
                    target_url: String(data.target_url || '')
                };
            } catch (e) {
                tgProxyTestState = {
                    loading: false,
                    ok: false,
                    message: e instanceof Error ? e.message : String(e || 'TG 延迟测试失败'),
                    latency_ms: 0,
                    mode: '',
                    proxy_url: '',
                    target_url: ''
                };
            }
            renderTgProxyTestStatus();
        }

        function setResourceTgHealthState(nextState = {}) {
            resourceTgHealthState = {
                ...resourceTgHealthState,
                ...nextState
            };
            renderResourceTgHealthStatus();
        }

        function formatResourceTgHealthInlineText() {
            if (!resourceTgHealthState.visible) return '';
            const title = String(resourceTgHealthState.title || '').trim();
            const meta = String(resourceTgHealthState.meta || '').trim();
            if (!title && !meta) return '';
            if (title === 'TG 待命') return '';
            return [title, meta].filter(Boolean).join(' · ');
        }

        function renderResourceBoardHint() {
            const hint = document.getElementById('resource-board-hint');
            if (!hint) return;
            const keyword = String(document.getElementById('resource-search-input')?.value || resourceState.search || '').trim();
            const directImport = isDirectImportInput(keyword);
            const tone = ['loading', 'success', 'warning', 'error'].includes(resourceTgHealthState.tone)
                ? resourceTgHealthState.tone
                : 'loading';
            const tgText = formatResourceTgHealthInlineText();
            let text = String(resourceBoardHintText || '').trim();

            if (resourceSearchBusy) {
                if (directImport) {
                    text = '正在识别导入链接，请稍候。';
                } else {
                    const baseText = `正在频道内搜索「${keyword || '...'}」，请稍候。`;
                    text = tgText ? `${baseText} ${tgText}` : baseText;
                }
            } else if (resourceSyncBusy) {
                const baseText = '正在刷新订阅频道资源，请稍候。';
                text = tgText ? `${baseText} ${tgText}` : baseText;
            } else if (tgText) {
                text = text ? `${text} ｜ ${tgText}` : tgText;
            }

            const hasText = !!text;
            hint.classList.toggle('hidden', !hasText);
            hint.classList.toggle('is-loading', hasText && (resourceSearchBusy || resourceSyncBusy));
            hint.classList.remove(
                'resource-search-sub--loading',
                'resource-search-sub--success',
                'resource-search-sub--warning',
                'resource-search-sub--error'
            );
            if (hasText && tgText) hint.classList.add(`resource-search-sub--${tone}`);
            hint.innerText = hasText ? text : '';
        }

        function renderResourceTgHealthStatus() {
            renderResourceBoardHint();
        }

        function getActionElapsedMs(startedAt) {
            if (!Number.isFinite(Number(startedAt || 0))) return 0;
            return Math.max(1, Math.round(performance.now() - Number(startedAt || 0)));
        }

        function setResourceTgHealthResult({ tone, title, detail = '', durationMs = 0, latencyMs = 0 }) {
            const totalText = formatDurationText(durationMs) || '总耗时 --';
            const parts = [formatLatencyText(latencyMs), totalText];
            if (detail) parts.push(detail);
            setResourceTgHealthState({
                visible: true,
                tone,
                title,
                meta: parts.join(' · '),
                note: '',
            });
        }

        function showResourceTgHealthLoading(context) {
            const actionText = context === 'sync'
                ? '刷新中'
                : '搜索中';
            setResourceTgHealthState({
                visible: true,
                tone: 'loading',
                title: `TG ${actionText}`,
                meta: '延迟检测中 · 总耗时 --',
                note: '',
            });
        }

        function applyResourceTgHealthFromSearchResult(data, durationMs = 0, latencyMs = 0) {
            const errors = Array.isArray(data?.search_meta?.errors) ? data.search_meta.errors : [];
            const searchedSources = Number(data?.search_meta?.searched_sources || 0);
            const filteredCount = Number(data?.stats?.filtered_item_count || 0);
            const successCount = Math.max(0, searchedSources - errors.length);

            if (!errors.length) {
                setResourceTgHealthResult({
                    tone: 'success',
                    title: 'TG 搜索完成',
                    detail: filteredCount > 0
                        ? `命中 ${filteredCount} 条`
                        : `扫描 ${searchedSources} 个频道`,
                    durationMs,
                    latencyMs,
                });
                return;
            }

            if (successCount > 0) {
                setResourceTgHealthResult({
                    tone: 'warning',
                    title: 'TG 搜索波动',
                    detail: `成功 ${successCount} / ${searchedSources}`,
                    durationMs,
                    latencyMs,
                });
                return;
            }

            setResourceTgHealthResult({
                tone: 'error',
                title: 'TG 搜索异常',
                detail: `${errors.length || searchedSources || 0} 个频道失败`,
                durationMs,
                latencyMs,
            });
        }

        function applyResourceTgHealthFromSyncResult(data, durationMs = 0, latencyMs = 0) {
            const errors = Array.isArray(data?.errors) ? data.errors : [];
            const synced = Number(data?.synced || 0);
            const skipped = Number(data?.skipped || 0);
            const inserted = Number(data?.items || 0);
            const pruned = Number(data?.cache_pruned || 0);

            if (!errors.length) {
                setResourceTgHealthResult({
                    tone: 'success',
                    title: 'TG 刷新完成',
                    detail: `频道 ${synced} · 新增 ${inserted}${skipped ? ` · 缓存 ${skipped}` : ''}${pruned ? ` · 清理 ${pruned}` : ''}`,
                    durationMs,
                    latencyMs,
                });
                return;
            }

            if (synced > 0 || skipped > 0) {
                setResourceTgHealthResult({
                    tone: 'warning',
                    title: 'TG 刷新波动',
                    detail: `成功 ${synced} · 异常 ${errors.length}`,
                    durationMs,
                    latencyMs,
                });
                return;
            }

            setResourceTgHealthResult({
                tone: 'error',
                title: 'TG 刷新异常',
                detail: `${errors.length} 个频道失败`,
                durationMs,
                latencyMs,
            });
        }

        function applyResourceTgHealthFailure(context, durationMs = 0, latencyMs = 0) {
            const actionText = context === 'sync' ? '刷新未完成' : '搜索未完成';
            setResourceTgHealthResult({
                tone: 'error',
                title: 'TG 异常',
                detail: actionText,
                durationMs,
                latencyMs,
            });
        }

        async function saveSettings() {
            const cfg = {};
            const standardIds = [
                'alist_url',
                'alist_token',
                'cookie_115',
                'tg_proxy_protocol',
                'tg_proxy_host',
                'tg_proxy_port',
                'tmdb_api_key',
                'tmdb_language',
                'tmdb_region',
                'mount_path',
                'cron_hour',
                'sync_mode',
                'extensions',
                'username',
                'password',
                'webhook_secret'
            ];
            standardIds.forEach(id => {
                const el = document.getElementById(id);
                if (el) cfg[id] = el.value;
            });

            cfg.check_hash = document.getElementById('check_hash').checked;
            cfg.sync_clean = document.getElementById('sync_clean').checked;
            cfg.tg_proxy_enabled = document.getElementById('tg_proxy_enabled').checked;
            cfg.tmdb_enabled = document.getElementById('tmdb_enabled').checked;
            const rawTmdbCacheTtl = parseInt(document.getElementById('tmdb_cache_ttl_hours')?.value || '', 10);
            cfg.tmdb_cache_ttl_hours = Math.min(720, Math.max(1, Number.isFinite(rawTmdbCacheTtl) ? rawTmdbCacheTtl : 24));
            const rawTgThreads = parseInt(document.getElementById('tg_channel_threads')?.value || '', 10);
            cfg.tg_channel_threads = Math.min(20, Math.max(1, Number.isFinite(rawTgThreads) ? rawTgThreads : 6));
            cfg.monitor_tasks = monitorState.tasks || [];
            cfg.trees = [];

            document.querySelectorAll('.tree-row').forEach(row => {
                const url = row.querySelector('.t-url').value.trim();
                if (url) {
                    cfg.trees.push({
                        url,
                        prefix: row.querySelector('.t-prefix').value.trim(),
                        exclude: parseInt(row.querySelector('.t-exclude').value || '1', 10) || 1
                    });
                }
            });

            const res = await fetch('/save_settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(cfg)
            });

            if (res.ok) {
                alert('✅ 配置已保存');
            } else {
                alert('❌ 保存失败');
            }
        }

        async function clearMainLogs() {
            const res = await fetch('/logs/clear', { method: 'POST' });
            if (res.ok) {
                lastLogSignature = '';
                await refreshMainLogs();
            }
        }

        async function clearMonitorLogs() {
            const res = await fetch('/monitor/logs/clear', { method: 'POST' });
            if (res.ok) {
                lastMonitorLogSignature = '';
                await refreshMonitorState();
            }
        }

        function currentMonitorFormData() {
            return {
                name: document.getElementById('monitor_name').value.trim(),
                webhook_enabled: document.getElementById('monitor_webhook_enabled').checked,
                scan_path: document.getElementById('monitor_scan_path').value.trim(),
                target_path: document.getElementById('monitor_target_path').value.trim(),
                skip_by_dir_mtime: document.getElementById('monitor_skip_by_dir_mtime').checked,
                incremental: document.getElementById('monitor_incremental').checked,
                retries: parseInt(document.getElementById('monitor_retries').value || '3', 10) || 3,
                list_delay_ms: parseInt(document.getElementById('monitor_list_delay_ms').value || '0', 10) || 0,
                min_file_size_mb: parseFloat(document.getElementById('monitor_min_file_size_mb').value || '0') || 0,
                delay_seconds: parseInt(document.getElementById('monitor_delay_seconds').value || '0', 10) || 0,
                cron_minutes: parseInt(document.getElementById('monitor_cron_minutes').value || '0', 10) || 0
            };
        }

        function resetMonitorForm() {
            editingMonitorName = null;
            document.getElementById('monitor-modal-title').innerText = '新增监控任务';
            document.getElementById('monitor_name').value = '';
            document.getElementById('monitor_webhook_enabled').checked = false;
            document.getElementById('monitor_scan_path').value = '';
            document.getElementById('monitor_target_path').value = '';
            document.getElementById('monitor_skip_by_dir_mtime').checked = false;
            document.getElementById('monitor_incremental').checked = false;
            document.getElementById('monitor_retries').value = 3;
            document.getElementById('monitor_list_delay_ms').value = 0;
            document.getElementById('monitor_min_file_size_mb').value = 0;
            document.getElementById('monitor_delay_seconds').value = 0;
            document.getElementById('monitor_cron_minutes').value = 0;
            refreshWebhookHint();
        }

        function openNewMonitorTask() {
            resetMonitorForm();
            document.getElementById('monitor-modal').classList.remove('hidden');
        }

        function closeMonitorModal() {
            document.getElementById('monitor-modal').classList.add('hidden');
        }

        function refreshWebhookHint() {
            const name = document.getElementById('monitor_name').value.trim() || '任务名';
            document.getElementById('webhook-hint').innerHTML = [
                `webhook 地址：IP:容器端口/webhook/${escapeHtml(name)}（用于触发指定任务）`,
                '普通刷新参数：savepath / sharetitle / refresh_target_type / delayTime / title',
                '磁力任务参数：magnet 或 link_url（值为磁力链接） + savepath（必填）',
                '磁力任务会直接创建到资源导入队列，并按当前监控任务自动刷新',
                '签名校验（可选）：X-Webhook-Ts / X-Webhook-Nonce / X-Webhook-Sign 或 X-Webhook-Token',
                '说明：签名密钥在「参数配置 -> 后台安全管理」里设置；为空时不校验'
            ].join('<br>');
        }

        async function persistMonitorTasks(tasks) {
            const res = await fetch('/monitor/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ tasks })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                throw new Error(data.msg || '保存监控任务失败');
            }
            applyMonitorState({ ...monitorState, tasks: data.tasks || [] }, { forceRender: true });
        }

        async function saveMonitorTask() {
            const task = currentMonitorFormData();
            if (!task.name) return alert('任务名不能为空');
            if (!task.scan_path) return alert('扫描路径不能为空');
            if (!task.target_path) return alert('目标路径不能为空');
            if (task.retries < 1 || task.retries > 5) return alert('读取失败尝试次数只能在 1 到 5 之间');
            if (task.cron_minutes < 0) return alert('定时执行分钟不能小于 0');

            const tasks = [...(monitorState.tasks || [])];
            const dup = tasks.find(item => item.name === task.name && item.name !== editingMonitorName);
            if (dup) return alert('任务名重复，请修改后再保存');

            const idx = tasks.findIndex(item => item.name === editingMonitorName);
            if (idx >= 0) tasks[idx] = task;
            else tasks.push(task);

            try {
                await persistMonitorTasks(tasks);
                resetMonitorForm();
                closeMonitorModal();
                alert('✅ 监控任务已保存');
            } catch (e) {
                alert(`❌ ${e.message}`);
            }
        }

        function editMonitorTask(name) {
            const task = (monitorState.tasks || []).find(item => item.name === name);
            if (!task) return;
            editingMonitorName = task.name;
            document.getElementById('monitor-modal-title').innerText = `编辑监控任务：${task.name}`;
            document.getElementById('monitor_name').value = task.name || '';
            document.getElementById('monitor_webhook_enabled').checked = !!task.webhook_enabled;
            document.getElementById('monitor_scan_path').value = task.scan_path || '';
            document.getElementById('monitor_target_path').value = task.target_path || '';
            document.getElementById('monitor_skip_by_dir_mtime').checked = !!task.skip_by_dir_mtime;
            document.getElementById('monitor_incremental').checked = !!task.incremental;
            document.getElementById('monitor_retries').value = task.retries ?? 3;
            document.getElementById('monitor_list_delay_ms').value = task.list_delay_ms ?? 0;
            document.getElementById('monitor_min_file_size_mb').value = task.min_file_size_mb ?? 0;
            document.getElementById('monitor_delay_seconds').value = task.delay_seconds ?? 0;
            document.getElementById('monitor_cron_minutes').value = task.cron_minutes ?? 0;
            refreshWebhookHint();
            document.getElementById('monitor-modal').classList.remove('hidden');
            switchTab('monitor');
        }

        async function deleteMonitorTask(name) {
            if (!confirm(`确定删除监控任务“${name}”吗？`)) return;
            if (isMonitorActionLocked('delete', name)) return;
            setMonitorActionLock('delete', name, true);
            try {
                const res = await fetch('/monitor/delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ name })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    return alert(`❌ ${data.msg || '删除失败'}`);
                }
                applyMonitorState({
                    ...monitorState,
                    tasks: (monitorState.tasks || []).filter(item => item.name !== name),
                    queued: (monitorState.queued || []).filter(item => item !== name),
                    next_runs: Object.fromEntries(Object.entries(monitorState.next_runs || {}).filter(([taskName]) => taskName !== name))
                }, { forceRender: true });
                if (editingMonitorName === name) resetMonitorForm();
            } finally {
                setMonitorActionLock('delete', name, false);
            }
        }

        async function startMonitorTask(name) {
            if (isMonitorActionLocked('start', name)) return;
            setMonitorActionLock('start', name, true);
            try {
                const res = await fetch('/monitor/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ name })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    return alert(`❌ ${data.msg || '启动失败'}`);
                }

                const queued = Array.isArray(monitorState.queued) ? [...monitorState.queued] : [];
                if (data.status === 'queued') {
                    if (!queued.includes(name)) queued.push(name);
                    applyMonitorState({ ...monitorState, queued }, { forceRender: true });
                } else {
                    applyMonitorState({
                        ...monitorState,
                        running: true,
                        current_task: name,
                        queued: queued.filter(item => item !== name),
                        summary: { step: '准备执行', detail: `${name} (manual)` }
                    }, { forceRender: true });
                }
                await refreshMonitorState();
            } finally {
                setMonitorActionLock('start', name, false);
            }
        }

        async function stopMonitorTask(name) {
            if (isMonitorActionLocked('stop', name)) return;
            setMonitorActionLock('stop', name, true);
            try {
                const res = await fetch('/monitor/stop', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ name })
                });
                const data = await res.json();
                if (!data.ok) {
                    alert('当前没有这个任务在运行');
                    return;
                }
                applyMonitorState({
                    ...monitorState,
                    summary: { step: '正在中断', detail: `${name} 已发送中断请求` }
                }, { forceRender: true });
                await refreshMonitorState();
            } finally {
                setMonitorActionLock('stop', name, false);
            }
        }

        function renderMonitorTasks() {
            const container = document.getElementById('monitor-task-list');
            const tasks = monitorState.tasks || [];
            if (!tasks.length) {
                container.innerHTML = `<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">还没有文件夹监控任务，点击“新增任务”即可创建。</div>`;
                return;
            }

            container.innerHTML = tasks.map(task => {
                const taskKey = encodeURIComponent(task.name || '');
                const running = monitorState.running && monitorState.current_task === task.name;
                const queued = (monitorState.queued || []).includes(task.name);
                const starting = isMonitorActionLocked('start', task.name);
                const stopping = isMonitorActionLocked('stop', task.name);
                const deleting = isMonitorActionLocked('delete', task.name);
                const startDisabled = monitorState.running || starting || stopping || deleting;
                const stopDisabled = !running || starting || stopping || deleting;
                const deleteDisabled = running || starting || stopping || deleting;
                const badge = running
                    ? '<span class="text-[10px] px-3 py-1 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">运行中</span>'
                    : queued
                        ? '<span class="text-[10px] px-3 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/20">已排队</span>'
                        : '<span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-300">待命</span>';
                const nextRun = (monitorState.next_runs || {})[task.name];
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-4">
                        <div class="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
                            <div class="space-y-2">
                                <div class="flex items-center gap-3 flex-wrap">
                                    <div class="text-lg font-black text-white">${escapeHtml(task.name)}</div>
                                    ${badge}
                                    ${task.webhook_enabled ? '<span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/20">Webhook</span>' : ''}
                                    ${task.incremental ? '<span class="text-[10px] px-3 py-1 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/20">增量</span>' : '<span class="text-[10px] px-3 py-1 rounded-full bg-red-500/10 text-red-300 border border-red-500/20">全量</span>'}
                                </div>
                                <div class="text-xs text-slate-400 leading-6">
                                    <div>扫描路径：${escapeHtml(task.scan_path)}</div>
                                    <div>目标路径：/strm/${escapeHtml(task.target_path)}</div>
                                    <div>参数：重试 ${task.retries} 次 / 列目录延时 ${task.list_delay_ms}ms / 体积过滤 ${task.min_file_size_mb}MB / 执行延时 ${task.delay_seconds}s / 定时 ${task.cron_minutes || 0} 分钟</div>
                                    <div>下次定时：${nextRun ? escapeHtml(nextRun) : '未开启'}</div>
                                </div>
                            </div>
                            <div class="monitor-task-actions grid grid-cols-4 gap-2 shrink-0 w-full lg:w-auto">
                                <button type="button" data-monitor-action="start" data-task-name="${taskKey}" class="px-2 sm:px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold ${startDisabled ? 'btn-disabled' : ''}" ${startDisabled ? 'disabled' : ''}>${starting ? '启动中...' : '运行'}</button>
                                <button type="button" data-monitor-action="stop" data-task-name="${taskKey}" class="px-2 sm:px-3 py-2 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 text-sm font-bold ${stopDisabled ? 'btn-disabled' : ''}" ${stopDisabled ? 'disabled' : ''}>${stopping ? '中断中...' : '中断'}</button>
                                <button type="button" data-monitor-action="edit" data-task-name="${taskKey}" class="px-2 sm:px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">编辑</button>
                                <button type="button" data-monitor-action="delete" data-task-name="${taskKey}" class="px-2 sm:px-3 py-2 rounded-xl bg-red-500/15 hover:bg-red-500/25 text-red-300 text-sm font-bold ${deleteDisabled ? 'btn-disabled' : ''}" ${deleteDisabled ? 'disabled' : ''}>${deleting ? '删除中...' : '删除'}</button>
                            </div>
                        </div>
                        ${task.webhook_enabled ? `<div class="mt-3 text-xs text-emerald-400">Webhook：IP:容器端口/webhook/${escapeHtml(task.name)}</div>` : ''}
                    </div>
                `;
            }).join('');
        }

        function isMonitorPageVisible() {
            return !document.getElementById('page-monitor')?.classList.contains('hidden');
        }

        function renderMonitorUserscriptJobs() {
            const container = document.getElementById('monitor-userscript-job-list');
            const summaryEl = document.getElementById('monitor-userscript-job-summary');
            if (!container || !summaryEl) return;

            const jobs = Array.isArray(monitorUserscriptJobs) ? monitorUserscriptJobs : [];
            const counts = monitorUserscriptJobCounts || getResourceJobCounts(jobs);
            summaryEl.innerText = jobs.length
                ? `最近 ${counts.total || jobs.length} 条油猴任务，处理中 ${counts.active || 0} 条，已完成 ${counts.completed || 0} 条${counts.failed ? `，失败 ${counts.failed} 条` : ''}`
                : (monitorUserscriptJobsLoading ? '正在读取油猴导入任务...' : '暂无油猴脚本导入任务');

            if (!jobs.length) {
                container.innerHTML = monitorUserscriptJobsLoading
                    ? `<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">正在加载任务列表...</div>`
                    : `<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">暂无记录。油猴脚本推送成功后会在这里显示。</div>`;
                return;
            }

            container.innerHTML = jobs.map(job => {
                const hasMonitorTask = !!String(job.monitor_task_name || '').trim();
                const normalizedStatus = String(job.status || '').toLowerCase();
                const canManualRefresh = hasMonitorTask && !job.last_triggered_at && normalizedStatus === 'submitted';
                const canCancel = ['pending', 'running', 'submitted'].includes(normalizedStatus);
                const canRetry = normalizedStatus === 'failed';
                const autoRefreshText = hasMonitorTask
                    ? (job.auto_refresh ? `自动刷新 ${escapeHtml(String(job.refresh_delay_seconds || 0))} 秒` : '手动刷新')
                    : '未绑定监控';
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-4">
                        <div class="flex flex-col xl:flex-row xl:items-start xl:justify-between gap-4">
                            <div class="min-w-0 space-y-2">
                                <div class="flex items-center gap-2 flex-wrap">
                                    <div class="text-sm font-black text-white">${escapeHtml(job.title || `任务 #${job.id}`)}</div>
                                    ${buildResourceStatusBadge(job.status)}
                                    <span class="text-[10px] px-2 py-1 rounded-full bg-slate-700 text-slate-100">#${job.id}</span>
                                </div>
                                <div class="text-xs text-slate-400 leading-6">
                                    <div>保存路径：${escapeHtml(job.savepath || '--')}</div>
                                    <div>监控任务：${escapeHtml(job.monitor_task_name || '--')}</div>
                                    <div>刷新策略：${escapeHtml(getResourceRefreshTargetLabel(job.refresh_target_type))} · ${autoRefreshText}</div>
                                    <div>创建时间：${escapeHtml(formatTimeText(job.created_at || '--'))}</div>
                                </div>
                                <div class="text-xs text-slate-300 break-all">${escapeHtml(job.status_detail || '--')}</div>
                            </div>
                            <div class="flex flex-wrap gap-2 shrink-0">
                                <button type="button" data-monitor-userscript-action="cancel" data-resource-job-id="${job.id}" class="px-3 py-2 rounded-xl text-xs font-bold ${canCancel ? 'bg-amber-600 hover:bg-amber-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canCancel ? '' : 'disabled'}>取消</button>
                                <button type="button" data-monitor-userscript-action="retry" data-resource-job-id="${job.id}" class="px-3 py-2 rounded-xl text-xs font-bold ${canRetry ? 'bg-emerald-600 hover:bg-emerald-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canRetry ? '' : 'disabled'}>重试</button>
                                <button type="button" data-monitor-userscript-action="refresh" data-resource-job-id="${job.id}" class="px-3 py-2 rounded-xl text-xs font-bold ${canManualRefresh ? 'bg-sky-600 hover:bg-sky-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canManualRefresh ? '' : 'disabled'}>刷新</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function refreshMonitorUserscriptJobs(force = false) {
            if (monitorUserscriptJobsLoading) return;
            if (!force && !isMonitorPageVisible()) return;
            monitorUserscriptJobsLoading = true;
            renderMonitorUserscriptJobs();
            try {
                const res = await fetch(`/monitor/userscript/jobs?limit=${encodeURIComponent(String(MONITOR_USERSCRIPT_JOB_LIMIT))}`);
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.msg || '读取油猴任务失败');
                }
                monitorUserscriptJobs = Array.isArray(data.jobs) ? data.jobs : [];
                monitorUserscriptJobCounts = data.counts || getResourceJobCounts(monitorUserscriptJobs);
            } catch (e) {
                if (!monitorUserscriptJobs.length) {
                    const summaryEl = document.getElementById('monitor-userscript-job-summary');
                    if (summaryEl) summaryEl.innerText = `读取失败：${e.message || '请稍后重试'}`;
                }
            } finally {
                monitorUserscriptJobsLoading = false;
                renderMonitorUserscriptJobs();
            }
        }

        function renderMonitorLogs() {
            const box = document.getElementById('monitor-log-box');
            const logs = monitorState.logs || [];
            const logSignature = buildLogSignature(logs, (item) => `${item?.level || 'info'}:${item?.text || ''}`);
            if (logSignature === lastMonitorLogSignature) return;
            box.innerHTML = logs.map(item => `<div class="log-${item.level || 'info'}">${formatMonitorLogHtml(item)}</div>`).join('');
            box.scrollTop = box.scrollHeight;
            lastMonitorLogSignature = logSignature;
        }

        async function refreshMainLogs() {
            try {
                const res = await fetch('/logs');
                if (!res.ok) return;
                applyMainState(await res.json());
            } catch (e) {}
        }

        async function refreshMonitorState() {
            try {
                const res = await fetch('/monitor/status');
                if (!res.ok) return;
                applyMonitorState(await res.json());
                if (isMonitorPageVisible()) refreshMonitorUserscriptJobs();
            } catch (e) {}
        }

        function buildSubscriptionRenderKey(state) {
            return JSON.stringify({
                running: !!state?.running,
                current_task: state?.current_task || '',
                queued: Array.isArray(state?.queued) ? state.queued : [],
                next_runs: state?.next_runs || {},
                tasks: Array.isArray(state?.tasks) ? state.tasks : []
            });
        }

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
            if (!data) return;
            subscriptionState = {
                ...subscriptionState,
                ...data,
                tasks: Array.isArray(data.tasks) ? data.tasks : (subscriptionState.tasks || []),
                logs: Array.isArray(data.logs) ? data.logs : (subscriptionState.logs || []),
                queued: Array.isArray(data.queued) ? data.queued : (subscriptionState.queued || []),
                next_runs: data.next_runs || subscriptionState.next_runs || {},
                summary: data.summary || subscriptionState.summary || { step: '空闲', detail: '等待订阅任务' }
            };

            const stepEl = document.getElementById('subscription-summary-step');
            const detailEl = document.getElementById('subscription-summary-detail');
            if (stepEl) stepEl.innerText = subscriptionState.summary?.step || '空闲';
            if (detailEl) detailEl.innerText = subscriptionState.summary?.detail || '等待订阅任务';

            const renderKey = buildSubscriptionRenderKey(subscriptionState);
            if (forceRender || renderKey !== lastSubscriptionRenderKey) {
                renderSubscriptionTasks();
                lastSubscriptionRenderKey = renderKey;
            }
            renderSubscriptionLogs();
        }

        function renderSubscriptionLogs() {
            const box = document.getElementById('subscription-log-box');
            if (!box) return;
            const logs = subscriptionState.logs || [];
            const logSignature = buildLogSignature(logs, (item) => `${item?.level || 'info'}:${item?.text || ''}`);
            if (logSignature === lastSubscriptionLogSignature) return;
            box.innerHTML = logs.map(item => `<div class="log-${item.level || 'info'}">${formatMonitorLogHtml(item)}</div>`).join('');
            box.scrollTop = box.scrollHeight;
            lastSubscriptionLogSignature = logSignature;
        }

        function normalizeSubscriptionMediaType(value) {
            const normalized = String(value || 'movie').trim().toLowerCase();
            return normalized === 'tv' ? 'tv' : 'movie';
        }

        function normalizeSubscriptionQualityPriority(value) {
            const normalized = String(value || 'balanced').trim().toLowerCase();
            if (['balanced', 'ultra', 'fhd', 'hd', 'sd'].includes(normalized)) return normalized;
            return 'balanced';
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

            return {
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
            syncSubscriptionTypeUI();
        }

        function parseSubscriptionAliases(value) {
            return uniquePreserveOrder(String(value || '')
                .split(/[,\n，|/]+/)
                .map(item => item.trim())
                .filter(Boolean));
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
                alert('请先输入影视名称，再搜索 TMDB');
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
                const res = await fetch(`/tmdb/search?${qs.toString()}`);
                const data = await res.json();
                if (requestToken !== subscriptionTmdbSearchToken) return;
                if (!res.ok || !data.ok) throw new Error(data.msg || 'TMDB 搜索失败');
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
                const res = await fetch(`/tmdb/detail?${qs.toString()}`);
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '读取 TMDB 详情失败');
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
                    const totalInput = document.getElementById('subscription_total_episodes');
                    const currentTotal = parseInt(totalInput?.value || '0', 10) || 0;
                    const selectedSeason = Math.max(1, parseInt(document.getElementById('subscription_season')?.value || '1', 10) || 1);
                    const seasonTotal = getTmdbSeasonEpisodeTotal(binding.tmdb_season_episode_map || {}, selectedSeason);
                    const multiSeasonMode = !!document.getElementById('subscription_anime_mode')?.checked;
                    const tmdbTotal = Math.max(0, parseInt(binding.tmdb_total_episodes || '0', 10) || 0);
                    const suggestedTotal = multiSeasonMode
                        ? (tmdbTotal > 0 ? tmdbTotal : seasonTotal)
                        : (seasonTotal > 0 ? seasonTotal : 0);
                    if (totalInput && currentTotal <= 0 && suggestedTotal > 0) totalInput.value = String(suggestedTotal);
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
            const tmdbBinding = getSubscriptionTmdbBindingFromForm();
            const multiSeasonMode = !!document.getElementById('subscription_anime_mode').checked;
            return {
                name: title,
                media_type: normalizeSubscriptionMediaType(document.getElementById('subscription_media_type').value),
                title,
                aliases: document.getElementById('subscription_aliases').value.trim(),
                year: document.getElementById('subscription_year').value.trim(),
                season: parseInt(document.getElementById('subscription_season').value || '1', 10) || 1,
                total_episodes: parseInt(document.getElementById('subscription_total_episodes').value || '0', 10) || 0,
                anime_mode: multiSeasonMode,
                multi_season_mode: multiSeasonMode,
                savepath: normalizeRelativePathInput(document.getElementById('subscription_savepath').value.trim()),
                cron_minutes: parseInt(document.getElementById('subscription_cron_minutes').value || '30', 10) || 0,
                min_score: parseInt(document.getElementById('subscription_min_score').value || '55', 10) || 55,
                quality_priority: normalizeSubscriptionQualityPriority(document.getElementById('subscription_quality_priority').value || 'balanced'),
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
            document.getElementById('subscription_media_type').value = 'movie';
            document.getElementById('subscription_title').value = '';
            document.getElementById('subscription_aliases').value = '';
            document.getElementById('subscription_year').value = '';
            document.getElementById('subscription_season').value = 1;
            document.getElementById('subscription_total_episodes').value = 0;
            document.getElementById('subscription_anime_mode').checked = false;
            setSubscriptionSavepath('0', '');
            subscriptionFolderTrail = [{ id: '0', name: '根目录' }];
            subscriptionFolderEntries = [];
            subscriptionFolderSummary = { folder_count: 0, file_count: 0 };
            subscriptionFolderLoading = false;
            subscriptionFolderCreateBusy = false;
            document.getElementById('subscription_cron_minutes').value = 30;
            document.getElementById('subscription_min_score').value = 55;
            document.getElementById('subscription_quality_priority').value = 'balanced';
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
            const res = await fetch('/subscription/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tasks })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.msg || '保存订阅任务失败');
            applySubscriptionState({ ...subscriptionState, tasks: data.tasks || [] }, { forceRender: true });
        }

        async function saveSubscriptionTask() {
            const task = currentSubscriptionFormData();
            if (!task.title) return alert('订阅影视名称不能为空');
            if (!task.savepath) return alert('请先从网盘选择保存目录');
            if (task.year && !/^(19|20)\d{2}$/.test(task.year)) return alert('年份格式不正确，请输入四位年份');
            if (task.cron_minutes < 0) return alert('定时检查分钟不能小于 0');
            if (task.min_score < 30 || task.min_score > 100) return alert('匹配阈值需在 30-100 之间');
            if (!['balanced', 'ultra', 'fhd', 'hd', 'sd'].includes(task.quality_priority)) return alert('清晰度优先级配置无效');
            if (task.tmdb_id > 0 && task.tmdb_media_type && task.tmdb_media_type !== task.media_type) {
                return alert('TMDB 绑定类型与订阅类型不一致，请重新绑定');
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
            const dup = tasks.find(item => item.name === task.name && item.name !== editingSubscriptionName);
            if (dup) return alert('影视名称重复，请修改标题或年份后再保存');
            const idx = tasks.findIndex(item => item.name === editingSubscriptionName);
            if (idx >= 0) tasks[idx] = task;
            else tasks.push(task);

            try {
                await persistSubscriptionTasks(tasks);
                closeSubscriptionModal();
                resetSubscriptionForm();
                alert('✅ 订阅任务已保存');
            } catch (e) {
                alert(`❌ ${e.message}`);
            }
        }

        function editSubscriptionTask(name) {
            const task = (subscriptionState.tasks || []).find(item => item.name === name);
            if (!task) return;
            editingSubscriptionName = task.name;
            const titleEl = document.getElementById('subscription-modal-title');
            if (titleEl) titleEl.innerText = `编辑订阅任务：${task.name}`;
            document.getElementById('subscription_media_type').value = normalizeSubscriptionMediaType(task.media_type || 'movie');
            document.getElementById('subscription_title').value = task.title || '';
            document.getElementById('subscription_aliases').value = Array.isArray(task.aliases) ? task.aliases.join(', ') : (task.aliases || '');
            document.getElementById('subscription_year').value = task.year || '';
            document.getElementById('subscription_season').value = task.season || 1;
            document.getElementById('subscription_total_episodes').value = task.total_episodes || 0;
            document.getElementById('subscription_anime_mode').checked = resolveTaskMultiSeasonMode(task);
            subscriptionFolderTrail = [{ id: '0', name: '根目录' }];
            setSubscriptionSavepath('0', task.savepath || '');
            document.getElementById('subscription_cron_minutes').value = task.cron_minutes ?? 30;
            document.getElementById('subscription_min_score').value = task.min_score ?? 55;
            document.getElementById('subscription_quality_priority').value = normalizeSubscriptionQualityPriority(task.quality_priority || 'balanced');
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
            if (!confirm(`确定删除订阅任务“${name}”吗？`)) return;
            const res = await fetch('/subscription/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                return alert(`❌ ${data.msg || '删除失败'}`);
            }
            await refreshSubscriptionState();
            if (editingSubscriptionName === name) resetSubscriptionForm();
        }

        async function startSubscriptionTask(name) {
            const res = await fetch('/subscription/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                return alert(`❌ ${data.msg || '启动失败'}`);
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

        async function stopSubscriptionTask(name) {
            const res = await fetch('/subscription/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            const data = await res.json();
            if (!data.ok) {
                alert('当前没有这个订阅任务在运行');
                return;
            }
            applySubscriptionState({
                ...subscriptionState,
                summary: { step: '正在中断', detail: `${name} 已发送中断请求` }
            }, { forceRender: true });
            await refreshSubscriptionState();
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
                const running = subscriptionState.running && subscriptionState.current_task === taskName;
                const queued = (subscriptionState.queued || []).includes(taskName);
                const status = running ? 'running' : (task.status || 'idle');
                const nextRun = (subscriptionState.next_runs || {})[taskName];
                const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
                const isTv = normalizeSubscriptionMediaType(task.media_type || 'movie') === 'tv';
                const multiSeasonMode = resolveTaskMultiSeasonMode(task);
                const episodeText = isTv
                    ? `追更进度：E${Number(task.last_episode || 0)}${Number(task.total_episodes || 0) > 0 ? ` / E${Number(task.total_episodes || 0)}` : ''}`
                    : '电影订阅：命中资源即执行';
                const statusBadge = queued
                    ? '<span class="text-[10px] px-3 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/20">已排队</span>'
                    : buildSubscriptionStatusBadge(status);
                const startDisabled = subscriptionState.running || running;
                const stopDisabled = !running;
                const actionGridClass = isTv
                    ? 'grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2 shrink-0'
                    : 'grid grid-cols-2 md:grid-cols-4 gap-2 shrink-0';
                const episodeViewButton = isTv
                    ? `<button type="button" data-subscription-action="episodes" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">集数视图</button>`
                    : '';
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-4">
                        <div class="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
                            <div class="space-y-3 min-w-0 flex-1">
                                <div class="flex items-center gap-3 flex-wrap">
                                    <div class="text-lg font-black text-white">${escapeHtml(taskName)}</div>
                                    ${statusBadge}
                                    <span class="text-[10px] px-3 py-1 rounded-full ${task.enabled === false ? 'bg-slate-700 text-slate-400' : 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'}">${task.enabled === false ? '已停用' : '已启用'}</span>
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-100">${isTv ? '电视剧' : '电影'}</span>
                                    ${Number(task.tmdb_id || 0) > 0 ? `<span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/20">TMDB #${escapeHtml(String(task.tmdb_id || 0))}</span>` : ''}
                                </div>
                                <div class="text-xs text-slate-400 leading-6">
                                    <div>订阅名称：${escapeHtml(task.title || '--')}</div>
                                    <div>保存路径：${escapeHtml(task.savepath || '--')}</div>
                                    <div>${escapeHtml(episodeText)}</div>
                                    ${isTv ? `<div>订阅模式：${multiSeasonMode ? '多季合一' : '单季订阅'}</div>` : ''}
                                    ${Number(task.tmdb_id || 0) > 0 ? `<div>TMDB：${escapeHtml(task.tmdb_title || task.title || '--')}${task.tmdb_year ? ` (${escapeHtml(task.tmdb_year)})` : ''}${isTv ? ` / ${task.tmdb_episode_mode === 'absolute' ? '绝对集序' : '按季集序'}` : ''}</div>` : ''}
                                    <div>匹配阈值：${escapeHtml(String(task.min_score || 55))} / 清晰度：${escapeHtml(getSubscriptionQualityPriorityLabel(task.quality_priority || 'balanced'))}</div>
                                    <div>定时：${Number(task.cron_minutes || 0)} 分钟 / 下次定时：${nextRun ? escapeHtml(nextRun) : '未开启'}</div>
                                    <div>最新命中：${escapeHtml(task.matched_resource_title || '--')}</div>
                                </div>
                            </div>
                            <div class="${actionGridClass}">
                                <button type="button" data-subscription-action="start" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold ${startDisabled ? 'btn-disabled' : ''}" ${startDisabled ? 'disabled' : ''}>运行</button>
                                <button type="button" data-subscription-action="stop" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 text-sm font-bold ${stopDisabled ? 'btn-disabled' : ''}" ${stopDisabled ? 'disabled' : ''}>中断</button>
                                <button type="button" data-subscription-action="edit" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">编辑</button>
                                <button type="button" data-subscription-action="delete" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-red-500/15 hover:bg-red-500/25 text-red-300 text-sm font-bold">删除</button>
                                ${episodeViewButton}
                            </div>
                        </div>
                        <div class="mt-3 space-y-2">
                            <div class="w-full bg-slate-950 rounded-full h-3 p-[2px] overflow-hidden">
                                <div class="bg-gradient-to-r from-sky-600 to-emerald-500 h-full rounded-full transition-width" style="width: ${progress}%"></div>
                            </div>
                            <div class="text-xs text-slate-500">${escapeHtml(task.detail || '等待执行')}</div>
                        </div>
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

            summaryEl.className = 'text-xs text-slate-300 mt-2';
            summaryEl.innerText = `已存在 ${presentInRange} 集 / 展示 ${displayTotal} 集（缺失 ${missingCount} 集）`;
            noteEl.innerText = [
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
                const res = await fetch(`/subscription/episodes?name=${encodeURIComponent(requestedTaskName)}`);
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '读取集数视图失败');
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
                alert('任务不存在或已被删除');
                return;
            }
            if (normalizeSubscriptionMediaType(task.media_type || 'movie') !== 'tv') {
                alert('仅电视剧任务支持集数视图');
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

        async function refreshSubscriptionState() {
            try {
                const res = await fetch('/subscription/status');
                if (!res.ok) return;
                applySubscriptionState(await res.json());
            } catch (e) {}
        }

        async function clearSubscriptionLogs() {
            const res = await fetch('/subscription/logs/clear', { method: 'POST' });
            if (res.ok) {
                lastSubscriptionLogSignature = '';
                await refreshSubscriptionState();
            }
        }

        function getResourceStatusLabel(status) {
            const normalized = String(status || 'new').trim().toLowerCase();
            const map = {
                new: '未处理',
                queued: '已入队',
                importing: '导入中',
                submitted: '待刷新',
                completed: '已完成',
                failed: '失败'
            };
            return map[normalized] || (normalized || '未处理');
        }

        function buildResourceStatusBadge(status) {
            const normalized = String(status || 'new').trim().toLowerCase();
            const map = {
                new: 'bg-slate-700 text-slate-100',
                queued: 'bg-sky-500/15 text-sky-300 border border-sky-500/20',
                importing: 'bg-violet-500/15 text-violet-300 border border-violet-500/20',
                submitted: 'bg-amber-500/15 text-amber-300 border border-amber-500/20',
                completed: 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20',
                failed: 'bg-red-500/10 text-red-300 border border-red-500/20'
            };
            const cls = map[normalized] || map.new;
            return `<span class="text-[10px] px-3 py-1 rounded-full ${cls}">${escapeHtml(getResourceStatusLabel(normalized))}</span>`;
        }

        function normalizeTelegramChannelIdInput(value) {
            return String(value || '')
                .trim()
                .replace(/^https?:\/\/t\.me\/s\//i, '')
                .replace(/^https?:\/\/t\.me\//i, '')
                .replace(/^https?:\/\/telegram\.me\/s\//i, '')
                .replace(/^https?:\/\/telegram\.me\//i, '')
                .replace(/^@/, '')
                .replace(/^\/+|\/+$/g, '');
        }

        function normalizeRelativePathInput(value) {
            return String(value || '')
                .split(/[\\/]+/)
                .map(part => part.trim())
                .filter(Boolean)
                .join('/');
        }

        function normalizeRemotePathInput(value) {
            const relative = normalizeRelativePathInput(value);
            return relative ? `/${relative}` : '/';
        }

        function joinRelativePathInput(...parts) {
            return parts
                .map(part => normalizeRelativePathInput(part))
                .filter(Boolean)
                .join('/');
        }

        function normalizeReceiveCodeInput(value) {
            const raw = String(value || '').trim().replace(/\s+/g, '');
            if (!raw) return '';
            return /^[A-Za-z0-9]{1,16}$/.test(raw) ? raw : '';
        }

        function extractReceiveCodeFromText(text) {
            const raw = String(text || '');
            const matched = raw.match(/(?:提取码|提取碼|访问码|訪問碼|密码|密碼|访问密码|訪問密碼|口令|pwd|pass(?:word|code)?|code)\s*(?:[:：=]|是|为|為)?\s*([A-Za-z0-9]{4,8})\b/i);
            return normalizeReceiveCodeInput(matched?.[1] || '');
        }

        function extractReceiveCodeFromShareUrl(url) {
            const raw = String(url || '').trim();
            if (!raw) return '';
            try {
                const normalized = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
                const parsed = new URL(normalized);
                const password = parsed.searchParams.get('password')
                    || parsed.searchParams.get('pwd')
                    || parsed.searchParams.get('receive_code')
                    || parsed.searchParams.get('access_code')
                    || parsed.searchParams.get('passcode')
                    || parsed.searchParams.get('code')
                    || '';
                return normalizeReceiveCodeInput(password);
            } catch (e) {
                return '';
            }
        }

        function getResourceSourceChannelId(source) {
            return normalizeTelegramChannelIdInput(source?.channel_id || source?.channel || '');
        }

        function isLikelyTelegramChannelId(channelId) {
            return /^[A-Za-z0-9_]{5,32}$/.test(String(channelId || '').trim());
        }

        function getResourceSourcesForSelect() {
            return Array.isArray(resourceState.sources) ? resourceState.sources : [];
        }

        function getEnabledResourceSources() {
            return getResourceSourcesForSelect().filter(source => source.enabled !== false && getResourceSourceChannelId(source));
        }

        function getResourceLinkTypeLabel(linkType) {
            const normalized = String(linkType || 'unknown').trim().toLowerCase();
            const map = {
                magnet: 'Magnet',
                '115share': '115 分享',
                ed2k: 'ED2K',
                quark: '夸克网盘',
                aliyun: '阿里云盘',
                baidu: '百度网盘',
                xunlei: '迅雷网盘',
                uc: 'UC 网盘',
                '123pan': '123 网盘',
                tianyi: '天翼云盘',
                pikpak: 'PikPak',
                lanzou: '蓝奏云',
                google_drive: 'Google Drive',
                onedrive: 'OneDrive',
                mega: 'MEGA',
                link: '直链',
                unknown: '待识别'
            };
            return map[normalized] || normalized || '待识别';
        }

        function detectResourceLinkTypeByUrl(url) {
            const raw = String(url || '').trim();
            const lowered = raw.toLowerCase();
            if (!lowered) return 'unknown';
            if (lowered.startsWith('magnet:?')) return 'magnet';
            if (lowered.startsWith('ed2k://')) return 'ed2k';
            if (/(?:https?:\/\/)?(?:115cdn|115|anxia)\.com\/s\/[a-z0-9]+/i.test(raw)) return '115share';
            if (/https?:\/\/(?:pan|www)\.quark\.cn\/s\/[a-z0-9]+/i.test(raw)) return 'quark';
            if (/https?:\/\/(?:www\.)?(?:aliyundrive|alipan)\.com\/s\/[a-z0-9]+/i.test(raw)) return 'aliyun';
            if (/https?:\/\/(?:pan|yun)\.baidu\.com\/(?:s\/|share\/)/i.test(raw)) return 'baidu';
            if (/https?:\/\/(?:pan|xlpan)\.xunlei\.com\/s\/[a-z0-9]+/i.test(raw)) return 'xunlei';
            if (/https?:\/\/drive\.uc\.cn\/s\/[a-z0-9]+/i.test(raw)) return 'uc';
            if (/https?:\/\/(?:www\.)?(?:123pan|123684|123865|123912)\.(?:com|cn)\/s\/[a-z0-9]+/i.test(raw)) return '123pan';
            if (/https?:\/\/cloud\.189\.cn\/(?:t\/|web\/share)/i.test(raw)) return 'tianyi';
            if (/https?:\/\/(?:www\.)?(?:mypikpak|pikpak)\.com\/s\/[a-z0-9]+/i.test(raw)) return 'pikpak';
            if (/https?:\/\/(?:www\.)?lanzou[a-z0-9]*\.[a-z.]+\/[a-z0-9]+/i.test(raw)) return 'lanzou';
            if (/https?:\/\/drive\.google\.com\//i.test(raw)) return 'google_drive';
            if (/https?:\/\/(?:1drv\.ms|onedrive\.live\.com)\//i.test(raw)) return 'onedrive';
            if (/https?:\/\/mega\.nz\//i.test(raw)) return 'mega';
            if (lowered.startsWith('http://') || lowered.startsWith('https://')) return 'link';
            return 'unknown';
        }

        function getEffectiveResourceLinkType(item) {
            const rawType = String(item?.link_type || '').trim().toLowerCase();
            const detected = detectResourceLinkTypeByUrl(item?.link_url || '');
            if (detected !== 'unknown') return detected;
            return rawType || 'unknown';
        }

        function getResourceRefreshTargetLabel(targetType) {
            const normalized = String(targetType || '').trim().toLowerCase();
            if (normalized === 'folder') return '目录';
            if (normalized === 'file') return '文件';
            if (normalized === 'mixed') return '混合';
            return '未指定';
        }

        function formatResourceSyncTime(value) {
            const ts = Number(value || 0);
            if (!ts) return '未同步';
            return formatTimeText(ts * 1000);
        }

        function formatFileSizeText(value) {
            let size = Number(value || 0);
            if (!Number.isFinite(size) || size <= 0) return '0 B';
            const units = ['B', 'KB', 'MB', 'GB', 'TB'];
            let unitIndex = 0;
            while (size >= 1024 && unitIndex < units.length - 1) {
                size /= 1024;
                unitIndex += 1;
            }
            const precision = unitIndex === 0 ? 0 : (size >= 100 ? 0 : size >= 10 ? 1 : 2);
            return `${size.toFixed(precision)} ${units[unitIndex]}`;
        }

        function formatShareModifiedAt(value) {
            const raw = String(value || '').trim();
            if (!raw) return '--';
            if (/^\d{10}$/.test(raw)) return formatTimeText(Number(raw) * 1000);
            if (/^\d{13}$/.test(raw)) return formatTimeText(Number(raw));
            return formatTimeText(raw);
        }

        function canOpenResourceImport(item) {
            const linkType = getEffectiveResourceLinkType(item);
            return !!String(item?.link_url || '').trim() && ['magnet', '115share'].includes(linkType);
        }

        function canImportResource(item) {
            return canOpenResourceImport(item) && !!resourceState.cookie_configured;
        }

        function getResourceImportLabel(item) {
            const linkType = getEffectiveResourceLinkType(item);
            if (!String(item?.link_url || '').trim()) return '暂无可导入链接';
            if (linkType === '115share') return '转存到 115';
            if (linkType === 'magnet') return '下载到 115';
            return '当前不可导入';
        }

        function getResourceCopyLabel(item) {
            return String(item?.link_url || '').trim() ? '复制链接' : '复制文案';
        }

        function findResourceItem(resourceId) {
            const target = Number(resourceId || 0);
            if (!target) return null;
            if (selectedResourceItem && Number(selectedResourceItem?.id || 0) === target) return selectedResourceItem;
            const direct = (resourceState.items || []).find(item => Number(item.id) === target);
            if (direct) return direct;
            for (const section of resourceState.channel_sections || []) {
                const found = getResourceSectionItems(section, '').find(item => Number(item.id) === target);
                if (found) return found;
            }
            const searchKeyword = String(resourceState.search || '').trim();
            for (const section of resourceState.search_sections || []) {
                const found = getResourceSectionItems(section, searchKeyword).find(item => Number(item.id) === target);
                if (found) return found;
            }
            return null;
        }

        function createTransientResourceItem(rawItem) {
            const item = rawItem && typeof rawItem === 'object' ? rawItem : {};
            const extra = item?.extra && typeof item.extra === 'object' ? item.extra : {};
            const resolvedReceiveCode = normalizeReceiveCodeInput(
                item?.receive_code
                || extra?.receive_code
                || extractReceiveCodeFromShareUrl(item?.link_url || '')
                || extractReceiveCodeFromText(item?.raw_text || '')
            );
            return {
                id: resourceTempIdSeed--,
                source_type: String(item?.source_type || 'manual').trim() || 'manual',
                source_name: String(item?.source_name || '').trim(),
                channel_name: String(item?.channel_name || '').trim(),
                title: String(item?.title || '未命名资源').trim() || '未命名资源',
                normalized_title: String(item?.normalized_title || '').trim(),
                raw_text: String(item?.raw_text || '').trim(),
                link_url: String(item?.link_url || '').trim(),
                link_type: String(item?.link_type || '').trim(),
                message_url: String(item?.message_url || '').trim(),
                quality: String(item?.quality || '').trim(),
                year: String(item?.year || '').trim(),
                published_at: String(item?.published_at || '').trim(),
                receive_code: resolvedReceiveCode,
                created_at: new Date().toISOString(),
                status: 'new',
                extra: {
                    cover_url: String(extra?.cover_url || '').trim(),
                    source_post_id: String(extra?.source_post_id || '').trim(),
                    source_url: String(extra?.source_url || '').trim(),
                    receive_code: resolvedReceiveCode
                },
                cover_url: String(item?.cover_url || extra?.cover_url || '').trim(),
                source_post_id: String(item?.source_post_id || extra?.source_post_id || '').trim(),
            };
        }

        function serializeTransientResourceForJob(item) {
            const resource = item && typeof item === 'object' ? item : {};
            return {
                source_type: String(resource?.source_type || 'manual').trim() || 'manual',
                source_name: String(resource?.source_name || '').trim(),
                channel_name: String(resource?.channel_name || '').trim(),
                title: String(resource?.title || '未命名资源').trim() || '未命名资源',
                normalized_title: String(resource?.normalized_title || '').trim(),
                raw_text: String(resource?.raw_text || '').trim(),
                link_url: String(resource?.link_url || '').trim(),
                link_type: String(resource?.link_type || '').trim(),
                message_url: String(resource?.message_url || '').trim(),
                quality: String(resource?.quality || '').trim(),
                year: String(resource?.year || '').trim(),
                published_at: String(resource?.published_at || '').trim(),
                receive_code: normalizeReceiveCodeInput(resource?.receive_code || resource?.extra?.receive_code || ''),
                extra: {
                    cover_url: String(resource?.cover_url || resource?.extra?.cover_url || '').trim(),
                    source_post_id: String(resource?.source_post_id || resource?.extra?.source_post_id || '').trim(),
                    source_url: String(resource?.extra?.source_url || '').trim(),
                    receive_code: normalizeReceiveCodeInput(resource?.receive_code || resource?.extra?.receive_code || '')
                }
            };
        }

        function getResourceItemIdentity(item) {
            const sourcePostId = String(item?.source_post_id || item?.extra?.source_post_id || '').trim();
            if (sourcePostId) return `post:${sourcePostId}`;
            const messageUrl = String(item?.message_url || '').trim();
            if (messageUrl) return `msg:${messageUrl}`;
            const linkUrl = String(item?.link_url || '').trim();
            if (linkUrl) return `link:${linkUrl}`;
            const id = Number(item?.id || 0);
            if (id) return `id:${id}`;
            return `title:${String(item?.title || '').trim()}|raw:${String(item?.raw_text || '').trim().slice(0, 120)}`;
        }

        function ensureResourceClientId(item) {
            const payload = item && typeof item === 'object' ? item : {};
            const numericId = Number(payload?.id || 0);
            if (numericId) return { ...payload, id: numericId };
            const identity = getResourceItemIdentity(payload);
            let clientId = resourceClientIdsByIdentity[identity];
            if (!clientId) {
                clientId = resourceClientIdSeed--;
                resourceClientIdsByIdentity = {
                    ...resourceClientIdsByIdentity,
                    [identity]: clientId
                };
            }
            return {
                ...payload,
                id: clientId
            };
        }

        function hydrateResourceItems(items) {
            return (Array.isArray(items) ? items : []).map(item => ensureResourceClientId(item));
        }

        function hydrateResourceSections(sections) {
            return (Array.isArray(sections) ? sections : []).map(section => ({
                ...section,
                items: hydrateResourceItems(section?.items || [])
            }));
        }

        function dedupeResourceItems(items) {
            const seen = new Set();
            const result = [];
            (Array.isArray(items) ? items : []).forEach(item => {
                const key = getResourceItemIdentity(item);
                if (!key || seen.has(key)) return;
                seen.add(key);
                result.push(item);
            });
            return result;
        }

        function getResourceItemSortScore(item) {
            const postCursor = Number(getResourceItemPostCursor(item) || 0);
            if (Number.isFinite(postCursor) && postCursor > 0) return postCursor;
            const publishedAt = Date.parse(item?.published_at || item?.created_at || '');
            if (Number.isFinite(publishedAt) && publishedAt > 0) return publishedAt;
            return Number(item?.id || 0);
        }

        function getResourceItemPostCursor(item) {
            const sourcePostId = String(item?.source_post_id || item?.extra?.source_post_id || '').trim();
            const sourceMatch = sourcePostId.match(/\/(\d+)$/);
            if (sourceMatch) return sourceMatch[1];
            const messageUrl = String(item?.message_url || '').trim();
            const urlMatch = messageUrl.match(/\/(\d+)(?:\?.*)?$/);
            return urlMatch ? urlMatch[1] : '';
        }

        function getResourceSectionPagingKey(channelId, searchKeyword = '') {
            const normalizedChannelId = normalizeTelegramChannelIdInput(channelId || '');
            if (!normalizedChannelId) return '';
            const keyword = String(searchKeyword || '').trim().toLowerCase();
            return keyword ? `search:${keyword}:${normalizedChannelId}` : `feed:${normalizedChannelId}`;
        }

        function getResourceSectionPagingMeta(section, searchKeyword = '') {
            const pagingKey = getResourceSectionPagingKey(section?.channel_id || '', searchKeyword);
            const sectionItems = Array.isArray(section?.items) ? section.items : [];
            const fallbackBefore = getResourceItemPostCursor(sectionItems[sectionItems.length - 1]);
            const sectionHasMore = typeof section?.has_more === 'boolean'
                ? section.has_more
                : Number(section?.item_count || 0) > sectionItems.length;
            return {
                key: pagingKey,
                loading: !!resourceChannelLoadingMore[pagingKey],
                nextBefore: String(resourceChannelNextBefore[pagingKey] || section?.next_before || fallbackBefore || '').trim(),
                noMore: Object.prototype.hasOwnProperty.call(resourceChannelNoMore, pagingKey)
                    ? !!resourceChannelNoMore[pagingKey]
                    : !sectionHasMore,
            };
        }

        function getResourceSectionItems(section, searchKeyword = '') {
            const channelId = normalizeTelegramChannelIdInput(section?.channel_id || '');
            const pagingKey = getResourceSectionPagingKey(channelId, searchKeyword);
            return dedupeResourceItems([
                ...(Array.isArray(section?.items) ? section.items : []),
                ...(Array.isArray(resourceChannelExtraItems[pagingKey]) ? resourceChannelExtraItems[pagingKey] : [])
            ]).sort((a, b) => getResourceItemSortScore(b) - getResourceItemSortScore(a));
        }

        function normalizeResourceStatusForDisplay(status) {
            const normalized = String(status || '').trim().toLowerCase();
            if (normalized === 'pending') return 'queued';
            if (normalized === 'running') return 'importing';
            return normalized || 'new';
        }

        function findMatchingResourceJob(item) {
            const itemKeys = uniquePreserveOrder([
                String(item?.source_post_id || item?.extra?.source_post_id || '').trim() ? `post:${String(item?.source_post_id || item?.extra?.source_post_id || '').trim()}` : '',
                String(item?.message_url || '').trim() ? `msg:${String(item?.message_url || '').trim()}` : '',
                String(item?.link_url || '').trim() ? `link:${String(item?.link_url || '').trim()}` : ''
            ].filter(Boolean));
            if (!itemKeys.length) return null;
            const jobs = Array.isArray(resourceState.jobs) ? resourceState.jobs : [];
            for (const job of jobs) {
                const jobKeys = new Set(uniquePreserveOrder([
                    String(job?.source_post_id || '').trim() ? `post:${String(job?.source_post_id || '').trim()}` : '',
                    String(job?.message_url || '').trim() ? `msg:${String(job?.message_url || '').trim()}` : '',
                    String(job?.link_url || '').trim() ? `link:${String(job?.link_url || '').trim()}` : ''
                ].filter(Boolean)));
                if (itemKeys.some(key => jobKeys.has(key))) return job;
            }
            return null;
        }

        function getResourceDisplayStatus(item) {
            const matchedJob = findMatchingResourceJob(item);
            if (matchedJob) {
                return normalizeResourceStatusForDisplay(matchedJob?.status);
            }
            return normalizeResourceStatusForDisplay(item?.status);
        }

        function getResourceCopyText(item) {
            return String(item?.link_url || item?.raw_text || item?.title || '').trim();
        }

        function getResourceIconSvg(kind) {
            if (kind === 'folder') {
                return `
                    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <path fill="currentColor" d="M3.75 6.75A2.25 2.25 0 0 1 6 4.5h3.172c.597 0 1.169.237 1.591.659l1.078 1.078c.14.14.33.22.53.22H18A2.25 2.25 0 0 1 20.25 8.7v.6H3.75v-2.55Z"/>
                        <path fill="currentColor" d="M3 10.8A1.8 1.8 0 0 1 4.8 9h14.4A1.8 1.8 0 0 1 21 10.8v4.95A3.75 3.75 0 0 1 17.25 19.5H6.75A3.75 3.75 0 0 1 3 15.75V10.8Z"/>
                    </svg>
                `;
            }
            return `
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path fill="currentColor" d="M7.5 3.75A2.25 2.25 0 0 0 5.25 6v12A2.25 2.25 0 0 0 7.5 20.25h9A2.25 2.25 0 0 0 18.75 18V8.56a2.25 2.25 0 0 0-.659-1.591l-2.56-2.56A2.25 2.25 0 0 0 13.94 3.75H7.5Z"/>
                    <path fill="rgba(15,23,42,0.18)" d="M14.25 3.9v3.6c0 .414.336.75.75.75h3.6"/>
                </svg>
            `;
        }

        function buildResourcePoster(item) {
            const title = escapeHtml(item?.title || '未命名资源');
            const sourceLabel = escapeHtml((item?.source_name || item?.channel_name || '资源').slice(0, 18) || '资源');
            const coverUrl = String(item?.cover_url || item?.extra?.cover_url || '').trim();
            if (!coverUrl) {
                return `<div class="resource-poster resource-placeholder">${sourceLabel}</div>`;
            }
            const proxyUrl = `/resource/image?url=${encodeURIComponent(coverUrl)}`;
            return `
                <div class="relative">
                    <img src="${proxyUrl}" alt="${title}" class="resource-poster" loading="lazy" onerror="this.classList.add('hidden');this.nextElementSibling.classList.remove('hidden')">
                    <div class="resource-poster resource-placeholder hidden">${sourceLabel}</div>
                </div>
            `;
        }

        function buildResourceEntryRow(entry, { showOpenButton = false, openActionPrefix = 'resource-folder' } = {}) {
            const isDir = !!entry?.is_dir;
            const normalizedOpenActionPrefix = String(openActionPrefix || 'resource-folder').replace(/[^a-z0-9-]/gi, '') || 'resource-folder';
            const normalizedEntryId = String(entry?.id || '').trim();
            const name = escapeHtml(entry?.name || '--');
            const idText = escapeHtml(isDir ? (entry?.id || '--') : (entry?.pick_code || entry?.sha1 || '--'));
            const meta = isDir
                ? (showOpenButton ? '文件夹' : `CID: ${idText}`)
                : `${escapeHtml(formatFileSizeText(entry?.size || 0))}${entry?.modified_at ? ` / ${escapeHtml(entry.modified_at)}` : ''}`;
            const actionHtml = showOpenButton && isDir
                ? `<button type="button" data-${normalizedOpenActionPrefix}-action="open" data-${normalizedOpenActionPrefix}-id="${escapeHtml(entry?.id || '')}" data-${normalizedOpenActionPrefix}-name="${name}" class="resource-entry-action shrink-0">进入</button>`
                : `<span class="resource-entry-flag shrink-0">${isDir ? '目录' : escapeHtml(formatFileSizeText(entry?.size || 0))}</span>`;
            return `
                <div class="resource-entry ${isDir ? 'resource-entry-dir' : 'resource-entry-file'}" data-resource-entry-id="${escapeHtml(normalizedEntryId)}">
                    <div class="resource-entry-main">
                        <span class="resource-entry-icon">${getResourceIconSvg(isDir ? 'folder' : 'file')}</span>
                        <div class="min-w-0">
                            <div class="resource-entry-name">${name}</div>
                            <div class="resource-entry-meta">${meta}</div>
                        </div>
                    </div>
                    ${actionHtml}
                </div>
            `;
        }

        function buildResourceMeta(item) {
            const tokens = [];
            const sourceName = String(item?.source_name || item?.channel_name || '频道资源').trim();
            if (sourceName) tokens.push(sourceName);
            if (item?.year) tokens.push(String(item.year));
            if (item?.quality) tokens.push(String(item.quality));
            const published = item?.published_at || item?.created_at || '';
            if (published) tokens.push(formatTimeText(published));
            return escapeHtml(tokens.join(' / ') || '暂无附加信息');
        }

        function buildResourceDescription(item) {
            const raw = String(item?.raw_text || item?.title || '').replace(/\s+/g, ' ').trim();
            return escapeHtml(raw || '暂无描述信息');
        }

        function buildResourceCard(item) {
            const importOpenable = canOpenResourceImport(item);
            const importClass = importOpenable ? 'resource-card-action-primary' : 'resource-card-action-secondary resource-card-action-disabled';
            const copyDisabled = String(item?.link_url || item?.raw_text || item?.title || '').trim() ? '' : 'resource-card-action-disabled';
            return `
                <article class="resource-card">
                    <button type="button" data-resource-action="preview" data-resource-id="${item.id}" class="resource-card-preview-trigger shrink-0">
                        ${buildResourcePoster(item)}
                    </button>
                    <div class="min-w-0">
                        <div class="flex items-start justify-between gap-3">
                            <div class="min-w-0">
                                <button type="button" data-resource-action="preview" data-resource-id="${item.id}" class="resource-card-title break-words text-left bg-transparent border-none p-0 hover:text-sky-700 transition-colors">${escapeHtml(item?.title || '未命名资源')}</button>
                                    <div class="flex flex-wrap items-center gap-2 mt-2">
                                        ${buildResourceStatusBadge(getResourceDisplayStatus(item))}
                                        <span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-100">${escapeHtml(getResourceLinkTypeLabel(getEffectiveResourceLinkType(item)))}</span>
                                        ${item?.quality ? `<span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/20">${escapeHtml(item.quality)}</span>` : ''}
                                        ${item?.year ? `<span class="text-[10px] px-3 py-1 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/20">${escapeHtml(item.year)}</span>` : ''}
                                    </div>
                            </div>
                            <button type="button" data-resource-action="subscribe" data-resource-id="${item.id}" class="resource-card-subscribe-btn shrink-0">转订阅</button>
                        </div>
                        <div class="resource-card-meta mt-3">${buildResourceMeta(item)}</div>
                        <div class="resource-card-desc mt-3">${buildResourceDescription(item)}</div>
                        <div class="resource-card-actions">
                            <button type="button" data-resource-action="preview" data-resource-id="${item.id}" class="resource-card-action-secondary">详情</button>
                            <button type="button" data-resource-action="copy" data-resource-id="${item.id}" class="resource-card-action-secondary ${copyDisabled}" ${copyDisabled ? 'disabled' : ''}>${escapeHtml(getResourceCopyLabel(item))}</button>
                            <button type="button" data-resource-action="import" data-resource-id="${item.id}" class="${importClass}" ${importOpenable ? '' : 'disabled'}>导入</button>
                        </div>
                    </div>
                </article>
            `;
        }

        function isResourceSectionCollapsed(channelId) {
            const normalized = normalizeTelegramChannelIdInput(channelId || '');
            return !!resourceSectionCollapsed[normalized];
        }

        function toggleResourceSection(channelId) {
            const normalized = normalizeTelegramChannelIdInput(channelId || '');
            if (!normalized) return;
            resourceSectionCollapsed = {
                ...resourceSectionCollapsed,
                [normalized]: !isResourceSectionCollapsed(normalized)
            };
            renderResourceBoard();
        }

        function syncResourceSourceSelect() {
            const select = document.getElementById('resource_manual_source');
            if (!select) return;
            const current = select.value || '__manual__';
            const options = ['<option value="__manual__">手动录入 / 未绑定频道</option>']
                .concat(getResourceSourcesForSelect().map((source, index) => {
                    const label = `${source.name || `频道 ${index + 1}`}${source.enabled ? '' : ' (停用)'}`;
                    return `<option value="${escapeHtml(source.name || '')}">${escapeHtml(label)}</option>`;
                }));
            select.innerHTML = options.join('');
            if ([...select.options].some(option => option.value === current)) select.value = current;
        }

        function resolveResourceMonitorTaskMatch(savepath) {
            const normalizedSavepath = normalizeRelativePathInput(savepath);
            const tasks = Array.isArray(resourceState.monitor_tasks) && resourceState.monitor_tasks.length
                ? resourceState.monitor_tasks
                : (monitorState.tasks || []);
            const mountPath = normalizeRemotePathInput(document.getElementById('mount_path')?.value || '/115');
            const fullPath = normalizeRemotePathInput(joinRelativePathInput(mountPath, normalizedSavepath));
            let matchedTask = null;
            let bestDepth = -1;
            tasks.forEach(task => {
                const scanPath = normalizeRemotePathInput(task.scan_path || '');
                if (!task?.name || !scanPath || scanPath === '/') return;
                const matches = fullPath === scanPath || fullPath.startsWith(`${scanPath}/`);
                if (!matches) return;
                const depth = scanPath.split('/').filter(Boolean).length;
                if (depth > bestDepth) {
                    bestDepth = depth;
                    matchedTask = task;
                }
            });
            return {
                savepath: normalizedSavepath,
                fullPath,
                task: matchedTask,
                taskName: matchedTask?.name || '',
                scanPath: normalizeRemotePathInput(matchedTask?.scan_path || ''),
            };
        }

        function syncResourceSavepathPreview(savepath = '') {
            const previewEl = document.getElementById('resource_job_savepath_preview');
            if (!previewEl) return;
            const normalizedSavepath = normalizeRelativePathInput(savepath);
            if (normalizedSavepath) {
                previewEl.textContent = normalizedSavepath;
            } else {
                previewEl.textContent = '请选择保存目录';
            }
        }

        function getResourceImportSelectionHint() {
            if (!isCurrentResource115Share()) return '当前资源会按完整内容导入。';
            if (!resourceState.cookie_configured) return '配置 115 Cookie 后可浏览分享目录并选择具体内容。';
            if (!resourceShareRootLoaded) return '分享目录载入后可选择需要保存的目录或文件。';

            const selectionState = getResourceShareSelectionState();
            const directCount = selectionState.selected_entries.length;
            if (!directCount) return '请选择需要保存的目录或文件。';
            if (selectionState.refresh_target_type === 'folder') return '当前选择单个目录，将优先定位到 savepath/目录名。';
            if (selectionState.refresh_target_type === 'file') return '当前选择单个文件，将按 savepath 刷新。';
            if (selectionState.refresh_target_type === 'mixed') return '当前为多选内容，将按 savepath 刷新。';
            return '当前会按保存目录执行刷新。';
        }

        function renderResourceImportBehaviorHint(savepath = '') {
            const hintEl = document.getElementById('resource_job_monitor_task_hint');
            if (!hintEl) return;

            const match = resolveResourceMonitorTaskMatch(savepath || document.getElementById('resource_job_savepath')?.value || '');
            if (!match.savepath) {
                hintEl.innerText = '请选择一个非根目录的 115 保存目录。';
                return;
            }

            const selectionHint = getResourceImportSelectionHint();
            const monitorHint = match.taskName
                ? `当前保存路径会映射到 OpenList 的 ${match.fullPath}，命中文件夹监控任务“${match.taskName}”，保存完成后会自动触发生成 strm。`
                : `当前保存路径会映射到 OpenList 的 ${match.fullPath}，未命中文件夹监控任务，保存后不会自动生成 strm。`;
            hintEl.innerText = `${selectionHint} ${monitorHint}`.trim();
        }

        function syncResourceMonitorTaskOptions(savepath = '') {
            const hiddenInput = document.getElementById('resource_job_monitor_task');
            const displayInput = document.getElementById('resource_job_monitor_task_display');
            const delayInput = document.getElementById('resource_job_refresh_delay_seconds');
            if (!hiddenInput || !displayInput || !delayInput) return;

            const match = resolveResourceMonitorTaskMatch(savepath);
            syncResourceSavepathPreview(match.savepath);

            if (!match.savepath) {
                hiddenInput.value = '';
                displayInput.textContent = '请先选择保存目录';
                delayInput.disabled = false;
                renderResourceImportBehaviorHint('');
                return;
            }

            hiddenInput.value = match.taskName;

            if (match.taskName) {
                displayInput.textContent = match.taskName;
            } else {
                displayInput.textContent = '当前目录不自动触发';
            }
            delayInput.disabled = false;

            renderResourceImportBehaviorHint(match.savepath);
            renderResourceImportSummary();
        }

        function renderResourceImportSummary() {
            const selectionCountEl = document.getElementById('resource-import-selection-count');
            const selectionState = getResourceShareSelectionState();
            const isShare = isCurrentResource115Share();
            let selectionText = '整条资源';

            if (isShare) {
                const directCount = selectionState.selected_entries.length;
                if (!directCount) {
                    selectionText = '未选择';
                } else if (directCount === 1) {
                    selectionText = `1 项 · ${getResourceRefreshTargetLabel(selectionState.refresh_target_type)}`;
                } else {
                    selectionText = `${directCount} 项 · 混合`;
                }
            }

            if (selectionCountEl) selectionCountEl.textContent = selectionText;
        }

        function syncResourceChannelPagingState() {
            const searchKeyword = String(resourceState.search || '').trim();
            const validKeys = new Set();
            (resourceState.channel_sections || []).forEach(section => {
                const key = getResourceSectionPagingKey(section?.channel_id || '', '');
                if (key) validKeys.add(key);
            });
            (resourceState.search_sections || []).forEach(section => {
                const key = getResourceSectionPagingKey(section?.channel_id || '', searchKeyword);
                if (key) validKeys.add(key);
            });
            [resourceChannelExtraItems, resourceChannelLoadingMore, resourceChannelNextBefore, resourceChannelNoMore].forEach(store => {
                Object.keys(store).forEach(key => {
                    if (!validKeys.has(key)) delete store[key];
                });
            });
        }

        async function loadMoreResourceChannelItems(channelId, searchKeyword = '') {
            const normalizedChannelId = normalizeTelegramChannelIdInput(channelId || '');
            const keyword = String(searchKeyword || '').trim();
            const pagingKey = getResourceSectionPagingKey(normalizedChannelId, keyword);
            if (!normalizedChannelId || !pagingKey || resourceChannelLoadingMore[pagingKey]) return null;
            const sectionPool = keyword ? (resourceState.search_sections || []) : (resourceState.channel_sections || []);
            const section = sectionPool.find(item => normalizeTelegramChannelIdInput(item?.channel_id || '') === normalizedChannelId);
            if (!section) return null;

            const currentItems = getResourceSectionItems(section, keyword);
            const meta = getResourceSectionPagingMeta(section, keyword);
            const before = String(meta.nextBefore || getResourceItemPostCursor(currentItems[currentItems.length - 1]) || '').trim();

            resourceChannelLoadingMore = {
                ...resourceChannelLoadingMore,
                [pagingKey]: true
            };
            renderResourceBoard();

            try {
                const res = await fetch('/resource/channels/more', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        channel_id: normalizedChannelId,
                        before,
                        limit: 10,
                        query: keyword
                    })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '获取更多资源失败');

                const incomingItems = hydrateResourceItems(Array.isArray(data.items) ? data.items : []);
                const mergedItems = dedupeResourceItems([
                    ...(Array.isArray(resourceChannelExtraItems[pagingKey]) ? resourceChannelExtraItems[pagingKey] : []),
                    ...incomingItems
                ]);
                resourceChannelExtraItems = {
                    ...resourceChannelExtraItems,
                    [pagingKey]: mergedItems
                };
                resourceChannelNextBefore = {
                    ...resourceChannelNextBefore,
                    [pagingKey]: String(data.next_before || '').trim()
                };
                resourceChannelNoMore = {
                    ...resourceChannelNoMore,
                    [pagingKey]: incomingItems.length === 0 || !String(data.next_before || '').trim()
                };
                const nextSectionPool = sectionPool.map(item => {
                    if (normalizeTelegramChannelIdInput(item?.channel_id || '') !== normalizedChannelId) return item;
                    const nextShownCount = dedupeResourceItems([
                        ...currentItems,
                        ...incomingItems
                    ]).length;
                    return {
                        ...item,
                        item_count: keyword
                            ? Math.max(Number(item?.item_count || 0), nextShownCount)
                            : Math.max(Number(item?.item_count || 0), Number(data.total_count || 0)),
                        next_before: String(data.next_before || '').trim(),
                        has_more: Boolean(data.has_more) && !!String(data.next_before || '').trim(),
                        last_error: ''
                    };
                });
                resourceState = {
                    ...resourceState,
                    items: keyword
                        ? dedupeResourceItems(nextSectionPool.flatMap(item => getResourceSectionItems(item, keyword)))
                        : resourceState.items,
                    channel_sections: keyword ? resourceState.channel_sections : nextSectionPool,
                    search_sections: keyword ? nextSectionPool : resourceState.search_sections,
                    stats: keyword
                        ? {
                            ...(resourceState.stats || {}),
                            filtered_item_count: nextSectionPool.reduce((sum, item) => sum + getResourceSectionItems(item, keyword).length, 0)
                        }
                        : resourceState.stats
                };
                const itemCountEl = document.getElementById('resource-item-count');
                if (itemCountEl) itemCountEl.innerText = String(Number(resourceState?.stats?.item_count || 0));
                renderResourceBoard();
                return data;
            } catch (e) {
                alert(`❌ ${e.message || '获取更多资源失败'}`);
                return null;
            } finally {
                resourceChannelLoadingMore = {
                    ...resourceChannelLoadingMore,
                    [pagingKey]: false
                };
                renderResourceBoard();
            }
        }

        function buildResourceSectionCard(section, { searchKeyword = '' } = {}) {
            const keyword = String(searchKeyword || '').trim();
            const isSearchSection = !!keyword;
            const sectionItems = getResourceSectionItems(section, keyword);
            const pagingMeta = getResourceSectionPagingMeta(section, keyword);
            const normalizedChannelId = normalizeTelegramChannelIdInput(section?.channel_id || '');
            const shownCount = sectionItems.length;
            const primaryBadge = isSearchSection
                ? `命中 ${shownCount} 条`
                : `最近 ${Math.min((Array.isArray(section.items) ? section.items.length : 0), 10)} 条`;
            const secondaryBadge = isSearchSection
                ? `${escapeHtml(String(section?.pages_scanned || 0))} 页搜索结果`
                : `首页缓存 ${escapeHtml(String(section.item_count || (section.items || []).length || 0))} 条`;
            const primaryType = getResourceLinkTypeLabel(section?.primary_link_type || section?.channel_profile?.primary_link_type || 'unknown');
            const latestPublishedAt = String(section?.latest_published_at || section?.channel_profile?.latest_published_at || '').trim();
            const subtleText = isSearchSection
                ? '当前按频道源分组展示命中结果，可继续获取更早匹配内容。'
                : `最近资源：${escapeHtml(latestPublishedAt ? formatTimeText(latestPublishedAt) : '--')} / 最近同步：${escapeHtml(formatResourceSyncTime(section.last_sync_at))}`;
            const footerText = isSearchSection
                ? `当前已显示 ${escapeHtml(String(shownCount))} 条命中结果。`
                : `当前已展开 ${escapeHtml(String(shownCount))} 条；首页缓存 ${escapeHtml(String(section.item_count || 0))} 条最新记录。`;
            const emptyText = isSearchSection
                ? '这个频道暂时没有可展示的命中结果。'
                : '这个频道还没有同步到资源，稍后再试一次同步。';

            return `
                <section class="resource-section-card" data-collapsed="${isResourceSectionCollapsed(section.channel_id) ? 'true' : 'false'}">
                    <div class="resource-section-header">
                        <button type="button" data-resource-section-toggle="${escapeHtml(section.channel_id || '')}" class="resource-section-header-main min-w-0 flex-1 text-left bg-transparent border-none p-0">
                            <div class="flex flex-wrap items-center gap-2">
                                <h4 class="text-lg font-black text-white">${escapeHtml(section.name || section.channel_id || '未命名频道')}</h4>
                                <span class="text-[11px] px-3 py-1 rounded-full bg-slate-800 text-slate-300 border border-slate-700">@${escapeHtml(section.channel_id || '--')}</span>
                                <span class="text-[11px] px-3 py-1 rounded-full bg-sky-500/10 text-sky-300 border border-sky-500/20">${primaryBadge}</span>
                                <span class="text-[11px] px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">${secondaryBadge}</span>
                                ${!isSearchSection ? `<span class="text-[11px] px-3 py-1 rounded-full bg-violet-500/10 text-violet-300 border border-violet-500/20">${escapeHtml(primaryType)}</span>` : ''}
                                ${!isSearchSection && section.last_error ? '<span class="text-[11px] px-3 py-1 rounded-full bg-rose-500/10 text-rose-300 border border-rose-500/20">同步异常</span>' : ''}
                            </div>
                            <div class="subtle mt-2">${subtleText}</div>
                        </button>
                        <div class="flex items-center gap-2 shrink-0">
                            <a href="${escapeHtml(section.url || '#')}" target="_blank" rel="noopener noreferrer" class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm font-bold border border-slate-700">打开频道</a>
                            <button type="button" data-resource-section-toggle="${escapeHtml(section.channel_id || '')}" class="resource-section-toggle bg-transparent border-none p-0">⌄</button>
                        </div>
                    </div>
                    <div class="resource-section-body">
                        ${!isSearchSection && section.last_error ? `<div class="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-5 text-sm text-rose-200 mb-4">频道同步失败：${escapeHtml(section.last_error || '未知错误')}</div>` : ''}
                        ${sectionItems.length
                            ? `<div class="resource-grid">${sectionItems.map(item => buildResourceCard(item)).join('')}</div>`
                            : `<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">${emptyText}</div>`
                        }
                        <div class="resource-section-footer">
                            <div class="resource-section-footer-text">${footerText}</div>
                            <button
                                type="button"
                                data-resource-load-more="${escapeHtml(normalizedChannelId)}"
                                class="resource-section-more-btn ${pagingMeta.loading ? 'btn-disabled' : ''}"
                                ${pagingMeta.loading || pagingMeta.noMore ? 'disabled' : ''}
                            >${pagingMeta.loading
                                ? '获取中...'
                                : (pagingMeta.noMore ? '没有更多资源了' : '获取更多资源')
                            }</button>
                        </div>
                    </div>
                </section>
            `;
        }

        function renderResourceBoard() {
            const container = document.getElementById('resource-board');
            if (!container) return;

            const activeKeyword = String(resourceState.search || '').trim();
            const isSearchMode = !!activeKeyword;
            const sections = (resourceState.channel_sections || []).filter(section => section.enabled !== false);
            if (isSearchMode) {
                const searchSections = (resourceState.search_sections || []).filter(section => section.enabled !== false);
                const filteredCount = Number(resourceState?.stats?.filtered_item_count ?? 0);
                const searchedSources = Number(resourceState?.search_meta?.searched_sources || 0);
                const searchErrors = Array.isArray(resourceState?.search_meta?.errors) ? resourceState.search_meta.errors : [];
                resourceBoardHintText = `频道内搜索：关键词「${activeKeyword}」 / 命中 ${filteredCount} 条${searchedSources ? ` / 已检索 ${searchedSources} 个订阅源` : ''}${searchErrors.length ? ` / ${searchErrors.length} 个频道暂未返回` : ''}`;
                if (!searchSections.length) {
                    container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">没有在已启用订阅频道里找到匹配内容。可以先同步频道，或直接粘贴 magnet / 常见网盘分享链接进入识别。</div>';
                    renderResourceBoardHint();
                    return;
                }
                const errorNote = searchErrors.length
                    ? `<div class="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-100">${escapeHtml(`以下频道本次未返回结果：${searchErrors.map(item => item?.name || item?.channel_id || '未命名频道').join('、')}`)}</div>`
                    : '';
                container.innerHTML = `${errorNote}${errorNote ? '<div class="h-4"></div>' : ''}${searchSections.map(section => buildResourceSectionCard(section, { searchKeyword: activeKeyword })).join('')}`;
                renderResourceBoardHint();
                return;
            }

            resourceBoardHintText = '';
            if (!sections.length) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">还没有可展示的频道资源。先在“参数配置”里添加频道，并执行一次同步即可。</div>';
                renderResourceBoardHint();
                return;
            }

            container.innerHTML = sections.map(section => buildResourceSectionCard(section, { searchKeyword: '' })).join('');
            renderResourceBoardHint();
        }

        function applyResourceState(data) {
            if (!data) return;
            const nextSources = Array.isArray(data.sources) ? data.sources : (resourceState.sources || []);
            const nextItems = hydrateResourceItems(Array.isArray(data.items) ? data.items : (resourceState.items || []));
            const nextJobs = Array.isArray(data.jobs) ? data.jobs : (resourceState.jobs || []);
            const nextStats = data.stats || {
                source_count: nextSources.length,
                item_count: Number(resourceState?.stats?.item_count || 0),
                filtered_item_count: nextItems.length,
                completed_job_count: Number(resourceState?.stats?.completed_job_count ?? 0),
                failed_job_count: Number(resourceState?.stats?.failed_job_count ?? 0),
            };
            resourceState = {
                ...resourceState,
                ...data,
                sources: nextSources,
                items: nextItems,
                jobs: nextJobs,
                channel_sections: hydrateResourceSections(Array.isArray(data.channel_sections) ? data.channel_sections : (resourceState.channel_sections || [])),
                channel_profiles: data.channel_profiles && typeof data.channel_profiles === 'object'
                    ? data.channel_profiles
                    : (resourceState.channel_profiles || {}),
                search_sections: hydrateResourceSections(Array.isArray(data.search_sections) ? data.search_sections : (resourceState.search_sections || [])),
                last_syncs: data.last_syncs || resourceState.last_syncs || {},
                monitor_tasks: Array.isArray(data.monitor_tasks) ? data.monitor_tasks : (resourceState.monitor_tasks || monitorState.tasks || []),
                stats: nextStats,
                search: typeof data.search === 'string' ? data.search : (resourceState.search || ''),
                search_meta: data.search_meta || resourceState.search_meta || {}
            };
            normalizeResourceSourceBulkSelections();
            syncResourceChannelPagingState();
            if (selectedResourceId) {
                const refreshedSelectedItem = findResourceItem(selectedResourceId);
                if (refreshedSelectedItem) selectedResourceItem = refreshedSelectedItem;
            }

            const stats = resourceState.stats || {};
            document.getElementById('resource-source-count').innerText = String(stats.source_count ?? resourceState.sources.length ?? 0);
            document.getElementById('resource-item-count').innerText = String(stats.item_count ?? 0);
            const jobCounts = getResourceJobCounts(resourceState.jobs || []);
            const completedCount = Number(stats.completed_job_count ?? jobCounts.completed ?? 0);
            const completedCountEl = document.getElementById('resource-completed-job-count');
            if (completedCountEl) completedCountEl.innerText = String(completedCount);
            syncResourceJobClearMenuState();
            document.getElementById('resource-cookie-hint').classList.toggle('hidden', !!resourceState.cookie_configured);
            syncResourceSourceSelect();
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceSources();
            renderResourceBoard();
            renderResourceJobs();
            syncResourceJobModalTrigger();
            syncResourceSearchClearButton();
            syncResourceActionButtons();
            renderResourceTgHealthStatus();
            if (selectedResourceItem) renderResourceModalLayout(selectedResourceItem);
            renderResourceShareBrowser();
            renderResourceTargetPreview();

        }

        function syncResourceSearchClearButton() {
            const input = document.getElementById('resource-search-input');
            const clearBtn = document.getElementById('resource-search-clear-btn');
            if (!input || !clearBtn) return;
            const hasValue = !!String(input.value || '').trim();
            clearBtn.classList.toggle('hidden', !hasValue);
            clearBtn.disabled = !hasValue;
            syncResourceActionButtons();
        }

        function syncResourceActionButtons() {
            const input = document.getElementById('resource-search-input');
            const searchBtn = document.getElementById('resource-search-btn');
            const syncBtn = document.getElementById('resource-sync-btn');
            const keyword = String(input?.value || resourceState.search || '').trim();
            const directImport = isDirectImportInput(keyword);

            if (searchBtn) {
                const blocked = resourceSearchBusy || resourceSyncBusy;
                searchBtn.disabled = blocked;
                searchBtn.classList.toggle('btn-disabled', blocked);
                searchBtn.classList.toggle('is-loading', resourceSearchBusy);
                searchBtn.setAttribute('aria-busy', resourceSearchBusy ? 'true' : 'false');
                searchBtn.textContent = resourceSearchBusy
                    ? (directImport ? '识别中...' : '搜索中...')
                    : '搜索';
            }

            if (syncBtn) {
                const blocked = resourceSyncBusy || resourceSearchBusy;
                syncBtn.disabled = blocked;
                syncBtn.classList.toggle('btn-disabled', blocked);
                syncBtn.classList.toggle('is-loading', resourceSyncBusy);
                syncBtn.setAttribute('aria-busy', resourceSyncBusy ? 'true' : 'false');
                syncBtn.textContent = resourceSyncBusy ? '同步中...' : '同步频道';
            }
            renderResourceBoardHint();
        }

        function resetResourceSearchResults() {
            resourceState = {
                ...resourceState,
                search: '',
                items: [],
                search_sections: [],
                search_meta: {},
                stats: {
                    ...(resourceState.stats || {}),
                    filtered_item_count: 0
                }
            };
            syncResourceChannelPagingState();
            renderResourceBoard();
        }

        async function refreshResourceState({ allowSearch = true, keywordOverride = null } = {}) {
            try {
                const activeKeyword = typeof keywordOverride === 'string'
                    ? keywordOverride.trim()
                    : String(resourceState.search || '').trim();
                const shouldSearchChannels = !!activeKeyword && !isDirectImportInput(activeKeyword) && allowSearch;
                const params = new URLSearchParams();
                if (shouldSearchChannels) params.set('q', activeKeyword);
                const endpoint = params.toString() ? `/resource/state?${params.toString()}` : '/resource/state';
                const res = await fetch(endpoint);
                if (!res.ok) return null;
                const data = await res.json();
                applyResourceState(data);
                return data;
            } catch (e) {
                return null;
            }
        }

        async function refreshResourceJobsOnly() {
            try {
                const res = await fetch('/resource/state');
                if (!res.ok) return null;
                const data = await res.json();
                const keptItems = Array.isArray(resourceState.items) ? resourceState.items : [];
                const keptSections = Array.isArray(resourceState.search_sections) ? resourceState.search_sections : [];
                const keptSearchMeta = resourceState.search_meta || {};
                const keptFilteredCount = Number(resourceState?.stats?.filtered_item_count || 0);
                applyResourceState({
                    ...data,
                    search: resourceState.search || '',
                    items: keptItems,
                    search_sections: keptSections,
                    search_meta: keptSearchMeta,
                    stats: {
                        ...(data?.stats || {}),
                        filtered_item_count: keptFilteredCount,
                    },
                });
                return data;
            } catch (e) {
                return null;
            }
        }

        function isDirectImportInput(value) {
            const raw = String(value || '').trim();
            if (!raw) return false;
            if (/magnet:\?xt=urn:btih:[a-z0-9]{32,40}/i.test(raw)) return true;
            if (/ed2k:\/\/[^\s<>'"]+/i.test(raw)) return true;
            if (/(?:^|[\s(（【\[])(?:https?:\/\/)?(?:115cdn|115|anxia)\.com\/s\/[a-z0-9]+(?:\?[^\s<>'"]*)?/i.test(raw)) return true;
            const links = raw.match(/https?:\/\/[^\s<>'"]+/gi) || [];
            return links.some(link => {
                const linkType = detectResourceLinkTypeByUrl(link);
                return linkType !== 'unknown' && linkType !== 'link';
            });
        }

        async function parseResourceInputFromSearch(rawText) {
            const res = await fetch('/resource/items/preview_text', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    raw_text: rawText
                })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                throw new Error(data.msg || '链接解析失败');
            }
            const items = Array.isArray(data.items) ? data.items : [];
            const preferred = items.find(item => canOpenResourceImport(item));
            if (!preferred) throw new Error('未在文本中识别到可导入的 magnet 或 115 分享链接');
            openResourceItemModal(createTransientResourceItem(preferred), 'import');
            return {
                inserted: 0,
                updated: 0,
                item: preferred
            };
        }

        async function searchResources() {
            const keyword = document.getElementById('resource-search-input')?.value?.trim() || '';
            if (resourceSearchBusy || resourceSyncBusy) return null;
            if (!keyword) {
                renderResourceBoard();
                return null;
            }
            const directImportMode = isDirectImportInput(keyword);
            const startedAt = performance.now();
            resourceSearchBusy = true;
            let latencyProbePromise = null;
            if (!directImportMode) {
                showResourceTgHealthLoading('search');
                latencyProbePromise = probeResourceTgLatency();
            }
            syncResourceActionButtons();
            try {
                if (directImportMode) {
                    if (String(resourceState.search || '').trim()) resetResourceSearchResults();
                    const result = await parseResourceInputFromSearch(keyword);
                    return result;
                }
                const data = await refreshResourceState({ allowSearch: true, keywordOverride: keyword });
                if (!data) throw new Error('搜索请求失败，请稍后重试');
                const latencyMs = await resolveResourceTgLatencyMs(latencyProbePromise);
                applyResourceTgHealthFromSearchResult(data, getActionElapsedMs(startedAt), latencyMs);
                return data;
            } catch (e) {
                if (!directImportMode) {
                    const latencyMs = await resolveResourceTgLatencyMs(latencyProbePromise);
                    applyResourceTgHealthFailure('search', getActionElapsedMs(startedAt), latencyMs);
                }
                alert(`❌ ${e.message || '搜索失败'}`);
                return null;
            } finally {
                resourceSearchBusy = false;
                syncResourceActionButtons();
                if (!resourceSyncBusy) renderResourceBoard();
            }
        }

        async function syncResourceChannels(force = false, { silent = false } = {}) {
            if (resourceSyncBusy || resourceSearchBusy) return null;
            const startedAt = performance.now();
            resourceSyncBusy = true;
            let latencyProbePromise = null;
            if (!silent) showResourceTgHealthLoading('sync');
            if (!silent) latencyProbePromise = probeResourceTgLatency();
            syncResourceActionButtons();
            try {
                const res = await fetch('/resource/channels/sync', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ force, limit: 10 })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.msg || '同步失败');
                await refreshResourceState();
                if (!silent) {
                    const latencyMs = await resolveResourceTgLatencyMs(latencyProbePromise);
                    applyResourceTgHealthFromSyncResult(data, getActionElapsedMs(startedAt), latencyMs);
                }
                return data;
            } catch (e) {
                if (!silent) {
                    const latencyMs = await resolveResourceTgLatencyMs(latencyProbePromise);
                    applyResourceTgHealthFailure('sync', getActionElapsedMs(startedAt), latencyMs);
                }
                return null;
            } finally {
                resourceSyncBusy = false;
                syncResourceActionButtons();
                if (!resourceSearchBusy) renderResourceBoard();
            }
        }

        function getResourceJobClearMeta(scope = 'completed') {
            const normalized = String(scope || 'completed').trim().toLowerCase();
            const jobCounts = getResourceJobCounts(resourceState.jobs || []);
            const completedCount = Number(resourceState?.stats?.completed_job_count ?? jobCounts.completed ?? 0);
            const failedCount = Number(resourceState?.stats?.failed_job_count ?? jobCounts.failed ?? 0);
            if (normalized === 'failed') {
                return {
                    scope: 'failed',
                    count: failedCount,
                    label: '失败',
                    emptyText: '当前没有可清空的失败导入记录',
                    confirmText: '将清空失败导入记录（不删除网盘文件；执行中/待处理任务不会清理）。继续吗？',
                };
            }
            if (normalized === 'terminal') {
                return {
                    scope: 'terminal',
                    count: completedCount + failedCount,
                    label: '已完成和失败',
                    emptyText: '当前没有可清空的已完成或失败导入记录',
                    confirmText: '将清空已完成和失败导入记录（不删除网盘文件；执行中/待处理任务不会清理）。继续吗？',
                };
            }
            return {
                scope: 'completed',
                count: completedCount,
                label: '已完成',
                emptyText: '当前没有可清空的已完成导入记录',
                confirmText: '将清空已完成导入记录（不删除网盘文件；执行中/待处理任务不会清理）。继续吗？',
            };
        }

        async function clearResourceJobs(scope = 'completed') {
            const meta = getResourceJobClearMeta(scope);
            closeResourceJobClearMenu();
            if (meta.count <= 0) {
                alert(meta.emptyText);
                return;
            }
            if (!confirm(meta.confirmText)) return;
            const res = await fetch('/resource/jobs/clear', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ scope: meta.scope })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) return alert(`❌ ${data.msg || '清空失败'}`);
            await refreshResourceState();
            const deleted = Number(data.deleted || 0);
            if (deleted > 0) {
                alert(`✅ 已清空 ${deleted} 条${meta.label}导入记录`);
            } else {
                alert(`✅ ${meta.emptyText}`);
            }
        }

        async function clearCompletedResourceJobs() {
            await clearResourceJobs('completed');
        }

        async function clearFailedResourceJobs() {
            await clearResourceJobs('failed');
        }

        async function clearTerminalResourceJobs() {
            await clearResourceJobs('terminal');
        }

        async function clearResourceSearch() {
            const input = document.getElementById('resource-search-input');
            if (!input) return;
            const hadKeyword = !!String(input.value || '').trim();
            input.value = '';
            syncResourceSearchClearButton();
            if (resourceState.search || hadKeyword) {
                resetResourceSearchResults();
                await refreshResourceState({ keywordOverride: '' });
            } else {
                renderResourceBoard();
            }
            input.focus();
        }

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

        function getResourceSourceSectionIndex() {
            const index = {};
            (Array.isArray(resourceState.channel_sections) ? resourceState.channel_sections : []).forEach(section => {
                const channelId = normalizeTelegramChannelIdInput(section?.channel_id || '');
                if (!channelId) return;
                index[channelId] = section;
            });
            return index;
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
                const activity = getResourceSourceActivityMeta(profile);
                const primaryType = getResourceSourcePrimaryLinkType(profile);
                const activityBucket = getResourceSourceActivityBucket(profile);
                const dominantTypes = sanitizeResourceLinkTypeList(profile?.dominant_link_types);
                const sourceTypes = getResourceSourceTypes(profile);
                return {
                    source,
                    index,
                    channelId,
                    channelUrl: String(source?.url || (channelId ? `https://t.me/s/${channelId}` : '')).trim(),
                    profile,
                    activity,
                    activityBucket,
                    primaryType,
                    dominantTypes,
                    sourceTypes,
                };
            });
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

        function openResourceSourceManagerModal() {
            switchTab('settings');
            resourceSourceManagerOpen = true;
            normalizeResourceSourceBulkSelections();
            showLockedModal('resource-source-manager-modal');
            renderResourceSourceManagerModal();
        }

        function closeResourceSourceManagerModal() {
            resourceSourceManagerOpen = false;
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

        function getFilteredResourceSourceViewList() {
            const sources = resourceState.sources || [];
            const sectionIndex = getResourceSourceSectionIndex();
            const list = getResourceSourceViewList(sources, sectionIndex);
            return list.filter(view => {
                if (!isResourceSourceVisibleByFilter(view.source, sectionIndex, resourceSourceFilter)) return false;
                if (!isResourceSourceVisibleByEnabled(view.source, resourceSourceEnabledFilter)) return false;
                if (!isResourceSourceVisibleByActivity(view.source, sectionIndex, resourceSourceActivityFilter)) return false;
                return true;
            });
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
                alert('请先在当前筛选结果中勾选要操作的频道');
                return;
            }
            const selectedSet = new Set(selectedIds);
            const nextSources = (resourceState.sources || []).map(source => {
                const channelId = getResourceSourceChannelId(source);
                if (!selectedSet.has(channelId)) return source;
                return { ...source, enabled: !!enabled };
            });
            try {
                await persistResourceSources(nextSources);
                renderResourceSourceManagerModal();
                alert(`✅ 已${enabled ? '启用' : '停用'} ${selectedIds.length} 个频道`);
            } catch (e) {
                alert(`❌ ${e.message}`);
            }
        }

        async function bulkDeleteResourceSources() {
            const selectedIds = getSelectedResourceSourceIdsInFiltered();
            if (!selectedIds.length) {
                alert('请先在当前筛选结果中勾选要删除的频道');
                return;
            }
            const ok = confirm(`将删除 ${selectedIds.length} 个频道，确定继续吗？`);
            if (!ok) return;
            const selectedSet = new Set(selectedIds);
            const nextSources = (resourceState.sources || []).filter(source => !selectedSet.has(getResourceSourceChannelId(source)));
            try {
                await persistResourceSources(nextSources);
                const nextSelected = { ...resourceSourceBulkSelected };
                selectedIds.forEach(channelId => {
                    delete nextSelected[channelId];
                });
                resourceSourceBulkSelected = nextSelected;
                renderResourceSourceManagerModal();
                alert(`✅ 已删除 ${selectedIds.length} 个频道`);
            } catch (e) {
                alert(`❌ ${e.message}`);
            }
        }

        function renderResourceSourceManagerModal() {
            const modal = document.getElementById('resource-source-manager-modal');
            if (!modal || !resourceSourceManagerOpen) return;

            const typeFiltersEl = document.getElementById('resource-source-manager-type-filters');
            const statusFiltersEl = document.getElementById('resource-source-manager-status-filters');
            const activityFiltersEl = document.getElementById('resource-source-manager-activity-filters');
            const hintEl = document.getElementById('resource-source-manager-filter-hint');
            const listEl = document.getElementById('resource-source-manager-list');
            const selectedCountEl = document.getElementById('resource-source-manager-selected-count');
            const resultEl = document.getElementById('resource-source-manager-test-result');
            const testBtn = document.getElementById('resource-source-manager-test-btn');
            const selectAllBtn = document.getElementById('resource-source-manager-select-all-btn');
            const invertBtn = document.getElementById('resource-source-manager-invert-btn');
            if (!typeFiltersEl || !statusFiltersEl || !activityFiltersEl || !hintEl || !listEl || !selectedCountEl || !resultEl || !testBtn || !selectAllBtn || !invertBtn) return;

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

            const filtered = sourceViews.filter(view => {
                if (!isResourceSourceVisibleByFilter(view.source, sectionIndex, resourceSourceFilter)) return false;
                if (!isResourceSourceVisibleByEnabled(view.source, resourceSourceEnabledFilter)) return false;
                if (!isResourceSourceVisibleByActivity(view.source, sectionIndex, resourceSourceActivityFilter)) return false;
                return true;
            });

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
            selectedCountEl.textContent = String(selectedInFiltered);
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

            if (resourceSourceTestBusy) {
                const total = Number(resourceSourceTestResult.total || sources.length || 0);
                const done = Number(resourceSourceTestResult.done || 0);
                const success = Number(resourceSourceTestResult.success || 0);
                const failed = Number(resourceSourceTestResult.failed || 0);
                const threads = Math.max(1, Number(resourceSourceTestResult.threads || 1));
                const lastName = String(resourceSourceTestResult.last_name || '').trim();
                resultEl.textContent = `测试中：${done}/${total}，成功 ${success}，失败 ${failed}，线程 ${threads}${lastName ? `，当前 ${lastName}` : ''}`;
            } else if (Number(resourceSourceTestResult.total || 0) > 0) {
                const threads = Math.max(1, Number(resourceSourceTestResult.threads || 1));
                const base = `测试完成：共 ${resourceSourceTestResult.total} 个频道，成功 ${resourceSourceTestResult.success || 0}，失败 ${resourceSourceTestResult.failed || 0}，线程 ${threads}。`;
                const firstError = String(resourceSourceTestResult.error || '').trim();
                resultEl.textContent = firstError ? `${base} 失败示例：${firstError}` : base;
            } else if (resourceSourceTestResult.error) {
                resultEl.textContent = `测试失败：${resourceSourceTestResult.error}`;
            } else {
                const defaultThreads = getCurrentTgChannelThreads();
                resultEl.textContent = `点击后会按当前配置并发测试频道分类（线程 ${defaultThreads}，每个频道采样 20 条）。`;
            }
            testBtn.disabled = resourceSourceTestBusy || sources.length <= 0;

            if (!filtered.length) {
                listEl.innerHTML = '<div class="resource-source-empty"><div class="resource-source-empty-title">当前筛选无结果</div><div class="resource-source-empty-copy">可以切换资源类型、启用状态或活跃时间范围。</div></div>';
                return;
            }

            listEl.innerHTML = filtered.map(view => {
                const checked = !!resourceSourceBulkSelected[view.channelId];
                const enabled = view.source.enabled !== false;
                const latest = String(view.profile?.latest_published_at || '').trim();
                const typeText = (Array.isArray(view.sourceTypes) ? view.sourceTypes : [])
                    .slice(0, 3)
                    .map(type => getResourceLinkTypeLabel(type))
                    .join(' / ');
                return `
                    <div class="resource-source-manager-row">
                        <label class="ui-checkbox">
                            <input type="checkbox" data-resource-source-bulk-toggle="${escapeHtml(view.channelId)}" ${checked ? 'checked' : ''}>
                            <span></span>
                        </label>
                        <div class="resource-source-manager-row-main">
                            <div class="resource-source-manager-row-title">
                                <span>${escapeHtml(view.source.name || view.channelId || '未命名频道')}</span>
                                <span class="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">@${escapeHtml(view.channelId || '--')}</span>
                                <span class="text-[10px] px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-200 border border-sky-500/20">${escapeHtml(getResourceLinkTypeLabel(view.primaryType))}</span>
                                <span class="text-[10px] px-2 py-0.5 rounded-full ${enabled ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20' : 'bg-slate-700 text-slate-300 border border-slate-600'}">${enabled ? '已启用' : '已停用'}</span>
                            </div>
                            <div class="resource-source-manager-row-meta">类型：${escapeHtml(typeText || getResourceLinkTypeLabel(view.primaryType || 'unknown'))} · 活跃度：${escapeHtml(getResourceSourceActivityBucketLabel(view.activityBucket))} · 最近发布时间 ${escapeHtml(latest ? formatTimeText(latest) : '--')}</div>
                        </div>
                        <div class="resource-source-manager-row-actions">
                            <button type="button" data-resource-source-manager-action="edit" data-source-index="${view.index}" class="resource-source-compact-btn">编辑</button>
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
                alert('当前没有可测试的频道');
                return;
            }

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
                            const res = await fetch('/resource/channels/classify', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({
                                    channel_id: item.channel_id,
                                    sample_size: 20,
                                }),
                            });
                            const data = await res.json();
                            if (!res.ok || !data.ok) throw new Error(data.msg || '分类测试失败');
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
            const totalEl = document.getElementById('resource-source-total-count');
            const enabledEl = document.getElementById('resource-source-enabled-count');
            const disabledEl = document.getElementById('resource-source-disabled-count');
            if (totalEl) totalEl.innerText = String(sources.length);
            if (enabledEl) enabledEl.innerText = String(enabledCount);
            if (disabledEl) disabledEl.innerText = String(disabledCount);
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
                document.getElementById('resource_source_enabled').checked = !!source.enabled;
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

        function buildResourceSourceExportPayload(sources = []) {
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

        async function exportResourceSources() {
            const payload = buildResourceSourceExportPayload(resourceState.sources || []);
            if (!payload.length) {
                alert('当前没有可导出的频道源');
                return;
            }
            const text = JSON.stringify(payload, null, 2);
            let copied = false;
            try {
                if (!navigator.clipboard?.writeText) throw new Error('当前浏览器不支持剪贴板接口');
                await navigator.clipboard.writeText(text);
                copied = true;
            } catch (e) {
                window.prompt('复制失败，请手动复制下面的频道源 JSON：', text);
            }
            const downloaded = downloadResourceSourceExportFile(text);
            if (copied && downloaded) {
                alert(`✅ 已导出 ${payload.length} 个频道（已复制到剪贴板，并下载 JSON 文件）`);
                return;
            }
            if (copied) {
                alert(`✅ 已导出 ${payload.length} 个频道（已复制到剪贴板）`);
                return;
            }
            if (downloaded) {
                alert(`✅ 已导出 ${payload.length} 个频道（已下载 JSON 文件）`);
            }
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

        function parseResourceSourceImportText(rawText) {
            const text = String(rawText || '').trim();
            if (!text) throw new Error('请先粘贴频道源 JSON');
            let payload = null;
            try {
                payload = JSON.parse(text);
            } catch (e) {
                throw new Error(`JSON 格式错误：${e.message}`);
            }
            if (!Array.isArray(payload)) throw new Error('导入内容必须是 JSON 数组');

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
                alert(`❌ ${e.message}`);
                return;
            }

            if (!parsed.sources.length) {
                const firstReasons = parsed.invalidReasons.slice(0, 5).join('\n');
                const reasonHint = firstReasons ? `\n\n示例问题：\n${firstReasons}` : '';
                alert(`❌ 没有识别到可导入的频道 ID${reasonHint}`);
                return;
            }

            const currentSources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            const replaceExisting = !!replaceEl?.checked;
            if (replaceExisting && currentSources.length) {
                const ok = confirm(`将覆盖当前 ${currentSources.length} 个频道源，继续导入吗？`);
                if (!ok) return;
            }

            const nextSources = replaceExisting
                ? parsed.sources
                : mergeResourceSourcesByChannel(currentSources, parsed.sources);

            setResourceSourceImportBusy(true);
            try {
                await persistResourceSources(nextSources);
                closeResourceSourceImportModal();
                const notes = [
                    `✅ 已导入 ${parsed.sources.length} 个频道`,
                ];
                if (replaceExisting) notes.push('已覆盖旧配置');
                else notes.push(`当前频道总数 ${nextSources.length}`);
                if (parsed.duplicateCount > 0) notes.push(`导入数据内重复 ${parsed.duplicateCount} 项已自动去重`);
                if (parsed.invalidReasons.length > 0) notes.push(`无效数据 ${parsed.invalidReasons.length} 项已跳过`);
                alert(notes.join('，'));
            } catch (e) {
                alert(`❌ ${e.message}`);
            } finally {
                setResourceSourceImportBusy(false);
            }
        }

        async function persistResourceSources(sources) {
            const res = await fetch('/resource/sources/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sources })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.msg || '保存频道源失败');
            applyResourceState({ ...resourceState, sources: data.sources || [] });
        }

        async function moveResourceSource(index, offset) {
            const sources = [...(resourceState.sources || [])];
            const nextIndex = index + offset;
            if (index < 0 || nextIndex < 0 || nextIndex >= sources.length) return;
            [sources[index], sources[nextIndex]] = [sources[nextIndex], sources[index]];
            try {
                await persistResourceSources(sources);
            } catch (e) {
                alert(`❌ ${e.message}`);
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
                await persistResourceSources(sources);
                return true;
            } catch (e) {
                alert(`❌ ${e.message}`);
                return false;
            }
        }

        async function saveResourceSource() {
            const source = currentResourceSourceFormData();
            const isEditing = editingResourceSourceIndex !== null && editingResourceSourceIndex >= 0;
            if (!source.name && !source.channel_id) return alert('请至少填写频道名称或频道 ID');
            if (!source.channel_id) return alert('频道 ID 不能为空，例如 QukanMovie');
            if (!isLikelyTelegramChannelId(source.channel_id)) {
                return alert('频道 ID 看起来不是有效的公开频道用户名。请填写 t.me 后面的公开频道标识，例如 QukanMovie，而不是备注名或过短的编号。');
            }
            const sources = [...(resourceState.sources || [])];
            if (editingResourceSourceIndex !== null && editingResourceSourceIndex >= 0) sources[editingResourceSourceIndex] = source;
            else sources.push(source);
            try {
                await persistResourceSources(sources);
                closeResourceSourceModal();
                alert(isEditing ? '✅ 频道订阅已更新' : '✅ 频道订阅已添加');
            } catch (e) {
                alert(`❌ ${e.message}`);
            }
        }

        function editResourceSource(index) {
            openResourceSourceModal(index);
        }

        async function deleteResourceSource(index) {
            const source = (resourceState.sources || [])[index];
            if (!source) return;
            const channelId = getResourceSourceChannelId(source);
            if (!confirm(`确定删除频道源“${source.name || channelId || '未命名频道'}”吗？`)) return;
            const sources = [...(resourceState.sources || [])];
            sources.splice(index, 1);
            try {
                await persistResourceSources(sources);
                if (editingResourceSourceIndex === index) closeResourceSourceModal();
            } catch (e) {
                alert(`❌ ${e.message}`);
            }
        }

        function renderResourceSources() {
            const container = document.getElementById('resource-source-list');
            const sources = resourceState.sources || [];
            if (!container) return;
            syncResourceSourceSummary();
            const sectionIndex = getResourceSourceSectionIndex();
            if (!sources.length) {
                container.innerHTML = `
                    <div class="resource-source-empty">
                        <div class="resource-source-empty-title">还没有频道订阅</div>
                        <div class="resource-source-empty-copy">从底部添加一个公开 TG 频道后，资源中心就会按这里的顺序展示对应内容。</div>
                    </div>
                `;
                return;
            }
            const rows = getResourceSourceViewList(sources, sectionIndex).map(view => {
                const moveUpDisabled = view.index === 0 ? 'btn-disabled' : '';
                const moveDownDisabled = view.index === sources.length - 1 ? 'btn-disabled' : '';
                const enabledLabel = view.source.enabled !== false ? '已启用' : '已停用';
                const latestPublished = String(view.profile?.latest_published_at || '').trim();
                return `
                    <div class="resource-source-compact-row">
                        <div class="resource-source-compact-main">
                            <div class="resource-source-compact-title">
                                <span class="resource-source-compact-name">${escapeHtml(view.source.name || `频道 ${view.index + 1}`)}</span>
                                <span class="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">#${view.index + 1}</span>
                                <span class="text-[10px] px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-200 border border-sky-500/20">${escapeHtml(getResourceLinkTypeLabel(view.primaryType))}</span>
                                <span class="text-[10px] px-2 py-0.5 rounded-full ${view.source.enabled !== false ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20' : 'bg-slate-700 text-slate-300 border border-slate-600'}">${enabledLabel}</span>
                            </div>
                            <div class="resource-source-compact-meta">@${escapeHtml(view.channelId || '--')} · ${escapeHtml(getResourceSourceActivityBucketLabel(view.activityBucket))} · 最近 ${escapeHtml(latestPublished ? formatTimeText(latestPublished) : '--')}</div>
                        </div>
                        <div class="resource-source-compact-actions">
                            <label class="ui-switch">
                                <input type="checkbox" data-resource-source-toggle="1" data-resource-source-index="${view.index}" ${view.source.enabled !== false ? 'checked' : ''}>
                                <span class="ui-switch-slider"></span>
                            </label>
                            <button type="button" data-resource-source-action="move-up" data-resource-source-index="${view.index}" class="resource-source-compact-btn ${moveUpDisabled}" ${view.index === 0 ? 'disabled' : ''}>上移</button>
                            <button type="button" data-resource-source-action="move-down" data-resource-source-index="${view.index}" class="resource-source-compact-btn ${moveDownDisabled}" ${view.index === sources.length - 1 ? 'disabled' : ''}>下移</button>
                            <button type="button" data-resource-source-action="edit" data-resource-source-index="${view.index}" class="resource-source-compact-btn">编辑</button>
                        </div>
                    </div>
                `;
            }).join('');
            container.innerHTML = `<div class="resource-source-compact-list">${rows}</div>`;
            renderResourceSourceManagerModal();
        }

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
            const summary = document.getElementById('resource-job-modal-summary');
            const counts = getResourceJobCounts(jobs);
            if (!container) return;

            const totalEl = document.getElementById('resource-job-stat-total');
            const activeEl = document.getElementById('resource-job-stat-active');
            const completedEl = document.getElementById('resource-job-stat-completed');
            const failedEl = document.getElementById('resource-job-stat-failed');
            if (totalEl) totalEl.innerText = String(counts.total);
            if (activeEl) activeEl.innerText = String(counts.active);
            if (completedEl) completedEl.innerText = String(counts.completed);
            if (failedEl) failedEl.innerText = String(counts.failed);

            renderResourceJobFilters(counts);

            if (summary) {
                if (!jobs.length) summary.innerText = '最近还没有导入记录。';
                else summary.innerText = `最近 ${counts.total} 条任务，处理中 ${counts.active} 条，已完成 ${counts.completed} 条${counts.failed ? `，失败 ${counts.failed} 条` : ''}`;
            }

            const visibleJobs = jobs.filter(job => isResourceJobVisible(job, resourceJobFilter));
            if (!visibleJobs.length) {
                container.innerHTML = `<div class="resource-job-card-empty">${escapeHtml(getResourceJobEmptyText(resourceJobFilter))}</div>`;
                return;
            }

            container.innerHTML = visibleJobs.map(job => {
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
                return `
                    <div class="resource-job-card">
                        <div class="resource-job-card-head">
                            <div class="min-w-0 flex-1">
                                <div class="flex flex-wrap items-center gap-2">
                                    <div class="resource-job-card-title">${escapeHtml(job.title || `任务 #${job.id}`)}</div>
                                    ${buildResourceStatusBadge(job.status)}
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
        }

        function syncResourceJobModalTrigger() {
            const btn = document.getElementById('resource-job-modal-toggle');
            const badge = document.getElementById('resource-job-modal-badge');
            if (!btn || !badge) return;
            const jobs = Array.isArray(resourceState.jobs) ? resourceState.jobs : [];
            const activeCount = jobs.filter(job => ['pending', 'running', 'submitted'].includes(String(job?.status || '').toLowerCase())).length;
            badge.textContent = String(activeCount);
            badge.classList.toggle('hidden', activeCount <= 0);
            btn.classList.toggle('border-sky-500', activeCount > 0);
            btn.classList.toggle('text-sky-100', activeCount > 0);
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
            resourceJobModalOpen = typeof force === 'boolean' ? force : !resourceJobModalOpen;
            modal.classList.toggle('hidden', !resourceJobModalOpen);
            if (!resourceJobModalOpen) closeResourceJobClearMenu();
            else syncResourceJobClearMenuState();
            syncResourceJobModalTrigger();
        }

        async function fetchResourceFolderData(cid = '0') {
            const res = await fetch(`/resource/115/folders?cid=${encodeURIComponent(String(cid || '0'))}`);
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.msg || '读取目录失败');
            return {
                entries: Array.isArray(data.entries) ? data.entries : [],
                summary: data.summary || {
                    folder_count: Array.isArray(data.folders) ? data.folders.length : 0,
                    file_count: Array.isArray(data.files) ? data.files.length : 0
                }
            };
        }

        async function createResourceFolder(cid = '0', name = '') {
            const res = await fetch('/resource/115/folders/create', {
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

        function resetResourceShareState() {
            resourceShareEntriesByParent = { '0': [] };
            resourceShareEntryIndex = {};
            resourceShareExpanded = {};
            resourceShareLoadingParents = {};
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
            return String(resourceModalLinkType || '').trim().toLowerCase() === '115share';
        }

        function syncResourceShareReceiveCodeSection() {
            const sectionEl = document.getElementById('resource-share-receive-code-section');
            const inputEl = document.getElementById('resource_share_receive_code');
            const applyBtnEl = document.getElementById('resource-share-receive-code-apply');
            const shouldShow = resourceModalMode === 'import' && isCurrentResource115Share();

            if (sectionEl) sectionEl.classList.toggle('hidden', !shouldShow);
            if (!shouldShow) return;

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
            if (!resourceState.cookie_configured || !selectedResourceItem) return;
            await loadResourceShareBranch(selectedResourceId, '0', { resetSelection: true });
        }

        async function fetchResourceShareData(resourceId, cid = '0') {
            const receiveCode = normalizeReceiveCodeInput(resourceShareReceiveCode);
            let res;
            if (Number(resourceId || 0) > 0) {
                const params = new URLSearchParams({
                    resource_id: String(resourceId || 0),
                    cid: String(cid || '0')
                });
                if (receiveCode) params.set('receive_code', receiveCode);
                res = await fetch(`/resource/115/share_entries?${params.toString()}`);
            } else {
                res = await fetch('/resource/115/share_entries_preview', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        cid,
                        link_url: String(selectedResourceItem?.link_url || '').trim(),
                        raw_text: String(selectedResourceItem?.raw_text || '').trim(),
                        receive_code: receiveCode
                    })
                });
            }
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.msg || '读取分享内容失败');
            return {
                entries: Array.isArray(data.entries) ? data.entries : [],
                summary: data.summary || { folder_count: 0, file_count: 0 },
                share: data.share || { title: '', share_code: '', receive_code: '', count: 0 }
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

        async function loadResourceShareBranch(resourceId, cid = '0', { resetSelection = false } = {}) {
            if (!resourceState.cookie_configured || !isCurrentResource115Share()) {
                renderResourceShareBrowser();
                return;
            }
            const branchId = String(cid || '0');
            const isRoot = branchId === '0';
            let currentToken = resourceShareRequestToken;
            if (isRoot) {
                if (resetSelection) {
                    resourceShareEntriesByParent = { '0': [] };
                    resourceShareEntryIndex = {};
                    resourceShareExpanded = {};
                    resourceShareLoadingParents = {};
                    resourceShareSelected = {};
                }
                resourceShareLoading = true;
                resourceShareError = '';
                resourceShareRequestToken += 1;
                currentToken = resourceShareRequestToken;
                resourceShareCurrentCid = '0';
                resourceShareTrail = [{ cid: '0', name: resourceShareInfo?.title || '分享根目录' }];
            }
            resourceShareLoadingParents[branchId] = true;
            renderResourceShareBrowser();
            try {
                const result = await fetchResourceShareData(resourceId, branchId);
                if (selectedResourceId !== Number(resourceId)) return;
                if (isRoot && currentToken !== resourceShareRequestToken) return;
                const entries = Array.isArray(result.entries) ? result.entries : [];
                resourceShareEntriesByParent[branchId] = entries;
                entries.forEach(entry => {
                    const normalized = buildResourceShareSelectableEntry(entry);
                    if (normalized.id) resourceShareEntryIndex[normalized.id] = { ...entry, ...normalized };
                });
                if (isRoot) {
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
                }
            } catch (e) {
                if (selectedResourceId !== Number(resourceId)) return;
                if (isRoot) {
                    resourceShareEntriesByParent = { '0': [] };
                    resourceShareEntryIndex = {};
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
                delete resourceShareLoadingParents[branchId];
                if (isRoot) resourceShareLoading = false;
                if (isRoot) syncResourceShareReceiveCodeSection();
                renderResourceShareBrowser();
            }
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
            const branchId = String(entry.cid || entry.id || '').trim();
            if (!branchId) return;
            resourceShareCurrentCid = branchId;
            resourceShareTrail = resourceShareTrail.concat([{ cid: branchId, name: String(entry.name || '未命名目录') }]);
            if (!Object.prototype.hasOwnProperty.call(resourceShareEntriesByParent, branchId)) {
                await loadResourceShareBranch(selectedResourceId, branchId);
                return;
            }
            renderResourceShareBrowser();
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

        function buildResourceShareRows(entries) {
            return (Array.isArray(entries) ? entries : []).map(entry => {
                const normalized = buildResourceShareSelectableEntry(entry);
                const directSelected = !!resourceShareSelected[normalized.id];
                const coveredByAncestor = !directSelected ? getResourceShareCoveredAncestor(normalized) : null;
                const effectiveSelected = directSelected || !!coveredByAncestor;
                const noteText = coveredByAncestor
                    ? `已由上级目录“${coveredByAncestor.name}”一并选择`
                    : (normalized.is_dir ? '展开后可继续选择子项' : '');
                return `
                    <div class="resource-browser-row">
                        <div class="resource-browser-name-cell">
                            <input
                                type="checkbox"
                                data-resource-share-check="1"
                                data-resource-share-id="${escapeHtml(normalized.id)}"
                                class="ui-checkbox ui-checkbox-sm"
                                ${effectiveSelected ? 'checked' : ''}
                                ${coveredByAncestor ? 'disabled' : ''}
                            >
                            <div class="resource-browser-entry-main">
                                <span class="${normalized.is_dir ? 'resource-browser-folder-icon' : 'resource-browser-file-icon'}">${getResourceIconSvg(normalized.is_dir ? 'folder' : 'file')}</span>
                                <div class="min-w-0">
                                    ${normalized.is_dir
                                        ? `<button type="button" data-resource-share-action="enter" data-resource-share-id="${escapeHtml(normalized.id)}" class="resource-browser-link resource-browser-entry-name">${escapeHtml(normalized.name || '--')}</button>`
                                        : `<div class="resource-browser-entry-name">${escapeHtml(normalized.name || '--')}</div>`
                                    }
                                    ${noteText ? `<div class="resource-browser-entry-sub">${escapeHtml(noteText)}</div>` : ''}
                                </div>
                            </div>
                        </div>
                        <div class="resource-browser-col-size">${normalized.is_dir ? '--' : escapeHtml(formatFileSizeText(entry?.size || 0))}</div>
                    </div>
                `;
            }).join('');
        }

        function renderResourceShareBrowser() {
            const card = document.getElementById('resource-share-browser-card');
            const treeEl = document.getElementById('resource-share-tree');
            const rootTitleEl = document.getElementById('resource-share-root-title');
            const currentCheckAllEl = document.getElementById('resource-share-current-check-all');
            if (!card || !treeEl || !rootTitleEl) return;

            const importMode = resourceModalMode === 'import';
            const isShare = isCurrentResource115Share();
            card.classList.toggle('hidden', !importMode);
            syncResourceShareReceiveCodeSection();
            if (!importMode) {
                renderResourceImportBehaviorHint();
                renderResourceImportSummary();
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
                renderResourceImportBehaviorHint();
                renderResourceImportSummary();
                return;
            }

            const currentEntries = getCurrentResourceShareEntries();
            const currentFolderLoading = !!resourceShareLoadingParents[resourceShareCurrentCid];
            const breadcrumbHtml = [
                '<span class="text-slate-400">当前路径</span>',
                '<span class="resource-browser-sep">/</span>',
                resourceShareTrail.length
                    ? '<button type="button" onclick="goResourceShareRoot()" class="resource-browser-crumb">根目录</button>'
                    : '<span class="resource-browser-crumb resource-browser-crumb-active">根目录</span>',
                ...resourceShareTrail.map((item, index) => {
                    const label = escapeHtml(item?.name || '分享根目录');
                    const sep = '<span class="resource-browser-sep">/</span>';
                    if (index === resourceShareTrail.length - 1) {
                        return `${sep}<span class="resource-browser-crumb resource-browser-crumb-active">${label}</span>`;
                    }
                    return `${sep}<button type="button" data-resource-share-action="trail" data-resource-share-index="${index}" class="resource-browser-crumb">${label}</button>`;
                })
            ].join(' ');
            rootTitleEl.innerHTML = breadcrumbHtml;

            if (resourceShareLoading || currentFolderLoading) {
                treeEl.innerHTML = '<div class="resource-browser-empty">正在读取 115 分享目录，请稍候...</div>';
            } else if (!resourceState.cookie_configured) {
                treeEl.innerHTML = '<div class="resource-browser-empty">当前未配置 115 Cookie，暂时无法读取分享目录。</div>';
            } else if (resourceShareError) {
                treeEl.innerHTML = `<div class="resource-browser-empty text-red-300">${escapeHtml(resourceShareError)}</div>`;
            } else if (!resourceShareRootLoaded) {
                treeEl.innerHTML = '<div class="resource-browser-empty">这里会显示分享里的目录列表，你可以进入文件夹后再勾选具体内容。</div>';
            } else if (!currentEntries.length) {
                treeEl.innerHTML = '<div class="resource-browser-empty">这个目录下暂时没有可转存的内容。</div>';
            } else {
                treeEl.innerHTML = buildResourceShareRows(currentEntries);
            }

            const selectedInCurrentCount = currentEntries.filter(entry => isResourceShareEntryEffectivelySelected(entry)).length;
            if (currentCheckAllEl) {
                currentCheckAllEl.disabled = !currentEntries.length || !resourceState.cookie_configured || !!resourceShareError || resourceShareLoading || currentFolderLoading;
                currentCheckAllEl.checked = !!currentEntries.length && selectedInCurrentCount === currentEntries.length;
                currentCheckAllEl.indeterminate = selectedInCurrentCount > 0 && selectedInCurrentCount < currentEntries.length;
            }

            renderResourceImportBehaviorHint();
            renderResourceImportSummary();
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
                const result = await fetchResourceFolderData(parentCid);
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
                const result = await fetchResourceFolderData(parentCid);
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
            if (!resourceState.cookie_configured) return true;
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
                    const detail = e?.message || '读取 115 目录失败';
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
            const pathEl = document.getElementById('resource-target-preview-path');
            const summaryEl = document.getElementById('resource-target-preview-summary');
            const listEl = document.getElementById('resource-target-preview-list');
            if (!pathEl || !summaryEl || !listEl) return;

            pathEl.innerText = document.getElementById('resource_job_folder_path')?.value?.trim() || '根目录';
            if (!resourceState.cookie_configured) {
                summaryEl.innerText = '配置 115 Cookie 后可预览目标目录下的文件夹和文件内容。';
                listEl.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前未配置 115 Cookie，暂时无法读取目标目录内容。</div>';
                return;
            }
            if (resourceTargetPreviewLoading) {
                summaryEl.innerText = '正在读取目标目录内容...';
                listEl.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在加载目标目录内容...</div>';
                return;
            }
            if (resourceTargetPreviewError) {
                summaryEl.innerText = '目标目录内容读取失败';
                listEl.innerHTML = `<div class="rounded-2xl border border-dashed border-red-500/20 bg-red-500/10 p-6 text-center text-red-300 text-sm">${escapeHtml(resourceTargetPreviewError)}</div>`;
                return;
            }
            const folderCount = Number(resourceTargetPreviewSummary?.folder_count || 0);
            const fileCount = Number(resourceTargetPreviewSummary?.file_count || 0);
            summaryEl.innerText = `当前目录下共有 ${folderCount} 个文件夹 / ${fileCount} 个文件。`;
            if (!resourceTargetPreviewEntries.length) {
                listEl.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前目录为空，你可以直接把资源保存到这里。</div>';
                return;
            }
            listEl.innerHTML = resourceTargetPreviewEntries.map(entry => buildResourceEntryRow(entry)).join('');
        }

        async function loadResourceTargetPreview(folderId = '0', { force = false } = {}) {
            if (!resourceState.cookie_configured) {
                resourceTargetPreviewEntries = [];
                resourceTargetPreviewSummary = { folder_count: 0, file_count: 0 };
                resourceTargetPreviewLoading = false;
                resourceTargetPreviewError = '';
                renderResourceTargetPreview();
                return;
            }
            if (!force && resourceTargetPreviewLoading) return;
            resourceTargetPreviewLoading = true;
            resourceTargetPreviewError = '';
            renderResourceTargetPreview();
            try {
                const result = await fetchResourceFolderData(folderId);
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
            if (!titleEl || !detailGrid || !rawCard || !savePanel || !saveHintEl || !footer || !submitBtn || !closeBtn) return;

            titleEl.innerText = importMode ? '导入资源' : '资源详情';
            detailGrid.className = importMode ? 'resource-import-layout' : 'grid grid-cols-1 gap-4';
            rawCard.classList.toggle('hidden', importMode);
            savePanel.classList.toggle('hidden', !importMode);
            closeBtn.innerText = importMode ? '取消' : '关闭';

            const canOpenImport = canOpenResourceImport(item);
            const canSubmit = canImportResource(item);
            const showPrimaryAction = importMode ? true : canOpenImport;
            footer.className = showPrimaryAction ? 'grid grid-cols-1 md:grid-cols-2 gap-3 pt-2' : 'grid grid-cols-1 gap-3 pt-2';
            submitBtn.classList.toggle('hidden', !showPrimaryAction);
            submitBtn.onclick = importMode
                ? submitResourceJob
                : (() => openResourceImportModal(item?.id));
            if (importMode) {
                submitBtn.disabled = !canSubmit;
                submitBtn.className = canSubmit
                    ? 'bg-emerald-600 hover:bg-emerald-500 rounded-xl py-3 font-bold text-white'
                    : 'bg-slate-700 rounded-xl py-3 font-bold text-slate-400 btn-disabled';
            } else {
                submitBtn.disabled = !canOpenImport;
                submitBtn.className = canOpenImport
                    ? 'bg-emerald-600 hover:bg-emerald-500 rounded-xl py-3 font-bold text-white'
                    : 'bg-slate-700 rounded-xl py-3 font-bold text-slate-400 btn-disabled';
            }
            submitBtn.innerText = getResourceImportLabel(item);

            if (!importMode) {
                saveHintEl.classList.add('hidden');
                saveHintEl.innerHTML = '';
                return;
            }

            const hints = [];
            if (!canOpenResourceImport(item)) {
                hints.push('当前资源没有可直接导入的 magnet 或 115 分享链接。');
            } else {
                if (!resourceState.cookie_configured) {
                    hints.push('还没有配置 115 Cookie。你可以先查看并填写保存资源和保存目录，但真正提交前需要先补上 Cookie。');
                }
                const taskCount = Array.isArray(resourceState.monitor_tasks) && resourceState.monitor_tasks.length
                    ? resourceState.monitor_tasks.length
                    : ((monitorState.tasks || []).length || 0);
                if (!taskCount) {
                    hints.push('当前还没有配置文件夹监控任务。保存到 115 仍然可用，但不会自动生成 strm。');
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
            if (resourceModalMode === 'import' && resourceState.cookie_configured) {
                void ensureResourceFolderSelectionValid({ phase: 'open' });
            }
            if (resourceModalMode === 'import' && resourceModalLinkType === '115share' && resourceState.cookie_configured) {
                loadResourceShareBranch(selectedResourceId, '0', { resetSelection: true });
            }
        }

        function openResourceModal(resourceId, mode = 'detail') {
            const item = findResourceItem(resourceId);
            if (!item) return;
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
            resetResourceShareState();
            hideLockedModal('resource-import-modal');
        }

        async function submitResourceJob() {
            if (!selectedResourceItem) return alert('未选择资源');
            const selectionState = getResourceShareSelectionState();
            if (isCurrentResource115Share() && resourceShareRootLoaded && !selectionState.selected_ids.length) {
                return alert('请先至少勾选一个要转存的目录或文件');
            }
            let receiveCode = '';
            if (isCurrentResource115Share()) {
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
                return alert('请先选择一个非根目录的 115 保存目录');
            }
            const refreshDelaySeconds = normalizeResourceRefreshDelaySeconds(
                document.getElementById('resource_job_refresh_delay_seconds').value,
                0
            );
            const payload = {
                savepath,
                refresh_delay_seconds: refreshDelaySeconds,
                auto_refresh: true
            };
            if (Number(selectedResourceId || 0) > 0) payload.resource_id = selectedResourceId;
            else payload.resource = serializeTransientResourceForJob(selectedResourceItem);
            if (isCurrentResource115Share()) {
                payload.share_selection = selectionState;
                if (receiveCode) payload.receive_code = receiveCode;
            }
            const res = await fetch('/resource/jobs/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                showToast(`提交失败：${data.msg || '请稍后重试'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
                return;
            }
            rememberResourceRefreshDelaySeconds(refreshDelaySeconds);
            closeResourceJobModal();
            await refreshResourceState();
            const matchedTaskName = String(data.monitor_task_name || '').trim();
            const tail = matchedTaskName
                ? (data.auto_refresh ? `，保存完成后会自动触发“${matchedTaskName}”` : `，已匹配“${matchedTaskName}”，可稍后手动触发刷新`)
                : '，当前目录不会自动生成 strm';
            showToast(`已创建导入任务 #${data.job_id}${tail}`, { tone: 'success', duration: 3000, placement: 'top-center' });
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
            const container = document.getElementById('resource-folder-list');
            const summary = document.getElementById('resource-folder-summary');
            if (!container) return;
            if (summary) {
                summary.innerText = `当前目录下共有 ${Number(resourceFolderSummary?.folder_count || 0)} 个文件夹 / ${Number(resourceFolderSummary?.file_count || 0)} 个文件。`;
            }
            if (resourceFolderLoading) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在读取 115 目录...</div>';
                return;
            }
            if (!resourceFolderEntries.length) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前目录为空，可以直接选择这里作为保存位置。</div>';
                return;
            }
            container.innerHTML = resourceFolderEntries.map(entry => buildResourceEntryRow(entry, { showOpenButton: true })).join('');
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
            const container = document.getElementById('resource-folder-breadcrumbs');
            if (!container) return;
            container.innerHTML = resourceFolderTrail.map((item, index) => {
                const isLast = index === resourceFolderTrail.length - 1;
                return `
                    ${index > 0 ? '<span class="resource-folder-sep">›</span>' : ''}
                    <button
                        type="button"
                        data-resource-folder-action="trail"
                        data-resource-folder-index="${index}"
                        class="resource-folder-crumb ${isLast ? 'resource-folder-crumb-active' : ''}"
                        ${isLast ? 'disabled' : ''}
                    >${escapeHtml(item?.name || '根目录')}</button>
                `;
            }).join('');
        }

        async function loadResourceFolders(cid = '0') {
            resourceFolderLoading = true;
            renderResourceFolderBreadcrumbs();
            renderResourceFolderList();
            try {
                const result = await fetchResourceFolderData(cid);
                resourceFolderEntries = result.entries;
                resourceFolderSummary = result.summary;
            } catch (e) {
                resourceFolderEntries = [];
                resourceFolderSummary = { folder_count: 0, file_count: 0 };
                showToast(`目录读取失败：${e.message || '请稍后重试'}`, { tone: 'error', duration: 3200 });
            } finally {
                resourceFolderLoading = false;
                renderResourceFolderBreadcrumbs();
                renderResourceFolderList();
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
                const result = await createResourceFolder(currentCid, folderName);
                const folder = result.folder || {};
                const createdFolderId = String(folder.id || '').trim();
                const createdFolderName = String(folder.name || folderName).trim() || folderName;
                if (nameInput) nameInput.value = '';

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
            if (!container) return;
            if (summary) {
                summary.innerText = `当前目录下共有 ${Number(subscriptionFolderSummary?.folder_count || 0)} 个文件夹 / ${Number(subscriptionFolderSummary?.file_count || 0)} 个文件。`;
            }
            if (subscriptionFolderLoading) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在读取 115 目录...</div>';
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

        async function loadSubscriptionFolders(cid = '0') {
            subscriptionFolderLoading = true;
            renderSubscriptionFolderBreadcrumbs();
            renderSubscriptionFolderList();
            try {
                const result = await fetchResourceFolderData(cid);
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

        async function openSubscriptionFolderModal() {
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
                const result = await createResourceFolder(currentCid, folderName);
                const folder = result.folder || {};
                const createdFolderId = String(folder.id || '').trim();
                const createdFolderName = String(folder.name || folderName).trim() || folderName;
                if (nameInput) nameInput.value = '';

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

        async function triggerResourceJobRefresh(jobId) {
            const res = await fetch('/resource/jobs/refresh', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ job_id: jobId })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) return alert(`❌ ${data.msg || '触发刷新失败'}`);
            await refreshResourceState();
            if (isMonitorPageVisible()) refreshMonitorUserscriptJobs(true);
            alert('✅ 已触发文件夹监控任务');
        }

        async function triggerResourceJobCancel(jobId) {
            if (!confirm('确定要取消这个导入任务吗？')) return;
            const res = await fetch('/resource/jobs/cancel', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ job_id: jobId })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                showToast(`取消失败：${data.msg || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return;
            }
            await refreshResourceState();
            if (isMonitorPageVisible()) refreshMonitorUserscriptJobs(true);
            showToast(`任务 #${jobId} 已取消`, { tone: 'success', duration: 2600, placement: 'top-center' });
        }

        async function triggerResourceJobRetry(jobId) {
            const res = await fetch('/resource/jobs/retry', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ job_id: jobId })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                showToast(`重试失败：${data.msg || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return;
            }
            await refreshResourceState();
            if (isMonitorPageVisible()) refreshMonitorUserscriptJobs(true);
            showToast(`已创建重试任务 #${Number(data.job_id || 0) || '--'}`, { tone: 'success', duration: 2800, placement: 'top-center' });
        }

        function showVersionBanner(latest) {
            if (!latest) return;
            const banner = document.getElementById('version-banner');
            if (!banner) return;
            const textEl = document.getElementById('version-banner-text');
            const noteEl = document.getElementById('version-banner-notes');
            const linkEl = document.getElementById('version-banner-link');
            const fromVer = normalizeVersionLabel(versionInfo?.local?.version || 'dev');
            const toVer = latest.version ? normalizeVersionLabel(latest.version) : '';
            if (textEl) textEl.textContent = toVer ? `${fromVer} -> ${toVer} 可更新` : '检测到可用更新';
            if (noteEl) {
                const notes = getVersionNotes();
                noteEl.textContent = notes.length ? notes[0] : '建议先在「关于」页查看更新说明，再执行升级。';
            }
            if (linkEl) linkEl.href = getChangelogUrl();
            banner.classList.remove('hidden');
        }

        function hideVersionBanner() {
            const banner = document.getElementById('version-banner');
            if (banner) banner.classList.add('hidden');
        }

        function dismissVersionBanner() {
            versionBannerDismissed = true;
            hideVersionBanner();
        }

        async function refreshVersionInfo(force = false) {
            try {
                const endpoint = force ? '/version?refresh=1' : '/version';
                const res = await fetch(endpoint);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                versionInfo = {
                    ...versionInfo,
                    ...data,
                    error: data?.error || ''
                };
                renderVersionInfoPanel();
                if (!versionBannerDismissed && versionInfo.has_update) {
                    showVersionBanner(versionInfo.latest || {});
                } else if (!versionInfo.has_update) {
                    hideVersionBanner();
                    versionBannerDismissed = false;
                }
            } catch (err) {
                console.warn('Version refresh failed', err);
                versionInfo = {
                    ...versionInfo,
                    error: err instanceof Error ? err.message : String(err || 'unknown error')
                };
                renderVersionInfoPanel();
            }
        }

        async function manualVersionCheck() {
            const btn = document.getElementById('about-check-btn');
            const hintEl = document.getElementById('about-version-hint');
            const originalText = btn ? btn.textContent : '';
            if (btn) {
                btn.disabled = true;
                btn.classList.add('btn-disabled');
                btn.textContent = '检查中...';
            }
            await refreshVersionInfo(true);
            if (hintEl) {
                if (versionInfo?.error) {
                    hintEl.textContent = `手动检查失败：${versionInfo.error}`;
                } else if (versionInfo?.has_update) {
                    const latest = normalizeVersionLabel(versionInfo?.latest?.version || '');
                    hintEl.textContent = latest ? `手动检查完成，发现可用更新 ${latest}。` : '手动检查完成，发现可用更新。';
                } else {
                    hintEl.textContent = '手动检查完成，当前已是最新版本。';
                }
            }
            if (btn) {
                btn.disabled = false;
                btn.classList.remove('btn-disabled');
                btn.textContent = originalText || '手动检查更新';
            }
        }

        async function init() {
            try {
                const res = await fetch('/get_settings');
                if (!res.ok) return;
                const cfg = await res.json();

                Object.keys(cfg).forEach(k => {
                    const el = document.getElementById(k);
                    if (el && k !== 'trees') {
                        if (el.type === 'checkbox') el.checked = cfg[k];
                        else el.value = cfg[k];
                    }
                });
                const tgThreadsInput = document.getElementById('tg_channel_threads');
                if (tgThreadsInput) {
                    const rawTgThreads = parseInt(cfg.tg_channel_threads || '', 10);
                    tgThreadsInput.value = String(Math.min(20, Math.max(1, Number.isFinite(rawTgThreads) ? rawTgThreads : 6)));
                }

                const container = document.getElementById('trees-container');
                container.innerHTML = '';
                if (cfg.trees && cfg.trees.length > 0) cfg.trees.forEach(t => addTreeRow(t));
                else addTreeRow();

                applyMonitorState({ ...monitorState, tasks: cfg.monitor_tasks || [] }, { forceRender: true });
                applySubscriptionState({ ...subscriptionState, tasks: cfg.subscription_tasks || [] }, { forceRender: true });
                applyResourceState({
                    ...resourceState,
                    sources: cfg.resource_sources || [],
                    monitor_tasks: cfg.monitor_tasks || [],
                    cookie_configured: !!String(cfg.cookie_115 || '').trim()
                });
                renderTgProxyTestStatus();
                resetMonitorForm();
                resetSubscriptionForm();
                resetResourceSourceForm();
                syncResourceSourceSelect();
                refreshWebhookHint();
                renderVersionInfoPanel();
            } catch (e) {}
        }

        document.getElementById('monitor_name').addEventListener('input', refreshWebhookHint);
        ['subscription_title'].forEach(id => {
            document.getElementById(id).addEventListener('keydown', async (e) => {
                if (e.key !== 'Enter' || e.isComposing) return;
                e.preventDefault();
                await saveSubscriptionTask();
            });
        });
        document.getElementById('subscription_tmdb_search_keyword').addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter' || e.isComposing) return;
            e.preventDefault();
            await searchSubscriptionTmdbBinding();
        });
        document.getElementById('subscription_media_type').addEventListener('change', () => {
            syncSubscriptionTypeUI();
        });
        document.getElementById('subscription_season').addEventListener('change', () => {
            suggestSubscriptionTotalEpisodesFromTmdb({ force: false });
            renderSubscriptionTmdbBinding();
        });
        document.getElementById('subscription_anime_mode').addEventListener('change', () => {
            syncSubscriptionTypeUI({ forceSuggestTotal: true });
        });
        ['resource_source_name', 'resource_source_channel'].forEach(id => {
            document.getElementById(id).addEventListener('keydown', async (e) => {
                if (e.key !== 'Enter' || e.isComposing) return;
                e.preventDefault();
                await saveResourceSource();
            });
        });
        document.getElementById('resource_source_import_json').addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter' || e.isComposing || (!e.metaKey && !e.ctrlKey)) return;
            e.preventDefault();
            await importResourceSources();
        });
        document.getElementById('resource-search-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') searchResources();
        });
        document.getElementById('resource-search-input').addEventListener('input', async (e) => {
            syncResourceSearchClearButton();
            if (String(e.target?.value || '').trim()) return;
            if (String(resourceState.search || '').trim()) {
                resetResourceSearchResults();
                await refreshResourceState({ keywordOverride: '' });
                return;
            }
            renderResourceBoard();
        });
        document.getElementById('resource-job-modal-toggle').addEventListener('click', () => {
            toggleResourceJobModal();
        });
        document.getElementById('resource-source-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-source-action]');
            if (!btn) return;
            const action = btn.dataset.resourceSourceAction || '';
            const index = parseInt(btn.dataset.resourceSourceIndex || '-1', 10);
            if (index < 0) return;
            if (action === 'move-up') await moveResourceSource(index, -1);
            if (action === 'move-down') await moveResourceSource(index, 1);
            if (action === 'edit') editResourceSource(index);
            if (action === 'delete') await deleteResourceSource(index);
        });
        document.getElementById('resource-source-list').addEventListener('change', async (e) => {
            const toggle = e.target.closest('[data-resource-source-toggle]');
            if (!toggle) return;
            const index = parseInt(toggle.dataset.resourceSourceIndex || '-1', 10);
            if (index < 0) return;
            const ok = await toggleResourceSourceEnabled(index, !!toggle.checked);
            if (!ok) toggle.checked = !toggle.checked;
        });
        document.getElementById('resource-source-manager-type-filters').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-source-manager-filter="type"]');
            if (!btn) return;
            const nextFilter = normalizeResourceSourceFilterValue(btn.dataset.filterValue || 'all');
            if (resourceSourceFilter === nextFilter) return;
            resourceSourceFilter = nextFilter;
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-status-filters').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-source-manager-filter="status"]');
            if (!btn) return;
            const nextFilter = normalizeResourceSourceFilterValue(btn.dataset.filterValue || 'all');
            if (resourceSourceEnabledFilter === nextFilter) return;
            resourceSourceEnabledFilter = nextFilter;
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-activity-filters').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-source-manager-filter="activity"]');
            if (!btn) return;
            const nextFilter = normalizeResourceSourceFilterValue(btn.dataset.filterValue || 'all');
            if (resourceSourceActivityFilter === nextFilter) return;
            resourceSourceActivityFilter = nextFilter;
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-list').addEventListener('change', (e) => {
            const checkbox = e.target.closest('[data-resource-source-bulk-toggle]');
            if (!checkbox) return;
            setResourceSourceBulkSelected(checkbox.dataset.resourceSourceBulkToggle || '', !!checkbox.checked);
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-source-manager-action]');
            if (!btn) return;
            const action = String(btn.dataset.resourceSourceManagerAction || '').trim();
            if (action === 'edit') {
                const index = parseInt(btn.dataset.sourceIndex || '-1', 10);
                if (index >= 0) {
                    closeResourceSourceManagerModal();
                    openResourceSourceModal(index);
                }
            }
        });
        document.getElementById('resource-board').addEventListener('click', async (e) => {
            const toggleBtn = e.target.closest('[data-resource-section-toggle]');
            if (toggleBtn) {
                toggleResourceSection(toggleBtn.dataset.resourceSectionToggle || '');
                return;
            }
            const loadMoreBtn = e.target.closest('[data-resource-load-more]');
            if (loadMoreBtn) {
                await loadMoreResourceChannelItems(loadMoreBtn.dataset.resourceLoadMore || '', String(resourceState.search || '').trim());
                return;
            }
            const btn = e.target.closest('[data-resource-action]');
            if (!btn) return;
            const action = btn.dataset.resourceAction || '';
            const resourceId = parseInt(btn.dataset.resourceId || '0', 10);
            if (!resourceId) return;
            if (action === 'preview') openResourceDetailModal(resourceId);
            if (action === 'import') openResourceImportModal(resourceId);
            if (action === 'copy') await copyResourceRecord(resourceId);
            if (action === 'subscribe') openSubscriptionFromResource(resourceId);
        });
        document.getElementById('resource-job-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-job-action]');
            if (!btn) return;
            const action = btn.dataset.resourceJobAction || '';
            const jobId = parseInt(btn.dataset.resourceJobId || '0', 10);
            if (!jobId) return;
            if (action === 'refresh') await triggerResourceJobRefresh(jobId);
            if (action === 'cancel') await triggerResourceJobCancel(jobId);
            if (action === 'retry') await triggerResourceJobRetry(jobId);
        });
        document.getElementById('resource-job-filter-tabs').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-job-filter]');
            if (!btn) return;
            const nextFilter = String(btn.dataset.resourceJobFilter || 'all').trim() || 'all';
            if (resourceJobFilter === nextFilter) return;
            resourceJobFilter = nextFilter;
            renderResourceJobs();
        });
        document.getElementById('subscription-task-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionAction || '';
            const name = decodeURIComponent(btn.dataset.taskName || '');
            if (!name) return;
            if (action === 'start') await startSubscriptionTask(name);
            if (action === 'stop') await stopSubscriptionTask(name);
            if (action === 'edit') editSubscriptionTask(name);
            if (action === 'delete') await deleteSubscriptionTask(name);
            if (action === 'episodes') await openSubscriptionEpisodeModal(name);
        });
        document.getElementById('monitor-task-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-monitor-action]');
            if (!btn) return;
            const action = btn.dataset.monitorAction || '';
            const name = decodeURIComponent(btn.dataset.taskName || '');
            if (!name) return;
            if (action === 'start') await startMonitorTask(name);
            if (action === 'stop') await stopMonitorTask(name);
            if (action === 'edit') editMonitorTask(name);
            if (action === 'delete') await deleteMonitorTask(name);
        });
        document.getElementById('monitor-userscript-job-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-monitor-userscript-action]');
            if (!btn) return;
            const action = btn.dataset.monitorUserscriptAction || '';
            const jobId = parseInt(btn.dataset.resourceJobId || '0', 10);
            if (!jobId) return;
            if (action === 'refresh') await triggerResourceJobRefresh(jobId);
            if (action === 'cancel') await triggerResourceJobCancel(jobId);
            if (action === 'retry') await triggerResourceJobRetry(jobId);
        });
        document.getElementById('monitor-modal').addEventListener('click', (e) => {
            if (e.target.id === 'monitor-modal') closeMonitorModal();
        });
        document.getElementById('subscription-modal').addEventListener('click', (e) => {
            if (e.target.id === 'subscription-modal') closeSubscriptionModal();
        });
        document.getElementById('subscription-tmdb-modal').addEventListener('click', (e) => {
            if (e.target.id === 'subscription-tmdb-modal') closeSubscriptionTmdbSearchModal();
        });
        document.getElementById('subscription-episode-modal').addEventListener('click', (e) => {
            if (e.target.id === 'subscription-episode-modal') closeSubscriptionEpisodeModal();
        });
        document.getElementById('subscription-folder-modal').addEventListener('click', (e) => {
            if (e.target.id === 'subscription-folder-modal') closeSubscriptionFolderModal();
        });
        document.getElementById('help-modal').addEventListener('click', (e) => {
            if (e.target.id === 'help-modal') closeHelpModal();
        });
        document.getElementById('resource-source-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-source-modal') closeResourceSourceModal();
        });
        document.getElementById('resource-source-import-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-source-import-modal') closeResourceSourceImportModal();
        });
        document.getElementById('resource-source-manager-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-source-manager-modal') closeResourceSourceManagerModal();
        });
        document.getElementById('resource-import-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-import-modal') closeResourceJobModal();
        });
        document.getElementById('resource-folder-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-folder-modal') closeResourceFolderModal();
        });
        document.getElementById('resource-folder-create-name').addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            createResourceFolderInCurrent();
        });
        document.getElementById('subscription-folder-create-name').addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            createSubscriptionFolderInCurrent();
        });
        document.getElementById('resource-folder-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-folder-action]');
            if (!btn) return;
            const action = btn.dataset.resourceFolderAction || '';
            if (action === 'open') {
                await openResourceFolderChild(btn.dataset.resourceFolderId || '0', btn.dataset.resourceFolderName || '--');
            }
        });
        document.getElementById('subscription-folder-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-folder-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionFolderAction || '';
            if (action === 'open') {
                await openSubscriptionFolderChild(btn.dataset.subscriptionFolderId || '0', btn.dataset.subscriptionFolderName || '--');
            }
        });
        document.getElementById('subscription_tmdb_result_list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-tmdb-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionTmdbAction || '';
            if (action === 'select') {
                await selectSubscriptionTmdbResult(btn.dataset.subscriptionTmdbIndex || '0');
            }
        });
        document.getElementById('resource-folder-breadcrumbs').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-folder-action]');
            if (!btn) return;
            const action = btn.dataset.resourceFolderAction || '';
            if (action === 'trail') {
                await openResourceFolderTrail(btn.dataset.resourceFolderIndex || '0');
            }
        });
        document.getElementById('subscription-folder-breadcrumbs').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-folder-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionFolderAction || '';
            if (action === 'trail') {
                await openSubscriptionFolderTrail(btn.dataset.subscriptionFolderIndex || '0');
            }
        });
        document.getElementById('resource-job-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-job-modal') toggleResourceJobModal(false);
        });
        document.addEventListener('click', (e) => {
            if (!resourceJobClearMenuOpen) return;
            const menu = document.getElementById('resource-job-clear-menu');
            if (!menu) return;
            if (menu.contains(e.target)) return;
            closeResourceJobClearMenu();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && resourceJobClearMenuOpen) {
                closeResourceJobClearMenu();
                return;
            }
            const subscriptionEpisodeModal = document.getElementById('subscription-episode-modal');
            if (e.key === 'Escape' && subscriptionEpisodeModal && !subscriptionEpisodeModal.classList.contains('hidden')) {
                closeSubscriptionEpisodeModal();
                return;
            }
            const subscriptionTmdbModal = document.getElementById('subscription-tmdb-modal');
            if (e.key === 'Escape' && subscriptionTmdbModal && !subscriptionTmdbModal.classList.contains('hidden')) {
                closeSubscriptionTmdbSearchModal();
                return;
            }
            const subscriptionFolderModal = document.getElementById('subscription-folder-modal');
            if (e.key === 'Escape' && subscriptionFolderModal && !subscriptionFolderModal.classList.contains('hidden')) {
                closeSubscriptionFolderModal();
                return;
            }
            const subscriptionModal = document.getElementById('subscription-modal');
            if (e.key === 'Escape' && subscriptionModal && !subscriptionModal.classList.contains('hidden')) {
                closeSubscriptionModal();
                return;
            }
            if (e.key === 'Escape' && resourceSourceManagerOpen) {
                closeResourceSourceManagerModal();
                return;
            }
            if (e.key === 'Escape' && resourceSourceImportModalOpen) {
                closeResourceSourceImportModal();
                return;
            }
            if (e.key === 'Escape' && resourceSourceModalOpen) {
                closeResourceSourceModal();
                return;
            }
            if (e.key === 'Escape' && resourceJobModalOpen) toggleResourceJobModal(false);
        });
        document.getElementById('resource-share-tree').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-share-action]');
            if (!btn) return;
            const action = btn.dataset.resourceShareAction || '';
            if (action === 'enter') {
                await openResourceShareFolder(btn.dataset.resourceShareId || '');
            }
        });
        document.getElementById('resource-share-root-title').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-share-action]');
            if (!btn) return;
            const action = btn.dataset.resourceShareAction || '';
            if (action === 'trail') {
                await openResourceShareTrail(btn.dataset.resourceShareIndex || '0');
            }
        });
        document.getElementById('resource-share-tree').addEventListener('change', (e) => {
            const checkbox = e.target.closest('[data-resource-share-check]');
            if (!checkbox) return;
            const entryId = String(checkbox.dataset.resourceShareId || '').trim();
            const entry = resourceShareEntryIndex[entryId];
            if (!entry) return;
            applyResourceShareSelection(entry, checkbox.checked);
        });
        document.getElementById('resource-share-current-check-all').addEventListener('change', (e) => {
            setCurrentResourceShareEntriesChecked(!!e.target.checked);
        });
        document.getElementById('resource_share_receive_code').addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            await applyResourceShareReceiveCode();
        });
        document.getElementById('resource_share_receive_code').addEventListener('input', (e) => {
            const rawCode = String(e?.target?.value || '').trim();
            resourceShareReceiveCode = normalizeReceiveCodeInput(rawCode);
        });
        window.addEventListener('scroll', () => {
            syncResourceBackTopButton();
            syncSettingsSaveDock();
        }, { passive: true });
        window.addEventListener('resize', () => {
            syncResourceBackTopButton();
            syncSettingsSaveDock();
        });
        function applyThemeFromStorage() {
            try {
                const isDay = localStorage.getItem('theme-day') === 'day';
                document.documentElement.classList.toggle('theme-day', isDay);
                const btn = document.getElementById('theme-toggle');
                if (btn) btn.textContent = isDay ? '☀️ 日间' : '🌙 夜间';
            } catch (e) {}
        }
        function toggleTheme() {
            try {
                const el = document.documentElement;
                const isDay = !el.classList.contains('theme-day');
                if (isDay) {
                    el.classList.add('theme-day');
                    localStorage.setItem('theme-day', 'day');
                } else {
                    el.classList.remove('theme-day');
                    localStorage.setItem('theme-day', 'night');
                }
                const btn = document.getElementById('theme-toggle');
                if (btn) btn.textContent = isDay ? '☀️ 日间' : '🌙 夜间';
            } catch (e) {}
        }
        applyThemeFromStorage();
        initMainTabRow();
        init();
        syncResourceBackTopButton();
        syncSettingsSaveDock();
        syncMainTabRowState();
        refreshMainLogs();
        refreshMonitorState();
        refreshSubscriptionState();
        refreshResourceState();
        connectStatusStream();
        refreshVersionInfo();
        setInterval(() => refreshVersionInfo(false), VERSION_REFRESH_INTERVAL);
        setInterval(() => {
            const keyword = document.getElementById('resource-search-input')?.value?.trim() || '';
            if (keyword && !isDirectImportInput(keyword)) {
                refreshResourceJobsOnly();
                return;
            }
            refreshResourceState();
        }, RESOURCE_REFRESH_INTERVAL);
    
