export async function ensureTabData(context) {
    context.moduleVisitState.settings = true;
}

let latestCookieHealthState = {};
const cookieHealthBusyProviders = new Set();

function escapeHtml(value = '') {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function randomAlphaNumericSecret(length = 32) {
    const size = Math.max(8, Number(length || 32) || 32);
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

function normalizeFavoriteDirPath(value = '') {
    return String(value || '')
        .split(/[\\/]+/)
        .map(part => part.trim())
        .filter(Boolean)
        .join('/');
}

function parseFavoriteDirLines(value = '') {
    const seen = new Set();
    return String(value || '')
        .split(/\r?\n/)
        .map(line => line.trim())
        .filter(Boolean)
        .map((line) => {
            const separatorIndex = line.indexOf('=');
            const rawName = separatorIndex >= 0 ? line.slice(0, separatorIndex).trim() : '';
            const rawPath = separatorIndex >= 0 ? line.slice(separatorIndex + 1).trim() : line;
            const path = normalizeFavoriteDirPath(rawPath);
            if (!path || seen.has(path)) return null;
            seen.add(path);
            const fallbackName = path.split('/').filter(Boolean).pop() || path;
            return {
                name: (rawName || fallbackName).slice(0, 32),
                path,
            };
        })
        .filter(Boolean)
        .slice(0, 12);
}

function formatFavoriteDirLines(items = []) {
    return (Array.isArray(items) ? items : [])
        .map((item) => {
            const path = normalizeFavoriteDirPath(item?.path || item?.savepath || '');
            if (!path) return '';
            const name = String(item?.name || '').trim();
            return name ? `${name}=${path}` : path;
        })
        .filter(Boolean)
        .join('\n');
}

export function renderResourceFavoriteDirSettings(favoriteDirs = {}) {
    const grid = document.getElementById('resource-favorite-dir-settings-grid');
    if (!grid) return;
    const meta = (window.providerMeta || []).filter(p => p.supports_folder_browse !== false);
    const providers = meta.length ? meta : [
        { name: '115', label: '115' },
        { name: 'quark', label: 'Quark' },
    ];
    const source = favoriteDirs && typeof favoriteDirs === 'object' ? favoriteDirs : {};
    grid.innerHTML = providers.map((p) => {
        const providerName = String(p.name || '').trim();
        const providerLabel = String(p.label || providerName).trim();
        const textareaId = `resource_favorite_dirs_${providerName.replace(/[^A-Za-z0-9_-]/g, '_')}`;
        return `
            <label class="block">
                <span class="text-xs text-slate-500">${escapeHtml(providerLabel)} 常用目录</span>
                <textarea id="${escapeHtml(textareaId)}" data-resource-favorite-provider="${escapeHtml(providerName)}" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-1 min-h-[110px]" placeholder="电影=影视/电影&#10;电视剧=影视/电视剧">${escapeHtml(formatFavoriteDirLines(source[providerName] || []))}</textarea>
            </label>
        `;
    }).join('');
}

function collectResourceFavoriteDirs() {
    const result = {};
    document.querySelectorAll('[data-resource-favorite-provider]').forEach((el) => {
        const provider = String(el.getAttribute('data-resource-favorite-provider') || '').trim();
        if (!provider) return;
        result[provider] = parseFavoriteDirLines(el.value || '');
    });
    if (Object.keys(result).length) return result;
    return {
        '115': parseFavoriteDirLines(document.getElementById('resource_favorite_dirs_115')?.value || ''),
        quark: parseFavoriteDirLines(document.getElementById('resource_favorite_dirs_quark')?.value || ''),
    };
}

function collectSettingsPayload({
    sensitiveSettingFields = [],
    getMonitorTasks,
} = {}) {
    const cfg = {};
    const standardIds = [
        'strm_proxy_base_url',
        'api_115_rate_limit_seconds',
        'api_115_list_cache_ttl_seconds',
        'api_115_download_url_cache_ttl_seconds',
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
        'pansou_base_url',
        'pansou_username',
        'pansou_password',
        'pansou_src',
        'pansou_channels',
        'pansou_plugins',
        'extensions',
        'username',
        'password',
        'webhook_secret'
    ];
    const sensitiveFieldSet = new Set(Array.isArray(sensitiveSettingFields) ? sensitiveSettingFields : []);
    standardIds.forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        const value = String(el.value || '');
        if (sensitiveFieldSet.has(id) && !value.trim()) return;
        cfg[id] = value;
    });

    const syncCleanElement = document.getElementById('sync_clean');
    if (syncCleanElement) cfg.sync_clean = !!syncCleanElement.checked;
    cfg.sign115_enabled = !!document.getElementById('sign115_enabled')?.checked;
    cfg.tg_proxy_enabled = !!document.getElementById('tg_proxy_enabled')?.checked;
    cfg.notify_push_enabled = !!document.getElementById('notify_push_enabled')?.checked;
    cfg.notify_monitor_enabled = !!document.getElementById('notify_monitor_enabled')?.checked;
    cfg.tmdb_enabled = !!document.getElementById('tmdb_enabled')?.checked;
    cfg.pansou_enabled = !!document.getElementById('pansou_enabled')?.checked;
    cfg.resource_favorite_dirs = collectResourceFavoriteDirs();

    // Dynamically collect provider cookies
    const meta = window.providerMeta || [];
    const providerEnabled = {};
    meta.forEach(p => {
        const keys = Array.isArray(p.config_keys) && p.config_keys.length ? p.config_keys : ['cookie_' + p.name];
        keys.forEach((key) => {
            const el = document.getElementById(key);
            if (el) cfg[key] = el.value;
        });
        const enabledEl = document.getElementById('provider_enabled_' + p.name);
        providerEnabled[p.name] = enabledEl ? enabledEl.checked : p.enabled;
    });
    cfg.provider_enabled = providerEnabled;
    cfg.default_magnet_provider = '115';
    cfg.magnet_staging_root = String(document.getElementById('magnet_staging_root')?.value || '').trim() || '云下载/磁力中转';

    const rawTmdbCacheTtl = parseInt(document.getElementById('tmdb_cache_ttl_hours')?.value || '', 10);
    cfg.tmdb_cache_ttl_hours = Math.min(720, Math.max(1, Number.isFinite(rawTmdbCacheTtl) ? rawTmdbCacheTtl : 24));

    const rawTgThreads = parseInt(document.getElementById('tg_channel_threads')?.value || '', 10);
    cfg.tg_channel_threads = Math.min(20, Math.max(1, Number.isFinite(rawTgThreads) ? rawTgThreads : 6));

    const rawTgSyncLimit = parseInt(document.getElementById('tg_channel_sync_limit')?.value || '', 10);
    cfg.tg_channel_sync_limit = Math.min(30, Math.max(1, Number.isFinite(rawTgSyncLimit) ? rawTgSyncLimit : 10));

    cfg.monitor_tasks = typeof getMonitorTasks === 'function' ? (getMonitorTasks() || []) : [];

    return cfg;
}

