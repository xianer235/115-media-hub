        let isRunning = false;
        let monitorState = { running: false, current_task: '', tasks: [], logs: [], summary: { step: '空闲', detail: '等待监控任务' }, queued: [], next_runs: {} };
        let subscriptionState = { running: false, current_task: '', tasks: [], logs: [], summary: { step: '空闲', detail: '等待订阅任务' }, queued: [], next_runs: {} };
        let sign115State = {
            enabled: false,
            cron_time: '09:00',
            next_run: '',
            running: false,
            state: 'idle',
            message: '尚未检查签到状态',
            signed_today: null,
            reward_leaf: 0,
            balance_leaf: null,
            last_checked_at: '',
            last_sign_at: '',
            last_trigger: ''
        };
        let resourceState = { sources: [], quick_links: [], items: [], jobs: [], channel_sections: [], channel_profiles: {}, search_sections: [], last_syncs: {}, monitor_tasks: [], stats: { source_count: 0, item_count: 0, filtered_item_count: 0, completed_job_count: 0 }, cookie_configured: false, quark_cookie_configured: false, setup_status: null, search: '', search_meta: {} };
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
        let subscriptionShareFolderTrail = [{ cid: '0', name: '分享根目录' }];
        let subscriptionShareFolderEntriesByParent = { '0': [] };
        let subscriptionShareFolderCurrentCid = '0';
        let subscriptionShareFolderLoading = false;
        let subscriptionShareFolderLoadingParents = {};
        let subscriptionShareFolderLoadingMoreParents = {};
        let subscriptionShareFolderNextOffsetByParent = { '0': 0 };
        let subscriptionShareFolderHasMoreByParent = {};
        let subscriptionShareFolderError = '';
        let subscriptionShareFolderInfo = { title: '', count: 0, share_code: '', receive_code: '' };
        let subscriptionShareFolderRootLoaded = false;
        let subscriptionShareFolderRequestToken = 0;
        let subscriptionShareFolderLinkFingerprint = '';
        let subscriptionTmdbSearchBusy = false;
        let subscriptionTmdbSearchToken = 0;
        let subscriptionTmdbResults = [];
        let subscriptionEpisodeViewTaskName = '';
        let subscriptionEpisodeViewLoading = false;
        let subscriptionEpisodeViewError = '';
        let subscriptionEpisodeViewData = null;
        let subscriptionEpisodeViewCache = {};
        let subscriptionEpisodeViewMode = 'absolute';
        let subscriptionIntroEpisodeLookupLoading = {};
        let subscriptionIntroEpisodeLookupFailedAt = {};
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
        let resourceShareLoadingMoreParents = {};
        let resourceShareNextOffsetByParent = { '0': 0 };
        let resourceShareHasMoreByParent = {};
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
        let resourceBatchImportItems = [];
        let resourceClientIdSeed = -100000;
        let resourceClientIdsByIdentity = {};
        let resourceJobModalOpen = false;
        let resourceJobClearMenuOpen = false;
        let resourceQuickLinkModalOpen = false;
        let resourceSourceModalOpen = false;
        let resourceSourceImportModalOpen = false;
        let resourceSourceManagerOpen = false;
        let resourceChannelManageModalOpen = false;
        let resourceChannelManageSourceIndex = -1;
        let resourceChannelManageChannelId = '';
        let resourceQuickLinks = [];
        let resourceQuickLinksMigrationChecked = false;
        let editingResourceQuickLinkId = '';
        let resourceSourceFilter = 'all';
        let resourceSourceEnabledFilter = 'all';
        let resourceSourceActivityFilter = 'all';
        let resourceSourceKeyword = '';
        let resourceSourceSortMode = 'recent';
        let resourceSourceBulkSelected = {};
        let resourceSourceManagerMobilePanel = 'list';
        let resourceSourceTestBusy = false;
        let resourceSourceTestResult = { total: 0, done: 0, success: 0, failed: 0, running: false, last_name: '', error: '' };
        let resourceSubmitBusy = false;
        let resourceJobFilter = 'all';
        let resourceImportLastFeedback = null;
        let tgProxyTestState = { loading: false, ok: null, message: '', latency_ms: 0, mode: '', proxy_url: '', target_url: '' };
        let notifyTestState = { loading: false, ok: null, message: '', channel: '', target_desc: '', webhook_host: '', sent_at: '' };
        let resourceBoardHintText = '';
        let resourceTgHealthState = { visible: false, tone: 'loading', title: '', meta: '', note: '' };
        let resourceTgLastLatencyMs = 0;
        let lastLogSignature = '';
        let lastMonitorLogSignature = '';
        let lastSubscriptionLogSignature = '';
        let lastMonitorRenderKey = '';
        let lastSubscriptionRenderKey = '';
        let monitorTaskIntroExpanded = {};
        let subscriptionTaskIntroExpanded = {};
        let statusEventSource = null;
        let statusFallbackTimer = null;
        const monitorActionLocks = new Set();
        let versionInfo = { local: null, latest: null, has_update: false, checked_at: 0, error: '', source: '' };
        let versionBannerDismissed = false;
        let currentTab = 'resource';
        const moduleScrollTopState = {
            resource: 0,
            subscription: 0,
            monitor: 0,
            task: 0,
            settings: 0,
            about: 0
        };
        let shellMoreMenuOpen = false;
        let shellRailExpanded = false;
        let aboutWorkflowImageLoaded = false;
        let aboutWorkflowImageLoadingPromise = null;
        let modalScrollLockCount = 0;
        let modalScrollLockY = 0;
        let viewportMetricsRafId = 0;
        const moduleVisitState = {
            resource: true,
            subscription: false,
            monitor: false,
            task: false,
            settings: false,
            about: false
        };
        const SHELL_TAB_META = {
            resource: { title: '资源中心' },
            subscription: { title: '影视订阅' },
            monitor: { title: '文件夹监控' },
            task: { title: '目录树任务' },
            settings: { title: '参数配置' },
            about: { title: '关于与版本' }
        };
        const btnTexts = ["🌐 联网同步更新", "🛠 本地调试解析", "🔥 强制全量重刷"];
        const DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,wmv,flv,webm,vob,mpg,mpeg,ts,m2ts,mts,rmvb,rm,asf,3gp,m4v,f4v,iso";
        const STATUS_FALLBACK_INTERVAL = 15000;
        const RESOURCE_REFRESH_INTERVAL = 15000;
        const VERSION_REFRESH_INTERVAL = 1000 * 60 * 15;
        const SIGN115_REFRESH_INTERVAL = 1000 * 60;
        const VERSION_FALLBACK_PROJECT_URL = 'https://github.com/xianer235/115-media-hub';
        const VERSION_FALLBACK_CHANGELOG_URL = 'https://github.com/xianer235/115-media-hub/blob/main/CHANGELOG.md';
        const ABOUT_WORKFLOW_IMAGE_URL = '/static/images/about-workflow-cookie-openlist.png';
        const RESOURCE_FOLDER_MEMORY_KEY = 'resource-folder-selection-v1';
        const RESOURCE_IMPORT_DELAY_MEMORY_KEY = 'resource-import-delay-seconds-v1';
        const RESOURCE_QUICK_LINKS_MEMORY_KEY = 'resource-quick-links-v1';
        const RESOURCE_QUICK_LINKS_LIMIT = 60;
        const MAIN_TAB_ROW_HINT_MEMORY_KEY = 'main-tab-row-hint-v1';
        const SHELL_RAIL_EXPANDED_MEMORY_KEY = 'shell-rail-expanded-v1';
        const TOAST_DEFAULT_DURATION_MS = 3000;
        const SUBSCRIPTION_EPISODE_CACHE_TTL_MS = 1000 * 60 * 3;
        const SUBSCRIPTION_INTRO_EPISODE_RETRY_MS = 1000 * 60;
        const RESOURCE_SHARE_BROWSE_PAGE_LIMIT = 200;
        const SUBSCRIPTION_WEEKDAY_LABELS = {
            1: '周一',
            2: '周二',
            3: '周三',
            4: '周四',
            5: '周五',
            6: '周六',
            7: '周日'
        };
        const SUBSCRIPTION_DEFAULT_WEEKDAYS = [1, 2, 3, 4, 5, 6, 7];

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

        function syncViewportMetrics() {
            const viewportHeight = Math.max(
                0,
                window.visualViewport?.height || window.innerHeight || document.documentElement.clientHeight || 0,
            );
            if (!viewportHeight) return;
            document.documentElement.style.setProperty('--app-vh', `${viewportHeight}px`);
        }

        function requestViewportMetricsSync() {
            if (viewportMetricsRafId) return;
            viewportMetricsRafId = window.requestAnimationFrame(() => {
                viewportMetricsRafId = 0;
                syncViewportMetrics();
            });
        }

        function syncShellHeader(tab = currentTab) {
            const meta = SHELL_TAB_META[tab] || SHELL_TAB_META.resource;
            const titleEl = document.getElementById('shell-current-title');
            if (titleEl) titleEl.innerText = meta.title;
        }

        function readShellRailExpandedFromStorage() {
            try {
                return localStorage.getItem(SHELL_RAIL_EXPANDED_MEMORY_KEY) === '1';
            } catch (e) {
                return false;
            }
        }

        function applyShellRailState(expanded = shellRailExpanded) {
            shellRailExpanded = !!expanded;
            const shell = document.querySelector('[data-app-shell]');
            const toggle = document.getElementById('shell-rail-toggle');
            if (shell) shell.dataset.shellExpanded = shellRailExpanded ? 'true' : 'false';
            document.body.classList.toggle('shell-rail-expanded', shellRailExpanded);
            if (toggle) {
                const label = shellRailExpanded ? '收起侧边栏' : '展开侧边栏';
                toggle.setAttribute('aria-expanded', shellRailExpanded ? 'true' : 'false');
                toggle.setAttribute('aria-label', label);
                toggle.title = label;
            }
        }

        function toggleShellRail(force = null) {
            shellRailExpanded = typeof force === 'boolean' ? force : !shellRailExpanded;
            try {
                localStorage.setItem(SHELL_RAIL_EXPANDED_MEMORY_KEY, shellRailExpanded ? '1' : '0');
            } catch (e) {}
            applyShellRailState(shellRailExpanded);
        }

        function syncShellMoreMenuState() {
            const menu = document.getElementById('shell-more-menu');
            const toggle = document.getElementById('shell-more-toggle');
            if (menu) menu.classList.toggle('hidden', !shellMoreMenuOpen);
            if (toggle) toggle.setAttribute('aria-expanded', shellMoreMenuOpen ? 'true' : 'false');
        }

        function closeShellMoreMenu() {
            if (!shellMoreMenuOpen) return;
            shellMoreMenuOpen = false;
            syncShellMoreMenuState();
        }

        function toggleShellMoreMenu(force = null) {
            shellMoreMenuOpen = typeof force === 'boolean' ? force : !shellMoreMenuOpen;
            syncShellMoreMenuState();
        }

        function syncMainTabRowState() {
            document.querySelectorAll('[data-tab-target]').forEach((button) => {
                const target = String(button.dataset.tabTarget || '').trim();
                const active = target === currentTab;
                button.classList.toggle('is-active', active);
                button.setAttribute('aria-current', active ? 'page' : 'false');
            });
            syncShellHeader(currentTab);
        }

        function focusMainTab(tab, behavior = 'smooth') {
            const button = document.getElementById(`tab-${tab}`) || document.querySelector(`[data-tab-target="${tab}"]`);
            if (!button) return;
            button.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior });
        }

        function scrollMainTabs() {}

        function nudgeMainTabRowOnFirstVisit() {}

        function initMainTabRow() {
            shellRailExpanded = readShellRailExpandedFromStorage();
            applyShellRailState(shellRailExpanded);
            syncMainTabRowState();
            syncShellMoreMenuState();
            focusMainTab('resource', 'auto');
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

        async function ensureTabData(tab) {
            if (tab === 'resource') {
                moduleVisitState.resource = true;
                await refreshResourceState();
                return;
            }
            if (tab === 'subscription' && !moduleVisitState.subscription) {
                await refreshSubscriptionState();
                moduleVisitState.subscription = true;
                return;
            }
            if (tab === 'monitor' && !moduleVisitState.monitor) {
                await refreshMonitorState();
                moduleVisitState.monitor = true;
                return;
            }
            if (tab === 'task' && !moduleVisitState.task) {
                await refreshMainLogs();
                moduleVisitState.task = true;
                return;
            }
            if (tab === 'settings') {
                moduleVisitState.settings = true;
                return;
            }
            if (tab === 'about') {
                if (!versionInfo?.checked_at) await refreshVersionInfo(false);
                moduleVisitState.about = true;
            }
        }

        async function switchTab(tab) {
            const nextTab = SHELL_TAB_META[tab] ? tab : 'resource';
            const prevTab = currentTab;
            moduleScrollTopState[prevTab] = Math.max(0, window.scrollY || window.pageYOffset || 0);
            currentTab = nextTab;
            ['task', 'resource', 'subscription', 'settings', 'monitor', 'about'].forEach(name => {
                const page = document.getElementById(`page-${name}`);
                if (page) page.classList.toggle('hidden', nextTab !== name);
            });
            if (nextTab !== 'resource') toggleResourceJobModal(false);
            closeShellMoreMenu();
            syncMainTabRowState();
            await ensureTabData(nextTab);
            const targetScrollTop = Math.max(0, Number(moduleScrollTopState[nextTab] || 0));
            window.scrollTo(0, targetScrollTop);
            syncResourceBackTopButton();
            syncSettingsSaveDock();
            focusMainTab(nextTab);
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

        function parseTaskDividerText(text) {
            const raw = String(text || '').trim();
            const match = raw.match(/^(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+[-—━]{3,}\s*(.*?)\s*[-—━]{3,}\s*$/u);
            if (!match) return null;
            return {
                timestamp: String(match[1] || ''),
                label: String(match[2] || '')
            };
        }

        function getTaskDividerTone(label) {
            const raw = String(label || '').trim();
            if (!raw) return '';
            if (/(任务开始|订阅开始)/.test(raw)) return 'start';
            if (/(执行成功|订阅成功|已完成|完成)/.test(raw)) return 'success';
            if (/(已中断|中断|取消)/.test(raw)) return 'warn';
            if (/(执行失败|失败|异常|错误)/.test(raw)) return 'error';
            return '';
        }

        function getLogEntryClass(item) {
            const level = item?.level || 'info';
            if (level !== 'task-divider') return `log-${level}`;
            const parsed = parseTaskDividerText(item?.text || '');
            const tone = getTaskDividerTone(parsed?.label || item?.text || '');
            return ['log-task-divider', tone ? `log-task-divider-${tone}` : ''].filter(Boolean).join(' ');
        }

        function formatMonitorTaskDividerHtml(text) {
            const raw = String(text || '').trim();
            const parsed = parseTaskDividerText(raw);
            if (!parsed) return escapeHtml(raw);

            const timestamp = escapeHtml(parsed.timestamp || '');
            const label = escapeHtml(parsed.label || '');
            return `
                <span class="log-task-divider-time">${timestamp}</span>
                <span class="log-task-divider-rule" aria-hidden="true"></span>
                <span class="log-task-divider-label">${label}</span>
                <span class="log-task-divider-rule" aria-hidden="true"></span>
            `;
        }

        function formatMonitorLogHtml(item) {
            const level = item?.level || 'info';
            const text = String(item?.text || '');
            if (level === 'task-divider') return formatMonitorTaskDividerHtml(text);
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

        function pruneTaskIntroExpanded(expandedMap, tasks) {
            const validNames = new Set(
                (Array.isArray(tasks) ? tasks : [])
                    .map(item => String(item?.name || '').trim())
                    .filter(Boolean)
            );
            const next = {};
            Object.keys(expandedMap || {}).forEach((name) => {
                if (validNames.has(name) && expandedMap[name]) next[name] = true;
            });
            return next;
        }

        function isTaskIntroExpanded(expandedMap, taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return false;
            return !!expandedMap?.[normalizedName];
        }

        function toggleTaskIntroExpanded(expandedMap, taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return expandedMap;
            const next = { ...(expandedMap || {}) };
            if (next[normalizedName]) delete next[normalizedName];
            else next[normalizedName] = true;
            return next;
        }

        function normalizeSign115State(data) {
            const payload = data || {};
            return {
                ...sign115State,
                ...payload,
                enabled: !!payload?.enabled,
                running: !!payload?.running,
                state: String(payload?.state || sign115State.state || 'idle'),
                message: String(payload?.message || sign115State.message || ''),
                cron_time: String(payload?.cron_time || sign115State.cron_time || '09:00'),
                next_run: String(payload?.next_run || ''),
                reward_leaf: Math.max(0, Number(payload?.reward_leaf || 0) || 0),
                balance_leaf: payload?.balance_leaf === null || payload?.balance_leaf === undefined
                    ? null
                    : Math.max(0, Number(payload?.balance_leaf || 0) || 0),
                signed_today: payload?.signed_today === null || payload?.signed_today === undefined
                    ? null
                    : !!payload?.signed_today,
                last_checked_at: String(payload?.last_checked_at || ''),
                last_sign_at: String(payload?.last_sign_at || ''),
                last_trigger: String(payload?.last_trigger || '')
            };
        }

        function renderSign115Indicator() {
            const chip = document.getElementById('sign115-indicator');
            const textEl = document.getElementById('sign115-indicator-text');
            const menuLabelEl = document.getElementById('shell-more-sign-label');
            if (!chip || !textEl) return;

            const state = String(sign115State.state || 'idle');
            const enabled = !!sign115State.enabled;
            const running = !!sign115State.running;
            const rewardLeaf = Math.max(0, Number(sign115State.reward_leaf || 0) || 0);
            const balanceLeaf = sign115State.balance_leaf === null || sign115State.balance_leaf === undefined
                ? null
                : Math.max(0, Number(sign115State.balance_leaf || 0) || 0);

            const toneClasses = [
                'bg-slate-700/50',
                'text-slate-100',
                'border-slate-500/40',
                'hover:bg-slate-600'
            ];
            let label = '签到';
            let tone = 'idle';
            if (running || state === 'checking') {
                label = '签中';
                tone = 'checking';
                toneClasses.splice(0, toneClasses.length, 'bg-sky-500/20', 'text-sky-200', 'border-sky-400/40', 'hover:bg-sky-500/30');
            } else if (state === 'signed' || sign115State.signed_today === true) {
                label = '已签';
                tone = 'signed';
                toneClasses.splice(0, toneClasses.length, 'bg-emerald-500/20', 'text-emerald-200', 'border-emerald-400/40', 'hover:bg-emerald-500/30');
            } else if (state === 'unsigned' || sign115State.signed_today === false) {
                label = '未签';
                tone = 'unsigned';
                toneClasses.splice(0, toneClasses.length, 'bg-amber-500/20', 'text-amber-200', 'border-amber-400/40', 'hover:bg-amber-500/30');
            } else if (state === 'error') {
                label = '异常';
                tone = 'error';
                toneClasses.splice(0, toneClasses.length, 'bg-rose-500/20', 'text-rose-200', 'border-rose-400/40', 'hover:bg-rose-500/30');
            }

            textEl.innerText = label;
            if (menuLabelEl) menuLabelEl.innerText = label;
            chip.dataset.signTone = tone;
            chip.classList.remove(
                'bg-slate-700/50', 'text-slate-100', 'border-slate-500/40', 'hover:bg-slate-600',
                'bg-sky-500/20', 'text-sky-200', 'border-sky-400/40', 'hover:bg-sky-500/30',
                'bg-emerald-500/20', 'text-emerald-200', 'border-emerald-400/40', 'hover:bg-emerald-500/30',
                'bg-amber-500/20', 'text-amber-200', 'border-amber-400/40', 'hover:bg-amber-500/30',
                'bg-rose-500/20', 'text-rose-200', 'border-rose-400/40', 'hover:bg-rose-500/30'
            );
            chip.classList.add(...toneClasses);

            const titleBits = [];
            if (sign115State.message) titleBits.push(sign115State.message);
            if (rewardLeaf > 0) titleBits.push(`本次获得：${rewardLeaf} 枫叶`);
            if (balanceLeaf !== null) titleBits.push(`当前枫叶：${balanceLeaf}`);
            if (sign115State.next_run) titleBits.push(`下次自动签到：${sign115State.next_run}`);
            if (!enabled) titleBits.push('定时签到未启用，可手动点击签到');
            chip.title = titleBits.join(' | ') || '115 每日签到状态';
        }

        function renderSign115SettingsHint() {
            const hintEl = document.getElementById('sign115-settings-hint');
            const cardEl = document.getElementById('sign115-settings-status-card');
            if (!hintEl) return;
            const bits = [];
            let tone = 'idle';
            if (sign115State.running || sign115State.state === 'checking') {
                bits.push('正在执行签到...');
                tone = 'checking';
            } else if (sign115State.state === 'signed' || sign115State.signed_today === true) {
                bits.push('今天已签到');
                tone = 'signed';
            } else if (sign115State.state === 'unsigned' || sign115State.signed_today === false) {
                bits.push('今天未签到');
                tone = 'unsigned';
            } else if (sign115State.state === 'error') {
                bits.push('签到异常');
                tone = 'error';
            }
            if (!sign115State.enabled) bits.push('未启用定时签到（可手动签到）');
            if (sign115State.reward_leaf > 0) bits.push(`本次获得 ${Math.max(0, Number(sign115State.reward_leaf || 0))} 枫叶`);
            if (sign115State.balance_leaf !== null && sign115State.balance_leaf !== undefined) {
                bits.push(`当前枫叶 ${Math.max(0, Number(sign115State.balance_leaf || 0))}`);
            }
            if (sign115State.next_run) bits.push(`下次自动签到 ${sign115State.next_run}`);
            if (sign115State.message) bits.push(sign115State.message);
            if (cardEl) cardEl.dataset.signTone = tone;
            hintEl.innerText = bits.join('；') || '尚未检查签到状态';
        }

        function applySign115State(data) {
            if (!data) return;
            sign115State = normalizeSign115State(data);
            renderSign115Indicator();
            renderSign115SettingsHint();
        }

        async function refreshSign115Status(force = false) {
            try {
                const endpoint = force ? '/settings/115/sign/status?refresh=1' : '/settings/115/sign/status';
                const res = await fetch(endpoint);
                if (!res.ok) return;
                const data = await res.json();
                applySign115State(data);
            } catch (err) {
                console.warn('Sign115 status refresh failed', err);
            }
        }

        async function manualSign115(notify = false) {
            if (sign115State.running) return;
            try {
                const res = await fetch('/settings/115/sign/run', { method: 'POST' });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    if (data?.state) applySign115State(data.state);
                    if (notify) showToast(`签到失败：${data?.msg || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                    return;
                }
                if (data?.state) applySign115State(data.state);
                if (notify) {
                    const message = String(data?.state?.message || '签到完成');
                    showToast(message, { tone: 'success', duration: 3000, placement: 'top-center' });
                }
            } catch (err) {
                if (notify) showToast(`签到失败：${err?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        function applyMainState(data) {
            if (!data) return;
            if (data.running !== isRunning) updateButtonState(!!data.running);

            const logBox = document.getElementById('log-box');
            const logs = Array.isArray(data.logs) ? data.logs : [];
            const logSignature = buildLogSignature(logs, (item) => `${item?.level || 'info'}:${item?.text || ''}`);
            if (logSignature !== lastLogSignature) {
                logBox.innerHTML = logs.map(item => `<div class="${getLogEntryClass(item)}">${formatMonitorLogHtml(item)}</div>`).join('');
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
            monitorTaskIntroExpanded = pruneTaskIntroExpanded(monitorTaskIntroExpanded, monitorState.tasks);

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
                refreshSign115Status(false);
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
                    applySign115State(payload.sign115);
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

        async function ensureAboutWorkflowImageLoaded() {
            if (aboutWorkflowImageLoaded) return true;
            if (aboutWorkflowImageLoadingPromise) return aboutWorkflowImageLoadingPromise;

            const modalImage = document.getElementById('about-workflow-modal-image');
            const loadingEl = document.getElementById('about-workflow-modal-loading');
            const errorEl = document.getElementById('about-workflow-modal-error');
            if (!modalImage) return false;

            if (loadingEl) loadingEl.classList.remove('hidden');
            if (errorEl) errorEl.classList.add('hidden');

            const targetSrc = String(modalImage.dataset.src || ABOUT_WORKFLOW_IMAGE_URL).trim() || ABOUT_WORKFLOW_IMAGE_URL;
            aboutWorkflowImageLoadingPromise = new Promise((resolve) => {
                let done = false;
                const finish = (ok) => {
                    if (done) return;
                    done = true;
                    if (ok) {
                        aboutWorkflowImageLoaded = true;
                        if (loadingEl) loadingEl.classList.add('hidden');
                        if (errorEl) errorEl.classList.add('hidden');
                        modalImage.classList.remove('hidden');
                    } else {
                        if (loadingEl) loadingEl.classList.add('hidden');
                        if (errorEl) errorEl.classList.remove('hidden');
                    }
                    aboutWorkflowImageLoadingPromise = null;
                    resolve(ok);
                };

                const handleLoad = () => finish(true);
                const handleError = () => finish(false);

                modalImage.addEventListener('load', handleLoad, { once: true });
                modalImage.addEventListener('error', handleError, { once: true });

                if (!modalImage.src) {
                    modalImage.src = targetSrc;
                }
                if (modalImage.complete) {
                    if (modalImage.naturalWidth > 0) finish(true);
                    else finish(false);
                }
            });

            return aboutWorkflowImageLoadingPromise;
        }

        function openAboutWorkflowModal() {
            showLockedModal('about-workflow-modal');
            void ensureAboutWorkflowImageLoaded();
        }

        function closeAboutWorkflowModal() {
            hideLockedModal('about-workflow-modal');
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

        function getCurrentNotifyConfig() {
            return {
                notify_push_enabled: document.getElementById('notify_push_enabled').checked,
                notify_monitor_enabled: document.getElementById('notify_monitor_enabled').checked,
                notify_channel: document.getElementById('notify_channel').value.trim(),
                notify_wecom_webhook: document.getElementById('notify_wecom_webhook').value.trim(),
                notify_wecom_app_corp_id: document.getElementById('notify_wecom_app_corp_id').value.trim(),
                notify_wecom_app_agent_id: document.getElementById('notify_wecom_app_agent_id').value.trim(),
                notify_wecom_app_secret: document.getElementById('notify_wecom_app_secret').value.trim(),
                notify_wecom_app_touser: document.getElementById('notify_wecom_app_touser').value.trim()
            };
        }

        function notifyChannelLabel(value) {
            const key = String(value || '').trim().toLowerCase();
            if (key === 'wecom_app') return '企业微信应用 API';
            return '企业微信群机器人';
        }

        function syncNotifyChannelUI() {
            const channel = String(document.getElementById('notify_channel')?.value || 'wecom_bot').trim().toLowerCase();
            const botFields = document.getElementById('notify-bot-fields');
            const appFields = document.getElementById('notify-app-fields');
            if (botFields) botFields.classList.toggle('hidden', channel !== 'wecom_bot');
            if (appFields) appFields.classList.toggle('hidden', channel === 'wecom_bot');
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

        function renderNotifyTestStatus() {
            const btn = document.getElementById('notify-test-btn');
            const statusEl = document.getElementById('notify-test-status');
            if (btn) {
                btn.disabled = notifyTestState.loading;
                btn.classList.toggle('btn-disabled', notifyTestState.loading);
                btn.textContent = notifyTestState.loading ? '发送中...' : '发送测试消息';
            }
            if (!statusEl) return;

            if (notifyTestState.loading) {
                statusEl.className = 'tg-proxy-status tg-proxy-status--loading';
                statusEl.innerHTML = `
                    <div class="tg-proxy-status-title">正在发送测试消息</div>
                    <div class="tg-proxy-status-meta">请稍候，正在请求企业微信通知接口...</div>
                `;
                statusEl.classList.remove('hidden');
                return;
            }

            if (notifyTestState.ok === true) {
                const channelLabel = notifyChannelLabel(notifyTestState.channel || document.getElementById('notify_channel')?.value || '');
                statusEl.className = 'tg-proxy-status tg-proxy-status--success';
                statusEl.innerHTML = `
                    <div class="tg-proxy-status-title">测试消息发送成功</div>
                    <div class="tg-proxy-status-meta">${escapeHtml(notifyTestState.message || '通知配置可用')}</div>
                    <div class="tg-proxy-status-note">渠道：${escapeHtml(channelLabel)}｜目标：${escapeHtml(notifyTestState.target_desc || notifyTestState.webhook_host || '--')}</div>
                `;
                statusEl.classList.remove('hidden');
                return;
            }

            if (notifyTestState.ok === false) {
                statusEl.className = 'tg-proxy-status tg-proxy-status--error';
                statusEl.innerHTML = `
                    <div class="tg-proxy-status-title">测试消息发送失败</div>
                    <div class="tg-proxy-status-meta">${escapeHtml(notifyTestState.message || '未知错误')}</div>
                `;
                statusEl.classList.remove('hidden');
                return;
            }

            statusEl.classList.add('hidden');
            statusEl.textContent = '';
        }

        async function testNotifyPush() {
            if (notifyTestState.loading) return;
            notifyTestState = { loading: true, ok: null, message: '', channel: '', target_desc: '', webhook_host: '', sent_at: '' };
            renderNotifyTestStatus();
            try {
                const res = await fetch('/settings/notify/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(getCurrentNotifyConfig())
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '测试消息发送失败');
                notifyTestState = {
                    loading: false,
                    ok: true,
                    message: String(data.msg || '测试消息已发送'),
                    channel: String(data.channel || ''),
                    target_desc: String(data.target_desc || ''),
                    webhook_host: String(data.webhook_host || ''),
                    sent_at: String(data.sent_at || '')
                };
            } catch (e) {
                notifyTestState = {
                    loading: false,
                    ok: false,
                    message: e instanceof Error ? e.message : String(e || '测试消息发送失败'),
                    channel: '',
                    target_desc: '',
                    webhook_host: '',
                    sent_at: ''
                };
            }
            renderNotifyTestStatus();
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
                'cookie_quark',
                'sign115_cron_time',
                'tg_proxy_protocol',
                'tg_proxy_host',
                'tg_proxy_port',
                'notify_channel',
                'notify_wecom_webhook',
                'notify_wecom_app_corp_id',
                'notify_wecom_app_agent_id',
                'notify_wecom_app_secret',
                'notify_wecom_app_touser',
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
            cfg.sign115_enabled = document.getElementById('sign115_enabled').checked;
            cfg.tg_proxy_enabled = document.getElementById('tg_proxy_enabled').checked;
            cfg.notify_push_enabled = document.getElementById('notify_push_enabled').checked;
            cfg.notify_monitor_enabled = document.getElementById('notify_monitor_enabled').checked;
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
                await refreshResourceState({ allowSearch: false });
                alert('✅ 配置已保存');
                refreshSign115Status(false);
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
            showLockedModal('monitor-modal');
        }

        function closeMonitorModal() {
            hideLockedModal('monitor-modal');
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
            showLockedModal('monitor-modal');
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
                const clearedCount = Math.max(0, Number(data.cleared || 0));
                let detailText = `${name} 已发送中断请求`;
                if (data.status === 'cleared') {
                    detailText = `${name} 未在运行，已清空排队 ${clearedCount} 项`;
                } else if (data.status === 'stopping_and_cleared' && clearedCount > 0) {
                    detailText = `${name} 已发送中断请求，并清空排队 ${clearedCount} 项`;
                }
                applyMonitorState({
                    ...monitorState,
                    summary: { step: '正在中断', detail: detailText }
                }, { forceRender: true });
                await refreshMonitorState();
            } finally {
                setMonitorActionLock('stop', name, false);
            }
        }

        function buildMonitorTaskIntro(task, { running = false, queued = false, nextRun = '' } = {}) {
            const statusText = running ? '运行中' : (queued ? '已排队' : '待命');
            const scanPath = String(task?.scan_path || '').trim() || '--';
            const targetPath = String(task?.target_path || '').trim() || '--';
            const modeText = task?.incremental ? '增量刷新' : '全量刷新';
            const scheduleMinutes = Math.max(0, Number(task?.cron_minutes || 0) || 0);
            const scheduleText = scheduleMinutes > 0
                ? `每 ${scheduleMinutes} 分钟自动执行一次，下次定时 ${String(nextRun || '计算中')}`
                : '未开启定时，仅手动运行或通过 Webhook 触发';
            const webhookText = task?.webhook_enabled ? '已启用 Webhook 触发' : '未启用 Webhook';
            return `状态：${statusText}。该任务会扫描 ${scanPath}，输出到 /strm/${targetPath}，采用 ${modeText} 策略；${scheduleText}；${webhookText}。`;
        }

        function toggleMonitorTaskIntro(taskName) {
            monitorTaskIntroExpanded = toggleTaskIntroExpanded(monitorTaskIntroExpanded, taskName);
            renderMonitorTasks();
        }

        function renderMonitorTasks() {
            const container = document.getElementById('monitor-task-list');
            const tasks = monitorState.tasks || [];
            if (!tasks.length) {
                container.innerHTML = `<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">还没有文件夹监控任务，点击“新增任务”即可创建。</div>`;
                return;
            }

            container.innerHTML = tasks.map(task => {
                const taskName = String(task?.name || '').trim();
                const taskKey = encodeURIComponent(taskName);
                const running = monitorState.running && monitorState.current_task === taskName;
                const queued = (monitorState.queued || []).includes(taskName);
                const starting = isMonitorActionLocked('start', taskName);
                const stopping = isMonitorActionLocked('stop', taskName);
                const deleting = isMonitorActionLocked('delete', taskName);
                const startDisabled = monitorState.running || starting || stopping || deleting;
                const stopDisabled = !running || starting || stopping || deleting;
                const deleteDisabled = running || starting || stopping || deleting;
                const nextRun = (monitorState.next_runs || {})[taskName];
                const introExpanded = isTaskIntroExpanded(monitorTaskIntroExpanded, taskName);
                const introText = buildMonitorTaskIntro(task, { running, queued, nextRun });
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-3 sm:p-4">
                        <div class="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
                            <div class="min-w-0 flex-1 flex items-center justify-between gap-3">
                                <button
                                    type="button"
                                    data-monitor-toggle-intro="${taskKey}"
                                    aria-expanded="${introExpanded ? 'true' : 'false'}"
                                    class="min-w-0 flex-1 text-left rounded-lg border border-transparent hover:border-slate-700/75 focus:outline-none focus:ring-2 focus:ring-sky-500/45 px-1 py-0.5"
                                >
                                    <div class="text-lg font-black text-white break-all leading-tight">${escapeHtml(taskName)}</div>
                                </button>
                                <button
                                    type="button"
                                    data-monitor-toggle-intro="${taskKey}"
                                    aria-expanded="${introExpanded ? 'true' : 'false'}"
                                    class="shrink-0 text-[11px] sm:text-xs font-bold text-sky-300 hover:text-sky-200 hover:underline underline-offset-2 rounded-lg px-1.5 py-1 focus:outline-none focus:ring-2 focus:ring-sky-500/45"
                                >${introExpanded ? '收起简介' : '展开简介'}</button>
                            </div>
                            <div class="monitor-task-actions grid grid-cols-4 gap-2 shrink-0 w-full lg:w-auto">
                                <button type="button" data-monitor-action="start" data-task-name="${taskKey}" class="px-2 sm:px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold ${startDisabled ? 'btn-disabled' : ''}" ${startDisabled ? 'disabled' : ''}>${starting ? '启动中...' : '运行'}</button>
                                <button type="button" data-monitor-action="stop" data-task-name="${taskKey}" class="px-2 sm:px-3 py-2 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 text-sm font-bold ${stopDisabled ? 'btn-disabled' : ''}" ${stopDisabled ? 'disabled' : ''}>${stopping ? '中断中...' : '中断'}</button>
                                <button type="button" data-monitor-action="edit" data-task-name="${taskKey}" class="px-2 sm:px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">编辑</button>
                                <button type="button" data-monitor-action="delete" data-task-name="${taskKey}" class="px-2 sm:px-3 py-2 rounded-xl bg-red-500/15 hover:bg-red-500/25 text-red-300 text-sm font-bold ${deleteDisabled ? 'btn-disabled' : ''}" ${deleteDisabled ? 'disabled' : ''}>${deleting ? '删除中...' : '删除'}</button>
                            </div>
                        </div>
                        ${introExpanded ? `<div class="mt-3 text-xs text-slate-300 leading-6 rounded-xl border border-slate-700/90 bg-slate-950/45 px-3 py-2">${escapeHtml(introText)}</div>` : ''}
                    </div>
                `;
            }).join('');
        }

        function renderMonitorLogs() {
            const box = document.getElementById('monitor-log-box');
            const logs = monitorState.logs || [];
            const logSignature = buildLogSignature(logs, (item) => `${item?.level || 'info'}:${item?.text || ''}`);
            if (logSignature === lastMonitorLogSignature) return;
            box.innerHTML = logs.map(item => `<div class="${getLogEntryClass(item)}">${formatMonitorLogHtml(item)}</div>`).join('');
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
            renderSubscriptionLogs();
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
            const providerText = provider === 'quark' ? '夸克' : '115';
            const titleText = String(task?.title || task?.name || '').trim() || '未命名影视';
            const savepath = String(task?.savepath || '').trim() || '--';
            const fixedShareLink = String(task?.share_link_url || '').trim();
            const fixedLinkChannelSearch = !!task?.fixed_link_channel_search;
            const shareSubdir = normalizeRelativePathInput(task?.share_subdir || '');
            const shareSubdirCid = normalizeShareCidInput(task?.share_subdir_cid || '');
            const scheduleWeekdays = normalizeSubscriptionWeekdays(task?.schedule_weekdays || []);
            const scheduleStartTime = normalizeSubscriptionScheduleTime(task?.schedule_start_time || '00:00', '00:00');
            const scheduleEndTime = normalizeSubscriptionScheduleTime(task?.schedule_end_time || '23:59', '23:59');
            const scheduleIntervalMinutes = Math.max(1, Number(task?.schedule_interval_minutes || task?.cron_minutes || 30) || 30);
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
            const latestMatched = String(task?.matched_resource_title || '').trim();
            const latestText = latestMatched ? `最近命中：${latestMatched}` : '最近尚未命中资源';
            const modeText = isTv ? (multiSeasonMode ? '多季合一追更' : '单季追更') : '命中资源后即执行';
            const fixedShareText = provider === '115' && fixedShareLink
                ? `，固定分享链接模式${fixedLinkChannelSearch ? '（频道补搜兜底）' : ''}`
                : '';
            const shareScopeText = provider === '115' && shareSubdir
                ? `，分享子目录 ${shareSubdir}${shareSubdirCid ? `（CID ${shareSubdirCid}）` : ''}`
                : (provider === '115' && shareSubdirCid ? `，分享子目录 CID ${shareSubdirCid}` : '');
            const providerRuleText = provider === 'quark' ? '，仅频道自动匹配（不使用固定分享链接）' : '';
            return `状态：${statusText}（${enabledText}）。${providerText} · ${mediaText}《${titleText}》保存到 ${savepath}${fixedShareText}${shareScopeText}${providerRuleText}，${modeText}，${episodeText}；${scheduleText}；${latestText}。`;
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
            const logSignature = buildLogSignature(logs, (item) => `${item?.level || 'info'}:${item?.text || ''}`);
            if (logSignature === lastSubscriptionLogSignature) return;
            box.innerHTML = logs.map(item => `<div class="${getLogEntryClass(item)}">${formatMonitorLogHtml(item)}</div>`).join('');
            box.scrollTop = box.scrollHeight;
            lastSubscriptionLogSignature = logSignature;
        }

        function normalizeSubscriptionMediaType(value) {
            const normalized = String(value || 'movie').trim().toLowerCase();
            return normalized === 'tv' ? 'tv' : 'movie';
        }

        function normalizeSubscriptionProvider(value, fallback = '115') {
            const normalized = String(value || '').trim().toLowerCase();
            if (normalized === '115' || normalized === 'quark') return normalized;
            const fallbackNormalized = String(fallback || '115').trim().toLowerCase();
            return fallbackNormalized === 'quark' ? 'quark' : '115';
        }

        function getSubscriptionProviderLabel(provider) {
            return normalizeSubscriptionProvider(provider, '115') === 'quark' ? 'Quark' : '115';
        }

        function getCurrentSubscriptionProvider() {
            return normalizeSubscriptionProvider(document.getElementById('subscription_provider')?.value || '115', '115');
        }

        function normalizeSubscriptionQualityPriority(value) {
            const normalized = String(value || 'balanced').trim().toLowerCase();
            if (['balanced', 'ultra', 'fhd', 'hd', 'sd'].includes(normalized)) return normalized;
            return 'balanced';
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
            const provider = normalizeSubscriptionProvider(
                getEffectiveResourceLinkType(payload) === 'quark' ? 'quark' : '115',
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
            const isQuark = provider === 'quark';
            const providerLabel = getSubscriptionProviderLabel(provider);
            const savepathProviderLabelEl = document.getElementById('subscription-savepath-provider-label');
            const fixedLinkBlockEl = document.getElementById('subscription-115-fixed-link-block');
            const quarkHintEl = document.getElementById('subscription-quark-provider-hint');
            const minScoreWrapEl = document.getElementById('subscription-min-score-wrap');
            const minScoreInputEl = document.getElementById('subscription_min_score');
            const strategyHintEl = document.getElementById('subscription-provider-strategy-hint');

            if (savepathProviderLabelEl) savepathProviderLabelEl.textContent = `${providerLabel} 保存目录`;
            if (fixedLinkBlockEl) fixedLinkBlockEl.classList.toggle('hidden', isQuark);
            if (quarkHintEl) quarkHintEl.classList.toggle('hidden', !isQuark);
            if (minScoreWrapEl) minScoreWrapEl.classList.toggle('hidden', isQuark);
            if (minScoreInputEl) minScoreInputEl.disabled = isQuark;
            if (strategyHintEl) {
                strategyHintEl.textContent = isQuark
                    ? '匹配策略：Quark 仅使用频道自动匹配，采用独立评分（强标题命中 + 集数命中）；仅集数命中会被拦截。'
                    : '匹配策略：若填写了固定 115 分享链接，默认只在该链接内扫描；可开启“固定链接后再补搜一次频道”作为兜底。未填写固定链接时，会在已启用频道按标题/别名主动搜索并评分命中。';
            }

            if (isQuark) {
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
                parseInt(document.getElementById('subscription_schedule_interval_minutes')?.value || '30', 10) || 30
            );
            const shareLinkRaw = String(document.getElementById('subscription_share_link_url')?.value || '').trim();
            const shareLinkType = detectResourceLinkTypeByUrl(shareLinkRaw);
            const normalizedShareLink = provider === '115' && shareLinkType === '115share' ? shareLinkRaw : '';
            const receiveCodeRaw = String(document.getElementById('subscription_share_receive_code')?.value || '').trim();
            const normalizedReceiveCode = normalizeReceiveCodeInput(receiveCodeRaw);
            const shareSubdir = normalizeRelativePathInput(document.getElementById('subscription_share_subdir')?.value || '');
            const shareSubdirCid = shareSubdir
                ? normalizeShareCidInput(document.getElementById('subscription_share_subdir_cid')?.value || '')
                : '';
            const fixedLinkChannelSearch = provider === '115' && !!document.getElementById('subscription_fixed_link_channel_search')?.checked;
            return {
                name: title,
                provider,
                media_type: normalizeSubscriptionMediaType(document.getElementById('subscription_media_type').value),
                title,
                aliases: document.getElementById('subscription_aliases').value.trim(),
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
            if (providerInput) providerInput.value = '115';
            document.getElementById('subscription_title').value = '';
            document.getElementById('subscription_aliases').value = '';
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
            document.getElementById('subscription_schedule_interval_minutes').value = 30;
            document.getElementById('subscription_min_score').value = 55;
            document.getElementById('subscription_quality_priority').value = 'ultra';
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

        function buildSubscriptionProviderTaskName(title, provider) {
            const normalizedTitle = String(title || '').trim();
            if (!normalizedTitle) return '';
            const suffix = normalizeSubscriptionProvider(provider, '115') === 'quark' ? 'quark' : '115';
            return `${normalizedTitle} (${suffix})`;
        }

        async function saveSubscriptionTask() {
            const task = currentSubscriptionFormData();
            task.provider = normalizeSubscriptionProvider(task.provider, '115');
            if (!task.title) return alert('订阅影视名称不能为空');
            if (!task.savepath) return alert('请先从网盘选择保存目录');
            const rawShareLink = String(document.getElementById('subscription_share_link_url')?.value || '').trim();
            if (task.provider === '115' && rawShareLink && !task.share_link_url) return alert('固定分享链接仅支持 115 分享链接格式');
            const rawReceiveCode = String(document.getElementById('subscription_share_receive_code')?.value || '').trim();
            if (task.provider === '115' && rawReceiveCode && !task.share_link_receive_code) return alert('提取码格式不正确，请输入 1-16 位字母或数字');
            if (task.provider !== '115' || !task.share_link_url) {
                task.share_link_url = '';
                task.share_link_receive_code = '';
                task.share_subdir = '';
                task.share_subdir_cid = '';
                task.fixed_link_channel_search = false;
            }
            if (!task.share_subdir) task.share_subdir_cid = '';
            if (task.year && !/^(19|20)\d{2}$/.test(task.year)) return alert('年份格式不正确，请输入四位年份');
            if (task.schedule_start_time === task.schedule_end_time) return alert('开始时间和结束时间不能相同');
            if (task.schedule_interval_minutes < 1) return alert('时段内查询间隔不能小于 1 分钟');
            if (task.enabled && (!Array.isArray(task.schedule_weekdays) || task.schedule_weekdays.length <= 0)) {
                return alert('请至少选择一个查询星期，或先关闭任务启用状态');
            }
            if (task.provider === '115' && (task.min_score < 30 || task.min_score > 100)) return alert('匹配阈值需在 30-100 之间');
            if (task.provider !== '115') task.min_score = 55;
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
            if (dup) return alert(`任务名称重复（${task.name}），请修改标题或网盘提供方后再保存`);
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
            const providerInput = document.getElementById('subscription_provider');
            if (providerInput) providerInput.value = normalizeSubscriptionProvider(task.provider || '115', '115');
            document.getElementById('subscription_media_type').value = normalizeSubscriptionMediaType(task.media_type || 'movie');
            document.getElementById('subscription_title').value = task.title || '';
            document.getElementById('subscription_aliases').value = Array.isArray(task.aliases) ? task.aliases.join(', ') : (task.aliases || '');
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
            document.getElementById('subscription_schedule_interval_minutes').value = Math.max(1, parseInt(task.schedule_interval_minutes ?? task.cron_minutes ?? 30, 10) || 30);
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

        async function rebuildSubscriptionTask(name, { refreshEpisodeModal = false } = {}) {
            const normalizedName = String(name || '').trim();
            if (!normalizedName) return;
            if (!confirm(`按当前保存目录重建“${normalizedName}”的追更进度和集数账本吗？`)) return;
            try {
                const res = await fetch('/subscription/rebuild', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: normalizedName })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '重建失败');
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
                const toggleRunClass = running
                    ? 'bg-amber-500/15 hover:bg-amber-500/25 text-amber-300'
                    : (queued
                        ? 'bg-slate-700/80 text-slate-300'
                        : 'bg-emerald-600 hover:bg-emerald-500 text-white');
                const rebuildDisabled = running;
                const actionGridClass = isTv
                    ? 'subscription-task-actions subscription-task-actions-tv grid grid-cols-3 sm:grid-cols-6 gap-2 shrink-0 w-full lg:w-auto'
                    : 'subscription-task-actions subscription-task-actions-movie grid grid-cols-2 sm:grid-cols-4 gap-2 shrink-0 w-full lg:w-auto';
                const rebuildButton = isTv
                    ? `<button type="button" data-subscription-action="rebuild" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-sky-500/15 hover:bg-sky-500/25 text-sky-200 text-sm font-bold ${rebuildDisabled ? 'btn-disabled' : ''}" ${rebuildDisabled ? 'disabled' : ''}>校准</button>`
                    : '';
                const episodeViewButton = isTv
                    ? `<button type="button" data-subscription-action="episodes" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">集数视图</button>`
                    : '';
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
                                    <div class="text-lg font-black text-white break-all leading-tight">${escapeHtml(taskName)}</div>
                                </button>
                                <button
                                    type="button"
                                    data-subscription-toggle-intro="${encodeURIComponent(taskName)}"
                                    aria-expanded="${introExpanded ? 'true' : 'false'}"
                                    class="shrink-0 text-[11px] sm:text-xs font-bold text-sky-300 hover:text-sky-200 hover:underline underline-offset-2 rounded-lg px-1.5 py-1 focus:outline-none focus:ring-2 focus:ring-sky-500/45"
                                >${introExpanded ? '收起简介' : '展开简介'}</button>
                            </div>
                            <div class="${actionGridClass}">
                                <button type="button" data-subscription-action="toggle-run" data-subscription-run-action="${toggleRunAction}" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl text-sm font-bold ${toggleRunClass} ${toggleRunDisabled ? 'btn-disabled' : ''}" ${toggleRunDisabled ? 'disabled' : ''}>${toggleRunLabel}</button>
                                <button type="button" data-subscription-action="edit" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">编辑</button>
                                <button type="button" data-subscription-action="delete" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-red-500/15 hover:bg-red-500/25 text-red-300 text-sm font-bold">删除</button>
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
                const res = await fetch(`/subscription/episodes?name=${encodeURIComponent(normalizedName)}`);
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '读取集数失败');
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

        function normalizeShareCidInput(value) {
            const raw = String(value || '').trim().replace(/\s+/g, '');
            if (!raw || raw === '0') return '';
            return /^[A-Za-z0-9_-]{1,64}$/.test(raw) ? raw : '';
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

        function getResourceProviderByLinkType(linkType) {
            const normalized = String(linkType || '').trim().toLowerCase();
            if (normalized === 'quark') return 'quark';
            return '115';
        }

        function getResourceProviderLabel(provider) {
            return normalizeSubscriptionProvider(provider, '115') === 'quark' ? '夸克' : '115';
        }

        function getResourceFolderApiPrefix(provider) {
            return normalizeSubscriptionProvider(provider, '115') === 'quark' ? '/resource/quark' : '/resource/115';
        }

        function getResourceShareApiPrefix(linkType) {
            const normalized = String(linkType || '').trim().toLowerCase();
            if (normalized === 'quark') return '/resource/quark';
            return '/resource/115';
        }

        function isProviderCookieConfigured(provider) {
            const normalized = normalizeSubscriptionProvider(provider, '115');
            if (normalized === 'quark') return !!resourceState?.quark_cookie_configured;
            return !!resourceState?.cookie_configured;
        }

        function isLinkTypeCookieConfigured(linkType) {
            return isProviderCookieConfigured(getResourceProviderByLinkType(linkType));
        }

        function hasAnyResourceCookieConfigured() {
            return !!resourceState?.cookie_configured || !!resourceState?.quark_cookie_configured;
        }

        function isResourceShareLinkType(linkType) {
            const normalized = String(linkType || '').trim().toLowerCase();
            return normalized === '115share' || normalized === 'quark';
        }

        function getCurrentResourceProvider() {
            return getResourceProviderByLinkType(resourceModalLinkType);
        }

        function getResourceLinkTypeBadgeClass(linkType) {
            const normalized = String(linkType || 'unknown').trim().toLowerCase();
            if (normalized === 'magnet') return 'resource-card-type-badge resource-card-type-badge-magnet';
            if (normalized === '115share') return 'resource-card-type-badge resource-card-type-badge-115share';
            if (normalized === 'quark') return 'resource-card-type-badge resource-card-type-badge-quark';
            return 'resource-card-type-badge resource-card-type-badge-default';
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

        function getResourceJobSourceLabel(source) {
            const normalized = String(source || '').trim().toLowerCase();
            if (normalized === 'manual_import') return '手动导入';
            if (normalized === 'subscription_auto') return '订阅自动';
            if (normalized === 'userscript_webhook') return '油猴脚本';
            if (normalized === 'webhook') return 'Webhook';
            return '未知来源';
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

        function createResourceQuickLinkId() {
            return `rql_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
        }

        function normalizeResourceQuickLinkNameInput(value) {
            return String(value || '').replace(/\s+/g, ' ').trim();
        }

        function normalizeResourceQuickLinkUrlInput(value) {
            const raw = String(value || '').trim();
            if (!raw) return '';
            const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `https://${raw}`;
            try {
                const parsed = new URL(withScheme);
                if (!/^https?:$/i.test(parsed.protocol)) return '';
                return parsed.toString();
            } catch (e) {
                return '';
            }
        }

        function buildResourceQuickLinkFingerprint(url) {
            const raw = String(url || '').trim();
            if (!raw) return '';
            try {
                const parsed = new URL(raw);
                parsed.hash = '';
                const protocol = String(parsed.protocol || '').toLowerCase();
                const host = String(parsed.host || '').toLowerCase();
                return `${protocol}//${host}${parsed.pathname}${parsed.search}`;
            } catch (e) {
                return raw.toLowerCase();
            }
        }

        function suggestResourceQuickLinkName(url) {
            const linkType = detectResourceLinkTypeByUrl(url);
            if (linkType && linkType !== 'unknown' && linkType !== 'link') {
                return getResourceLinkTypeLabel(linkType);
            }
            try {
                const host = new URL(url).hostname.replace(/^www\./i, '');
                return host || '网盘分享';
            } catch (e) {
                return '网盘分享';
            }
        }

        function normalizeResourceQuickLinks(list = []) {
            const sourceList = Array.isArray(list) ? list : [];
            const output = [];
            const seenFingerprint = new Set();
            const seenId = new Set();
            for (const rawItem of sourceList) {
                if (!rawItem || typeof rawItem !== 'object' || Array.isArray(rawItem)) continue;
                const normalizedUrl = normalizeResourceQuickLinkUrlInput(rawItem.url || rawItem.link_url || rawItem.href || '');
                if (!normalizedUrl) continue;
                const fingerprint = buildResourceQuickLinkFingerprint(normalizedUrl);
                if (!fingerprint || seenFingerprint.has(fingerprint)) continue;
                seenFingerprint.add(fingerprint);

                let id = String(rawItem.id || '').trim();
                if (!id || seenId.has(id)) id = createResourceQuickLinkId();
                seenId.add(id);

                const now = Date.now();
                const createdAtRaw = Number(rawItem.created_at || now);
                const updatedAtRaw = Number(rawItem.updated_at || createdAtRaw || now);
                const usedAtRaw = Number(rawItem.last_used_at || 0);
                output.push({
                    id,
                    name: normalizeResourceQuickLinkNameInput(rawItem.name || rawItem.title || '') || suggestResourceQuickLinkName(normalizedUrl),
                    url: normalizedUrl,
                    fingerprint,
                    created_at: Number.isFinite(createdAtRaw) ? createdAtRaw : now,
                    updated_at: Number.isFinite(updatedAtRaw) ? updatedAtRaw : now,
                    last_used_at: Number.isFinite(usedAtRaw) ? usedAtRaw : 0,
                });
                if (output.length >= RESOURCE_QUICK_LINKS_LIMIT) break;
            }
            return output;
        }

        function serializeResourceQuickLinks(list = []) {
            return (Array.isArray(list) ? list : []).map(item => ({
                id: String(item?.id || '').trim(),
                name: String(item?.name || '').trim(),
                url: String(item?.url || '').trim(),
                created_at: Number(item?.created_at || 0),
                updated_at: Number(item?.updated_at || 0),
                last_used_at: Number(item?.last_used_at || 0),
            }));
        }

        function readResourceQuickLinksFromStorage() {
            try {
                const raw = localStorage.getItem(RESOURCE_QUICK_LINKS_MEMORY_KEY);
                return raw ? JSON.parse(raw) : [];
            } catch (e) {
                return [];
            }
        }

        function clearResourceQuickLinksStorage() {
            try {
                localStorage.removeItem(RESOURCE_QUICK_LINKS_MEMORY_KEY);
            } catch (e) {}
        }

        async function persistResourceQuickLinksToBackend(nextLinks, { silent = false, clearLocalOnSuccess = false } = {}) {
            const payload = serializeResourceQuickLinks(nextLinks);
            try {
                const res = await fetch('/resource/quick_links/save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ quick_links: payload })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '保存常用网盘链接失败');
                setResourceQuickLinks(Array.isArray(data.quick_links) ? data.quick_links : payload, { render: true });
                if (clearLocalOnSuccess) clearResourceQuickLinksStorage();
                return true;
            } catch (e) {
                if (!silent) {
                    showToast(`常用网盘链接保存失败：${e.message || '未知错误'}`, { tone: 'error', duration: 2800, placement: 'top-center' });
                }
                return false;
            }
        }

        function setResourceQuickLinks(nextLinks, { render = true } = {}) {
            resourceQuickLinks = normalizeResourceQuickLinks(nextLinks);
            if (render) {
                renderResourceQuickLinkStrip();
                renderResourceQuickLinkList();
            }
        }

        async function migrateResourceQuickLinksFromStorageIfNeeded(serverLinks = []) {
            if (resourceQuickLinksMigrationChecked) return;
            resourceQuickLinksMigrationChecked = true;
            const localLinks = normalizeResourceQuickLinks(readResourceQuickLinksFromStorage());
            if (!localLinks.length) {
                clearResourceQuickLinksStorage();
                return;
            }
            if (Array.isArray(serverLinks) && serverLinks.length) {
                clearResourceQuickLinksStorage();
                return;
            }
            const migrated = await persistResourceQuickLinksToBackend(localLinks, { silent: true, clearLocalOnSuccess: true });
            if (migrated) {
                showToast('已将本地常用网盘链接迁移到后端，可多端同步', { tone: 'success', duration: 2600, placement: 'top-center' });
            }
        }

        function loadResourceQuickLinksFromStorage() {
            setResourceQuickLinks(readResourceQuickLinksFromStorage(), { render: true });
            syncResourceQuickLinkFormState();
        }

        function getResourceQuickLinkById(linkId) {
            const target = String(linkId || '').trim();
            if (!target) return null;
            return (resourceQuickLinks || []).find(item => String(item?.id || '').trim() === target) || null;
        }

        function resetResourceQuickLinkForm({ keepUrl = false } = {}) {
            editingResourceQuickLinkId = '';
            const nameInput = document.getElementById('resource-quick-link-name');
            const urlInput = document.getElementById('resource-quick-link-url');
            if (nameInput) nameInput.value = '';
            if (urlInput && !keepUrl) urlInput.value = '';
            syncResourceQuickLinkFormState();
        }

        function syncResourceQuickLinkFormState() {
            const saveBtn = document.getElementById('resource-quick-link-save-btn');
            const cancelBtn = document.getElementById('resource-quick-link-cancel-edit-btn');
            const editing = !!String(editingResourceQuickLinkId || '').trim();
            if (saveBtn) saveBtn.textContent = editing ? '保存修改' : '添加常用网盘链接';
            if (cancelBtn) cancelBtn.classList.toggle('hidden', !editing);
        }

        function renderResourceQuickLinkStrip() {
            const container = document.getElementById('resource-quick-link-strip');
            if (!container) return;
            const links = Array.isArray(resourceQuickLinks) ? resourceQuickLinks : [];
            const hasLinks = links.length > 0;
            const previewLimit = 8;
            const preview = links.slice(0, previewLimit);
            const overflow = Math.max(0, links.length - preview.length);
            container.classList.remove('hidden');
            container.innerHTML = `
                <div class="resource-quick-link-strip-list">
                    ${hasLinks
                        ? preview.map(item => `
                            <button type="button" class="resource-quick-link-pill" data-resource-quick-link-action="search" data-resource-quick-link-id="${escapeHtml(item.id)}" title="${escapeHtml(item.url)}">${escapeHtml(item.name || '未命名')}</button>
                        `).join('')
                        : '<span class="resource-quick-link-strip-empty">暂无常用链接</span>'}
                    <button type="button" class="resource-quick-link-manage-btn" data-resource-quick-link-action="manage">${overflow > 0 ? `管理 +${overflow}` : '管理'}</button>
                </div>
            `;
        }

        function renderResourceQuickLinkList() {
            const container = document.getElementById('resource-quick-link-list');
            if (!container) return;
            const links = Array.isArray(resourceQuickLinks) ? resourceQuickLinks : [];
            if (!links.length) {
                container.innerHTML = '<div class="resource-quick-link-list-empty">还没有常用网盘链接。<br>可先在搜索框粘贴分享链接，再点“读取搜索框”一键保存。</div>';
                return;
            }
            container.innerHTML = links.map(item => {
                const usedText = Number(item?.last_used_at || 0) > 0 ? formatTimeText(Number(item.last_used_at)) : '未使用';
                return `
                    <div class="resource-quick-link-item">
                        <div class="resource-quick-link-item-main">
                            <div class="resource-quick-link-item-name">${escapeHtml(item.name || '未命名链接')}</div>
                            <div class="resource-quick-link-item-url">${escapeHtml(item.url || '')}</div>
                            <div class="resource-quick-link-item-meta">最近使用：${escapeHtml(usedText)}</div>
                        </div>
                        <div class="resource-quick-link-item-actions">
                            <button type="button" class="resource-quick-link-item-action resource-quick-link-item-action-primary" data-resource-quick-link-action="search" data-resource-quick-link-id="${escapeHtml(item.id)}">识别</button>
                            <button type="button" class="resource-quick-link-item-action" data-resource-quick-link-action="open" data-resource-quick-link-id="${escapeHtml(item.id)}">跳转</button>
                            <button type="button" class="resource-quick-link-item-action" data-resource-quick-link-action="copy" data-resource-quick-link-id="${escapeHtml(item.id)}">复制</button>
                            <button type="button" class="resource-quick-link-item-action" data-resource-quick-link-action="edit" data-resource-quick-link-id="${escapeHtml(item.id)}">编辑</button>
                            <button type="button" class="resource-quick-link-item-action resource-quick-link-item-action-danger" data-resource-quick-link-action="delete" data-resource-quick-link-id="${escapeHtml(item.id)}">删除</button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function openResourceQuickLinkModal(prefillFromSearch = false) {
            const shouldPrefill = prefillFromSearch === true || String(prefillFromSearch || '').trim() === 'true';
            if (!shouldPrefill) resetResourceQuickLinkForm();
            resourceQuickLinkModalOpen = true;
            showLockedModal('resource-quick-link-modal');
            renderResourceQuickLinkList();
            syncResourceQuickLinkFormState();
            if (shouldPrefill) {
                editingResourceQuickLinkId = '';
                syncResourceQuickLinkFormState();
                fillResourceQuickLinkFormFromSearch({ silent: true });
            }
            requestAnimationFrame(() => {
                const input = document.getElementById('resource-quick-link-name') || document.getElementById('resource-quick-link-url');
                if (!input) return;
                input.focus();
                input.select?.();
            });
        }

        function closeResourceQuickLinkModal() {
            resourceQuickLinkModalOpen = false;
            hideLockedModal('resource-quick-link-modal');
            resetResourceQuickLinkForm();
        }

        function pickFirstHttpUrlFromText(text = '') {
            const raw = String(text || '').trim();
            if (!raw) return '';
            const links = raw.match(/https?:\/\/[^\s<>'"]+/gi) || [];
            if (links.length) return String(links[0] || '').replace(/[，。；、]+$/g, '');
            const compact = raw.replace(/\s+/g, '');
            if (/^[a-z0-9.-]+\.[a-z]{2,}(?:\/[^\s]*)?$/i.test(compact)) return compact;
            return '';
        }

        function fillResourceQuickLinkFormFromSearch({ silent = false } = {}) {
            const searchInput = document.getElementById('resource-search-input');
            const nameInput = document.getElementById('resource-quick-link-name');
            const urlInput = document.getElementById('resource-quick-link-url');
            if (!nameInput || !urlInput) return false;

            const keyword = String(searchInput?.value || '').trim();
            if (!keyword) {
                if (!silent) showToast('搜索框为空，请先粘贴网盘分享链接', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return false;
            }
            const candidate = pickFirstHttpUrlFromText(keyword) || keyword;
            const normalizedUrl = normalizeResourceQuickLinkUrlInput(candidate);
            if (!normalizedUrl) {
                if (!silent) showToast('未识别到有效的 http/https 分享链接', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return false;
            }
            urlInput.value = normalizedUrl;
            if (!normalizeResourceQuickLinkNameInput(nameInput.value)) {
                nameInput.value = suggestResourceQuickLinkName(normalizedUrl);
            }
            if (!silent) showToast('已读取搜索框链接，可直接保存', { tone: 'info', duration: 2200, placement: 'top-center' });
            return true;
        }

        function cancelEditResourceQuickLink() {
            resetResourceQuickLinkForm();
            const nameInput = document.getElementById('resource-quick-link-name');
            if (nameInput) nameInput.focus();
        }

        function editResourceQuickLink(linkId) {
            const item = getResourceQuickLinkById(linkId);
            if (!item) return;
            const nameInput = document.getElementById('resource-quick-link-name');
            const urlInput = document.getElementById('resource-quick-link-url');
            if (!nameInput || !urlInput) return;
            editingResourceQuickLinkId = item.id;
            nameInput.value = item.name || '';
            urlInput.value = item.url || '';
            syncResourceQuickLinkFormState();
            nameInput.focus();
            nameInput.select?.();
        }

        function touchResourceQuickLink(linkId) {
            const target = String(linkId || '').trim();
            if (!target) return;
            const now = Date.now();
            let changed = false;
            const nextLinks = (resourceQuickLinks || []).map(item => {
                if (String(item?.id || '').trim() !== target) return item;
                changed = true;
                return {
                    ...item,
                    last_used_at: now,
                    updated_at: Math.max(Number(item?.updated_at || 0), now),
                };
            });
            if (!changed) return;
            setResourceQuickLinks(nextLinks, { render: true });
            void persistResourceQuickLinksToBackend(nextLinks, { silent: true });
        }

        async function useResourceQuickLinkForSearch(linkId, { closeModal = false } = {}) {
            const item = getResourceQuickLinkById(linkId);
            if (!item) return null;
            const input = document.getElementById('resource-search-input');
            if (!input) return null;
            input.value = item.url || '';
            syncResourceSearchInputActions();
            touchResourceQuickLink(item.id);
            if (closeModal) closeResourceQuickLinkModal();
            return searchResources();
        }

        function openResourceQuickLinkExternal(linkId) {
            const item = getResourceQuickLinkById(linkId);
            if (!item || !item.url) return;
            const opened = window.open(item.url, '_blank', 'noopener,noreferrer');
            if (!opened) {
                showToast('浏览器拦截了新窗口，请允许弹窗后重试', { tone: 'warn', duration: 2800, placement: 'top-center' });
                return;
            }
            touchResourceQuickLink(item.id);
        }

        async function copyResourceQuickLink(linkId) {
            const item = getResourceQuickLinkById(linkId);
            if (!item || !item.url) return;
            try {
                if (!navigator.clipboard?.writeText) throw new Error('当前浏览器不支持剪贴板接口');
                await navigator.clipboard.writeText(item.url);
                touchResourceQuickLink(item.id);
                showToast('链接已复制到剪贴板', { tone: 'success', duration: 2200, placement: 'top-center' });
            } catch (e) {
                window.prompt('复制失败，请手动复制以下链接：', item.url);
            }
        }

        async function saveResourceQuickLink() {
            const nameInput = document.getElementById('resource-quick-link-name');
            const urlInput = document.getElementById('resource-quick-link-url');
            if (!nameInput || !urlInput) return;

            const normalizedUrl = normalizeResourceQuickLinkUrlInput(urlInput.value);
            if (!normalizedUrl) {
                showToast('请填写有效的 http/https 网盘链接', { tone: 'warn', duration: 2600, placement: 'top-center' });
                urlInput.focus();
                urlInput.select?.();
                return;
            }
            const now = Date.now();
            const normalizedName = normalizeResourceQuickLinkNameInput(nameInput.value) || suggestResourceQuickLinkName(normalizedUrl);
            const normalizedFingerprint = buildResourceQuickLinkFingerprint(normalizedUrl);
            const editingId = String(editingResourceQuickLinkId || '').trim();

            const duplicate = (resourceQuickLinks || []).find(item =>
                String(item?.fingerprint || '') === normalizedFingerprint
                && String(item?.id || '').trim() !== editingId
            );
            if (duplicate) {
                const mergedLinks = (resourceQuickLinks || []).map(item => {
                    if (String(item?.id || '').trim() !== String(duplicate?.id || '').trim()) return item;
                    return {
                        ...item,
                        name: normalizedName,
                        url: normalizedUrl,
                        fingerprint: normalizedFingerprint,
                        updated_at: now,
                    };
                });
                const saved = await persistResourceQuickLinksToBackend(mergedLinks);
                if (!saved) return;
                editingResourceQuickLinkId = String(duplicate?.id || '').trim();
                syncResourceQuickLinkFormState();
                nameInput.value = normalizedName;
                urlInput.value = normalizedUrl;
                showToast('该链接已存在，已更新名称和地址', { tone: 'info', duration: 2400, placement: 'top-center' });
                return;
            }

            if (editingId) {
                let updated = false;
                const nextLinks = (resourceQuickLinks || []).map(item => {
                    if (String(item?.id || '').trim() !== editingId) return item;
                    updated = true;
                    return {
                        ...item,
                        name: normalizedName,
                        url: normalizedUrl,
                        fingerprint: normalizedFingerprint,
                        updated_at: now,
                    };
                });
                if (updated) {
                    const saved = await persistResourceQuickLinksToBackend(nextLinks);
                    if (!saved) return;
                    showToast('常用网盘链接已更新', { tone: 'success', duration: 2200, placement: 'top-center' });
                    resetResourceQuickLinkForm();
                    urlInput.value = normalizedUrl;
                    nameInput.focus();
                    return;
                }
            }

            const overflow = Math.max(0, (resourceQuickLinks || []).length + 1 - RESOURCE_QUICK_LINKS_LIMIT);
            const newItem = {
                id: createResourceQuickLinkId(),
                name: normalizedName,
                url: normalizedUrl,
                fingerprint: normalizedFingerprint,
                created_at: now,
                updated_at: now,
                last_used_at: 0,
            };
            const nextLinks = [newItem, ...(resourceQuickLinks || [])];
            const saved = await persistResourceQuickLinksToBackend(nextLinks);
            if (!saved) return;
            resetResourceQuickLinkForm();
            urlInput.value = normalizedUrl;
            nameInput.focus();
            showToast(
                overflow > 0
                    ? `已添加常用链接，超出的最旧 ${overflow} 条已自动移除`
                    : '常用网盘链接已添加',
                { tone: 'success', duration: 2400, placement: 'top-center' }
            );
        }

        async function deleteResourceQuickLink(linkId) {
            const item = getResourceQuickLinkById(linkId);
            if (!item) return;
            if (!confirm(`确认删除常用链接「${item.name || '未命名链接'}」吗？`)) return;
            const targetId = String(item.id || '').trim();
            const nextLinks = (resourceQuickLinks || []).filter(link => String(link?.id || '').trim() !== targetId);
            const saved = await persistResourceQuickLinksToBackend(nextLinks);
            if (!saved) return;
            if (String(editingResourceQuickLinkId || '').trim() === targetId) resetResourceQuickLinkForm();
            showToast('常用链接已删除', { tone: 'success', duration: 2200, placement: 'top-center' });
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
            return !!String(item?.link_url || '').trim() && ['magnet', '115share', 'quark'].includes(linkType);
        }

        function canImportResource(item) {
            const linkType = getEffectiveResourceLinkType(item);
            return canOpenResourceImport(item) && isLinkTypeCookieConfigured(linkType);
        }

        function getResourceImportLabel(item) {
            const linkType = getEffectiveResourceLinkType(item);
            if (!String(item?.link_url || '').trim()) return '暂无可导入链接';
            if (linkType === '115share') return '转存到 115';
            if (linkType === 'quark') return '转存到夸克';
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

        function normalizeResourceBatchImportItems(items) {
            const seenLinks = new Set();
            const normalized = [];
            (Array.isArray(items) ? items : []).forEach(rawItem => {
                const item = rawItem && typeof rawItem === 'object' ? rawItem : {};
                const linkUrl = String(item?.link_url || '').trim();
                if (!linkUrl) return;
                const linkKey = linkUrl.toLowerCase();
                if (seenLinks.has(linkKey)) return;
                seenLinks.add(linkKey);
                normalized.push(item);
            });
            return normalized;
        }

        function setResourceBatchImportItems(items = []) {
            resourceBatchImportItems = normalizeResourceBatchImportItems(items);
        }

        function getResourceBatchMagnetItems() {
            return normalizeResourceBatchImportItems(resourceBatchImportItems).filter(item => {
                const linkUrl = String(item?.link_url || '').trim();
                if (!linkUrl) return false;
                return getEffectiveResourceLinkType(item) === 'magnet';
            });
        }

        function isResourceBatchImportMode() {
            if (resourceModalMode !== 'import') return false;
            if (Number(selectedResourceId || 0) > 0) return false;
            const batchItems = getResourceBatchMagnetItems();
            if (batchItems.length <= 1) return false;
            const selectedLink = String(selectedResourceItem?.link_url || '').trim().toLowerCase();
            return !selectedLink || batchItems.some(item => String(item?.link_url || '').trim().toLowerCase() === selectedLink);
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
            const publishedRaw = item?.published_at || item?.created_at || '';
            const publishedMs = parseResourceTimeMs(publishedRaw);
            if (publishedMs) {
                const relative = formatResourceAgeText(publishedMs);
                const absolute = formatTimeText(publishedRaw);
                tokens.push(`${relative}（${absolute}）`);
            } else if (publishedRaw) {
                tokens.push(String(publishedRaw));
            }
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
                    <div class="resource-card-content">
                        <div class="resource-card-header">
                            <button type="button" data-resource-action="preview" data-resource-id="${item.id}" class="resource-card-title break-words text-left bg-transparent border-none p-0 hover:text-sky-700 transition-colors">${escapeHtml(item?.title || '未命名资源')}</button>
                            <div class="resource-card-badges">
                                ${buildResourceStatusBadge(getResourceDisplayStatus(item))}
                                <span class="${escapeHtml(getResourceLinkTypeBadgeClass(getEffectiveResourceLinkType(item)))}">${escapeHtml(getResourceLinkTypeLabel(getEffectiveResourceLinkType(item)))}</span>
                                ${item?.quality ? `<span class="text-[10px] px-3 py-1 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/20">${escapeHtml(item.quality)}</span>` : ''}
                                ${item?.year ? `<span class="text-[10px] px-3 py-1 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/20">${escapeHtml(item.year)}</span>` : ''}
                            </div>
                        </div>
                        <div class="resource-card-meta">${buildResourceMeta(item)}</div>
                        <div class="resource-card-desc">${buildResourceDescription(item)}</div>
                    </div>
                    <div class="resource-card-actions">
                        <button type="button" data-resource-action="preview" data-resource-id="${item.id}" class="resource-card-action-secondary">详情</button>
                        <button type="button" data-resource-action="copy" data-resource-id="${item.id}" class="resource-card-action-secondary ${copyDisabled}" ${copyDisabled ? 'disabled' : ''}>${escapeHtml(getResourceCopyLabel(item))}</button>
                        <button type="button" data-resource-action="subscribe" data-resource-id="${item.id}" class="resource-card-action-subscribe">转订阅</button>
                        <button type="button" data-resource-action="import" data-resource-id="${item.id}" class="${importClass}" ${importOpenable ? '' : 'disabled'}>导入</button>
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
            const linkType = String(resourceModalLinkType || '').trim().toLowerCase();
            const provider = getResourceProviderByLinkType(linkType);
            const providerLabel = getResourceProviderLabel(provider);
            if (isResourceBatchImportMode()) {
                const batchCount = getResourceBatchMagnetItems().length;
                return `当前为批量模式，将按同一保存目录依次导入 ${batchCount} 条磁力链接。`;
            }
            if (!isCurrentResource115Share()) return '当前资源会按完整内容导入。';
            if (!isLinkTypeCookieConfigured(linkType)) return `配置 ${providerLabel} Cookie 后可浏览分享目录并选择具体内容。`;
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
            const provider = getCurrentResourceProvider();
            const providerLabel = getResourceProviderLabel(provider);

            const match = resolveResourceMonitorTaskMatch(savepath || document.getElementById('resource_job_savepath')?.value || '');
            if (!match.savepath) {
                hintEl.innerText = `请选择一个非根目录的${providerLabel}保存目录。`;
                return;
            }

            const selectionHint = getResourceImportSelectionHint();
            if (provider === 'quark') {
                hintEl.innerText = `${selectionHint} 当前为夸克独立链路，提交后不会联动文件夹监控刷新。`.trim();
                return;
            }
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
            const provider = getCurrentResourceProvider();

            const match = resolveResourceMonitorTaskMatch(savepath);
            syncResourceSavepathPreview(match.savepath);

            if (!match.savepath) {
                hiddenInput.value = '';
                displayInput.textContent = '请先选择保存目录';
                delayInput.disabled = false;
                renderResourceImportBehaviorHint('');
                return;
            }

            if (provider === 'quark') {
                hiddenInput.value = '';
                displayInput.textContent = '夸克链路不绑定监控';
                delayInput.value = '0';
                delayInput.disabled = true;
                renderResourceImportBehaviorHint(match.savepath);
                renderResourceImportSummary();
                renderResourceImportFeedback();
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
            renderResourceImportFeedback();
        }

        function syncResourceProviderUI() {
            const provider = getCurrentResourceProvider();
            const providerLabel = getResourceProviderLabel(provider);
            const savepathLabelEl = document.getElementById('resource-savepath-provider-label');
            const folderModalTitleEl = document.getElementById('resource-folder-modal-title');
            const receiveCodeLabelEl = document.getElementById('resource-share-receive-code-label');
            if (savepathLabelEl) savepathLabelEl.textContent = `${providerLabel} 保存目录`;
            if (folderModalTitleEl) folderModalTitleEl.textContent = `选择${providerLabel}目录`;
            if (receiveCodeLabelEl) receiveCodeLabelEl.textContent = `${providerLabel} 提取码`;
        }

        function renderResourceImportSummary() {
            const selectionCountEl = document.getElementById('resource-import-selection-count');
            const selectionState = getResourceShareSelectionState();
            const isShare = isCurrentResource115Share();
            let selectionText = '整条资源';

            if (!isShare && isResourceBatchImportMode()) {
                selectionText = `${getResourceBatchMagnetItems().length} 条磁力`;
            }

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

        function renderResourceImportStepper(item, importMode = false, isSubmitting = false) {
            const wrapper = document.getElementById('resource-import-stepper');
            if (!wrapper) return;
            wrapper.classList.toggle('hidden', !importMode);
            if (!importMode) return;

            const steps = wrapper.querySelectorAll('.resource-import-step');
            const hasItem = !!item;
            const savepath = normalizeRelativePathInput(document.getElementById('resource_job_savepath')?.value || '');
            const hasSavepath = !!savepath;
            const activeStep = isSubmitting ? 3 : (hasSavepath ? 3 : (hasItem ? 2 : 1));

            steps.forEach((node, idx) => {
                const step = idx + 1;
                node.classList.toggle('is-done', step < activeStep);
                node.classList.toggle('is-active', step === activeStep);
            });
        }

        function renderResourceImportFeedback() {
            const card = document.getElementById('resource-import-feedback-card');
            if (!card) return;
            if (resourceModalMode !== 'import' || !resourceImportLastFeedback) {
                card.classList.add('hidden');
                card.innerHTML = '';
                return;
            }
            const feedback = resourceImportLastFeedback;
            const lines = [
                `任务：${feedback.jobText || '--'}`,
                `阶段：${feedback.stage || '--'}`,
                `时间：${feedback.timeText || formatTimeText(new Date())}`,
            ];
            if (feedback.note) lines.push(`说明：${feedback.note}`);
            card.innerHTML = lines.map(line => `<div>${escapeHtml(line)}</div>`).join('');
            card.classList.remove('hidden');
        }

        function updateResourceImportFeedback(payload = {}) {
            resourceImportLastFeedback = {
                stage: String(payload.stage || '已提交').trim(),
                jobText: String(payload.jobText || '--').trim(),
                note: String(payload.note || '').trim(),
                timeText: formatTimeText(new Date())
            };
            renderResourceImportFeedback();
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
                ? `命中 ${shownCount}`
                : `显示 ${shownCount}`;
            const secondaryBadge = isSearchSection
                ? `${escapeHtml(String(section?.pages_scanned || 0))} 页`
                : `缓存 ${escapeHtml(String(section.item_count || (section.items || []).length || 0))}`;
            const primaryType = getResourceLinkTypeLabel(section?.primary_link_type || section?.channel_profile?.primary_link_type || 'unknown');
            const latestPublishedAt = String(section?.latest_published_at || section?.channel_profile?.latest_published_at || '').trim();
            const subtleText = isSearchSection
                ? `关键词「${escapeHtml(keyword)}」`
                : `最近资源 ${escapeHtml(latestPublishedAt ? formatTimeText(latestPublishedAt) : '--')} · 最近同步 ${escapeHtml(formatResourceSyncTime(section.last_sync_at))}`;
            const footerText = isSearchSection
                ? `当前已显示 ${escapeHtml(String(shownCount))} 条命中结果。`
                : `当前已显示 ${escapeHtml(String(shownCount))} 条，频道缓存 ${escapeHtml(String(section.item_count || 0))} 条。`;
            const emptyText = isSearchSection
                ? '这个频道暂时没有可展示的命中结果。'
                : '这个频道还没有同步到资源，稍后再试一次同步。';

            return `
                <section class="resource-section-card" data-collapsed="${isResourceSectionCollapsed(section.channel_id) ? 'true' : 'false'}">
                    <div class="resource-section-header">
                        <button type="button" data-resource-section-toggle="${escapeHtml(section.channel_id || '')}" class="resource-section-header-main min-w-0 flex-1 text-left bg-transparent border-none p-0">
                            <div class="resource-section-title-row">
                                <h4 class="resource-section-title">${escapeHtml(section.name || section.channel_id || '未命名频道')}</h4>
                                <span class="resource-section-chip">@${escapeHtml(section.channel_id || '--')}</span>
                                <span class="resource-section-chip resource-section-chip-accent">${primaryBadge}</span>
                                <span class="resource-section-chip">${secondaryBadge}</span>
                                ${!isSearchSection ? `<span class="resource-section-chip">${escapeHtml(primaryType)}</span>` : ''}
                                ${!isSearchSection && section.last_error ? '<span class="resource-section-chip resource-section-chip-warn">同步异常</span>' : ''}
                            </div>
                            <div class="resource-section-subtle">${subtleText}</div>
                        </button>
                        <div class="resource-section-actions">
                            ${!isSearchSection ? `<button type="button" data-resource-section-manage="${escapeHtml(section.channel_id || '')}" class="resource-section-manage-btn">管理</button>` : ''}
                            <a href="${escapeHtml(section.url || '#')}" target="_blank" rel="noopener noreferrer" class="resource-section-link">打开频道</a>
                            <button type="button" data-resource-section-toggle="${escapeHtml(section.channel_id || '')}" class="resource-section-toggle bg-transparent border-none p-0" aria-label="展开或收起频道">⌄</button>
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

        function renderResourceOnboardingCard() {
            const card = document.getElementById('resource-onboarding-card');
            const stepsEl = document.getElementById('resource-onboarding-steps');
            if (!card || !stepsEl) return;

            const setupStatus = resourceState?.setup_status && typeof resourceState.setup_status === 'object'
                ? resourceState.setup_status
                : null;
            if (!setupStatus) {
                card.classList.add('hidden');
                stepsEl.innerHTML = '';
                return;
            }

            const hasCookie115 = !!setupStatus.cookie_configured;
            const hasCookieQuark = !!setupStatus.quark_cookie_configured;
            const hasCookie = hasCookie115 || hasCookieQuark;
            const hasSources = !!setupStatus.has_sources;
            const hasMonitor = !!setupStatus.has_monitor;
            const hasResourceData = !!setupStatus.has_resource_data;
            const hasJobs = !!setupStatus.has_jobs;
            const steps = [
                { label: '配置 AList/OpenList', done: !!setupStatus.alist_configured, tab: 'settings', meta: '播放链接基础配置' },
                { label: '配置网盘 Cookie', done: hasCookie, tab: 'settings', meta: '启用导入/转存能力' },
                { label: '同步频道资源', done: hasSources && hasResourceData, tab: 'resource', meta: '先同步再搜索导入' },
                { label: '创建监控任务', done: hasMonitor, tab: 'monitor', meta: '用于自动生成 strm' },
                { label: '提交首个导入任务', done: hasJobs, tab: 'resource', meta: '验证全链路可用' },
            ];
            const doneCount = steps.filter(step => step.done).length;
            card.classList.toggle('hidden', doneCount >= steps.length);
            stepsEl.innerHTML = steps.map((step, index) => `
                <button type="button" class="resource-onboarding-step ${step.done ? 'is-done' : ''}" data-onboarding-tab="${escapeHtml(step.tab)}">
                    <span class="resource-onboarding-dot">${step.done ? '✓' : index + 1}</span>
                    <span>
                        <span class="resource-onboarding-label">${escapeHtml(step.label)}</span>
                        <span class="resource-onboarding-meta">${escapeHtml(step.meta)}</span>
                    </span>
                </button>
            `).join('');
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
            const nextQuickLinks = Array.isArray(data.quick_links) ? data.quick_links : (resourceState.quick_links || []);
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
                quick_links: nextQuickLinks,
                items: nextItems,
                jobs: nextJobs,
                channel_sections: hydrateResourceSections(Array.isArray(data.channel_sections) ? data.channel_sections : (resourceState.channel_sections || [])),
                channel_profiles: data.channel_profiles && typeof data.channel_profiles === 'object'
                    ? data.channel_profiles
                    : (resourceState.channel_profiles || {}),
                search_sections: hydrateResourceSections(Array.isArray(data.search_sections) ? data.search_sections : (resourceState.search_sections || [])),
                last_syncs: data.last_syncs || resourceState.last_syncs || {},
                monitor_tasks: Array.isArray(data.monitor_tasks) ? data.monitor_tasks : (resourceState.monitor_tasks || monitorState.tasks || []),
                cookie_configured: !!(
                    typeof data.cookie_configured === 'boolean'
                        ? data.cookie_configured
                        : resourceState.cookie_configured
                ),
                quark_cookie_configured: !!(
                    typeof data.quark_cookie_configured === 'boolean'
                        ? data.quark_cookie_configured
                        : resourceState.quark_cookie_configured
                ),
                setup_status: data.setup_status && typeof data.setup_status === 'object'
                    ? data.setup_status
                    : (resourceState.setup_status || null),
                stats: nextStats,
                search: typeof data.search === 'string' ? data.search : (resourceState.search || ''),
                search_meta: data.search_meta || resourceState.search_meta || {}
            };
            normalizeResourceSourceBulkSelections();
            syncResourceChannelPagingState();
            setResourceQuickLinks(nextQuickLinks, { render: true });
            void migrateResourceQuickLinksFromStorageIfNeeded(nextQuickLinks);
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
            document.getElementById('resource-cookie-hint').classList.toggle('hidden', hasAnyResourceCookieConfigured());
            syncResourceSourceSelect();
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceOnboardingCard();
            renderResourceSources();
            if (resourceChannelManageModalOpen) {
                const nextIndex = getResourceSourceIndexByChannelId(resourceChannelManageChannelId);
                resourceChannelManageSourceIndex = nextIndex;
                if (nextIndex < 0) closeResourceChannelManageModal();
                else syncResourceChannelManageModalState();
            }
            renderResourceBoard();
            renderResourceJobs();
            syncResourceJobModalTrigger();
            syncResourceSearchInputActions();
            syncResourceActionButtons();
            renderResourceTgHealthStatus();
            if (selectedResourceItem) renderResourceModalLayout(selectedResourceItem);
            renderResourceShareBrowser();
            renderResourceTargetPreview();

        }

        function syncResourceSearchInputActions() {
            const input = document.getElementById('resource-search-input');
            const clearBtn = document.getElementById('resource-search-clear-btn');
            const pasteBtn = document.getElementById('resource-search-paste-btn');
            if (!input) return;
            const hasValue = !!String(input.value || '').trim();
            if (clearBtn) {
                clearBtn.classList.toggle('hidden', !hasValue);
                clearBtn.disabled = !hasValue;
            }
            if (pasteBtn) {
                const showPaste = !hasValue;
                pasteBtn.classList.toggle('hidden', !showPaste);
                pasteBtn.disabled = !showPaste;
            }
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
            const importableItems = items
                .filter(item => canOpenResourceImport(item))
                .map(item => createTransientResourceItem(item));
            if (!importableItems.length) throw new Error('未在文本中识别到可导入的 magnet / 115 / quark 分享链接');

            const magnetItems = importableItems.filter(item => getEffectiveResourceLinkType(item) === 'magnet');
            const hasShareItems = importableItems.some(item => isResourceShareLinkType(getEffectiveResourceLinkType(item)));
            if (magnetItems.length > 1 && !hasShareItems) {
                setResourceBatchImportItems(magnetItems);
                const batchMagnetItems = getResourceBatchMagnetItems();
                const firstItem = batchMagnetItems[0] || magnetItems[0];
                openResourceItemModal(firstItem, 'import');
                showToast(`已识别 ${batchMagnetItems.length} 条磁力链接，提交时将批量导入`, {
                    tone: 'info',
                    duration: 3200,
                    placement: 'top-center'
                });
                return {
                    inserted: 0,
                    updated: 0,
                    item: firstItem,
                    items: batchMagnetItems,
                    batch_total: batchMagnetItems.length
                };
            }

            setResourceBatchImportItems([]);
            const preferred = importableItems[0];
            if (importableItems.length > 1) {
                showToast(`已识别 ${importableItems.length} 条可导入链接，当前先处理第 1 条`, {
                    tone: 'info',
                    duration: 3200,
                    placement: 'top-center'
                });
            }
            openResourceItemModal(preferred, 'import');
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
            syncResourceSearchInputActions();
            if (resourceState.search || hadKeyword) {
                resetResourceSearchResults();
                await refreshResourceState({ keywordOverride: '' });
            } else {
                renderResourceBoard();
            }
            input.focus();
        }

        async function pasteResourceSearch() {
            const input = document.getElementById('resource-search-input');
            if (!input) return;
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
            input.value = text;
            syncResourceSearchInputActions();
            input.focus();
            input.setSelectionRange?.(text.length, text.length);
            showToast('已粘贴剪贴板内容，可直接搜索', { tone: 'info', duration: 2200, placement: 'top-center' });
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

        function getResourceSourceIndexByChannelId(channelId) {
            const normalized = normalizeTelegramChannelIdInput(channelId || '');
            if (!normalized) return -1;
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            for (let i = 0; i < sources.length; i += 1) {
                if (getResourceSourceChannelId(sources[i]) === normalized) return i;
            }
            return -1;
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
                const latestPublishedAt = String(profile?.latest_published_at || '').trim();
                const latestPublishedMs = parseResourceTimeMs(latestPublishedAt);
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
                    latestPublishedAt,
                    latestPublishedMs,
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

        function normalizeResourceSourceManagerMobilePanel(panel) {
            return String(panel || '').trim().toLowerCase() === 'tools' ? 'tools' : 'list';
        }

        function isCompactPortraitResourceSourceManager() {
            return !!window.matchMedia && window.matchMedia('(orientation: portrait) and (max-width: 900px)').matches;
        }

        function setResourceSourceManagerMobilePanel(panel) {
            resourceSourceManagerMobilePanel = normalizeResourceSourceManagerMobilePanel(panel);
        }

        function openResourceSourceManagerModal() {
            switchTab('settings');
            resourceSourceManagerOpen = true;
            setResourceSourceManagerMobilePanel('list');
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
            const keyword = String(resourceSourceKeyword || '').trim().toLowerCase();
            const filtered = list.filter(view => {
                if (!isResourceSourceVisibleByFilter(view.source, sectionIndex, resourceSourceFilter)) return false;
                if (!isResourceSourceVisibleByEnabled(view.source, resourceSourceEnabledFilter)) return false;
                if (!isResourceSourceVisibleByActivity(view.source, sectionIndex, resourceSourceActivityFilter)) return false;
                if (keyword) {
                    const name = String(view?.source?.name || '').trim().toLowerCase();
                    const id = String(view?.channelId || '').trim().toLowerCase();
                    const typeText = (Array.isArray(view?.sourceTypes) ? view.sourceTypes : []).join(' ').toLowerCase();
                    if (!name.includes(keyword) && !id.includes(keyword) && !typeText.includes(keyword)) return false;
                }
                return true;
            });

            const mode = String(resourceSourceSortMode || 'recent').trim().toLowerCase();
            filtered.sort((a, b) => {
                if (mode === 'name') {
                    return String(a?.source?.name || a?.channelId || '').localeCompare(String(b?.source?.name || b?.channelId || ''));
                }
                if (mode === 'activity') {
                    const ad = (a?.activityBucket === 'week' ? 4 : a?.activityBucket === 'month' ? 3 : a?.activityBucket === 'half_year' ? 2 : a?.activityBucket === 'older' ? 1 : 0);
                    const bd = (b?.activityBucket === 'week' ? 4 : b?.activityBucket === 'month' ? 3 : b?.activityBucket === 'half_year' ? 2 : b?.activityBucket === 'older' ? 1 : 0);
                    if (bd !== ad) return bd - ad;
                }
                const aMs = Number(a?.latestPublishedMs || 0);
                const bMs = Number(b?.latestPublishedMs || 0);
                if (bMs !== aMs) return bMs - aMs;
                return String(a?.source?.name || a?.channelId || '').localeCompare(String(b?.source?.name || b?.channelId || ''));
            });
            return filtered;
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
            const sampleNames = (resourceState.sources || [])
                .filter(source => selectedIds.includes(getResourceSourceChannelId(source)))
                .slice(0, 3)
                .map(source => source?.name || getResourceSourceChannelId(source) || '未命名频道')
                .filter(Boolean);
            const summary = sampleNames.length
                ? `将删除 ${selectedIds.length} 个频道（如：${sampleNames.join('、')}）\n此操作不可恢复，确定继续吗？`
                : `将删除 ${selectedIds.length} 个频道，此操作不可恢复，确定继续吗？`;
            const ok = confirm(summary);
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
                showToast(`已删除 ${selectedIds.length} 个频道`, { tone: 'success', duration: 2600, placement: 'top-center' });
            } catch (e) {
                showToast(`删除失败：${e.message}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
        }

        function renderResourceSourceManagerModal() {
            const modal = document.getElementById('resource-source-manager-modal');
            if (!modal || !resourceSourceManagerOpen) return;

            const shell = modal.querySelector('.resource-source-manager-shell');
            const typeFiltersEl = document.getElementById('resource-source-manager-type-filters');
            const statusFiltersEl = document.getElementById('resource-source-manager-status-filters');
            const activityFiltersEl = document.getElementById('resource-source-manager-activity-filters');
            const searchInputEl = document.getElementById('resource-source-manager-search');
            const sortSelectEl = document.getElementById('resource-source-manager-sort');
            const hintEl = document.getElementById('resource-source-manager-filter-hint');
            const listEl = document.getElementById('resource-source-manager-list');
            const selectedCountEl = document.getElementById('resource-source-manager-selected-count');
            const mobileFilteredCountEl = document.getElementById('resource-source-manager-mobile-filtered-count');
            const mobileSelectedCountEl = document.getElementById('resource-source-manager-mobile-selected-count');
            const mobileListTabEl = document.getElementById('resource-source-manager-mobile-list-tab');
            const mobileToolsTabEl = document.getElementById('resource-source-manager-mobile-tools-tab');
            const resultEl = document.getElementById('resource-source-manager-test-result');
            const testBtn = document.getElementById('resource-source-manager-test-btn');
            const selectAllBtn = document.getElementById('resource-source-manager-select-all-btn');
            const invertBtn = document.getElementById('resource-source-manager-invert-btn');
            if (!shell || !typeFiltersEl || !statusFiltersEl || !activityFiltersEl || !searchInputEl || !sortSelectEl || !hintEl || !listEl || !selectedCountEl || !mobileFilteredCountEl || !mobileSelectedCountEl || !mobileListTabEl || !mobileToolsTabEl || !resultEl || !testBtn || !selectAllBtn || !invertBtn) return;

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

            const filtered = getFilteredResourceSourceViewList();
            searchInputEl.value = resourceSourceKeyword;
            sortSelectEl.value = resourceSourceSortMode;

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
            const compactPortrait = isCompactPortraitResourceSourceManager();
            const activeMobilePanel = compactPortrait ? normalizeResourceSourceManagerMobilePanel(resourceSourceManagerMobilePanel) : 'list';
            shell.classList.toggle('resource-source-manager-shell-mobile', compactPortrait);
            shell.classList.toggle('resource-source-manager-shell-mobile-list', compactPortrait && activeMobilePanel === 'list');
            shell.classList.toggle('resource-source-manager-shell-mobile-tools', compactPortrait && activeMobilePanel === 'tools');

            selectedCountEl.textContent = String(selectedInFiltered);
            mobileFilteredCountEl.textContent = String(filtered.length);
            mobileSelectedCountEl.textContent = String(selectedCount);
            mobileListTabEl.classList.toggle('resource-source-manager-mobile-tab-active', activeMobilePanel === 'list');
            mobileListTabEl.setAttribute('aria-pressed', activeMobilePanel === 'list' ? 'true' : 'false');
            mobileToolsTabEl.classList.toggle('resource-source-manager-mobile-tab-active', activeMobilePanel === 'tools');
            mobileToolsTabEl.setAttribute('aria-pressed', activeMobilePanel === 'tools' ? 'true' : 'false');
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
                const latest = String(view.latestPublishedAt || '').trim();
                const latestAge = view.latestPublishedMs ? formatResourceAgeText(view.latestPublishedMs) : '待同步';
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
                            <div class="resource-source-manager-row-meta">类型：${escapeHtml(typeText || getResourceLinkTypeLabel(view.primaryType || 'unknown'))} · 活跃度：${escapeHtml(getResourceSourceActivityBucketLabel(view.activityBucket))} · 最近：${escapeHtml(latestAge)}${latest ? `（${escapeHtml(formatTimeText(latest))}）` : ''}</div>
                        </div>
                        <div class="resource-source-manager-row-actions">
                            <button type="button" data-resource-source-manager-action="toggle" data-source-index="${view.index}" data-enabled="${enabled ? '1' : '0'}" class="resource-source-compact-btn">${enabled ? '停用' : '启用'}</button>
                            <button type="button" data-resource-source-manager-action="edit" data-source-index="${view.index}" class="resource-source-compact-btn">编辑</button>
                            <button type="button" data-resource-source-manager-action="delete" data-source-index="${view.index}" class="resource-source-compact-btn resource-source-compact-btn-danger">删除</button>
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

        function syncResourceChannelManageModalState() {
            const titleEl = document.getElementById('resource-channel-manage-title');
            const orderEl = document.getElementById('resource-channel-manage-order');
            const pinBtn = document.getElementById('resource-channel-manage-pin-btn');
            const enabledEl = document.getElementById('resource-channel-manage-enabled');
            const nameEl = document.getElementById('resource-channel-manage-name');
            const sources = Array.isArray(resourceState.sources) ? resourceState.sources : [];
            const index = resourceChannelManageSourceIndex;
            const source = index >= 0 ? sources[index] : null;
            if (!source) {
                if (titleEl) titleEl.innerText = '频道快捷管理';
                if (orderEl) orderEl.innerText = '--';
                if (pinBtn) {
                    pinBtn.disabled = true;
                    pinBtn.classList.add('btn-disabled');
                    pinBtn.innerText = '置顶（排序挪到1号）';
                }
                if (enabledEl) enabledEl.checked = false;
                if (nameEl) nameEl.value = '';
                return;
            }
            const displayName = String(source?.name || getResourceSourceChannelId(source) || '未命名频道').trim() || '未命名频道';
            if (titleEl) titleEl.innerText = `频道快捷管理 · ${displayName}`;
            if (orderEl) orderEl.innerText = `#${index + 1}`;
            if (pinBtn) {
                const alreadyTop = index <= 0;
                pinBtn.disabled = alreadyTop;
                pinBtn.classList.toggle('btn-disabled', alreadyTop);
                pinBtn.innerText = alreadyTop ? '已在1号位' : '置顶（排序挪到1号）';
            }
            if (enabledEl) enabledEl.checked = source?.enabled !== false;
            if (nameEl && !nameEl.value.trim()) {
                nameEl.value = displayName;
            }
        }

        function resetResourceChannelManageForm() {
            resourceChannelManageSourceIndex = -1;
            resourceChannelManageChannelId = '';
            const nameEl = document.getElementById('resource-channel-manage-name');
            const enabledEl = document.getElementById('resource-channel-manage-enabled');
            if (nameEl) nameEl.value = '';
            if (enabledEl) enabledEl.checked = true;
            syncResourceChannelManageModalState();
        }

        function openResourceChannelManageModal(channelId) {
            const normalized = normalizeTelegramChannelIdInput(channelId || '');
            const index = getResourceSourceIndexByChannelId(normalized);
            if (!normalized || index < 0) {
                showToast('未找到对应频道，可能已被删除或停用', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            const source = (resourceState.sources || [])[index] || {};
            resourceChannelManageSourceIndex = index;
            resourceChannelManageChannelId = normalized;
            const nameEl = document.getElementById('resource-channel-manage-name');
            const enabledEl = document.getElementById('resource-channel-manage-enabled');
            if (nameEl) nameEl.value = String(source?.name || normalized).trim() || normalized;
            if (enabledEl) enabledEl.checked = source?.enabled !== false;
            syncResourceChannelManageModalState();
            resourceChannelManageModalOpen = true;
            showLockedModal('resource-channel-manage-modal');
            requestAnimationFrame(() => {
                const input = document.getElementById('resource-channel-manage-name');
                if (!input) return;
                input.focus();
                input.select?.();
            });
        }

        function closeResourceChannelManageModal() {
            resourceChannelManageModalOpen = false;
            hideLockedModal('resource-channel-manage-modal');
            resetResourceChannelManageForm();
        }

        async function saveResourceChannelManage() {
            const index = resourceChannelManageSourceIndex;
            const channelId = resourceChannelManageChannelId;
            const sources = [...(resourceState.sources || [])];
            if (index < 0 || index >= sources.length) {
                showToast('频道不存在，无法保存', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            const nameEl = document.getElementById('resource-channel-manage-name');
            const enabledEl = document.getElementById('resource-channel-manage-enabled');
            const nextName = String(nameEl?.value || '').trim() || channelId;
            sources[index] = {
                ...sources[index],
                name: nextName,
                enabled: !!enabledEl?.checked,
            };
            try {
                await persistResourceSources(sources);
                resourceChannelManageSourceIndex = getResourceSourceIndexByChannelId(channelId);
                syncResourceChannelManageModalState();
                showToast('频道设置已保存', { tone: 'success', duration: 2200, placement: 'top-center' });
            } catch (e) {
                showToast(`保存失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
            }
        }

        async function pinResourceChannelToTop() {
            const index = resourceChannelManageSourceIndex;
            const channelId = resourceChannelManageChannelId;
            const sources = [...(resourceState.sources || [])];
            if (index <= 0 || index >= sources.length) return;
            const source = sources[index];
            sources.splice(index, 1);
            sources.unshift(source);
            try {
                await persistResourceSources(sources);
                resourceChannelManageSourceIndex = getResourceSourceIndexByChannelId(channelId);
                syncResourceChannelManageModalState();
                showToast('已置顶到1号位', { tone: 'success', duration: 2200, placement: 'top-center' });
            } catch (e) {
                showToast(`置顶失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
            }
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
            const counts = getResourceJobCounts(jobs);
            if (!container) return;

            renderResourceJobFilters(counts);

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
            } else {
                closeResourceJobClearMenu();
                unlockPageScroll();
            }
            syncResourceJobModalTrigger();
        }

        async function fetchResourceFolderData(cid = '0', { provider = '115' } = {}) {
            const apiPrefix = getResourceFolderApiPrefix(provider);
            const res = await fetch(`${apiPrefix}/folders?cid=${encodeURIComponent(String(cid || '0'))}`);
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

        async function createResourceFolder(cid = '0', name = '', { provider = '115' } = {}) {
            const apiPrefix = getResourceFolderApiPrefix(provider);
            const res = await fetch(`${apiPrefix}/folders/create`, {
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
            resourceShareLoadingMoreParents = {};
            resourceShareNextOffsetByParent = { '0': 0 };
            resourceShareHasMoreByParent = {};
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
            return isResourceShareLinkType(resourceModalLinkType);
        }

        function syncResourceShareReceiveCodeSection() {
            const sectionEl = document.getElementById('resource-share-receive-code-section');
            const inputEl = document.getElementById('resource_share_receive_code');
            const applyBtnEl = document.getElementById('resource-share-receive-code-apply');
            const labelEl = document.getElementById('resource-share-receive-code-label');
            const shouldShow = resourceModalMode === 'import' && isCurrentResource115Share();
            const providerLabel = getResourceProviderLabel(getCurrentResourceProvider());

            if (sectionEl) sectionEl.classList.toggle('hidden', !shouldShow);
            if (!shouldShow) return;
            if (labelEl) labelEl.textContent = `${providerLabel} 提取码`;

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
            if (!isLinkTypeCookieConfigured(resourceModalLinkType) || !selectedResourceItem) return;
            await loadResourceShareBranch(selectedResourceId, '0', { resetSelection: true });
        }

        async function fetchResourceShareData(
            resourceId,
            cid = '0',
            {
                offset = 0,
                limit = RESOURCE_SHARE_BROWSE_PAGE_LIMIT,
                paged = true
            } = {}
        ) {
            const receiveCode = normalizeReceiveCodeInput(resourceShareReceiveCode);
            const normalizedOffset = Math.max(0, Number(offset || 0));
            const normalizedLimit = Math.max(20, Math.min(Number(limit || RESOURCE_SHARE_BROWSE_PAGE_LIMIT), 400));
            const shareApiPrefix = getResourceShareApiPrefix(resourceModalLinkType);
            let res;
            if (Number(resourceId || 0) > 0) {
                const params = new URLSearchParams({
                    resource_id: String(resourceId || 0),
                    cid: String(cid || '0')
                });
                if (receiveCode) params.set('receive_code', receiveCode);
                if (paged) params.set('paged', '1');
                params.set('offset', String(normalizedOffset));
                params.set('limit', String(normalizedLimit));
                res = await fetch(`${shareApiPrefix}/share_entries?${params.toString()}`);
            } else {
                res = await fetch(`${shareApiPrefix}/share_entries_preview`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        cid,
                        link_url: String(selectedResourceItem?.link_url || '').trim(),
                        raw_text: String(selectedResourceItem?.raw_text || '').trim(),
                        receive_code: receiveCode,
                        paged: !!paged,
                        offset: normalizedOffset,
                        limit: normalizedLimit
                    })
                });
            }
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.msg || '读取分享内容失败');
            const entries = Array.isArray(data.entries) ? data.entries : [];
            const paging = data.paging && typeof data.paging === 'object' ? data.paging : {};
            const nextOffset = Math.max(
                normalizedOffset + entries.length,
                Number(paging.next_offset ?? (normalizedOffset + entries.length)) || (normalizedOffset + entries.length)
            );
            return {
                entries,
                summary: data.summary || { folder_count: 0, file_count: 0 },
                share: data.share || { title: '', share_code: '', receive_code: '', count: 0 },
                paging: {
                    offset: Math.max(0, Number(paging.offset ?? normalizedOffset) || normalizedOffset),
                    next_offset: nextOffset,
                    has_more: !!paging.has_more
                }
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

        function autoSelectCurrentResourceShareEntries({ clearEntryId = '' } = {}) {
            const normalizedClearId = String(clearEntryId || '').trim();
            if (normalizedClearId) delete resourceShareSelected[normalizedClearId];
            const entries = getCurrentResourceShareEntries();
            if (!entries.length) {
                syncResourceSharetitleFromSelection();
                renderResourceShareBrowser();
                return;
            }
            entries.forEach(entry => applyResourceShareSelection(entry, true, { renderAfter: false }));
            syncResourceSharetitleFromSelection();
            renderResourceShareBrowser();
        }

        function narrowResourceShareSelectionToBranch(branchId) {
            const normalizedBranchId = String(branchId || '').trim();
            if (!normalizedBranchId) return;
            Object.keys(resourceShareSelected || {}).forEach(selectedId => {
                const selectedEntry = buildResourceShareSelectableEntry(resourceShareSelected[selectedId] || {});
                const currentId = String(selectedEntry.id || selectedId || '').trim();
                if (!currentId) {
                    delete resourceShareSelected[selectedId];
                    return;
                }
                const keepInBranch = currentId === normalizedBranchId || isResourceShareDescendantOf(selectedEntry, normalizedBranchId);
                if (!keepInBranch) {
                    delete resourceShareSelected[currentId];
                }
            });
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

        async function loadResourceShareBranch(resourceId, cid = '0', { resetSelection = false, append = false } = {}) {
            if (!isLinkTypeCookieConfigured(resourceModalLinkType) || !isCurrentResource115Share()) {
                renderResourceShareBrowser();
                return;
            }
            const branchId = String(cid || '0');
            const isRoot = branchId === '0';
            const appendMode = !!append;
            let currentToken = resourceShareRequestToken;
            if (isRoot) {
                if (resetSelection && !appendMode) {
                    resourceShareEntriesByParent = { '0': [] };
                    resourceShareEntryIndex = {};
                    resourceShareExpanded = {};
                    resourceShareLoadingParents = {};
                    resourceShareLoadingMoreParents = {};
                    resourceShareNextOffsetByParent = { '0': 0 };
                    resourceShareHasMoreByParent = {};
                    resourceShareSelected = {};
                }
                if (!appendMode) {
                    resourceShareLoading = true;
                    resourceShareError = '';
                    resourceShareRequestToken += 1;
                    currentToken = resourceShareRequestToken;
                    resourceShareCurrentCid = '0';
                    resourceShareTrail = [{ cid: '0', name: resourceShareInfo?.title || '分享根目录' }];
                }
            }
            if (appendMode) resourceShareLoadingMoreParents[branchId] = true;
            else resourceShareLoadingParents[branchId] = true;
            renderResourceShareBrowser();
            try {
                const requestOffset = appendMode
                    ? Math.max(0, Number(resourceShareNextOffsetByParent[branchId] || 0))
                    : 0;
                const result = await fetchResourceShareData(resourceId, branchId, {
                    offset: requestOffset,
                    limit: RESOURCE_SHARE_BROWSE_PAGE_LIMIT,
                    paged: true
                });
                if (selectedResourceId !== Number(resourceId)) return;
                if (isRoot && !appendMode && currentToken !== resourceShareRequestToken) return;
                const incomingEntries = Array.isArray(result.entries) ? result.entries : [];
                const existingEntries = Array.isArray(resourceShareEntriesByParent?.[branchId]) ? resourceShareEntriesByParent[branchId] : [];
                let mergedEntries = incomingEntries;
                if (appendMode) {
                    const seen = new Set(existingEntries.map(item => String(item?.id || '').trim()).filter(Boolean));
                    const appended = incomingEntries.filter(item => {
                        const id = String(item?.id || '').trim();
                        if (!id || seen.has(id)) return false;
                        seen.add(id);
                        return true;
                    });
                    mergedEntries = existingEntries.concat(appended);
                }
                resourceShareEntriesByParent[branchId] = mergedEntries;
                mergedEntries.forEach(entry => {
                    const normalized = buildResourceShareSelectableEntry(entry);
                    if (normalized.id) resourceShareEntryIndex[normalized.id] = { ...entry, ...normalized };
                });
                const nextOffset = Math.max(
                    requestOffset + incomingEntries.length,
                    Number(result?.paging?.next_offset ?? (requestOffset + incomingEntries.length)) || (requestOffset + incomingEntries.length)
                );
                resourceShareNextOffsetByParent[branchId] = nextOffset;
                resourceShareHasMoreByParent[branchId] = !!result?.paging?.has_more;
                if (isRoot) {
                    if (!appendMode) {
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
                    } else {
                        syncResourceSharetitleFromSelection();
                    }
                }
            } catch (e) {
                if (selectedResourceId !== Number(resourceId)) return;
                if (isRoot && !appendMode) {
                    resourceShareEntriesByParent = { '0': [] };
                    resourceShareEntryIndex = {};
                    resourceShareLoadingMoreParents = {};
                    resourceShareNextOffsetByParent = { '0': 0 };
                    resourceShareHasMoreByParent = {};
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
                if (appendMode) delete resourceShareLoadingMoreParents[branchId];
                else delete resourceShareLoadingParents[branchId];
                if (isRoot && !appendMode) resourceShareLoading = false;
                if (isRoot && !appendMode) syncResourceShareReceiveCodeSection();
                renderResourceShareBrowser();
            }
        }

        async function loadMoreResourceShareCurrentFolder() {
            if (!selectedResourceItem || !isCurrentResource115Share()) return;
            const branchId = String(resourceShareCurrentCid || '0').trim() || '0';
            if (!resourceShareHasMoreByParent[branchId]) return;
            if (resourceShareLoadingMoreParents[branchId]) return;
            await loadResourceShareBranch(selectedResourceId, branchId, { append: true });
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
            const normalizedEntryId = String(entry.id || '').trim();
            if (normalizedEntryId) {
                // 进入子目录后，仅保留该子树内的选择，避免误带上级目录文件一起转存。
                narrowResourceShareSelectionToBranch(normalizedEntryId);
                delete resourceShareSelected[normalizedEntryId];
            }
            const branchId = String(entry.cid || entry.id || '').trim();
            if (!branchId) return;
            resourceShareCurrentCid = branchId;
            resourceShareTrail = resourceShareTrail.concat([{ cid: branchId, name: String(entry.name || '未命名目录') }]);
            if (!Object.prototype.hasOwnProperty.call(resourceShareEntriesByParent, branchId)) {
                await loadResourceShareBranch(selectedResourceId, branchId);
                if (!Object.prototype.hasOwnProperty.call(resourceShareEntriesByParent, branchId)) return;
                autoSelectCurrentResourceShareEntries({ clearEntryId: normalizedEntryId });
                return;
            }
            autoSelectCurrentResourceShareEntries({ clearEntryId: normalizedEntryId });
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
                    : '';
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
            const providerLabel = getResourceProviderLabel(getCurrentResourceProvider());
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
            const currentFolderLoadingMore = !!resourceShareLoadingMoreParents[resourceShareCurrentCid];
            const currentFolderHasMore = !!resourceShareHasMoreByParent[resourceShareCurrentCid];
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
                treeEl.innerHTML = `<div class="resource-browser-empty">正在读取${escapeHtml(providerLabel)}分享目录，请稍候...</div>`;
            } else if (!isLinkTypeCookieConfigured(resourceModalLinkType)) {
                treeEl.innerHTML = `<div class="resource-browser-empty">当前未配置${escapeHtml(providerLabel)} Cookie，暂时无法读取分享目录。</div>`;
            } else if (resourceShareError) {
                treeEl.innerHTML = `<div class="resource-browser-empty text-red-300">${escapeHtml(resourceShareError)}</div>`;
            } else if (!resourceShareRootLoaded) {
                treeEl.innerHTML = '<div class="resource-browser-empty">这里会显示分享里的目录和文件列表，你可以进入文件夹后再勾选具体内容。</div>';
            } else if (!currentEntries.length) {
                treeEl.innerHTML = '<div class="resource-browser-empty">这个目录下暂时没有可转存的内容。</div>';
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
                treeEl.innerHTML = `${buildResourceShareRows(currentEntries)}${loadMoreHtml}`;
            }

            const selectedInCurrentCount = currentEntries.filter(entry => isResourceShareEntryEffectivelySelected(entry)).length;
            if (currentCheckAllEl) {
                currentCheckAllEl.disabled = !currentEntries.length || !isLinkTypeCookieConfigured(resourceModalLinkType) || !!resourceShareError || resourceShareLoading || currentFolderLoading || currentFolderLoadingMore;
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
                const result = await fetchResourceFolderData(parentCid, { provider: getCurrentResourceProvider() });
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
                const result = await fetchResourceFolderData(parentCid, { provider: getCurrentResourceProvider() });
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
            const provider = getCurrentResourceProvider();
            const providerLabel = getResourceProviderLabel(provider);
            if (!isProviderCookieConfigured(provider)) return true;
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
                    const detail = e?.message || `读取${providerLabel}目录失败`;
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
            const provider = getCurrentResourceProvider();
            const providerLabel = getResourceProviderLabel(provider);

            pathEl.innerText = document.getElementById('resource_job_folder_path')?.value?.trim() || '根目录';
            if (!isProviderCookieConfigured(provider)) {
                summaryEl.innerText = `配置${providerLabel} Cookie 后可预览目标目录下的文件夹和文件内容。`;
                listEl.innerHTML = `<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前未配置${escapeHtml(providerLabel)} Cookie，暂时无法读取目标目录内容。</div>`;
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
            if (!isProviderCookieConfigured(getCurrentResourceProvider())) {
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
                const result = await fetchResourceFolderData(folderId, { provider: getCurrentResourceProvider() });
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
            if (resourceModalMode === 'import' && isProviderCookieConfigured(getCurrentResourceProvider())) {
                void ensureResourceFolderSelectionValid({ phase: 'open' });
            }
            if (resourceModalMode === 'import' && isCurrentResource115Share() && isLinkTypeCookieConfigured(resourceModalLinkType)) {
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
            resourceImportLastFeedback = null;
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
                    updateResourceImportFeedback({
                        stage: '提交中',
                        jobText: `批量 ${batchItems.length} 条`,
                        note: '正在逐条创建导入任务，请稍候'
                    });
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
                        let res;
                        try {
                            res = await fetch('/resource/jobs/create', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify(payload)
                            });
                        } catch (e) {
                            failedCount += 1;
                            if (!firstFailedMsg) {
                                firstFailedMsg = String(e?.message || '网络请求失败').trim() || '请稍后重试';
                            }
                            continue;
                        }
                        let data = {};
                        try {
                            data = await res.json();
                        } catch (e) {
                            data = {};
                        }
                        if (res.ok && data.ok) {
                            createdJobIds.push(Number(data.job_id || 0));
                            const currentTaskName = String(data.monitor_task_name || '').trim();
                            if (!matchedTaskName && currentTaskName) matchedTaskName = currentTaskName;
                            if (currentTaskName && data.auto_refresh) autoRefreshMatched = true;
                            continue;
                        }
                        if (res.status === 409) {
                            duplicatedCount += 1;
                            continue;
                        }
                        failedCount += 1;
                        if (!firstFailedMsg) {
                            firstFailedMsg = String(data.msg || `HTTP ${res.status}`).trim() || '请稍后重试';
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
                    updateResourceImportFeedback({
                        stage: failedCount > 0 ? '部分完成' : '已完成',
                        jobText: createdJobIds.length ? `#${createdJobIds[0]} 等 ${createdJobIds.length} 条` : '无新任务',
                        note: summaryText || '批量导入已处理完成'
                    });
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

                updateResourceImportFeedback({
                    stage: '提交中',
                    jobText: '等待返回任务编号',
                    note: '正在向后端创建导入任务'
                });

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
                let res;
                let data = {};
                try {
                    res = await fetch('/resource/jobs/create', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(payload)
                    });
                    data = await res.json();
                } catch (e) {
                    showToast(`提交失败：${e?.message || '网络请求失败'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                    return;
                }
                if (!res.ok || !data.ok) {
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
                updateResourceImportFeedback({
                    stage: '已完成',
                    jobText: `#${data.job_id}`,
                    note: currentProvider === 'quark'
                        ? '夸克导入任务已创建，可在任务中心继续追踪进度'
                        : `${matchedTaskName ? `命中监控任务 ${matchedTaskName}` : '未命中监控任务'}，可在任务中心继续追踪进度`
                });
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
            const container = document.getElementById('resource-folder-list');
            const summary = document.getElementById('resource-folder-summary');
            if (!container) return;
            const providerLabel = getResourceProviderLabel(getCurrentResourceProvider());
            if (summary) {
                summary.innerText = `当前目录下共有 ${Number(resourceFolderSummary?.folder_count || 0)} 个文件夹 / ${Number(resourceFolderSummary?.file_count || 0)} 个文件。`;
            }
            if (resourceFolderLoading) {
                container.innerHTML = `<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在读取${escapeHtml(providerLabel)}目录...</div>`;
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
                const result = await fetchResourceFolderData(cid, { provider: getCurrentResourceProvider() });
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
                const result = await createResourceFolder(currentCid, folderName, { provider: getCurrentResourceProvider() });
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
            const providerLabel = getResourceProviderLabel(getCurrentSubscriptionProvider());
            if (summary) {
                summary.innerText = `当前目录下共有 ${Number(subscriptionFolderSummary?.folder_count || 0)} 个文件夹 / ${Number(subscriptionFolderSummary?.file_count || 0)} 个文件。`;
            }
            if (subscriptionFolderLoading) {
                container.innerHTML = `<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在读取${escapeHtml(providerLabel)}目录...</div>`;
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
                const result = await fetchResourceFolderData(cid, { provider: getCurrentSubscriptionProvider() });
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
            const provider = getCurrentSubscriptionProvider();
            const providerLabel = getResourceProviderLabel(provider);
            if (!isProviderCookieConfigured(provider)) {
                showToast(`请先在参数配置中填写${providerLabel} Cookie`, { tone: 'warn', duration: 2800, placement: 'top-center' });
                return;
            }
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
                const result = await createResourceFolder(currentCid, folderName, { provider: getCurrentSubscriptionProvider() });
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

        function setSubscriptionShareSubdirSelection(path = '', cid = '') {
            const normalizedPath = normalizeRelativePathInput(path || '');
            const normalizedCid = normalizedPath ? normalizeShareCidInput(cid || '') : '';
            const subdirInput = document.getElementById('subscription_share_subdir');
            if (subdirInput) subdirInput.value = normalizedPath;
            const cidInput = document.getElementById('subscription_share_subdir_cid');
            if (cidInput) cidInput.value = normalizedCid;
        }

        function resetSubscriptionShareFolderBrowser() {
            subscriptionShareFolderTrail = [{ cid: '0', name: '分享根目录' }];
            subscriptionShareFolderEntriesByParent = { '0': [] };
            subscriptionShareFolderCurrentCid = '0';
            subscriptionShareFolderLoading = false;
            subscriptionShareFolderLoadingParents = {};
            subscriptionShareFolderLoadingMoreParents = {};
            subscriptionShareFolderNextOffsetByParent = { '0': 0 };
            subscriptionShareFolderHasMoreByParent = {};
            subscriptionShareFolderError = '';
            subscriptionShareFolderInfo = { title: '', count: 0, share_code: '', receive_code: '' };
            subscriptionShareFolderRootLoaded = false;
            subscriptionShareFolderRequestToken = 0;
            subscriptionShareFolderLinkFingerprint = '';
        }

        function getSubscriptionShareLinkPayload() {
            if (getCurrentSubscriptionProvider() !== '115') {
                throw new Error('当前网盘提供方不是 115，固定分享链接模式不可用');
            }
            const linkInput = document.getElementById('subscription_share_link_url');
            const receiveInput = document.getElementById('subscription_share_receive_code');
            const linkUrl = String(linkInput?.value || '').trim();
            const linkType = detectResourceLinkTypeByUrl(linkUrl);
            if (!linkUrl) throw new Error('请先填写固定 115 分享链接');
            if (linkType !== '115share') throw new Error('仅支持 115 分享链接');
            const rawReceiveCode = String(receiveInput?.value || '').trim();
            let receiveCode = normalizeReceiveCodeInput(rawReceiveCode);
            if (rawReceiveCode && !receiveCode) throw new Error('提取码格式不正确，请输入 1-16 位字母或数字');
            if (!receiveCode) receiveCode = extractReceiveCodeFromShareUrl(linkUrl);
            if (receiveInput) receiveInput.value = receiveCode;
            if (linkInput) linkInput.value = linkUrl;
            return {
                link_url: linkUrl,
                raw_text: linkUrl,
                receive_code: receiveCode,
            };
        }

        async function fetchSubscriptionShareFolderData(
            cid = '0',
            {
                offset = 0,
                limit = RESOURCE_SHARE_BROWSE_PAGE_LIMIT,
                paged = true
            } = {}
        ) {
            const payload = getSubscriptionShareLinkPayload();
            const normalizedOffset = Math.max(0, Number(offset || 0));
            const normalizedLimit = Math.max(20, Math.min(Number(limit || RESOURCE_SHARE_BROWSE_PAGE_LIMIT), 400));
            const res = await fetch('/resource/115/share_entries_preview', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    cid: String(cid || '0'),
                    link_url: payload.link_url,
                    raw_text: payload.raw_text,
                    receive_code: payload.receive_code,
                    paged: !!paged,
                    offset: normalizedOffset,
                    limit: normalizedLimit,
                }),
            });
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.msg || '读取分享目录失败');
            const entries = Array.isArray(data.entries) ? data.entries : [];
            const paging = data.paging && typeof data.paging === 'object' ? data.paging : {};
            const nextOffset = Math.max(
                normalizedOffset + entries.length,
                Number(paging.next_offset ?? (normalizedOffset + entries.length)) || (normalizedOffset + entries.length)
            );
            return {
                entries,
                summary: data.summary || { folder_count: 0, file_count: 0 },
                share: data.share || { title: '', share_code: '', receive_code: '', count: 0 },
                paging: {
                    offset: Math.max(0, Number(paging.offset ?? normalizedOffset) || normalizedOffset),
                    next_offset: nextOffset,
                    has_more: !!paging.has_more
                }
            };
        }

        function renderSubscriptionShareFolderBreadcrumbs() {
            const container = document.getElementById('subscription-share-folder-breadcrumbs');
            if (!container) return;
            container.innerHTML = subscriptionShareFolderTrail.map((item, index) => {
                const isLast = index === subscriptionShareFolderTrail.length - 1;
                return `
                    ${index > 0 ? '<span class="resource-folder-sep">›</span>' : ''}
                    <button
                        type="button"
                        data-subscription-share-folder-action="trail"
                        data-subscription-share-folder-index="${index}"
                        class="resource-folder-crumb ${isLast ? 'resource-folder-crumb-active' : ''}"
                        ${isLast ? 'disabled' : ''}
                    >${escapeHtml(item?.name || '分享根目录')}</button>
                `;
            }).join('');
        }

        function getCurrentSubscriptionShareFolderEntries() {
            return Array.isArray(subscriptionShareFolderEntriesByParent?.[subscriptionShareFolderCurrentCid])
                ? subscriptionShareFolderEntriesByParent[subscriptionShareFolderCurrentCid]
                : [];
        }

        function renderSubscriptionShareFolderList() {
            const container = document.getElementById('subscription-share-folder-list');
            const summary = document.getElementById('subscription-share-folder-summary');
            if (!container) return;
            const currentEntries = getCurrentSubscriptionShareFolderEntries();
            const currentFolderLoading = !!subscriptionShareFolderLoadingParents[subscriptionShareFolderCurrentCid];
            const currentFolderLoadingMore = !!subscriptionShareFolderLoadingMoreParents[subscriptionShareFolderCurrentCid];
            const currentFolderHasMore = !!subscriptionShareFolderHasMoreByParent[subscriptionShareFolderCurrentCid];
            if (summary) {
                const rootTitle = String(subscriptionShareFolderInfo?.title || '').trim();
                const folderCount = Number(currentEntries.filter(entry => !!entry?.is_dir).length);
                const fileCount = Math.max(0, Number(currentEntries.length) - folderCount);
                const counts = subscriptionShareFolderRootLoaded
                    ? `当前目录已加载 ${folderCount} 个子文件夹 / ${fileCount} 个文件。`
                    : '先填写固定分享链接，再浏览并选择链接中的目标子目录。';
                summary.innerText = rootTitle
                    ? `分享标题：${rootTitle}。${counts}`
                    : counts;
            }
            if (subscriptionShareFolderLoading || currentFolderLoading) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在读取分享目录...</div>';
                return;
            }
            if (subscriptionShareFolderError) {
                container.innerHTML = `<div class="rounded-2xl border border-dashed border-red-500/40 p-6 text-center text-red-300 text-sm">${escapeHtml(subscriptionShareFolderError)}</div>`;
                return;
            }
            if (!subscriptionShareFolderRootLoaded) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">点击“浏览链接目录”后，这里会显示分享内当前层级的目录和文件。</div>';
                return;
            }
            if (!currentEntries.length) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">当前目录没有可用条目，可以直接选择这里。</div>';
                return;
            }
            const loadMoreHtml = currentFolderHasMore
                ? `
                    <div class="resource-browser-load-more-row">
                        <button
                            type="button"
                            data-subscription-share-folder-action="load-more"
                            class="resource-browser-load-more-btn ${currentFolderLoadingMore ? 'btn-disabled' : ''}"
                            ${currentFolderLoadingMore ? 'disabled' : ''}
                        >${currentFolderLoadingMore ? '加载中...' : '加载更多条目'}</button>
                    </div>
                `
                : '';
            container.innerHTML = `${currentEntries.map(entry => buildResourceEntryRow(entry, {
                showOpenButton: true,
                openActionPrefix: 'subscription-share-folder',
            })).join('')}${loadMoreHtml}`;
        }

        async function loadSubscriptionShareFolderBranch(
            cid = '0',
            {
                append = false,
                forceRefresh = false
            } = {}
        ) {
            const normalizedCid = String(cid || '0').trim() || '0';
            const appendMode = !!append;
            const forceMode = !!forceRefresh;
            const hasCachedBranch = Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, normalizedCid);
            if (!appendMode && hasCachedBranch && !forceMode) {
                subscriptionShareFolderError = '';
                renderSubscriptionShareFolderBreadcrumbs();
                renderSubscriptionShareFolderList();
                return;
            }
            if (!appendMode) {
                subscriptionShareFolderError = '';
                if (normalizedCid === '0') subscriptionShareFolderLoading = true;
            }
            if (appendMode) subscriptionShareFolderLoadingMoreParents[normalizedCid] = true;
            else subscriptionShareFolderLoadingParents[normalizedCid] = true;
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
            const requestToken = ++subscriptionShareFolderRequestToken;
            try {
                const requestOffset = appendMode
                    ? Math.max(0, Number(subscriptionShareFolderNextOffsetByParent[normalizedCid] || 0))
                    : 0;
                if (!appendMode && forceMode) {
                    subscriptionShareFolderEntriesByParent[normalizedCid] = [];
                    subscriptionShareFolderNextOffsetByParent[normalizedCid] = 0;
                    subscriptionShareFolderHasMoreByParent[normalizedCid] = false;
                }
                const result = await fetchSubscriptionShareFolderData(normalizedCid, {
                    offset: requestOffset,
                    limit: RESOURCE_SHARE_BROWSE_PAGE_LIMIT,
                    paged: true,
                });
                if (requestToken !== subscriptionShareFolderRequestToken) return;
                const incomingEntries = Array.isArray(result.entries) ? result.entries : [];
                const existingEntries = Array.isArray(subscriptionShareFolderEntriesByParent?.[normalizedCid]) ? subscriptionShareFolderEntriesByParent[normalizedCid] : [];
                let mergedEntries = incomingEntries;
                if (appendMode) {
                    const seen = new Set(existingEntries.map(item => String(item?.id || '').trim()).filter(Boolean));
                    const appended = incomingEntries.filter(item => {
                        const id = String(item?.id || '').trim();
                        if (!id || seen.has(id)) return false;
                        seen.add(id);
                        return true;
                    });
                    mergedEntries = existingEntries.concat(appended);
                }
                subscriptionShareFolderEntriesByParent[normalizedCid] = mergedEntries;
                const nextOffset = Math.max(
                    requestOffset + incomingEntries.length,
                    Number(result?.paging?.next_offset ?? (requestOffset + incomingEntries.length)) || (requestOffset + incomingEntries.length)
                );
                subscriptionShareFolderNextOffsetByParent[normalizedCid] = nextOffset;
                subscriptionShareFolderHasMoreByParent[normalizedCid] = !!result?.paging?.has_more;
                subscriptionShareFolderInfo = result.share;
                subscriptionShareFolderRootLoaded = true;
                subscriptionShareFolderError = '';
            } catch (e) {
                if (requestToken !== subscriptionShareFolderRequestToken) return;
                if (!appendMode) subscriptionShareFolderEntriesByParent[normalizedCid] = [];
                subscriptionShareFolderError = e?.message || '读取分享目录失败';
                subscriptionShareFolderRootLoaded = false;
            } finally {
                if (requestToken !== subscriptionShareFolderRequestToken) return;
                if (appendMode) delete subscriptionShareFolderLoadingMoreParents[normalizedCid];
                else delete subscriptionShareFolderLoadingParents[normalizedCid];
                if (!appendMode && normalizedCid === '0') subscriptionShareFolderLoading = false;
                renderSubscriptionShareFolderBreadcrumbs();
                renderSubscriptionShareFolderList();
            }
        }

        async function loadMoreSubscriptionShareCurrentFolder() {
            const branchId = String(subscriptionShareFolderCurrentCid || '0').trim() || '0';
            if (!subscriptionShareFolderHasMoreByParent[branchId]) return;
            if (subscriptionShareFolderLoadingMoreParents[branchId]) return;
            await loadSubscriptionShareFolderBranch(branchId, { append: true });
        }

        async function openSubscriptionShareFolderModal() {
            if (getCurrentSubscriptionProvider() !== '115') {
                showToast('Quark 模式不支持固定分享链接目录浏览', { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            let payload;
            try {
                payload = getSubscriptionShareLinkPayload();
            } catch (e) {
                showToast(e?.message || '请先填写固定 115 分享链接', { tone: 'warn', duration: 2800, placement: 'top-center' });
                return;
            }
            const fingerprint = `${payload.link_url}#${payload.receive_code || ''}`;
            if (!subscriptionShareFolderLinkFingerprint || subscriptionShareFolderLinkFingerprint !== fingerprint) {
                resetSubscriptionShareFolderBrowser();
                subscriptionShareFolderLinkFingerprint = fingerprint;
            }
            showLockedModal('subscription-share-folder-modal');
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
            await loadSubscriptionShareFolderBranch(subscriptionShareFolderCurrentCid || '0', { forceRefresh: true });
        }

        function closeSubscriptionShareFolderModal() {
            hideLockedModal('subscription-share-folder-modal');
        }

        async function goSubscriptionShareFolderBack() {
            if (subscriptionShareFolderTrail.length <= 1) return;
            subscriptionShareFolderTrail = subscriptionShareFolderTrail.slice(0, -1);
            subscriptionShareFolderCurrentCid = String(subscriptionShareFolderTrail[subscriptionShareFolderTrail.length - 1]?.cid || '0');
            const branchId = String(subscriptionShareFolderCurrentCid || '0').trim() || '0';
            if (!Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, branchId)) {
                await loadSubscriptionShareFolderBranch(branchId);
                return;
            }
            subscriptionShareFolderError = '';
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
        }

        async function goSubscriptionShareFolderRoot() {
            subscriptionShareFolderTrail = [{ cid: '0', name: '分享根目录' }];
            subscriptionShareFolderCurrentCid = '0';
            if (!Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, '0') || !subscriptionShareFolderRootLoaded) {
                await loadSubscriptionShareFolderBranch('0');
                return;
            }
            subscriptionShareFolderError = '';
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
        }

        async function openSubscriptionShareFolderTrail(index) {
            const targetIndex = Math.max(0, Math.min(Number(index || 0), subscriptionShareFolderTrail.length - 1));
            subscriptionShareFolderTrail = subscriptionShareFolderTrail.slice(0, targetIndex + 1);
            subscriptionShareFolderCurrentCid = String(subscriptionShareFolderTrail[targetIndex]?.cid || '0');
            const branchId = String(subscriptionShareFolderCurrentCid || '0').trim() || '0';
            if (!Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, branchId)) {
                await loadSubscriptionShareFolderBranch(branchId);
                return;
            }
            subscriptionShareFolderError = '';
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
        }

        async function openSubscriptionShareFolderChild(folderId, folderName) {
            const nextCid = String(folderId || '0').trim() || '0';
            subscriptionShareFolderCurrentCid = nextCid;
            subscriptionShareFolderTrail = subscriptionShareFolderTrail.concat([{ cid: nextCid, name: String(folderName || '--') }]);
            if (!Object.prototype.hasOwnProperty.call(subscriptionShareFolderEntriesByParent, nextCid)) {
                await loadSubscriptionShareFolderBranch(nextCid);
                return;
            }
            subscriptionShareFolderError = '';
            renderSubscriptionShareFolderBreadcrumbs();
            renderSubscriptionShareFolderList();
        }

        function selectCurrentSubscriptionShareFolder() {
            const current = subscriptionShareFolderTrail[subscriptionShareFolderTrail.length - 1] || { cid: '0', name: '分享根目录' };
            const subdir = normalizeRelativePathInput(subscriptionShareFolderTrail.slice(1).map(item => item.name).join('/'));
            const subdirCid = subdir ? normalizeShareCidInput(current?.cid || '') : '';
            setSubscriptionShareSubdirSelection(subdir, subdirCid);
            closeSubscriptionShareFolderModal();
            showToast(
                subdir
                    ? `已选择分享子目录：${subdir}${subdirCid ? `（CID ${subdirCid}）` : ''}`
                    : '已选择分享根目录（留空）',
                { tone: 'success', duration: 2600, placement: 'top-center' }
            );
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
                    quick_links: cfg.resource_quick_links || [],
                    monitor_tasks: cfg.monitor_tasks || [],
                    cookie_configured: !!String(cfg.cookie_115 || '').trim(),
                    quark_cookie_configured: !!String(cfg.cookie_quark || '').trim()
                });
                applySign115State({
                    ...sign115State,
                    enabled: !!cfg.sign115_enabled,
                    cron_time: String(cfg.sign115_cron_time || '09:00')
                });
                syncNotifyChannelUI();
                renderTgProxyTestStatus();
                renderNotifyTestStatus();
                resetMonitorForm();
                resetSubscriptionForm();
                resetResourceSourceForm();
                syncResourceSourceSelect();
                refreshWebhookHint();
                renderVersionInfoPanel();
                await refreshSign115Status(true);
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
        document.getElementById('resource-channel-manage-name').addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter' || e.isComposing) return;
            e.preventDefault();
            await saveResourceChannelManage();
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
            syncResourceSearchInputActions();
            if (String(e.target?.value || '').trim()) return;
            if (String(resourceState.search || '').trim()) {
                resetResourceSearchResults();
                await refreshResourceState({ keywordOverride: '' });
                return;
            }
            renderResourceBoard();
        });
        document.getElementById('resource-quick-link-strip').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-quick-link-action]');
            if (!btn) return;
            const action = String(btn.dataset.resourceQuickLinkAction || '').trim();
            const linkId = String(btn.dataset.resourceQuickLinkId || '').trim();
            if (action === 'manage') {
                openResourceQuickLinkModal(false);
                return;
            }
            if (action === 'search' && linkId) {
                await useResourceQuickLinkForSearch(linkId, { closeModal: false });
                return;
            }
            if (action === 'open' && linkId) {
                openResourceQuickLinkExternal(linkId);
            }
        });
        document.getElementById('resource-quick-link-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-quick-link-action]');
            if (!btn) return;
            const action = String(btn.dataset.resourceQuickLinkAction || '').trim();
            const linkId = String(btn.dataset.resourceQuickLinkId || '').trim();
            if (!action || !linkId) return;
            if (action === 'search') {
                await useResourceQuickLinkForSearch(linkId, { closeModal: true });
                return;
            }
            if (action === 'open') {
                openResourceQuickLinkExternal(linkId);
                return;
            }
            if (action === 'copy') {
                await copyResourceQuickLink(linkId);
                return;
            }
            if (action === 'edit') {
                editResourceQuickLink(linkId);
                return;
            }
            if (action === 'delete') {
                await deleteResourceQuickLink(linkId);
            }
        });
        ['resource-quick-link-name', 'resource-quick-link-url'].forEach(id => {
            document.getElementById(id).addEventListener('keydown', async (e) => {
                if (e.key !== 'Enter' || e.isComposing) return;
                e.preventDefault();
                await saveResourceQuickLink();
            });
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
        document.getElementById('resource-source-manager-search').addEventListener('input', (e) => {
            resourceSourceKeyword = String(e.target?.value || '');
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-sort').addEventListener('change', (e) => {
            resourceSourceSortMode = String(e.target?.value || 'recent') || 'recent';
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
            const index = parseInt(btn.dataset.sourceIndex || '-1', 10);
            if (index < 0) return;
            if (action === 'edit') {
                closeResourceSourceManagerModal();
                openResourceSourceModal(index);
                return;
            }
            if (action === 'toggle') {
                const enabled = String(btn.dataset.enabled || '0') === '1';
                await toggleResourceSourceEnabled(index, !enabled);
                renderResourceSourceManagerModal();
                return;
            }
            if (action === 'delete') {
                const source = (resourceState.sources || [])[index];
                const name = source?.name || getResourceSourceChannelId(source) || '该频道';
                const ok = confirm(`将删除“${name}”，此操作不可恢复，确定继续吗？`);
                if (!ok) return;
                await deleteResourceSource(index);
                showToast(`已删除频道：${name}`, { tone: 'success', duration: 2400, placement: 'top-center' });
                renderResourceSourceManagerModal();
            }
        });
        window.addEventListener('resize', () => {
            if (resourceSourceManagerOpen) renderResourceSourceManagerModal();
        });
        document.getElementById('resource-onboarding-steps').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-onboarding-tab]');
            if (!btn) return;
            const tab = String(btn.dataset.onboardingTab || '').trim();
            if (!tab) return;
            switchTab(tab);
        });

        document.getElementById('resource-board').addEventListener('click', async (e) => {
            const manageBtn = e.target.closest('[data-resource-section-manage]');
            if (manageBtn) {
                openResourceChannelManageModal(manageBtn.dataset.resourceSectionManage || '');
                return;
            }
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
            const introBtn = e.target.closest('[data-subscription-toggle-intro]');
            if (introBtn) {
                const name = decodeURIComponent(introBtn.dataset.subscriptionToggleIntro || '');
                if (!name) return;
                toggleSubscriptionTaskIntro(name);
                return;
            }
            const btn = e.target.closest('[data-subscription-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionAction || '';
            const name = decodeURIComponent(btn.dataset.taskName || '');
            if (!name) return;
            if (action === 'toggle-run') {
                if (btn.dataset.subscriptionRunAction === 'stop') await stopSubscriptionTask(name);
                else await startSubscriptionTask(name);
                return;
            }
            if (action === 'edit') editSubscriptionTask(name);
            if (action === 'delete') await deleteSubscriptionTask(name);
            if (action === 'rebuild') await rebuildSubscriptionTask(name);
            if (action === 'episodes') await openSubscriptionEpisodeModal(name);
        });
        document.getElementById('monitor-task-list').addEventListener('click', async (e) => {
            const introBtn = e.target.closest('[data-monitor-toggle-intro]');
            if (introBtn) {
                const name = decodeURIComponent(introBtn.dataset.monitorToggleIntro || '');
                if (!name) return;
                toggleMonitorTaskIntro(name);
                return;
            }
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
        document.getElementById('subscription-share-folder-modal').addEventListener('click', (e) => {
            if (e.target.id === 'subscription-share-folder-modal') closeSubscriptionShareFolderModal();
        });
        document.getElementById('help-modal').addEventListener('click', (e) => {
            if (e.target.id === 'help-modal') closeHelpModal();
        });
        document.getElementById('about-workflow-modal').addEventListener('click', (e) => {
            if (e.target.id === 'about-workflow-modal') closeAboutWorkflowModal();
        });
        document.getElementById('resource-source-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-source-modal') closeResourceSourceModal();
        });
        document.getElementById('resource-channel-manage-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-channel-manage-modal') closeResourceChannelManageModal();
        });
        document.getElementById('resource-source-import-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-source-import-modal') closeResourceSourceImportModal();
        });
        document.getElementById('resource-source-manager-modal').addEventListener('click', (e) => {
            const panelBtn = e.target.closest('[data-resource-source-manager-panel]');
            if (panelBtn) {
                setResourceSourceManagerMobilePanel(panelBtn.dataset.resourceSourceManagerPanel || 'list');
                renderResourceSourceManagerModal();
                return;
            }
            if (e.target.id === 'resource-source-manager-modal') closeResourceSourceManagerModal();
        });
        document.getElementById('resource-import-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-import-modal') closeResourceJobModal();
        });
        document.getElementById('resource-folder-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-folder-modal') closeResourceFolderModal();
        });
        document.getElementById('resource-quick-link-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-quick-link-modal') closeResourceQuickLinkModal();
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
        document.getElementById('subscription-share-folder-list').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-share-folder-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionShareFolderAction || '';
            if (action === 'open') {
                await openSubscriptionShareFolderChild(btn.dataset.subscriptionShareFolderId || '0', btn.dataset.subscriptionShareFolderName || '--');
                return;
            }
            if (action === 'load-more') {
                await loadMoreSubscriptionShareCurrentFolder();
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
        document.getElementById('subscription-share-folder-breadcrumbs').addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-share-folder-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionShareFolderAction || '';
            if (action === 'trail') {
                await openSubscriptionShareFolderTrail(btn.dataset.subscriptionShareFolderIndex || '0');
            }
        });
        document.getElementById('resource-job-modal').addEventListener('click', (e) => {
            if (e.target.id === 'resource-job-modal') toggleResourceJobModal(false);
        });
        document.addEventListener('click', (e) => {
            if (shellMoreMenuOpen) {
                const menu = document.getElementById('shell-more-menu');
                const toggle = document.getElementById('shell-more-toggle');
                const clickedInsideMenu = !!menu && menu.contains(e.target);
                const clickedToggle = !!toggle && toggle.contains(e.target);
                if (!clickedInsideMenu && !clickedToggle) closeShellMoreMenu();
            }
            if (!resourceJobClearMenuOpen) return;
            const menu = document.getElementById('resource-job-clear-menu');
            if (!menu) return;
            if (menu.contains(e.target)) return;
            closeResourceJobClearMenu();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && shellMoreMenuOpen) {
                closeShellMoreMenu();
                return;
            }
            if (e.key === 'Escape' && resourceJobClearMenuOpen) {
                closeResourceJobClearMenu();
                return;
            }
            const aboutWorkflowModal = document.getElementById('about-workflow-modal');
            if (e.key === 'Escape' && aboutWorkflowModal && !aboutWorkflowModal.classList.contains('hidden')) {
                closeAboutWorkflowModal();
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
            const subscriptionShareFolderModal = document.getElementById('subscription-share-folder-modal');
            if (e.key === 'Escape' && subscriptionShareFolderModal && !subscriptionShareFolderModal.classList.contains('hidden')) {
                closeSubscriptionShareFolderModal();
                return;
            }
            const subscriptionModal = document.getElementById('subscription-modal');
            if (e.key === 'Escape' && subscriptionModal && !subscriptionModal.classList.contains('hidden')) {
                closeSubscriptionModal();
                return;
            }
            if (e.key === 'Escape' && resourceQuickLinkModalOpen) {
                closeResourceQuickLinkModal();
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
            if (e.key === 'Escape' && resourceChannelManageModalOpen) {
                closeResourceChannelManageModal();
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
                return;
            }
            if (action === 'load-more') {
                await loadMoreResourceShareCurrentFolder();
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
        document.getElementById('subscription_share_link_url').addEventListener('input', () => {
            const cidInput = document.getElementById('subscription_share_subdir_cid');
            if (cidInput) cidInput.value = '';
        });
        document.getElementById('subscription_share_subdir').addEventListener('input', () => {
            const cidInput = document.getElementById('subscription_share_subdir_cid');
            if (cidInput) cidInput.value = '';
        });
        window.addEventListener('scroll', () => {
            syncResourceBackTopButton();
            syncSettingsSaveDock();
        }, { passive: true });
        window.addEventListener('resize', () => {
            syncResourceBackTopButton();
            syncSettingsSaveDock();
            requestViewportMetricsSync();
        });
        window.addEventListener('orientationchange', requestViewportMetricsSync);
        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', requestViewportMetricsSync);
            window.visualViewport.addEventListener('scroll', requestViewportMetricsSync);
        }
        const THEME_DAY_ICON = `
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.8"/>
                <path d="M12 2.75V5.25M12 18.75V21.25M21.25 12H18.75M5.25 12H2.75M18.54 5.46L16.77 7.23M7.23 16.77L5.46 18.54M18.54 18.54L16.77 16.77M7.23 7.23L5.46 5.46" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
        `;
        const THEME_NIGHT_ICON = `
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M14.5 3.5C11.19 4.2 8.7 7.14 8.7 10.65C8.7 14.68 11.97 17.95 16 17.95C17.31 17.95 18.53 17.6 19.58 16.99C18.23 19.58 15.52 21.35 12.4 21.35C7.94 21.35 4.33 17.74 4.33 13.28C4.33 8.83 7.93 5.22 12.38 5.22C13.1 5.22 13.81 5.31 14.5 5.5V3.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
            </svg>
        `;
        function updateThemeToggleButton(isDay) {
            const btn = document.getElementById('theme-toggle');
            if (!btn) return;
            const icon = btn.querySelector('.theme-toggle-icon');
            if (!icon) return;
            const label = isDay ? '当前为日间模式，点击切换为夜间模式' : '当前为夜间模式，点击切换为日间模式';
            icon.innerHTML = isDay ? THEME_DAY_ICON : THEME_NIGHT_ICON;
            btn.setAttribute('aria-label', label);
            btn.setAttribute('title', label);
        }
        function applyThemeFromStorage() {
            try {
                const isDay = localStorage.getItem('theme-day') === 'day';
                document.documentElement.classList.toggle('theme-day', isDay);
                updateThemeToggleButton(isDay);
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
                updateThemeToggleButton(isDay);
            } catch (e) {}
        }
        syncViewportMetrics();
        applyThemeFromStorage();
        loadResourceQuickLinksFromStorage();
        initMainTabRow();
        const initPromise = init();
        syncResourceBackTopButton();
        syncSettingsSaveDock();
        syncMainTabRowState();
        refreshResourceState();
        initPromise.finally(() => {
            moduleVisitState.settings = true;
            connectStatusStream();
        });
        refreshVersionInfo();
        setInterval(() => refreshVersionInfo(false), VERSION_REFRESH_INTERVAL);
        setInterval(() => refreshSign115Status(false), SIGN115_REFRESH_INTERVAL);
        setInterval(() => {
            const keyword = document.getElementById('resource-search-input')?.value?.trim() || '';
            if (keyword && !isDirectImportInput(keyword)) {
                refreshResourceJobsOnly();
                return;
            }
            refreshResourceState();
        }, RESOURCE_REFRESH_INTERVAL);
    
