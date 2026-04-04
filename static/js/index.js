        let isRunning = false;
        let monitorState = { running: false, current_task: '', tasks: [], logs: [], summary: { step: '空闲', detail: '等待监控任务' }, queued: [], next_runs: {} };
        let resourceState = { sources: [], items: [], jobs: [], channel_sections: [], last_syncs: {}, monitor_tasks: [], stats: { source_count: 0, item_count: 0, job_count: 0 }, cookie_configured: false };
        let editingMonitorName = null;
        let editingResourceSourceIndex = null;
        let selectedResourceId = null;
        let selectedResourceItem = null;
        let resourceModalMode = 'detail';
        let selectedResourceChannelId = '';
        let resourceFolderTrail = [{ id: '0', name: '根目录' }];
        let resourceFolderEntries = [];
        let resourceFolderSummary = { folder_count: 0, file_count: 0 };
        let resourceFolderLoading = false;
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
        let resourceShareTrail = [{ cid: '0', name: '分享根目录' }];
        let resourceShareCurrentCid = '0';
        let resourceShareRequestToken = 0;
        let resourceSectionCollapsed = {};
        let resourceSyncBusy = false;
        let resourceWarmupDone = false;
        let tgProxyTestState = { loading: false, ok: null, message: '', latency_ms: 0, mode: '', proxy_url: '', target_url: '' };
        let lastLogSignature = '';
        let lastMonitorLogSignature = '';
        let lastMonitorRenderKey = '';
        let statusEventSource = null;
        let statusFallbackTimer = null;
        const monitorActionLocks = new Set();
        let versionInfo = { local: null, latest: null, has_update: false, checked_at: 0, error: '', source: '' };
        let versionBannerDismissed = false;
        const btnTexts = ["🌐 联网同步更新", "🛠 本地调试解析", "🔥 强制全量重刷"];
        const DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,wmv,flv,webm,vob,mpg,mpeg,ts,m2ts,mts,rmvb,rm,asf,3gp,m4v,f4v,iso";
        const STATUS_FALLBACK_INTERVAL = 15000;
        const RESOURCE_REFRESH_INTERVAL = 15000;
        const VERSION_REFRESH_INTERVAL = 1000 * 60 * 15;
        const VERSION_FALLBACK_PROJECT_URL = 'https://github.com/xianer235/115-strm-web';
        const VERSION_FALLBACK_CHANGELOG_URL = 'https://github.com/xianer235/115-strm-web/blob/main/CHANGELOG.md';

        function switchTab(tab) {
            ['task', 'resource', 'settings', 'monitor', 'about'].forEach(name => {
                document.getElementById(`page-${name}`).classList.toggle('hidden', tab !== name);
                document.getElementById(`tab-${name}`).className = tab === name ? 'tab-active uppercase' : 'tab-inactive uppercase';
            });
            if (tab === 'resource') refreshResourceState();
        }

        function escapeHtml(str) {
            return String(str || '')
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#39;');
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
                statusEl.className = 'rounded-xl border px-4 py-3 text-sm leading-6 border-sky-500/20 bg-sky-500/10 text-sky-200';
                statusEl.innerHTML = '正在请求 TG 频道页并测量当前响应时间，请稍候...';
                statusEl.classList.remove('hidden');
                return;
            }

            if (tgProxyTestState.ok === true) {
                const modeLabel = tgProxyTestState.mode === 'proxy'
                    ? `代理模式 <span class="text-slate-200">${escapeHtml(tgProxyTestState.proxy_url || '--')}</span>`
                    : '直连模式';
                statusEl.className = 'rounded-xl border px-4 py-3 text-sm leading-6 border-emerald-500/20 bg-emerald-500/10 text-emerald-300';
                statusEl.innerHTML = `
                    <div class="font-bold">TG 连通成功，延迟约 ${escapeHtml(String(tgProxyTestState.latency_ms || 0))} ms</div>
                    <div class="text-xs text-emerald-100/80 mt-1">${modeLabel}</div>
                    <div class="text-xs text-emerald-100/70 mt-1">测试地址：${escapeHtml(tgProxyTestState.target_url || '')}</div>
                `;
                statusEl.classList.remove('hidden');
                return;
            }

            if (tgProxyTestState.ok === false) {
                statusEl.className = 'rounded-xl border px-4 py-3 text-sm leading-6 border-rose-500/20 bg-rose-500/10 text-rose-300';
                statusEl.innerHTML = `
                    <div class="font-bold">TG 延迟测试失败</div>
                    <div class="text-xs text-rose-100/80 mt-1">${escapeHtml(tgProxyTestState.message || '未知错误')}</div>
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
                link: '直链',
                unknown: '待识别'
            };
            return map[normalized] || normalized || '待识别';
        }

        function getEffectiveResourceLinkType(item) {
            const rawType = String(item?.link_type || '').trim().toLowerCase();
            if (rawType === 'magnet' || rawType === '115share') return rawType;
            const linkUrl = String(item?.link_url || '').trim().toLowerCase();
            if (linkUrl.startsWith('magnet:?')) return 'magnet';
            if (linkUrl.includes('115cdn.com/s/') || linkUrl.includes('115.com/s/') || linkUrl.includes('anxia.com/s/')) return '115share';
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
            const direct = (resourceState.items || []).find(item => Number(item.id) === target);
            if (direct) return direct;
            for (const section of resourceState.channel_sections || []) {
                const found = (section.items || []).find(item => Number(item.id) === target);
                if (found) return found;
            }
            return null;
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
            const coverUrl = String(item?.cover_url || '').trim();
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
            const name = escapeHtml(entry?.name || '--');
            const idText = escapeHtml(isDir ? (entry?.id || '--') : (entry?.pick_code || entry?.sha1 || '--'));
            const meta = isDir
                ? (showOpenButton ? '文件夹' : `CID: ${idText}`)
                : `${escapeHtml(formatFileSizeText(entry?.size || 0))}${entry?.modified_at ? ` / ${escapeHtml(entry.modified_at)}` : ''}`;
            const actionHtml = showOpenButton && isDir
                ? `<button type="button" data-resource-folder-action="open" data-resource-folder-id="${escapeHtml(entry?.id || '')}" data-resource-folder-name="${name}" class="resource-entry-action shrink-0">进入</button>`
                : `<span class="resource-entry-flag shrink-0">${isDir ? '目录' : escapeHtml(formatFileSizeText(entry?.size || 0))}</span>`;
            return `
                <div class="resource-entry ${isDir ? 'resource-entry-dir' : 'resource-entry-file'}">
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
            const sourceName = String(item?.source_name || item?.channel_name || '手动录入').trim();
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
                                        ${buildResourceStatusBadge(item?.status)}
                                        <span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-100">${escapeHtml(getResourceLinkTypeLabel(getEffectiveResourceLinkType(item)))}</span>
                                        ${item?.quality ? `<span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/20">${escapeHtml(item.quality)}</span>` : ''}
                                        ${item?.year ? `<span class="text-[10px] px-3 py-1 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/20">${escapeHtml(item.year)}</span>` : ''}
                                    </div>
                            </div>
                            <button type="button" data-resource-action="delete" data-resource-id="${item.id}" class="text-[11px] font-bold text-slate-400 hover:text-red-300 shrink-0">删除</button>
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

        function renderResourceChannelTabs() {
            const container = document.getElementById('resource-channel-tabs');
            if (!container) return;
            const sources = getEnabledResourceSources();
            const channelIds = new Set(sources.map(source => getResourceSourceChannelId(source)));
            if (selectedResourceChannelId && !channelIds.has(selectedResourceChannelId)) {
                selectedResourceChannelId = '';
            }
            if (!sources.length) {
                container.innerHTML = '<span class="resource-chip">暂无已启用频道</span>';
                return;
            }
            const tabs = [
                {
                    channel_id: '',
                    label: '全部频道'
                },
                ...sources.map(source => ({
                    channel_id: getResourceSourceChannelId(source),
                    label: source.name || getResourceSourceChannelId(source)
                }))
            ];
            container.innerHTML = tabs.map(tab => `
                <button
                    type="button"
                    data-resource-channel="${escapeHtml(tab.channel_id || '__all__')}"
                    class="resource-chip ${selectedResourceChannelId === tab.channel_id ? 'resource-chip-active' : ''}"
                >${escapeHtml(tab.label)}</button>
            `).join('');
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
                delayInput.disabled = true;
                renderResourceImportBehaviorHint('');
                return;
            }

            hiddenInput.value = match.taskName;

            if (match.taskName) {
                displayInput.textContent = match.taskName;
                delayInput.disabled = false;
            } else {
                displayInput.textContent = '当前目录不自动触发';
                delayInput.disabled = true;
            }

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

        function renderResourceBoard() {
            const container = document.getElementById('resource-board');
            const hint = document.getElementById('resource-board-hint');
            if (!container || !hint) return;

            const keyword = document.getElementById('resource-search-input')?.value?.trim() || '';
            const status = document.getElementById('resource-status-filter')?.value || '';
            const sections = (resourceState.channel_sections || []).filter(section => section.enabled !== false);
            const filteredSections = selectedResourceChannelId
                ? sections.filter(section => normalizeTelegramChannelIdInput(section.channel_id) === selectedResourceChannelId)
                : sections;
            const listMode = !!keyword || !!status;

            if (listMode) {
                const items = resourceState.items || [];
                const channelLabel = selectedResourceChannelId
                    ? (getEnabledResourceSources().find(source => getResourceSourceChannelId(source) === selectedResourceChannelId)?.name || selectedResourceChannelId)
                    : '全部频道';
                const filteredCount = Number(resourceState?.stats?.filtered_item_count ?? items.length ?? 0);
                hint.innerText = `搜索结果：关键词「${keyword || '全部'}」 / 状态「${status ? getResourceStatusLabel(status) : '全部'}」 / 频道「${channelLabel}」 / 共 ${filteredCount} 条`;
                if (!items.length) {
                    container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">没有命中资源。可以先点“同步频道”，或者直接在搜索框里粘贴 magnet / 115 分享链接。</div>';
                    return;
                }
                container.innerHTML = `<div class="resource-grid">${items.map(item => buildResourceCard(item)).join('')}</div>`;
                return;
            }

            if (!filteredSections.length) {
                hint.innerText = '空搜索时显示每个启用频道最近 10 条资源；如果列表为空，请先点击“同步频道”。';
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">还没有可展示的频道资源。先在“参数配置”里添加频道，并执行一次同步即可。</div>';
                return;
            }

            hint.innerText = selectedResourceChannelId
                ? '当前只看所选订阅源最近 10 条资源。'
                : '空搜索时会按订阅源逐栏展示最近 10 条资源；搜索时显示命中结果。';
            container.innerHTML = filteredSections.map(section => `
                <section class="resource-section-card" data-collapsed="${isResourceSectionCollapsed(section.channel_id) ? 'true' : 'false'}">
                    <div class="resource-section-header">
                        <button type="button" data-resource-section-toggle="${escapeHtml(section.channel_id || '')}" class="resource-section-header-main min-w-0 flex-1 text-left bg-transparent border-none p-0">
                            <div class="flex flex-wrap items-center gap-2">
                                <h4 class="text-lg font-black text-white">${escapeHtml(section.name || section.channel_id || '未命名频道')}</h4>
                                <span class="text-[11px] px-3 py-1 rounded-full bg-slate-800 text-slate-300 border border-slate-700">@${escapeHtml(section.channel_id || '--')}</span>
                                <span class="text-[11px] px-3 py-1 rounded-full bg-sky-500/10 text-sky-300 border border-sky-500/20">最近 ${Math.min((section.items || []).length, 10)} 条</span>
                                <span class="text-[11px] px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">已同步 ${escapeHtml(String(section.item_count || (section.items || []).length || 0))} 条</span>
                                ${section.last_error ? '<span class="text-[11px] px-3 py-1 rounded-full bg-rose-500/10 text-rose-300 border border-rose-500/20">同步异常</span>' : ''}
                            </div>
                            <div class="subtle mt-2">最近同步：${escapeHtml(formatResourceSyncTime(section.last_sync_at))}</div>
                        </button>
                        <div class="flex items-center gap-2 shrink-0">
                            <a href="${escapeHtml(section.url || '#')}" target="_blank" rel="noopener noreferrer" class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm font-bold border border-slate-700">打开频道</a>
                            <button type="button" data-resource-section-toggle="${escapeHtml(section.channel_id || '')}" class="resource-section-toggle bg-transparent border-none p-0">⌄</button>
                        </div>
                    </div>
                    <div class="resource-section-body">
                        ${section.last_error ? `<div class="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-5 text-sm text-rose-200 mb-4">频道同步失败：${escapeHtml(section.last_error || '未知错误')}</div>` : ''}
                        ${(section.items || []).length
                            ? `<div class="resource-grid">${(section.items || []).map(item => buildResourceCard(item)).join('')}</div>`
                            : '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">这个频道还没有同步到资源，稍后再试一次同步。</div>'
                        }
                    </div>
                </section>
            `).join('');
        }

        function applyResourceState(data) {
            if (!data) return;
            const nextSources = Array.isArray(data.sources) ? data.sources : (resourceState.sources || []);
            const nextItems = Array.isArray(data.items) ? data.items : (resourceState.items || []);
            const nextJobs = Array.isArray(data.jobs) ? data.jobs : (resourceState.jobs || []);
            const nextStats = data.stats || {
                source_count: nextSources.length,
                item_count: nextItems.length,
                job_count: nextJobs.length
            };
            resourceState = {
                ...resourceState,
                ...data,
                sources: nextSources,
                items: nextItems,
                jobs: nextJobs,
                channel_sections: Array.isArray(data.channel_sections) ? data.channel_sections : (resourceState.channel_sections || []),
                last_syncs: data.last_syncs || resourceState.last_syncs || {},
                monitor_tasks: Array.isArray(data.monitor_tasks) ? data.monitor_tasks : (resourceState.monitor_tasks || monitorState.tasks || []),
                stats: nextStats
            };
            if (typeof data.channel_id === 'string') {
                selectedResourceChannelId = normalizeTelegramChannelIdInput(data.channel_id);
            }
            if (selectedResourceId) {
                const refreshedSelectedItem = findResourceItem(selectedResourceId);
                if (refreshedSelectedItem) selectedResourceItem = refreshedSelectedItem;
            }

            const stats = resourceState.stats || {};
            document.getElementById('resource-source-count').innerText = String(stats.source_count ?? resourceState.sources.length ?? 0);
            document.getElementById('resource-item-count').innerText = String(stats.item_count ?? resourceState.items.length ?? 0);
            document.getElementById('resource-job-count').innerText = String(stats.job_count ?? resourceState.jobs.length ?? 0);
            document.getElementById('resource-cookie-hint').classList.toggle('hidden', !!resourceState.cookie_configured);
            syncResourceSourceSelect();
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceChannelTabs();
            renderResourceSources();
            renderResourceBoard();
            renderResourceJobs();
            if (selectedResourceItem) renderResourceModalLayout(selectedResourceItem);
            renderResourceShareBrowser();
            renderResourceTargetPreview();

            const resourcePageVisible = !document.getElementById('page-resource')?.classList.contains('hidden');
            if (resourcePageVisible && !resourceWarmupDone && getEnabledResourceSources().length) {
                resourceWarmupDone = true;
                syncResourceChannels(false, { silent: true });
            }
        }

        async function refreshResourceState() {
            try {
                const q = document.getElementById('resource-search-input')?.value?.trim() || '';
                const status = document.getElementById('resource-status-filter')?.value || '';
                const params = new URLSearchParams();
                if (q) params.set('q', q);
                if (status) params.set('status', status);
                if (selectedResourceChannelId) params.set('channel_id', selectedResourceChannelId);
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
            return /magnet:\?xt=urn:btih:[a-z0-9]{32,40}/i.test(raw)
                || /https?:\/\/(?:115cdn|115|anxia)\.com\/s\/[A-Za-z0-9]+/i.test(raw);
        }

        async function parseResourceInputFromSearch(rawText) {
            const res = await fetch('/resource/items/import_text', {
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
            await refreshResourceState();
            const items = Array.isArray(data.items) ? data.items : [];
            const preferred = items.find(item => canOpenResourceImport(item)) || items[0];
            if (preferred) {
                openResourceDetailModal(preferred.id);
            }
            return {
                inserted: data.inserted || 0,
                updated: data.updated || 0,
                item: preferred || null
            };
        }

        async function searchResources() {
            const keyword = document.getElementById('resource-search-input')?.value?.trim() || '';
            if (!keyword) {
                await refreshResourceState();
                return;
            }
            if (isDirectImportInput(keyword)) {
                try {
                    selectedResourceChannelId = '';
                    document.getElementById('resource-status-filter').value = '';
                    const result = await parseResourceInputFromSearch(keyword);
                    const suffix = result.item ? '，已为你打开资源详情面板。' : '。';
                    alert(`✅ 解析完成：新增 ${result.inserted} 条，更新 ${result.updated} 条${suffix}`);
                } catch (e) {
                    alert(`❌ ${e.message}`);
                }
                return;
            }
            await refreshResourceState();
        }

        async function syncResourceChannels(force = false, { silent = false } = {}) {
            if (resourceSyncBusy) return null;
            resourceSyncBusy = true;
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
                    if (Array.isArray(data.errors) && data.errors.length) {
                        const detail = data.errors.map(item => `${item.name || item.channel_id}: ${item.message}`).join('\n');
                        alert(`⚠️ 已同步 ${data.synced || 0} 个频道，新增 ${data.items || 0} 条资源。\n\n以下频道同步失败：\n${detail}`);
                    } else {
                        alert(`✅ 同步完成：更新 ${data.synced || 0} 个频道，新增 ${data.items || 0} 条资源${data.skipped ? `，跳过 ${data.skipped} 个缓存未过期频道` : ''}`);
                    }
                }
                return data;
            } catch (e) {
                if (!silent) alert(`❌ ${e.message}`);
                return null;
            } finally {
                resourceSyncBusy = false;
            }
        }

        function clearResourceSearch() {
            document.getElementById('resource-search-input').value = '';
            document.getElementById('resource-status-filter').value = '';
            selectedResourceChannelId = '';
            refreshResourceState();
        }

        function currentResourceSourceFormData() {
            return {
                name: document.getElementById('resource_source_name').value.trim(),
                channel_id: normalizeTelegramChannelIdInput(document.getElementById('resource_source_channel').value.trim()),
                enabled: document.getElementById('resource_source_enabled').checked
            };
        }

        function resetResourceSourceForm() {
            editingResourceSourceIndex = null;
            document.getElementById('resource_source_name').value = '';
            document.getElementById('resource_source_channel').value = '';
            document.getElementById('resource_source_url').value = '';
            document.getElementById('resource_source_notes').value = '';
            document.getElementById('resource_source_enabled').checked = true;
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

        async function saveResourceSource() {
            const source = currentResourceSourceFormData();
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
                resetResourceSourceForm();
                alert('✅ 频道源已保存');
            } catch (e) {
                alert(`❌ ${e.message}`);
            }
        }

        function editResourceSource(index) {
            const source = (resourceState.sources || [])[index];
            if (!source) return;
            editingResourceSourceIndex = index;
            document.getElementById('resource_source_name').value = source.name || '';
            document.getElementById('resource_source_channel').value = getResourceSourceChannelId(source);
            document.getElementById('resource_source_url').value = source.url || '';
            document.getElementById('resource_source_notes').value = source.notes || '';
            document.getElementById('resource_source_enabled').checked = !!source.enabled;
            switchTab('settings');
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
                if (selectedResourceChannelId === channelId) selectedResourceChannelId = '';
                if (editingResourceSourceIndex === index) resetResourceSourceForm();
            } catch (e) {
                alert(`❌ ${e.message}`);
            }
        }

        function renderResourceSources() {
            const container = document.getElementById('resource-source-list');
            const sources = resourceState.sources || [];
            if (!container) return;
            if (!sources.length) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">还没有配置 TG 频道源，先加一条占位配置也可以。</div>';
                return;
            }
            container.innerHTML = sources.map((source, index) => {
                const channelId = getResourceSourceChannelId(source);
                const lastSync = formatResourceSyncTime((resourceState.last_syncs || {})[channelId]);
                const moveUpDisabled = index === 0 ? 'btn-disabled' : '';
                const moveDownDisabled = index === sources.length - 1 ? 'btn-disabled' : '';
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/50 p-4">
                        <div class="flex flex-wrap items-start justify-between gap-3">
                            <div>
                                <div class="flex flex-wrap items-center gap-2">
                                    <div class="text-sm font-bold text-white">${escapeHtml(source.name || `频道 ${index + 1}`)}</div>
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-slate-800 text-slate-300 border border-slate-700">排序 ${index + 1}</span>
                                    ${source.enabled ? '<span class="text-[10px] px-3 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/20">启用</span>' : '<span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-200">停用</span>'}
                                </div>
                                <div class="text-xs text-slate-400 leading-6 mt-2">
                                    <div>频道 ID：${escapeHtml(channelId || '--')}</div>
                                    <div>频道链接：${escapeHtml(source.url || '--')}</div>
                                    <div>最近同步：${escapeHtml(lastSync)}</div>
                                </div>
                            </div>
                            <div class="flex flex-wrap gap-2">
                                <button type="button" data-resource-source-action="move-up" data-resource-source-index="${index}" class="px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold ${moveUpDisabled}" ${index === 0 ? 'disabled' : ''}>上移</button>
                                <button type="button" data-resource-source-action="move-down" data-resource-source-index="${index}" class="px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold ${moveDownDisabled}" ${index === sources.length - 1 ? 'disabled' : ''}>下移</button>
                                <button type="button" data-resource-source-action="edit" data-resource-source-index="${index}" class="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">编辑</button>
                                <button type="button" data-resource-source-action="delete" data-resource-source-index="${index}" class="px-4 py-2 rounded-xl bg-red-500/15 hover:bg-red-500/25 text-red-300 text-sm font-bold">删除</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function renderResourceJobs() {
            const container = document.getElementById('resource-job-list');
            const jobs = resourceState.jobs || [];
            if (!container) return;
            if (!jobs.length) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">还没有导入任务，资源卡片里的“下载到 115 / 转存到 115”就会在这里留下记录。</div>';
                return;
            }
            container.innerHTML = jobs.map(job => {
                const hasMonitorTask = !!String(job.monitor_task_name || '').trim();
                const canManualRefresh = hasMonitorTask && !job.last_triggered_at && String(job.status || '').toLowerCase() === 'submitted';
                const manualRefreshLabel = !hasMonitorTask ? '当前目录不触发' : (canManualRefresh ? '立即触发刷新' : '无需手动刷新');
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/50 p-4">
                        <div class="flex flex-wrap items-start justify-between gap-3">
                            <div class="min-w-0 flex-1">
                                <div class="flex flex-wrap items-center gap-2">
                                    <div class="text-sm font-bold text-white break-all">${escapeHtml(job.title || `任务 #${job.id}`)}</div>
                                    ${buildResourceStatusBadge(job.status)}
                                    <span class="text-[10px] px-3 py-1 rounded-full bg-slate-700 text-slate-100">#${job.id}</span>
                                </div>
                                <div class="text-xs text-slate-400 leading-6 mt-2 break-all">
                                    <div>网盘保存路径：${escapeHtml(job.savepath || '--')}</div>
                                    <div>文件夹监控：${escapeHtml(job.monitor_task_name || '当前目录未纳入文件夹监控')}</div>
                                    <div>子目录：${escapeHtml(job.sharetitle || job.share_root_title || '--')}</div>
                                    <div>刷新类型：${escapeHtml(getResourceRefreshTargetLabel(job.refresh_target_type))}</div>
                                    <div>自动刷新：${hasMonitorTask ? (job.auto_refresh ? `开启（等待 ${escapeHtml(String(job.refresh_delay_seconds || 0))} 秒）` : '关闭') : '当前目录不自动触发'}</div>
                                    <div>状态详情：${escapeHtml(job.status_detail || '--')}</div>
                                    <div>创建时间：${escapeHtml(job.created_at || '--')}</div>
                                </div>
                            </div>
                            <div class="flex flex-wrap gap-2 shrink-0">
                                <button type="button" data-resource-job-action="refresh" data-resource-job-id="${job.id}" class="px-4 py-2 rounded-xl text-sm font-bold ${canManualRefresh ? 'bg-sky-600 hover:bg-sky-500 text-white' : 'bg-slate-700 text-slate-400 btn-disabled'}" ${canManualRefresh ? '' : 'disabled'}>${manualRefreshLabel}</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
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

        async function fetchResourceShareData(resourceId, cid = '0') {
            const res = await fetch(`/resource/115/share_entries?resource_id=${encodeURIComponent(String(resourceId || 0))}&cid=${encodeURIComponent(String(cid || '0'))}`);
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
            if (!selectedResourceId || !isCurrentResource115Share()) return;
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
                renderResourceShareBrowser();
            }
        }

        async function goResourceShareRoot() {
            if (!selectedResourceId || !isCurrentResource115Share()) return;
            resourceShareTrail = [{ cid: '0', name: resourceShareInfo?.title || '分享根目录' }];
            resourceShareCurrentCid = '0';
            if (!Object.prototype.hasOwnProperty.call(resourceShareEntriesByParent, '0') || !resourceShareRootLoaded) {
                await loadResourceShareBranch(selectedResourceId, '0');
                return;
            }
            renderResourceShareBrowser();
        }

        async function goResourceShareBack() {
            if (!selectedResourceId || !isCurrentResource115Share()) return;
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
            if (!selectedResourceId || !isCurrentResource115Share()) return;
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
            if (!selectedResourceId || !isCurrentResource115Share()) return;
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
                                class="h-4 w-4 rounded border-slate-600 bg-slate-900 accent-sky-500"
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

        function setSelectedResourceFolder(folderId, displayPath, { loadPreview = false } = {}) {
            const normalizedPath = normalizeRelativePathInput(displayPath);
            document.getElementById('resource_job_folder_id').value = String(folderId || '0');
            document.getElementById('resource_job_folder_path').value = normalizedPath || '根目录';
            document.getElementById('resource_job_savepath').value = normalizedPath;
            syncResourceMonitorTaskOptions(normalizedPath);
            if (loadPreview) loadResourceTargetPreview(folderId || '0');
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

        function openResourceModal(resourceId, mode = 'detail') {
            const item = findResourceItem(resourceId);
            if (!item) return;
            selectedResourceId = Number(item.id);
            selectedResourceItem = item;
            resourceModalMode = mode === 'import' ? 'import' : 'detail';
            resourceModalLinkType = getEffectiveResourceLinkType(item);
            document.getElementById('resource-import-poster').innerHTML = buildResourcePoster(item);
            document.getElementById('resource-import-title').innerText = item.title || '未命名资源';
            document.getElementById('resource-import-subtitle').innerText = `来源：${item.source_name || item.channel_name || '手动录入'} / 时间：${item.published_at ? formatTimeText(item.published_at) : formatTimeText(item.created_at)}`;
            document.getElementById('resource-import-meta').innerHTML = [
                buildResourceStatusBadge(item?.status),
                item?.quality ? `<span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/20">${escapeHtml(item.quality)}</span>` : '',
                item?.year ? `<span class="text-[10px] px-3 py-1 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/20">${escapeHtml(item.year)}</span>` : ''
            ].filter(Boolean).join('');
            document.getElementById('resource-import-link-actions').innerHTML = buildResourceImportLinkActions(item);
            document.getElementById('resource-import-raw-text').textContent = String(item.raw_text || item.title || '暂无可预览内容').trim();
            resourceFolderTrail = [{ id: '0', name: '根目录' }];
            resourceFolderEntries = [];
            resourceFolderSummary = { folder_count: 0, file_count: 0 };
            resourceTargetPreviewEntries = [];
            resourceTargetPreviewSummary = { folder_count: 0, file_count: 0 };
            resourceTargetPreviewLoading = false;
            resourceTargetPreviewError = '';
            resetResourceShareState();
            setSelectedResourceFolder('0', '', { loadPreview: false });
            document.getElementById('resource_job_refresh_delay_seconds').value = 4;
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceModalLayout(item);
            renderResourceShareBrowser();
            renderResourceImportSummary();
            document.getElementById('resource-import-modal').classList.remove('hidden');
            if (resourceModalMode === 'import' && resourceModalLinkType === '115share' && resourceState.cookie_configured) {
                loadResourceShareBranch(item.id, '0', { resetSelection: true });
            }
        }

        function openResourceDetailModal(resourceId) {
            openResourceModal(resourceId, 'detail');
        }

        function openResourceImportModal(resourceId) {
            openResourceModal(resourceId, 'import');
        }

        function closeResourceJobModal() {
            selectedResourceId = null;
            selectedResourceItem = null;
            resourceModalMode = 'detail';
            resourceModalLinkType = '';
            resetResourceShareState();
            document.getElementById('resource-import-modal').classList.add('hidden');
        }

        async function submitResourceJob() {
            if (!selectedResourceId) return alert('未选择资源');
            const selectionState = getResourceShareSelectionState();
            if (isCurrentResource115Share() && resourceShareRootLoaded && !selectionState.selected_ids.length) {
                return alert('请先至少勾选一个要转存的目录或文件');
            }
            const savepath = normalizeRelativePathInput(document.getElementById('resource_job_savepath').value.trim());
            if (!savepath) {
                return alert('请先选择一个非根目录的 115 保存目录');
            }
            const payload = {
                resource_id: selectedResourceId,
                savepath,
                refresh_delay_seconds: parseInt(document.getElementById('resource_job_refresh_delay_seconds').value || '0', 10) || 0,
                auto_refresh: true
            };
            if (isCurrentResource115Share()) {
                payload.share_selection = selectionState;
            }
            const res = await fetch('/resource/jobs/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (!res.ok || !data.ok) return alert(`❌ ${data.msg || '提交失败'}`);
            closeResourceJobModal();
            await refreshResourceState();
            const matchedTaskName = String(data.monitor_task_name || '').trim();
            const tail = matchedTaskName
                ? (data.auto_refresh ? `，保存完成后会自动触发“${matchedTaskName}”` : `，已匹配“${matchedTaskName}”，可稍后手动触发刷新`)
                : '，当前目录不会自动生成 strm';
            alert(`✅ 已创建导入任务 #${data.job_id}${tail}`);
        }

        async function deleteResourceItemRecord(resourceId) {
            if (!confirm('确定删除这条资源记录以及关联导入任务吗？')) return;
            const res = await fetch('/resource/items/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ id: resourceId })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) return alert(`❌ ${data.msg || '删除失败'}`);
            await refreshResourceState();
        }

        async function copyResourceRecord(resourceId) {
            const item = findResourceItem(resourceId);
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
                alert(`❌ ${e.message}`);
            } finally {
                resourceFolderLoading = false;
                renderResourceFolderBreadcrumbs();
                renderResourceFolderList();
            }
        }

        async function openResourceFolderModal() {
            document.getElementById('resource-folder-modal').classList.remove('hidden');
            renderResourceFolderBreadcrumbs();
            await loadResourceFolders(resourceFolderTrail[resourceFolderTrail.length - 1]?.id || '0');
        }

        function closeResourceFolderModal() {
            document.getElementById('resource-folder-modal').classList.add('hidden');
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
            setSelectedResourceFolder(current.id || '0', displayPath);
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
        document.getElementById('resource-search-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') searchResources();
        });
        document.getElementById('resource-status-filter').addEventListener('change', searchResources);
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
        document.getElementById('resource-channel-tabs').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-channel]');
            if (!btn) return;
            const nextChannelId = btn.dataset.resourceChannel === '__all__'
                ? ''
                : normalizeTelegramChannelIdInput(btn.dataset.resourceChannel || '');
            if (selectedResourceChannelId === nextChannelId) return;
            selectedResourceChannelId = nextChannelId;
            await refreshResourceState();
        });
        document.getElementById('resource-board').addEventListener('click', async (e) => {
            const toggleBtn = e.target.closest('[data-resource-section-toggle]');
            if (toggleBtn) {
                toggleResourceSection(toggleBtn.dataset.resourceSectionToggle || '');
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
            if (action === 'delete') await deleteResourceItemRecord(resourceId);
        });
        document.getElementById('resource-job-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-job-action]');
            if (!btn) return;
            const action = btn.dataset.resourceJobAction || '';
            const jobId = parseInt(btn.dataset.resourceJobId || '0', 10);
            if (!jobId) return;
            if (action === 'refresh') await triggerResourceJobRefresh(jobId);
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
        document.getElementById('resource-import-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-import-modal') closeResourceJobModal();
        });
        document.getElementById('resource-folder-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-folder-modal') closeResourceFolderModal();
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
        refreshMainLogs();
        refreshMonitorState();
        refreshResourceState();
        connectStatusStream();
        refreshVersionInfo();
        setInterval(() => refreshVersionInfo(false), VERSION_REFRESH_INTERVAL);
        setInterval(() => refreshResourceState(), RESOURCE_REFRESH_INTERVAL);
    