export function syncNotifyChannelUI() {
    const channel = String(document.getElementById('notify_channel')?.value || 'wecom_bot').trim().toLowerCase();
    const botFields = document.getElementById('notify-bot-fields');
    const appFields = document.getElementById('notify-app-fields');
    if (botFields) botFields.classList.toggle('hidden', channel !== 'wecom_bot');
    if (appFields) appFields.classList.toggle('hidden', channel === 'wecom_bot');
}

export function renderTgProxyTestStatus({
    tgProxyTestState,
    escapeHtml,
    formatDurationText,
} = {}) {
    const state = tgProxyTestState || {};
    const btn = document.getElementById('tg-proxy-test-btn');
    const statusEl = document.getElementById('tg-proxy-test-status');
    if (btn) {
        btn.disabled = !!state.loading;
        btn.classList.toggle('btn-disabled', !!state.loading);
        btn.textContent = state.loading ? '测试中...' : '测试 TG 延迟';
    }
    if (!statusEl) return;

    if (state.loading) {
        statusEl.className = 'tg-proxy-status tg-proxy-status--loading';
        statusEl.innerHTML = `
            <div class="tg-proxy-status-title">正在测试 TG 访问链路</div>
            <div class="tg-proxy-status-meta">正在请求 TG 频道页并测量当前响应时间，请稍候...</div>
        `;
        statusEl.classList.remove('hidden');
        return;
    }

    if (state.ok === true) {
        const modeLabel = state.mode === 'proxy'
            ? `代理模式 ${escapeHtml(state.proxy_url || '--')}`
            : '直连模式';
        statusEl.className = 'tg-proxy-status tg-proxy-status--success';
        statusEl.innerHTML = `
            <div class="tg-proxy-status-title">TG 可达 · ${escapeHtml(formatDurationText(state.latency_ms) || `总耗时 ${String(state.latency_ms || 0)} ms`)}</div>
            <div class="tg-proxy-status-meta">${modeLabel}</div>
            <div class="tg-proxy-status-note">测试地址：${escapeHtml(state.target_url || '')}</div>
        `;
        statusEl.classList.remove('hidden');
        return;
    }

    if (state.ok === false) {
        statusEl.className = 'tg-proxy-status tg-proxy-status--error';
        statusEl.innerHTML = `
            <div class="tg-proxy-status-title">TG 延迟测试失败</div>
            <div class="tg-proxy-status-meta">${escapeHtml(state.message || '未知错误')}</div>
        `;
        statusEl.classList.remove('hidden');
        return;
    }

    statusEl.classList.add('hidden');
    statusEl.textContent = '';
}

export async function testTgProxyLatency({
    getCurrentTgProxyConfig,
    getTgProxyTestState,
    setTgProxyTestState,
    renderTgProxyTestStatus,
} = {}) {
    const currentState = typeof getTgProxyTestState === 'function' ? getTgProxyTestState() : {};
    if (currentState?.loading) return;
    if (typeof setTgProxyTestState === 'function') {
        setTgProxyTestState({ loading: true, ok: null, message: '', latency_ms: 0, mode: '', proxy_url: '', target_url: '' });
    }
    if (typeof renderTgProxyTestStatus === 'function') renderTgProxyTestStatus();
    try {
        const data = await window.MediaHubApi.postJson(
            '/settings/tg_proxy/test',
            typeof getCurrentTgProxyConfig === 'function' ? getCurrentTgProxyConfig() : {}
        );
        if (typeof setTgProxyTestState === 'function') {
            setTgProxyTestState({
                loading: false,
                ok: true,
                message: data.msg || '',
                latency_ms: Number(data.latency_ms || 0),
                mode: String(data.mode || ''),
                proxy_url: String(data.proxy_url || ''),
                target_url: String(data.target_url || '')
            });
        }
    } catch (e) {
        if (typeof setTgProxyTestState === 'function') {
            setTgProxyTestState({
                loading: false,
                ok: false,
                message: e instanceof Error ? e.message : String(e || 'TG 延迟测试失败'),
                latency_ms: 0,
                mode: '',
                proxy_url: '',
                target_url: ''
            });
        }
    }
    if (typeof renderTgProxyTestStatus === 'function') renderTgProxyTestStatus();
}

