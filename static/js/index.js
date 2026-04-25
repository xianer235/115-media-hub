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
        let cookieHealthState = {
            '115': { configured: false, state: 'missing', message: '未配置 115 Cookie', last_checked_at: '', last_success_at: '', trigger: '', fail_count: 0 },
            quark: { configured: false, state: 'missing', message: '未配置 Quark Cookie', last_checked_at: '', last_success_at: '', trigger: '', fail_count: 0 }
        };
        let cookieHealthCheckBusy = false;
        let resourceState = { sources: [], quick_links: [], items: [], jobs: [], active_jobs: [], job_counts: {}, job_pagination: {}, channel_sections: [], channel_profiles: {}, subscription_channel_support: {}, search_sections: [], last_syncs: {}, monitor_tasks: [], stats: { source_count: 0, item_count: 0, filtered_item_count: 0, completed_job_count: 0 }, cookie_configured: false, quark_cookie_configured: false, cookie_health: null, setup_status: null, search: '', search_meta: {} };
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
        let resourceFolderFilesLoading = false;
        let resourceFolderEntriesComplete = false;
        let resourceFolderShowAllFiles = false;
        let resourceFolderCreateBusy = false;
        let resourceFolderRequestToken = 0;
        let resourceFolderBranchCache = {};
        let resourceFolderFetchInFlight = {};
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
        let resourceShareBranchCache = {};
        let resourceShareFetchInFlight = {};
        let subscriptionShareFolderFetchInFlight = {};
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
        let resourceJobLoadingMore = false;
        let resourceQuickLinkModalOpen = false;
        let resourceSourceModalOpen = false;
        let resourceSourceImportModalOpen = false;
        let resourceSourceManagerOpen = false;
        let resourceChannelManageModalOpen = false;
        let resourceChannelManageSourceIndex = -1;
        let resourceChannelManageChannelId = '';
        let resourceChannelManageDirty = false;
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
        let statusStreamHealthy = false;
        let statusFallbackTimer = null;
        let resourcePollTimer = null;
        let resourcePollInFlight = false;
        let sensitiveConfigMeta = {};
        const monitorActionLocks = new Set();
        let versionInfo = { local: null, latest: null, has_update: false, checked_at: 0, error: '', source: '' };
        let versionBannerDismissed = false;
        let currentTab = 'resource';
        let resourceStateHydrated = false;
        const moduleScrollTopState = {
            resource: 0,
            subscription: 0,
            monitor: 0,
            task: 0,
            settings: 0,
            about: 0
        };
        const tabRuntimeState = {
            tabModuleCache: {},
            shellTabRouterPromise: null
        };
        let tabSwitchTicket = 0;
        let suppressHashTabSync = false;
        let tabRuntimeModulePromise = null;
        let shellMoreMenuOpen = false;
        let shellRailExpanded = false;
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
        const SENSITIVE_SETTING_FIELDS = Object.freeze([
            'password',
            'cookie_115',
            'cookie_quark',
            'notify_wecom_webhook',
            'notify_wecom_app_secret',
            'tmdb_api_key',
        ]);
        const STATUS_FALLBACK_INTERVAL = 15000;
        const RESOURCE_POLL_ACTIVE_INTERVAL = 15000;
        const RESOURCE_POLL_SSE_INTERVAL = 30000;
        const RESOURCE_POLL_IDLE_INTERVAL = 60000;
        const VERSION_REFRESH_INTERVAL = 1000 * 60 * 15;
        const SIGN115_REFRESH_INTERVAL = 1000 * 60;
        const VERSION_FALLBACK_PROJECT_URL = 'https://github.com/xianer235/115-media-hub';
        const VERSION_FALLBACK_CHANGELOG_URL = 'https://github.com/xianer235/115-media-hub/blob/main/CHANGELOG.md';
        const RESOURCE_FOLDER_MEMORY_LEGACY_KEY = 'resource-folder-selection-v1';
        const RESOURCE_FOLDER_MEMORY_KEY = 'resource-folder-selection-v2';
        const RESOURCE_IMPORT_DELAY_MEMORY_KEY = 'resource-import-delay-seconds-v1';
        const RESOURCE_QUICK_LINKS_MEMORY_KEY = 'resource-quick-links-v1';
        const RESOURCE_QUICK_LINKS_LIMIT = 60;
        const MAIN_TAB_ROW_HINT_MEMORY_KEY = 'main-tab-row-hint-v1';
        const SHELL_RAIL_EXPANDED_MEMORY_KEY = 'shell-rail-expanded-v1';
        const TOAST_DEFAULT_DURATION_MS = 3000;
        const SUBSCRIPTION_EPISODE_CACHE_TTL_MS = 1000 * 60 * 3;
        const SUBSCRIPTION_INTRO_EPISODE_RETRY_MS = 1000 * 60;
        const RESOURCE_FOLDER_BRANCH_CACHE_TTL_MS = 1000 * 60 * 5;
        const RESOURCE_FOLDER_FILE_PREVIEW_LIMIT = 120;
        const RESOURCE_SHARE_BRANCH_CACHE_TTL_MS = 1000 * 60 * 10;
        const RESOURCE_SHARE_BROWSE_PAGE_LIMIT = 40;
        const RESOURCE_JOB_PAGE_SIZE = 20;
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
        const SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES = 120;
        const TAB_RUNTIME_IMPORT_PATH = '/static/js/modules/tabs/runtime.js';

        function getWindowScrollTop() {
            if (document.body.classList.contains('body-scroll-lock')) {
                return Math.max(0, Number(modalScrollLockY || 0));
            }
            return Math.max(0, window.scrollY || window.pageYOffset || 0);
        }

        function restoreWindowScrollTop(value = 0) {
            const target = Math.max(0, Number(value || 0));
            if (document.body.classList.contains('body-scroll-lock')) {
                modalScrollLockY = target;
                document.body.style.top = `-${target}px`;
                return;
            }
            window.scrollTo(0, target);
        }

        function restoreTabScrollPosition(tab) {
            const targetScrollTop = Math.max(0, Number(moduleScrollTopState[tab] || 0));
            restoreWindowScrollTop(targetScrollTop);
            window.requestAnimationFrame(() => {
                restoreWindowScrollTop(Math.max(0, Number(moduleScrollTopState[tab] || 0)));
                syncResourceBackTopButton();
                syncSettingsSaveDock();
            });
        }

        async function loadTabRuntimeModule() {
            if (tabRuntimeModulePromise) return tabRuntimeModulePromise;
            tabRuntimeModulePromise = import(TAB_RUNTIME_IMPORT_PATH).catch(() => null);
            return tabRuntimeModulePromise;
        }

        function buildTabModuleContext() {
            return {
                moduleVisitState,
                refreshResourceState,
                refreshSubscriptionState,
                refreshMonitorState,
                refreshMainLogs,
                refreshVersionInfo,
                getVersionInfo: () => versionInfo,
                isResourceStateHydrated: () => resourceStateHydrated,
            };
        }

        async function loadTabModule(tab) {
            const runtime = await loadTabRuntimeModule();
            if (!runtime?.loadTabModule) return null;
            return runtime.loadTabModule(tab, { tabModuleCache: tabRuntimeState.tabModuleCache });
        }

        async function createTabModuleContext() {
            const runtime = await loadTabRuntimeModule();
            if (runtime?.createTabModuleContext) {
                return runtime.createTabModuleContext(buildTabModuleContext());
            }
            const fallback = buildTabModuleContext();
            return {
                moduleVisitState: fallback.moduleVisitState,
                refreshResourceState: fallback.refreshResourceState,
                refreshSubscriptionState: fallback.refreshSubscriptionState,
                refreshMonitorState: fallback.refreshMonitorState,
                refreshMainLogs: fallback.refreshMainLogs,
                refreshVersionInfo: fallback.refreshVersionInfo,
                versionInfo,
                isResourceStateHydrated: fallback.isResourceStateHydrated,
            };
        }

        async function loadTaskTabModule() {
            return loadTabModule('task');
        }

        async function loadSettingsTabModule() {
            return loadTabModule('settings');
        }

        async function loadMonitorTabModule() {
            return loadTabModule('monitor');
        }

        async function loadSubscriptionTabModule() {
            return loadTabModule('subscription');
        }

        async function loadResourceTabModule() {
            return loadTabModule('resource');
        }

        async function loadAboutTabModule() {
            return loadTabModule('about');
        }

        async function readTabFromLocationHash() {
            const runtime = await loadTabRuntimeModule();
            if (!runtime?.readTabFromLocationHash) return '';
            return runtime.readTabFromLocationHash({
                state: tabRuntimeState,
                shellTabMeta: SHELL_TAB_META,
                currentHash: window.location.hash,
            });
        }

        async function syncLocationHashWithTab(tab, { replace = false } = {}) {
            const runtime = await loadTabRuntimeModule();
            if (!runtime?.syncLocationHashWithTab) return;
            await runtime.syncLocationHashWithTab(tab, {
                state: tabRuntimeState,
                currentHash: window.location.hash,
                pathname: window.location.pathname,
                search: window.location.search,
                replace,
                setHash: (nextHash) => {
                    window.location.hash = nextHash;
                },
                replaceUrl: (url) => {
                    history.replaceState(null, '', url);
                },
                onBeforeHashWrite: () => {
                    suppressHashTabSync = true;
                },
                onAfterHashWrite: () => {
                    window.setTimeout(() => {
                        suppressHashTabSync = false;
                    }, 0);
                }
            });
        }

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
            const scrollTop = getWindowScrollTop();
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
            const scrollTop = getWindowScrollTop();
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
            const tabModule = await loadTabModule(tab);
            if (tabModule && typeof tabModule.ensureTabData === 'function') {
                await tabModule.ensureTabData(await createTabModuleContext());
                return;
            }
            if (tab === 'resource') {
                moduleVisitState.resource = true;
                if (!resourceStateHydrated) await refreshResourceState();
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

        async function switchTab(tab, { syncHash = true, replaceHash = false } = {}) {
            const nextTab = SHELL_TAB_META[tab] ? tab : 'resource';
            const prevTab = currentTab;
            if (nextTab === prevTab) {
                if (syncHash) await syncLocationHashWithTab(nextTab, { replace: replaceHash });
                syncMainTabRowState();
                focusMainTab(nextTab);
                scheduleResourcePolling();
                return;
            }
            moduleScrollTopState[prevTab] = getWindowScrollTop();
            currentTab = nextTab;
            const switchTicket = ++tabSwitchTicket;
            Object.keys(SHELL_TAB_META).forEach(name => {
                const page = document.getElementById(`page-${name}`);
                if (page) page.classList.toggle('hidden', nextTab !== name);
            });
            if (nextTab !== 'resource') toggleResourceJobModal(false);
            closeShellMoreMenu();
            syncMainTabRowState();
            if (syncHash) await syncLocationHashWithTab(nextTab, { replace: replaceHash });
            await ensureTabData(nextTab);
            if (switchTicket !== tabSwitchTicket || currentTab !== nextTab) return;
            restoreTabScrollPosition(nextTab);
            focusMainTab(nextTab);
            scheduleResourcePolling(500);
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
            const settingsModule = tabRuntimeState.tabModuleCache.settings;
            if (settingsModule?.generateWebhookSecret) {
                settingsModule.generateWebhookSecret({ showToast });
                return;
            }
            void loadSettingsTabModule().then((mod) => {
                mod?.generateWebhookSecret?.({ showToast });
            });
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

        function normalizeSensitiveConfigMeta(meta) {
            const source = meta && typeof meta === 'object' ? meta : {};
            const result = {};
            SENSITIVE_SETTING_FIELDS.forEach((key) => {
                result[key] = !!source[key];
            });
            return result;
        }

        function applySensitiveConfigMeta(meta) {
            sensitiveConfigMeta = normalizeSensitiveConfigMeta(meta);
            SENSITIVE_SETTING_FIELDS.forEach((key) => {
                const el = document.getElementById(key);
                if (!el) return;
                if (!Object.prototype.hasOwnProperty.call(el.dataset, 'originPlaceholder')) {
                    el.dataset.originPlaceholder = String(el.getAttribute('placeholder') || '');
                }
                const configured = !!sensitiveConfigMeta[key];
                const originPlaceholder = String(el.dataset.originPlaceholder || '');
                if (configured) {
                    const suffix = '（已配置，留空不覆盖）';
                    el.setAttribute('placeholder', originPlaceholder ? `${originPlaceholder}${suffix}` : `已配置${suffix}`);
                    el.dataset.sensitiveConfigured = '1';
                } else {
                    el.setAttribute('placeholder', originPlaceholder);
                    el.dataset.sensitiveConfigured = '0';
                }
            });
        }

        function normalizeCookieHealthEntry(raw, provider = '115') {
            const source = raw && typeof raw === 'object' ? raw : {};
            const providerLabel = provider === 'quark' ? 'Quark' : '115';
            const configured = !!source.configured;
            const rawState = String(source.state || (configured ? 'unknown' : 'missing')).trim().toLowerCase();
            const state = ['missing', 'unknown', 'checking', 'valid', 'invalid', 'error'].includes(rawState)
                ? rawState
                : (configured ? 'unknown' : 'missing');
            let message = String(source.message || '').trim();
            if (!message) {
                if (state === 'missing') message = `未配置 ${providerLabel} Cookie`;
                else if (state === 'checking') message = `正在检测 ${providerLabel} Cookie...`;
                else if (state === 'valid') message = `${providerLabel} Cookie 可用`;
                else if (state === 'invalid') message = `${providerLabel} Cookie 可能已失效`;
                else if (state === 'error') message = `${providerLabel} Cookie 检测异常`;
                else message = `已配置 ${providerLabel} Cookie，等待检测`;
            }
            return {
                configured,
                state,
                message,
                last_checked_at: String(source.last_checked_at || ''),
                last_success_at: String(source.last_success_at || ''),
                trigger: String(source.trigger || ''),
                fail_count: Math.max(0, Number(source.fail_count || 0) || 0),
            };
        }

        function normalizeCookieHealthState(raw) {
            const source = raw && typeof raw === 'object' ? raw : {};
            return {
                '115': normalizeCookieHealthEntry(source['115'], '115'),
                quark: normalizeCookieHealthEntry(source.quark, 'quark'),
            };
        }

        function getCookieHealthTone(entry) {
            const state = String(entry?.state || '').trim().toLowerCase();
            if (state === 'valid') return 'success';
            if (state === 'invalid') return 'error';
            if (state === 'error') return 'error';
            if (state === 'checking') return 'checking';
            if (state === 'missing') return 'warn';
            return 'idle';
        }

        function applyCookieHealthCardTone(cardEl, tone) {
            if (!cardEl) return;
            cardEl.classList.remove(
                'border-slate-700/70', 'bg-slate-950/70',
                'border-sky-500/40', 'bg-sky-500/10',
                'border-emerald-500/40', 'bg-emerald-500/10',
                'border-amber-500/40', 'bg-amber-500/10',
                'border-rose-500/45', 'bg-rose-500/10'
            );
            if (tone === 'checking') {
                cardEl.classList.add('border-sky-500/40', 'bg-sky-500/10');
                return;
            }
            if (tone === 'success') {
                cardEl.classList.add('border-emerald-500/40', 'bg-emerald-500/10');
                return;
            }
            if (tone === 'warn') {
                cardEl.classList.add('border-amber-500/40', 'bg-amber-500/10');
                return;
            }
            if (tone === 'error') {
                cardEl.classList.add('border-rose-500/45', 'bg-rose-500/10');
                return;
            }
            cardEl.classList.add('border-slate-700/70', 'bg-slate-950/70');
        }

        function renderCookieHealthCards() {
            const providers = ['115', 'quark'];
            providers.forEach((provider) => {
                const entry = cookieHealthState?.[provider] || normalizeCookieHealthEntry({}, provider);
                const cardEl = document.getElementById(`cookie-health-${provider}-card`);
                const textEl = document.getElementById(`cookie-health-${provider}-text`);
                const tone = getCookieHealthTone(entry);
                applyCookieHealthCardTone(cardEl, tone);
                if (!textEl) return;
                const bits = [entry.message];
                if (entry.last_checked_at) bits.push(`上次检测 ${entry.last_checked_at}`);
                if (entry.last_success_at && entry.state !== 'valid') bits.push(`上次成功 ${entry.last_success_at}`);
                if (entry.fail_count > 0 && entry.state !== 'valid') bits.push(`连续失败 ${entry.fail_count} 次`);
                textEl.innerText = bits.filter(Boolean).join('；');
                textEl.classList.remove('text-slate-400', 'text-sky-200', 'text-emerald-200', 'text-amber-200', 'text-rose-200');
                if (tone === 'checking') textEl.classList.add('text-sky-200');
                else if (tone === 'success') textEl.classList.add('text-emerald-200');
                else if (tone === 'warn') textEl.classList.add('text-amber-200');
                else if (tone === 'error') textEl.classList.add('text-rose-200');
                else textEl.classList.add('text-slate-400');
            });

            const checkBtn = document.getElementById('cookie-health-check-btn');
            if (checkBtn) {
                checkBtn.disabled = cookieHealthCheckBusy;
                checkBtn.classList.toggle('btn-disabled', cookieHealthCheckBusy);
                checkBtn.innerText = cookieHealthCheckBusy ? '检测中...' : '立即检测 Cookie';
            }
        }

        function applyCookieHealthState(payload) {
            if (!payload || typeof payload !== 'object') return;
            cookieHealthState = normalizeCookieHealthState(payload);
            resourceState = {
                ...resourceState,
                cookie_health: cookieHealthState
            };
            renderCookieHealthCards();
            renderResourceCookieHint();
        }

        async function refreshCookieHealthStatus(force = false) {
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.refreshCookieHealthStatus) {
                await settingsModule.refreshCookieHealthStatus({
                    force,
                    applyCookieHealthState,
                });
            }
        }

        async function checkCookiesNow(force = true) {
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.checkCookiesNow) {
                await settingsModule.checkCookiesNow({
                    force,
                    isBusy: cookieHealthCheckBusy,
                    setBusy: (nextValue) => {
                        cookieHealthCheckBusy = !!nextValue;
                    },
                    renderCookieHealthCards,
                    applyCookieHealthState,
                    showToast,
                });
            }
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
                '保持不变': 'summary-skip',
                '跳过文件': 'summary-skip',
                '跳过目录': 'summary-skip',
                '总扫描': 'summary-info',
                '过期记录': 'summary-skip',
                '失败目录': 'summary-fail',
                '删除文件': 'summary-delete',
                '删除目录': 'summary-delete',
                '删除失败': 'summary-fail',
                '索引清理': 'summary-delete'
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
            if (/(执行成功|订阅成功|已完成|完成|已结束)/.test(raw)) return 'success';
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
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.refreshSign115Status) {
                await settingsModule.refreshSign115Status({
                    force,
                    applySign115State,
                });
            }
        }

        async function manualSign115(notify = false) {
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.manualSign115) {
                await settingsModule.manualSign115({
                    notify,
                    sign115State,
                    applySign115State,
                    showToast,
                });
            }
        }

        function applyMainState(data) {
            const taskModule = tabRuntimeState.tabModuleCache.task;
            if (taskModule?.applyMainState) {
                taskModule.applyMainState(data, {
                    getIsRunning: () => isRunning,
                    btnTexts,
                    setIsRunning: (nextValue) => {
                        isRunning = !!nextValue;
                    },
                    getLastLogSignature: () => lastLogSignature,
                    setLastLogSignature: (nextValue) => {
                        lastLogSignature = String(nextValue || '');
                    },
                    buildLogSignature,
                    getLogEntryClass,
                    formatLogHtml: formatMonitorLogHtml,
                });
                return;
            }
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
            const monitorModule = tabRuntimeState.tabModuleCache.monitor;
            if (monitorModule?.applyMonitorState) {
                monitorModule.applyMonitorState(data, {
                    forceRender,
                    getMonitorState: () => monitorState,
                    setMonitorState: (nextValue) => {
                        monitorState = { ...nextValue };
                    },
                    getIntroExpanded: () => monitorTaskIntroExpanded,
                    setIntroExpanded: (nextValue) => {
                        monitorTaskIntroExpanded = { ...(nextValue || {}) };
                    },
                    pruneTaskIntroExpanded,
                    buildMonitorRenderKey,
                    getLastMonitorRenderKey: () => lastMonitorRenderKey,
                    setLastMonitorRenderKey: (nextValue) => {
                        lastMonitorRenderKey = String(nextValue || '');
                    },
                    renderMonitorTasks,
                    renderMonitorLogs,
                    afterApply: (nextState) => {
                        resourceState.monitor_tasks = nextState.tasks || resourceState.monitor_tasks || [];
                        syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
                    },
                });
                return;
            }
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
                refreshCookieHealthStatus(false);
            }, STATUS_FALLBACK_INTERVAL);
        }

        function stopStatusFallbackPolling() {
            if (!statusFallbackTimer) return;
            window.clearInterval(statusFallbackTimer);
            statusFallbackTimer = null;
        }

        function getResourcePollingDelay() {
            const resourceTabVisible = currentTab === 'resource' && !document.hidden;
            if (resourceTabVisible) {
                return statusStreamHealthy ? RESOURCE_POLL_SSE_INTERVAL : RESOURCE_POLL_ACTIVE_INTERVAL;
            }
            if (hasActiveResourceJobs()) {
                return RESOURCE_POLL_ACTIVE_INTERVAL;
            }
            return statusStreamHealthy ? RESOURCE_POLL_IDLE_INTERVAL : RESOURCE_POLL_SSE_INTERVAL;
        }

        async function runResourcePollingTick() {
            if (resourcePollInFlight) {
                scheduleResourcePolling();
                return;
            }
            resourcePollInFlight = true;
            try {
                const keyword = String(document.getElementById('resource-search-input')?.value || resourceState.search || '').trim();
                const resourceTabVisible = currentTab === 'resource' && !document.hidden;
                if (resourceTabVisible) {
                    if (keyword && !isDirectImportInput(keyword)) {
                        await refreshResourceJobsOnly();
                    } else {
                        await refreshResourceState();
                    }
                } else if (hasActiveResourceJobs() || !statusStreamHealthy) {
                    await refreshResourceJobsOnly();
                }
            } finally {
                resourcePollInFlight = false;
                scheduleResourcePolling();
            }
        }

        function scheduleResourcePolling(delayOverride = null) {
            if (resourcePollTimer) {
                window.clearTimeout(resourcePollTimer);
                resourcePollTimer = null;
            }
            const parsedDelay = Number(delayOverride);
            const delay = Number.isFinite(parsedDelay) && parsedDelay >= 0
                ? parsedDelay
                : getResourcePollingDelay();
            resourcePollTimer = window.setTimeout(() => {
                void runResourcePollingTick();
            }, Math.max(1000, delay));
        }

        function connectStatusStream() {
            if (!window.EventSource) {
                statusStreamHealthy = false;
                startStatusFallbackPolling();
                scheduleResourcePolling(RESOURCE_POLL_ACTIVE_INTERVAL);
                return;
            }
            if (statusEventSource) statusEventSource.close();
            statusStreamHealthy = false;
            statusEventSource = new EventSource('/events');
            statusEventSource.addEventListener('state', (event) => {
                try {
                    const payload = JSON.parse(event.data || '{}');
                    stopStatusFallbackPolling();
                    applyMainState(payload.main);
                    applyMonitorState(payload.monitor);
                    applySubscriptionState(payload.subscription);
                    applySign115State(payload.sign115);
                    applyCookieHealthState(payload.cookie_health);
                } catch (err) {
                    console.warn('Status stream parse failed', err);
                }
            });
            statusEventSource.onopen = () => {
                statusStreamHealthy = true;
                stopStatusFallbackPolling();
                scheduleResourcePolling();
            };
            statusEventSource.onerror = () => {
                statusStreamHealthy = false;
                startStatusFallbackPolling();
                scheduleResourcePolling(RESOURCE_POLL_ACTIVE_INTERVAL);
            };
        }

        function formatTimeText(value) {
            if (!value) return '--';
            const d = new Date(value);
            if (Number.isNaN(d.getTime())) return String(value);
            return d.toLocaleString();
        }

        async function renderVersionInfoPanel() {
            const aboutModule = await loadAboutTabModule();
            if (!aboutModule?.renderVersionInfoPanel) return;
            aboutModule.renderVersionInfoPanel({
                versionInfo,
                fallbackProjectUrl: VERSION_FALLBACK_PROJECT_URL,
                fallbackChangelogUrl: VERSION_FALLBACK_CHANGELOG_URL,
                formatTimeText,
                escapeHtml,
            });
        }

        function showHelp(text) {
            const normalized = String(text || '').replace(/\\n/g, '\n');
            document.getElementById('help-modal-body').textContent = normalized;
            document.getElementById('help-modal').classList.remove('hidden');
        }

        function closeHelpModal() {
            document.getElementById('help-modal').classList.add('hidden');
        }

        function normalizeMountProviderInput(value) {
            const raw = String(value || '').trim().toLowerCase();
            if (!raw) return '';
            if (['115share', 'magnet115'].includes(raw)) return '115';
            if (['pan.quark', 'quarkshare', 'quark_pan'].includes(raw)) return 'quark';
            return raw.replace(/[^a-z0-9_.-]/g, '');
        }

        const BUILTIN_MOUNT_POINTS = Object.freeze([
            Object.freeze({ provider: '115', prefix: '/115' }),
            Object.freeze({ provider: 'quark', prefix: '/quark' }),
        ]);

        function getBuiltinMountPoints() {
            return BUILTIN_MOUNT_POINTS.map(item => ({ provider: item.provider, prefix: item.prefix }));
        }

        function getMountPrefixByProvider(provider) {
            const providerKey = normalizeMountProviderInput(provider);
            if (!providerKey) return '';
            const points = getBuiltinMountPoints();
            const matched = points.find(item => normalizeMountProviderInput(item.provider) === providerKey);
            return matched ? normalizeRemotePathInput(matched.prefix || '') : '';
        }

        function addTreeRow(data = { path: '', prefix: '', exclude: 1 }) {
            const container = document.getElementById('trees-container');
            const row = document.createElement('div');
            row.className = "tree-row grid grid-cols-12 gap-3 items-end bg-slate-900/50 p-4 rounded-2xl border border-slate-800 hover:border-slate-700 transition-colors";
            const sourcePath = String(data.path || '').trim();
            row.innerHTML = `
                <div class="col-span-12 md:col-span-6">
                    <span class="text-[10px] text-slate-500 ml-1 font-bold uppercase">115 目录树文件路径（相对 115 根目录）</span>
                    <input class="t-url w-full bg-slate-950 border-slate-700 rounded-lg p-2.5 text-sm mt-1 outline-none focus:border-sky-500" value="${escapeHtml(sourcePath)}" placeholder="例如 目录树.txt 或 子目录/目录树.txt">
                    <div class="text-[10px] text-slate-500 leading-4 mt-1">根目录填 目录树.txt；子目录填 子目录/目录树.txt。兼容 /目录树.txt、/115/目录树.txt、完整 URL。</div>
                </div>
                <div class="col-span-6 md:col-span-4">
                    <span class="text-[10px] text-slate-500 ml-1 font-bold uppercase">父文件夹路径前缀 (选填)</span>
                    <input class="t-prefix w-full bg-slate-950 border-slate-700 rounded-lg p-2.5 text-sm mt-1 outline-none focus:border-sky-500" value="${escapeHtml(data.prefix)}" placeholder="补全丢失的路径，如: 电影/漫威">
                </div>
                <div class="col-span-4 md:col-span-1">
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
            const taskModule = await loadTaskTabModule();
            if (taskModule?.triggerTask) {
                await taskModule.triggerTask({
                    local,
                    full,
                    isRunning,
                    btnTexts,
                    setIsRunning: (nextValue) => {
                        isRunning = !!nextValue;
                    }
                });
                return;
            }
            if (isRunning) return;
            const res = await fetch('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({use_local: local, force_full: full})
            });
            if ((await res.json()).status === 'started') updateButtonState(true);
        }

        function updateButtonState(running) {
            const taskModule = tabRuntimeState.tabModuleCache.task;
            if (taskModule?.updateButtonState) {
                taskModule.updateButtonState({
                    running,
                    btnTexts,
                    setIsRunning: (nextValue) => {
                        isRunning = !!nextValue;
                    }
                });
                return;
            }
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
            const settingsModule = tabRuntimeState.tabModuleCache.settings;
            if (settingsModule?.syncNotifyChannelUI) {
                settingsModule.syncNotifyChannelUI();
                return;
            }
            void loadSettingsTabModule().then((mod) => {
                mod?.syncNotifyChannelUI?.();
            });
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
            const settingsModule = tabRuntimeState.tabModuleCache.settings;
            if (settingsModule?.renderTgProxyTestStatus) {
                settingsModule.renderTgProxyTestStatus({
                    tgProxyTestState,
                    escapeHtml,
                    formatDurationText,
                });
                return;
            }
            void loadSettingsTabModule().then((mod) => {
                mod?.renderTgProxyTestStatus?.({
                    tgProxyTestState,
                    escapeHtml,
                    formatDurationText,
                });
            });
        }

        async function testTgProxyLatency() {
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.testTgProxyLatency) {
                await settingsModule.testTgProxyLatency({
                    getCurrentTgProxyConfig,
                    getTgProxyTestState: () => tgProxyTestState,
                    setTgProxyTestState: (nextValue) => {
                        tgProxyTestState = { ...nextValue };
                    },
                    renderTgProxyTestStatus,
                });
            }
        }

        function renderNotifyTestStatus() {
            const settingsModule = tabRuntimeState.tabModuleCache.settings;
            if (settingsModule?.renderNotifyTestStatus) {
                settingsModule.renderNotifyTestStatus({
                    notifyTestState,
                    escapeHtml,
                    notifyChannelLabel,
                });
                return;
            }
            void loadSettingsTabModule().then((mod) => {
                mod?.renderNotifyTestStatus?.({
                    notifyTestState,
                    escapeHtml,
                    notifyChannelLabel,
                });
            });
        }

        async function testNotifyPush() {
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.testNotifyPush) {
                await settingsModule.testNotifyPush({
                    getCurrentNotifyConfig,
                    getNotifyTestState: () => notifyTestState,
                    setNotifyTestState: (nextValue) => {
                        notifyTestState = { ...nextValue };
                    },
                    renderNotifyTestStatus,
                });
            }
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
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.saveSettings) {
                await settingsModule.saveSettings({
                    sensitiveSettingFields: SENSITIVE_SETTING_FIELDS,
                    getSensitiveConfigMeta: () => sensitiveConfigMeta,
                    applySensitiveConfigMeta,
                    applyCookieHealthState,
                    refreshResourceState,
                    refreshSign115Status,
                    getMonitorTasks: () => monitorState.tasks || [],
                });
            }
        }

        async function clearMainLogs() {
            const taskModule = await loadTaskTabModule();
            if (taskModule?.clearMainLogs) {
                await taskModule.clearMainLogs({
                    setLastLogSignature: (nextValue) => {
                        lastLogSignature = String(nextValue || '');
                    },
                    refreshMainLogs,
                });
                return;
            }
            const res = await fetch('/logs/clear', { method: 'POST' });
            if (res.ok) {
                lastLogSignature = '';
                await refreshMainLogs();
            }
        }

        async function clearMonitorLogs() {
            const monitorModule = await loadMonitorTabModule();
            if (monitorModule?.clearMonitorLogs) {
                await monitorModule.clearMonitorLogs({
                    setLastMonitorLogSignature: (nextValue) => {
                        lastMonitorLogSignature = String(nextValue || '');
                    },
                    refreshMonitorState,
                });
                return;
            }
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
            const taskModule = await loadTaskTabModule();
            if (taskModule?.refreshMainLogs) {
                await taskModule.refreshMainLogs({
                    applyMainState,
                });
                return;
            }
            try {
                const res = await fetch('/logs');
                if (!res.ok) return;
                applyMainState(await res.json());
            } catch (e) {}
        }

        async function refreshMonitorState() {
            const monitorModule = await loadMonitorTabModule();
            if (monitorModule?.refreshMonitorState) {
                await monitorModule.refreshMonitorState({
                    applyMonitorState,
                });
                return;
            }
            try {
                const res = await fetch('/monitor/status');
                if (!res.ok) return;
                applyMonitorState(await res.json());
            } catch (e) {}
        }
