        async function triggerResourceJobRefresh(jobId) {
            await window.ResourceJobActions?.triggerRefresh({ refreshResourceState }, jobId);
        }

        async function triggerResourceJobCancel(jobId) {
            await window.ResourceJobActions?.triggerCancel({ refreshResourceState, showToast }, jobId);
        }

        async function triggerResourceJobRetry(jobId) {
            await window.ResourceJobActions?.triggerRetry({ refreshResourceState, showToast }, jobId);
        }

        async function showVersionBanner(latest) {
            const aboutModule = await loadAboutTabModule();
            if (!aboutModule?.showVersionBanner) return;
            aboutModule.showVersionBanner({
                versionInfo,
                latest,
                fallbackProjectUrl: VERSION_FALLBACK_PROJECT_URL,
                fallbackChangelogUrl: VERSION_FALLBACK_CHANGELOG_URL,
            });
        }

        function hideVersionBanner() {
            const aboutModule = tabRuntimeState.tabModuleCache.about;
            if (aboutModule?.hideVersionBanner) {
                aboutModule.hideVersionBanner();
                return;
            }
            document.getElementById('version-banner')?.classList.add('hidden');
        }

        function dismissVersionBanner() {
            const aboutModule = tabRuntimeState.tabModuleCache.about;
            if (aboutModule?.dismissVersionBanner) {
                aboutModule.dismissVersionBanner({
                    setDismissed: (value) => {
                        versionBannerDismissed = !!value;
                    },
                });
                return;
            }
            versionBannerDismissed = true;
            hideVersionBanner();
        }

        async function refreshVersionInfo(force = false) {
            const aboutModule = await loadAboutTabModule();
            if (aboutModule?.refreshVersionInfo) {
                await aboutModule.refreshVersionInfo({
                    force,
                    getVersionInfo: () => versionInfo,
                    setVersionInfo: (nextVersionInfo) => {
                        versionInfo = nextVersionInfo || versionInfo;
                    },
                    isDismissed: () => versionBannerDismissed,
                    setDismissed: (value) => {
                        versionBannerDismissed = !!value;
                    },
                    renderPanel: renderVersionInfoPanel,
                    showBanner: ({ latest: nextLatest }) => showVersionBanner(nextLatest),
                    hideBanner: hideVersionBanner,
                    fallbackProjectUrl: VERSION_FALLBACK_PROJECT_URL,
                    fallbackChangelogUrl: VERSION_FALLBACK_CHANGELOG_URL,
                });
            }
        }

        async function manualVersionCheck() {
            const aboutModule = await loadAboutTabModule();
            if (aboutModule?.manualVersionCheck) {
                await aboutModule.manualVersionCheck({
                    refreshVersionInfo,
                    getVersionInfo: () => versionInfo,
                });
            }
        }

        async function init() {
            try {
                const res = await fetch('/get_settings');
                if (!res.ok) return;
                const cfg = await res.json();
                const sensitiveMeta = normalizeSensitiveConfigMeta(cfg.sensitive_configured || {});

                Object.keys(cfg).forEach(k => {
                    const el = document.getElementById(k);
                    if (el && k !== 'trees' && k !== 'sensitive_configured') {
                        if (el.type === 'checkbox') el.checked = cfg[k];
                        else el.value = cfg[k];
                    }
                });
                applySensitiveConfigMeta(sensitiveMeta);
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
                    cookie_configured: !!sensitiveMeta.cookie_115,
                    quark_cookie_configured: !!sensitiveMeta.cookie_quark,
                    cookie_health: cfg.cookie_health && typeof cfg.cookie_health === 'object'
                        ? cfg.cookie_health
                        : (resourceState.cookie_health || null)
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
                void renderVersionInfoPanel();
                await refreshSign115Status(true);
            } catch (e) {}
        }

        document.getElementById('monitor_name')?.addEventListener('input', refreshWebhookHint);
        ['subscription_title'].forEach(id => {
            document.getElementById(id)?.addEventListener('keydown', async (e) => {
                if (e.key !== 'Enter' || e.isComposing) return;
                e.preventDefault();
                await saveSubscriptionTask();
            });
        });
        document.getElementById('subscription_tmdb_search_keyword')?.addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter' || e.isComposing) return;
            e.preventDefault();
            await searchSubscriptionTmdbBinding();
        });
        document.getElementById('subscription_media_type')?.addEventListener('change', () => {
            syncSubscriptionTypeUI();
        });
        document.getElementById('subscription_season')?.addEventListener('change', () => {
            suggestSubscriptionTotalEpisodesFromTmdb({ force: true });
            renderSubscriptionTmdbBinding();
        });
        document.getElementById('subscription_anime_mode')?.addEventListener('change', () => {
            syncSubscriptionTypeUI({ forceSuggestTotal: true });
        });
        ['resource_source_name', 'resource_source_channel'].forEach(id => {
            document.getElementById(id)?.addEventListener('keydown', async (e) => {
                if (e.key !== 'Enter' || e.isComposing) return;
                e.preventDefault();
                await saveResourceSource();
            });
        });
        document.getElementById('resource-channel-manage-name')?.addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter' || e.isComposing) return;
            e.preventDefault();
            await saveResourceChannelManage();
        });
        document.getElementById('resource_source_import_json')?.addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter' || e.isComposing || (!e.metaKey && !e.ctrlKey)) return;
            e.preventDefault();
            await importResourceSources();
        });
        document.getElementById('resource-search-input')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') searchResources();
        });
        document.getElementById('resource-search-input')?.addEventListener('input', async (e) => {
            syncResourceSearchInputActions();
            if (String(e.target?.value || '').trim()) return;
            if (String(resourceState.search || '').trim()) {
                resetResourceSearchResults();
                await refreshResourceState({ keywordOverride: '' });
                return;
            }
            renderResourceBoard();
        });
        document.getElementById('resource-quick-link-strip')?.addEventListener('click', async (e) => {
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
        document.getElementById('resource-quick-link-list')?.addEventListener('click', async (e) => {
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
            document.getElementById(id)?.addEventListener('keydown', async (e) => {
                if (e.key !== 'Enter' || e.isComposing) return;
                e.preventDefault();
                await saveResourceQuickLink();
            });
        });
        document.getElementById('resource-job-modal-toggle')?.addEventListener('click', () => {
            toggleResourceJobModal();
        });
        document.getElementById('resource-source-list')?.addEventListener('click', async (e) => {
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
        document.getElementById('resource-source-list')?.addEventListener('change', async (e) => {
            const toggle = e.target.closest('[data-resource-source-toggle]');
            if (!toggle) return;
            const index = parseInt(toggle.dataset.resourceSourceIndex || '-1', 10);
            if (index < 0) return;
            const ok = await toggleResourceSourceEnabled(index, !!toggle.checked);
            if (!ok) toggle.checked = !toggle.checked;
        });
        document.getElementById('resource-source-manager-type-filters')?.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-source-manager-filter="type"]');
            if (!btn) return;
            const nextFilter = normalizeResourceSourceFilterValue(btn.dataset.filterValue || 'all');
            if (resourceSourceFilter === nextFilter) return;
            resourceSourceFilter = nextFilter;
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-status-filters')?.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-source-manager-filter="status"]');
            if (!btn) return;
            const nextFilter = normalizeResourceSourceFilterValue(btn.dataset.filterValue || 'all');
            if (resourceSourceEnabledFilter === nextFilter) return;
            resourceSourceEnabledFilter = nextFilter;
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-activity-filters')?.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-source-manager-filter="activity"]');
            if (!btn) return;
            const nextFilter = normalizeResourceSourceFilterValue(btn.dataset.filterValue || 'all');
            if (resourceSourceActivityFilter === nextFilter) return;
            resourceSourceActivityFilter = nextFilter;
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-search')?.addEventListener('input', (e) => {
            resourceSourceKeyword = String(e.target?.value || '');
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-sort')?.addEventListener('change', (e) => {
            resourceSourceSortMode = String(e.target?.value || 'recent') || 'recent';
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-list')?.addEventListener('change', (e) => {
            const checkbox = e.target.closest('[data-resource-source-bulk-toggle]');
            if (!checkbox) return;
            setResourceSourceBulkSelected(checkbox.dataset.resourceSourceBulkToggle || '', !!checkbox.checked);
            renderResourceSourceManagerModal();
        });
        document.getElementById('resource-source-manager-list')?.addEventListener('click', async (e) => {
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
        document.getElementById('resource-onboarding-steps')?.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-onboarding-tab]');
            if (!btn) return;
            const tab = String(btn.dataset.onboardingTab || '').trim();
            if (!tab) return;
            switchTab(tab);
        });

        document.getElementById('resource-board')?.addEventListener('click', async (e) => {
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
        document.getElementById('resource-job-list')?.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-job-action]');
            if (!btn) return;
            const action = btn.dataset.resourceJobAction || '';
            if (action === 'load-more') {
                await loadMoreResourceJobs();
                return;
            }
            const jobId = parseInt(btn.dataset.resourceJobId || '0', 10);
            if (!jobId) return;
            if (action === 'refresh') await triggerResourceJobRefresh(jobId);
            if (action === 'cancel') await triggerResourceJobCancel(jobId);
            if (action === 'retry') await triggerResourceJobRetry(jobId);
        });
        document.getElementById('resource-job-filter-tabs')?.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-resource-job-filter]');
            if (!btn) return;
            const nextFilter = String(btn.dataset.resourceJobFilter || 'all').trim() || 'all';
            const pageFilter = String(resourceState?.job_pagination?.status || 'all').trim() || 'all';
            if (resourceJobFilter === nextFilter && pageFilter === nextFilter) return;
            resourceJobFilter = nextFilter;
            void fetchResourceJobsPage({ status: nextFilter, offset: 0 });
        });
        document.getElementById('subscription-task-list')?.addEventListener('click', async (e) => {
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
        document.getElementById('monitor-task-list')?.addEventListener('click', async (e) => {
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
        document.getElementById('monitor-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'monitor-modal') closeMonitorModal();
        });
        document.getElementById('subscription-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'subscription-modal') closeSubscriptionModal();
        });
        document.getElementById('subscription-tmdb-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'subscription-tmdb-modal') closeSubscriptionTmdbSearchModal();
        });
        document.getElementById('subscription-episode-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'subscription-episode-modal') closeSubscriptionEpisodeModal();
        });
        document.getElementById('subscription-folder-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'subscription-folder-modal') closeSubscriptionFolderModal();
        });
        document.getElementById('subscription-share-folder-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'subscription-share-folder-modal') closeSubscriptionShareFolderModal();
        });
        document.getElementById('help-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'help-modal') closeHelpModal();
        });
        document.getElementById('resource-source-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'resource-source-modal') closeResourceSourceModal();
        });
        document.getElementById('resource-channel-manage-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'resource-channel-manage-modal') closeResourceChannelManageModal();
        });
        document.getElementById('resource-source-import-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'resource-source-import-modal') closeResourceSourceImportModal();
        });
        document.getElementById('resource-source-manager-modal')?.addEventListener('click', (e) => {
            const panelBtn = e.target.closest('[data-resource-source-manager-panel]');
            if (panelBtn) {
                setResourceSourceManagerMobilePanel(panelBtn.dataset.resourceSourceManagerPanel || 'list');
                renderResourceSourceManagerModal();
                return;
            }
            if (e.target.id === 'resource-source-manager-modal') closeResourceSourceManagerModal();
        });
        document.getElementById('resource-import-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'resource-import-modal') closeResourceJobModal();
        });
        document.getElementById('resource-folder-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'resource-folder-modal') closeResourceFolderModal();
        });
        document.getElementById('resource-quick-link-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'resource-quick-link-modal') closeResourceQuickLinkModal();
        });
        document.getElementById('resource-folder-create-name')?.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            createResourceFolderInCurrent();
        });
        document.getElementById('subscription-folder-create-name')?.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            createSubscriptionFolderInCurrent();
        });
        document.getElementById('resource-folder-list')?.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-folder-action]');
            if (!btn) return;
            const action = btn.dataset.resourceFolderAction || '';
            if (action === 'open') {
                await openResourceFolderChild(btn.dataset.resourceFolderId || '0', btn.dataset.resourceFolderName || '--');
                return;
            }
            if (action === 'load-files') {
                await loadResourceFolderFiles(resourceFolderTrail[resourceFolderTrail.length - 1]?.id || '0');
                return;
            }
            if (action === 'toggle-files') {
                resourceFolderShowAllFiles = !resourceFolderShowAllFiles;
                renderResourceFolderList();
            }
        });
        document.getElementById('subscription-folder-list')?.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-folder-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionFolderAction || '';
            if (action === 'open') {
                await openSubscriptionFolderChild(btn.dataset.subscriptionFolderId || '0', btn.dataset.subscriptionFolderName || '--');
            }
        });
        document.getElementById('subscription-share-folder-list')?.addEventListener('click', async (e) => {
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
        document.getElementById('subscription_tmdb_result_list')?.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-tmdb-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionTmdbAction || '';
            if (action === 'select') {
                await selectSubscriptionTmdbResult(btn.dataset.subscriptionTmdbIndex || '0');
            }
        });
        document.getElementById('resource-folder-breadcrumbs')?.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-folder-action]');
            if (!btn) return;
            const action = btn.dataset.resourceFolderAction || '';
            if (action === 'trail') {
                await openResourceFolderTrail(btn.dataset.resourceFolderIndex || '0');
            }
        });
        document.getElementById('subscription-folder-breadcrumbs')?.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-folder-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionFolderAction || '';
            if (action === 'trail') {
                await openSubscriptionFolderTrail(btn.dataset.subscriptionFolderIndex || '0');
            }
        });
        document.getElementById('subscription-share-folder-breadcrumbs')?.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-subscription-share-folder-action]');
            if (!btn) return;
            const action = btn.dataset.subscriptionShareFolderAction || '';
            if (action === 'trail') {
                await openSubscriptionShareFolderTrail(btn.dataset.subscriptionShareFolderIndex || '0');
            }
        });
        document.getElementById('resource-job-modal')?.addEventListener('click', (e) => {
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
        document.getElementById('resource-share-tree')?.addEventListener('click', async (e) => {
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
        document.getElementById('resource-share-root-title')?.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-resource-share-action]');
            if (!btn) return;
            const action = btn.dataset.resourceShareAction || '';
            if (action === 'trail') {
                await openResourceShareTrail(btn.dataset.resourceShareIndex || '0');
            }
        });
        document.getElementById('resource-share-tree')?.addEventListener('change', (e) => {
            const checkbox = e.target.closest('[data-resource-share-check]');
            if (!checkbox) return;
            const entryId = String(checkbox.dataset.resourceShareId || '').trim();
            const entry = resourceShareEntryIndex[entryId];
            if (!entry) return;
            applyResourceShareSelection(entry, checkbox.checked);
        });
        document.getElementById('resource-share-current-check-all')?.addEventListener('change', (e) => {
            setCurrentResourceShareEntriesChecked(!!e.target.checked);
        });
        document.getElementById('resource_share_receive_code')?.addEventListener('keydown', async (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            await applyResourceShareReceiveCode();
        });
        document.getElementById('resource_share_receive_code')?.addEventListener('input', (e) => {
            const rawCode = String(e?.target?.value || '').trim();
            resourceShareReceiveCode = normalizeReceiveCodeInput(rawCode);
        });
        document.getElementById('subscription_share_link_url')?.addEventListener('input', () => {
            const cidInput = document.getElementById('subscription_share_subdir_cid');
            if (cidInput) cidInput.value = '';
        });
        document.getElementById('subscription_share_subdir')?.addEventListener('input', () => {
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
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                scheduleResourcePolling(500);
                return;
            }
            scheduleResourcePolling();
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
        window.addEventListener('hashchange', () => {
            if (suppressHashTabSync) return;
            Promise.resolve().then(async () => {
                const targetTab = await readTabFromLocationHash();
                if (!targetTab || targetTab === currentTab) return;
                await switchTab(targetTab, { syncHash: false });
            });
        });
        syncViewportMetrics();
        applyThemeFromStorage();
        loadResourceQuickLinksFromStorage();
        initMainTabRow();
        void loadTaskTabModule();
        void loadSettingsTabModule();
        void loadMonitorTabModule();
        void loadSubscriptionTabModule();
        void loadResourceTabModule();
        const initPromise = init();
        syncResourceBackTopButton();
        syncSettingsSaveDock();
        syncMainTabRowState();
        refreshResourceState();
        Promise.resolve().then(async () => {
            const initialTab = await readTabFromLocationHash();
            if (initialTab && initialTab !== currentTab) {
                await switchTab(initialTab, { syncHash: false });
                return;
            }
            await syncLocationHashWithTab(currentTab, { replace: true });
        });
        initPromise.finally(() => {
            moduleVisitState.settings = true;
            connectStatusStream();
        });
        scheduleResourcePolling(RESOURCE_POLL_ACTIVE_INTERVAL);
        refreshVersionInfo();
        setInterval(() => refreshVersionInfo(false), VERSION_REFRESH_INTERVAL);
        setInterval(() => refreshSign115Status(false), SIGN115_REFRESH_INTERVAL);