export function renderPansouTestStatus({
    pansouTestState,
    escapeHtml,
    formatDurationText,
} = {}) {
    const state = pansouTestState || {};
    const btn = document.getElementById('pansou-test-btn');
    const statusEl = document.getElementById('pansou-test-status');
    if (btn) {
        btn.disabled = !!state.loading;
        btn.classList.toggle('btn-disabled', !!state.loading);
        btn.textContent = state.loading ? '测试中...' : '测试 PanSou';
    }
    if (!statusEl) return;

    if (state.loading) {
        statusEl.className = 'tg-proxy-status tg-proxy-status--loading';
        statusEl.innerHTML = `
            <div class="tg-proxy-status-title">正在检测 PanSou 服务</div>
            <div class="tg-proxy-status-meta">正在请求健康接口，请稍候...</div>
        `;
        statusEl.classList.remove('hidden');
        return;
    }

    if (state.ok === true) {
        statusEl.className = 'tg-proxy-status tg-proxy-status--success';
        statusEl.innerHTML = `
            <div class="tg-proxy-status-title">PanSou 可达 · ${escapeHtml(formatDurationText(state.latency_ms) || `总耗时 ${String(state.latency_ms || 0)} ms`)}</div>
            <div class="tg-proxy-status-meta">认证：${state.auth_enabled ? (state.auth_logged_in ? '已开启，账号已验证' : '已开启') : '未开启'}｜插件 ${escapeHtml(String(state.plugin_count || 0))}｜频道 ${escapeHtml(String(state.channels_count || 0))}</div>
        `;
        statusEl.classList.remove('hidden');
        return;
    }

    if (state.ok === false) {
        statusEl.className = 'tg-proxy-status tg-proxy-status--error';
        statusEl.innerHTML = `
            <div class="tg-proxy-status-title">PanSou 测试失败</div>
            <div class="tg-proxy-status-meta">${escapeHtml(state.message || '未知错误')}</div>
        `;
        statusEl.classList.remove('hidden');
        return;
    }

    statusEl.classList.add('hidden');
    statusEl.textContent = '';
}

export async function testPansouConnection({
    getCurrentPansouConfig,
    getPansouTestState,
    setPansouTestState,
    renderPansouTestStatus,
} = {}) {
    const currentState = typeof getPansouTestState === 'function' ? getPansouTestState() : {};
    if (currentState?.loading) return;
    if (typeof setPansouTestState === 'function') {
        setPansouTestState({ loading: true, ok: null, message: '', latency_ms: 0, auth_enabled: false, auth_configured: false, auth_logged_in: false, plugin_count: 0, channels_count: 0 });
    }
    if (typeof renderPansouTestStatus === 'function') renderPansouTestStatus();
    try {
        const data = await window.MediaHubApi.postJson(
            '/settings/pansou/test',
            typeof getCurrentPansouConfig === 'function' ? getCurrentPansouConfig() : {}
        );
        if (typeof setPansouTestState === 'function') {
            setPansouTestState({
                loading: false,
                ok: true,
                message: String(data.msg || 'PanSou 可用'),
                latency_ms: Number(data.latency_ms || 0),
                auth_enabled: !!data.auth_enabled,
                auth_configured: !!data.auth_configured,
                auth_logged_in: !!data.auth_logged_in,
                plugin_count: Number(data.plugin_count || 0),
                channels_count: Number(data.channels_count || 0)
            });
        }
    } catch (e) {
        if (typeof setPansouTestState === 'function') {
            setPansouTestState({
                loading: false,
                ok: false,
                message: e instanceof Error ? e.message : String(e || 'PanSou 测试失败'),
                latency_ms: 0,
                auth_enabled: false,
                auth_configured: false,
                auth_logged_in: false,
                plugin_count: 0,
                channels_count: 0
            });
        }
    }
    if (typeof renderPansouTestStatus === 'function') renderPansouTestStatus();
}

export function renderNotifyTestStatus({
    notifyTestState,
    escapeHtml,
    notifyChannelLabel,
} = {}) {
    const state = notifyTestState || {};
    const btn = document.getElementById('notify-test-btn');
    const statusEl = document.getElementById('notify-test-status');
    if (btn) {
        btn.disabled = !!state.loading;
        btn.classList.toggle('btn-disabled', !!state.loading);
        btn.textContent = state.loading ? '发送中...' : '发送测试消息';
    }
    if (!statusEl) return;

    if (state.loading) {
        statusEl.className = 'tg-proxy-status tg-proxy-status--loading';
        statusEl.innerHTML = `
            <div class="tg-proxy-status-title">正在发送测试消息</div>
            <div class="tg-proxy-status-meta">请稍候，正在请求企业微信通知接口...</div>
        `;
        statusEl.classList.remove('hidden');
        return;
    }

    if (state.ok === true) {
        const label = typeof notifyChannelLabel === 'function'
            ? notifyChannelLabel(state.channel || document.getElementById('notify_channel')?.value || '')
            : '企业微信群机器人';
        statusEl.className = 'tg-proxy-status tg-proxy-status--success';
        statusEl.innerHTML = `
            <div class="tg-proxy-status-title">测试消息发送成功</div>
            <div class="tg-proxy-status-meta">${escapeHtml(state.message || '通知配置可用')}</div>
            <div class="tg-proxy-status-note">渠道：${escapeHtml(label)}｜目标：${escapeHtml(state.target_desc || state.webhook_host || '--')}</div>
        `;
        statusEl.classList.remove('hidden');
        return;
    }

    if (state.ok === false) {
        statusEl.className = 'tg-proxy-status tg-proxy-status--error';
        statusEl.innerHTML = `
            <div class="tg-proxy-status-title">测试消息发送失败</div>
            <div class="tg-proxy-status-meta">${escapeHtml(state.message || '未知错误')}</div>
        `;
        statusEl.classList.remove('hidden');
        return;
    }

    statusEl.classList.add('hidden');
    statusEl.textContent = '';
}

