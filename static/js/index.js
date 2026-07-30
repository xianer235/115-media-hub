        let isRunning = false;
        let monitorState = { running: false, current_task: '', tasks: [], logs: [], log_segments: [], log_segment_total: 0, log_segment_has_more: false, summary: { step: '空闲', detail: '等待监控任务' }, queued: [], next_runs: {} };
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
        let resourceState = { sources: [], quick_links: [], favorite_dirs: { '115': [], quark: [] }, items: [], jobs: [], active_jobs: [], job_counts: {}, job_pagination: {}, channel_sections: [], channel_profiles: {}, subscription_channel_support: {}, search_sections: [], last_syncs: {}, channel_sync: {}, monitor_tasks: [], stats: { source_count: 0, item_count: 0, filtered_item_count: 0, completed_job_count: 0 }, cookie_configured: false, quark_cookie_configured: false, cookie_health: null, setup_status: null, search: '', search_source: 'tg', provider_filter: 'all', default_magnet_provider: '115', search_meta: {} };
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
        let monitorFolderTrail = [{ id: '0', name: '根目录' }];
        let monitorFolderEntries = [];
        let monitorFolderSummary = { folder_count: 0, file_count: 0 };
        let monitorFolderLoading = false;
        let monitorFolderRequestToken = 0;
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
        let resourceShareDiagnosticsByParent = {};
        let resourceShareSearchKeyword = '';
        let resourceShareReceiveCode = '';
        let resourceShareTrail = [{ cid: '0', name: '分享根目录' }];
        let resourceShareCurrentCid = '0';
        let resourceShareRequestToken = 0;
        let resourceShareBranchCache = {};
        let resourceShareFetchInFlight = {};
        let subscriptionShareFolderFetchInFlight = {};
        let resourceSectionCollapsed = {};
        let resourceSearchSource = 'tg';
        let resourceProviderFilter = 'all';
        let resourceSearchBusy = false;
        let resourceSearchAbortController = null;
        let resourceActiveSearchId = '';
        let resourceSearchCancelRequested = false;
        let resourceRestartSearchAfterCancel = false;
        let resourceSyncBusy = false;
        let resourceSyncCancelBusy = false;
        let resourceChannelExtraItems = {};
        let resourceChannelLoadingMore = {};
        let resourceChannelNextBefore = {};
        let resourceChannelNoMore = {};
        let resourceTempIdSeed = -1;
        let resourceBatchImportItems = [];
        let resourceEd2kState = {
            active: false,
            loading: false,
            error: '',
            requestToken: 0,
            sourceUrl: '',
            pageTitle: '',
            titleText: '',
            titleTokens: [],
            selectedTitleIndexes: [],
            titleExpanded: true,
            items: [],
            selectedItemIds: [],
            createFolder: true,
            folderName: '',
        };
        let resourceEd2kTitleGesture = null;
        let resourceClientIdSeed = -100000;
        let resourceClientIdsByIdentity = {};
        let resourceJobModalOpen = false;
        let resourceJobClearMenuOpen = false;
        let resourceJobLoadingMore = false;
        let taskCenterTab = 'resource';
        let scraperJobState = { jobs: [], job_counts: {}, active_jobs: [] };
        let scraperJobFilter = 'all';
        let scraperJobExpanded = new Set();
        let scraperJobLoading = false;
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
        let resourceSourceSortMode = 'manual';
        let resourceSourceSortSessionActive = false;
        let resourceSourceSortDraftIndexes = [];
        let resourceSourceSortDragIndex = -1;
        let resourceSourceSortPointerActive = false;
        let resourceSourceSortPointerId = null;
        let resourceSourceSortPointerIndex = -1;
        let resourceSourceSortPointerClientX = 0;
        let resourceSourceSortPointerClientY = 0;
        let resourceSourceSortDropTargetIndex = -1;
        let resourceSourceSortDropAfter = false;
        let resourceSourceSortAutoScrollRafId = 0;
        let resourceSourceBulkSelected = {};
        let resourceSourceManagerMobilePanel = 'list';
        let resourceSourcePersistToken = 0;
        let resourceSourcePersistTimer = null;
        let resourceSourcePersistInFlight = false;
        let resourceSourcePersistQueuedSources = null;
        let resourceSourcePersistQueuedToken = 0;
        let resourceSourcePersistPending = [];
        let resourceSourcePersistRollbackSources = null;
        let resourceSourceTestBusy = false;
        let resourceSourceNameSyncBusy = false;
        let resourceSourceTestResult = { total: 0, done: 0, success: 0, failed: 0, running: false, last_name: '', error: '' };
        let resourceHeavyRenderRafId = null;
        let resourceSubmitBusy = false;
        let resourceSubmitBusyToken = 0;
        let resourceSubmitRefreshToken = 0;
        let resourceJobFilter = 'all';
        let appMountPoints = [];
        let tgProxyTestState = { loading: false, ok: null, message: '', latency_ms: 0, mode: '', proxy_url: '', target_url: '' };
        let pansouTestState = { loading: false, ok: null, message: '', latency_ms: 0, auth_enabled: false, auth_configured: false, auth_logged_in: false, plugin_count: 0, channels_count: 0 };
        let notifyTestState = { loading: false, ok: null, message: '', channel: '', target_desc: '', webhook_host: '', sent_at: '' };
        let resourceBoardHintText = '';
        let resourceActiveSearchRuntime = null;
        let resourceTgHealthState = { visible: false, tone: 'loading', title: '', meta: '', note: '' };
        let resourceTgLastLatencyMs = 0;
        let lastLogSignature = '';
        let lastMonitorLogSignature = '';
        let monitorLogLoadBusy = false;
        let lastSubscriptionLogSignature = '';
        let lastMonitorRenderKey = '';
        let lastSubscriptionRenderKey = '';
        let monitorTaskIntroExpanded = {};
        let subscriptionTaskIntroExpanded = {};
        let statusEventSource = null;
        let sseReconnectAttempt = 0;
        const SSE_RECONNECT_BASE_MS = 1000;
        const SSE_RECONNECT_MAX_MS = 30000;
        let statusStreamHealthy = false;
        let statusFallbackTimer = null;
        let resourcePollTimer = null;
        let resourcePollInFlight = false;
        let resourceJobsSignalState = { revision: 0, updated_at: '', reason: '', latest_job: {} };
        let lastResourceChannelSyncFinishNotifiedAt = '';
        let sensitiveConfigMeta = {};
        const monitorActionLocks = new Set();
        let versionInfo = { local: null, latest: null, has_update: false, checked_at: 0, error: '', source: '' };
        let versionBannerDismissed = false;
        let currentTab = 'resource';
        let resourceStateHydrated = false;
        const moduleScrollTopState = {
            resource: 0,
            recommendation: 0,
            subscription: 0,
            scraper: 0,
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
            recommendation: false,
            subscription: false,
            scraper: false,
            monitor: false,
            task: false,
            settings: false,
            about: false
        };
        const SHELL_TAB_META = {
            resource: { title: '资源中心' },
            recommendation: { title: '资源推荐' },
            subscription: { title: '影视订阅' },
            scraper: { title: '刮削管理' },
            monitor: { title: '文件夹监控' },
            task: { title: '目录树同步' },
            settings: { title: '参数配置' },
            about: { title: '关于与版本' }
        };
        const btnTexts = ["🌐 联网增量写入", "🛠 本地调试解析", "🔥 强制全量重写"];
        let strmOrphanPreviewState = { root: '', candidates: [], empty_dirs: [], manual_check: [] };
        let strmOrphanScanBusy = false;
        let strmOrphanHasScanned = false;
        let strmOrphanFilter = 'all';
        let strmOrphanSelectedPaths = new Set();
        let strmCleanupActiveRoot = '';
        let strmCleanupConfirmedRoot = '';
        let strmCleanupDefaultRoot = '';
        let strmCleanupRootBrowserPath = '';
        let strmCleanupRootBrowserParent = '';
        let strmCleanupRootBrowserEntries = [];
        let strmCleanupRootBrowserBusy = false;
        let strmCleanupRootBrowserError = '';
        let strmCleanupMainTab = 'browse';
        const DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,wmv,flv,webm,vob,mpg,mpeg,ts,m2ts,mts,rmvb,rm,asf,3gp,m4v,f4v,iso";
        function getSensitiveSettingFields() {
            const fields = [
                'password',
                'cookie_115',
                'cookie_quark',
                'notify_wecom_webhook',
                'notify_wecom_app_secret',
                'tmdb_api_key',
                'pansou_password',
            ];
            const meta = window.providerMeta || [];
            meta.forEach(p => {
                (p.config_keys || []).forEach(ck => {
                    if (ck && fields.indexOf(ck) === -1) fields.push(ck);
                });
            });
            return fields;
        }
        const STATUS_FALLBACK_INTERVAL = 15000;
        const RESOURCE_SYNC_POLL_INTERVAL = 3000;
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
        const CURRENT_ASSET_IMPORT_QUERY = (() => {
            try {
                const script = document.currentScript
                    || Array.from(document.scripts || []).find(item => String(item?.src || '').includes('/static/js/index.js'));
                const url = new URL(String(script?.src || ''), window.location.origin);
                const version = String(url.searchParams.get('v') || '').trim();
                return version ? `?v=${encodeURIComponent(version)}` : '';
            } catch (e) {
                return '';
            }
        })();

        function withCurrentAssetImportQuery(path) {
            const value = String(path || '').trim();
            if (!value || !CURRENT_ASSET_IMPORT_QUERY || value.includes('?')) return value;
            return `${value}${CURRENT_ASSET_IMPORT_QUERY}`;
        }

        const TAB_RUNTIME_IMPORT_PATH = withCurrentAssetImportQuery('/static/js/modules/tabs/runtime.js');

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
                window.syncScraperBackTopButton?.();
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

        async function loadScraperTabModule() {
            return loadTabModule('scraper');
        }

        async function loadResourceTabModule() {
            return loadTabModule('resource');
        }

        async function loadRecommendationTabModule() {
            return loadTabModule('recommendation');
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
            window.syncScraperBackTopButton?.();
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
            window.syncScraperBackTopButton?.();
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
            if (tab === 'scraper') {
                moduleVisitState.scraper = true;
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

        function ensureAppDialogModal() {
            let modal = document.getElementById('app-dialog-modal');
            if (modal) return modal;
            modal = document.createElement('div');
            modal.id = 'app-dialog-modal';
            modal.className = 'app-dialog-modal hidden';
            modal.innerHTML = `
                <div class="app-dialog-shell" role="dialog" aria-modal="true" aria-labelledby="app-dialog-title">
                    <div class="app-dialog-header">
                        <div>
                            <div id="app-dialog-eyebrow" class="app-dialog-eyebrow">提示</div>
                            <div id="app-dialog-title" class="app-dialog-title">提示</div>
                        </div>
                        <button id="app-dialog-close" type="button" class="app-dialog-close" aria-label="关闭">关闭</button>
                    </div>
                    <div class="app-dialog-body">
                        <div id="app-dialog-message" class="app-dialog-message"></div>
                        <textarea id="app-dialog-text" class="app-dialog-text hidden" readonly></textarea>
                    </div>
                    <div class="app-dialog-footer">
                        <button id="app-dialog-copy" type="button" class="app-dialog-btn app-dialog-btn-secondary hidden">复制内容</button>
                        <button id="app-dialog-cancel" type="button" class="app-dialog-btn app-dialog-btn-secondary hidden">取消</button>
                        <button id="app-dialog-confirm" type="button" class="app-dialog-btn app-dialog-btn-primary">确定</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
            return modal;
        }

        function showAppDialog({
            title = '提示',
            message = '',
            eyebrow = '提示',
            tone = 'info',
            confirmText = '确定',
            cancelText = '取消',
            showCancel = false,
            text = '',
            copyText = '',
        } = {}) {
            return new Promise((resolve) => {
                const modal = ensureAppDialogModal();
                const shell = modal.querySelector('.app-dialog-shell');
                const eyebrowEl = modal.querySelector('#app-dialog-eyebrow');
                const titleEl = modal.querySelector('#app-dialog-title');
                const messageEl = modal.querySelector('#app-dialog-message');
                const textEl = modal.querySelector('#app-dialog-text');
                const closeBtn = modal.querySelector('#app-dialog-close');
                const copyBtn = modal.querySelector('#app-dialog-copy');
                const cancelBtn = modal.querySelector('#app-dialog-cancel');
                const confirmBtn = modal.querySelector('#app-dialog-confirm');
                const normalizedTone = ['success', 'error', 'warn', 'info'].includes(String(tone || '').toLowerCase())
                    ? String(tone || '').toLowerCase()
                    : 'info';
                shell.className = `app-dialog-shell app-dialog-${normalizedTone}`;
                eyebrowEl.textContent = String(eyebrow || '提示');
                titleEl.textContent = String(title || '提示');
                messageEl.textContent = String(message || '');
                const displayText = String(text || copyText || '');
                textEl.value = displayText;
                textEl.classList.toggle('hidden', !displayText);
                copyBtn.classList.toggle('hidden', !displayText);
                cancelBtn.classList.toggle('hidden', !showCancel);
                confirmBtn.textContent = String(confirmText || '确定');
                cancelBtn.textContent = String(cancelText || '取消');

                let settled = false;
                const cleanup = (value) => {
                    if (settled) return;
                    settled = true;
                    modal.classList.add('hidden');
                    unlockPageScroll();
                    confirmBtn.removeEventListener('click', onConfirm);
                    cancelBtn.removeEventListener('click', onCancel);
                    closeBtn.removeEventListener('click', onCancel);
                    copyBtn.removeEventListener('click', onCopy);
                    modal.removeEventListener('click', onBackdrop);
                    document.removeEventListener('keydown', onKeydown);
                    resolve(value);
                };
                const onConfirm = () => cleanup(true);
                const onCancel = () => cleanup(false);
                const onCopy = async () => {
                    try {
                        await navigator.clipboard.writeText(displayText);
                        showToast('内容已复制', { tone: 'success', duration: 1800, placement: 'top-center' });
                    } catch (e) {
                        showToast('复制失败，请手动选中文本复制', { tone: 'warn', duration: 2400, placement: 'top-center' });
                        textEl.focus();
                        textEl.select();
                    }
                };
                const onBackdrop = (event) => {
                    if (event.target === modal) cleanup(false);
                };
                const onKeydown = (event) => {
                    if (event.key === 'Escape') cleanup(false);
                    if (event.key === 'Enter' && !event.shiftKey && document.activeElement !== textEl) cleanup(true);
                };

                confirmBtn.addEventListener('click', onConfirm);
                cancelBtn.addEventListener('click', onCancel);
                closeBtn.addEventListener('click', onCancel);
                copyBtn.addEventListener('click', onCopy);
                modal.addEventListener('click', onBackdrop);
                document.addEventListener('keydown', onKeydown);
                modal.classList.remove('hidden');
                lockPageScroll();
                window.setTimeout(() => confirmBtn.focus(), 30);
            });
        }

        function showAppAlert(message, options = {}) {
            const text = String(message || '').trim();
            return showAppDialog({
                title: options.title || (text.startsWith('❌') ? '操作失败' : text.startsWith('✅') ? '操作成功' : '提示'),
                message: text,
                eyebrow: options.eyebrow || 'Message',
                tone: options.tone || (text.startsWith('❌') ? 'error' : text.startsWith('✅') ? 'success' : 'info'),
                confirmText: options.confirmText || '知道了',
            });
        }

        function showAppConfirm(message, options = {}) {
            return showAppDialog({
                title: options.title || '确认操作',
                message,
                eyebrow: options.eyebrow || 'Confirm',
                tone: options.tone || 'warn',
                showCancel: true,
                confirmText: options.confirmText || '确认',
                cancelText: options.cancelText || '取消',
            });
        }

        function showAppPrompt(message, defaultValue = '', options = {}) {
            return showAppDialog({
                title: options.title || '请手动复制',
                message,
                eyebrow: options.eyebrow || 'Copy',
                tone: options.tone || 'info',
                text: defaultValue,
                copyText: defaultValue,
                confirmText: options.confirmText || '关闭',
            });
        }

        window.showToast = showToast;
        window.showAppDialog = showAppDialog;
        window.showAppAlert = showAppAlert;
        window.showAppConfirm = showAppConfirm;
        window.showAppPrompt = showAppPrompt;

        window.alert = (message) => {
            void showAppAlert(message);
        };
        window.confirm = (message) => {
            void showAppConfirm(message);
            return false;
        };
        window.prompt = (message, defaultValue = '') => {
            void showAppPrompt(message, defaultValue);
            return '';
        };

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
            getSensitiveSettingFields().forEach((key) => {
                result[key] = !!source[key];
            });
            return result;
        }

        function applySensitiveConfigMeta(meta) {
            const suffix = '（已配置，留空不覆盖）';
            sensitiveConfigMeta = normalizeSensitiveConfigMeta(meta);
            getSensitiveSettingFields().forEach((key) => {
                const el = document.getElementById(key);
                if (!el) return;
                let raw = String(el.getAttribute('placeholder') || '');
                if (raw.endsWith(suffix)) raw = raw.slice(0, -suffix.length);
                if (!Object.prototype.hasOwnProperty.call(el.dataset, 'originPlaceholder')) {
                    el.dataset.originPlaceholder = raw;
                }
                const configured = !!sensitiveConfigMeta[key];
                const originPlaceholder = String(el.dataset.originPlaceholder || '');
                if (configured) {
                    el.setAttribute('placeholder', originPlaceholder ? `${originPlaceholder}${suffix}` : suffix);
                    el.dataset.sensitiveConfigured = '1';
                } else {
                    el.setAttribute('placeholder', originPlaceholder);
                    el.dataset.sensitiveConfigured = '0';
                }
            });
        }

        function normalizeCookieHealthEntry(raw, provider = '115') {
            const source = raw && typeof raw === 'object' ? raw : {};
            const meta = (window.providerMeta || []).find(p => p.name === provider);
            const providerLabel = meta?.label || provider;
            const enabled = Object.prototype.hasOwnProperty.call(source, 'enabled')
                ? source.enabled !== false
                : meta?.enabled !== false;
            const configured = !!source.configured;
            const rawState = String(source.state || (configured ? 'unknown' : 'missing')).trim().toLowerCase();
            const state = ['disabled', 'missing', 'unknown', 'checking', 'valid', 'invalid', 'error'].includes(rawState)
                ? rawState
                : (configured ? 'unknown' : 'missing');
            let message = String(source.message || '').trim();
            if (!message) {
                if (state === 'disabled') message = `${providerLabel} 未启用`;
                else if (state === 'missing') message = `未配置 ${providerLabel} Cookie`;
                else if (state === 'checking') message = `正在检测 ${providerLabel} Cookie...`;
                else if (state === 'valid') message = `${providerLabel} Cookie 可用`;
                else if (state === 'invalid') message = `${providerLabel} Cookie 可能已失效`;
                else if (state === 'error') message = `${providerLabel} Cookie 检测异常`;
                else message = `已配置 ${providerLabel} Cookie，等待检测`;
            }
            return {
                enabled,
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
            const result = {};
            Object.keys(source).forEach((key) => {
                result[key] = normalizeCookieHealthEntry(source[key], key);
            });
            return result;
        }

        function getCookieHealthTone(entry) {
            const state = String(entry?.state || '').trim().toLowerCase();
            if (state === 'valid') return 'success';
            if (state === 'invalid') return 'error';
            if (state === 'error') return 'error';
            if (state === 'checking') return 'checking';
            if (state === 'missing') return 'warn';
            if (state === 'disabled') return 'idle';
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
            const meta = window.providerMeta || [];
            meta.forEach((p) => {
                const entry = cookieHealthState?.[p.name] || normalizeCookieHealthEntry({}, p.name);
                const cardEl = document.getElementById(`cookie-health-${p.name}-card`);
                const textEl = document.getElementById(`cookie-health-${p.name}-text`);
                const tone = getCookieHealthTone(entry);
                if (cardEl) applyCookieHealthCardTone(cardEl, tone);
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
            if (typeof updateCookieHealthBar === 'function') {
                updateCookieHealthBar(cookieHealthState);
            }
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

        async function checkCookiesNow(force = true, providers = null) {
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.checkCookiesNow) {
                return await settingsModule.checkCookiesNow({
                    force,
                    providers,
                    isBusy: cookieHealthCheckBusy,
                    setBusy: (nextValue) => {
                        cookieHealthCheckBusy = !!nextValue;
                    },
                    renderCookieHealthCards,
                    getCookieHealthState: () => cookieHealthState,
                    applyCookieHealthState,
                    showToast,
                });
            }
            return false;
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
                '删除 STRM': 'summary-delete',
                '删除空目录': 'summary-delete',
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
            if (/(执行失败|失败|异常|错误)/.test(raw)) return 'error';
            if (/(已中断|中断|取消)/.test(raw)) return 'warn';
            if (/(任务结束|订阅结束|执行成功|订阅成功|MD5 校验命中|已完成|完成|已结束)/.test(raw)) return 'success';
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

        function setMonitorSummary(summary) {
            const step = String(summary?.step || '空闲').trim() || '空闲';
            const detail = String(summary?.detail || '等待监控任务').trim() || '等待监控任务';
            const fullText = `当前状态：${step} / ${detail}`;

            const summaryStep = document.getElementById('monitor-summary-step');
            if (summaryStep) summaryStep.innerText = step;
            const summaryDetail = document.getElementById('monitor-summary-detail');
            if (summaryDetail) {
                summaryDetail.innerText = detail;
                summaryDetail.setAttribute('title', detail);
            }
            const summaryPill = document.getElementById('monitor-summary-pill');
            if (summaryPill) {
                summaryPill.setAttribute('title', fullText);
                summaryPill.setAttribute('aria-label', fullText);
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
            const incomingSegments = Array.isArray(data.log_segments) ? data.log_segments : null;
            const currentSegments = Array.isArray(monitorState.log_segments) ? monitorState.log_segments : [];
            let logSegments = currentSegments;
            if (incomingSegments) {
                const previousTotal = Number(monitorState.log_segment_total || 0) || currentSegments.length;
                const nextTotal = Number(data.log_segment_total || 0) || incomingSegments.length;
                if (nextTotal < previousTotal || currentSegments.length <= incomingSegments.length) {
                    logSegments = incomingSegments;
                } else {
                    const incomingIds = new Set(incomingSegments.map(segment => String(segment?.id || '')).filter(Boolean));
                    const olderSegments = currentSegments.filter(segment => {
                        const id = String(segment?.id || '');
                        return id && !incomingIds.has(id);
                    });
                    logSegments = [...olderSegments, ...incomingSegments];
                }
            }
            monitorState = {
                ...monitorState,
                ...data,
                tasks: Array.isArray(data.tasks) ? data.tasks : (monitorState.tasks || []),
                logs: Array.isArray(data.logs) ? data.logs : (monitorState.logs || []),
                log_segments: logSegments,
                log_segment_total: Number(data.log_segment_total || monitorState.log_segment_total || logSegments.length) || logSegments.length,
                log_segment_has_more: logSegments.length < (Number(data.log_segment_total || monitorState.log_segment_total || logSegments.length) || logSegments.length),
                queued: Array.isArray(data.queued) ? data.queued : (monitorState.queued || []),
                next_runs: data.next_runs || monitorState.next_runs || {},
                summary: data.summary || monitorState.summary || { step: '空闲', detail: '等待监控任务' }
            };
            monitorTaskIntroExpanded = pruneTaskIntroExpanded(monitorTaskIntroExpanded, monitorState.tasks);

            setMonitorSummary(monitorState.summary);

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
            statusFallbackTimer = window.setInterval(async () => {
                try {
                    const payload = await window.MediaHubApi.getJson('/status-summary');
                    applyMainState(payload.main);
                    applyMonitorState(payload.monitor);
                    applySubscriptionState(payload.subscription);
                    applySign115State(payload.sign115);
                    applyCookieHealthState(payload.cookie_health);
                    applyResourceChannelSyncState(payload.resource_channel_sync);
                    applyResourceJobsSignalState(payload.resource_jobs);
                } catch (e) {}
            }, STATUS_FALLBACK_INTERVAL);
        }

        function stopStatusFallbackPolling() {
            if (!statusFallbackTimer) return;
            window.clearInterval(statusFallbackTimer);
            statusFallbackTimer = null;
        }

        function normalizeResourceChannelSyncState(value) {
            const source = value && typeof value === 'object' ? value : {};
            return {
                submitted: !!source.submitted,
                running: !!source.running,
                cancel_requested: !!source.cancel_requested,
                cancelled: !!source.cancelled,
                started_at: String(source.started_at || ''),
                started_ts: Number(source.started_ts || 0) || 0,
                finished_at: String(source.finished_at || ''),
                finished_ts: Number(source.finished_ts || 0) || 0,
                duration_ms: Math.max(0, Number(source.duration_ms || source.last_result?.duration_ms || 0) || 0),
                last_updated_at: String(source.last_updated_at || ''),
                last_result: source.last_result && typeof source.last_result === 'object' ? source.last_result : {},
                last_error: String(source.last_error || '')
            };
        }

        function isResourceChannelSyncActive(state = resourceState.channel_sync) {
            const syncState = normalizeResourceChannelSyncState(state);
            return !!syncState.submitted || !!syncState.running;
        }

        function handleResourceChannelSyncStateChange(previousState, nextState, { refreshOnComplete = true } = {}) {
            const prev = normalizeResourceChannelSyncState(previousState);
            const next = normalizeResourceChannelSyncState(nextState);
            const wasActive = !!prev.submitted || !!prev.running;
            const isActive = !!next.submitted || !!next.running;
            if (isActive) {
                if (currentTab === 'resource' && !document.hidden) {
                    scheduleResourcePolling(RESOURCE_SYNC_POLL_INTERVAL);
                }
                if (!resourceSyncBusy && !resourceSyncCancelBusy) {
                    setResourceTgHealthState({
                        visible: true,
                        tone: 'loading',
                        title: next.cancel_requested ? '频道同步停止中' : '频道同步后台运行中',
                        meta: next.cancel_requested ? '等待当前批次收尾' : '',
                        note: '',
                    });
                }
                return;
            }
            if (!wasActive || !next.finished_at || next.finished_at === lastResourceChannelSyncFinishNotifiedAt) return;
            lastResourceChannelSyncFinishNotifiedAt = next.finished_at;

            const result = next.last_result && typeof next.last_result === 'object' ? next.last_result : {};
            const durationMs = Math.max(0, Number(next.duration_ms || result.duration_ms || 0) || 0);
            if (next.cancelled || result.cancelled) {
                applyResourceTgHealthFromSyncResult(
                    { ...result, queued: false, cancelled: true },
                    durationMs,
                    resourceTgLastLatencyMs,
                );
            } else if (next.last_error) {
                setResourceTgHealthResult({
                    tone: 'error',
                    title: '频道同步失败',
                    detail: next.last_error,
                    durationMs,
                    includeLatency: false,
                    detailFirst: true,
                });
            } else {
                applyResourceTgHealthFromSyncResult({ ...result, queued: false }, durationMs, resourceTgLastLatencyMs);
            }
            if (
                refreshOnComplete
                && currentTab === 'resource'
                && !document.hidden
                && typeof refreshResourceState === 'function'
            ) {
                void refreshResourceState({ allowSearch: false });
            }
        }

        function applyResourceChannelSyncState(payload, options = {}) {
            if (!payload || typeof payload !== 'object') return;
            const previous = resourceState.channel_sync || {};
            const next = normalizeResourceChannelSyncState(payload);
            resourceState = { ...resourceState, channel_sync: next };
            handleResourceChannelSyncStateChange(previous, next, options);
            if (typeof window.syncResourceActionButtons === 'function') {
                window.syncResourceActionButtons();
            } else if (typeof window.renderResourceBoardHint === 'function') {
                window.renderResourceBoardHint();
            }
        }

        function normalizeResourceItemStatusFromJob(status) {
            const normalized = String(status || '').trim().toLowerCase();
            if (normalized === 'running') return 'importing';
            if (normalized === 'pending') return 'queued';
            if (['queued', 'importing', 'submitted', 'completed', 'failed'].includes(normalized)) return normalized;
            return '';
        }

        function getResourceJobId(job = {}) {
            return Number(job?.id || 0) || 0;
        }

        function normalizeResourceJobStatus(status) {
            return String(status || '').trim().toLowerCase();
        }

        function isResourceJobActiveStatus(status) {
            return ['pending', 'running', 'submitted'].includes(normalizeResourceJobStatus(status));
        }

        function normalizeResourceJobListFilter(value = 'all') {
            const normalized = String(value || 'all').trim().toLowerCase();
            return ['all', 'active', 'submitted', 'completed', 'failed'].includes(normalized) ? normalized : 'all';
        }

        function doesResourceJobMatchFilter(job = {}, filter = 'all') {
            const normalizedFilter = normalizeResourceJobListFilter(filter);
            const status = normalizeResourceJobStatus(job?.status || '');
            if (normalizedFilter === 'active') return isResourceJobActiveStatus(status);
            if (normalizedFilter === 'submitted') return status === 'submitted';
            if (normalizedFilter === 'completed') return status === 'completed';
            if (normalizedFilter === 'failed') return status === 'failed';
            return true;
        }

        function hasResourceJobSignalDiff(previousJob = {}, nextJob = {}) {
            return ['id', 'resource_id', 'status', 'status_detail', 'updated_at', 'finished_at', 'last_triggered_at']
                .some(key => String(previousJob?.[key] ?? '') !== String(nextJob?.[key] ?? ''));
        }

        function mergeResourceJobSignalIntoList(jobs = [], latestJob = {}, { filter = 'all', addWhenMatched = false } = {}) {
            const sourceJobs = Array.isArray(jobs) ? jobs : [];
            const jobId = getResourceJobId(latestJob);
            if (!jobId) return { jobs: sourceJobs, changed: false };

            const signalJob = {
                ...latestJob,
                id: jobId,
                resource_id: Number(latestJob?.resource_id || 0) || 0,
                status: normalizeResourceJobStatus(latestJob?.status || ''),
            };
            const matchedFilter = doesResourceJobMatchFilter(signalJob, filter);
            let changed = false;
            let found = false;
            const nextJobs = [];
            sourceJobs.forEach((job) => {
                if (getResourceJobId(job) !== jobId) {
                    nextJobs.push(job);
                    return;
                }
                found = true;
                if (!matchedFilter) {
                    changed = true;
                    return;
                }
                const mergedJob = { ...job, ...signalJob };
                if (hasResourceJobSignalDiff(job, mergedJob)) changed = true;
                nextJobs.push(mergedJob);
            });
            if (!found && addWhenMatched && matchedFilter) {
                nextJobs.unshift(signalJob);
                changed = true;
            }
            return { jobs: changed ? nextJobs : sourceJobs, changed };
        }

        function applyResourceJobStatusToItems(items = [], resourceId = 0, status = '') {
            if (!resourceId || !status || !Array.isArray(items)) return items;
            let changed = false;
            const nextItems = items.map((item) => {
                if (Number(item?.id || 0) !== resourceId || String(item?.status || '') === status) return item;
                changed = true;
                return { ...item, status };
            });
            return changed ? nextItems : items;
        }

        function applyResourceJobStatusToSections(sections = [], resourceId = 0, status = '') {
            if (!resourceId || !status || !Array.isArray(sections)) return sections;
            let changed = false;
            const nextSections = sections.map((section) => {
                const items = Array.isArray(section?.items) ? section.items : [];
                const nextItems = applyResourceJobStatusToItems(items, resourceId, status);
                if (nextItems === items) return section;
                changed = true;
                return { ...section, items: nextItems };
            });
            return changed ? nextSections : sections;
        }

        function applyResourceJobSignalToResourceState(job = {}) {
            const resourceId = Number(job?.resource_id || 0) || 0;
            const status = normalizeResourceItemStatusFromJob(job?.status || '');
            const jobId = getResourceJobId(job);
            if ((!resourceId || !status) && !jobId) return false;
            const currentItems = Array.isArray(resourceState.items) ? resourceState.items : [];
            const currentChannelSections = Array.isArray(resourceState.channel_sections) ? resourceState.channel_sections : [];
            const currentSearchSections = Array.isArray(resourceState.search_sections) ? resourceState.search_sections : [];
            const nextItems = applyResourceJobStatusToItems(currentItems, resourceId, status);
            const nextChannelSections = applyResourceJobStatusToSections(currentChannelSections, resourceId, status);
            const nextSearchSections = applyResourceJobStatusToSections(currentSearchSections, resourceId, status);
            const jobPageFilter = normalizeResourceJobListFilter(resourceState?.job_pagination?.status || resourceJobFilter || 'all');
            const nextJobsResult = mergeResourceJobSignalIntoList(resourceState.jobs || [], job, {
                filter: jobPageFilter,
                addWhenMatched: false,
            });
            const nextActiveJobsResult = mergeResourceJobSignalIntoList(resourceState.active_jobs || [], job, {
                filter: 'active',
                addWhenMatched: isResourceJobActiveStatus(job?.status || ''),
            });
            const selectedChanged = selectedResourceItem && Number(selectedResourceItem?.id || 0) === resourceId;
            const changed = nextItems !== currentItems
                || nextChannelSections !== currentChannelSections
                || nextSearchSections !== currentSearchSections
                || nextJobsResult.changed
                || nextActiveJobsResult.changed
                || selectedChanged;
            if (!changed) return false;
            resourceState = {
                ...resourceState,
                items: nextItems,
                jobs: nextJobsResult.jobs,
                active_jobs: nextActiveJobsResult.jobs,
                channel_sections: nextChannelSections,
                search_sections: nextSearchSections,
            };
            if (selectedChanged) {
                selectedResourceItem = { ...selectedResourceItem, status };
            }
            if (currentTab === 'resource') {
                if (typeof renderResourceJobs === 'function') renderResourceJobs();
                if (typeof syncResourceJobModalTrigger === 'function') syncResourceJobModalTrigger();
                renderResourceBoard();
                renderResourceBoardHint();
            }
            return true;
        }

        function normalizeResourceJobsSignalState(value) {
            const source = value && typeof value === 'object' ? value : {};
            return {
                revision: Number(source.revision || 0) || 0,
                updated_at: String(source.updated_at || ''),
                reason: String(source.reason || ''),
                latest_job: source.latest_job && typeof source.latest_job === 'object' ? source.latest_job : {},
            };
        }

        function applyResourceJobsSignalState(payload) {
            if (!payload || typeof payload !== 'object') return;
            const previous = resourceJobsSignalState || { revision: 0 };
            const next = normalizeResourceJobsSignalState(payload);
            resourceJobsSignalState = next;
            if (next.revision <= 0 || next.revision === Number(previous.revision || 0)) return;
            applyResourceJobSignalToResourceState(next.latest_job);
            if (!document.hidden) {
                scheduleResourcePolling(1000);
            }
        }

        function getResourcePollingDelay() {
            const resourceTabVisible = currentTab === 'resource' && !document.hidden;
            if (resourceTabVisible && isResourceChannelSyncActive()) {
                return RESOURCE_SYNC_POLL_INTERVAL;
            }
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
                const scraperJobsActive = typeof hasActiveScraperJobs === 'function' && hasActiveScraperJobs();
                const scraperJobsVisible = resourceJobModalOpen && taskCenterTab === 'scraper';
                if (resourceTabVisible) {
                    if (isResourceChannelSyncActive()) {
                        await refreshResourceState({ allowSearch: false, compact: true });
                    } else if (keyword && !isDirectImportInput(keyword)) {
                        await refreshResourceJobsOnly();
                    } else {
                        await refreshResourceState({ compact: true });
                    }
                    if ((scraperJobsActive || scraperJobsVisible) && typeof fetchScraperJobsState === 'function') {
                        await fetchScraperJobsState({ silent: true });
                    }
                } else if (hasActiveResourceJobs() || scraperJobsVisible || !statusStreamHealthy) {
                    if (typeof refreshTaskCenterJobsOnly === 'function' && (scraperJobsActive || scraperJobsVisible)) {
                        await refreshTaskCenterJobsOnly();
                    } else {
                        await refreshResourceJobsOnly();
                    }
                }
            } finally {
                resourcePollInFlight = false;
                scheduleResourcePolling();
            }
        }

        let resourcePollingPaused = false;

        function pauseResourcePolling() {
            resourcePollingPaused = true;
            if (resourcePollTimer) {
                window.clearTimeout(resourcePollTimer);
                resourcePollTimer = null;
            }
        }

        function resumeResourcePolling(delay = 500) {
            resourcePollingPaused = false;
            scheduleResourcePolling(delay);
        }

        function scheduleResourcePolling(delayOverride = null) {
            if (resourcePollingPaused) return;
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
        window.scheduleResourcePolling = scheduleResourcePolling;

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
                    const changed = Array.isArray(payload._changed) ? payload._changed : null;
                    if (changed) {
                        if (changed.includes('main') && payload.main) applyMainState(payload.main);
                        if (changed.includes('monitor') && payload.monitor) applyMonitorState(payload.monitor);
                        if (changed.includes('subscription') && payload.subscription) applySubscriptionState(payload.subscription);
                        if (changed.includes('sign115') && payload.sign115) applySign115State(payload.sign115);
                        if (changed.includes('cookie_health') && payload.cookie_health) applyCookieHealthState(payload.cookie_health);
                        if (changed.includes('resource_channel_sync') && payload.resource_channel_sync) applyResourceChannelSyncState(payload.resource_channel_sync);
                        if (changed.includes('resource_jobs') && payload.resource_jobs) applyResourceJobsSignalState(payload.resource_jobs);
                    } else {
                        if (payload.main) applyMainState(payload.main);
                        if (payload.monitor) applyMonitorState(payload.monitor);
                        if (payload.subscription) applySubscriptionState(payload.subscription);
                        if (payload.sign115) applySign115State(payload.sign115);
                        if (payload.cookie_health) applyCookieHealthState(payload.cookie_health);
                        if (payload.resource_channel_sync) applyResourceChannelSyncState(payload.resource_channel_sync);
                        if (payload.resource_jobs) applyResourceJobsSignalState(payload.resource_jobs);
                    }
                } catch (err) {
                    console.warn('Status stream parse failed', err);
                }
            });
            statusEventSource.onopen = () => {
                statusStreamHealthy = true;
                sseReconnectAttempt = 0;
                stopStatusFallbackPolling();
                scheduleResourcePolling();
            };
            statusEventSource.onerror = () => {
                statusStreamHealthy = false;
                startStatusFallbackPolling();
                scheduleResourcePolling(RESOURCE_POLL_ACTIVE_INTERVAL);
                statusEventSource.close();
                sseReconnectAttempt += 1;
                const delay = Math.min(
                    SSE_RECONNECT_MAX_MS,
                    SSE_RECONNECT_BASE_MS * Math.pow(2, sseReconnectAttempt - 1)
                );
                window.setTimeout(() => {
                    connectStatusStream();
                }, delay);
            };
        }

        (function wrapPostJsonForRequestPriority() {
            if (!window.MediaHubApi || typeof window.MediaHubApi.postJson !== 'function') return;
            var originalPostJson = window.MediaHubApi.postJson.bind(window.MediaHubApi);
            window.MediaHubApi.postJson = async function () {
                pauseResourcePolling();
                try {
                    return await originalPostJson.apply(this, arguments);
                } finally {
                    resumeResourcePolling();
                }
            };
        })();

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

        function normalizeMountPointsInput(value) {
            const source = Array.isArray(value) ? value : [];
            const seen = new Set();
            const normalized = [];
            source.forEach((item) => {
                const provider = normalizeMountProviderInput(item?.provider || '');
                const prefix = normalizeRemotePathInput(item?.prefix || '');
                if (!provider || !prefix || prefix === '/' || seen.has(provider)) return;
                seen.add(provider);
                normalized.push({ provider, prefix });
            });
            getBuiltinMountPoints().forEach((item) => {
                const provider = normalizeMountProviderInput(item.provider);
                const prefix = normalizeRemotePathInput(item.prefix);
                if (!provider || !prefix || prefix === '/' || seen.has(provider)) return;
                seen.add(provider);
                normalized.push({ provider, prefix });
            });
            return normalized;
        }

        function setAppMountPoints(value) {
            appMountPoints = normalizeMountPointsInput(value);
        }

        function getMountPrefixByProvider(provider) {
            const providerKey = normalizeMountProviderInput(provider);
            if (!providerKey) return '';
            const points = Array.isArray(appMountPoints) && appMountPoints.length
                ? appMountPoints
                : normalizeMountPointsInput([]);
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

        async function resetExtensions() {
            if (await showAppConfirm("确定要恢复默认扫描后缀名吗？\n(恢复后请手动点击下方的保存全部配置)")) {
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
            const data = await window.MediaHubApi.postJson('/start', { use_local: local, force_full: full }).catch(() => null);
            if (data?.status === 'started') updateButtonState(true);
        }

        function formatOrphanExtensions(item) {
            const extensions = Array.isArray(item?.extensions) ? item.extensions : [];
            const unknown = Array.isArray(item?.unknown_extensions) ? item.unknown_extensions : [];
            const knownText = extensions.filter(ext => ext !== '.strm').slice(0, 8).join('、') || '--';
            if (!unknown.length) return knownText;
            return `${knownText}；未知：${unknown.slice(0, 6).join('、')}`;
        }

        function getOrphanKindMeta(kind) {
            if (kind === 'empty') {
                return { label: '空文件夹', tone: 'empty', selectable: true };
            }
            if (kind === 'manual') {
                return { label: '需手动检查', tone: 'manual', selectable: false };
            }
            return { label: '仅剩元数据', tone: 'metadata', selectable: true };
        }

        function getStrmCleanupRootInput() {
            return document.getElementById('strm-cleanup-root-input');
        }

        function getStrmCleanupRootInputValue() {
            return String(getStrmCleanupRootInput()?.value || '').trim();
        }

        function setStrmCleanupRootInputValue(value) {
            const input = getStrmCleanupRootInput();
            if (!input) return;
            input.value = String(value || '').trim();
        }

        function buildStrmCleanupPathSegments(path) {
            const normalized = normalizeStrmCleanupRoot(path);
            const defaultRoot = normalizeStrmCleanupRoot(strmCleanupDefaultRoot);
            if (!normalized) return [];
            const relative = defaultRoot && normalized.startsWith(defaultRoot)
                ? normalized.slice(defaultRoot.length).replace(/^\/+/, '')
                : '';
            const segments = [];
            if (defaultRoot) {
                segments.push({ label: defaultRoot.split('/').filter(Boolean).pop() || defaultRoot || '/', path: defaultRoot });
            } else {
                segments.push({ label: normalized.split('/').filter(Boolean).pop() || normalized || '/', path: normalized });
            }
            if (!relative) return segments;
            let current = defaultRoot || normalized;
            relative.split('/').filter(Boolean).forEach((part) => {
                current = `${current.replace(/\/+$/, '')}/${part}`;
                segments.push({ label: part, path: current });
            });
            return segments;
        }

        function renderStrmCleanupPathbar(path = '') {
            const pathbarEl = document.getElementById('strm-cleanup-root-pathbar');
            if (!pathbarEl) return;
            const targetPath = normalizeStrmCleanupRoot(path || getStrmCleanupRootInputValue() || strmCleanupRootBrowserPath || strmCleanupDefaultRoot);
            if (!targetPath) {
                pathbarEl.innerHTML = '<span class="strm-cleanup-root-pathbar-empty">未选择目录</span>';
                return;
            }
            const segments = buildStrmCleanupPathSegments(targetPath);
            pathbarEl.innerHTML = segments.map((segment, index) => {
                const isLast = index === segments.length - 1;
                const label = escapeHtml(segment.label || '--');
                const button = `<button type="button" class="strm-cleanup-root-crumb ${isLast ? 'is-current' : ''}" data-strm-cleanup-root-path="${escapeHtml(segment.path)}" ${isLast ? 'aria-current="page"' : ''} onclick="openStrmCleanupRootChild(this.dataset.strmCleanupRootPath)">${label}</button>`;
                const separator = isLast ? '' : '<span class="strm-cleanup-root-crumb-sep">/</span>';
                return `${button}${separator}`;
            }).join('');
        }

        function getStrmCleanupRequestedRoot() {
            return getStrmCleanupRootInputValue();
        }

        function getStrmCleanupRequestedRootLabel() {
            return getStrmCleanupRequestedRoot() || strmCleanupDefaultRoot || '默认 STRM 目录';
        }

        function getStrmCleanupConfirmedRoot() {
            return normalizeStrmCleanupRoot(strmCleanupConfirmedRoot);
        }

        function hasConfirmedStrmCleanupRoot() {
            return !!getStrmCleanupConfirmedRoot();
        }

        function normalizeStrmCleanupRoot(root) {
            return String(root || '').trim();
        }

        function getStrmCleanupComparableRequestedRoot() {
            return normalizeStrmCleanupRoot(getStrmCleanupRequestedRoot() || strmCleanupDefaultRoot);
        }

        function buildStrmCleanupPreviewUrl(root) {
            const normalized = normalizeStrmCleanupRoot(root);
            if (!normalized) return '/strm/orphan-metadata/preview';
            return `/strm/orphan-metadata/preview?root=${encodeURIComponent(normalized)}`;
        }

        function buildStrmCleanupLocalDirsUrl(path) {
            const normalized = normalizeStrmCleanupRoot(path);
            if (!normalized) return '/strm/orphan-metadata/local-dirs';
            return `/strm/orphan-metadata/local-dirs?path=${encodeURIComponent(normalized)}`;
        }

        async function fetchStrmCleanupLocalDirs(path = '') {
            return await window.MediaHubApi.getJson(buildStrmCleanupLocalDirsUrl(path));
        }

        async function ensureStrmCleanupDefaultRoot({ syncSelection = true, silent = true } = {}) {
            if (!strmCleanupDefaultRoot) {
                try {
                    const data = await fetchStrmCleanupLocalDirs('');
                    strmCleanupDefaultRoot = String(data?.default_root || data?.path || '').trim();
                } catch (error) {
                    if (!silent) {
                        showToast(`默认目录读取失败：${error?.message || '请稍后重试'}`, {
                            tone: 'error',
                            duration: 3200,
                            placement: 'top-center'
                        });
                    }
                }
            }
            if (syncSelection && strmCleanupDefaultRoot && !getStrmCleanupRequestedRoot()) {
                setStrmCleanupRootInputValue(strmCleanupDefaultRoot);
            }
            updateStrmCleanupRootHint();
            return strmCleanupDefaultRoot;
        }

        function resetStrmCleanupResultsForPendingScan(root) {
            const normalizedRoot = normalizeStrmCleanupRoot(root || strmCleanupDefaultRoot);
            strmCleanupActiveRoot = '';
            strmOrphanHasScanned = false;
            strmOrphanSelectedPaths = new Set();
            renderOrphanMetadataPreview({
                root: normalizedRoot,
                default_root: strmCleanupDefaultRoot,
                candidates: [],
                empty_dirs: [],
                manual_check: []
            });
        }

        function isStrmCleanupBrowseTabActive() {
            return strmCleanupMainTab === 'browse';
        }

        function updateStrmCleanupModeView() {
            const browserPanel = document.getElementById('strm-cleanup-browser-panel');
            const resultsPanel = document.getElementById('strm-cleanup-results-panel');
            const browseTabBtn = document.getElementById('strm-cleanup-tab-browse');
            const resultsTabBtn = document.getElementById('strm-cleanup-tab-results');
            const browsing = isStrmCleanupBrowseTabActive();
            const resultsLocked = !hasConfirmedStrmCleanupRoot();
            if (browserPanel) {
                browserPanel.classList.toggle('hidden', !browsing);
                browserPanel.setAttribute('aria-hidden', browsing ? 'false' : 'true');
            }
            if (resultsPanel) {
                resultsPanel.classList.toggle('hidden', browsing);
                resultsPanel.setAttribute('aria-hidden', browsing ? 'true' : 'false');
            }
            if (browseTabBtn) {
                browseTabBtn.classList.toggle('is-active', browsing);
                browseTabBtn.setAttribute('aria-selected', browsing ? 'true' : 'false');
                browseTabBtn.tabIndex = browsing ? 0 : -1;
            }
            if (resultsTabBtn) {
                resultsTabBtn.classList.toggle('is-active', !browsing);
                resultsTabBtn.setAttribute('aria-selected', browsing ? 'false' : 'true');
                resultsTabBtn.tabIndex = browsing ? -1 : 0;
                resultsTabBtn.disabled = resultsLocked && browsing;
                resultsTabBtn.classList.toggle('btn-disabled', resultsLocked && browsing);
            }
        }

        function setStrmCleanupScopePanelExpanded(expanded, { loadBrowser = false } = {}) {
            if (!expanded && !hasConfirmedStrmCleanupRoot()) {
                showToast('请先在“选择目录”里确认待处理目录', {
                    tone: 'warn',
                    duration: 2200,
                    placement: 'top-center'
                });
                strmCleanupMainTab = 'browse';
                updateStrmCleanupModeView();
                return;
            }
            strmCleanupMainTab = expanded ? 'browse' : 'results';
            updateStrmCleanupModeView();
            if (!expanded || !loadBrowser) return;
            const targetPath = getStrmCleanupRequestedRoot() || strmCleanupRootBrowserPath || strmCleanupDefaultRoot;
            if (targetPath) {
                void loadStrmCleanupRootBrowser(targetPath);
                return;
            }
            void ensureStrmCleanupDefaultRoot({ syncSelection: true, silent: true }).then((defaultRoot) => {
                if (isStrmCleanupBrowseTabActive() && defaultRoot) {
                    void loadStrmCleanupRootBrowser(defaultRoot);
                }
            });
        }

        function updateStrmCleanupScanButton() {
            const scanBtn = document.getElementById('strm-orphan-scan-btn');
            if (!scanBtn) return;
            const disabled = strmOrphanScanBusy || !hasConfirmedStrmCleanupRoot();
            scanBtn.disabled = disabled;
            scanBtn.classList.toggle('btn-disabled', disabled);
            if (strmOrphanScanBusy) {
                scanBtn.innerText = '扫描中...';
                return;
            }
            if (!hasConfirmedStrmCleanupRoot()) {
                scanBtn.innerText = '请先确认目录';
                return;
            }
            scanBtn.innerText = strmOrphanHasScanned ? '重新扫描当前目录' : '扫描当前目录';
        }

        function isStrmCleanupRootChangedSinceScan() {
            if (!strmOrphanHasScanned) return false;
            return getStrmCleanupConfirmedRoot() !== normalizeStrmCleanupRoot(strmCleanupActiveRoot);
        }

        function updateStrmCleanupRootHint() {
            const input = getStrmCleanupRootInput();
            if (input && strmCleanupDefaultRoot) {
                input.placeholder = strmCleanupDefaultRoot;
            }
            const requestedRoot = getStrmCleanupRequestedRoot() || strmCleanupDefaultRoot;
            const confirmedRoot = getStrmCleanupConfirmedRoot();
            if (requestedRoot && !getStrmCleanupRequestedRoot()) {
                setStrmCleanupRootInputValue(requestedRoot);
            }
            renderStrmCleanupPathbar(requestedRoot);
        }

        function renderStrmCleanupRootBrowser() {
            const listEl = document.getElementById('strm-cleanup-root-browser-list');
            const parentBtn = document.getElementById('strm-cleanup-root-parent-btn');
            const refreshBtn = document.getElementById('strm-cleanup-root-refresh-btn');
            const useBtn = document.getElementById('strm-cleanup-root-use-btn');
            const requestedRoot = getStrmCleanupComparableRequestedRoot();
            const confirmedRoot = getStrmCleanupConfirmedRoot();
            const activeRoot = normalizeStrmCleanupRoot(strmCleanupActiveRoot);
            const rootChanged = isStrmCleanupRootChangedSinceScan();
            if (parentBtn) {
                parentBtn.disabled = strmCleanupRootBrowserBusy || !strmCleanupRootBrowserParent;
                parentBtn.classList.toggle('btn-disabled', parentBtn.disabled);
            }
            if (refreshBtn) {
                refreshBtn.disabled = strmCleanupRootBrowserBusy || !strmCleanupRootBrowserPath;
                refreshBtn.classList.toggle('btn-disabled', refreshBtn.disabled);
            }
            if (useBtn) {
                const alreadySelected = !!confirmedRoot && confirmedRoot === normalizeStrmCleanupRoot(strmCleanupRootBrowserPath);
                useBtn.disabled = strmCleanupRootBrowserBusy || !strmCleanupRootBrowserPath;
                useBtn.classList.toggle('btn-disabled', useBtn.disabled);
                useBtn.innerText = alreadySelected ? '继续处理当前目录' : '确认目录并进入扫描处理';
            }
            renderStrmCleanupPathbar(strmCleanupRootBrowserPath || requestedRoot);
            if (!listEl) return;
            if (strmCleanupRootBrowserBusy && !strmCleanupRootBrowserEntries.length) {
                listEl.innerHTML = '<div class="strm-cleanup-root-empty">正在读取目录...</div>';
                return;
            }
            if (strmCleanupRootBrowserError) {
                listEl.innerHTML = `<div class="strm-cleanup-root-empty">${escapeHtml(strmCleanupRootBrowserError)}</div>`;
                return;
            }
            if (!strmCleanupRootBrowserEntries.length) {
                listEl.innerHTML = '<div class="strm-cleanup-root-empty">当前目录下没有子目录，可以直接使用当前目录扫描。</div>';
                return;
            }
            const manager = window.MediaHubFileManager;
            const entries = strmCleanupRootBrowserEntries.map((entry) => {
                const path = String(entry?.path || '').trim();
                const name = String(entry?.name || path || '--').trim();
                const modified = String(entry?.last_modified || '') || '--';
                const normalizedPath = normalizeStrmCleanupRoot(path);
                const isRequested = !!requestedRoot && requestedRoot === normalizedPath;
                const isConfirmed = !!confirmedRoot && confirmedRoot === normalizedPath;
                const badgeText = isConfirmed
                    ? (!rootChanged && strmOrphanHasScanned && activeRoot === normalizedPath ? '当前扫描目录' : '已确认目录')
                    : (isRequested ? '当前显示目录' : '');
                return {
                    ...entry,
                    id: path,
                    name,
                    path,
                    modified_at: modified,
                    is_dir: true,
                    is_current: isRequested || isConfirmed,
                    secondaryText: badgeText,
                };
            });
            const columns = [
                {
                    key: 'name',
                    label: '名称',
                    sortable: true,
                    cellClass: 'file-manager-cell--name',
                    render: (entry) => manager.renderNameCell(entry, {
                        nameHtml: `<span class="strm-cleanup-root-row-name" title="${escapeHtml(entry.path || entry.name || '')}">${escapeHtml(entry.name || '--')}</span>`,
                        iconClass: 'strm-cleanup-folder-icon',
                        mainClass: 'strm-cleanup-root-row-main',
                    }),
                },
                {
                    key: 'modified_at',
                    label: '修改时间',
                    sortable: true,
                    cellClass: 'file-manager-cell--modified',
                    render: (entry) => escapeHtml(entry.modified_at || '--'),
                },
            ];
            listEl.innerHTML = manager.renderTable({
                entries,
                columns,
                sort: { key: 'name', direction: 'asc' },
                sortable: true,
                entryFilter: 'folders',
                foldersFirst: true,
                tableClass: 'strm-cleanup-root-manager',
                emptyText: '当前目录下没有子目录，可以直接使用当前目录扫描。',
                gridTemplate: 'minmax(220px, 1fr) 142px',
                minWidth: '520px',
                rowTag: 'button',
                rowClass: (entry) => `strm-cleanup-root-row ${entry.is_current ? 'is-current' : ''}`,
                rowAttrs: (entry) => `data-strm-cleanup-root-path="${escapeHtml(entry.path)}" onclick="openStrmCleanupRootChild(this.dataset.strmCleanupRootPath)"`,
            });
        }

        async function loadStrmCleanupRootBrowser(path = '') {
            if (strmCleanupRootBrowserBusy) return;
            strmCleanupRootBrowserBusy = true;
            strmCleanupRootBrowserError = '';
            strmCleanupRootBrowserEntries = [];
            strmCleanupRootBrowserParent = '';
            strmCleanupRootBrowserPath = normalizeStrmCleanupRoot(path || strmCleanupRootBrowserPath);
            renderStrmCleanupRootBrowser();
            try {
                const data = await fetchStrmCleanupLocalDirs(path);
                strmCleanupRootBrowserPath = String(data?.path || '').trim();
                strmCleanupRootBrowserParent = String(data?.parent || '').trim();
                strmCleanupRootBrowserEntries = Array.isArray(data?.entries) ? data.entries : [];
                if (data?.default_root) strmCleanupDefaultRoot = String(data.default_root || '').trim();
                if (strmCleanupRootBrowserPath) {
                    setStrmCleanupRootInputValue(strmCleanupRootBrowserPath);
                }
            } catch (error) {
                strmCleanupRootBrowserError = `目录读取失败：${error?.message || '请检查路径是否存在且可访问'}`;
                strmCleanupRootBrowserPath = '';
                strmCleanupRootBrowserParent = '';
                strmCleanupRootBrowserEntries = [];
            } finally {
                strmCleanupRootBrowserBusy = false;
                renderStrmCleanupRootBrowser();
                updateStrmCleanupRootHint();
                updateOrphanMetadataSelection();
            }
        }

        function openStrmCleanupRootChild(path) {
            const normalized = normalizeStrmCleanupRoot(path);
            if (!normalized) return;
            void loadStrmCleanupRootBrowser(normalized);
        }

        function goStrmCleanupRootParent() {
            if (!strmCleanupRootBrowserParent) return;
            void loadStrmCleanupRootBrowser(strmCleanupRootBrowserParent);
        }

        function refreshStrmCleanupRootBrowser() {
            void loadStrmCleanupRootBrowser(strmCleanupRootBrowserPath || getStrmCleanupRootInputValue());
        }

        async function confirmStrmCleanupRootSelection() {
            const confirmedRoot = normalizeStrmCleanupRoot(strmCleanupRootBrowserPath || getStrmCleanupRequestedRoot() || strmCleanupDefaultRoot);
            if (!confirmedRoot) {
                showToast('请先在 STRM 根目录内选择一个待处理目录', {
                    tone: 'warn',
                    duration: 2600,
                    placement: 'top-center'
                });
                return;
            }
            setStrmCleanupRootInputValue(confirmedRoot);
            strmCleanupConfirmedRoot = confirmedRoot;
            resetStrmCleanupResultsForPendingScan(confirmedRoot);
            setStrmCleanupScopePanelExpanded(false);
            renderStrmCleanupRootBrowser();
            updateStrmCleanupRootHint();
            updateOrphanMetadataSelection();
            showToast('目录已确认，开始扫描当前目录', {
                tone: 'success',
                duration: 1800,
                placement: 'top-center'
            });
            await scanOrphanMetadataDirs();
        }

        async function resetStrmCleanupRoot() {
            const defaultRoot = await ensureStrmCleanupDefaultRoot({ syncSelection: true, silent: false });
            if (!defaultRoot) return;
            setStrmCleanupRootInputValue(defaultRoot);
            if (isStrmCleanupBrowseTabActive() || !strmCleanupRootBrowserPath) {
                await loadStrmCleanupRootBrowser(defaultRoot);
            }
            updateStrmCleanupRootHint();
            updateOrphanMetadataSelection();
        }

        function getNormalizedOrphanItems() {
            const metadataItems = Array.isArray(strmOrphanPreviewState.candidates) ? strmOrphanPreviewState.candidates : [];
            const emptyItems = Array.isArray(strmOrphanPreviewState.empty_dirs) ? strmOrphanPreviewState.empty_dirs : [];
            const manualItems = Array.isArray(strmOrphanPreviewState.manual_check) ? strmOrphanPreviewState.manual_check : [];
            return [
                ...metadataItems.map(item => ({ ...item, cleanup_kind: 'metadata' })),
                ...emptyItems.map(item => ({ ...item, cleanup_kind: 'empty' })),
                ...manualItems.map(item => ({ ...item, cleanup_kind: 'manual' })),
            ];
        }

        function getVisibleOrphanItems() {
            const items = getNormalizedOrphanItems();
            if (strmOrphanFilter === 'all') return items;
            return items.filter(item => String(item.cleanup_kind || '') === strmOrphanFilter);
        }

        function getSelectableOrphanPaths(items = getNormalizedOrphanItems()) {
            return items
                .filter(item => getOrphanKindMeta(item.cleanup_kind).selectable)
                .map(item => String(item?.path || '').trim())
                .filter(Boolean);
        }

        function getSelectedOrphanMetadataPaths() {
            const selectable = new Set(getSelectableOrphanPaths());
            return Array.from(strmOrphanSelectedPaths)
                .map(path => String(path || '').trim())
                .filter(path => path && selectable.has(path));
        }

        function updateOrphanMetadataSelection() {
            const selectedCount = getSelectedOrphanMetadataPaths().length;
            const rootChanged = isStrmCleanupRootChangedSinceScan();
            const btn = document.getElementById('strm-orphan-delete-btn');
            const visibleSelectablePaths = getSelectableOrphanPaths(getVisibleOrphanItems());
            const checkedVisibleCount = visibleSelectablePaths.filter(path => strmOrphanSelectedPaths.has(path)).length;
            if (btn) {
                btn.disabled = selectedCount <= 0 || strmOrphanScanBusy || rootChanged;
                btn.classList.toggle('btn-disabled', btn.disabled);
                btn.innerText = rootChanged ? '请先重新扫描' : (selectedCount > 0 ? `删除选中 ${selectedCount} 项` : '删除选中');
            }
            const checkAll = document.getElementById('strm-orphan-check-all');
            if (checkAll) {
                checkAll.disabled = !visibleSelectablePaths.length || strmOrphanScanBusy || rootChanged;
                checkAll.checked = visibleSelectablePaths.length > 0 && checkedVisibleCount === visibleSelectablePaths.length;
                checkAll.indeterminate = checkedVisibleCount > 0 && checkedVisibleCount < visibleSelectablePaths.length;
            }
            document.querySelectorAll('.strm-orphan-checkbox').forEach(input => {
                const path = String(input.value || '').trim();
                input.checked = !!path && strmOrphanSelectedPaths.has(path);
                input.disabled = strmOrphanScanBusy || rootChanged;
            });
            updateStrmCleanupScanButton();
            updateStrmCleanupRootHint();
        }

        function closeStrmCleanupTool() {
            setStrmCleanupScopePanelExpanded(true);
            hideLockedModal('strm-cleanup-modal');
        }

        function openStrmCleanupTool() {
            setStrmCleanupScopePanelExpanded(true);
            updateStrmCleanupModeView();
            updateStrmCleanupRootHint();
            renderOrphanMetadataPreview(strmOrphanPreviewState, { preserveSelection: true });
            showLockedModal('strm-cleanup-modal');
            void ensureStrmCleanupDefaultRoot({ syncSelection: true, silent: true }).then((defaultRoot) => {
                if (!defaultRoot) return;
                const targetPath = getStrmCleanupRequestedRoot() || defaultRoot;
                void loadStrmCleanupRootBrowser(targetPath);
                if (!strmOrphanHasScanned && !getNormalizedOrphanItems().length) {
                    resetStrmCleanupResultsForPendingScan(targetPath);
                }
                updateStrmCleanupRootHint();
                updateOrphanMetadataSelection();
            });
        }

        function setStrmCleanupFilter(filter) {
            const normalized = ['all', 'metadata', 'empty', 'manual'].includes(filter) ? filter : 'all';
            strmOrphanFilter = normalized;
            renderOrphanMetadataPreview(strmOrphanPreviewState, { preserveSelection: true });
        }

        function toggleOrphanMetadataPath(path, checked) {
            const normalized = String(path || '').trim();
            if (!normalized) return;
            const selectable = new Set(getSelectableOrphanPaths());
            if (!selectable.has(normalized)) return;
            if (checked) {
                strmOrphanSelectedPaths.add(normalized);
            } else {
                strmOrphanSelectedPaths.delete(normalized);
            }
            renderOrphanMetadataPreview(strmOrphanPreviewState, { preserveSelection: true });
        }

        function selectVisibleOrphanMetadata() {
            const paths = getSelectableOrphanPaths(getVisibleOrphanItems());
            if (!paths.length) return;
            paths.forEach(path => strmOrphanSelectedPaths.add(path));
            renderOrphanMetadataPreview(strmOrphanPreviewState, { preserveSelection: true });
        }

        function clearSelectedOrphanMetadata() {
            if (!strmOrphanSelectedPaths.size) return;
            strmOrphanSelectedPaths = new Set();
            renderOrphanMetadataPreview(strmOrphanPreviewState, { preserveSelection: true });
        }

        function handleOrphanRowClick(event, path) {
            const target = event?.target;
            if (target?.closest('input, button, a, label')) return;
            const normalized = String(path || '').trim();
            if (!normalized || strmOrphanScanBusy || isStrmCleanupRootChangedSinceScan()) return;
            const selectable = new Set(getSelectableOrphanPaths());
            if (!selectable.has(normalized)) return;
            if (strmOrphanSelectedPaths.has(normalized)) {
                strmOrphanSelectedPaths.delete(normalized);
            } else {
                strmOrphanSelectedPaths.add(normalized);
            }
            renderOrphanMetadataPreview(strmOrphanPreviewState, { preserveSelection: true });
        }

        function setVisibleOrphanMetadataChecked(checked) {
            const paths = getSelectableOrphanPaths(getVisibleOrphanItems());
            paths.forEach(path => {
                if (checked) {
                    strmOrphanSelectedPaths.add(path);
                } else {
                    strmOrphanSelectedPaths.delete(path);
                }
            });
            renderOrphanMetadataPreview(strmOrphanPreviewState, { preserveSelection: true });
        }

        function renderStrmCleanupFilterCounts() {
            const items = getNormalizedOrphanItems();
            const counts = {
                all: items.length,
                metadata: items.filter(item => item.cleanup_kind === 'metadata').length,
                empty: items.filter(item => item.cleanup_kind === 'empty').length,
                manual: items.filter(item => item.cleanup_kind === 'manual').length,
            };
            Object.entries(counts).forEach(([key, count]) => {
                const el = document.querySelector(`[data-strm-filter-count="${key}"]`);
                if (el) el.innerText = String(count);
            });
            document.querySelectorAll('[data-strm-orphan-filter]').forEach(btn => {
                const active = String(btn.dataset.strmOrphanFilter || 'all') === strmOrphanFilter;
                btn.classList.toggle('is-active', active);
                btn.setAttribute('aria-pressed', active ? 'true' : 'false');
            });
        }

        function buildOrphanItemDetail(item) {
            const kind = String(item.cleanup_kind || 'metadata');
            if (kind === 'empty') return '目录为空';
            const fileCount = Number(item?.file_count || 0) || 0;
            const detail = formatOrphanExtensions(item);
            const reason = String(item?.reason || '').trim();
            const base = `文件 ${fileCount} 个 · ${detail}`;
            return reason ? `${base} · ${reason}` : base;
        }

        function renderOrphanEmptyState(listEl, message) {
            if (!listEl) return;
            listEl.innerHTML = `<div class="resource-browser-empty">${escapeHtml(message)}</div>`;
        }

        function renderOrphanMetadataPreview(data, { preserveSelection = false } = {}) {
            if (data?.default_root) {
                strmCleanupDefaultRoot = String(data.default_root || '').trim();
            }
            strmOrphanPreviewState = {
                root: String(data?.root || strmOrphanPreviewState.root || ''),
                candidates: Array.isArray(data?.candidates) ? data.candidates : [],
                empty_dirs: Array.isArray(data?.empty_dirs) ? data.empty_dirs : [],
                manual_check: Array.isArray(data?.manual_check) ? data.manual_check : []
            };
            if (!preserveSelection) {
                strmOrphanSelectedPaths = new Set();
            } else {
                const selectable = new Set(getSelectableOrphanPaths());
                strmOrphanSelectedPaths = new Set(Array.from(strmOrphanSelectedPaths).filter(path => selectable.has(path)));
            }
            const items = getNormalizedOrphanItems();
            const visibleItems = getVisibleOrphanItems();
            const allSelectablePaths = getSelectableOrphanPaths(items);
            const visibleSelectablePaths = getSelectableOrphanPaths(visibleItems);
            const rootChanged = isStrmCleanupRootChangedSinceScan();
            const summaryEl = document.getElementById('strm-orphan-summary');
            const listEl = document.getElementById('strm-orphan-list');
            if (summaryEl) {
                if (strmOrphanScanBusy) {
                    summaryEl.innerText = `正在扫描 ${getStrmCleanupRequestedRootLabel()}，请稍候...`;
                } else if (!hasConfirmedStrmCleanupRoot()) {
                    summaryEl.innerText = '请先确认待处理目录。';
                } else if (!strmOrphanHasScanned && !items.length) {
                    summaryEl.innerText = `待处理目录已确认：${getStrmCleanupConfirmedRoot()}。`;
                } else {
                    const selectedCount = getSelectedOrphanMetadataPaths().length;
                    const activeRoot = strmOrphanPreviewState.root || getStrmCleanupRequestedRootLabel();
                    if (rootChanged) {
                        summaryEl.innerText = `目录已变更，请先重新扫描 ${getStrmCleanupRequestedRootLabel()}。`;
                    } else if (!allSelectablePaths.length) {
                        summaryEl.innerText = `已扫描 ${activeRoot}，当前没有可直接删除的目录。`;
                    } else {
                        const scopeLabel = strmOrphanFilter === 'all' ? '全部结果' : '当前筛选';
                        summaryEl.innerText = `已扫描 ${activeRoot}，共 ${items.length} 项；${scopeLabel}可清理 ${visibleSelectablePaths.length} 项，已选 ${selectedCount} 项。`;
                    }
                }
            }
            renderStrmCleanupFilterCounts();
            updateStrmCleanupModeView();
            if (!listEl) {
                updateOrphanMetadataSelection();
                return;
            }
            if (!hasConfirmedStrmCleanupRoot()) {
                renderOrphanEmptyState(listEl, '先在“选择目录”里确认待处理目录。确认后会自动扫描并在这里显示结果。');
                updateOrphanMetadataSelection();
                return;
            }
            if (!strmOrphanHasScanned && !items.length) {
                renderOrphanEmptyState(listEl, '正在等待扫描结果...');
                updateOrphanMetadataSelection();
                return;
            }
            if (!visibleItems.length) {
                renderOrphanEmptyState(listEl, strmOrphanFilter === 'all' ? '没有发现 STRM 残留目录。' : '当前分类没有扫描结果，可以切换到其他分类查看。');
                updateOrphanMetadataSelection();
                return;
            }
            const manager = window.MediaHubFileManager;
            const rows = visibleItems.map((item) => {
                const path = String(item?.path || '');
                const modified = String(item?.last_modified || '') || '--';
                const kind = String(item.cleanup_kind || 'metadata');
                const meta = getOrphanKindMeta(kind);
                const checked = meta.selectable && strmOrphanSelectedPaths.has(path);
                const checkboxHtml = meta.selectable
                    ? `<input type="checkbox" class="ui-checkbox ui-checkbox-sm strm-orphan-checkbox" value="${escapeHtml(path)}" onchange="toggleOrphanMetadataPath(this.value, this.checked)" ${checked ? 'checked' : ''}>`
                    : '<span class="strm-cleanup-readonly-marker" title="目录内含未知或非元数据文件，需要手动检查">!</span>';
                const detailText = buildOrphanItemDetail(item);
                return {
                    ...item,
                    id: path,
                    name: path || '--',
                    path,
                    modified_at: modified,
                    is_dir: true,
                    checked,
                    selectable: meta.selectable,
                    tone: meta.tone,
                    kindLabel: meta.label,
                    checkboxHtml,
                    detailText,
                };
            });
            const columns = [
                {
                    key: 'name',
                    label: '目录路径',
                    cellClass: 'file-manager-cell--name',
                    render: (entry) => manager.renderNameCell(entry, {
                        checkboxHtml: entry.checkboxHtml,
                        nameHtml: `<span class="resource-browser-entry-name file-manager-entry-name" title="${escapeHtml(entry.path || '')}">${escapeHtml(entry.path || '--')}</span>`,
                        iconClass: 'strm-cleanup-folder-icon',
                        mainClass: 'resource-browser-entry-main',
                    }),
                },
                {
                    key: 'kind',
                    label: '类型',
                    cellClass: 'strm-cleanup-col-kind file-manager-cell--kind',
                    render: (entry) => `<span class="strm-cleanup-kind strm-cleanup-kind-${escapeHtml(entry.tone)}">${escapeHtml(entry.kindLabel)}</span>`,
                },
                {
                    key: 'detail',
                    label: '内容',
                    cellClass: 'strm-cleanup-col-detail',
                    render: (entry) => escapeHtml(entry.detailText),
                },
                {
                    key: 'modified_at',
                    label: '修改时间',
                    cellClass: 'strm-cleanup-col-time file-manager-cell--modified',
                    render: (entry) => escapeHtml(entry.modified_at || '--'),
                },
            ];
            listEl.innerHTML = manager.renderRows(rows, columns, {
                emptyText: strmOrphanFilter === 'all' ? '没有发现 STRM 残留目录。' : '当前分类没有扫描结果，可以切换到其他分类查看。',
                rowClass: (entry) => [
                    'resource-browser-row',
                    'strm-cleanup-row',
                    `strm-cleanup-row-${entry.tone}`,
                    entry.checked ? 'is-selected' : '',
                    entry.selectable ? '' : 'is-readonly',
                ].filter(Boolean).join(' '),
                rowAttrs: (entry) => `data-strm-orphan-path="${escapeHtml(entry.path)}" onclick="handleOrphanRowClick(event, this.dataset.strmOrphanPath)" style="--file-manager-columns:minmax(0, 1.5fr) 138px minmax(220px, 0.9fr) 152px;--file-manager-min-width:760px"`,
            });
            updateOrphanMetadataSelection();
        }

        async function scanOrphanMetadataDirs() {
            if (strmOrphanScanBusy) return;
            const requestedRoot = getStrmCleanupConfirmedRoot();
            if (!requestedRoot) {
                showToast('请先确认待处理目录', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            strmOrphanScanBusy = true;
            setStrmCleanupScopePanelExpanded(false);
            const summaryEl = document.getElementById('strm-orphan-summary');
            if (summaryEl) summaryEl.innerText = `正在扫描 ${requestedRoot || strmCleanupDefaultRoot || '默认 STRM 目录'} 的残留目录...`;
            updateOrphanMetadataSelection();
            try {
                const data = await window.MediaHubApi.getJson(buildStrmCleanupPreviewUrl(requestedRoot));
                strmOrphanHasScanned = true;
                const scannedRoot = String(data?.root || requestedRoot || '').trim();
                if (data?.default_root) strmCleanupDefaultRoot = String(data.default_root || '').trim();
                strmCleanupActiveRoot = scannedRoot;
                if (scannedRoot) setStrmCleanupRootInputValue(scannedRoot);
                renderOrphanMetadataPreview(data);
            } catch (error) {
                showToast(`扫描失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            } finally {
                strmOrphanScanBusy = false;
                renderOrphanMetadataPreview(strmOrphanPreviewState, { preserveSelection: true });
                updateOrphanMetadataSelection();
            }
        }

        async function deleteSelectedOrphanMetadataDirs() {
            if (isStrmCleanupRootChangedSinceScan()) {
                showToast('扫描根目录已变化，请先重新扫描后再删除', { tone: 'warn', duration: 2800, placement: 'top-center' });
                updateOrphanMetadataSelection();
                return;
            }
            const paths = getSelectedOrphanMetadataPaths();
            if (!paths.length) {
                showToast('请先勾选要清理的目录', { tone: 'warn', duration: 2400, placement: 'top-center' });
                return;
            }
            const confirmed = await showAppConfirm(
                `将从 ${strmCleanupActiveRoot || strmOrphanPreviewState.root || '当前扫描目录'} 删除 ${paths.length} 个 STRM 残留目录。后端会再次校验：只删除没有 .strm 且为空，或只包含已知刮削元数据的目录。继续吗？`,
                { title: '确认删除残留目录', tone: 'error', confirmText: '删除选中' }
            );
            if (!confirmed) return;
            try {
                const result = await window.MediaHubApi.postJson('/strm/orphan-metadata/delete', {
                    paths,
                    root: strmCleanupActiveRoot || strmOrphanPreviewState.root || getStrmCleanupRootInputValue()
                });
                const deletedCount = Number(result?.deleted_count || 0) || 0;
                const skippedCount = Number(result?.skipped_count || 0) || 0;
                showToast(`清理完成：删除 ${deletedCount} 个，跳过 ${skippedCount} 个`, {
                    tone: skippedCount > 0 ? 'warn' : 'success',
                    duration: 3200,
                    placement: 'top-center'
                });
                await scanOrphanMetadataDirs();
            } catch (error) {
                showToast(`清理失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
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

        function getCurrentPansouConfig() {
            return {
                pansou_enabled: !!document.getElementById('pansou_enabled')?.checked,
                pansou_base_url: document.getElementById('pansou_base_url')?.value?.trim() || '',
                pansou_username: document.getElementById('pansou_username')?.value?.trim() || '',
                pansou_password: document.getElementById('pansou_password')?.value?.trim() || '',
                pansou_src: document.getElementById('pansou_src')?.value?.trim() || 'all',
                pansou_channels: document.getElementById('pansou_channels')?.value?.trim() || '',
                pansou_plugins: document.getElementById('pansou_plugins')?.value?.trim() || ''
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

        function getCurrentTgChannelSyncLimit() {
            const inputRaw = parseInt(document.getElementById('tg_channel_sync_limit')?.value || '', 10);
            const stateRaw = parseInt(
                resourceState?.search_meta?.sync_limit_per_channel
                    || resourceState?.channel_sync?.last_result?.limit_per_channel
                    || '',
                10
            );
            const candidate = Number.isFinite(inputRaw)
                ? inputRaw
                : (Number.isFinite(stateRaw) ? stateRaw : 10);
            return Math.min(30, Math.max(1, candidate));
        }

        function formatDurationText(durationMs, label = '总耗时') {
            const value = Number(durationMs || 0);
            if (!Number.isFinite(value) || value <= 0) return '';
            if (value < 1000) return `${label} ${Math.max(1, Math.round(value))} ms`;
            return `${label} ${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} s`;
        }

        function formatLatencyText(latencyMs, label = 'TG 延迟') {
            const value = Number(latencyMs || 0);
            if (!Number.isFinite(value) || value <= 0) return `${label} --`;
            return `${label} ${Math.max(1, Math.round(value))} ms`;
        }

        async function probeResourceTgLatency() {
            try {
                const data = await window.MediaHubApi.postJson('/settings/tg_proxy/test', getCurrentTgProxyConfig());
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

        function renderPansouTestStatus() {
            const settingsModule = tabRuntimeState.tabModuleCache.settings;
            if (settingsModule?.renderPansouTestStatus) {
                settingsModule.renderPansouTestStatus({
                    pansouTestState,
                    escapeHtml,
                    formatDurationText,
                });
                return;
            }
            void loadSettingsTabModule().then((mod) => {
                mod?.renderPansouTestStatus?.({
                    pansouTestState,
                    escapeHtml,
                    formatDurationText,
                });
            });
        }

        async function testPansouConnection() {
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.testPansouConnection) {
                await settingsModule.testPansouConnection({
                    getCurrentPansouConfig,
                    getPansouTestState: () => pansouTestState,
                    setPansouTestState: (nextValue) => {
                        pansouTestState = { ...nextValue };
                    },
                    renderPansouTestStatus,
                });
                return;
            }
            showToast('PanSou 测试模块加载失败，请刷新页面后重试', { tone: 'error', duration: 3200, placement: 'top-center' });
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
            const channelSyncState = typeof normalizeResourceChannelSyncState === 'function'
                ? normalizeResourceChannelSyncState(resourceState.channel_sync)
                : (resourceState.channel_sync || {});
            const channelSyncActive = !resourceSyncBusy && (
                typeof isResourceChannelSyncActive === 'function'
                    ? isResourceChannelSyncActive(channelSyncState)
                    : (!!channelSyncState.submitted || !!channelSyncState.running)
            );
            const tone = ['loading', 'success', 'warning', 'error'].includes(resourceTgHealthState.tone)
                ? resourceTgHealthState.tone
                : 'loading';
            const tgText = formatResourceTgHealthInlineText();
            let text = String(resourceBoardHintText || '').trim();

            if (resourceSearchBusy) {
                const tgProgressText = String(resourceTgHealthState.meta || '').trim();
                if (typeof getResourceSearchRunningHintText === 'function') {
                    text = getResourceSearchRunningHintText({
                        keyword,
                        source: resourceSearchSource,
                        providerFilter: resourceProviderFilter,
                        latencyMs: resourceSearchSource === 'pansou' ? 0 : resourceTgLastLatencyMs,
                        latencyText: resourceSearchSource === 'pansou' ? '' : tgProgressText,
                        directImportMode: directImport,
                    });
                } else if (!text) {
                    if (directImport) {
                        text = `资源识别执行中 · 关键词「${keyword || '...'}」 · 已开始`;
                    } else {
                        if (typeof buildResourceSearchStatusText === 'function') {
                            text = buildResourceSearchStatusText({
                                phase: 'running',
                                source: resourceSearchSource,
                                keyword,
                                providerFilter: resourceProviderFilter,
                                latencyMs: resourceSearchSource === 'pansou' ? 0 : resourceTgLastLatencyMs,
                                latencyText: resourceSearchSource === 'pansou' ? '' : tgProgressText,
                            });
                        } else {
                            const sourceLabel = resourceSearchSource === 'pansou' ? '盘搜中' : '频道搜索中';
                            const latencyText = resourceSearchSource === 'pansou'
                                ? '已开始'
                                : (tgProgressText || 'TG 延迟检测中');
                            text = `${sourceLabel} · 关键词「${keyword || '...'}」 · ${latencyText}`;
                        }
                    }
                }
            } else if (resourceSyncBusy) {
                text = tgText || '频道同步提交中 · 正在检测 TG 代理延迟';
            } else if (channelSyncActive && !text) {
                text = tgText || (
                    channelSyncState.cancel_requested
                        ? '频道同步停止中 · 等待当前批次收尾'
                        : '频道同步后台运行中'
                );
            } else if (tgText && !text) {
                text = text ? `${text} ｜ ${tgText}` : tgText;
            }

            const hasText = !!text;
            hint.classList.toggle('hidden', !hasText);
            hint.classList.toggle('is-loading', hasText && (resourceSearchBusy || resourceSyncBusy || resourceSyncCancelBusy || channelSyncActive));
            hint.classList.remove(
                'resource-search-sub--loading',
                'resource-search-sub--success',
                'resource-search-sub--warning',
                'resource-search-sub--error'
            );
            if (hasText && (tgText || resourceSearchBusy || resourceSyncBusy || resourceSyncCancelBusy || channelSyncActive)) {
                hint.classList.add(`resource-search-sub--${tone}`);
            }
            hint.innerText = hasText ? text : '';
        }

        function renderResourceTgHealthStatus() {
            renderResourceBoardHint();
        }

        function getActionElapsedMs(startedAt) {
            if (!Number.isFinite(Number(startedAt || 0))) return 0;
            return Math.max(1, Math.round(performance.now() - Number(startedAt || 0)));
        }

        function setResourceTgHealthResult({
            tone,
            title,
            detail = '',
            durationMs = 0,
            latencyMs = 0,
            durationLabel = '总耗时',
            latencyLabel = 'TG 延迟',
            includeDuration = true,
            includeLatency = true,
            detailFirst = false,
        }) {
            const parts = [];
            if (includeLatency) parts.push(formatLatencyText(latencyMs, latencyLabel));
            if (detailFirst && detail) parts.push(detail);
            if (includeDuration) parts.push(formatDurationText(durationMs, durationLabel) || `${durationLabel} --`);
            if (!detailFirst && detail) parts.push(detail);
            setResourceTgHealthState({
                visible: true,
                tone,
                title,
                meta: parts.join(' · '),
                note: '',
            });
        }

        function showResourceTgHealthLoading(context) {
            if (context === 'sync') {
                setResourceTgHealthState({
                    visible: true,
                    tone: 'loading',
                    title: '频道同步提交中',
                    meta: '正在检测 TG 代理延迟',
                    note: '',
                });
                return;
            }
            setResourceTgHealthState({
                visible: true,
                tone: 'loading',
                title: 'TG 搜索中',
                meta: 'TG 延迟检测中',
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
            const cancelled = !!data?.cancelled;

            if (data?.queued) {
                setResourceTgHealthResult({
                    tone: data.accepted === false ? 'warning' : 'loading',
                    title: data.accepted === false ? '频道同步已在执行' : '频道同步已提交',
                    detail: data.accepted === false ? '本次未重复提交' : '后台执行中',
                    durationMs,
                    latencyMs,
                    durationLabel: '提交耗时',
                    latencyLabel: 'TG 代理延迟',
                    includeLatency: data.accepted !== false,
                });
                return;
            }

            if (cancelled) {
                const detail = (synced > 0 || inserted > 0 || skipped > 0 || pruned > 0 || errors.length > 0)
                    ? `频道 ${synced} · 新增 ${inserted} · 缓存 ${skipped} · 清理 ${pruned}`
                    : '已按请求停止';
                setResourceTgHealthResult({
                    tone: 'warning',
                    title: '频道同步已停止',
                    detail,
                    durationMs,
                    includeLatency: false,
                    detailFirst: true,
                });
                return;
            }

            if (!errors.length) {
                setResourceTgHealthResult({
                    tone: 'success',
                    title: '频道同步完成',
                    detail: `频道 ${synced} · 新增 ${inserted} · 缓存 ${skipped} · 清理 ${pruned}`,
                    durationMs,
                    includeLatency: false,
                    detailFirst: true,
                });
                return;
            }

            if (synced > 0 || skipped > 0) {
                setResourceTgHealthResult({
                    tone: 'warning',
                    title: '频道同步完成但有异常',
                    detail: `成功 ${synced} · 异常 ${errors.length}`,
                    durationMs,
                    includeLatency: false,
                    detailFirst: true,
                });
                return;
            }

            setResourceTgHealthResult({
                tone: 'error',
                title: '频道同步失败',
                detail: `${errors.length} 个频道失败`,
                durationMs,
                includeLatency: false,
                detailFirst: true,
            });
        }

        function applyResourceTgHealthFailure(context, durationMs = 0, latencyMs = 0) {
            if (context === 'sync') {
                setResourceTgHealthResult({
                    tone: 'error',
                    title: '频道同步提交失败',
                    detail: 'TG 代理连接异常',
                    durationMs,
                    latencyMs,
                    durationLabel: '提交耗时',
                    latencyLabel: 'TG 代理延迟',
                });
                return;
            }
            setResourceTgHealthResult({
                tone: 'error',
                title: 'TG 异常',
                detail: '搜索未完成',
                durationMs,
                latencyMs,
            });
        }

        async function saveSettings() {
            const settingsModule = await loadSettingsTabModule();
            if (settingsModule?.saveSettings) {
                await settingsModule.saveSettings({
                    sensitiveSettingFields: getSensitiveSettingFields(),
                    getSensitiveConfigMeta: () => sensitiveConfigMeta,
                    applySensitiveConfigMeta,
                    applyCookieHealthState,
                    refreshResourceState,
                    refreshSign115Status,
                    getMonitorTasks: () => monitorState.tasks || [],
                    showToast,
                });
                return;
            }
            showToast('设置模块加载失败，请刷新页面后重试', { tone: 'error', duration: 3200, placement: 'top-center' });
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
            try {
                await window.MediaHubApi.postJson('/logs/clear');
                lastLogSignature = '';
                await refreshMainLogs();
            } catch (e) {}
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
            try {
                await window.MediaHubApi.postJson('/monitor/logs/clear');
                lastMonitorLogSignature = '';
                await refreshMonitorState();
            } catch (e) {}
        }

        function currentMonitorFormData() {
            const rawScanPath = document.getElementById('monitor_scan_path').value.trim();
            return {
                name: document.getElementById('monitor_name').value.trim(),
                webhook_enabled: document.getElementById('monitor_webhook_enabled').checked,
                scan_path: rawScanPath ? normalizeRemotePathInput(rawScanPath) : '',
                target_path: document.getElementById('monitor_target_path').value.trim(),
                skip_by_dir_mtime: document.getElementById('monitor_skip_by_dir_mtime').checked,
                strm_write_mode: document.getElementById('monitor_strm_write_mode')?.value || 'incremental',
                sync_clean: document.getElementById('monitor_sync_clean').checked,
                incremental: !document.getElementById('monitor_sync_clean').checked,
                retries: parseInt(document.getElementById('monitor_retries').value || '3', 10) || 3,
                list_delay_ms: document.getElementById('monitor_list_delay_ms').value === ''
                    ? 250
                    : (parseInt(document.getElementById('monitor_list_delay_ms').value, 10) || 0),
                min_file_size_mb: parseFloat(document.getElementById('monitor_min_file_size_mb').value || '0') || 0,
                delay_seconds: parseInt(document.getElementById('monitor_delay_seconds').value || '0', 10) || 0,
                cron_minutes: parseInt(document.getElementById('monitor_cron_minutes').value || '0', 10) || 0
            };
        }

        function getMonitorMountPrefix() {
            return normalizeRemotePathInput(getMountPrefixByProvider('115') || '/115');
        }

        function updateMonitorScanPathHint(scanPath = '') {
            const hintEl = document.getElementById('monitor_scan_path_hint');
            if (!hintEl) return;
            const normalized = normalizeRemotePathInput(scanPath || '');
            hintEl.textContent = normalized && normalized !== '/'
                ? `当前保存路径：${normalized}。保存的是 115 路径字符串；即使 Cookie 暂时失效，路径也会保留，恢复后可继续使用。`
                : '保存的是 115 路径字符串；即使 Cookie 暂时失效，路径也会保留，恢复后可继续使用。';
        }

        function getMonitorScanPathRelative(scanPath = '') {
            const normalized = normalizeRemotePathInput(scanPath || '');
            const mountPrefix = getMonitorMountPrefix();
            if (!normalized || normalized === '/' || normalized === mountPrefix) return '';
            if (normalized.startsWith(`${mountPrefix}/`)) {
                return normalizeRelativePathInput(normalized.slice(mountPrefix.length));
            }
            return '';
        }

        function buildMonitorScanPathFromTrail(trail = []) {
            const relativePath = buildResourceFolderDisplayPathFromTrail(trail);
            return normalizeRemotePathInput(joinRelativePathInput(getMonitorMountPrefix(), relativePath));
        }

        function renderMonitorFolderBreadcrumbs() {
            const container = document.getElementById('monitor-folder-breadcrumbs');
            if (!container) return;
            container.innerHTML = monitorFolderTrail.map((item, index) => {
                const isLast = index === monitorFolderTrail.length - 1;
                return `
                    ${index > 0 ? '<span class="resource-folder-sep">›</span>' : ''}
                    <button
                        type="button"
                        data-monitor-folder-action="trail"
                        data-monitor-folder-index="${index}"
                        class="resource-folder-crumb ${isLast ? 'resource-folder-crumb-active' : ''}"
                        ${isLast ? 'disabled' : ''}
                    >${escapeHtml(item?.name || '根目录')}</button>
                `;
            }).join('');
        }

        function renderMonitorFolderList() {
            const container = document.getElementById('monitor-folder-list');
            const summaryEl = document.getElementById('monitor-folder-summary');
            const refreshBtn = document.getElementById('monitor-folder-refresh-btn');
            if (!container) return;
            const manager = window.MediaHubFileManager;
            const renderEmpty = (message) => manager?.renderEmpty
                ? manager.renderEmpty(message)
                : `<div class="resource-browser-empty">${escapeHtml(message)}</div>`;
            if (refreshBtn) {
                refreshBtn.disabled = monitorFolderLoading;
                refreshBtn.classList.toggle('btn-disabled', monitorFolderLoading);
                refreshBtn.textContent = monitorFolderLoading ? '刷新中...' : '刷新当前目录';
            }
            if (summaryEl) {
                const folderCount = Number(monitorFolderSummary.folder_count || 0);
                const fileCount = Number(monitorFolderSummary.file_count || 0);
                summaryEl.textContent = `当前目录下共有 ${folderCount} 个文件夹 / ${fileCount} 个文件，这里只展示文件夹，方便精确选择监控范围。`;
            }
            if (monitorFolderLoading && !monitorFolderEntries.length) {
                container.innerHTML = renderEmpty('正在读取 115 目录...');
                return;
            }
            if (!monitorFolderEntries.length) {
                container.innerHTML = renderEmpty('当前目录下没有子文件夹，可以直接选择这里作为监控路径。');
                return;
            }
            if (!manager?.renderTable) {
                container.innerHTML = monitorFolderEntries.map((entry) => (
                    buildResourceEntryRow(entry, { showOpenButton: true, openActionPrefix: 'monitor-folder' })
                )).join('');
                return;
            }
            const entries = monitorFolderEntries.filter(entry => !!entry?.is_dir).map(entry => ({
                ...entry,
                id: String(entry?.id || entry?.cid || entry?.path || entry?.name || '').trim(),
                name: String(entry?.name || entry?.path || '--').trim() || '--',
                modified_at: entry?.modified_at || entry?.last_modified || entry?.updated_at || entry?.time || '',
                is_dir: true,
            }));
            const columns = [
                {
                    key: 'name',
                    label: '名称',
                    sortable: true,
                    cellClass: 'file-manager-cell--name',
                    render: (entry) => manager.renderNameCell(entry, {
                        nameHtml: `
                            <button
                                type="button"
                                data-monitor-folder-action="open"
                                data-monitor-folder-id="${escapeHtml(entry.id)}"
                                data-monitor-folder-name="${escapeHtml(entry.name)}"
                                class="resource-browser-link resource-browser-entry-name file-manager-entry-link"
                                title="${escapeHtml(entry.path || entry.name || '')}"
                            >${escapeHtml(entry.name || '--')}</button>
                        `,
                        mainClass: 'resource-browser-entry-main',
                    }),
                },
                {
                    key: 'modified_at',
                    label: '修改时间',
                    sortable: true,
                    cellClass: 'file-manager-cell--modified',
                    render: (entry) => escapeHtml(manager.formatModified(entry.modified_at)),
                },
            ];
            container.innerHTML = manager.renderTable({
                entries,
                columns,
                sort: { key: 'name', direction: 'asc' },
                sortable: true,
                entryFilter: 'folders',
                foldersFirst: true,
                tableClass: 'file-manager-table-compact',
                emptyText: '当前目录下没有子文件夹，可以直接选择这里作为监控路径。',
                gridTemplate: 'minmax(220px, 1fr) 142px',
                minWidth: '560px',
            });
        }

        async function loadMonitorFolders(cid = '0', { forceRefresh = false } = {}) {
            const requestToken = ++monitorFolderRequestToken;
            const targetCid = String(cid || '0').trim() || '0';
            monitorFolderLoading = true;
            renderMonitorFolderBreadcrumbs();
            renderMonitorFolderList();
            try {
                const result = await fetchResourceFolderData(targetCid, {
                    provider: '115',
                    foldersOnly: true,
                    forceRefresh,
                });
                if (requestToken !== monitorFolderRequestToken) return false;
                monitorFolderEntries = Array.isArray(result.entries) ? result.entries.filter(entry => !!entry?.is_dir) : [];
                monitorFolderSummary = result.summary || { folder_count: 0, file_count: 0 };
                return true;
            } catch (e) {
                if (requestToken !== monitorFolderRequestToken) return false;
                monitorFolderEntries = [];
                monitorFolderSummary = { folder_count: 0, file_count: 0 };
                showToast(`目录读取失败：${e?.message || '请稍后重试'}`, {
                    tone: 'error',
                    duration: 3200,
                    placement: 'top-center'
                });
                return false;
            } finally {
                if (requestToken !== monitorFolderRequestToken) return false;
                monitorFolderLoading = false;
                renderMonitorFolderBreadcrumbs();
                renderMonitorFolderList();
            }
        }

        async function resolveMonitorFolderTrailByPath(scanPath = '') {
            const relativePath = getMonitorScanPathRelative(scanPath);
            const resolvedTrail = [{ id: '0', name: '根目录' }];
            if (!relativePath) return resolvedTrail;

            let parentCid = '0';
            const parts = relativePath.split('/').filter(Boolean);
            for (const part of parts) {
                const result = await fetchResourceFolderData(parentCid, {
                    provider: '115',
                    foldersOnly: true,
                });
                const entries = Array.isArray(result.entries) ? result.entries : [];
                const matched = entries.find((entry) => !!entry?.is_dir && String(entry?.name || '').trim() === part);
                if (!matched) break;
                const matchedId = String(matched.id || matched.cid || '').trim();
                if (!matchedId) break;
                resolvedTrail.push({ id: matchedId, name: String(matched.name || part).trim() || part });
                parentCid = matchedId;
            }
            return resolvedTrail;
        }

        async function openMonitorFolderModal() {
            const hasConfiguredCookie = !!(resourceState.cookie_configured || sensitiveConfigMeta.cookie_115);
            if (!hasConfiguredCookie) {
                showToast('请先在参数配置中填写 115 Cookie', {
                    tone: 'warn',
                    duration: 2800,
                    placement: 'top-center'
                });
                return;
            }
            showLockedModal('monitor-folder-modal');
            renderMonitorFolderBreadcrumbs();
            renderMonitorFolderList();
            try {
                monitorFolderTrail = await resolveMonitorFolderTrailByPath(
                    document.getElementById('monitor_scan_path')?.value || ''
                );
            } catch (e) {
                monitorFolderTrail = [{ id: '0', name: '根目录' }];
            }
            await loadMonitorFolders(monitorFolderTrail[monitorFolderTrail.length - 1]?.id || '0');
        }

        function closeMonitorFolderModal() {
            hideLockedModal('monitor-folder-modal');
        }

        async function goMonitorFolderBack() {
            if (monitorFolderTrail.length <= 1) return;
            monitorFolderTrail = monitorFolderTrail.slice(0, -1);
            await loadMonitorFolders(monitorFolderTrail[monitorFolderTrail.length - 1]?.id || '0');
        }

        async function openMonitorFolderTrail(index) {
            const targetIndex = Math.max(0, Math.min(Number(index || 0), monitorFolderTrail.length - 1));
            monitorFolderTrail = monitorFolderTrail.slice(0, targetIndex + 1);
            await loadMonitorFolders(monitorFolderTrail[monitorFolderTrail.length - 1]?.id || '0');
        }

        async function openMonitorFolderChild(folderId, folderName) {
            monitorFolderTrail = monitorFolderTrail.concat([{ id: String(folderId || '0'), name: String(folderName || '--') }]);
            await loadMonitorFolders(folderId);
        }

        async function refreshCurrentMonitorFolder() {
            if (monitorFolderLoading) return;
            const currentCid = monitorFolderTrail[monitorFolderTrail.length - 1]?.id || '0';
            const refreshed = await loadMonitorFolders(currentCid, { forceRefresh: true });
            if (refreshed) {
                showToast('已刷新当前目录', { tone: 'success', duration: 2200, placement: 'top-center' });
            }
        }

        function selectCurrentMonitorFolder() {
            const scanPath = buildMonitorScanPathFromTrail(monitorFolderTrail);
            const inputEl = document.getElementById('monitor_scan_path');
            if (inputEl) inputEl.value = scanPath;
            updateMonitorScanPathHint(scanPath);
            closeMonitorFolderModal();
        }

        function resetMonitorForm() {
            editingMonitorName = null;
            document.getElementById('monitor-modal-title').innerText = '新增监控任务';
            document.getElementById('monitor_name').value = '';
            document.getElementById('monitor_webhook_enabled').checked = false;
            document.getElementById('monitor_scan_path').value = '';
            updateMonitorScanPathHint('');
            monitorFolderTrail = [{ id: '0', name: '根目录' }];
            monitorFolderEntries = [];
            monitorFolderSummary = { folder_count: 0, file_count: 0 };
            monitorFolderLoading = false;
            document.getElementById('monitor_target_path').value = '';
            document.getElementById('monitor_skip_by_dir_mtime').checked = false;
            document.getElementById('monitor_strm_write_mode').value = 'incremental';
            document.getElementById('monitor_sync_clean').checked = true;
            document.getElementById('monitor_retries').value = 3;
            document.getElementById('monitor_list_delay_ms').value = 250;
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
                `webhook 地址：IP:容器端口/webhook/${escapeHtml(name)}（任务名用于绑定这个监控任务）`,
                '磁力导入必填：magnet 或 link_url + savepath',
                'savepath 是 115 保存目录；必须落在本任务扫描路径内，导入后才会自动刷新 strm',
                'delayTime 可选：本次导入成功后延迟几秒刷新；不传则使用任务默认延迟',
                'title / sharetitle 可选：仅用于日志或局部刷新提示',
                '签名校验（可选）：X-Webhook-Ts / X-Webhook-Nonce / X-Webhook-Sign 或 X-Webhook-Token',
                '说明：签名密钥在「参数配置 -> 后台安全管理」里设置；为空时不校验'
            ].join('<br>');
        }

        async function persistMonitorTasks(tasks) {
            const data = await window.MediaHubApi.postJson('/monitor/save', { tasks });
            applyMonitorState({ ...monitorState, tasks: data.tasks || [] }, { forceRender: true });
        }

        async function saveMonitorTask() {
            const task = currentMonitorFormData();
            if (!task.name) return showToast('任务名不能为空', { tone: 'warn', duration: 2600, placement: 'top-center' });
            if (!task.scan_path) return showToast('扫描路径不能为空', { tone: 'warn', duration: 2600, placement: 'top-center' });
            if (!task.target_path) return showToast('目标路径不能为空', { tone: 'warn', duration: 2600, placement: 'top-center' });
            const mountPrefix = getMonitorMountPrefix();
            if (task.scan_path !== mountPrefix && !task.scan_path.startsWith(`${mountPrefix}/`)) {
                return showToast(`扫描路径必须位于 ${mountPrefix} 下`, { tone: 'warn', duration: 3200, placement: 'top-center' });
            }
            if (task.retries < 1 || task.retries > 5) return showToast('读取失败尝试次数只能在 1 到 5 之间', { tone: 'warn', duration: 2600, placement: 'top-center' });
            if (task.cron_minutes < 0) return showToast('定时执行分钟不能小于 0', { tone: 'warn', duration: 2600, placement: 'top-center' });

            const tasks = [...(monitorState.tasks || [])];
            const dup = tasks.find(item => item.name === task.name && item.name !== editingMonitorName);
            if (dup) return showToast('任务名重复，请修改后再保存', { tone: 'warn', duration: 2800, placement: 'top-center' });

            const idx = tasks.findIndex(item => item.name === editingMonitorName);
            if (idx >= 0) tasks[idx] = task;
            else tasks.push(task);

            try {
                await persistMonitorTasks(tasks);
                resetMonitorForm();
                closeMonitorModal();
                showToast('监控任务已保存', { tone: 'success', duration: 2400, placement: 'top-center' });
            } catch (e) {
                showToast(`保存失败：${e.message || '未知错误'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
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
            updateMonitorScanPathHint(task.scan_path || '');
            monitorFolderTrail = [{ id: '0', name: '根目录' }];
            monitorFolderEntries = [];
            monitorFolderSummary = { folder_count: 0, file_count: 0 };
            monitorFolderLoading = false;
            document.getElementById('monitor_target_path').value = task.target_path || '';
            document.getElementById('monitor_skip_by_dir_mtime').checked = !!task.skip_by_dir_mtime;
            document.getElementById('monitor_strm_write_mode').value = task.strm_write_mode === 'full' ? 'full' : 'incremental';
            document.getElementById('monitor_sync_clean').checked = Object.prototype.hasOwnProperty.call(task, 'sync_clean')
                ? !!task.sync_clean
                : !task.incremental;
            document.getElementById('monitor_retries').value = task.retries ?? 3;
            document.getElementById('monitor_list_delay_ms').value = task.list_delay_ms ?? 250;
            document.getElementById('monitor_min_file_size_mb').value = task.min_file_size_mb ?? 0;
            document.getElementById('monitor_delay_seconds').value = task.delay_seconds ?? 0;
            document.getElementById('monitor_cron_minutes').value = task.cron_minutes ?? 0;
            refreshWebhookHint();
            showLockedModal('monitor-modal');
            switchTab('monitor');
        }

        async function deleteMonitorTask(name) {
            if (!(await showAppConfirm(`确定删除监控任务“${name}”吗？`))) return;
            if (isMonitorActionLocked('delete', name)) return;
            setMonitorActionLock('delete', name, true);
            try {
                await window.MediaHubApi.postJson('/monitor/delete', { name });
                applyMonitorState({
                    ...monitorState,
                    tasks: (monitorState.tasks || []).filter(item => item.name !== name),
                    queued: (monitorState.queued || []).filter(item => item !== name),
                    next_runs: Object.fromEntries(Object.entries(monitorState.next_runs || {}).filter(([taskName]) => taskName !== name))
                }, { forceRender: true });
                if (editingMonitorName === name) resetMonitorForm();
            } catch (error) {
                showToast(`删除失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            } finally {
                setMonitorActionLock('delete', name, false);
            }
        }

        async function startMonitorTask(name) {
            if (isMonitorActionLocked('start', name)) return;
            setMonitorActionLock('start', name, true);
            try {
                const data = await window.MediaHubApi.postJson('/monitor/start', { name });

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
            } catch (error) {
                showToast(`启动失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            } finally {
                setMonitorActionLock('start', name, false);
            }
        }

        async function stopMonitorTask(name) {
            if (isMonitorActionLocked('stop', name)) return;
            setMonitorActionLock('stop', name, true);
            try {
                const data = await window.MediaHubApi.postJson('/monitor/stop', { name }).catch(() => ({ ok: false }));
                if (!data.ok) {
                    showToast('当前没有这个任务在运行', { tone: 'warn', duration: 2600, placement: 'top-center' });
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
            const writeModeText = task?.strm_write_mode === 'full' ? '全量重写 STRM' : '增量写入 STRM';
            const cleanupText = (Object.prototype.hasOwnProperty.call(task || {}, 'sync_clean') ? !!task.sync_clean : !task?.incremental)
                ? '生成并清理过期 STRM'
                : '仅生成/更新 STRM';
            const scheduleMinutes = Math.max(0, Number(task?.cron_minutes || 0) || 0);
            const scheduleText = scheduleMinutes > 0
                ? `每 ${scheduleMinutes} 分钟自动执行一次，下次定时 ${String(nextRun || '计算中')}`
                : '未开启定时，仅手动运行或通过 Webhook 触发';
            const webhookText = task?.webhook_enabled ? '已启用 Webhook 触发' : '未启用 Webhook';
            return `状态：${statusText}。该任务会扫描 ${scanPath}，输出到 /strm/${targetPath}，写入模式为 ${writeModeText}，清理策略为 ${cleanupText}；${scheduleText}；${webhookText}。`;
        }

        function toggleMonitorTaskIntro(taskName) {
            monitorTaskIntroExpanded = toggleTaskIntroExpanded(monitorTaskIntroExpanded, taskName);
            renderMonitorTasks();
        }

        function buildMonitorTaskActionIcon(icon) {
            const icons = {
                run: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M8 5.75V18.25L17.5 12L8 5.75Z" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
                stop: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7.25 7.25H16.75V16.75H7.25V7.25Z" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
                queued: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 19.25A7.25 7.25 0 1 0 12 4.75A7.25 7.25 0 0 0 12 19.25Z" stroke="currentColor" stroke-width="1.8"/><path d="M12 8.25V12.25L14.75 14.25" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
                edit: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5.25 18.75L9.1 17.9L18.45 8.55A2.05 2.05 0 0 0 15.55 5.65L6.2 15L5.25 18.75Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M14.35 6.85L17.15 9.65" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
                delete: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 7.5H19" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M9.25 7.5V5.75H14.75V7.5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M8 10V18.25H16V10" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M10.5 11.5V16.5M13.5 11.5V16.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
                collapse: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 14L12 9L17 14" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
                expand: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 10L12 15L17 10" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            };
            return icons[icon] || icons.edit;
        }

        function buildMonitorTaskIconButton({
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
                    data-monitor-action="${escapeHtml(normalizedAction)}"
                    data-task-name="${encodeURIComponent(taskName)}"
                    class="monitor-task-icon-btn monitor-task-icon-btn-${escapeHtml(tone)} ${disabled ? 'btn-disabled' : ''}"
                    title="${escapeHtml(normalizedLabel)}"
                    aria-label="${escapeHtml(normalizedLabel)}"
                    ${attrText ? `${attrText} ` : ''}${disabledAttrs}
                >
                    ${buildMonitorTaskActionIcon(icon)}
                </button>
            `;
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
                const otherTaskRunning = monitorState.running && !running;
                const toggleRunAction = running ? 'stop' : 'start';
                const toggleRunLabel = running
                    ? (stopping ? '中断中' : '中断')
                    : (queued ? '排队中' : (starting ? '启动中' : '运行'));
                const toggleRunDisabled = queued || otherTaskRunning || starting || stopping || deleting;
                const toggleRunTone = running ? 'stop' : (queued ? 'queued' : 'run');
                const toggleRunIcon = running ? 'stop' : (queued ? 'queued' : 'run');
                const deleteDisabled = running || starting || stopping || deleting;
                const nextRun = (monitorState.next_runs || {})[taskName];
                const introExpanded = isTaskIntroExpanded(monitorTaskIntroExpanded, taskName);
                const introText = buildMonitorTaskIntro(task, { running, queued, nextRun });
                const toggleRunButton = buildMonitorTaskIconButton({
                    action: 'toggle-run',
                    taskName,
                    label: toggleRunLabel,
                    icon: toggleRunIcon,
                    tone: toggleRunTone,
                    disabled: toggleRunDisabled,
                    extraAttrs: `data-monitor-run-action="${escapeHtml(toggleRunAction)}"`,
                });
                const editButton = buildMonitorTaskIconButton({
                    action: 'edit',
                    taskName,
                    label: '编辑',
                    icon: 'edit',
                    tone: 'edit',
                });
                const deleteButton = buildMonitorTaskIconButton({
                    action: 'delete',
                    taskName,
                    label: deleting ? '删除中' : '删除',
                    icon: 'delete',
                    tone: 'delete',
                    disabled: deleteDisabled,
                });
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
                                    class="monitor-intro-toggle-btn"
                                    title="${introExpanded ? '收起简介' : '展开简介'}"
                                    aria-label="${introExpanded ? '收起简介' : '展开简介'}"
                                >${buildMonitorTaskActionIcon(introExpanded ? 'collapse' : 'expand')}</button>
                            </div>
                            <div class="monitor-task-actions monitor-task-actionbar" aria-label="文件夹监控任务操作">
                                ${toggleRunButton}
                                ${editButton}
                                ${deleteButton}
                            </div>
                        </div>
                        ${introExpanded ? `<div class="mt-3 text-xs text-slate-300 leading-6 rounded-xl border border-slate-700/90 bg-slate-950/45 px-3 py-2">${escapeHtml(introText)}</div>` : ''}
                    </div>
                `;
            }).join('');
        }

        function buildMonitorLogSignature() {
            const segments = Array.isArray(monitorState.log_segments) && monitorState.log_segments.length
                ? monitorState.log_segments
                : [{ id: 'legacy', entries: monitorState.logs || [] }];
            return buildLogSignature(segments, (segment) => {
                const entries = Array.isArray(segment?.entries) ? segment.entries : [];
                return `${segment?.id || ''}:${segment?.entry_count || entries.length}:${segment?.complete ? 1 : 0}:${entries.map((item) => `${item?.level || 'info'}:${item?.text || ''}`).join('||')}`;
            });
        }

        function updateMonitorLogSegmentSummary() {
            const summary = document.getElementById('monitor-log-segment-summary');
            const loadMoreBtn = document.getElementById('monitor-log-load-more');
            if (summary) {
                const total = Number(monitorState.log_segment_total || 0) || 0;
                const visible = Array.isArray(monitorState.log_segments) && monitorState.log_segments.length
                    ? monitorState.log_segments.filter(segment => String(segment?.kind || '') === 'task').length || monitorState.log_segments.length
                    : (Array.isArray(monitorState.logs) ? 1 : 0);
                summary.innerText = total > 0 ? `已显示最近 ${visible} / ${total} 条任务` : '暂无任务日志';
            }
            if (loadMoreBtn) {
                const hasMore = !!monitorState.log_segment_has_more;
                loadMoreBtn.classList.toggle('hidden', !hasMore);
                loadMoreBtn.disabled = !hasMore || monitorLogLoadBusy;
                loadMoreBtn.innerText = monitorLogLoadBusy ? '加载中...' : '加载更早 3 条';
            }
        }

        function renderMonitorLogs({ preserveScroll = false } = {}) {
            const box = document.getElementById('monitor-log-box');
            const segments = Array.isArray(monitorState.log_segments) && monitorState.log_segments.length
                ? monitorState.log_segments
                : null;
            const logSignature = buildMonitorLogSignature();
            if (logSignature === lastMonitorLogSignature) {
                updateMonitorLogSegmentSummary();
                return;
            }
            const previousScrollTop = preserveScroll ? box.scrollTop : 0;
            const previousScrollHeight = preserveScroll ? box.scrollHeight : 0;
            const logs = segments
                ? segments.flatMap(segment => Array.isArray(segment?.entries) ? segment.entries : [])
                : (monitorState.logs || []);
            box.innerHTML = logs.map(item => `<div class="${getLogEntryClass(item)}">${formatMonitorLogHtml(item)}</div>`).join('');
            if (preserveScroll) {
                box.scrollTop = Math.max(0, box.scrollHeight - previousScrollHeight + previousScrollTop);
            } else {
                box.scrollTop = box.scrollHeight;
            }
            lastMonitorLogSignature = logSignature;
            updateMonitorLogSegmentSummary();
        }

        async function loadOlderMonitorLogs() {
            if (monitorLogLoadBusy || !monitorState.log_segment_has_more) return;
            monitorLogLoadBusy = true;
            updateMonitorLogSegmentSummary();
            try {
                const offset = Array.isArray(monitorState.log_segments)
                    ? monitorState.log_segments.filter(segment => String(segment?.kind || '') === 'task').length
                    : 0;
                const data = await window.MediaHubApi.getJson(`/monitor/logs/tasks?offset=${offset}&limit=3`);
                const olderSegments = Array.isArray(data?.segments) ? data.segments : [];
                const currentSegments = Array.isArray(monitorState.log_segments) ? monitorState.log_segments : [];
                const existingIds = new Set(currentSegments.map(segment => String(segment?.id || '')).filter(Boolean));
                const merged = [
                    ...olderSegments.filter(segment => !existingIds.has(String(segment?.id || ''))),
                    ...currentSegments,
                ];
                monitorState = {
                    ...monitorState,
                    log_segments: merged,
                    log_segment_total: Number(data?.total || monitorState.log_segment_total || merged.length) || merged.length,
                    log_segment_has_more: !!data?.has_more,
                };
                renderMonitorLogs({ preserveScroll: true });
            } catch (e) {}
            monitorLogLoadBusy = false;
            updateMonitorLogSegmentSummary();
        }

        async function refreshMainLogs({ compact = false } = {}) {
            const taskModule = await loadTaskTabModule();
            if (taskModule?.refreshMainLogs) {
                await taskModule.refreshMainLogs({
                    applyMainState,
                    compact,
                });
                return;
            }
            try {
                const endpoint = compact ? '/logs?compact=1' : '/logs';
                applyMainState(await window.MediaHubApi.getJson(endpoint));
            } catch (e) {}
        }

        async function refreshMonitorState({ compact = false } = {}) {
            const monitorModule = await loadMonitorTabModule();
            if (monitorModule?.refreshMonitorState) {
                await monitorModule.refreshMonitorState({
                    applyMonitorState,
                    compact,
                });
                return;
            }
            try {
                const endpoint = compact ? '/monitor/status?compact=1' : '/monitor/status';
                applyMonitorState(await window.MediaHubApi.getJson(endpoint));
            } catch (e) {}
        }
