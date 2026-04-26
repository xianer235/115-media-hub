export async function ensureTabData(context) {
    context.moduleVisitState.settings = true;
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
        'cron_hour',
        'sync_mode',
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

    cfg.check_hash = !!document.getElementById('check_hash')?.checked;
    cfg.sync_clean = !!document.getElementById('sync_clean')?.checked;
    cfg.sign115_enabled = !!document.getElementById('sign115_enabled')?.checked;
    cfg.tg_proxy_enabled = !!document.getElementById('tg_proxy_enabled')?.checked;
    cfg.notify_push_enabled = !!document.getElementById('notify_push_enabled')?.checked;
    cfg.notify_monitor_enabled = !!document.getElementById('notify_monitor_enabled')?.checked;
    cfg.tmdb_enabled = !!document.getElementById('tmdb_enabled')?.checked;

    const rawTmdbCacheTtl = parseInt(document.getElementById('tmdb_cache_ttl_hours')?.value || '', 10);
    cfg.tmdb_cache_ttl_hours = Math.min(720, Math.max(1, Number.isFinite(rawTmdbCacheTtl) ? rawTmdbCacheTtl : 24));

    const rawTgThreads = parseInt(document.getElementById('tg_channel_threads')?.value || '', 10);
    cfg.tg_channel_threads = Math.min(20, Math.max(1, Number.isFinite(rawTgThreads) ? rawTgThreads : 6));

    cfg.monitor_tasks = typeof getMonitorTasks === 'function' ? (getMonitorTasks() || []) : [];
    cfg.trees = [];

    document.querySelectorAll('.tree-row').forEach((row) => {
        const path = row.querySelector('.t-url')?.value?.trim();
        if (!path) return;
        cfg.trees.push({
            source_type: 'tree_file',
            path,
            prefix: row.querySelector('.t-prefix')?.value?.trim() || '',
            exclude: parseInt(row.querySelector('.t-exclude')?.value || '1', 10) || 1
        });
    });

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
    isBusy = false,
    setBusy,
    renderCookieHealthCards,
    applyCookieHealthState,
    showToast,
} = {}) {
    if (isBusy) return;
    if (typeof setBusy === 'function') setBusy(true);
    if (typeof renderCookieHealthCards === 'function') renderCookieHealthCards();
    try {
        const data = await window.MediaHubApi.postJson('/settings/cookies/check', {
            providers: ['115', 'quark'],
            force: !!force
        });
        if (data?.cookie_health && typeof applyCookieHealthState === 'function') {
            applyCookieHealthState(data.cookie_health);
        }
        if (typeof showToast === 'function') {
            showToast('Cookie 检测已完成', { tone: 'success', duration: 2200, placement: 'top-center' });
        }
    } catch (err) {
        if (typeof showToast === 'function') {
            showToast(`Cookie 检测失败：${err?.message || '请稍后重试'}`, { tone: 'error', duration: 3000, placement: 'top-center' });
        }
    } finally {
        if (typeof setBusy === 'function') setBusy(false);
        if (typeof renderCookieHealthCards === 'function') renderCookieHealthCards();
    }
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

export async function saveSettings({
    sensitiveSettingFields = [],
    getSensitiveConfigMeta,
    applySensitiveConfigMeta,
    applyCookieHealthState,
    refreshResourceState,
    refreshSign115Status,
    getMonitorTasks,
} = {}) {
    const cfg = collectSettingsPayload({
        sensitiveSettingFields,
        getMonitorTasks,
    });
    let data = null;
    try {
        data = await window.MediaHubApi.postJson('/save_settings', cfg);
    } catch (error) {
        window.alert(`❌ ${error?.message || '保存失败'}`);
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
        window.alert('✅ 配置已保存');
        if (typeof refreshResourceState === 'function') void refreshResourceState({ allowSearch: false });
        if (typeof refreshSign115Status === 'function') void refreshSign115Status(false);
        return true;
    }

    window.alert(`❌ ${data?.msg || '保存失败'}`);
    return false;
}