export async function testNotifyPush({
    getCurrentNotifyConfig,
    getNotifyTestState,
    setNotifyTestState,
    renderNotifyTestStatus,
} = {}) {
    const currentState = typeof getNotifyTestState === 'function' ? getNotifyTestState() : {};
    if (currentState?.loading) return;
    if (typeof setNotifyTestState === 'function') {
        setNotifyTestState({ loading: true, ok: null, message: '', channel: '', target_desc: '', webhook_host: '', sent_at: '' });
    }
    if (typeof renderNotifyTestStatus === 'function') renderNotifyTestStatus();
    try {
        const data = await window.MediaHubApi.postJson(
            '/settings/notify/test',
            typeof getCurrentNotifyConfig === 'function' ? getCurrentNotifyConfig() : {}
        );
        if (typeof setNotifyTestState === 'function') {
            setNotifyTestState({
                loading: false,
                ok: true,
                message: String(data.msg || '测试消息已发送'),
                channel: String(data.channel || ''),
                target_desc: String(data.target_desc || ''),
                webhook_host: String(data.webhook_host || ''),
                sent_at: String(data.sent_at || '')
            });
        }
    } catch (e) {
        if (typeof setNotifyTestState === 'function') {
            setNotifyTestState({
                loading: false,
                ok: false,
                message: e instanceof Error ? e.message : String(e || '测试消息发送失败'),
                channel: '',
                target_desc: '',
                webhook_host: '',
                sent_at: ''
            });
        }
    }
    if (typeof renderNotifyTestStatus === 'function') renderNotifyTestStatus();
}

export async function refreshCookieHealthStatus({
    force = false,
    applyCookieHealthState,
} = {}) {
    try {
        const endpoint = force ? '/settings/cookies/status?refresh=1' : '/settings/cookies/status';
        const data = await window.MediaHubApi.getJson(endpoint);
        if (data?.cookie_health && typeof applyCookieHealthState === 'function') {
            applyCookieHealthState(data.cookie_health);
        }
    } catch (err) {
        console.warn('Cookie health status refresh failed', err);
    }
}

export async function checkCookiesNow({
    force = true,
    providers = null,
    isBusy = false,
    setBusy,
    renderCookieHealthCards,
    getCookieHealthState,
    applyCookieHealthState,
    showToast,
} = {}) {
    return checkCookieHealthProviders({
        providers,
        force,
        isBusy,
        setBusy,
        renderCookieHealthCards,
        getCookieHealthState,
        applyCookieHealthState,
        showToast,
    });
}

export async function refreshSign115Status({
    force = false,
    applySign115State,
} = {}) {
    try {
        const endpoint = force ? '/settings/115/sign/status?refresh=1' : '/settings/115/sign/status';
        const data = await window.MediaHubApi.getJson(endpoint);
        if (typeof applySign115State === 'function') applySign115State(data);
    } catch (err) {
        console.warn('Sign115 status refresh failed', err);
    }
}

