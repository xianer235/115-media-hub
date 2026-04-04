        let isRunning = false;
        let monitorState = { running: false, current_task: '', tasks: [], logs: [], summary: { step: '空闲', detail: '等待监控任务' }, queued: [], next_runs: {} };
        let resourceState = { sources: [], items: [], jobs: [], channel_sections: [], channel_profiles: {}, search_sections: [], last_syncs: {}, monitor_tasks: [], stats: { source_count: 0, item_count: 0, filtered_item_count: 0, completed_job_count: 0 }, cookie_configured: false, search: '', search_meta: {} };
        let editingMonitorName = null;
        let editingResourceSourceIndex = null;
        let selectedResourceId = null;
        let selectedResourceItem = null;
        let resourceModalMode = 'detail';
        let resourceFolderTrail = [{ id: '0', name: '根目录' }];
        let resourceFolderEntries = [];
        let resourceFolderSummary = { folder_count: 0, file_count: 0 };
        let resourceFolderLoading = false;
        let resourceFolderCreateBusy = false;
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
        let resourceWarmupDone = false;
        let resourceChannelExtraItems = {};
        let resourceChannelLoadingMore = {};
        let resourceChannelNextBefore = {};
        let resourceChannelNoMore = {};
        let resourceTempIdSeed = -1;
        let resourceClientIdSeed = -100000;
        let resourceClientIdsByIdentity = {};
        let resourceJobModalOpen = false;
        let resourceSourceModalOpen = false;
        let resourceSourceImportModalOpen = false;
        let resourceSourceManagerOpen = false;
        let resourceSourceFilter = 'all';
        let resourceSourceActivityFilter = 'all';
        let resourceSourceBulkSelected = {};
        let resourceSourceTestBusy = false;
        let resourceSourceTestResult = { total: 0, done: 0, success: 0, failed: 0, running: false, last_name: '', error: '' };
        let resourceJobFilter = 'all';
        let tgProxyTestState = { loading: false, ok: null, message: '', latency_ms: 0, mode: '', proxy_url: '', target_url: '' };
        let resourceBoardHintText = '';
        let resourceTgHealthState = { visible: false, tone: 'loading', title: '', meta: '', note: '' };
        let resourceTgLastLatencyMs = 0;
        let lastLogSignature = '';
        let lastMonitorLogSignature = '';
        let lastMonitorRenderKey = '';
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
        const TOAST_DEFAULT_DURATION_MS = 3000;

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
            ['task', 'resource', 'settings', 'monitor', 'about'].forEach(name => {
                document.getElementById(`page-${name}`).classList.toggle('hidden', tab !== name);
                document.getElementById(`tab-${name}`).className = tab === name ? 'tab-active uppercase' : 'tab-inactive uppercase';
            });
            if (tab !== 'resource') toggleResourceJobModal(false);
            if (tab === 'resource') refreshResourceState();
            syncResourceBackTopButton();
            syncSettingsSaveDock();
        }

        function normalizeToastPlacement(placement) {
            const normalized = String(placement || '').trim().toLowerCase();
            if (normalized === 'top-center') return 'top-center';
            return 'bottom-right';
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
            const standardIds = ['alist_url', 'alist_token', 'cookie_115', 'tg_proxy_protocol', 'tg_proxy_host', 'tg_proxy_port', 'mount_path', 'cron_hour', 'sync_mode', 'extensions', 'username', 'password'];
            standardIds.forEach(id => {
                const el = document.getElementById(id);
                if (el) cfg[id] = el.value;
            });

            cfg.check_hash = document.getElementById('check_hash').checked;
            cfg.sync_clean = document.getElementById('sync_clean').checked;
            cfg.tg_proxy_enabled = document.getElementById('tg_proxy_enabled').checked;
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
                resourceWarmupDone = false;
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
                'savepath：转存目标父路径（用于定位刷新范围）',
                'sharetitle：转存后的目录名或文件名',
                'refresh_target_type：folder / file / mixed（帮助区分目录刷新还是父目录刷新）',
                'delayTime：可选，单位秒（覆盖本次任务执行延时）',
                'title：可选（仅日志展示）',
                '说明：本页面仅接收参数；触发条件与映射规则请在 CloudSaver 中配置'
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
                            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 shrink-0">
                                <button type="button" data-monitor-action="start" data-task-name="${taskKey}" class="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold ${startDisabled ? 'btn-disabled' : ''}" ${startDisabled ? 'disabled' : ''}>${starting ? '启动中...' : '运行'}</button>
                                <button type="button" data-monitor-action="stop" data-task-name="${taskKey}" class="px-4 py-2 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 text-sm font-bold ${stopDisabled ? 'btn-disabled' : ''}" ${stopDisabled ? 'disabled' : ''}>${stopping ? '中断中...' : '中断'}</button>
                                <button type="button" data-monitor-action="edit" data-task-name="${taskKey}" class="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">编辑</button>
                                <button type="button" data-monitor-action="delete" data-task-name="${taskKey}" class="px-4 py-2 rounded-xl bg-red-500/15 hover:bg-red-500/25 text-red-300 text-sm font-bold ${deleteDisabled ? 'btn-disabled' : ''}" ${deleteDisabled ? 'disabled' : ''}>${deleting ? '删除中...' : '删除'}</button>
                            </div>
                        </div>
                        ${task.webhook_enabled ? `<div class="mt-3 text-xs text-emerald-400">Webhook：IP:容器端口/webhook/${escapeHtml(task.name)}</div>` : ''}
                    </div>
                `;
            }).join('');
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
            } catch (e) {}
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

        function buildResourceEntryRow(entry, { showOpenButton = false } = {}) {
            const isDir = !!entry?.is_dir;
            const normalizedEntryId = String(entry?.id || '').trim();
            const name = escapeHtml(entry?.name || '--');
            const idText = escapeHtml(isDir ? (entry?.id || '--') : (entry?.pick_code || entry?.sha1 || '--'));
            const meta = isDir
                ? (showOpenButton ? '文件夹' : `CID: ${idText}`)
                : `${escapeHtml(formatFileSizeText(entry?.size || 0))}${entry?.modified_at ? ` / ${escapeHtml(entry.modified_at)}` : ''}`;
            const actionHtml = showOpenButton && isDir
                ? `<button type="button" data-resource-folder-action="open" data-resource-folder-id="${escapeHtml(entry?.id || '')}" data-resource-folder-name="${name}" class="resource-entry-action shrink-0">进入</button>`
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
                completed_job_count: Number(resourceState?.stats?.completed_job_count ?? 0)
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
            const completedCount = Number(stats.completed_job_count ?? 0);
            const completedCountEl = document.getElementById('resource-completed-job-count');
            if (completedCountEl) completedCountEl.innerText = String(completedCount);
            const clearCompletedBtn = document.getElementById('resource-clear-completed-btn');
            if (clearCompletedBtn) {
                clearCompletedBtn.textContent = completedCount > 0
                    ? `清空已完成（${completedCount}）`
                    : '清空已完成';
                clearCompletedBtn.disabled = completedCount <= 0;
                clearCompletedBtn.classList.toggle('btn-disabled', completedCount <= 0);
            }
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

            const resourcePageVisible = !document.getElementById('page-resource')?.classList.contains('hidden');
            if (resourcePageVisible && !resourceWarmupDone && getEnabledResourceSources().length) {
                resourceWarmupDone = true;
                syncResourceChannels(false, { silent: true });
            }
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
                if (!!activeKeyword && !allowSearch && !isDirectImportInput(activeKeyword)) return null;
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
                    const suffix = result.item ? '，已直接打开导入面板。' : '。';
                    alert(`✅ 识别完成${suffix}`);
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
                if (!silent) {
                    if (Array.isArray(data.errors) && data.errors.length) {
                        const detail = data.errors.map(item => `${item.name || item.channel_id}: ${item.message}`).join('\n');
                        alert(`⚠️ 已同步 ${data.synced || 0} 个频道，新增 ${data.items || 0} 条资源${data.cache_pruned ? `，清理 ${data.cache_pruned} 条旧缓存` : ''}。\n\n以下频道同步失败：\n${detail}`);
                    } else {
                        alert(`✅ 同步完成：更新 ${data.synced || 0} 个频道，新增 ${data.items || 0} 条资源${data.skipped ? `，跳过 ${data.skipped} 个缓存未过期频道` : ''}${data.cache_pruned ? `，清理 ${data.cache_pruned} 条旧缓存` : ''}`);
                    }
                }
                return data;
            } catch (e) {
                if (!silent) {
                    const latencyMs = await resolveResourceTgLatencyMs(latencyProbePromise);
                    applyResourceTgHealthFailure('sync', getActionElapsedMs(startedAt), latencyMs);
                }
                if (!silent) alert(`❌ ${e.message}`);
                return null;
            } finally {
                resourceSyncBusy = false;
                syncResourceActionButtons();
                if (!resourceSearchBusy) renderResourceBoard();
            }
        }

        async function clearCompletedResourceJobs() {
            const completedCount = Number(resourceState?.stats?.completed_job_count || 0);
            if (completedCount <= 0) {
                alert('当前没有可清空的已完成导入记录');
                return;
            }
            if (!confirm('将清空已完成导入记录（不删除网盘文件）。继续吗？')) return;
            const res = await fetch('/resource/jobs/clear_completed', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({})
            });
            const data = await res.json();
            if (!res.ok || !data.ok) return alert(`❌ ${data.msg || '清空失败'}`);
            await refreshResourceState();
            const deleted = Number(data.deleted || 0);
            if (deleted > 0) {
                alert(`✅ 已清空 ${deleted} 条已完成导入记录`);
            } else {
                alert('✅ 当前没有可清空的已完成导入记录');
            }
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

        function getFilteredResourceSourceViewList() {
            const sources = resourceState.sources || [];
            const sectionIndex = getResourceSourceSectionIndex();
            const list = getResourceSourceViewList(sources, sectionIndex);
            return list.filter(view => {
                if (!isResourceSourceVisibleByFilter(view.source, sectionIndex, resourceSourceFilter)) return false;
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
            const activityFiltersEl = document.getElementById('resource-source-manager-activity-filters');
            const hintEl = document.getElementById('resource-source-manager-filter-hint');
            const listEl = document.getElementById('resource-source-manager-list');
            const selectedCountEl = document.getElementById('resource-source-manager-selected-count');
            const resultEl = document.getElementById('resource-source-manager-test-result');
            const testBtn = document.getElementById('resource-source-manager-test-btn');
            const selectAllEl = document.getElementById('resource-source-manager-select-all');
            if (!typeFiltersEl || !activityFiltersEl || !hintEl || !listEl || !selectedCountEl || !resultEl || !testBtn || !selectAllEl) return;

            const sources = resourceState.sources || [];
            const sectionIndex = getResourceSourceSectionIndex();
            const sourceViews = getResourceSourceViewList(sources, sectionIndex);
            const typeOptions = buildResourceSourceFilterOptions(sources, sectionIndex);
            const activityOptions = buildResourceSourceActivityFilterOptions(sources, sectionIndex);

            if (!typeOptions.some(option => option.value === normalizeResourceSourceFilterValue(resourceSourceFilter))) {
                resourceSourceFilter = 'all';
            }
            if (!activityOptions.some(option => option.value === normalizeResourceSourceFilterValue(resourceSourceActivityFilter))) {
                resourceSourceActivityFilter = 'all';
            }

            const filtered = sourceViews.filter(view => {
                if (!isResourceSourceVisibleByFilter(view.source, sectionIndex, resourceSourceFilter)) return false;
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

            selectAllEl.checked = filtered.length > 0 && selectedInFiltered === filtered.length;
            selectAllEl.indeterminate = selectedInFiltered > 0 && selectedInFiltered < filtered.length;
            selectAllEl.disabled = filtered.length <= 0;

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
                listEl.innerHTML = '<div class="resource-source-empty"><div class="resource-source-empty-title">当前筛选无结果</div><div class="resource-source-empty-copy">可以切换资源类型或活跃时间范围。</div></div>';
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
            resourceWarmupDone = false;
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
                const manualRefreshLabel = !hasMonitorTask ? '当前目录不触发' : (canManualRefresh ? '立即触发刷新' : '无需手动刷新');
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

        function toggleResourceJobModal(force) {
            const modal = document.getElementById('resource-job-modal');
            if (!modal) return;
            resourceJobModalOpen = typeof force === 'boolean' ? force : !resourceJobModalOpen;
            modal.classList.toggle('hidden', !resourceJobModalOpen);
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

        async function triggerResourceJobRefresh(jobId) {
            const res = await fetch('/resource/jobs/refresh', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ job_id: jobId })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) return alert(`❌ ${data.msg || '触发刷新失败'}`);
            await refreshResourceState();
            alert('✅ 已触发文件夹监控任务');
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
                applyResourceState({
                    ...resourceState,
                    sources: cfg.resource_sources || [],
                    monitor_tasks: cfg.monitor_tasks || [],
                    cookie_configured: !!String(cfg.cookie_115 || '').trim()
                });
                renderTgProxyTestStatus();
                resetMonitorForm();
                resetResourceSourceForm();
                syncResourceSourceSelect();
                refreshWebhookHint();
                renderVersionInfoPanel();
            } catch (e) {}
        }

        document.getElementById('monitor_name').addEventListener('input', refreshWebhookHint);
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
        document.getElementById('resource-source-manager-activity-filters').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-source-manager-filter="activity"]');
            if (!btn) return;
            const nextFilter = normalizeResourceSourceFilterValue(btn.dataset.filterValue || 'all');
            if (resourceSourceActivityFilter === nextFilter) return;
            resourceSourceActivityFilter = nextFilter;
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-select-all').addEventListener('change', (e) => {
            toggleSelectAllFilteredResourceSources(!!e.target.checked);
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
        });
        document.getElementById('resource-job-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-job-action]');
            if (!btn) return;
            const action = btn.dataset.resourceJobAction || '';
            const jobId = parseInt(btn.dataset.resourceJobId || '0', 10);
            if (!jobId) return;
            if (action === 'refresh') await triggerResourceJobRefresh(jobId);
        });
        document.getElementById('resource-job-filter-tabs').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-job-filter]');
            if (!btn) return;
            const nextFilter = String(btn.dataset.resourceJobFilter || 'all').trim() || 'all';
            if (resourceJobFilter === nextFilter) return;
            resourceJobFilter = nextFilter;
            renderResourceJobs();
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
        document.getElementById('monitor-modal').addEventListener('click', (e) => {
            if (e.target.id === 'monitor-modal') closeMonitorModal();
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
        document.getElementById('resource-folder-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-folder-action]');
            if (!btn) return;
            const action = btn.dataset.resourceFolderAction || '';
            if (action === 'open') {
                await openResourceFolderChild(btn.dataset.resourceFolderId || '0', btn.dataset.resourceFolderName || '--');
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
        document.getElementById('resource-job-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-job-modal') toggleResourceJobModal(false);
        });
        document.addEventListener('keydown', (e) => {
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
        init();
        syncResourceBackTopButton();
        syncSettingsSaveDock();
        refreshMainLogs();
        refreshMonitorState();
        refreshResourceState();
        connectStatusStream();
        refreshVersionInfo();
        setInterval(() => refreshVersionInfo(false), VERSION_REFRESH_INTERVAL);
        setInterval(() => {
            const keyword = document.getElementById('resource-search-input')?.value?.trim() || '';
            if (keyword && !isDirectImportInput(keyword)) return;
            refreshResourceState();
        }, RESOURCE_REFRESH_INTERVAL);
    
