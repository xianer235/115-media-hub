        const resourcePosterFailedProxyUrls = new Set();

        function markResourcePosterLoadFailed(img) {
            const proxyUrl = String(img?.dataset?.proxyUrl || img?.getAttribute('src') || '').trim();
            if (proxyUrl) resourcePosterFailedProxyUrls.add(proxyUrl);
            img?.classList?.add('hidden');
            img?.nextElementSibling?.classList?.remove('hidden');
        }

        window.markResourcePosterLoadFailed = markResourcePosterLoadFailed;

        function getResourceStatusLabel(status) {
            const normalized = String(status || 'new').trim().toLowerCase();
            const map = {
                new: '未处理',
                queued: '已入队',
                pending: '等待中',
                running: '执行中',
                importing: '导入中',
                submitted: '待刷新',
                partial: '部分完成',
                completed: '已完成',
                failed: '失败',
                rollback_running: '回退中',
                rolled_back: '已回退',
                rollback_failed: '回退失败',
            };
            return map[normalized] || (normalized || '未处理');
        }

        function buildResourceStatusBadge(status) {
            const normalized = String(status || 'new').trim().toLowerCase();
            const map = {
                new: 'bg-slate-700 text-slate-100',
                queued: 'bg-sky-500/15 text-sky-300 border border-sky-500/20',
                pending: 'bg-sky-500/15 text-sky-300 border border-sky-500/20',
                running: 'bg-violet-500/15 text-violet-300 border border-violet-500/20',
                importing: 'bg-violet-500/15 text-violet-300 border border-violet-500/20',
                submitted: 'bg-amber-500/15 text-amber-300 border border-amber-500/20',
                partial: 'bg-amber-500/15 text-amber-300 border border-amber-500/20',
                completed: 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20',
                failed: 'bg-red-500/10 text-red-300 border border-red-500/20',
                rollback_running: 'bg-amber-500/15 text-amber-300 border border-amber-500/20',
                rolled_back: 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20',
                rollback_failed: 'bg-red-500/10 text-red-300 border border-red-500/20',
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

        function normalizeResourceSourceUsage(source) {
            const rawSource = source && typeof source === 'object' ? source : {};
            const rawUsage = String(rawSource.usage || '').trim().toLowerCase().replace(/-/g, '_');
            if (['off', 'disabled', 'disable', 'closed', 'close', 'none', 'false', '0'].includes(rawUsage)) return 'off';
            if (['search', 'search_only', 'only_search', 'searchonly'].includes(rawUsage)) return 'search_only';
            if (['sync_search', 'sync_and_search', 'search_sync', 'sync', 'enabled', 'enable', 'on', 'true', '1', 'all'].includes(rawUsage)) return 'sync_search';

            if (Object.prototype.hasOwnProperty.call(rawSource, 'sync_enabled') || Object.prototype.hasOwnProperty.call(rawSource, 'search_enabled')) {
                const syncEnabled = rawSource.sync_enabled === true;
                const searchEnabled = Object.prototype.hasOwnProperty.call(rawSource, 'search_enabled')
                    ? rawSource.search_enabled === true
                    : syncEnabled;
                if (syncEnabled) return 'sync_search';
                if (searchEnabled) return 'search_only';
                return 'off';
            }

            if (Object.prototype.hasOwnProperty.call(rawSource, 'enabled')) {
                return rawSource.enabled === false ? 'off' : 'sync_search';
            }
            return 'sync_search';
        }

        function isResourceSourceSyncEnabled(source) {
            return normalizeResourceSourceUsage(source) === 'sync_search';
        }

        function isResourceSourceSearchEnabled(source) {
            return ['search_only', 'sync_search'].includes(normalizeResourceSourceUsage(source));
        }

        function getResourceSourceUsageLabel(sourceOrUsage) {
            const usage = typeof sourceOrUsage === 'string'
                ? normalizeResourceSourceUsage({ usage: sourceOrUsage })
                : normalizeResourceSourceUsage(sourceOrUsage);
            if (usage === 'off') return '关闭';
            if (usage === 'search_only') return '仅搜索';
            return '同步+搜索';
        }

        function getResourceSourceUsageBadgeClass(sourceOrUsage) {
            const usage = typeof sourceOrUsage === 'string'
                ? normalizeResourceSourceUsage({ usage: sourceOrUsage })
                : normalizeResourceSourceUsage(sourceOrUsage);
            if (usage === 'off') return 'bg-slate-700 text-slate-300 border border-slate-600';
            if (usage === 'search_only') return 'bg-sky-500/10 text-sky-300 border border-sky-500/20';
            return 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20';
        }

        function isLikelyTelegramChannelId(channelId) {
            return /^[A-Za-z0-9_]{5,32}$/.test(String(channelId || '').trim());
        }

        function getResourceSourcesForSelect() {
            return Array.isArray(resourceState.sources) ? resourceState.sources : [];
        }

        function getEnabledResourceSources() {
            return getResourceSourcesForSelect().filter(source => isResourceSourceSearchEnabled(source) && getResourceSourceChannelId(source));
        }

        function getProviderMeta() {
            return window.providerMeta || [];
        }

        function getEnabledProviders() {
            return getProviderMeta().filter(p => p.enabled);
        }

        function normalizeResourceProviderName(value, fallback = '115') {
            const normalized = String(value || '').trim().toLowerCase();
            const byName = getProviderMeta().find(p => p.name === normalized);
            if (byName) return byName.name;
            const byLinkType = getProviderMeta().find(p => p.link_type === normalized);
            if (byLinkType) return byLinkType.name;
            const fallbackName = String(fallback || '115').trim().toLowerCase();
            const fallbackMeta = getProviderMeta().find(p => p.name === fallbackName);
            return fallbackMeta ? fallbackMeta.name : '115';
        }

        function getProviderByName(name) {
            const normalized = String(name || '').trim().toLowerCase();
            return getProviderMeta().find(p => p.name === normalized);
        }

        function getProviderByLinkType(linkType) {
            const normalized = String(linkType || '').trim().toLowerCase();
            return getProviderMeta().find(p => p.link_type === normalized) || null;
        }

        function getOfflineMagnetProviders() {
            return getProviderMeta().filter(p => p && p.supports_offline && p.enabled !== false);
        }

        function normalizeResourceMagnetProviderName(provider, fallback = '115') {
            const normalized = String(provider || '').trim().toLowerCase();
            const offlineProviders = getOfflineMagnetProviders();
            const matched = offlineProviders.find(p => p.name === normalized);
            if (matched) return matched.name;
            const fallbackName = String(fallback || '115').trim().toLowerCase();
            const fallbackMatched = offlineProviders.find(p => p.name === fallbackName);
            if (fallbackMatched) return fallbackMatched.name;
            return offlineProviders[0]?.name || '115';
        }

        function getResourceDefaultMagnetProvider() {
            const fromState = resourceState?.default_magnet_provider;
            if (fromState) {
                const normalized = String(fromState).trim().toLowerCase();
                return normalizeResourceMagnetProviderName(normalized);
            }
            const settingEl = document.getElementById('default_magnet_provider');
            const rawValue = settingEl ? settingEl.value : '115';
            const normalized = String(rawValue || '115').trim().toLowerCase();
            return normalizeResourceMagnetProviderName(normalized);
        }

        function getResourceSelectedMagnetProvider() {
            return getResourceDefaultMagnetProvider();
        }

        function getResourceProviderForLinkType(linkType) {
            const normalized = String(linkType || '').trim().toLowerCase();
            if (normalized === 'magnet') return getResourceSelectedMagnetProvider();
            if (normalized === 'ed2k' || normalized === 'link') return '115';
            return getResourceProviderByLinkType(normalized);
        }

        function getCurrentResourceProviderLabel() {
            const provider = getCurrentResourceProvider();
            return provider ? getResourceProviderLabel(provider) : '下载网盘';
        }

        function getResourceLinkTypeLabel(linkType) {
            const normalized = String(linkType || 'unknown').trim().toLowerCase();
            const p = getProviderByLinkType(normalized);
            if (p) return p.label;
            const map = {
                magnet: 'Magnet',
                '115share': '115 分享',
                ed2k: 'ED2K',
                baidu: '百度网盘',
                xunlei: '迅雷网盘',
                uc: 'UC 网盘',
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

        function getResourceDisplayLinkType(item) {
            return window.ResourceLinkTags.resolveDisplayType(item);
        }

        function getResourceDisplayLinkTypeLabel(linkType) {
            return window.ResourceLinkTags.getTagMeta(linkType).label;
        }

        function getResourceDisplayLinkTypeBadgeClass(linkType) {
            const tone = window.ResourceLinkTags.getTagMeta(linkType).tone;
            return `resource-link-tag resource-link-tag--${tone}`;
        }

        function getResourceLinkRecords(item) {
            return window.ResourceLinkTags.getResourceLinkRecords(item);
        }

        function createResourceLinkActionItem(item, record) {
            const resource = item && typeof item === 'object' ? item : {};
            const link = record && typeof record === 'object' ? record : {};
            const linkUrl = String(link.link_url || '').trim();
            const linkType = String(link.link_type || '').trim();
            const allRecords = getResourceLinkRecords(resource);
            const relatedRecords = linkType === 'ed2k'
                ? allRecords.filter(candidate => String(candidate?.link_type || '').trim() === 'ed2k')
                : [link];
            const extra = resource.extra && typeof resource.extra === 'object' ? resource.extra : {};
            return {
                ...resource,
                link_url: linkUrl,
                link_type: linkType,
                receive_code: String(link.receive_code || '').trim(),
                extra: {
                    ...extra,
                    resource_links: relatedRecords,
                    all_links: relatedRecords.map(candidate => String(candidate?.link_url || '').trim()).filter(Boolean),
                    receive_code: String(link.receive_code || '').trim(),
                },
            };
        }

        function getResourceImportCandidates(item) {
            const candidates = [];
            let hasEd2kCandidate = false;
            getResourceLinkRecords(item).forEach(record => {
                const candidate = createResourceLinkActionItem(item, record);
                const linkType = getEffectiveResourceLinkType(candidate);
                if (!canOpenResourceImportLink(candidate) || !isLinkTypeCookieConfigured(linkType)) return;
                if (linkType === 'ed2k') {
                    if (hasEd2kCandidate) return;
                    hasEd2kCandidate = true;
                }
                candidates.push(candidate);
            });
            return candidates;
        }

        function openResourceLinkChoiceModal(records, { title = '选择资源链接', actionLabel = '继续' } = {}) {
            const candidates = Array.isArray(records) ? records.filter(Boolean) : [];
            if (!candidates.length) return Promise.resolve(null);
            if (candidates.length === 1) return Promise.resolve(candidates[0]);
            return new Promise((resolve) => {
                const modal = document.createElement('div');
                modal.className = 'fixed inset-0 bg-black/60 z-[60] p-4 flex items-start justify-center';
                modal.innerHTML = `
                    <div class="w-full max-w-xl mt-[12vh] group-card modal-card" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
                        <div class="flex items-center justify-between gap-3 mb-3">
                            <div class="text-lg font-black text-white">${escapeHtml(title)}</div>
                            <button type="button" class="px-3 py-1 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm" data-resource-link-choice-cancel>关闭</button>
                        </div>
                        <div class="space-y-2">
                            ${candidates.map((record, index) => {
                                const displayType = getResourceDisplayLinkType(record);
                                const label = getResourceDisplayLinkTypeLabel(displayType);
                                return `
                                    <button type="button" class="w-full text-left p-3 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700" data-resource-link-choice-index="${index}">
                                        <span class="${escapeHtml(getResourceDisplayLinkTypeBadgeClass(displayType))}">${escapeHtml(label)}</span>
                                        <span class="block text-xs text-slate-400 break-all mt-2">${escapeHtml(record.link_url)}</span>
                                        <span class="block text-xs text-sky-300 mt-2">${escapeHtml(actionLabel)}</span>
                                    </button>
                                `;
                            }).join('')}
                        </div>
                    </div>
                `;
                const cleanup = (value) => {
                    document.removeEventListener('keydown', onKeydown);
                    modal.remove();
                    resolve(value || null);
                };
                const onKeydown = (event) => {
                    if (event.key === 'Escape') cleanup(null);
                };
                modal.addEventListener('click', (event) => {
                    if (event.target === modal || event.target.closest('[data-resource-link-choice-cancel]')) {
                        cleanup(null);
                        return;
                    }
                    const button = event.target.closest('[data-resource-link-choice-index]');
                    if (!button) return;
                    cleanup(candidates[Number(button.dataset.resourceLinkChoiceIndex)] || null);
                });
                document.addEventListener('keydown', onKeydown);
                document.body.appendChild(modal);
                window.setTimeout(() => modal.querySelector('[data-resource-link-choice-index]')?.focus(), 0);
            });
        }

        function getResourceImportMode(item) {
            return window.ResourceLinkTags.getTagMeta(getResourceDisplayLinkType(item)).importMode;
        }

        function buildResourceDisplayProfile(items, fallbackProfile = {}) {
            return window.ResourceLinkTags.summarize(items, fallbackProfile);
        }

        function getResourceProviderByLinkType(linkType) {
            if (linkType === 'magnet') {
                return getResourceSelectedMagnetProvider();
            }
            const p = getProviderByLinkType(linkType);
            return p ? p.name : '115';
        }

        function getResourceProviderLabel(provider) {
            const p = getProviderByName(normalizeResourceProviderName(provider, '115'));
            return p ? p.label : '115';
        }

        function normalizeResourceFavoriteDirsPayload(value = {}) {
            const source = value && typeof value === 'object' ? value : {};
            const providerNames = getProviderMeta()
                .filter(p => p.supports_folder_browse !== false)
                .map(p => p.name);
            const normalizeItems = (items = []) => {
                const seen = new Set();
                return (Array.isArray(items) ? items : [])
                    .map((item) => {
                        const path = normalizeRelativePathInput(item?.path || item?.savepath || '');
                        if (!path || seen.has(path)) return null;
                        seen.add(path);
                        const fallbackName = path.split('/').filter(Boolean).pop() || path;
                        return {
                            name: String(item?.name || fallbackName).trim().slice(0, 32) || fallbackName,
                            path,
                        };
                    })
                    .filter(Boolean)
                    .slice(0, 12);
            };
            const result = {};
            (providerNames.length ? providerNames : ['115', 'quark']).forEach((providerName) => {
                result[providerName] = normalizeItems(source[providerName]);
            });
            return result;
        }

        function getResourceFavoriteDirs(provider = getCurrentResourceProvider()) {
            if (!String(provider || '').trim()) return [];
            const normalizedProvider = normalizeResourceProviderName(provider, '115');
            const favoriteDirs = normalizeResourceFavoriteDirsPayload(resourceState.favorite_dirs || {});
            return favoriteDirs[normalizedProvider] || [];
        }

        function renderResourceFavoriteDirs() {
            const panel = document.getElementById('resource-favorite-dir-panel');
            const list = document.getElementById('resource-favorite-dir-list');
            const providerEl = document.getElementById('resource-favorite-dir-provider');
            if (!panel || !list) return;
            const provider = getCurrentResourceProvider();
            const providerLabel = getCurrentResourceProviderLabel();
            const dirs = getResourceFavoriteDirs(provider);
            const currentPath = normalizeRelativePathInput(document.getElementById('resource_job_savepath')?.value || '');
            if (providerEl) providerEl.textContent = providerLabel;
            panel.classList.toggle('hidden', !dirs.length);
            if (!dirs.length) {
                list.innerHTML = '';
                return;
            }
            list.innerHTML = dirs.map((item, index) => {
                const active = currentPath && currentPath === item.path;
                return `
                    <button
                        type="button"
                        data-resource-favorite-dir-index="${index}"
                        class="resource-favorite-dir-btn ${active ? 'resource-favorite-dir-btn-active' : ''}"
                        title="${escapeHtml(item.path)}"
                    >
                        <span class="resource-favorite-dir-name">${escapeHtml(item.name || item.path)}</span>
                        <span class="resource-favorite-dir-path">${escapeHtml(item.path)}</span>
                    </button>
                `;
            }).join('');
        }

        async function selectResourceFavoriteDir(index) {
            const dirs = getResourceFavoriteDirs();
            const item = dirs[Math.max(0, Number(index || 0))];
            const path = normalizeRelativePathInput(item?.path || '');
            if (!path) return;
            let selectedTrail = [{ id: '0', name: '根目录' }];
            let selectedFolderId = '0';
            try {
                const resolved = await resolveResourceFolderTrailByPath(path);
                if (resolved?.valid && Array.isArray(resolved.trail) && resolved.trail.length) {
                    selectedTrail = normalizeResourceFolderTrail(resolved.trail);
                    selectedFolderId = String(selectedTrail[selectedTrail.length - 1]?.id || '0').trim() || '0';
                }
            } catch (e) {}

            resourceFolderTrail = selectedTrail;
            resourceFolderEntries = [];
            resourceFolderSummary = { folder_count: 0, file_count: 0 };
            resourceFolderEntriesComplete = false;
            resourceFolderShowAllFiles = false;
            setSelectedResourceFolder(selectedFolderId, path, {
                loadPreview: false,
                persist: true,
                trail: selectedTrail,
            });
            renderResourceFavoriteDirs();
            showToast(`已选择常用目录：${path}`, { tone: 'success', duration: 2200, placement: 'top-center' });
        }

        function normalizeResourceSearchSource(value) {
            const normalized = String(value || 'tg').trim().toLowerCase();
            return normalized === 'pansou' ? 'pansou' : 'tg';
        }

        function normalizeResourceProviderFilter(value) {
            const normalized = String(value || 'all').trim().toLowerCase();
            if (normalized === 'all' || normalized === 'magnet') return normalized;
            const byName = getProviderByName(normalized);
            if (byName) return byName.name;
            const byLinkType = getProviderByLinkType(normalized);
            if (byLinkType) return byLinkType.name;
            if (normalized === '115share') return '115';
            if (normalized === 'magnet115') return 'magnet';
            return 'all';
        }

        function getResourceSearchSourceLabel(value = resourceSearchSource) {
            return normalizeResourceSearchSource(value) === 'pansou' ? '盘搜' : '频道搜索';
        }

        function getResourceProviderFilterLabel(value = resourceProviderFilter) {
            const normalized = normalizeResourceProviderFilter(value);
            if (normalized === 'magnet') return '离线';
            const p = getProviderByName(normalized);
            if (p) return p.label;
            return '全部';
        }

        function resourceItemMatchesProviderFilter(item, providerFilter = resourceProviderFilter) {
            const normalized = normalizeResourceProviderFilter(providerFilter);
            if (normalized === 'all') return true;
            const linkTypes = getResourceLinkRecords(item).map(record => getEffectiveResourceLinkType(record));
            if (normalized === 'magnet') return linkTypes.some(linkType => linkType === 'magnet' || linkType === 'ed2k');
            const p = getProviderByName(normalized);
            if (p) return linkTypes.includes(p.link_type);
            return false;
        }

        function getResourceFolderApiPrefix(provider) {
            return '/resource/browse/' + encodeURIComponent(normalizeResourceProviderName(provider, '115'));
        }

        function getResourceShareApiPrefix(linkType) {
            const p = getProviderByLinkType(linkType);
            if (p) return '/resource/browse/' + encodeURIComponent(p.name);
            return '/resource/115';
        }

        function isProviderCookieConfigured(provider) {
            if (!String(provider || '').trim()) return false;
            const meta = window.providerMeta || [];
            const p = meta.find(m => m.name === normalizeResourceProviderName(provider, '115'));
            if (!p) return false;
            if (resourceState?.provider_auth && resourceState.provider_auth[p.name] !== undefined) {
                return !!resourceState.provider_auth[p.name];
            }
            const key = 'cookie_configured_' + p.name;
            if (resourceState && resourceState[key] !== undefined) return resourceState[key];
            const cookieKey = p.config_keys[0] || 'cookie_' + p.name;
            return (resourceState && resourceState[cookieKey + '_configured']) || false;
        }

        function isLinkTypeCookieConfigured(linkType) {
            return isProviderCookieConfigured(getResourceProviderForLinkType(linkType));
        }

        function hasAnyResourceCookieConfigured() {
            const enabledProviderNames = new Set(getEnabledProviders().map(p => p.name));
            if (resourceState?.provider_auth && typeof resourceState.provider_auth === 'object') {
                return Object.entries(resourceState.provider_auth)
                    .some(([name, configured]) => enabledProviderNames.has(name) && !!configured);
            }
            const has115 = enabledProviderNames.has('115') && !!resourceState?.cookie_configured;
            const hasQuark = enabledProviderNames.has('quark') && !!resourceState?.quark_cookie_configured;
            return has115 || hasQuark;
        }

        function isResourceShareContentCookieHealthNoise(item) {
            const trigger = String(item?.entry?.trigger || '').trim().toLowerCase();
            return trigger.startsWith('runtime:list_115_share_entries')
                || trigger.startsWith('runtime:submit_115_share_receive')
                || trigger.startsWith('runtime:list_quark_share_entries')
                || trigger.startsWith('runtime:submit_quark_share_save');
        }

        function renderResourceCookieHint() {
            const hintEl = document.getElementById('resource-cookie-hint');
            if (!hintEl) return;
            if (!resourceStateHydrated) {
                hintEl.classList.add('hidden');
                return;
            }

            const state = normalizeCookieHealthState(resourceState?.cookie_health || cookieHealthState || {});
            const wm = window.providerMeta || [];
            const enabledMeta = wm.filter((p) => p.enabled !== false);
            if (wm.length && !enabledMeta.length) {
                hintEl.classList.add('hidden');
                return;
            }
            const providerMeta = wm.length ? enabledMeta.map((p) => ({
                provider: p.name,
                label: p.label || p.name,
                entry: normalizeCookieHealthEntry(state?.[p.name], p.name)
            })) : ['115', 'quark'].map((provider) => ({
                provider,
                label: provider === 'quark' ? 'Quark' : '115',
                entry: normalizeCookieHealthEntry(state?.[provider], provider)
            }));
            const configuredAny = providerMeta.some((item) => item.entry.configured) || hasAnyResourceCookieConfigured();
            const riskyProviders = providerMeta.filter((item) => (
                item.entry.configured && (item.entry.state === 'invalid' || item.entry.state === 'error')
                && !isResourceShareContentCookieHealthNoise(item)
            ));

            let message = '';
            let tone = 'warn';
            if (!configuredAny) {
                const labels = enabledMeta.length ? enabledMeta.map(p => p.label).join('、') : '115 或 Quark';
                message = `尚未配置可用网盘认证信息。请在”参数配置”填写 ${labels} 认证信息，保存后可点击健康检查。`;
            } else if (riskyProviders.length) {
                const hasInvalid = riskyProviders.some((item) => item.entry.state === 'invalid');
                tone = hasInvalid ? 'error' : 'warn';
                const detailText = riskyProviders
                    .map((item) => `${item.label}：${item.entry.message}`)
                    .join('；');
                message = `检测到网盘认证状态异常（${detailText}）。可继续执行，但建议在“参数配置”更新后重新检测。`;
            }

            hintEl.classList.toggle('hidden', !message);
            if (!message) return;
            hintEl.classList.remove(
                'border-amber-500/25', 'bg-amber-500/10', 'text-amber-200',
                'border-rose-500/25', 'bg-rose-500/10', 'text-rose-200'
            );
            if (tone === 'error') {
                hintEl.classList.add('border-rose-500/25', 'bg-rose-500/10', 'text-rose-200');
            } else {
                hintEl.classList.add('border-amber-500/25', 'bg-amber-500/10', 'text-amber-200');
            }
            hintEl.innerText = message;
        }

        function renderResourceSearchFilters() {
            const currentSource = normalizeResourceSearchSource(resourceSearchSource || resourceState.search_source || 'tg');
            const currentProvider = normalizeResourceProviderFilter(resourceProviderFilter || resourceState.provider_filter || 'all');
            [
                ['resource-search-source-tg', currentSource === 'tg'],
                ['resource-search-source-pansou', currentSource === 'pansou'],
                ['resource-provider-filter-all', currentProvider === 'all'],
                ['resource-provider-filter-magnet', currentProvider === 'magnet'],
            ].forEach(([id, active]) => {
                const el = document.getElementById(id);
                if (!el) return;
                el.classList.toggle('resource-search-segment-btn-active', !!active);
                el.setAttribute('aria-pressed', active ? 'true' : 'false');
            });
            getEnabledProviders().forEach((provider) => {
                const el = document.getElementById('resource-provider-filter-' + provider.name);
                if (!el) return;
                const active = currentProvider === provider.name;
                el.classList.toggle('resource-search-segment-btn-active', active);
                el.setAttribute('aria-pressed', active ? 'true' : 'false');
            });
        }

        async function refreshResourceForCurrentSearchControls() {
            const keyword = String(document.getElementById('resource-search-input')?.value || resourceState.search || '').trim();
            if (keyword && resourceSearchBusy) {
                resourceRestartSearchAfterCancel = true;
                cancelActiveResourceSearch({ notify: false });
                return;
            }
            if (keyword && !isDirectImportInput(keyword)) {
                await searchResources();
                return;
            }
            if (!keyword) {
                await refreshResourceState({ allowSearch: false, keywordOverride: '' });
                return;
            }
            renderResourceBoard();
        }

        function setResourceSearchSource(value) {
            const next = normalizeResourceSearchSource(value);
            if (next === resourceSearchSource) {
                renderResourceSearchFilters();
                return;
            }
            resourceSearchSource = next;
            resourceState = {
                ...resourceState,
                search_source: next,
            };
            renderResourceSearchFilters();
            void refreshResourceForCurrentSearchControls();
        }

        function setResourceProviderFilter(value) {
            const next = normalizeResourceProviderFilter(value);
            if (next === resourceProviderFilter) {
                renderResourceSearchFilters();
                return;
            }
            resourceProviderFilter = next;
            resourceState = {
                ...resourceState,
                provider_filter: next,
            };
            renderResourceSearchFilters();
            if (resourceSearchBusy) {
                const keyword = String(document.getElementById('resource-search-input')?.value || resourceState.search || '').trim();
                const source = normalizeResourceSearchSource(resourceSearchSource || resourceState.search_source || 'tg');
                updateResourceActiveSearchRuntime({
                    source,
                    keyword,
                    providerFilter: next,
                    latencyMs: source === 'tg' ? Number(resourceTgLastLatencyMs || 0) : 0,
                });
                resourceBoardHintText = getResourceSearchRunningHintText();
                renderResourceBoardHint();
                return;
            }
            renderResourceBoard();
        }

        function isResourceShareLinkType(linkType) {
            const normalized = String(linkType || '').trim().toLowerCase();
            const p = getProviderByLinkType(normalized);
            return !!(p && p.supports_share_receive);
        }

        function getCurrentResourceProvider() {
            return getResourceProviderForLinkType(resourceModalLinkType);
        }

        function getResourceLinkTypeBadgeClass(linkType) {
            const normalized = String(linkType || 'unknown').trim().toLowerCase();
            if (normalized === 'magnet') return 'resource-card-type-badge resource-card-type-badge-magnet';
            if (normalized === '115share') return 'resource-card-type-badge resource-card-type-badge-115share';
            if (normalized === 'quark') return 'resource-card-type-badge resource-card-type-badge-quark';
            return 'resource-card-type-badge resource-card-type-badge-default';
        }

        function detectResourceLinkTypeByUrl(url) {
            return window.ResourceLinkTags.resolveActionType({ link_url: url });
        }

        function getEffectiveResourceLinkType(item) {
            return window.ResourceLinkTags.resolveActionType(item);
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
                const data = await window.MediaHubApi.postJson('/resource/quick_links/save', { quick_links: payload });
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
                void showAppPrompt('复制失败，请手动复制以下链接：', item.url);
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
            if (!(await showAppConfirm(`确认删除常用链接「${item.name || '未命名链接'}」吗？`))) return;
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

        function canOpenResourceImportLink(item) {
            const linkType = getEffectiveResourceLinkType(item);
            const linkUrl = String(item?.link_url || '').trim();
            return !!linkUrl && (
                linkType === 'magnet'
                || getResourceImportMode(item) === 'ed2k-direct'
                || getResourceImportMode(item) === 'ed2k-page'
                || isResourceShareLinkType(linkType)
            );
        }

        function canOpenResourceImport(item) {
            return getResourceLinkRecords(item).some(record => canOpenResourceImportLink(createResourceLinkActionItem(item, record)));
        }

        function canImportResource(item) {
            return getResourceImportCandidates(item).length > 0;
        }

        function getResourceImportLabel(item) {
            const records = getResourceLinkRecords(item);
            const importCandidates = getResourceImportCandidates(item);
            if (!records.length) return '暂无可导入链接';
            if (!importCandidates.length) return '暂不支持下载';
            if (importCandidates.length > 1) return '下载/转存';
            const linkType = getEffectiveResourceLinkType(importCandidates[0]);
            if (isResourceShareLinkType(linkType)) return '转存';
            if (
                linkType === 'magnet'
                || getResourceImportMode(item) === 'ed2k-direct'
                || getResourceImportMode(item) === 'ed2k-page'
            ) {
                return '下载';
            }
            return '暂不支持下载';
        }

        function getResourceCopyLabel(item) {
            return getResourceLinkRecords(item).length ? '复制链接' : '复制文案';
        }

        function findResourceItem(resourceId) {
            const target = Number(resourceId || 0);
            if (!target) return null;
            if (selectedResourceItem && Number(selectedResourceItem?.id || 0) === target) return selectedResourceItem;
            const direct = (resourceState.items || []).find(item => Number(item.id) === target);
            if (direct) return direct;
            for (const section of resourceState.channel_sections || []) {
                const found = getResourceSectionItems(section, '', { providerFilter: 'all' }).find(item => Number(item.id) === target);
                if (found) return found;
            }
            const searchKeyword = String(resourceState.search || '').trim();
            for (const section of resourceState.search_sections || []) {
                const found = getResourceSectionItems(section, searchKeyword, { providerFilter: 'all' }).find(item => Number(item.id) === target);
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

        function normalizeResourceItemStatusFromJob(status) {
            const normalized = String(status || '').trim().toLowerCase();
            if (normalized === 'running') return 'importing';
            if (normalized === 'pending') return 'queued';
            if (['queued', 'importing', 'submitted', 'completed', 'failed'].includes(normalized)) return normalized;
            return '';
        }

        function buildResourceItemStatusByJob(jobs = [], activeJobs = []) {
            const statusByResourceId = new Map();
            [...(Array.isArray(jobs) ? jobs : []), ...(Array.isArray(activeJobs) ? activeJobs : [])].forEach((job) => {
                const resourceId = Number(job?.resource_id || 0) || 0;
                if (!resourceId || statusByResourceId.has(resourceId)) return;
                const status = normalizeResourceItemStatusFromJob(job?.status || '');
                if (status) statusByResourceId.set(resourceId, status);
            });
            return statusByResourceId;
        }

        function applyResourceJobStatusesToItems(items = [], statusByResourceId = new Map()) {
            if (!statusByResourceId.size || !Array.isArray(items)) return items;
            let changed = false;
            const nextItems = items.map((item) => {
                const resourceId = Number(item?.id || 0) || 0;
                const status = statusByResourceId.get(resourceId);
                if (!resourceId || !status || String(item?.status || '') === status) return item;
                changed = true;
                return { ...item, status };
            });
            return changed ? nextItems : items;
        }

        function applyResourceJobStatusesToSections(sections = [], statusByResourceId = new Map()) {
            if (!statusByResourceId.size || !Array.isArray(sections)) return sections;
            let changed = false;
            const nextSections = sections.map((section) => {
                const items = Array.isArray(section?.items) ? section.items : [];
                const nextItems = applyResourceJobStatusesToItems(items, statusByResourceId);
                if (nextItems === items) return section;
                changed = true;
                return { ...section, items: nextItems };
            });
            return changed ? nextSections : sections;
        }

        function syncResourceSectionsWithSources(sections, sources, options = {}) {
            const usageMode = String(options?.usageMode || 'search').trim().toLowerCase() === 'sync' ? 'sync' : 'search';
            const sourceIndex = new Map();
            (Array.isArray(sources) ? sources : []).forEach(source => {
                const channelId = typeof getResourceSourceChannelId === 'function'
                    ? getResourceSourceChannelId(source)
                    : normalizeTelegramChannelIdInput(source?.channel_id || source?.channel || source?.id || source?.url || '');
                if (!channelId || sourceIndex.has(channelId)) return;
                sourceIndex.set(channelId, source);
            });
            return (Array.isArray(sections) ? sections : [])
                .map(section => {
                    const sectionType = String(section?.section_type || '').trim().toLowerCase();
                    if (sectionType === 'pansou') {
                        return {
                            ...section,
                            name: section?.name || '盘搜结果',
                            section_type: 'pansou',
                            channel_id: 'pansou',
                            enabled: true
                        };
                    }
                    if (!sourceIndex.size) return null;
                    const channelId = normalizeTelegramChannelIdInput(section?.channel_id || '');
                    if (!channelId || !sourceIndex.has(channelId)) return null;
                    const source = sourceIndex.get(channelId) || {};
                    return {
                        ...section,
                        name: source.name || section?.name || channelId,
                        channel_id: channelId,
                        url: source.url || section?.url || '',
                        usage: normalizeResourceSourceUsage(source),
                        enabled: usageMode === 'sync'
                            ? isResourceSourceSyncEnabled(source)
                            : isResourceSourceSearchEnabled(source),
                        sync_enabled: isResourceSourceSyncEnabled(source),
                        search_enabled: isResourceSourceSearchEnabled(source)
                    };
                })
                .filter(Boolean);
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
            const canProbeMore = !!fallbackBefore && sectionItems.length >= 10;
            return {
                key: pagingKey,
                loading: !!resourceChannelLoadingMore[pagingKey],
                nextBefore: String(resourceChannelNextBefore[pagingKey] || section?.next_before || fallbackBefore || '').trim(),
                noMore: Object.prototype.hasOwnProperty.call(resourceChannelNoMore, pagingKey)
                    ? !!resourceChannelNoMore[pagingKey]
                    : !(sectionHasMore || canProbeMore),
            };
        }

        function resetResourceChannelPagingKeys(pagingKeys, { clearLoadedItems = true } = {}) {
            (Array.isArray(pagingKeys) ? pagingKeys : []).forEach(rawKey => {
                const key = String(rawKey || '').trim();
                if (!key) return;
                if (clearLoadedItems) delete resourceChannelExtraItems[key];
                delete resourceChannelLoadingMore[key];
                delete resourceChannelNextBefore[key];
                delete resourceChannelNoMore[key];
            });
        }

        function getResourceSectionItems(section, searchKeyword = '', options = {}) {
            const channelId = normalizeTelegramChannelIdInput(section?.channel_id || '');
            const pagingKey = getResourceSectionPagingKey(channelId, searchKeyword);
            const providerFilter = normalizeResourceProviderFilter(
                Object.prototype.hasOwnProperty.call(options || {}, 'providerFilter')
                    ? options.providerFilter
                    : (resourceProviderFilter || resourceState.provider_filter || 'all')
            );
            return dedupeResourceItems([
                ...(Array.isArray(section?.items) ? section.items : []),
                ...(Array.isArray(resourceChannelExtraItems[pagingKey]) ? resourceChannelExtraItems[pagingKey] : [])
            ])
                .filter(item => resourceItemMatchesProviderFilter(item, providerFilter))
                .sort((a, b) => getResourceItemSortScore(b) - getResourceItemSortScore(a));
        }

        function getResourceVisibleSections(sections, searchKeyword = '') {
            return (Array.isArray(sections) ? sections : [])
                .filter(section => section?.enabled !== false)
                .filter(section => getResourceSectionItems(section, searchKeyword).length > 0);
        }

        function countResourceVisibleSectionItems(sections, searchKeyword = '') {
            return getResourceVisibleSections(sections, searchKeyword)
                .reduce((sum, section) => sum + getResourceSectionItems(section, searchKeyword).length, 0);
        }

        function normalizeResourceStatusForDisplay(status) {
            const normalized = String(status || '').trim().toLowerCase();
            if (normalized === 'pending') return 'queued';
            if (normalized === 'running') return 'importing';
            return normalized || 'new';
        }

        function mergeResourceJobRecords(primaryJobs = [], secondaryJobs = []) {
            const seen = new Set();
            return [...(Array.isArray(primaryJobs) ? primaryJobs : []), ...(Array.isArray(secondaryJobs) ? secondaryJobs : [])]
                .filter((job, index) => {
                    const jobId = Number(job?.id || 0) || 0;
                    const key = jobId > 0 ? `id:${jobId}` : `fallback:${String(job?.title || '')}:${index}`;
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                });
        }

        function findMatchingResourceJob(item) {
            const itemKeys = uniquePreserveOrder([
                String(item?.source_post_id || item?.extra?.source_post_id || '').trim() ? `post:${String(item?.source_post_id || item?.extra?.source_post_id || '').trim()}` : '',
                String(item?.message_url || '').trim() ? `msg:${String(item?.message_url || '').trim()}` : '',
                String(item?.link_url || '').trim() ? `link:${String(item?.link_url || '').trim()}` : ''
            ].filter(Boolean));
            if (!itemKeys.length) return null;
            const jobs = Array.isArray(resourceState.jobs) ? resourceState.jobs : [];
            const activeJobs = Array.isArray(resourceState.active_jobs) ? resourceState.active_jobs : [];
            for (const job of mergeResourceJobRecords(jobs, activeJobs)) {
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

        function appendResourceBoardStatusSignatureParts(items = [], scope = '', parts = []) {
            (Array.isArray(items) ? items : []).forEach((item, index) => {
                const identity = getResourceItemIdentity(item || {}) || `index:${index}`;
                parts.push(`${scope}:${identity}:${getResourceDisplayStatus(item)}`);
            });
            return parts;
        }

        function buildResourceBoardStatusSignature() {
            const parts = [];
            const searchKeyword = String(resourceState.search || '').trim();
            appendResourceBoardStatusSignatureParts(resourceState.items || [], 'items', parts);
            (Array.isArray(resourceState.channel_sections) ? resourceState.channel_sections : []).forEach((section, index) => {
                appendResourceBoardStatusSignatureParts(
                    getResourceSectionItems(section, '', { providerFilter: 'all' }),
                    `channel:${section?.channel_id || index}`,
                    parts
                );
            });
            (Array.isArray(resourceState.search_sections) ? resourceState.search_sections : []).forEach((section, index) => {
                appendResourceBoardStatusSignatureParts(
                    getResourceSectionItems(section, searchKeyword, { providerFilter: 'all' }),
                    `search:${section?.channel_id || index}`,
                    parts
                );
            });
            return parts.sort().join('|');
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
            if (resourcePosterFailedProxyUrls.has(proxyUrl)) {
                return `<div class="resource-poster resource-placeholder">${sourceLabel}</div>`;
            }
            return `
                <div class="relative">
                    <img src="${escapeHtml(proxyUrl)}" data-proxy-url="${escapeHtml(proxyUrl)}" alt="${title}" class="resource-poster" loading="lazy" onerror="markResourcePosterLoadFailed(this)">
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

        function buildResourceSearchMatchSnippet(item) {
            const keyword = String(resourceState.search || '').trim();
            const match = item?.search_match && typeof item.search_match === 'object' ? item.search_match : {};
            const snippet = String(match?.snippet || '').trim();
            if (!keyword || !snippet) return '';
            const label = String(match?.field_label || '匹配').trim() || '匹配';
            return `<span class="resource-card-match-label">${escapeHtml(label)}命中：</span>${escapeHtml(snippet)}`;
        }

        function buildResourceDescription(item) {
            const matchSnippet = buildResourceSearchMatchSnippet(item);
            if (matchSnippet) return matchSnippet;
            const raw = String(item?.raw_text || item?.title || '').replace(/\s+/g, ' ').trim();
            return escapeHtml(raw || '暂无描述信息');
        }

        function buildResourceCard(item) {
            const linkRecords = getResourceLinkRecords(item);
            const displayTypes = [...new Set(linkRecords.map(record => getResourceDisplayLinkType(record)))];
            const importOpenable = getResourceImportCandidates(item).length > 0;
            const importClass = importOpenable ? 'resource-card-action-primary' : 'resource-card-action-secondary resource-card-action-disabled';
            const copyDisabled = linkRecords.length || String(item?.raw_text || item?.title || '').trim() ? '' : 'resource-card-action-disabled';
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
                                ${displayTypes.map(displayType => `<span class="${escapeHtml(getResourceDisplayLinkTypeBadgeClass(displayType))}">${escapeHtml(getResourceDisplayLinkTypeLabel(displayType))}</span>`).join('')}
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
                        <button type="button" data-resource-action="import" data-resource-id="${item.id}" class="${importClass}" ${importOpenable ? '' : 'disabled'}>${escapeHtml(getResourceImportLabel(item))}</button>
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
                    const label = `${source.name || `频道 ${index + 1}`} (${getResourceSourceUsageLabel(source)})`;
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
            const provider = getCurrentResourceProvider();
            const mountPath = normalizeRemotePathInput(getMountPrefixByProvider(provider) || `/${provider}`);
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

        function isResourceEd2kImportActive() {
            return resourceModalMode === 'import' && !!resourceEd2kState?.active;
        }

        function getResourceImportTargetSavepath(savepath = '') {
            const parentSavepath = normalizeRelativePathInput(savepath);
            if (!isResourceEd2kImportActive()) return parentSavepath;
            const createFolder = resourceEd2kState.createFolder !== false;
            const folderName = String(
                document.getElementById('resource-ed2k-folder-name')?.value
                || resourceEd2kState.folderName
                || ''
            ).trim();
            if (window.ResourceEd2kImport?.buildTargetSavepath) {
                return window.ResourceEd2kImport.buildTargetSavepath(parentSavepath, folderName, createFolder);
            }
            return createFolder ? joinRelativePathInput(parentSavepath, folderName) : parentSavepath;
        }

        function syncResourceSavepathPreview(savepath = '') {
            const previewEl = document.getElementById('resource_job_savepath_preview');
            if (!previewEl) return;
            const normalizedSavepath = getResourceImportTargetSavepath(savepath);
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
            if (isResourceEd2kImportActive()) {
                const selectedCount = Array.isArray(resourceEd2kState.selectedItemIds)
                    ? resourceEd2kState.selectedItemIds.length
                    : 0;
                return selectedCount ? `当前选择 ${selectedCount} 个 ED2K 文件。` : '当前未选择 ED2K 文件。';
            }
            if (isResourceBatchImportMode()) {
                const batchCount = getResourceBatchMagnetItems().length;
                return `当前为批量模式，将按同一保存目录依次导入 ${batchCount} 条磁力链接。`;
            }
            if (!isCurrentResource115Share()) return '当前资源会按完整内容导入。';
            if (!isLinkTypeCookieConfigured(linkType)) return `配置 ${providerLabel} 认证信息后可浏览分享目录并选择具体内容。`;
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
            const providerLabel = getCurrentResourceProviderLabel();
            const providerMeta = (window.providerMeta || []).find(m => m.name === provider);
            const providerSupportsMonitor = !!providerMeta?.supports_monitor;

            if (!provider) {
                hintEl.innerText = '当前资源无法确定保存网盘，请重新打开导入窗口。';
                return;
            }

            const parentSavepath = savepath || document.getElementById('resource_job_savepath')?.value || '';
            const match = resolveResourceMonitorTaskMatch(getResourceImportTargetSavepath(parentSavepath));
            if (!match.savepath) {
                hintEl.innerText = `请选择一个非根目录的${providerLabel}保存目录。`;
                return;
            }

            const selectionHint = getResourceImportSelectionHint();
            if (!providerSupportsMonitor) {
                hintEl.innerText = `${selectionHint} 当前为${providerLabel}独立链路，提交后不会联动文件夹监控刷新。`.trim();
                return;
            }
            const monitorHint = match.taskName
                ? `当前保存路径会映射到 ${providerLabel} 路径 ${match.fullPath}，命中文件夹监控任务“${match.taskName}”，保存完成后会自动触发生成 strm。`
                : `当前保存路径会映射到 ${providerLabel} 路径 ${match.fullPath}，未命中文件夹监控任务，保存后不会自动生成 strm。`;
            hintEl.innerText = `${selectionHint} ${monitorHint}`.trim();
        }

        function syncResourceMonitorTaskOptions(savepath = '') {
            const hiddenInput = document.getElementById('resource_job_monitor_task');
            const displayInput = document.getElementById('resource_job_monitor_task_display');
            const delayInput = document.getElementById('resource_job_refresh_delay_seconds');
            if (!hiddenInput || !displayInput || !delayInput) return;
            const provider = getCurrentResourceProvider();
            const providerLabel = getResourceProviderLabel(provider);
            const providerMeta = (window.providerMeta || []).find(m => m.name === provider);
            const providerSupportsMonitor = !!providerMeta?.supports_monitor;

            if (!provider) {
                hiddenInput.value = '';
                displayInput.textContent = '无法确定保存网盘';
                delayInput.disabled = false;
                syncResourceSavepathPreview('');
                renderResourceImportBehaviorHint('');
                renderResourceImportSummary();
                return;
            }

            const targetSavepath = getResourceImportTargetSavepath(savepath);
            const match = resolveResourceMonitorTaskMatch(targetSavepath);
            syncResourceSavepathPreview(savepath);

            if (!match.savepath) {
                hiddenInput.value = '';
                displayInput.textContent = '请先选择保存目录';
                delayInput.disabled = false;
                renderResourceImportBehaviorHint('');
                return;
            }

            if (!providerSupportsMonitor) {
                hiddenInput.value = '';
                displayInput.textContent = `${providerLabel}链路不绑定监控`;
                delayInput.value = '0';
                delayInput.disabled = true;
                renderResourceImportBehaviorHint(savepath);
                renderResourceImportSummary();
                return;
            }

            hiddenInput.value = match.taskName;

            if (match.taskName) {
                displayInput.textContent = match.taskName;
            } else {
                displayInput.textContent = '当前目录不自动触发';
            }
            delayInput.disabled = false;

            renderResourceImportBehaviorHint(savepath);
            renderResourceImportSummary();
        }

        function syncResourceProviderUI() {
            const provider = getCurrentResourceProvider();
            const providerLabel = getCurrentResourceProviderLabel();
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

            if (isResourceEd2kImportActive()) {
                const selectedCount = Array.isArray(resourceEd2kState.selectedItemIds)
                    ? resourceEd2kState.selectedItemIds.length
                    : 0;
                selectionText = resourceEd2kState.loading ? '解析中' : `${selectedCount} 个文件`;
            }

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

            const currentItems = getResourceSectionItems(section, keyword, { providerFilter: 'all' });
            const meta = getResourceSectionPagingMeta(section, keyword);
            const before = String(meta.nextBefore || getResourceItemPostCursor(currentItems[currentItems.length - 1]) || '').trim();

            resourceChannelLoadingMore = {
                ...resourceChannelLoadingMore,
                [pagingKey]: true
            };
            renderResourceBoard();

            try {
                const data = await window.MediaHubApi.postJson('/resource/channels/more', {
                    channel_id: normalizedChannelId,
                    before,
                    limit: 10,
                    query: keyword,
                    provider_filter: 'all'
                });

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
                    [pagingKey]: !(Boolean(data.has_more) && !!String(data.next_before || '').trim())
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
                        ? dedupeResourceItems(nextSectionPool.flatMap(item => getResourceSectionItems(item, keyword, { providerFilter: 'all' })))
                        : resourceState.items,
                    channel_sections: keyword ? resourceState.channel_sections : nextSectionPool,
                    search_sections: keyword ? nextSectionPool : resourceState.search_sections,
                    stats: keyword
                        ? {
                            ...(resourceState.stats || {}),
                            filtered_item_count: countResourceVisibleSectionItems(nextSectionPool, keyword)
                        }
                        : resourceState.stats
                };
                const itemCountEl = document.getElementById('resource-item-count');
                if (itemCountEl) itemCountEl.innerText = String(Number(resourceState?.stats?.item_count || 0));
                renderResourceBoard();
                return data;
            } catch (e) {
                showToast(`获取更多资源失败：${e.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
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
            const sectionType = String(section?.section_type || '').trim().toLowerCase();
            const isPansouSection = sectionType === 'pansou';
            const sectionItems = getResourceSectionItems(section, keyword);
            const pagingMeta = getResourceSectionPagingMeta(section, keyword);
            const normalizedChannelId = normalizeTelegramChannelIdInput(section?.channel_id || '');
            const canManageSection = !!normalizedChannelId && !isPansouSection;
            const canLoadMoreSection = !isPansouSection;
            const shownCount = sectionItems.length;
            const primaryBadge = isSearchSection
                ? `命中 ${shownCount}`
                : `显示 ${shownCount}`;
            const secondaryBadge = isSearchSection
                ? (isPansouSection ? '外部搜索' : `${escapeHtml(String(section?.pages_scanned || 0))} 页`)
                : `缓存 ${escapeHtml(String(section.item_count || (section.items || []).length || 0))}`;
            const latestPublishedAt = String(section?.latest_published_at || section?.channel_profile?.latest_published_at || '').trim();
            const subtleText = isSearchSection
                ? (isPansouSection ? `关键词「${escapeHtml(keyword)}」 · 类型 ${escapeHtml(getResourceProviderFilterLabel())}` : `关键词「${escapeHtml(keyword)}」`)
                : `最近资源 ${escapeHtml(latestPublishedAt ? formatTimeText(latestPublishedAt) : '--')} · 最近同步 ${escapeHtml(formatResourceSyncTime(section.last_sync_at))}`;
            const footerText = isSearchSection
                ? (isPansouSection ? `当前已显示 ${escapeHtml(String(shownCount))} 条盘搜结果。` : `当前已显示 ${escapeHtml(String(shownCount))} 条命中结果。`)
                : `当前已显示 ${escapeHtml(String(shownCount))} 条，频道缓存 ${escapeHtml(String(section.item_count || 0))} 条。`;
            const emptyText = isSearchSection
                ? (isPansouSection ? '盘搜暂时没有返回可导入结果。' : '这个频道暂时没有可展示的命中结果。')
                : '这个频道还没有同步到资源，稍后再试一次同步。';

            return `
                <section class="resource-section-card" data-collapsed="${isResourceSectionCollapsed(section.channel_id) ? 'true' : 'false'}">
                    <div class="resource-section-header">
                        <button type="button" data-resource-section-toggle="${escapeHtml(section.channel_id || '')}" class="resource-section-header-main min-w-0 flex-1 text-left bg-transparent border-none p-0">
                            <div class="resource-section-title-row">
                                <h4 class="resource-section-title">${escapeHtml(section.name || section.channel_id || '未命名频道')}</h4>
                                ${isPansouSection ? '<span class="resource-section-chip resource-section-chip-accent">PanSou</span>' : `<span class="resource-section-chip">@${escapeHtml(section.channel_id || '--')}</span>`}
                                <span class="resource-section-chip resource-section-chip-accent">${primaryBadge}</span>
                                <span class="resource-section-chip">${secondaryBadge}</span>
                                ${!isSearchSection && section.last_error ? '<span class="resource-section-chip resource-section-chip-warn">同步异常</span>' : ''}
                            </div>
                            <div class="resource-section-subtle">${subtleText}</div>
                        </button>
                        <div class="resource-section-actions">
                            ${canManageSection ? `<button type="button" data-resource-section-manage="${escapeHtml(normalizedChannelId)}" class="resource-section-manage-btn">管理</button>` : ''}
                            ${section.url ? `<a href="${escapeHtml(section.url || '#')}" target="_blank" rel="noopener noreferrer" class="resource-section-link">${isPansouSection ? '打开盘搜' : '打开频道'}</a>` : ''}
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
                                ${(!canLoadMoreSection) || pagingMeta.loading || pagingMeta.noMore ? 'disabled' : ''}
                            >${pagingMeta.loading
                                ? '获取中...'
                                : ((!canLoadMoreSection) ? '盘搜结果已全部显示' : (pagingMeta.noMore ? '没有更多资源了' : '获取更多资源'))
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
            const strmReady = !!setupStatus.strm_ready;
            const steps = [
                { label: '配置 115 与播放', done: strmReady, tab: 'settings', meta: '播放链接基础配置' },
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

        function setResourceBoardHtml(container, html) {
            const nextHtml = String(html || '');
            if (container.__resourceBoardHtml === nextHtml && container.innerHTML) return;
            container.innerHTML = nextHtml;
            container.__resourceBoardHtml = nextHtml;
        }

        function formatResourceSearchDuration(durationMs, label = '耗时') {
            const value = Number(durationMs || 0);
            if (!Number.isFinite(value) || value <= 0) return `${label} --`;
            if (value < 1000) return `${label} ${Math.max(1, Math.round(value))} ms`;
            return `${label} ${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} 秒`;
        }

        function formatResourceSearchLatency(latencyMs) {
            const value = Number(latencyMs || 0);
            if (!Number.isFinite(value) || value <= 0) return 'TG 延迟检测中';
            return `TG 延迟 ${Math.max(1, Math.round(value))} ms`;
        }

        function getResourceActiveSearchRuntime() {
            return resourceActiveSearchRuntime && typeof resourceActiveSearchRuntime === 'object'
                ? resourceActiveSearchRuntime
                : null;
        }

        function updateResourceActiveSearchRuntime(nextState = {}) {
            const current = getResourceActiveSearchRuntime() || {};
            resourceActiveSearchRuntime = {
                ...current,
                ...(nextState && typeof nextState === 'object' ? nextState : {}),
            };
            return resourceActiveSearchRuntime;
        }

        function clearResourceActiveSearchRuntime(searchId = '') {
            const active = getResourceActiveSearchRuntime();
            if (!active) return;
            const expectedSearchId = String(searchId || '').trim();
            if (expectedSearchId && String(active.searchId || '').trim() && String(active.searchId || '').trim() !== expectedSearchId) return;
            resourceActiveSearchRuntime = null;
        }

        function buildResourceSearchRunningStatusText({
            source = resourceSearchSource,
            keyword = '',
            providerFilter = resourceProviderFilter,
            latencyMs = 0,
            latencyText = '',
        } = {}) {
            const normalizedSource = normalizeResourceSearchSource(source);
            const keywordText = String(keyword || resourceState?.search || '').trim() || '...';
            const normalizedProviderFilter = normalizeResourceProviderFilter(providerFilter);
            const providerLabel = getResourceProviderFilterLabel(normalizedProviderFilter);
            const parts = [
                normalizedSource === 'pansou' ? '盘搜中' : '频道搜索中',
                `关键词「${keywordText}」`,
            ];
            if (normalizedProviderFilter !== 'all') parts.push(`类型 ${providerLabel}`);
            if (normalizedSource === 'tg') {
                parts.push(String(latencyText || '').trim() || formatResourceSearchLatency(latencyMs));
            } else {
                parts.push('已开始');
            }
            return parts.join(' · ');
        }

        function getResourceSearchRunningHintText(fallback = {}) {
            const active = {
                ...(fallback && typeof fallback === 'object' ? fallback : {}),
                ...(getResourceActiveSearchRuntime() || {}),
            };
            const keywordText = String(active.keyword || resourceState?.search || '').trim() || '...';
            if (active.directImportMode) {
                return `资源识别执行中 · 关键词「${keywordText}」 · 已开始`;
            }
            return buildResourceSearchRunningStatusText({
                source: active.source || resourceSearchSource,
                keyword: keywordText,
                providerFilter: active.providerFilter || resourceProviderFilter,
                latencyMs: Number(active.latencyMs || 0),
                latencyText: String(active.latencyText || '').trim(),
            });
        }

        function getResourceSearchResultCount(state = resourceState, keyword = '') {
            const sections = Array.isArray(state?.search_sections) ? state.search_sections : [];
            return countResourceVisibleSectionItems(sections, keyword);
        }

        function buildResourceSearchStatusText({
            phase = 'completed',
            source = resourceSearchSource,
            keyword = '',
            providerFilter = resourceProviderFilter,
            state = resourceState,
            durationMs = 0,
            latencyMs = 0,
            latencyText = '',
        } = {}) {
            const normalizedSource = normalizeResourceSearchSource(source);
            const meta = state?.search_meta && typeof state.search_meta === 'object' ? state.search_meta : {};
            const sourceLabel = getResourceSearchSourceLabel(normalizedSource);
            const keywordText = String(keyword || state?.search || '').trim() || '...';
            const providerLabel = getResourceProviderFilterLabel(providerFilter);
            const errors = Array.isArray(meta.errors) ? meta.errors : [];
            const searchedSources = Number(meta.searched_sources || 0);
            const resultCount = getResourceSearchResultCount(state, keywordText);
            const normalizedPhase = String(phase || '').trim().toLowerCase();
            const phaseLabel = normalizedPhase === 'running'
                ? '执行中'
                : (normalizedPhase === 'failed' ? '失败' : (normalizedPhase === 'cancelled' ? '已中断' : '完成'));

            if (normalizedPhase === 'running') {
                return buildResourceSearchRunningStatusText({
                    source: normalizedSource,
                    keyword: keywordText,
                    providerFilter,
                    latencyMs,
                    latencyText,
                });
            }

            const parts = [
                `${sourceLabel}${phaseLabel}`,
                `关键词「${keywordText}」`,
                `类型 ${providerLabel}`,
            ];

            if (normalizedPhase === 'completed') parts.push(`命中 ${resultCount} 条`);
            if (normalizedSource === 'tg' && searchedSources > 0) parts.push(`检索 ${searchedSources} 个来源`);
            if (errors.length) parts.push(`异常 ${errors.length} 个来源`);
            if (normalizedSource === 'tg') {
                const finalLatencyMs = Number(latencyMs || meta.tg_latency_ms || resourceTgLastLatencyMs || 0);
                parts.push(finalLatencyMs > 0 ? formatResourceSearchLatency(finalLatencyMs) : 'TG 延迟 --');
            }
            if (normalizedSource === 'pansou') {
                const pansouElapsedMs = Number(meta.pansou_elapsed_ms || 0);
                parts.push(formatResourceSearchDuration(pansouElapsedMs || durationMs || meta.client_elapsed_ms, 'PanSou 耗时'));
            } else {
                parts.push(formatResourceSearchDuration(durationMs || meta.client_elapsed_ms, normalizedPhase === 'cancelled' ? '已耗时' : '耗时'));
            }
            return parts.join(' · ');
        }

        function buildPansouIdleState() {
            const providerLabel = getResourceProviderFilterLabel(resourceProviderFilter || resourceState.provider_filter);
            return `
                <div class="resource-pansou-idle" role="status" aria-live="polite">
                    <div class="resource-pansou-idle-main">
                        <div class="resource-pansou-idle-kicker">PanSou</div>
                        <div class="resource-pansou-idle-title">输入关键词后搜索盘搜</div>
                        <div class="resource-pansou-idle-copy">盘搜不会在空关键词时自动请求；当前类型筛选为 ${escapeHtml(providerLabel)}。</div>
                    </div>
                    <div class="resource-pansou-idle-meta">下方仍显示已同步频道的资源概览</div>
                </div>
            `;
        }

        function buildResourceOverviewDivider() {
            return `
                <div class="resource-overview-divider">
                    <div>
                        <div class="resource-overview-title">频道资源概览</div>
                        <div class="resource-overview-copy">来自同步+搜索频道的本地缓存，不是盘搜结果。</div>
                    </div>
                </div>
            `;
        }

        function renderResourceBoard() {
            const container = document.getElementById('resource-board');
            if (!container) return;
            const runningKeyword = String(document.getElementById('resource-search-input')?.value || '').trim();
            const runningHintText = resourceSearchBusy
                ? getResourceSearchRunningHintText({
                    keyword: runningKeyword || resourceState.search || '',
                    source: resourceSearchSource || resourceState.search_source || 'tg',
                    providerFilter: resourceProviderFilter || resourceState.provider_filter || 'all',
                    latencyMs: Number(resourceTgLastLatencyMs || 0),
                })
                : '';

            if (!resourceStateHydrated) {
                resourceBoardHintText = '';
                setResourceBoardHtml(container, '<div class="rounded-2xl border border-slate-700 p-8 text-center text-slate-400 text-sm">正在加载首页配置，请稍候...</div>');
                renderResourceBoardHint();
                return;
            }

            const activeKeyword = String(resourceState.search || '').trim();
            const isSearchMode = !!activeKeyword;
            const isPansouIdle = !isSearchMode && normalizeResourceSearchSource(resourceState.search_source || resourceSearchSource) === 'pansou';
            const sections = getResourceVisibleSections(resourceState.channel_sections || [], '');
            if (isSearchMode) {
                const searchSections = getResourceVisibleSections(resourceState.search_sections || [], activeKeyword);
                const searchErrors = Array.isArray(resourceState?.search_meta?.errors) ? resourceState.search_meta.errors : [];
                resourceBoardHintText = resourceSearchBusy
                    ? runningHintText
                    : buildResourceSearchStatusText({
                        phase: resourceState?.search_meta?.client_phase || 'completed',
                        source: resourceState.search_source || resourceSearchSource,
                        keyword: activeKeyword,
                        providerFilter: resourceProviderFilter || resourceState.provider_filter || 'all',
                        durationMs: Number(resourceState?.search_meta?.client_elapsed_ms || 0),
                        latencyMs: Number(resourceState?.search_meta?.tg_latency_ms || resourceTgLastLatencyMs || 0),
                    });
                if (!searchSections.length) {
                    const emptyCopy = normalizeResourceSearchSource(resourceState.search_source || resourceSearchSource) === 'pansou'
                        ? '盘搜没有返回当前类型的可导入结果。请检查 PanSou 配置，或换一个关键词再试。'
                        : '没有在参与搜索的订阅频道里找到匹配内容。可以调整频道用途，或直接粘贴 magnet / 常见网盘分享链接进入识别。';
                    setResourceBoardHtml(container, `<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">${escapeHtml(emptyCopy)}</div>`);
                    renderResourceBoardHint();
                    return;
                }
                const errorNote = searchErrors.length
                    ? `<div class="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-100">${escapeHtml(`以下频道本次未返回结果：${searchErrors.map(item => item?.name || item?.channel_id || '未命名频道').join('、')}`)}</div>`
                    : '';
                setResourceBoardHtml(container, `${errorNote}${errorNote ? '<div class="h-4"></div>' : ''}${searchSections.map(section => buildResourceSectionCard(section, { searchKeyword: activeKeyword })).join('')}`);
                renderResourceBoardHint();
                return;
            }

            resourceBoardHintText = resourceSearchBusy ? runningHintText : '';
            if (!sections.length) {
                const hasAnyEnabledSection = (resourceState.channel_sections || []).some(section => section?.enabled !== false);
                const emptyText = hasAnyEnabledSection && normalizeResourceProviderFilter(resourceProviderFilter || resourceState.provider_filter) !== 'all'
                    ? `当前类型（${getResourceProviderFilterLabel(resourceProviderFilter || resourceState.provider_filter)}）暂无可展示的频道资源。`
                    : '还没有可展示的频道资源。先在“参数配置”里添加频道，并执行一次同步即可。';
                const emptyChannelHtml = `<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">${escapeHtml(emptyText)}</div>`;
                setResourceBoardHtml(container, `${isPansouIdle ? buildPansouIdleState() : ''}${isPansouIdle ? '<div class="h-3"></div>' : ''}${emptyChannelHtml}`);
                renderResourceBoardHint();
                return;
            }

            const overviewHtml = sections.map(section => buildResourceSectionCard(section, { searchKeyword: '' })).join('');
            setResourceBoardHtml(
                container,
                isPansouIdle
                    ? `${buildPansouIdleState()}<div class="h-3"></div>${buildResourceOverviewDivider()}${overviewHtml}`
                    : overviewHtml
            );
            renderResourceBoardHint();
        }

        function renderHeavyResourceSurfaces() {
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

        function scheduleResourceHeavyRender(defer = false) {
            if (defer && window.requestAnimationFrame) {
                if (resourceHeavyRenderRafId !== null && window.cancelAnimationFrame) {
                    window.cancelAnimationFrame(resourceHeavyRenderRafId);
                }
                resourceHeavyRenderRafId = window.requestAnimationFrame(() => {
                    resourceHeavyRenderRafId = null;
                    renderHeavyResourceSurfaces();
                });
                return;
            }
            if (resourceHeavyRenderRafId !== null && window.cancelAnimationFrame) {
                window.cancelAnimationFrame(resourceHeavyRenderRafId);
                resourceHeavyRenderRafId = null;
            }
            renderHeavyResourceSurfaces();
        }

        function normalizeResourceStatCount(value, fallback = 0) {
            const parsed = Number(value);
            if (Number.isFinite(parsed) && parsed >= 0) return parsed;
            const fallbackParsed = Number(fallback);
            return Number.isFinite(fallbackParsed) && fallbackParsed >= 0 ? fallbackParsed : 0;
        }

        function renderResourceSourceStats() {
            const stats = resourceState.stats || {};
            const meta = resourceState.search_meta && typeof resourceState.search_meta === 'object'
                ? resourceState.search_meta
                : {};
            const isSearchMode = !!String(resourceState.search || '').trim();
            const labelEl = document.getElementById('resource-source-count-label');
            const countEl = document.getElementById('resource-source-count');
            const itemCountEl = document.getElementById('resource-item-count');
            if (labelEl) labelEl.innerText = isSearchMode ? '搜索源' : '同步源';
            if (countEl) {
                const hasSearchedSources = Object.prototype.hasOwnProperty.call(meta, 'searched_sources');
                const rawCount = isSearchMode
                    ? (hasSearchedSources ? meta.searched_sources : (stats.search_source_count ?? stats.source_count ?? resourceState.sources.length ?? 0))
                    : (stats.sync_source_count ?? stats.source_count ?? resourceState.sources.length ?? 0);
                countEl.innerText = String(normalizeResourceStatCount(rawCount));
            }
            if (itemCountEl) itemCountEl.innerText = String(normalizeResourceStatCount(stats.item_count));
        }

        function applyResourceSourcesLocal(sources, options = {}) {
            const nextSources = Array.isArray(sources) ? sources : [];
            resourceState = {
                ...resourceState,
                sources: nextSources,
                stats: {
                    ...(resourceState.stats || {}),
                    source_count: nextSources.filter(source => isResourceSourceSyncEnabled(source)).length,
                    total_source_count: nextSources.length,
                    sync_source_count: nextSources.filter(source => isResourceSourceSyncEnabled(source)).length,
                    search_source_count: nextSources.filter(source => isResourceSourceSearchEnabled(source)).length,
                    disabled_source_count: nextSources.filter(source => !isResourceSourceSearchEnabled(source)).length,
                },
                channel_sections: syncResourceSectionsWithSources(resourceState.channel_sections || [], nextSources, { usageMode: 'sync' }),
                search_sections: syncResourceSectionsWithSources(resourceState.search_sections || [], nextSources, { usageMode: 'search' }),
            };

            normalizeResourceSourceBulkSelections();
            syncResourceChannelPagingState();
            renderResourceSourceStats();
            syncResourceSourceSelect();
            renderResourceOnboardingCard();
            renderResourceSources();
            if (resourceChannelManageModalOpen) {
                const nextIndex = getResourceSourceIndexByChannelId(resourceChannelManageChannelId);
                resourceChannelManageSourceIndex = nextIndex;
                if (nextIndex < 0) closeResourceChannelManageModal();
                else syncResourceChannelManageModalState();
            }
            scheduleResourceHeavyRender(!!options.deferHeavyRender);
        }

        function applyResourceState(data, options = {}) {
            if (!data) return;
            const projectedJobs = projectResourceJobsResponse(data, options);
            data = projectedJobs.data;
            const deferHeavyRender = !!options.deferHeavyRender;
            const compactUpdate = !!options.compactUpdate;
            const previousBoardStatusSignature = compactUpdate ? buildResourceBoardStatusSignature() : '';
            const previousChannelSync = resourceState.channel_sync || {};
            const nextSources = Array.isArray(data.sources) ? data.sources : (resourceState.sources || []);
            const nextQuickLinks = Array.isArray(data.quick_links) ? data.quick_links : (resourceState.quick_links || []);
            const nextFavoriteDirs = data.favorite_dirs && typeof data.favorite_dirs === 'object'
                ? normalizeResourceFavoriteDirsPayload(data.favorite_dirs)
                : normalizeResourceFavoriteDirsPayload(resourceState.favorite_dirs || {});
            const nextJobs = Array.isArray(data.jobs) ? data.jobs : (resourceState.jobs || []);
            const nextActiveJobs = Array.isArray(data.active_jobs) ? data.active_jobs : (resourceState.active_jobs || []);
            const nextJobStatusByResourceId = buildResourceItemStatusByJob(nextJobs, nextActiveJobs);
            const nextItems = applyResourceJobStatusesToItems(
                hydrateResourceItems(Array.isArray(data.items) ? data.items : (resourceState.items || [])),
                nextJobStatusByResourceId
            );
            const nextChannelSections = applyResourceJobStatusesToSections(
                syncResourceSectionsWithSources(
                    hydrateResourceSections(Array.isArray(data.channel_sections) ? data.channel_sections : (resourceState.channel_sections || [])),
                    nextSources,
                    { usageMode: 'sync' }
                ),
                nextJobStatusByResourceId
            );
            const nextSearchSections = applyResourceJobStatusesToSections(
                syncResourceSectionsWithSources(
                    hydrateResourceSections(Array.isArray(data.search_sections) ? data.search_sections : (resourceState.search_sections || [])),
                    nextSources,
                    { usageMode: 'search' }
                ),
                nextJobStatusByResourceId
            );
            const nextJobCounts = data.job_counts && typeof data.job_counts === 'object'
                ? data.job_counts
                : (resourceState.job_counts || {});
            const nextJobPagination = data.pagination && typeof data.pagination === 'object'
                ? data.pagination
                : (resourceState.job_pagination || {});
            const nextSearchSource = normalizeResourceSearchSource(data.search_source || resourceSearchSource || resourceState.search_source || 'tg');
            const nextProviderFilter = normalizeResourceProviderFilter(resourceProviderFilter || resourceState.provider_filter || data.provider_filter || 'all');
            const previousChannelSectionById = new Map(
                (Array.isArray(resourceState.channel_sections) ? resourceState.channel_sections : [])
                    .map(section => [normalizeTelegramChannelIdInput(section?.channel_id || ''), section])
                    .filter(([channelId]) => !!channelId)
            );
            const currentStats = resourceState.stats && typeof resourceState.stats === 'object' ? resourceState.stats : {};
            const incomingStats = data.stats && typeof data.stats === 'object' ? data.stats : {};
            const fallbackSyncSourceCount = nextSources.filter(source => isResourceSourceSyncEnabled(source)).length;
            const fallbackSearchSourceCount = nextSources.filter(source => isResourceSourceSearchEnabled(source)).length;
            const nextStats = {
                ...currentStats,
                ...incomingStats,
                source_count: Number(incomingStats.source_count ?? currentStats.source_count ?? fallbackSyncSourceCount ?? 0),
                total_source_count: Number(incomingStats.total_source_count ?? currentStats.total_source_count ?? nextSources.length ?? 0),
                sync_source_count: Number(incomingStats.sync_source_count ?? currentStats.sync_source_count ?? fallbackSyncSourceCount ?? 0),
                search_source_count: Number(incomingStats.search_source_count ?? currentStats.search_source_count ?? fallbackSearchSourceCount ?? 0),
                disabled_source_count: Number(incomingStats.disabled_source_count ?? currentStats.disabled_source_count ?? Math.max(0, nextSources.length - fallbackSearchSourceCount)),
                item_count: Number(incomingStats.item_count ?? currentStats.item_count ?? 0),
                filtered_item_count: Number(incomingStats.filtered_item_count ?? currentStats.filtered_item_count ?? nextItems.length ?? 0),
                total_job_count: Number(incomingStats.total_job_count ?? currentStats.total_job_count ?? 0),
                active_job_count: Number(incomingStats.active_job_count ?? currentStats.active_job_count ?? 0),
                completed_job_count: Number(incomingStats.completed_job_count ?? currentStats.completed_job_count ?? 0),
                failed_job_count: Number(incomingStats.failed_job_count ?? currentStats.failed_job_count ?? 0),
            };
            const feedPagingKeysToReset = [];
            nextChannelSections.forEach(section => {
                const channelId = normalizeTelegramChannelIdInput(section?.channel_id || '');
                if (!channelId) return;
                const previousSection = previousChannelSectionById.get(channelId);
                if (!previousSection) return;
                const previousSyncAt = Number(previousSection?.last_sync_at || 0);
                const nextSyncAt = Number(section?.last_sync_at || 0);
                if (nextSyncAt > 0 && nextSyncAt !== previousSyncAt) {
                    const pagingKey = getResourceSectionPagingKey(channelId, '');
                    if (pagingKey) feedPagingKeysToReset.push(pagingKey);
                }
            });
            resourceState = {
                ...resourceState,
                ...data,
                sources: nextSources,
                quick_links: nextQuickLinks,
                favorite_dirs: nextFavoriteDirs,
                items: nextItems,
                jobs: nextJobs,
                active_jobs: nextActiveJobs,
                job_counts: nextJobCounts,
                job_pagination: nextJobPagination,
                channel_sections: nextChannelSections,
                channel_profiles: data.channel_profiles && typeof data.channel_profiles === 'object'
                    ? data.channel_profiles
                    : (resourceState.channel_profiles || {}),
                subscription_channel_support: data.subscription_channel_support && typeof data.subscription_channel_support === 'object'
                    ? data.subscription_channel_support
                    : (resourceState.subscription_channel_support || {}),
                search_sections: nextSearchSections,
                last_syncs: data.last_syncs || resourceState.last_syncs || {},
                channel_sync: data.channel_sync && typeof data.channel_sync === 'object'
                    ? data.channel_sync
                    : (resourceState.channel_sync || {}),
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
                cookie_health: data.cookie_health && typeof data.cookie_health === 'object'
                    ? data.cookie_health
                    : (resourceState.cookie_health || null),
                stats: nextStats,
                search: typeof data.search === 'string' ? data.search : (resourceState.search || ''),
                search_source: nextSearchSource,
                provider_filter: nextProviderFilter,
                search_meta: data.search_meta || resourceState.search_meta || {}
            };
            const compactBoardStatusChanged = compactUpdate && previousBoardStatusSignature !== buildResourceBoardStatusSignature();
            resourceSearchSource = nextSearchSource;
            resourceProviderFilter = nextProviderFilter;
            if (data.cookie_health && typeof data.cookie_health === 'object') {
                applyCookieHealthState(data.cookie_health);
            } else {
                renderResourceCookieHint();
            }
            if (typeof handleResourceChannelSyncStateChange === 'function') {
                handleResourceChannelSyncStateChange(previousChannelSync, resourceState.channel_sync, { refreshOnComplete: compactUpdate });
            }
            if (!compactUpdate) {
                if (feedPagingKeysToReset.length) {
                    resetResourceChannelPagingKeys(feedPagingKeysToReset);
                }
                normalizeResourceSourceBulkSelections();
                syncResourceChannelPagingState();
                setResourceQuickLinks(nextQuickLinks, { render: true });
                void migrateResourceQuickLinksFromStorageIfNeeded(nextQuickLinks);
                if (selectedResourceId) {
                    const refreshedSelectedItem = findResourceItem(selectedResourceId);
                    if (refreshedSelectedItem) selectedResourceItem = refreshedSelectedItem;
                }
            }

            renderResourceSourceStats();
            syncResourceJobClearMenuState();
            if (data.cookie_health && typeof data.cookie_health === 'object') {
                renderResourceCookieHint();
            } else if (!compactUpdate) {
                renderResourceCookieHint();
            }
            if (!compactUpdate) {
                renderResourceSearchFilters();
                syncResourceSourceSelect();
                syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
                renderResourceFavoriteDirs();
                renderResourceOnboardingCard();
                renderResourceSources();
                if (resourceChannelManageModalOpen) {
                    const nextIndex = getResourceSourceIndexByChannelId(resourceChannelManageChannelId);
                    resourceChannelManageSourceIndex = nextIndex;
                    if (nextIndex < 0) closeResourceChannelManageModal();
                    else syncResourceChannelManageModalState();
                }
                scheduleResourceHeavyRender(deferHeavyRender);
            } else {
                renderResourceJobs();
                syncResourceJobModalTrigger();
                if (compactBoardStatusChanged && currentTab === 'resource') {
                    renderResourceBoard();
                } else {
                    renderResourceBoardHint();
                }
            }

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
            const channelSyncState = typeof normalizeResourceChannelSyncState === 'function'
                ? normalizeResourceChannelSyncState(resourceState.channel_sync)
                : (resourceState.channel_sync || {});
            const channelSyncActive = typeof isResourceChannelSyncActive === 'function'
                ? isResourceChannelSyncActive(channelSyncState)
                : (!!channelSyncState.submitted || !!channelSyncState.running);
            const channelSyncCancelPending = channelSyncActive && !!channelSyncState.cancel_requested;

            if (searchBtn) {
                const blocked = resourceSyncBusy || resourceSyncCancelBusy;
                searchBtn.disabled = blocked;
                searchBtn.classList.toggle('btn-disabled', blocked);
                searchBtn.classList.toggle('is-loading', resourceSearchBusy);
                searchBtn.classList.toggle('resource-search-btn-cancel', resourceSearchBusy);
                searchBtn.setAttribute('aria-busy', resourceSearchBusy ? 'true' : 'false');
                searchBtn.textContent = resourceSearchBusy
                    ? (resourceSearchCancelRequested ? '停止中...' : (directImport ? '停止识别' : '停止搜索'))
                    : '搜索';
            }

            if (syncBtn) {
                const blocked = resourceSearchBusy || resourceSyncBusy || resourceSyncCancelBusy || channelSyncCancelPending;
                syncBtn.disabled = blocked;
                syncBtn.classList.toggle('btn-disabled', blocked);
                syncBtn.classList.toggle('is-loading', resourceSyncBusy || resourceSyncCancelBusy);
                syncBtn.classList.toggle('resource-search-btn-cancel', channelSyncActive);
                syncBtn.setAttribute('aria-busy', (resourceSyncBusy || resourceSyncCancelBusy) ? 'true' : 'false');
                syncBtn.textContent = resourceSyncBusy
                    ? '同步中...'
                    : ((resourceSyncCancelBusy || channelSyncCancelPending)
                        ? '停止中...'
                        : (channelSyncActive ? '停止同步' : '同步频道'));
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

        function buildResourceSearchId() {
            if (window.crypto && typeof window.crypto.randomUUID === 'function') {
                return `resource-${window.crypto.randomUUID()}`;
            }
            return `resource-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
        }

        function cancelActiveResourceSearch({ notify = true } = {}) {
            if (!resourceSearchBusy) return false;
            resourceSearchCancelRequested = true;
            if (resourceSearchAbortController) {
                try { resourceSearchAbortController.abort(); } catch (e) {}
            }
            const searchId = String(resourceActiveSearchId || '').trim();
            if (searchId) {
                void window.MediaHubApi.postJson('/resource/search/cancel', { search_id: searchId }).catch(() => null);
            }
            if (notify) {
                showToast('已请求停止当前搜索', { tone: 'info', duration: 1800, placement: 'top-center' });
            }
            syncResourceActionButtons();
            renderResourceBoardHint();
            return true;
        }

        async function cancelActiveResourceChannelSync({ notify = true } = {}) {
            const channelSyncState = typeof normalizeResourceChannelSyncState === 'function'
                ? normalizeResourceChannelSyncState(resourceState.channel_sync)
                : (resourceState.channel_sync || {});
            const active = typeof isResourceChannelSyncActive === 'function'
                ? isResourceChannelSyncActive(channelSyncState)
                : (!!channelSyncState.submitted || !!channelSyncState.running);
            if (!active || resourceSyncBusy || resourceSyncCancelBusy) return false;
            resourceSyncCancelBusy = true;
            setResourceTgHealthState({
                visible: true,
                tone: 'loading',
                title: '频道同步停止中',
                meta: '等待当前批次收尾',
                note: '',
            });
            syncResourceActionButtons();
            try {
                const data = await window.MediaHubApi.postJson('/resource/channels/sync/cancel', {});
                if (data?.channel_sync && typeof applyResourceChannelSyncState === 'function') {
                    applyResourceChannelSyncState(data.channel_sync, { refreshOnComplete: false });
                } else if (typeof scheduleResourcePolling === 'function') {
                    scheduleResourcePolling(1000);
                }
                if (notify) {
                    showToast(
                        data?.cancelled === false ? '当前没有进行中的频道同步' : '已请求停止当前同步',
                        {
                            tone: data?.cancelled === false ? 'warn' : 'info',
                            duration: 1800,
                            placement: 'top-center',
                        }
                    );
                }
                return data;
            } catch (e) {
                if (active && !channelSyncState.cancel_requested) {
                    setResourceTgHealthState({
                        visible: true,
                        tone: 'loading',
                        title: '频道同步后台运行中',
                        meta: '',
                        note: '',
                    });
                }
                showToast(`停止同步失败：${e?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return null;
            } finally {
                resourceSyncCancelBusy = false;
                syncResourceActionButtons();
                if (!resourceSearchBusy) renderResourceBoard();
            }
        }

        async function refreshResourceState({ allowSearch = true, keywordOverride = null, searchId = '', signal = null, compact = false, jobMode = 'poll' } = {}) {
            const resourceModule = await loadResourceTabModule();
            if (resourceModule?.refreshResourceState) {
                return resourceModule.refreshResourceState({
                    allowSearch,
                    keywordOverride,
                    searchId,
                    signal,
                    compact,
                    getResourceState: () => resourceState,
                    getResourceJobsStateRequest: () => getResourceJobsStateRequest({ mode: jobMode }),
                    isDirectImportInput,
                    setResourceStateHydrated: (nextValue) => {
                        resourceStateHydrated = !!nextValue;
                    },
                    applyResourceState,
                    rejectResourceJobsRequest,
                });
            }
            let jobRequest = null;
            try {
                const activeKeyword = typeof keywordOverride === 'string'
                    ? keywordOverride.trim()
                    : String(resourceState.search || '').trim();
                const shouldSearchChannels = !!activeKeyword && !isDirectImportInput(activeKeyword) && allowSearch;
                const params = new URLSearchParams();
                if (shouldSearchChannels) params.set('q', activeKeyword);
                params.set('search_source', normalizeResourceSearchSource(resourceSearchSource));
                params.set('provider_filter', 'all');
                if (searchId) params.set('search_id', String(searchId || '').trim());
                jobRequest = getResourceJobsStateRequest({ mode: jobMode });
                params.set('job_status', jobRequest.status);
                params.set('job_offset', String(jobRequest.offset));
                params.set('job_limit', String(jobRequest.limit));
                if (compact && !shouldSearchChannels) params.set('compact', '1');
                const endpoint = params.toString() ? `/resource/state?${params.toString()}` : '/resource/state';
                const data = await window.MediaHubApi.getJson(endpoint, signal ? { signal } : undefined);
                resourceStateHydrated = true;
                applyResourceState(data, { compactUpdate: !!compact, jobRequest });
                return data;
            } catch (e) {
                rejectResourceJobsRequest(jobRequest, e);
                return null;
            }
        }

        function hasActiveResourceJobs() {
            if (typeof hasActiveScraperJobs === 'function' && hasActiveScraperJobs()) return true;
            const resourceModule = tabRuntimeState.tabModuleCache.resource;
            if (resourceModule?.hasActiveResourceJobs) {
                return resourceModule.hasActiveResourceJobs({
                    getResourceState: () => resourceState,
                });
            }
            const jobs = Array.isArray(resourceState?.jobs) ? resourceState.jobs : [];
            const activeCount = Number(resourceState?.job_counts?.active ?? resourceState?.stats?.active_job_count ?? 0) || 0;
            if (activeCount > 0) return true;
            return jobs.some((job) => {
                const status = String(job?.status || '').trim().toLowerCase();
                return ['pending', 'running', 'queued', 'importing', 'submitted'].includes(status);
            });
        }

        const resourceJobStateController = window.ResourceJobState.create({
            pageSize: RESOURCE_JOB_PAGE_SIZE,
            maxWindowSize: RESOURCE_JOB_PAGE_MAX_SIZE,
        });

        function scheduleResourceJobWindowCalibration() {
            if (resourceJobCalibrationPending) return;
            resourceJobCalibrationPending = true;
            Promise.resolve()
                .then(() => refreshResourceJobsOnly({ mode: 'window' }))
                .finally(() => {
                    resourceJobCalibrationPending = false;
                });
        }

        function projectResourceJobsResponse(data, options = {}) {
            const source = data && typeof data === 'object' ? data : {};
            const result = resourceJobStateController.accept(options.jobRequest || null, source);
            if (!result.accepted) {
                const currentStats = resourceState?.stats && typeof resourceState.stats === 'object'
                    ? resourceState.stats
                    : {};
                const incomingStats = source.stats && typeof source.stats === 'object' ? source.stats : {};
                return {
                    accepted: false,
                    data: {
                        ...source,
                        jobs: resourceState.jobs || [],
                        active_jobs: resourceState.active_jobs || [],
                        job_counts: resourceState.job_counts || {},
                        pagination: resourceState.job_pagination || {},
                        stats: {
                            ...incomingStats,
                            total_job_count: currentStats.total_job_count,
                            active_job_count: currentStats.active_job_count,
                            completed_job_count: currentStats.completed_job_count,
                            failed_job_count: currentStats.failed_job_count,
                        },
                    },
                };
            }
            resourceJobLoadError = '';
            const projected = {
                ...source,
                jobs: result.jobs,
                active_jobs: result.activeJobs,
                pagination: result.pagination,
            };
            if (result.needsCalibration) scheduleResourceJobWindowCalibration();
            return { accepted: true, data: projected };
        }

        function rejectResourceJobsRequest(jobRequest, error) {
            const result = resourceJobStateController.reject(jobRequest, error);
            if (!result.accepted) return result;
            resourceJobLoadError = result.error;
            resourceJobLoadingMore = false;
            renderResourceJobs();
            return result;
        }

        function buildResourceJobsStateUrl({ status = resourceJobFilter, offset = 0, limit = RESOURCE_JOB_PAGE_SIZE } = {}) {
            const params = new URLSearchParams();
            const normalizedStatus = normalizeResourceJobFilter(status);
            params.set('status', normalizedStatus);
            params.set('offset', String(Math.max(0, Number(offset || 0) || 0)));
            params.set('limit', String(Math.max(1, Math.min(RESOURCE_JOB_PAGE_MAX_SIZE, Number(limit || RESOURCE_JOB_PAGE_SIZE) || RESOURCE_JOB_PAGE_SIZE))));
            return `/resource/jobs/state?${params.toString()}`;
        }

        function getResourceJobsStateRequest({ status = resourceJobFilter, reset = false, extend = false, mode = 'poll' } = {}) {
            const normalizedStatus = normalizeResourceJobFilter(status);
            resourceJobFilter = normalizedStatus;
            resourceJobLoadError = '';
            return resourceJobStateController.begin({
                status: normalizedStatus,
                reset,
                extend,
                mode,
            });
        }

        async function fetchResourceJobsPage({ status = resourceJobFilter, reset = false, extend = false } = {}) {
            const normalizedStatus = normalizeResourceJobFilter(status);
            resourceJobFilter = normalizedStatus;
            if (extend) {
                resourceJobLoadingMore = true;
                renderResourceJobs();
            }
            const jobRequest = getResourceJobsStateRequest({
                status: normalizedStatus,
                reset,
                extend,
                mode: 'window',
            });
            try {
                const data = await window.MediaHubApi.getJson(buildResourceJobsStateUrl(jobRequest));
                applyResourceJobsState(data, { jobRequest });
                return data;
            } catch (e) {
                rejectResourceJobsRequest(jobRequest, e);
                return null;
            } finally {
                if (extend) {
                    resourceJobLoadingMore = false;
                    renderResourceJobs();
                }
            }
        }

        async function loadMoreResourceJobs() {
            if (resourceJobLoadingMore) return;
            const pagination = resourceState?.job_pagination && typeof resourceState.job_pagination === 'object'
                ? resourceState.job_pagination
                : {};
            if (!pagination.has_more) return;
            await fetchResourceJobsPage({
                status: pagination.status || resourceJobFilter,
                extend: true,
            });
        }

        function applyResourceJobsState(data, options = {}) {
            const projectedJobs = projectResourceJobsResponse(data, options);
            if (!projectedJobs.accepted) return;
            data = projectedJobs.data;
            const resourceModule = tabRuntimeState.tabModuleCache.resource;
            if (resourceModule?.applyResourceJobsState) {
                resourceModule.applyResourceJobsState(data, {
                    getResourceState: () => resourceState,
                    setResourceState: (nextValue) => {
                        resourceState = { ...nextValue };
                    },
                    getResourceJobCounts,
                    syncResourceMonitorTaskOptions,
                    renderResourceJobs,
                    syncResourceJobModalTrigger,
                    renderResourceBoard,
                    renderResourceBoardHint,
                    isResourceTabActive: () => currentTab === 'resource',
                });
                return;
            }
            if (!data || typeof data !== 'object') return;
            const nextJobs = Array.isArray(data.jobs) ? data.jobs : (resourceState.jobs || []);
            const nextActiveJobs = Array.isArray(data.active_jobs) ? data.active_jobs : (resourceState.active_jobs || []);
            const nextMonitorTasks = Array.isArray(data.monitor_tasks) ? data.monitor_tasks : (resourceState.monitor_tasks || []);
            const incomingStats = data.stats && typeof data.stats === 'object' ? data.stats : {};
            const nextJobCounts = data.job_counts && typeof data.job_counts === 'object'
                ? data.job_counts
                : (resourceState.job_counts || {});
            const nextJobPagination = data.pagination && typeof data.pagination === 'object'
                ? data.pagination
                : (resourceState.job_pagination || {});
            const fallbackCounts = getResourceJobCounts(nextJobs);
            resourceState = {
                ...resourceState,
                jobs: nextJobs,
                active_jobs: nextActiveJobs,
                job_counts: nextJobCounts,
                job_pagination: nextJobPagination,
                monitor_tasks: nextMonitorTasks,
                stats: {
                    ...(resourceState.stats || {}),
                    total_job_count: Number(incomingStats.total_job_count ?? nextJobCounts.total ?? fallbackCounts.total ?? 0),
                    active_job_count: Number(incomingStats.active_job_count ?? nextJobCounts.active ?? fallbackCounts.active ?? 0),
                    completed_job_count: Number(incomingStats.completed_job_count ?? fallbackCounts.completed ?? 0),
                    failed_job_count: Number(incomingStats.failed_job_count ?? fallbackCounts.failed ?? 0),
                }
            };
            syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
            renderResourceJobs();
            syncResourceJobModalTrigger();
            if (currentTab === 'resource') {
                renderResourceBoard();
                renderResourceBoardHint();
            }
        }

        async function refreshResourceJobsOnly({ mode = 'poll' } = {}) {
            const resourceModule = await loadResourceTabModule();
            if (resourceModule?.refreshResourceJobsOnly) {
                return resourceModule.refreshResourceJobsOnly({
                    applyResourceJobsState,
                    buildResourceJobsStateUrl,
                    getResourceJobsStateRequest,
                    rejectResourceJobsRequest,
                    requestOptions: { mode },
                });
            }
            const jobRequest = getResourceJobsStateRequest({ mode });
            try {
                const data = await window.MediaHubApi.getJson(buildResourceJobsStateUrl(jobRequest));
                applyResourceJobsState(data, { jobRequest });
                return data;
            } catch (e) {
                rejectResourceJobsRequest(jobRequest, e);
                return null;
            }
        }

        function isDirectImportInput(value) {
            const raw = String(value || '').trim();
            if (!raw) return false;
            if (/magnet:\?/i.test(raw)) return true;
            if (/ed2k:\/\/\|file\|/i.test(raw)) return true;
            if (/(?:^|[\s(（【\[])(?:https?:\/\/)?(?:115cdn|115|anxia)\.com\/s\/[a-z0-9]+(?:\?[^\s<>'"]*)?/i.test(raw)) return true;
            const links = raw.match(/https?:\/\/[^\s<>'"]+/gi) || [];
            return links.some(link => {
                const linkType = detectResourceLinkTypeByUrl(link);
                return linkType !== 'unknown';
            });
        }

        async function parseResourceInputFromSearch(rawText) {
            const data = await window.MediaHubApi.postJson('/resource/items/preview_text', {
                raw_text: rawText
            }, resourceSearchAbortController?.signal ? { signal: resourceSearchAbortController.signal } : undefined);
            const items = Array.isArray(data.items) ? data.items : [];
            const importableItems = items
                .filter(item => canOpenResourceImport(item))
                .map(item => createTransientResourceItem(item));
            if (!importableItems.length) throw new Error('未在文本中识别到可导入的离线链接、资源外链或已启用网盘分享链接');

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
            if (resourceSearchBusy) {
                resourceRestartSearchAfterCancel = false;
                cancelActiveResourceSearch();
                return null;
            }
            if (resourceSyncBusy) return null;
            if (!keyword) {
                renderResourceBoard();
                return null;
            }
            const directImportMode = isDirectImportInput(keyword);
            const currentSearchSource = normalizeResourceSearchSource(resourceSearchSource || resourceState.search_source || 'tg');
            const startedAt = performance.now();
            const currentSearchId = buildResourceSearchId();
            resourceActiveSearchId = currentSearchId;
            resourceSearchAbortController = new AbortController();
            resourceSearchCancelRequested = false;
            resourceSearchBusy = true;
            updateResourceActiveSearchRuntime({
                searchId: currentSearchId,
                source: currentSearchSource,
                keyword,
                providerFilter: resourceProviderFilter,
                directImportMode,
                latencyMs: currentSearchSource === 'tg' ? Number(resourceTgLastLatencyMs || 0) : 0,
                latencyText: currentSearchSource === 'pansou' ? '已开始' : '',
            });
            let latencyProbePromise = null;
            if (!directImportMode && currentSearchSource === 'tg') {
                showResourceTgHealthLoading('search');
                latencyProbePromise = probeResourceTgLatency();
                latencyProbePromise.then((result) => {
                    const latencyMs = Number(result?.latency_ms || resourceTgLastLatencyMs || 0);
                    if (resourceSearchBusy && resourceActiveSearchId === currentSearchId && latencyMs > 0) {
                        updateResourceActiveSearchRuntime({
                            latencyMs,
                            latencyText: formatResourceSearchLatency(latencyMs),
                        });
                        resourceBoardHintText = getResourceSearchRunningHintText();
                        renderResourceBoardHint();
                    }
                }).catch(() => null);
            } else if (!directImportMode && currentSearchSource === 'pansou') {
                setResourceTgHealthState({ visible: false, tone: 'loading', title: '', meta: '', note: '' });
            }
            resourceBoardHintText = getResourceSearchRunningHintText();
            renderResourceBoardHint();
            syncResourceActionButtons();
            let finalHintText = '';
            try {
                if (directImportMode) {
                    if (String(resourceState.search || '').trim()) resetResourceSearchResults();
                    const result = await parseResourceInputFromSearch(keyword);
                    return result;
                }
                const data = await refreshResourceState({
                    allowSearch: true,
                    keywordOverride: keyword,
                    searchId: currentSearchId,
                    signal: resourceSearchAbortController.signal,
                });
                if (!data) throw new Error('搜索请求失败，请稍后重试');
                const hasSearchErrors = Array.isArray(resourceState?.search_meta?.errors) && resourceState.search_meta.errors.length > 0;
                const visibleResultCount = getResourceSearchResultCount(resourceState, keyword);
                const completedPhase = hasSearchErrors && visibleResultCount <= 0 ? 'failed' : 'completed';
                if (currentSearchSource === 'tg') {
                    const latencyMs = await resolveResourceTgLatencyMs(latencyProbePromise);
                    resourceState = {
                        ...resourceState,
                        search_meta: {
                            ...(resourceState.search_meta || {}),
                            client_phase: completedPhase,
                            client_elapsed_ms: getActionElapsedMs(startedAt),
                            tg_latency_ms: latencyMs,
                        }
                    };
                    applyResourceTgHealthFromSearchResult(data, getActionElapsedMs(startedAt), latencyMs);
                    finalHintText = buildResourceSearchStatusText({
                        phase: completedPhase,
                        source: currentSearchSource,
                        keyword,
                        providerFilter: resourceProviderFilter,
                        durationMs: getActionElapsedMs(startedAt),
                        latencyMs,
                    });
                } else {
                    resourceState = {
                        ...resourceState,
                        search_meta: {
                            ...(resourceState.search_meta || {}),
                            client_phase: completedPhase,
                            client_elapsed_ms: getActionElapsedMs(startedAt),
                        }
                    };
                    finalHintText = buildResourceSearchStatusText({
                        phase: completedPhase,
                        source: currentSearchSource,
                        keyword,
                        providerFilter: resourceProviderFilter,
                        durationMs: getActionElapsedMs(startedAt),
                    });
                }
                return data;
            } catch (e) {
                if (e?.name === 'AbortError') {
                    const latencyMs = currentSearchSource === 'tg' ? Number(resourceTgLastLatencyMs || 0) : 0;
                    resourceState = {
                        ...resourceState,
                        search_meta: {
                            ...(resourceState.search_meta || {}),
                            client_phase: 'cancelled',
                            client_elapsed_ms: getActionElapsedMs(startedAt),
                            tg_latency_ms: latencyMs,
                        }
                    };
                    finalHintText = buildResourceSearchStatusText({
                        phase: 'cancelled',
                        source: currentSearchSource,
                        keyword,
                        providerFilter: resourceProviderFilter,
                        durationMs: getActionElapsedMs(startedAt),
                        latencyMs,
                    });
                    showToast(resourceSearchCancelRequested ? '搜索已停止' : '搜索请求已取消', { tone: 'info', duration: 1800, placement: 'top-center' });
                    return null;
                }
                if (!directImportMode && currentSearchSource === 'tg') {
                    const latencyMs = await resolveResourceTgLatencyMs(latencyProbePromise);
                    resourceState = {
                        ...resourceState,
                        search_meta: {
                            ...(resourceState.search_meta || {}),
                            client_phase: 'failed',
                            client_elapsed_ms: getActionElapsedMs(startedAt),
                            tg_latency_ms: latencyMs,
                        }
                    };
                    finalHintText = buildResourceSearchStatusText({
                        phase: 'failed',
                        source: currentSearchSource,
                        keyword,
                        providerFilter: resourceProviderFilter,
                        durationMs: getActionElapsedMs(startedAt),
                        latencyMs,
                    });
                    applyResourceTgHealthFailure('search', getActionElapsedMs(startedAt), latencyMs);
                } else if (!directImportMode) {
                    resourceState = {
                        ...resourceState,
                        search_meta: {
                            ...(resourceState.search_meta || {}),
                            client_phase: 'failed',
                            client_elapsed_ms: getActionElapsedMs(startedAt),
                        }
                    };
                    finalHintText = buildResourceSearchStatusText({
                        phase: 'failed',
                        source: currentSearchSource,
                        keyword,
                        providerFilter: resourceProviderFilter,
                        durationMs: getActionElapsedMs(startedAt),
                    });
                }
                showToast(`搜索失败：${e.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return null;
            } finally {
                if (resourceActiveSearchId === currentSearchId) {
                    resourceActiveSearchId = '';
                    resourceSearchAbortController = null;
                    resourceSearchCancelRequested = false;
                }
                resourceSearchBusy = false;
                clearResourceActiveSearchRuntime(currentSearchId);
                syncResourceActionButtons();
                if (!resourceSyncBusy) renderResourceBoard();
                if (finalHintText) {
                    resourceBoardHintText = finalHintText;
                    renderResourceBoardHint();
                }
                if (resourceRestartSearchAfterCancel) {
                    resourceRestartSearchAfterCancel = false;
                    window.setTimeout(() => {
                        if (!resourceSearchBusy && !resourceSyncBusy) void searchResources();
                    }, 0);
                }
            }
        }

        async function syncResourceChannels(force = false, { silent = false } = {}) {
            if (resourceSearchBusy || resourceSyncBusy || resourceSyncCancelBusy) return null;
            const channelSyncState = typeof normalizeResourceChannelSyncState === 'function'
                ? normalizeResourceChannelSyncState(resourceState.channel_sync)
                : (resourceState.channel_sync || {});
            const channelSyncActive = typeof isResourceChannelSyncActive === 'function'
                ? isResourceChannelSyncActive(channelSyncState)
                : (!!channelSyncState.submitted || !!channelSyncState.running);
            if (channelSyncActive) {
                return cancelActiveResourceChannelSync({ notify: !silent });
            }
            const startedAt = performance.now();
            resourceSyncBusy = true;
            let latencyProbePromise = null;
            if (!silent) showResourceTgHealthLoading('sync');
            if (!silent) latencyProbePromise = probeResourceTgLatency();
            syncResourceActionButtons();
            try {
                const syncLimit = typeof getCurrentTgChannelSyncLimit === 'function'
                    ? getCurrentTgChannelSyncLimit()
                    : 10;
                const data = await window.MediaHubApi.postJson('/resource/channels/sync', { force, limit: syncLimit });
                if (data?.channel_sync && typeof applyResourceChannelSyncState === 'function') {
                    applyResourceChannelSyncState(data.channel_sync);
                }
                if (!data?.queued) {
                    await refreshResourceState();
                } else if (typeof scheduleResourcePolling === 'function') {
                    scheduleResourcePolling(3000);
                }
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
                showToast(meta.emptyText, { tone: 'warn', duration: 2600, placement: 'top-center' });
                return;
            }
            if (!(await showAppConfirm(meta.confirmText))) return;
            let data = {};
            try {
                data = await window.MediaHubApi.postJson('/resource/jobs/clear', { scope: meta.scope });
            } catch (error) {
                showToast(`清空失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
                return;
            }
            await refreshResourceState({ jobMode: 'window' });
            const deleted = Number(data.deleted || 0);
            if (deleted > 0) {
                showToast(`已清空 ${deleted} 条${meta.label}导入记录`, { tone: 'success', duration: 2600, placement: 'top-center' });
            } else {
                showToast(meta.emptyText, { tone: 'info', duration: 2600, placement: 'top-center' });
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

        function renderProviderFilterButtons() {
            const container = document.getElementById('resource-provider-filters');
            if (!container) return;
            container.querySelectorAll('.provider-filter-dynamic').forEach(el => el.remove());
            const enabled = getEnabledProviders();
            enabled.forEach(p => {
                const btn = document.createElement('button');
                btn.id = 'resource-provider-filter-' + p.name;
                btn.className = 'resource-search-segment-btn provider-filter-dynamic';
                btn.onclick = () => setResourceProviderFilter(p.name);
                btn.textContent = p.label;
                container.appendChild(btn);
            });
        }

        Object.assign(window, {
            applyResourceState,
            renderResourceBoard,
            refreshResourceState,
            refreshResourceJobsOnly,
            searchResources,
            setResourceSearchSource,
            setResourceProviderFilter,
            syncResourceChannels,
            clearResourceSearch,
            pasteResourceSearch,
            resetResourceSearchResults,
            syncResourceSearchInputActions,
            syncResourceSourceSelect,
            syncResourceProviderUI,
            renderResourceFavoriteDirs,
            selectResourceFavoriteDir,
            syncResourceMonitorTaskOptions,
            renderResourceImportSummary,
            renderResourceImportStepper,
            renderResourceImportBehaviorHint,
            renderProviderFilterButtons,
            syncResourceActionButtons,
            toggleResourceSection,
            loadMoreResourceChannelItems,
            findResourceItem,
            createTransientResourceItem,
            serializeTransientResourceForJob,
            setResourceBatchImportItems,
            getResourceBatchMagnetItems,
            isResourceBatchImportMode,
            getResourceLinkRecords,
            createResourceLinkActionItem,
            getResourceImportCandidates,
            openResourceLinkChoiceModal,
            canOpenResourceImport,
            canOpenResourceImportLink,
            canImportResource,
            getResourceImportLabel,
            getResourceCopyText,
            getResourceDisplayStatus,
            getCurrentResourceProvider,
            getResourceProviderForLinkType,
            getCurrentResourceProviderLabel,
            getResourceProviderLabel,
            normalizeResourceProviderName,
            getOfflineMagnetProviders,
            getResourceDefaultMagnetProvider,
            getResourceSelectedMagnetProvider,
            getResourceProviderByLinkType,
            getEffectiveResourceLinkType,
            buildResourceDisplayProfile,
            getResourceDisplayLinkType,
            getResourceDisplayLinkTypeBadgeClass,
            getResourceDisplayLinkTypeLabel,
            getResourceImportMode,
            isLinkTypeCookieConfigured,
            isProviderCookieConfigured,
            normalizeReceiveCodeInput,
            extractReceiveCodeFromText,
            extractReceiveCodeFromShareUrl,
            normalizeRelativePathInput,
            buildResourcePoster,
            buildResourceStatusBadge,
            formatFileSizeText,
            openResourceQuickLinkModal,
            closeResourceQuickLinkModal,
            fillResourceQuickLinkFormFromSearch,
            cancelEditResourceQuickLink,
            saveResourceQuickLink,
            useResourceQuickLinkForSearch,
            openResourceQuickLinkExternal,
            copyResourceQuickLink,
            editResourceQuickLink,
            deleteResourceQuickLink,
            clearCompletedResourceJobs,
            clearFailedResourceJobs,
            clearTerminalResourceJobs,
        });