export async function manualSign115({
    notify = false,
    sign115State,
    applySign115State,
    showToast,
} = {}) {
    if (sign115State?.running) return;
    try {
        const data = await window.MediaHubApi.postJson('/settings/115/sign/run');
        if (!data.ok) {
            if (data?.state && typeof applySign115State === 'function') applySign115State(data.state);
            if (notify && typeof showToast === 'function') {
                showToast(`签到失败：${data?.msg || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            }
            return;
        }
        if (data?.state && typeof applySign115State === 'function') applySign115State(data.state);
        if (notify && typeof showToast === 'function') {
            const message = String(data?.state?.message || '签到完成');
            showToast(message, { tone: 'success', duration: 3000, placement: 'top-center' });
        }
    } catch (err) {
        if (err?.payload?.state && typeof applySign115State === 'function') applySign115State(err.payload.state);
        if (notify && typeof showToast === 'function') {
            showToast(`签到失败：${err?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
        }
    }
}

export function generateWebhookSecret({ showToast } = {}) {
    const input = document.getElementById('webhook_secret');
    if (!input) return;
    input.value = randomAlphaNumericSecret(32);
    input.focus();
    input.select();
    if (typeof showToast === 'function') {
        showToast('已生成随机密钥，请记得点击“保存全部配置”', { tone: 'success', duration: 3000, placement: 'top-center' });
    }
}

export function renderProviderAuthBlocks(cfg, sensitiveMeta) {
    const container = document.getElementById('settings-provider-auth-container');
    if (!container) return;
    const meta = window.providerMeta || [];
    if (!meta.length) return;

    const sm = sensitiveMeta && typeof sensitiveMeta === 'object' ? sensitiveMeta : {};

    container.innerHTML = meta.map(p => {
        const enabled = p.enabled;
        const configKeys = Array.isArray(p.config_keys) && p.config_keys.length ? p.config_keys : ['cookie_' + p.name];
        const cookieKey = configKeys[0] || 'cookie_' + p.name;
        const passwordKey = configKeys[1] || '';
        const mixedUsernameKey = configKeys[1] || '';
        const mixedPasswordKey = configKeys[2] || '';
        const isConfigured = p.auth_type === 'password'
            ? (!!sm[cookieKey] && !!sm[passwordKey])
            : p.auth_type === 'password_cookie'
            ? ((!!sm[mixedUsernameKey] && !!sm[mixedPasswordKey]) || !!sm[cookieKey])
            : !!sm[cookieKey];
        const placeholder = p.auth_type === 'refresh_token'
            ? '粘贴 refresh_token'
            : p.auth_type === 'password'
            ? '输入 ' + p.label + ' 账号'
            : p.auth_type === 'password_cookie'
            ? '粘贴 ' + p.label + ' Cookie（账号密码触发验证码时备用）'
            : '粘贴 ' + p.label + ' Cookie';

        let authHint = '';
        if (p.auth_type === 'refresh_token') {
            authHint = '<a href="https://aliyuntoken.vercel.app/" target="_blank" class="text-xs text-blue-400 hover:text-blue-300">获取 refresh_token（手机扫码）</a>';
        } else if (p.auth_type === 'oauth2') {
            authHint = '<span class="text-xs text-slate-500">Cookie + OAuth2 自动续期</span>';
        } else if (p.auth_type === 'password') {
            authHint = '<span class="text-xs text-slate-500">账号密码登录，自动获取 Token</span>';
        } else if (p.auth_type === 'password_cookie') {
            authHint = '<span class="text-xs text-slate-500">优先账号密码登录；如触发验证码/短信/设备锁，可保留 Cookie 备用</span>';
        } else {
            authHint = '<span class="text-xs text-slate-500">从浏览器复制 Cookie</span>';
        }

        const tags = [];
        if (p.supports_share_receive) tags.push('分享转存');
        if (p.supports_offline) tags.push('离线下载');
        if (p.supports_strm) tags.push('STRM');
        const tagsHtml = tags.length ? '<span class="text-xs text-slate-500 ml-2">' + tags.join(' · ') + '</span>' : '';

        const statusDot = isConfigured
            ? '<span class="w-2 h-2 rounded-full bg-emerald-400 inline-block ml-1" title="已配置"></span>'
            : '<span class="w-2 h-2 rounded-full bg-slate-600 inline-block ml-1" title="未配置"></span>';

        return '<div class="provider-auth-block mb-3 bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden">' +
            '<div class="flex items-center justify-between p-3 cursor-pointer" onclick="toggleProviderBlock(\'' + p.name + '\')">' +
                '<div class="flex items-center gap-3">' +
                    '<span class="text-sm text-slate-200">' + p.label + '</span>' +
                    statusDot +
                    tagsHtml +
                '</div>' +
                '<label class="relative inline-flex items-center cursor-pointer" onclick="event.stopPropagation()">' +
                    '<input type="checkbox" id="provider_enabled_' + p.name + '" ' + (enabled ? 'checked' : '') + ' onchange="toggleProviderEnabled(\'' + p.name + '\', this.checked)" class="sr-only peer">' +
                    '<div class="provider-toggle w-9 h-5 bg-slate-600 rounded-full peer peer-checked:bg-emerald-500/70 peer-focus:ring-2 peer-focus:ring-emerald-400/30 after:content-[\'\'] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full"></div>' +
                '</label>' +
            '</div>' +
            '<div id="provider-block-body-' + p.name + '" class="p-3 pt-0 border-t border-slate-700/50 hidden">' +
                authHint +
                (p.auth_type === 'password'
                    ? ('<input id="' + cookieKey + '" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-2" placeholder="' + placeholder + '">' +
                       '<input id="' + passwordKey + '" type="password" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-2" placeholder="输入 ' + p.label + ' 密码">')
                    : p.auth_type === 'password_cookie'
                    ? ('<input id="' + mixedUsernameKey + '" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-2" placeholder="输入 ' + p.label + ' 账号">' +
                       '<input id="' + mixedPasswordKey + '" type="password" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-2" placeholder="输入 ' + p.label + ' 密码">' +
                       '<textarea id="' + cookieKey + '" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-2 font-mono" rows="3" placeholder="' + placeholder + '"></textarea>')
                    : '<textarea id="' + cookieKey + '" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-2 font-mono" rows="3" placeholder="' + placeholder + '"></textarea>') +
                '<div class="mt-2 flex items-center gap-2">' +
                    '<button type="button" onclick="testProviderCookie(\'' + p.name + '\')" class="text-xs text-slate-400 hover:text-slate-200 bg-slate-700 hover:bg-slate-600 px-3 py-1 rounded-lg transition-colors">健康检查</button>' +
                    '<span id="provider-health-' + p.name + '" class="text-xs text-slate-500"></span>' +
                '</div>' +
            '</div>' +
        '</div>';
    }).join('');
}

function toggleProviderBlock(name) {
    const body = document.getElementById('provider-block-body-' + name);
    if (body) body.classList.toggle('hidden');
}

function toggleProviderEnabled(name, checked) {
    window._providerEnabledChanged = true;
}

async function testProviderCookie(name) {
    const meta = window.providerMeta || [];
    const p = meta.find(m => m.name === name);
    if (!p) return;
    const cookieKey = p.config_keys[0] || 'cookie_' + name;
    const credentials = {};
    (Array.isArray(p.config_keys) ? p.config_keys : [cookieKey]).forEach((key) => {
        credentials[key] = String(document.getElementById(key)?.value || '').trim();
    });
    const cookie = String(credentials[cookieKey] || '').trim();
    const hasCurrentInput = p.auth_type === 'password'
        ? (Array.isArray(p.config_keys) ? p.config_keys : [cookieKey]).every(key => String(credentials[key] || '').trim())
        : p.auth_type === 'password_cookie'
        ? (!!cookie || (!!String(credentials[p.config_keys?.[1]] || '').trim() && !!String(credentials[p.config_keys?.[2]] || '').trim()))
        : !!cookie;
    const statusEl = document.getElementById('provider-health-' + name);
    if (statusEl) { statusEl.textContent = '检测中...'; statusEl.className = 'text-xs text-slate-500'; }
    if (!hasCurrentInput) {
        let result = null;
        if (typeof window.checkCookieHealthProvider === 'function') {
            result = await window.checkCookieHealthProvider(name);
        }
        if (statusEl) {
            const entry = latestCookieHealthState?.[name] || {};
            const tone = getCookieHealthResultTone(entry);
            const rawMessage = result && typeof result === 'object' && result.message
                ? String(result.message)
                : getCookieHealthResultText(entry, name);
            const labelPrefix = `${getCookieHealthProviderLabel(name)}：`;
            const message = rawMessage.startsWith(labelPrefix) ? rawMessage.slice(labelPrefix.length) : rawMessage;
            statusEl.textContent = message;
            statusEl.className = 'text-xs ' + (
                tone === 'success' ? 'text-emerald-400' :
                tone === 'error' ? 'text-red-400' :
                tone === 'warn' ? 'text-amber-300' : 'text-slate-500'
            );
        }
        return;
    }
    try {
        const resp = await window.MediaHubApi.postJson('/test_provider_cookie', { provider: name, cookie: cookie, credentials });
        if (statusEl) {
            statusEl.textContent = resp && resp.ok ? '✓ ' + ((resp && resp.message) || '当前输入可用，保存后生效') : '✗ ' + ((resp && resp.error) || '连接失败');
            statusEl.className = 'text-xs ' + (resp && resp.ok ? 'text-emerald-400' : 'text-red-400');
        }
    } catch (e) {
        if (statusEl) { statusEl.textContent = '✗ 请求失败'; statusEl.className = 'text-xs text-red-400'; }
    }
}

export function renderMagnetProviderSetting(cfg) {
    const container = document.getElementById('settings-magnet-provider-container');
    if (!container) return;
    const meta = window.providerMeta || [];
    const pan115 = meta.find(p => p.name === '115');
    const label = pan115?.label || '115网盘';
    const stagingRoot = String(cfg?.magnet_staging_root || '').trim() || '云下载/磁力中转';

    container.innerHTML = `
        <div class="provider-auth-block mb-3 bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden">
            <div class="flex items-center justify-between p-3">
                <div class="flex items-center gap-3">
                    <span class="text-sm text-slate-200">离线下载网盘</span>
                    <span class="text-xs text-slate-500">磁力、电驴链接仅支持</span>
                </div>
                <input id="default_magnet_provider" type="hidden" value="115">
                <span class="px-3 py-1.5 rounded-lg bg-slate-700 border border-slate-600 text-sm text-slate-200">${label}</span>
            </div>
            <label class="block p-3 pt-0">
                <span class="text-xs text-slate-500">磁力中转目录（115 离线下载先落到这里，命中文件再移动入库）</span>
                <input id="magnet_staging_root" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-1" value="${escapeHtml(stagingRoot)}" placeholder="云下载/磁力中转">
            </label>
        </div>
    `;
}

export async function saveSettings({
    sensitiveSettingFields = [],
    getSensitiveConfigMeta,
    applySensitiveConfigMeta,
    applyCookieHealthState,
    refreshResourceState,
    refreshSign115Status,
    getMonitorTasks,
    showToast,
} = {}) {
    const cfg = collectSettingsPayload({
        sensitiveSettingFields,
        getMonitorTasks,
    });
    let data = null;
    try {
        data = await window.MediaHubApi.postJson('/save_settings', cfg);
    } catch (error) {
        if (typeof showToast === 'function') {
            showToast(`保存失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
        }
        return false;
    }

    if (data?.ok) {
        if (data?.cookie_health && typeof applyCookieHealthState === 'function') {
            applyCookieHealthState(data.cookie_health);
        }
        const nextSensitiveMeta = {
            ...(typeof getSensitiveConfigMeta === 'function' ? getSensitiveConfigMeta() : {})
        };
        (Array.isArray(sensitiveSettingFields) ? sensitiveSettingFields : []).forEach((key) => {
            const value = String(document.getElementById(key)?.value || '').trim();
            if (value) nextSensitiveMeta[key] = true;
        });
        if (typeof applySensitiveConfigMeta === 'function') {
            applySensitiveConfigMeta(nextSensitiveMeta);
        }
        if (typeof showToast === 'function') {
            showToast('配置已保存', { tone: 'success', duration: 2400, placement: 'top-center' });
        }
        if (typeof refreshResourceState === 'function') void refreshResourceState({ allowSearch: false });
        if (typeof refreshSign115Status === 'function') void refreshSign115Status(false);
        return true;
    }

    if (typeof showToast === 'function') {
        showToast(`保存失败：${data?.msg || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
    }
    return false;
}

function getCookieHealthDotColor(state) {
    if (state === 'valid') return '#10b981';
    if (state === 'invalid' || state === 'error') return '#ef4444';
    if (state === 'checking') return '#0ea5e9';
    if (state === 'missing') return '#f59e0b';
    if (state === 'disabled') return '#64748b';
    return '#64748b';
}

function getEnabledCookieHealthProviders(providers = null) {
    const meta = window.providerMeta || [];
    const enabledProviders = meta.filter(p => p.enabled !== false);
    const explicitProviders = Array.isArray(providers) && providers.length;
    const source = explicitProviders
        ? providers
        : enabledProviders.map(p => p.name);
    const names = [];
    source.forEach((item) => {
        const name = String(item || '').trim();
        if (!name || names.includes(name)) return;
        const provider = meta.find(p => p.name === name);
        if (provider && provider.enabled === false) return;
        names.push(name);
    });
    if (names.length) return names;
    return explicitProviders ? [] : ['115', 'quark'];
}

function getCookieHealthProviderLabel(name) {
    const provider = (window.providerMeta || []).find(p => p.name === name);
    return String(provider?.label || name || '').trim();
}

function getCookieHealthResultTone(entry) {
    const state = String(entry?.state || '').trim().toLowerCase();
    if (state === 'valid') return 'success';
    if (state === 'invalid' || state === 'error') return 'error';
    if (state === 'missing' || state === 'unknown') return 'warn';
    return 'info';
}

function getCookieHealthResultText(entry, providerName) {
    const label = getCookieHealthProviderLabel(providerName);
    const source = entry && typeof entry === 'object' ? entry : {};
    const message = String(source.message || '').trim();
    if (message) return message;
    const state = String(source.state || '').trim().toLowerCase();
    if (state === 'valid') return `${label} 认证信息可用`;
    if (state === 'invalid') return `${label} 认证信息可能已失效`;
    if (state === 'error') return `${label} 认证检测异常`;
    if (state === 'missing') return `未配置 ${label} 认证信息`;
    if (state === 'checking') return `正在检测 ${label} 认证信息...`;
    return `${label} 认证状态未知`;
}

function summarizeCookieHealthResults(cookieHealthState, providerNames) {
    const state = cookieHealthState && typeof cookieHealthState === 'object' ? cookieHealthState : {};
    const names = Array.isArray(providerNames) ? providerNames : [];
    const results = names.map((name) => {
        const entry = state[name] && typeof state[name] === 'object' ? state[name] : {};
        return {
            provider: name,
            label: getCookieHealthProviderLabel(name),
            state: String(entry.state || '').trim().toLowerCase(),
            tone: getCookieHealthResultTone(entry),
            message: getCookieHealthResultText(entry, name),
        };
    });
    const failing = results.filter(item => item.tone === 'error');
    const pending = results.filter(item => item.tone === 'warn');
    const valid = results.filter(item => item.tone === 'success');
    let tone = 'success';
    if (failing.length) tone = 'error';
    else if (pending.length) tone = 'warning';
    const detailItems = failing.length ? failing : (pending.length ? pending : results);
    const detail = detailItems
        .slice(0, 3)
        .map(item => item.message)
        .filter(Boolean)
        .join('；');
    const prefix = names.length === 1
        ? `${results[0]?.label || getCookieHealthProviderLabel(names[0])}：`
        : `健康检查：${valid.length} 个可用，${pending.length} 个待处理，${failing.length} 个异常。`;
    return {
        ok: failing.length === 0,
        tone,
        results,
        message: `${prefix}${detail}`,
    };
}

function getCookieHealthChipTone(state, provider) {
    if (provider?.enabled === false) return 'disabled';
    if (state === 'valid') return 'valid';
    if (state === 'invalid' || state === 'error') return 'error';
    if (state === 'checking') return 'checking';
    if (state === 'missing' || state === 'unknown') return 'pending';
    return 'idle';
}

function buildCookieHealthCheckingState(sourceState, providers) {
    const state = sourceState && typeof sourceState === 'object' ? sourceState : {};
    const nextState = { ...state };
    providers.forEach((name) => {
        const entry = state[name] && typeof state[name] === 'object' ? state[name] : {};
        const label = getCookieHealthProviderLabel(name);
        nextState[name] = {
            configured: !!entry.configured,
            state: 'checking',
            message: `正在检测 ${label} 认证信息...`,
            last_checked_at: String(entry.last_checked_at || ''),
            last_success_at: String(entry.last_success_at || ''),
            trigger: 'manual_check',
            fail_count: Math.max(0, Number(entry.fail_count || 0) || 0),
        };
    });
    return nextState;
}

export async function checkCookieHealthProviders({
    providers = null,
    force = true,
    isBusy = false,
    setBusy,
    renderCookieHealthCards,
    getCookieHealthState,
    applyCookieHealthState,
    showToast,
} = {}) {
    if (isBusy || cookieHealthBusyProviders.size > 0) return false;
    const providerNames = getEnabledCookieHealthProviders(providers);
    if (!providerNames.length) return false;
    providerNames.forEach(name => cookieHealthBusyProviders.add(name));
    const previousState = typeof getCookieHealthState === 'function'
        ? getCookieHealthState()
        : latestCookieHealthState;
    const checkingState = buildCookieHealthCheckingState(previousState, providerNames);
    if (typeof setBusy === 'function') setBusy(true);
    if (typeof applyCookieHealthState === 'function') applyCookieHealthState(checkingState);
    else updateCookieHealthBar(checkingState);
    if (typeof renderCookieHealthCards === 'function') renderCookieHealthCards();

    try {
        const data = await window.MediaHubApi.postJson('/settings/cookies/check', {
            providers: providerNames,
            force: !!force
        });
        const nextState = data?.cookie_health && typeof data.cookie_health === 'object'
            ? data.cookie_health
            : previousState;
        if (data?.cookie_health && typeof applyCookieHealthState === 'function') {
            applyCookieHealthState(data.cookie_health);
        } else if (data?.cookie_health) {
            updateCookieHealthBar(data.cookie_health);
        }
        const summary = summarizeCookieHealthResults(nextState, providerNames);
        if (typeof showToast === 'function') {
            showToast(summary.message, { tone: summary.tone, duration: summary.ok ? 2600 : 4200, placement: 'top-center' });
        }
        return { ...summary, cookie_health: nextState };
    } catch (err) {
        if (typeof applyCookieHealthState === 'function') applyCookieHealthState(previousState);
        else updateCookieHealthBar(previousState);
        if (typeof showToast === 'function') {
            showToast(`健康检查失败：${err?.message || '请稍后重试'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
        }
        return {
            ok: false,
            tone: 'error',
            results: [],
            message: err?.message || '健康检查失败',
            cookie_health: previousState,
        };
    } finally {
        providerNames.forEach(name => cookieHealthBusyProviders.delete(name));
        if (typeof setBusy === 'function') setBusy(false);
        if (typeof renderCookieHealthCards === 'function') renderCookieHealthCards();
        updateCookieHealthBar(latestCookieHealthState);
    }
}

export function renderCookieHealthBar(cookieHealthState) {
    const container = document.getElementById('settings-provider-auth-container');
    if (!container) return;
    const meta = window.providerMeta || [];
    if (!meta.length) return;
    let bar = document.getElementById('cookie-health-bar');
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'cookie-health-bar';
        bar.className = 'cookie-health-bar';
        bar.innerHTML = '<div id="cookie-health-dots" class="cookie-health-chips"></div>' +
            '<button id="cookie-health-check-all-btn" type="button" class="cookie-health-check-all-btn">健康检查</button>';
        container.insertBefore(bar, container.firstChild);
        const chipsContainer = bar.querySelector('#cookie-health-dots');
        if (chipsContainer) {
            chipsContainer.addEventListener('click', (event) => {
                const chip = event.target.closest('[data-cookie-health-provider]');
                if (!chip || chip.disabled) return;
                const provider = chip.getAttribute('data-cookie-health-provider');
                if (typeof window.checkCookieHealthProvider === 'function') {
                    window.checkCookieHealthProvider(provider);
                }
            });
        }
        const checkBtn = bar.querySelector('#cookie-health-check-all-btn');
        if (checkBtn) {
            checkBtn.addEventListener('click', () => {
                if (typeof window.checkAllCookiesHealth === 'function') {
                    window.checkAllCookiesHealth();
                }
            });
        }
    }
    updateCookieHealthBar(cookieHealthState);
}

export function updateCookieHealthBar(cookieHealthState) {
    const dotsContainer = document.getElementById('cookie-health-dots');
    const checkBtn = document.getElementById('cookie-health-check-all-btn');
    if (!dotsContainer) return;
    const state = cookieHealthState && typeof cookieHealthState === 'object' ? cookieHealthState : {};
    latestCookieHealthState = state;
    const meta = window.providerMeta || [];
    let busy = false;
    dotsContainer.innerHTML = meta.map(p => {
        const entry = state[p.name] || {};
        const dotState = cookieHealthBusyProviders.has(p.name)
            ? 'checking'
            : (entry.state || (entry.configured ? 'unknown' : 'missing'));
        const color = getCookieHealthDotColor(dotState);
        const tone = getCookieHealthChipTone(dotState, p);
        if (dotState === 'checking') busy = true;
        const label = escapeHtml(p.label || p.name);
        const title = escapeHtml(entry.message || (p.enabled === false ? `${p.label || p.name} 未启用` : '点击检查'));
        const disabled = p.enabled === false || cookieHealthBusyProviders.size > 0;
        return '<button type="button" class="cookie-health-chip cookie-health-chip--' + tone + '" ' +
            'data-cookie-health-provider="' + escapeHtml(p.name) + '" ' +
            'title="' + title + '" ' +
            'aria-label="检查 ' + label + ' 健康状态" ' +
            (disabled ? 'disabled' : '') + '>' +
            '<span class="cookie-health-chip-dot" style="background:' + color + ';' + (dotState === 'checking' ? 'animation:cookie-dot-pulse 1s ease-in-out infinite' : '') + '"></span>' +
            '<span class="cookie-health-chip-label">' + label + '</span>' +
            '</button>';
    }).join('');
    if (checkBtn) {
        checkBtn.disabled = busy;
        checkBtn.classList.toggle('is-busy', busy);
        checkBtn.innerText = busy ? '检查中…' : '健康检查';
    }
}

// Register functions to global scope for boot.js
if (typeof window !== 'undefined') {
    window.renderProviderAuthBlocks = renderProviderAuthBlocks;
    window.renderMagnetProviderSetting = renderMagnetProviderSetting;
    window.renderResourceFavoriteDirSettings = renderResourceFavoriteDirSettings;
    window.toggleProviderBlock = toggleProviderBlock;
    window.toggleProviderEnabled = toggleProviderEnabled;
    window.testProviderCookie = testProviderCookie;
    window.renderCookieHealthBar = renderCookieHealthBar;
    window.updateCookieHealthBar = updateCookieHealthBar;
    window.checkCookieHealthProviders = checkCookieHealthProviders;
    window.checkAllCookiesHealth = async function() {
        if (typeof window.checkCookiesNow === 'function') return window.checkCookiesNow(true);
        return checkCookieHealthProviders();
    };
    window.checkCookieHealthProvider = async function(provider) {
        if (typeof window.checkCookiesNow === 'function') return window.checkCookiesNow(true, [provider]);
        return checkCookieHealthProviders({ providers: [provider] });
    };
}
