// ==UserScript==
// @name         115云盘磁力助手 Webhook 增强版
// @namespace    http://tampermonkey.net/
// @version      1.8
// @description  自动捕捉页面磁力链接并保存至115云盘, 可选择已有文件夹保存并按目录触发 webhook
// @author       原作者：天黑了；本地定制：xianer
// @copyright    原始脚本版权归原作者“天黑了”所有；当前版本为基于原脚本的本地定制修改版
// @license      MIT
// @match        *://*/*
// @connect      115.com
// @connect      *
// @grant        GM_xmlhttpRequest
// @grant        GM_notification
// @grant        GM_log
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        window.Notification
// @run-at       document-end
// @homepage     https://github.com/tianheil3/115-magnet-helper
// @supportURL   https://github.com/tianheil3/115-magnet-helper/issues
// ==/UserScript==

(function() {
    'use strict';

    const APP_NAME = '115云盘磁力助手 Webhook 增强版';
    console.log(`${APP_NAME} 已加载 (v1.8)`);
    // 备注：
    // 1. 本脚本基于原作者“天黑了”的 115 磁力助手做本地二次定制。
    // 2. 本地定制内容主要包括：文件夹级 webhook 映射、延迟时间配置、管理界面、测试触发。
    // 3. 由于当前版本未单独托管发布，因此移除了 downloadURL/updateURL，避免误指向原始发布链接。
    
    // 调试函数
    function debug(msg, ...args) {
        console.log(`[115助手] ${msg}`, ...args);
    }

    // 匹配磁力链接的正则表达式
    const magnetRegex = /magnet:\?xt=urn:btih:[a-zA-Z0-9]{32,40}/gi;
    const WEBHOOK_RULES_KEY = 'magnet_helper_webhook_rules_v1';
    const ROOT_FOLDER = { id: '0', name: '根目录' };
    const TOAST_CONTAINER_ID = 'magnet-helper-toast-container';

    // 修改115图标的SVG，使用文字"115"
    const icon115 = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16">
        <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" 
            fill="white" font-family="Arial" font-weight="bold" font-size="10">115</text>
    </svg>`;

    // 修改按钮样式，移除定位相关的属性
    const buttonStyle = `
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 26px;
        background-color: #2777F8;
        border-radius: 50%;
        cursor: pointer;
        margin-left: 5px;
        color: white;
        font-family: Arial, sans-serif;
        font-size: 11px;
        font-weight: bold;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
        opacity: 0.9;
        user-select: none;
        vertical-align: middle;
    `;

    // 存储已创建的按钮
    const createdButtons = new Set();
    let webhookRulesCache = loadWebhookRules();

    // 创建一个通用的通知函数
    function showNotification(title, text, isWarning = false) {
        debug('准备显示通知:', { title, text, isWarning });
        
        // 直接使用 alert 显示通知
        setTimeout(() => {
            window.alert(`${title}\n${text}`);
        }, 100);

        // 同时尝试使用 GM_notification
        try {
            GM_notification({
                title: title,
                text: text,
                timeout: isWarning ? 3000 : 5000,
                onclick: () => debug('通知被点击了')
            });
            debug('GM_notification 已调用');
        } catch (e) {
            debug('GM_notification 调用失败:', e);
        }
    }

    function getToastContainer() {
        let container = document.getElementById(TOAST_CONTAINER_ID);
        if (container) return container;

        container = document.createElement('div');
        container.id = TOAST_CONTAINER_ID;
        container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10001;
            display: flex;
            flex-direction: column;
            gap: 10px;
            pointer-events: none;
            max-width: min(420px, calc(100vw - 24px));
        `;
        document.body.appendChild(container);
        return container;
    }

    function showSuccessToast(title, text, duration = 2600) {
        debug('显示自动消失提示:', { title, text, duration });
        const container = getToastContainer();
        const toast = document.createElement('div');
        toast.style.cssText = `
            background: linear-gradient(135deg, rgba(15, 118, 110, 0.96), rgba(21, 128, 61, 0.96));
            color: #ecfeff;
            border-radius: 12px;
            box-shadow: 0 14px 32px rgba(0, 0, 0, 0.28);
            border: 1px solid rgba(204, 251, 241, 0.22);
            padding: 14px 16px;
            font-family: Arial, sans-serif;
            line-height: 1.6;
            white-space: pre-wrap;
            opacity: 0;
            transform: translateY(-8px);
            transition: opacity 0.22s ease, transform 0.22s ease;
        `;
        toast.innerHTML = `<div style="font-weight:bold;margin-bottom:4px;">${escapeHtml(title)}</div><div style="font-size:13px;">${escapeHtml(text)}</div>`;
        container.appendChild(toast);

        requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        });

        window.setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-8px)';
            window.setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
                if (container.childElementCount === 0 && container.parentNode) {
                    container.parentNode.removeChild(container);
                }
            }, 240);
        }, Math.max(2000, duration));
    }

    function normalizeFolderId(folderId) {
        if (folderId === null || typeof folderId === 'undefined' || folderId === '') {
            return '0';
        }
        return String(folderId);
    }

    function normalizeFolder(folder) {
        if (typeof folder === 'object' && folder !== null) {
            return {
                id: normalizeFolderId(folder.id),
                name: String(folder.name || '').trim() || (normalizeFolderId(folder.id) === '0' ? '根目录' : `文件夹 ${normalizeFolderId(folder.id)}`)
            };
        }
        return {
            id: normalizeFolderId(folder),
            name: normalizeFolderId(folder) === '0' ? '根目录' : `文件夹 ${normalizeFolderId(folder)}`
        };
    }

    function normalizeWebhookRule(rule) {
        const folderId = normalizeFolderId(rule && rule.folderId);
        const delaySeconds = Math.max(0, parseInt(rule && rule.delaySeconds, 10) || 0);
        return {
            folderId,
            folderName: String((rule && rule.folderName) || (folderId === '0' ? '根目录' : '')).trim(),
            webhookUrl: String((rule && rule.webhookUrl) || '').trim(),
            delaySeconds,
            enabled: Boolean(rule && rule.enabled)
        };
    }

    function readStoredValue(key, fallbackValue) {
        try {
            if (typeof GM_getValue === 'function') {
                const stored = GM_getValue(key, fallbackValue);
                return typeof stored === 'undefined' ? fallbackValue : stored;
            }
        } catch (e) {
            debug('读取 GM_getValue 失败，回退 localStorage:', e);
        }

        try {
            const raw = window.localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallbackValue;
        } catch (e) {
            debug('读取 localStorage 失败:', e);
            return fallbackValue;
        }
    }

    function writeStoredValue(key, value) {
        try {
            if (typeof GM_setValue === 'function') {
                GM_setValue(key, value);
                return;
            }
        } catch (e) {
            debug('写入 GM_setValue 失败，回退 localStorage:', e);
        }

        try {
            window.localStorage.setItem(key, JSON.stringify(value));
        } catch (e) {
            debug('写入 localStorage 失败:', e);
        }
    }

    function loadWebhookRules() {
        const stored = readStoredValue(WEBHOOK_RULES_KEY, []);
        const rawRules = Array.isArray(stored) ? stored : [];
        const seen = new Set();
        return rawRules
            .map(normalizeWebhookRule)
            .filter(rule => {
                if (seen.has(rule.folderId)) return false;
                seen.add(rule.folderId);
                return true;
            });
    }

    function persistWebhookRules(rules) {
        const uniqueRules = [];
        const seen = new Set();
        rules
            .map(normalizeWebhookRule)
            .forEach(rule => {
                if (seen.has(rule.folderId)) return;
                seen.add(rule.folderId);
                uniqueRules.push(rule);
            });
        webhookRulesCache = uniqueRules;
        writeStoredValue(WEBHOOK_RULES_KEY, uniqueRules);
    }

    function getWebhookRuleForFolder(folderId) {
        const normalizedId = normalizeFolderId(folderId);
        return webhookRulesCache.find(rule => rule.folderId === normalizedId) || null;
    }

    function escapeHtml(text) {
        const value = String(text || '');
        return value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function isValidWebhookUrl(url) {
        return /^https?:\/\/\S+/i.test(String(url || '').trim());
    }

    function buildFolderCatalog(folders = []) {
        const folderMap = new Map();
        folderMap.set(ROOT_FOLDER.id, { ...ROOT_FOLDER });

        folders.forEach(folder => {
            const normalized = normalizeFolder(folder);
            folderMap.set(normalized.id, normalized);
        });

        webhookRulesCache.forEach(rule => {
            if (!folderMap.has(rule.folderId)) {
                folderMap.set(rule.folderId, {
                    id: rule.folderId,
                    name: rule.folderName || `文件夹 ${rule.folderId}`
                });
            }
        });

        return Array.from(folderMap.values()).sort((a, b) => {
            if (a.id === '0') return -1;
            if (b.id === '0') return 1;
            return a.name.localeCompare(b.name, 'zh-Hans-CN');
        });
    }

    function formatWebhookRuleLabel(rule) {
        if (!rule || !rule.webhookUrl) return '';
        const status = rule.enabled ? '已启用' : '已停用';
        return `${status} webhook · 延迟 ${rule.delaySeconds} 秒`;
    }

    async function postWebhook(url, payload) {
        return new Promise((resolve) => {
            GM_xmlhttpRequest({
                method: 'POST',
                url,
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/plain, */*'
                },
                data: JSON.stringify(payload),
                timeout: 15000,
                onload: function(response) {
                    const ok = response.status >= 200 && response.status < 300;
                    resolve({
                        ok,
                        status: response.status,
                        body: String(response.responseText || '')
                    });
                },
                onerror: function(error) {
                    resolve({
                        ok: false,
                        status: 0,
                        body: String((error && (error.error || error.message)) || '网络请求失败')
                    });
                },
                ontimeout: function() {
                    resolve({
                        ok: false,
                        status: 0,
                        body: '请求超时'
                    });
                }
            });
        });
    }

    async function triggerWebhookForFolder(folder, magnetLink) {
        const normalizedFolder = normalizeFolder(folder);
        const rule = getWebhookRuleForFolder(normalizedFolder.id);

        if (!rule || !rule.enabled || !rule.webhookUrl) {
            return { configured: false, ok: true, message: '' };
        }

        const payload = {
            delayTime: rule.delaySeconds,
            title: getDisplayNameFromMagnet(magnetLink) || '',
            folderId: normalizedFolder.id,
            folderName: normalizedFolder.name
        };

        debug('准备触发 webhook:', { folder: normalizedFolder, webhookUrl: rule.webhookUrl, payload });

        const response = await postWebhook(rule.webhookUrl, payload);
        if (!response.ok) {
            debug('webhook 触发失败:', response.status, response.body);
        } else {
            debug('webhook 触发成功:', response.status, response.body);
        }
        return {
            configured: true,
            ok: response.ok,
            message: response.ok ? `已触发 webhook（延迟 ${rule.delaySeconds} 秒）` : `Webhook 触发失败：${response.status ? `HTTP ${response.status}` : response.body}`
        };
    }

    async function showWebhookManager() {
        const existingModal = document.getElementById('magnet-helper-webhook-manager');
        if (existingModal) {
            existingModal.remove();
        }

        const overlay = document.createElement('div');
        overlay.id = 'magnet-helper-webhook-manager';
        overlay.style.cssText = `
            position: fixed; inset: 0; z-index: 10000;
            background: rgba(0, 0, 0, 0.7);
            display: flex; align-items: center; justify-content: center;
            padding: 16px;
        `;

        const panel = document.createElement('div');
        panel.style.cssText = `
            width: min(860px, 100%);
            max-height: 92vh;
            overflow-y: auto;
            background: #0f172a;
            color: #e2e8f0;
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 14px;
            box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45);
            padding: 22px;
            font-family: Arial, sans-serif;
        `;

        panel.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;">
                <div>
                    <h3 style="margin:0;color:#60a5fa;font-size:20px;">文件夹 webhook 管理</h3>
                    <p style="margin:8px 0 0;color:#94a3b8;line-height:1.7;font-size:13px;">
                        给保存目标文件夹绑定一个 webhook 地址和延迟秒数。之后点击 115 按钮保存成功时，脚本会自动额外发送一次 POST 请求。
                    </p>
                </div>
                <button type="button" id="webhook-manager-close-top" style="border:none;background:#334155;color:#fff;border-radius:10px;padding:8px 14px;cursor:pointer;">关闭</button>
            </div>
            <div id="webhook-manager-loading" style="padding:22px 0;color:#cbd5e1;">正在加载 115 文件夹列表...</div>
            <div id="webhook-manager-body" style="display:none;"></div>
        `;

        overlay.appendChild(panel);
        document.body.appendChild(overlay);

        function closeManager() {
            overlay.remove();
        }

        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) {
                closeManager();
            }
        });
        panel.querySelector('#webhook-manager-close-top').addEventListener('click', closeManager);

        let folders = [];
        try {
            folders = await get115Folders();
        } catch (e) {
            debug('加载 webhook 管理文件夹失败:', e);
        }

        const loading = panel.querySelector('#webhook-manager-loading');
        const body = panel.querySelector('#webhook-manager-body');
        loading.style.display = 'none';
        body.style.display = 'block';

        const folderCatalog = buildFolderCatalog(folders);

        body.innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:18px;">
                <label style="display:block;">
                    <span style="display:block;font-size:13px;color:#bfdbfe;margin-bottom:6px;">保存文件夹</span>
                    <select id="webhook-folder-select" style="width:100%;padding:10px 12px;border-radius:10px;border:1px solid #334155;background:#020617;color:#e2e8f0;">
                        ${folderCatalog.map(folder => `<option value="${escapeHtml(folder.id)}">${escapeHtml(folder.name)}${folder.id === '0' ? ' (默认)' : ''}</option>`).join('')}
                    </select>
                </label>
                <label style="display:block;">
                    <span style="display:block;font-size:13px;color:#bfdbfe;margin-bottom:6px;">延迟秒数</span>
                    <input id="webhook-delay-input" type="number" min="0" value="0" style="width:100%;padding:10px 12px;border-radius:10px;border:1px solid #334155;background:#020617;color:#e2e8f0;">
                </label>
            </div>
            <label style="display:block;margin-top:14px;">
                <span style="display:block;font-size:13px;color:#bfdbfe;margin-bottom:6px;">Webhook 地址</span>
                <input id="webhook-url-input" type="url" placeholder="例如：http://127.0.0.1:18080/webhook/自存影视" style="width:100%;padding:10px 12px;border-radius:10px;border:1px solid #334155;background:#020617;color:#e2e8f0;">
            </label>
            <label style="display:flex;align-items:center;gap:8px;margin-top:14px;color:#cbd5e1;font-size:13px;">
                <input id="webhook-enabled-input" type="checkbox" checked>
                启用该文件夹的 webhook 触发
            </label>
            <div id="webhook-folder-meta" style="margin-top:12px;font-size:12px;color:#94a3b8;line-height:1.7;"></div>
            <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:18px;">
                <button type="button" id="webhook-save-btn" style="border:none;background:#2563eb;color:#fff;border-radius:10px;padding:10px 16px;cursor:pointer;">保存配置</button>
                <button type="button" id="webhook-test-btn" style="border:none;background:#0f766e;color:#ccfbf1;border-radius:10px;padding:10px 16px;cursor:pointer;">测试 webhook</button>
                <button type="button" id="webhook-delete-btn" style="border:none;background:#7c2d12;color:#fed7aa;border-radius:10px;padding:10px 16px;cursor:pointer;">删除当前文件夹配置</button>
                <button type="button" id="webhook-close-btn" style="border:none;background:#334155;color:#fff;border-radius:10px;padding:10px 16px;cursor:pointer;">关闭</button>
            </div>
            <div style="margin-top:24px;padding-top:18px;border-top:1px solid rgba(148, 163, 184, 0.16);">
                <h4 style="margin:0 0 12px;color:#93c5fd;font-size:15px;">当前映射</h4>
                <div id="webhook-rule-list" style="display:flex;flex-direction:column;gap:10px;"></div>
            </div>
        `;

        const folderSelect = body.querySelector('#webhook-folder-select');
        const urlInput = body.querySelector('#webhook-url-input');
        const delayInput = body.querySelector('#webhook-delay-input');
        const enabledInput = body.querySelector('#webhook-enabled-input');
        const folderMeta = body.querySelector('#webhook-folder-meta');
        const ruleList = body.querySelector('#webhook-rule-list');

        function getSelectedFolder() {
            const folder = folderCatalog.find(item => item.id === folderSelect.value);
            return normalizeFolder(folder || { id: folderSelect.value, name: '' });
        }

        function syncFormFromRule() {
            const folder = getSelectedFolder();
            const rule = getWebhookRuleForFolder(folder.id);
            urlInput.value = rule ? rule.webhookUrl : '';
            delayInput.value = rule ? String(rule.delaySeconds) : '0';
            enabledInput.checked = rule ? rule.enabled : true;
            folderMeta.innerHTML = rule
                ? `当前文件夹：<strong>${escapeHtml(folder.name)}</strong><br>状态：${escapeHtml(formatWebhookRuleLabel(rule) || '未配置')}`
                : `当前文件夹：<strong>${escapeHtml(folder.name)}</strong><br>状态：未配置`;
        }

        function renderRuleList() {
            if (!webhookRulesCache.length) {
                ruleList.innerHTML = '<div style="padding:14px;border:1px dashed #334155;border-radius:12px;color:#94a3b8;">还没有任何文件夹 webhook 配置。</div>';
                return;
            }

            ruleList.innerHTML = webhookRulesCache
                .map(rule => {
                    const folder = folderCatalog.find(item => item.id === rule.folderId) || { id: rule.folderId, name: rule.folderName || `文件夹 ${rule.folderId}` };
                    return `
                        <div data-folder-id="${escapeHtml(rule.folderId)}" style="border:1px solid rgba(148,163,184,0.18);border-radius:12px;padding:14px;background:#111827;">
                            <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start;">
                                <div style="min-width:0;flex:1;">
                                    <div style="font-weight:bold;color:#e2e8f0;">${escapeHtml(folder.name)}${rule.folderId === '0' ? ' (默认)' : ''}</div>
                                    <div style="margin-top:6px;color:#93c5fd;font-size:12px;">${escapeHtml(rule.webhookUrl)}</div>
                                    <div style="margin-top:6px;color:#94a3b8;font-size:12px;">${escapeHtml(formatWebhookRuleLabel(rule))}</div>
                                </div>
                                <button type="button" class="webhook-edit-btn" data-folder-id="${escapeHtml(rule.folderId)}" style="border:none;background:#1d4ed8;color:#fff;border-radius:10px;padding:8px 12px;cursor:pointer;">编辑</button>
                            </div>
                        </div>
                    `;
                })
                .join('');

            ruleList.querySelectorAll('.webhook-edit-btn').forEach(button => {
                button.addEventListener('click', () => {
                    folderSelect.value = button.getAttribute('data-folder-id') || '0';
                    syncFormFromRule();
                });
            });
        }

        folderSelect.addEventListener('change', syncFormFromRule);

        body.querySelector('#webhook-save-btn').addEventListener('click', () => {
            const folder = getSelectedFolder();
            const webhookUrl = urlInput.value.trim();
            const delaySeconds = Math.max(0, parseInt(delayInput.value || '0', 10) || 0);
            const enabled = enabledInput.checked;

            if (!webhookUrl) {
                window.alert('请先填写 webhook 地址');
                return;
            }
            if (!isValidWebhookUrl(webhookUrl)) {
                window.alert('Webhook 地址格式不正确，请使用 http:// 或 https:// 开头');
                return;
            }

            const nextRules = webhookRulesCache.filter(rule => rule.folderId !== folder.id);
            nextRules.push({
                folderId: folder.id,
                folderName: folder.name,
                webhookUrl,
                delaySeconds,
                enabled
            });
            persistWebhookRules(nextRules);
            syncFormFromRule();
            renderRuleList();
            showSuccessToast(APP_NAME, `已保存 ${folder.name} 的 webhook 配置`);
        });

        body.querySelector('#webhook-test-btn').addEventListener('click', async () => {
            const folder = getSelectedFolder();
            const webhookUrl = urlInput.value.trim();
            const delaySeconds = Math.max(0, parseInt(delayInput.value || '0', 10) || 0);

            if (!webhookUrl) {
                window.alert('请先填写 webhook 地址');
                return;
            }
            if (!isValidWebhookUrl(webhookUrl)) {
                window.alert('Webhook 地址格式不正确，请使用 http:// 或 https:// 开头');
                return;
            }

            const testButton = body.querySelector('#webhook-test-btn');
            const originalText = testButton.textContent;
            testButton.textContent = '测试中...';
            testButton.disabled = true;
            testButton.style.opacity = '0.7';

            const payload = {
                delayTime: delaySeconds,
                title: '115助手测试请求',
                folderId: folder.id,
                folderName: folder.name,
                event: 'test'
            };

            const response = await postWebhook(webhookUrl, payload);
            debug('测试 webhook 响应:', { webhookUrl, payload, response });

            testButton.textContent = originalText;
            testButton.disabled = false;
            testButton.style.opacity = '1';

            if (response.ok) {
                const bodyPreview = response.body ? `\n响应：${response.body.substring(0, 300)}` : '';
                showSuccessToast(APP_NAME, `测试成功\n目标：${folder.name}\n延迟：${delaySeconds} 秒${bodyPreview}`);
            } else {
                window.alert(`测试失败\n${response.status ? `HTTP ${response.status}` : response.body}`);
            }
        });

        body.querySelector('#webhook-delete-btn').addEventListener('click', () => {
            const folder = getSelectedFolder();
            const currentRule = getWebhookRuleForFolder(folder.id);
            if (!currentRule) {
                window.alert('当前文件夹还没有配置 webhook');
                return;
            }
            if (!window.confirm(`确定删除“${folder.name}”的 webhook 配置吗？`)) {
                return;
            }
            persistWebhookRules(webhookRulesCache.filter(rule => rule.folderId !== folder.id));
            syncFormFromRule();
            renderRuleList();
        });

        body.querySelector('#webhook-close-btn').addEventListener('click', closeManager);

        syncFormFromRule();
        renderRuleList();
    }

    // 解析磁力链接中的 dn 参数
    function getDisplayNameFromMagnet(magnetLink) {
        try {
            const urlParams = new URLSearchParams(magnetLink.substring(magnetLink.indexOf('?') + 1));
            const dn = urlParams.get('dn');
            if (dn) {
                // 解码并清理非法字符
                let decodedDn = decodeURIComponent(dn.replace(/\+/g, ' '));
                // 移除 Windows 文件名非法字符: \ / : * ? " < > |
                decodedDn = decodedDn.replace(/[\\/:*?"<>|]/g, '_');
                // 移除控制字符
                decodedDn = decodedDn.replace(/[\x00-\x1F\x7F]/g, '');
                // 移除首尾空格
                decodedDn = decodedDn.trim();
                // 避免文件名过长（115 可能有限制，暂定 200）
                return decodedDn.substring(0, 200);
            }
        } catch (e) {
            debug('解析 dn 参数失败:', e);
        }
        return null; // 如果没有 dn 参数或解析失败，返回 null
    }

    // 获取 115 文件夹列表 (目前只获取根目录下的)
    async function get115Folders() {
        return new Promise((resolve) => {
            debug('开始获取根目录文件夹列表');
            // 尝试简化 URL 参数，并减少 limit
            const apiUrl = 'https://aps.115.com/natsort/files.php?aid=1&cid=0&offset=0&limit=300&show_dir=1&natsort=1&format=json';
            GM_xmlhttpRequest({
                method: 'GET',
                // 使用 115 Web API 获取文件列表，cid=0 表示根目录
                // 参数可能随版本变化，limit 设置大一些以获取更多文件夹
                url: apiUrl, 
                headers: {
                    'Accept': 'application/json, text/javascript, */*; q=0.01',
                    'Referer': 'https://115.com/',
                    'User-Agent': window.navigator.userAgent
                },
                withCredentials: true,
                onload: function(response) {
                    try {
                        debug('获取文件夹列表 API 响应:', response.responseText.substring(0, 500) + '...'); // 避免日志过长
                        const result = JSON.parse(response.responseText);
                        if (result.state) {
                            // 115 API 返回的数据结构可能变化，这里尝试兼容常见的文件夹判断方式
                            const folders = result.data
                                // 主要判断方式：查找具有 cid (文件夹ID) 且 n (名称) 存在的项
                                // 可能需要结合其他字段，如 ico == 'folder'，或检查是否存在 pid (父ID)
                                // 更可靠的判断：有 cid 和 n，但没有 fid (文件ID) 和 sha1 (文件哈希)
                                .filter(item => item.cid && item.n && typeof item.fid === 'undefined' && typeof item.sha1 === 'undefined')
                                .map(item => ({ id: item.cid, name: item.n }));
                            debug('成功获取文件夹列表:', folders.length, '个');
                            resolve(folders); // 返回 {id, name} 数组
                        } else {
                            // 改进错误日志，包含 errNo
                            const errorDetail = `errNo: ${result.errNo}, error: "${result.error || ''}", msg: "${result.msg || 'N/A'}"`;
                            console.error(`获取文件夹列表失败: API返回 state:false, ${errorDetail}`);
                            resolve([]); // 返回空数组
                        }
                    } catch (error) {
                        console.error('解析文件夹列表响应失败:', error, response.responseText);
                        resolve([]); // 解析失败返回空数组
                    }
                },
                onerror: function(error) {
                    console.error('获取文件夹列表请求失败:', error);
                    resolve([]); // 请求失败返回空数组
                }
            });
        });
    }

    // 显示文件夹选择模态框
    async function showFolderSelector(magnetLink, buttonElement) {
        // --- 创建模态框基础结构 ---
        const modalOverlay = document.createElement('div');
        modalOverlay.id = 'magnet-helper-modal-overlay'; // 添加 ID 以便查找和移除
        modalOverlay.style.cssText = `
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background-color: rgba(0, 0, 0, 0.6); z-index: 9999;
            display: flex; justify-content: center; align-items: center;
        `;

        const modalContent = document.createElement('div');
        modalContent.style.cssText = `
            background-color: white; padding: 25px; border-radius: 8px;
            min-width: 300px; max-width: 80%; max-height: 80%;
            overflow-y: auto; box-shadow: 0 5px 15px rgba(0,0,0,0.3);
            color: #333; font-family: sans-serif; font-size: 14px;
        `;

        const title = document.createElement('h3');
        title.textContent = '选择保存位置';
        title.style.cssText = 'margin-top: 0; margin-bottom: 15px; color: #1E5AC8; border-bottom: 1px solid #eee; padding-bottom: 10px;';
        modalContent.appendChild(title);

        const helperBar = document.createElement('div');
        helperBar.style.cssText = 'display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap;';

        const helperText = document.createElement('div');
        helperText.textContent = '已配置 webhook 的目录会在保存成功后自动触发任务。';
        helperText.style.cssText = 'font-size: 12px; color: #666; line-height: 1.6;';
        helperBar.appendChild(helperText);

        const configButton = document.createElement('button');
        configButton.type = 'button';
        configButton.textContent = '管理 webhook';
        configButton.style.cssText = `
            padding: 6px 12px; background-color: #1E5AC8; color: white;
            border: none; border-radius: 4px; cursor: pointer; font-size: 12px;
        `;
        configButton.addEventListener('click', () => {
            closeModal();
            showWebhookManager().catch(error => {
                debug('打开 webhook 管理界面失败:', error);
                window.alert('打开 webhook 管理界面失败: ' + (error.message || '未知错误'));
            });
        });
        helperBar.appendChild(configButton);
        modalContent.appendChild(helperBar);

        const loadingText = document.createElement('p');
        loadingText.textContent = '正在加载文件夹列表...';
        modalContent.appendChild(loadingText);

        modalOverlay.appendChild(modalContent);
        document.body.appendChild(modalOverlay);

        // --- 获取并显示文件夹 ---
        try {
            const folders = await get115Folders();
            if (modalContent.contains(loadingText)) {
                 modalContent.removeChild(loadingText); // 移除加载提示
            }

            const list = document.createElement('ul');
            list.style.cssText = 'list-style: none; padding: 0; margin: 0 0 15px 0; max-height: 300px; overflow-y: auto;';

            // 添加 "根目录" 选项
            const rootOption = document.createElement('li');
            const rootRule = getWebhookRuleForFolder(ROOT_FOLDER.id);
            rootOption.textContent = rootRule && rootRule.webhookUrl
                ? `根目录 (默认) · ${formatWebhookRuleLabel(rootRule)}`
                : '根目录 (默认)';
            rootOption.style.cssText = 'padding: 8px 12px; cursor: pointer; border-radius: 4px; margin-bottom: 5px; background-color: #f0f0f0;';
            rootOption.addEventListener('mouseover', () => { rootOption.style.backgroundColor = '#e0e0e0'; });
            rootOption.addEventListener('mouseout', () => { rootOption.style.backgroundColor = '#f0f0f0'; });
            rootOption.addEventListener('click', () => {
                selectFolder(ROOT_FOLDER); // 根目录 ID 为 0
            });
            list.appendChild(rootOption);

            // 添加获取到的文件夹
            folders.forEach(folder => {
                const item = document.createElement('li');
                const normalizedFolder = normalizeFolder(folder);
                const rule = getWebhookRuleForFolder(normalizedFolder.id);
                item.textContent = rule && rule.webhookUrl
                    ? `${normalizedFolder.name} · ${formatWebhookRuleLabel(rule)}`
                    : normalizedFolder.name;
                item.title = rule && rule.webhookUrl
                    ? `${normalizedFolder.name}\n${rule.webhookUrl}\n延迟 ${rule.delaySeconds} 秒`
                    : normalizedFolder.name; // 防止名称过长显示不全
                item.style.cssText = 'padding: 8px 12px; cursor: pointer; border-radius: 4px; margin-bottom: 5px; background-color: #f9f9f9; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;';
                 item.addEventListener('mouseover', () => { item.style.backgroundColor = '#eee'; });
                 item.addEventListener('mouseout', () => { item.style.backgroundColor = '#f9f9f9'; });
                item.addEventListener('click', () => {
                    selectFolder(normalizedFolder);
                });
                list.appendChild(item);
            });
            modalContent.appendChild(list);

        } catch (error) { // 网络或其他错误导致 get115Folders reject
            if (modalContent.contains(loadingText)) {
                modalContent.removeChild(loadingText);
            }
            const errorText = document.createElement('p');
            errorText.textContent = '加载文件夹列表失败！将尝试保存到根目录。' + (error.message ? `(${error.message})` : '');
            errorText.style.color = 'red';
            modalContent.appendChild(errorText);
            // 自动选择根目录并关闭
            setTimeout(() => selectFolder(0), 2500);
        }

        // --- 添加取消按钮 ---
        const cancelButton = document.createElement('button');
        cancelButton.textContent = '取消';
        cancelButton.style.cssText = `
            padding: 8px 15px; background-color: #ccc; color: #333;
            border: none; border-radius: 4px; cursor: pointer; float: right;
        `;
        cancelButton.addEventListener('click', closeAndCancel);
        modalContent.appendChild(cancelButton);

        // --- 点击遮罩层关闭 ---
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) {
                closeAndCancel();
            }
        });

        // --- 关闭模态框的通用函数 ---
        function closeModal() {
            setTimeout(() => { // Add delay
                const existingModal = document.getElementById('magnet-helper-modal-overlay');
                if (existingModal && existingModal.parentNode) {
                    existingModal.parentNode.removeChild(existingModal);
                }
            }, 100); // Delay of 100ms
        }

        // --- 选择文件夹并关闭模态框的函数 ---
        async function selectFolder(folderId) {
            closeModal();
            const folder = normalizeFolder(folderId);
            debug(`用户选择文件夹 ID: ${folder.id}`, folder);
            buttonElement.textContent = '...'; // 再次确认按钮是加载状态
            buttonElement.style.backgroundColor = '#ff9800';
            // 调用保存函数，并传递按钮元素用于状态恢复
            const success = await saveTo115(magnetLink, folder, buttonElement);
            // 状态恢复在 saveTo115 内部处理
        }

        // --- 关闭模态框并不执行操作 ---
        function closeAndCancel() {
            closeModal();
            debug('用户取消选择');
            // 恢复按钮状态
            buttonElement.textContent = '115';
            buttonElement.style.backgroundColor = '#2777F8';
        }
    }

    // 保存到115云盘
    async function saveTo115(magnetLink, targetFolderId = 0, buttonElement = null) {
        const selectedFolder = normalizeFolder(targetFolderId);
        let success = false;
        let isWarning = false;
        try {
            // 检查登录状态
            const checkLogin = () => {
                return new Promise((resolve) => {
                    GM_xmlhttpRequest({
                        method: 'GET',
                        url: 'https://115.com/?ct=offline&ac=space',
                        headers: {
                            'Accept': 'application/json',
                            'Referer': 'https://115.com/',
                            'User-Agent': window.navigator.userAgent
                        },
                        withCredentials: true,
                        onload: function(response) {
                            try {
                                const data = JSON.parse(response.responseText);
                                resolve(data.state);
                            } catch (error) {
                                resolve(false);
                            }
                        },
                        onerror: () => resolve(false)
                    });
                });
            };

            // 获取离线空间和用户ID
            const getOfflineSpace = () => {
                return new Promise((resolve) => {
                    GM_xmlhttpRequest({
                        method: 'GET',
                        url: 'https://115.com/?ct=offline&ac=space',
                        headers: {
                            'Accept': 'application/json',
                            'Referer': 'https://115.com/'
                        },
                        withCredentials: true,
                        onload: function(response) {
                            try {
                                const data = JSON.parse(response.responseText);
                                resolve(data);
                            } catch (error) {
                                resolve(null);
                            }
                        },
                        onerror: () => resolve(null)
                    });
                });
            };

            // 检查登录状态
            const isLoggedIn = await checkLogin();
            if (!isLoggedIn) {
                GM_notification({
                    text: '请先登录115云盘',
                    title: APP_NAME,
                    timeout: 3000
                });
                window.open('https://115.com/?ct=login', '_blank');
                return false;
            }

            // 获取离线空间信息
            const spaceInfo = await getOfflineSpace();
            if (!spaceInfo || !spaceInfo.state) {
                debug('获取离线空间信息失败，但仍尝试添加任务');
            }

            // 添加离线任务，并指定目标文件夹ID (wp_path_id)
            return new Promise((resolve) => {
                GM_xmlhttpRequest({
                    method: 'POST',
                    url: 'https://115.com/web/lixian/?ct=lixian&ac=add_task_url',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Referer': 'https://115.com/',
                        'Origin': 'https://115.com',
                        'User-Agent': window.navigator.userAgent
                    },
                    // 在 data 中添加 wp_path_id 参数
                    data: `url=${encodeURIComponent(magnetLink)}&wp_path_id=${encodeURIComponent(selectedFolder.id)}`,
                    withCredentials: true,
                    onload: async function(response) {
                        try {
                            // 增加详细的调试信息
                            debug('API响应:', response.responseText);
                            debug('响应状态:', response.status);
                            
                            const result = JSON.parse(response.responseText);
                            debug('解析后的结果:', {
                                state: result.state,
                                errtype: result.errtype,
                                errcode: result.errcode,
                                errno: result.errno,
                                error_msg: result.error_msg
                            });
                            
                            success = result.state;
                            isWarning = result.errtype === 'war' || result.errcode === 10008; // 任务已存在算警告

                            if (success) {
                                const webhookResult = await triggerWebhookForFolder(selectedFolder, magnetLink);
                                const successMessage = webhookResult.configured
                                    ? `磁力链接已成功添加到离线下载队列\n${webhookResult.message}`
                                    : '磁力链接已成功添加到离线下载队列';
                                showSuccessToast(APP_NAME, successMessage);
                                resolve(true);
                            } else {
                                let errorMessage = '添加任务失败';
                                
                                // 优先使用 error_msg
                                if (result.error_msg) {
                                    errorMessage = result.error_msg;
                                    debug('使用 error_msg 作为错误信息:', errorMessage);
                                } else {
                                    const errorCode = result.errcode || result.errno;
                                    debug('使用错误代码:', errorCode);
                                    
                                    const errorTypes = {
                                        911: '用户未登录',
                                        10008: '任务已存在',
                                        10009: '任务超出限制',
                                        10004: '空间不足',
                                        10002: '解析失败',
                                    };

                                    if (errorCode && errorTypes[errorCode]) {
                                        errorMessage = errorTypes[errorCode];
                                        debug('从错误类型映射获取错误信息:', errorMessage);
                                    }
                                }

                                // 检查是否为警告类型
                                debug('是否为警告类型:', isWarning, '(errtype:', result.errtype, 'errcode:', result.errcode, ')');

                                // 显示通知
                                let finalMessage = errorMessage;
                                if (isWarning) {
                                    const webhookResult = await triggerWebhookForFolder(selectedFolder, magnetLink);
                                    if (webhookResult.configured) {
                                        finalMessage = `${errorMessage}\n${webhookResult.message}`;
                                    }
                                }
                                showNotification(
                                    isWarning ? `${APP_NAME} - 提示` : `${APP_NAME} - 错误`,
                                    finalMessage,
                                    isWarning
                                );

                                resolve(isWarning);
                            }
                        } catch (error) {
                            success = false;
                            console.error('解析响应失败:', error, response.responseText);
                            GM_notification({
                                text: '添加任务失败: ' + (error.message || '未知错误'),
                                title: APP_NAME,
                                timeout: 3000
                            });
                            resolve(false);
                        }
                    },
                    onerror: function(error) {
                        success = false;
                        console.error('请求失败:', error);
                        GM_notification({
                            text: '网络请求失败',
                            title: APP_NAME,
                            timeout: 3000
                        });
                        resolve(false);
                    },
                    // GM_xmlhttpRequest 的 finally 不可靠，在 onload 和 onerror 中处理
                    onloadend: function() {
                        // 恢复按钮状态
                        if (buttonElement) {
                           debug('恢复按钮状态, success:', success, 'isWarning:', isWarning);
                           buttonElement.textContent = '115';
                           // 成功或警告(任务已存在) 都用蓝色，否则用红色
                           buttonElement.style.backgroundColor = (success || isWarning) ? '#2777F8' : '#f44336';
                           if (!(success || isWarning)) { // 如果是彻底失败，一段时间后恢复蓝色
                               setTimeout(() => {
                                   if (buttonElement.style.backgroundColor === 'rgb(244, 67, 54)') { // 检查是否仍是红色
                                      buttonElement.style.backgroundColor = '#2777F8';
                                   }
                               }, 2000);
                           }
                        }
                    }
                });
            });
        } catch (error) {
            success = false;
            console.error('保存到115云盘外层失败:', error);
            GM_notification({
                text: '保存失败：' + error.message,
                title: APP_NAME,
                timeout: 3000
            });
             // 恢复按钮状态 (如果需要)
             if (buttonElement) {
                 buttonElement.textContent = '115';
                 buttonElement.style.backgroundColor = '#f44336'; // 红色表示错误
                 setTimeout(() => {
                     if (buttonElement.style.backgroundColor === 'rgb(244, 67, 54)') {
                          buttonElement.style.backgroundColor = '#2777F8';
                     }
                 }, 2000);
             }
            return false;
        }
    }

    // 创建磁力链接按钮
    function createMagnetButton(magnetLink, element) {
        if (createdButtons.has(magnetLink)) return;
        debug('创建按钮:', magnetLink);

        // 创建一个包装容器
        const wrapper = document.createElement('span');
        wrapper.style.cssText = `
            display: inline-flex;
            align-items: center;
            white-space: nowrap;
            margin: 0 2px;
        `;

        // 创建按钮 - 改名为 buttonElement
        const buttonElement = document.createElement('span');
        buttonElement.innerHTML = '115';
        buttonElement.style.cssText = buttonStyle;
        buttonElement.title = '点击保存到115云盘';

        if (element.nodeType === Node.TEXT_NODE) {
            // 处理文本节点
            const text = element.textContent;
            const index = text.indexOf(magnetLink);
            if (index !== -1) {
                const beforeText = document.createTextNode(text.substring(0, index));
                const afterText = document.createTextNode(text.substring(index + magnetLink.length));
                const magnetSpan = document.createElement('span');
                magnetSpan.textContent = magnetLink;
                
                const parent = element.parentNode;
                parent.insertBefore(beforeText, element);
                parent.insertBefore(wrapper, element);
                wrapper.appendChild(magnetSpan);
                wrapper.appendChild(buttonElement);
                parent.insertBefore(afterText, element);
                parent.removeChild(element);
            }
        } else {
            // 处理元素节点
            if (element.tagName === 'A' || element.tagName === 'INPUT') {
                element.parentNode.insertBefore(wrapper, element.nextSibling);
                wrapper.appendChild(buttonElement);
            } else {
                element.appendChild(wrapper);
                wrapper.appendChild(buttonElement);
            }
        }

        // 添加按钮事件处理 - 直接使用 buttonElement
        if (buttonElement) {
            // 添加交互效果
            buttonElement.addEventListener('mouseenter', () => {
                buttonElement.style.transform = 'scale(1.1)';
                buttonElement.style.opacity = '1';
            });
            
            buttonElement.addEventListener('mouseleave', () => {
                buttonElement.style.transform = 'scale(1)';
                buttonElement.style.opacity = '0.9';
            });
            
            // 点击处理
            buttonElement.addEventListener('click', async (e) => {
                e.stopPropagation();
                e.preventDefault();
                debug('点击按钮，准备显示文件夹选择器:', magnetLink);

                // 改变按钮外观，表示正在处理
                buttonElement.textContent = '...';
                buttonElement.style.backgroundColor = '#ff9800'; // 橙色表示等待
                buttonElement.disabled = true; // 暂时禁用按钮防止重复点击

                // 显示文件夹选择器，传递按钮元素以便后续恢复状态
                try {
                    await showFolderSelector(magnetLink, buttonElement);
                    // 选择器内部会调用 saveTo115 并处理后续状态
                } catch (error) {
                    console.error('显示文件夹选择器时出错:', error);
                    // 如果选择器本身出错，恢复按钮
                    buttonElement.textContent = '115';
                    buttonElement.style.backgroundColor = '#f44336'; // 显示错误
                    setTimeout(() => {
                          buttonElement.style.backgroundColor = '#2777F8';
                     }, 2000);
                } finally {
                    buttonElement.disabled = false; // 无论如何最终都恢复按钮可用性
                }
            });
        }

        createdButtons.add(magnetLink);
    }

    // 查找并处理磁力链接
    function findAndProcessMagnetLinks() {
        debug('开始查找磁力链接');
        
        // 使用 TreeWalker 遍历所有文本节点
        const processedLinks = new Set();
        const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode: function(node) {
                    // 过滤掉不可见元素和脚本标签
                    const parent = node.parentElement;
                    if (!parent || 
                        parent.tagName === 'SCRIPT' || 
                        parent.tagName === 'STYLE' || 
                        parent.tagName === 'NOSCRIPT' ||
                        getComputedStyle(parent).display === 'none' ||
                        getComputedStyle(parent).visibility === 'hidden') {
                        return NodeFilter.FILTER_REJECT;
                    }
                    // 只接受包含磁力链接的文本节点
                    return node.textContent.includes('magnet:?') ? 
                        NodeFilter.FILTER_ACCEPT : 
                        NodeFilter.FILTER_SKIP;
                }
            }
        );

        const textNodes = [];
        while (walker.nextNode()) {
            textNodes.push(walker.currentNode);
        }

        // 处理找到的文本节点
        textNodes.forEach(node => {
            const matches = node.textContent.match(magnetRegex);
            if (matches) {
                matches.forEach(magnetLink => {
                    if (!processedLinks.has(magnetLink)) {
                        // 找到实际包含磁力链接的最小父元素
                        let targetElement = node;
                        let parent = node.parentElement;
                        while (parent && parent !== document.body) {
                            if (parent.textContent.trim() === node.textContent.trim()) {
                                targetElement = parent;
                                parent = parent.parentElement;
                            } else {
                                break;
                            }
                        }
                        createMagnetButton(magnetLink, targetElement);
                        processedLinks.add(magnetLink);
                    }
                });
            }
        });

        // 检查特殊属性（如链接和输入框）
        const elements = document.querySelectorAll('a[href], input[value], [data-url], [title], [data-clipboard-text]');
        elements.forEach(element => {
            const attributes = ['href', 'data-url', 'value', 'title', 'data-clipboard-text'];
            for (const attr of attributes) {
                const value = element.getAttribute(attr);
                if (value) {
                    const matches = value.match(magnetRegex);
                    if (matches) {
                        matches.forEach(magnetLink => {
                            if (!processedLinks.has(magnetLink)) {
                                createMagnetButton(magnetLink, element);
                                processedLinks.add(magnetLink);
                            }
                        });
                    }
                }
            }
        });
    }

    // 初始化
    function init() {
        debug('初始化脚本');
        if (typeof GM_registerMenuCommand === 'function') {
            GM_registerMenuCommand(`${APP_NAME}：管理文件夹 webhook`, () => {
                showWebhookManager().catch(error => {
                    debug('打开 webhook 管理界面失败:', error);
                    window.alert('打开 webhook 管理界面失败: ' + (error.message || '未知错误'));
                });
            });
        }
        findAndProcessMagnetLinks();

        // 使用 MutationObserver 监听页面变化
        const observer = new MutationObserver(() => {
            setTimeout(findAndProcessMagnetLinks, 500);
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    // 等待页面加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})(); 
