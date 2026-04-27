// ==UserScript==
// @name         115-media-hub助手
// @namespace    http://tampermonkey.net/
// @version      2.4.0
// @description  检测网页 magnet / torrent / 115 / 夸克分享链接并生成快捷按钮
// @author       仙儿
// @license      MIT
// @match        *://*/*
// @connect      *
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @run-at       document-end
// ==/UserScript==

(function () {
    'use strict';

    const APP_NAME = '115-media-hub助手';
    const MAGNET_REGEX = /magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}[^\s<>'"]*/gi;
    const DETECTABLE_LINK_REGEX = /(magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}[^\s<>'"]*|https?:\/\/[^\s<>'"]+?\.torrent(?:\?[^\s<>'"]*)?|https?:\/\/(?:115cdn|115|anxia)\.com\/s\/[A-Za-z0-9]+[^\s<>'"]*|https?:\/\/(?:pan|www)\.quark\.cn\/s\/[A-Za-z0-9]+[^\s<>'"]*)/gi;
    const STORE_TASKS_KEY = 'magnet_push_tasks_v2';
    const STORE_SECRET_KEY = 'magnet_push_secret_v2';

    const BTN_CLASS = 'mh-push-btn';
    const COPY_BTN_CLASS = 'mh-copy-btn';
    const WRAP_CLASS = 'mh-magnet-wrap';
    const NODE_MARK = '__mh_magnet_scanned__';

    const BTN_STYLE = [
        'display:inline-flex',
        'align-items:center',
        'justify-content:center',
        'flex:0 0 auto',
        'min-width:32px',
        'width:auto',
        'height:26px',
        'padding:0 6px',
        'margin-left:6px',
        'border:none',
        'border-radius:999px',
        'background:#2777F8',
        'color:#fff',
        'font-size:11px',
        'line-height:1',
        'font-family:Arial,sans-serif',
        'font-weight:700',
        'white-space:nowrap',
        'word-break:normal',
        'overflow-wrap:normal',
        'writing-mode:horizontal-tb',
        'text-orientation:mixed',
        'cursor:pointer',
        'box-shadow:0 2px 5px rgba(0,0,0,0.22)',
        'transition:all .18s ease',
        'user-select:none'
    ].join(';');

    let tasks = loadTasks();
    let toastTimer = null;
    let managerEditorState = { mode: 'none', taskId: '' };

    function readStore(key, fallback) {
        try {
            if (typeof GM_getValue === 'function') {
                const val = GM_getValue(key, fallback);
                return typeof val === 'undefined' ? fallback : val;
            }
        } catch (err) {
            console.warn(`[${APP_NAME}] GM_getValue 读取失败`, err);
        }
        try {
            const raw = window.localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (err) {
            console.warn(`[${APP_NAME}] localStorage 读取失败`, err);
            return fallback;
        }
    }

    function writeStore(key, value) {
        try {
            if (typeof GM_setValue === 'function') {
                GM_setValue(key, value);
                return;
            }
        } catch (err) {
            console.warn(`[${APP_NAME}] GM_setValue 写入失败`, err);
        }
        try {
            window.localStorage.setItem(key, JSON.stringify(value));
        } catch (err) {
            console.warn(`[${APP_NAME}] localStorage 写入失败`, err);
        }
    }

    function normalizeSavePath(path) {
        return String(path || '')
            .replace(/\\/g, '/')
            .split('/')
            .filter(Boolean)
            .join('/');
    }

    function isHttpUrl(url) {
        return /^https?:\/\//i.test(String(url || '').trim());
    }

    function normalizeSourceLink(link) {
        let out = String(link || '').trim();
        while (out && /[)\],.;!?，。；！？）】》]$/.test(out)) {
            out = out.slice(0, -1).trim();
        }
        return out;
    }

    function isLikelyTorrentUrl(url) {
        const text = String(url || '').trim();
        if (!isHttpUrl(text)) return false;
        return /\.torrent(?:$|[?#])/i.test(text) || /[?&](?:info_hash|xt|btih)=/i.test(text);
    }

    function isLikely115ShareUrl(url) {
        const text = String(url || '').trim();
        if (!isHttpUrl(text)) return false;
        return /^https?:\/\/(?:115cdn|115|anxia)\.com\/s\/[A-Za-z0-9]+/i.test(text);
    }

    function isLikelyQuarkShareUrl(url) {
        const text = String(url || '').trim();
        if (!isHttpUrl(text)) return false;
        return /^https?:\/\/(?:pan|www)\.quark\.cn\/s\/[A-Za-z0-9]+/i.test(text);
    }

    function getShareLinkMeta(url) {
        if (isLikely115ShareUrl(url)) {
            return {
                provider: '115',
                copyTitle: '复制 115 分享链接',
                copiedMessage: '115 链接已复制',
                baseColor: '#16a34a'
            };
        }
        if (isLikelyQuarkShareUrl(url)) {
            return {
                provider: 'quark',
                copyTitle: '复制夸克分享链接',
                copiedMessage: '夸克链接已复制',
                baseColor: '#0891b2'
            };
        }
        return null;
    }

    function isLikelyShareUrl(url) {
        return !!getShareLinkMeta(url);
    }

    function hasDetectableSourceText(text) {
        const raw = String(text || '');
        return raw.includes('magnet:?')
            || /\.torrent/i.test(raw)
            || /(?:115cdn|115|anxia)\.com\/s\/[A-Za-z0-9]+/i.test(raw)
            || /(?:pan|www)\.quark\.cn\/s\/[A-Za-z0-9]+/i.test(raw);
    }

    async function copyTextToClipboard(text) {
        const value = String(text || '');
        if (!value) throw new Error('复制内容为空');
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            await navigator.clipboard.writeText(value);
            return;
        }
        const area = document.createElement('textarea');
        area.value = value;
        area.setAttribute('readonly', 'readonly');
        area.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0;';
        document.body.appendChild(area);
        area.focus();
        area.select();
        const copied = document.execCommand && document.execCommand('copy');
        if (area.parentNode) area.parentNode.removeChild(area);
        if (!copied) throw new Error('当前页面不支持自动复制');
    }

    function decodeBase32ToHex(base32Text) {
        const source = String(base32Text || '').trim().toUpperCase().replace(/=+$/g, '');
        if (!source || /[^A-Z2-7]/.test(source)) return '';
        const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
        let bits = 0;
        let value = 0;
        const bytes = [];
        for (const ch of source) {
            const idx = alphabet.indexOf(ch);
            if (idx < 0) return '';
            value = (value << 5) | idx;
            bits += 5;
            if (bits >= 8) {
                bits -= 8;
                bytes.push((value >> bits) & 0xff);
            }
        }
        return bytes.map((b) => b.toString(16).padStart(2, '0')).join('').toUpperCase();
    }

    function normalizeBtihHash(rawHash) {
        const cleaned = String(rawHash || '')
            .trim()
            .replace(/^urn:btih:/i, '')
            .replace(/[^A-Za-z0-9]/g, '');
        if (!cleaned) return '';
        if (/^[A-Fa-f0-9]{40}$/.test(cleaned)) return cleaned.toUpperCase();
        if (/^[A-Za-z2-7]{32}$/i.test(cleaned)) {
            const hex = decodeBase32ToHex(cleaned);
            return hex.length === 40 ? hex : '';
        }
        return '';
    }

    function tryExtractBtihFromUrl(url) {
        const text = String(url || '').trim();
        if (!text) return '';

        const direct = text.match(/btih:([A-Za-z0-9]{32,40})/i);
        if (direct && direct[1]) {
            const normalizedDirect = normalizeBtihHash(direct[1]);
            if (normalizedDirect) return normalizedDirect;
        }

        try {
            const parsed = new URL(text);
            const candidates = [
                parsed.searchParams.get('xt'),
                parsed.searchParams.get('btih'),
                parsed.searchParams.get('info_hash'),
                parsed.searchParams.get('hash')
            ].filter(Boolean);
            for (const item of candidates) {
                const normalized = normalizeBtihHash(item);
                if (normalized) return normalized;
                const embedded = String(item || '').match(/btih:([A-Za-z0-9]{32,40})/i);
                if (embedded && embedded[1]) {
                    const normalizedEmbedded = normalizeBtihHash(embedded[1]);
                    if (normalizedEmbedded) return normalizedEmbedded;
                }
            }

            const rawQuery = String(parsed.search || '').replace(/^\?/, '');
            for (const pair of rawQuery.split('&')) {
                if (!pair) continue;
                const eqIndex = pair.indexOf('=');
                const rawKey = eqIndex >= 0 ? pair.slice(0, eqIndex) : pair;
                let decodedKey = '';
                try {
                    decodedKey = decodeURIComponent(rawKey.replace(/\+/g, '%20')).toLowerCase();
                } catch (err) {
                    decodedKey = rawKey.toLowerCase();
                }
                if (decodedKey !== 'info_hash') continue;
                const rawVal = eqIndex >= 0 ? pair.slice(eqIndex + 1) : '';
                const normalizedRaw = normalizeBtihHash(rawVal);
                if (normalizedRaw) return normalizedRaw;
                try {
                    const decodedVal = decodeURIComponent(rawVal.replace(/\+/g, '%20'));
                    const normalizedDecoded = normalizeBtihHash(decodedVal);
                    if (normalizedDecoded) return normalizedDecoded;
                    const bytes = Array.from(decodedVal, (ch) => ch.charCodeAt(0) & 0xff);
                    if (bytes.length === 20) {
                        return bytes.map((b) => b.toString(16).padStart(2, '0')).join('').toUpperCase();
                    }
                } catch (err) {
                    // ignore decoding errors, continue probing
                }
            }
        } catch (err) {
            return '';
        }
        return '';
    }

    function makeTaskId() {
        return `task_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    }

    function normalizeTask(raw) {
        const payload = raw && typeof raw === 'object' ? raw : {};
        return {
            id: String(payload.id || '').trim() || makeTaskId(),
            name: String(payload.name || '').trim(),
            webhookUrl: String(payload.webhookUrl || '').trim(),
            savepath: normalizeSavePath(payload.savepath || ''),
            delaySeconds: Math.max(0, parseInt(payload.delaySeconds, 10) || 0),
            enabled: typeof payload.enabled === 'boolean' ? payload.enabled : true
        };
    }

    function loadTasks() {
        const stored = readStore(STORE_TASKS_KEY, []);
        const list = Array.isArray(stored) ? stored : [];
        const out = [];
        const seen = new Set();
        list.map(normalizeTask).forEach((task) => {
            if (!task.id || seen.has(task.id)) return;
            seen.add(task.id);
            out.push(task);
        });
        return out;
    }

    function saveTasks(nextTasks) {
        const deduped = [];
        const seen = new Set();
        (Array.isArray(nextTasks) ? nextTasks : [])
            .map(normalizeTask)
            .forEach((task) => {
                if (!task.id || seen.has(task.id)) return;
                seen.add(task.id);
                deduped.push(task);
            });
        tasks = deduped;
        writeStore(STORE_TASKS_KEY, deduped);
    }

    function getSecret() {
        return String(readStore(STORE_SECRET_KEY, '') || '').trim();
    }

    function setSecret(secret) {
        writeStore(STORE_SECRET_KEY, String(secret || '').trim());
    }

    function showToast(message, tone = 'success') {
        const id = 'mh-core-toast';
        let el = document.getElementById(id);
        if (!el) {
            el = document.createElement('div');
            el.id = id;
            el.style.cssText = [
                'position:fixed',
                'top:18px',
                'right:18px',
                'z-index:10005',
                'padding:11px 13px',
                'border-radius:10px',
                'font:13px/1.4 Arial,sans-serif',
                'max-width:min(420px, calc(100vw - 24px))',
                'white-space:pre-wrap',
                'box-shadow:0 12px 28px rgba(0,0,0,.28)'
            ].join(';');
            document.body.appendChild(el);
        }
        const colors = tone === 'error'
            ? { bg: 'rgba(153,27,27,.96)', border: 'rgba(254,202,202,.3)', fg: '#fee2e2' }
            : { bg: 'rgba(6,95,70,.96)', border: 'rgba(167,243,208,.3)', fg: '#ecfdf5' };
        el.style.background = colors.bg;
        el.style.border = `1px solid ${colors.border}`;
        el.style.color = colors.fg;
        el.textContent = message;
        if (toastTimer) window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => {
            if (el && el.parentNode) el.parentNode.removeChild(el);
            toastTimer = null;
        }, tone === 'error' ? 3400 : 2300);
    }

    function showPageDialog({
        title = '提示',
        message = '',
        tone = 'info',
        confirmText = '确定',
        cancelText = '取消',
        showCancel = false
    } = {}) {
        return new Promise((resolve) => {
            const existed = document.getElementById('mh-core-dialog-overlay');
            if (existed && existed.parentNode) existed.parentNode.removeChild(existed);

            const overlay = document.createElement('div');
            overlay.id = 'mh-core-dialog-overlay';
            overlay.style.cssText = [
                'position:fixed',
                'inset:0',
                'z-index:2147483647',
                'background:rgba(2,6,23,.72)',
                'backdrop-filter:blur(2px)',
                'display:flex',
                'align-items:center',
                'justify-content:center',
                'padding:14px'
            ].join(';');
            const accent = tone === 'warn' ? '#f59e0b' : (tone === 'error' ? '#ef4444' : '#2777F8');
            overlay.innerHTML = `
                <div style="width:min(420px, calc(100vw - 24px));background:#020617;border:1px solid #334155;border-radius:14px;box-shadow:0 26px 60px rgba(0,0,0,.45);color:#e2e8f0;font:13px/1.55 Arial,sans-serif;overflow:hidden;">
                    <div style="padding:13px 14px;border-bottom:1px solid #334155;">
                        <div style="font-size:11px;font-weight:800;color:${accent};text-transform:uppercase;">Message</div>
                        <div style="margin-top:2px;font-size:16px;font-weight:800;color:#f8fafc;">${escapeHtml(title)}</div>
                    </div>
                    <div style="padding:14px;color:#cbd5e1;white-space:pre-wrap;word-break:break-word;">${escapeHtml(message)}</div>
                    <div style="padding:12px 14px;border-top:1px solid #334155;display:flex;justify-content:flex-end;gap:8px;background:#0b1220;">
                        ${showCancel ? `<button type="button" data-mh-dialog-action="cancel" style="padding:7px 12px;border-radius:9px;border:1px solid #475569;background:#1e293b;color:#e2e8f0;cursor:pointer;">${escapeHtml(cancelText)}</button>` : ''}
                        <button type="button" data-mh-dialog-action="confirm" style="padding:7px 12px;border-radius:9px;border:1px solid ${accent};background:${accent};color:#fff;cursor:pointer;font-weight:700;">${escapeHtml(confirmText)}</button>
                    </div>
                </div>
            `;

            const done = (value) => {
                document.removeEventListener('keydown', onKeydown, true);
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                resolve(value);
            };
            const onKeydown = (event) => {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    done(false);
                }
                if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    done(true);
                }
            };

            document.addEventListener('keydown', onKeydown, true);
            overlay.addEventListener('click', (event) => {
                if (event.target === overlay) {
                    done(false);
                    return;
                }
                const btn = event.target.closest('[data-mh-dialog-action]');
                if (!btn) return;
                done(String(btn.dataset.mhDialogAction || '') === 'confirm');
            });
            document.body.appendChild(overlay);
            window.setTimeout(() => overlay.querySelector('[data-mh-dialog-action="confirm"]')?.focus(), 30);
        });
    }

    function showPageAlert(message, options = {}) {
        return showPageDialog({
            title: options.title || '提示',
            message,
            tone: options.tone || 'info',
            confirmText: options.confirmText || '知道了'
        });
    }

    function showPageConfirm(message, options = {}) {
        return showPageDialog({
            title: options.title || '确认操作',
            message,
            tone: options.tone || 'warn',
            showCancel: true,
            confirmText: options.confirmText || '确认',
            cancelText: options.cancelText || '取消'
        });
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function parseMagnetTitle(magnet) {
        try {
            const idx = magnet.indexOf('?');
            if (idx < 0) return '';
            const params = new URLSearchParams(magnet.slice(idx + 1));
            const dn = params.get('dn');
            if (!dn) return '';
            return decodeURIComponent(dn.replace(/\+/g, ' '))
                .replace(/[\\/:*?"<>|]/g, '_')
                .replace(/[\x00-\x1F\x7F]/g, '')
                .trim()
                .slice(0, 200);
        } catch (err) {
            return '';
        }
    }

    function parseTorrentNameFromUrl(url) {
        try {
            const parsed = new URL(String(url || '').trim());
            const base = parsed.pathname.split('/').pop() || '';
            const decoded = decodeURIComponent(base.replace(/\+/g, ' '));
            const name = decoded
                .replace(/\.torrent$/i, '')
                .replace(/[\\/:*?"<>|]/g, '_')
                .replace(/[\x00-\x1F\x7F]/g, '')
                .trim();
            return name.slice(0, 200);
        } catch (err) {
            return '';
        }
    }

    function extractMagnetHash(magnet) {
        const match = String(magnet || '').match(/btih:([A-Za-z0-9]{32,40})/i);
        if (!match || !match[1]) return '';
        const normalized = normalizeBtihHash(match[1]);
        return normalized || String(match[1]).toUpperCase();
    }

    function parseBencodeStringMeta(bytes, index) {
        let cursor = index;
        let length = 0;
        if (cursor >= bytes.length || bytes[cursor] < 48 || bytes[cursor] > 57) {
            throw new Error('bencode 字符串长度无效');
        }
        while (cursor < bytes.length && bytes[cursor] >= 48 && bytes[cursor] <= 57) {
            length = (length * 10) + (bytes[cursor] - 48);
            cursor += 1;
        }
        if (cursor >= bytes.length || bytes[cursor] !== 58) {
            throw new Error('bencode 字符串缺少分隔符');
        }
        cursor += 1;
        const dataStart = cursor;
        const dataEnd = dataStart + length;
        if (dataEnd > bytes.length) {
            throw new Error('bencode 字符串越界');
        }
        return { dataStart, dataEnd, next: dataEnd };
    }

    function skipBencodeValue(bytes, index) {
        if (index >= bytes.length) throw new Error('bencode 值越界');
        const marker = bytes[index];
        if (marker === 105) { // i
            let cursor = index + 1;
            if (cursor >= bytes.length) throw new Error('bencode 整数无效');
            if (bytes[cursor] === 45) cursor += 1; // -
            if (cursor >= bytes.length || bytes[cursor] < 48 || bytes[cursor] > 57) {
                throw new Error('bencode 整数字面量无效');
            }
            while (cursor < bytes.length && bytes[cursor] !== 101) { // e
                if (bytes[cursor] < 48 || bytes[cursor] > 57) throw new Error('bencode 整数字面量无效');
                cursor += 1;
            }
            if (cursor >= bytes.length) throw new Error('bencode 整数缺少结束符');
            return cursor + 1;
        }
        if (marker === 108) { // l
            let cursor = index + 1;
            while (cursor < bytes.length && bytes[cursor] !== 101) {
                cursor = skipBencodeValue(bytes, cursor);
            }
            if (cursor >= bytes.length) throw new Error('bencode 列表缺少结束符');
            return cursor + 1;
        }
        if (marker === 100) { // d
            let cursor = index + 1;
            while (cursor < bytes.length && bytes[cursor] !== 101) {
                const keyMeta = parseBencodeStringMeta(bytes, cursor);
                cursor = keyMeta.next;
                cursor = skipBencodeValue(bytes, cursor);
            }
            if (cursor >= bytes.length) throw new Error('bencode 字典缺少结束符');
            return cursor + 1;
        }
        if (marker >= 48 && marker <= 57) {
            return parseBencodeStringMeta(bytes, index).next;
        }
        throw new Error('bencode 类型标记无效');
    }

    function bencodeKeyEquals(bytes, keyMeta, keyText) {
        const expectLen = keyText.length;
        if (!keyMeta || (keyMeta.dataEnd - keyMeta.dataStart) !== expectLen) return false;
        for (let i = 0; i < expectLen; i += 1) {
            if (bytes[keyMeta.dataStart + i] !== keyText.charCodeAt(i)) return false;
        }
        return true;
    }

    function extractTorrentInfoBytes(data) {
        const bytes = data instanceof Uint8Array ? data : new Uint8Array(data || []);
        if (!bytes.length) throw new Error('torrent 文件为空');
        if (bytes[0] !== 100) throw new Error('torrent 文件格式无效');
        let cursor = 1;
        let infoStart = -1;
        let infoEnd = -1;
        while (cursor < bytes.length && bytes[cursor] !== 101) {
            const keyMeta = parseBencodeStringMeta(bytes, cursor);
            cursor = keyMeta.next;
            const valueStart = cursor;
            cursor = skipBencodeValue(bytes, cursor);
            if (infoStart < 0 && bencodeKeyEquals(bytes, keyMeta, 'info')) {
                infoStart = valueStart;
                infoEnd = cursor;
            }
        }
        if (cursor >= bytes.length || bytes[cursor] !== 101) {
            throw new Error('torrent 元数据解析失败');
        }
        if (infoStart < 0 || infoEnd <= infoStart) {
            throw new Error('torrent 文件缺少 info 字段');
        }
        return bytes.slice(infoStart, infoEnd);
    }

    function fetchArrayBuffer(url) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: 'GET',
                url,
                timeout: 26000,
                responseType: 'arraybuffer',
                onload: (res) => {
                    if (res.status < 200 || res.status >= 300) {
                        reject(new Error(`下载 torrent 失败: ${res.status || '网络错误'}`));
                        return;
                    }
                    const body = res.response;
                    if (body instanceof ArrayBuffer) {
                        resolve(body);
                        return;
                    }
                    if (ArrayBuffer.isView(body)) {
                        resolve(body.buffer.slice(body.byteOffset, body.byteOffset + body.byteLength));
                        return;
                    }
                    reject(new Error('torrent 返回内容不是二进制'));
                },
                onerror: () => reject(new Error('下载 torrent 失败: 网络错误')),
                ontimeout: () => reject(new Error('下载 torrent 失败: 请求超时'))
            });
        });
    }

    async function sha1Hex(data) {
        if (!window.crypto || !window.crypto.subtle) {
            throw new Error('当前页面不支持 WebCrypto SHA-1');
        }
        const bytes = data instanceof Uint8Array ? data : new Uint8Array(data || []);
        const digest = await window.crypto.subtle.digest('SHA-1', bytes);
        return arrayBufferToHex(digest).toUpperCase();
    }

    async function convertTorrentUrlToMagnet(torrentUrl) {
        const link = normalizeSourceLink(torrentUrl);
        if (!isLikelyTorrentUrl(link)) {
            throw new Error('当前链接不是可识别的 torrent 下载地址');
        }
        let hash = tryExtractBtihFromUrl(link);
        if (!hash) {
            const torrentBody = await fetchArrayBuffer(link);
            const infoBytes = extractTorrentInfoBytes(torrentBody);
            hash = await sha1Hex(infoBytes);
        }
        if (!hash) {
            throw new Error('无法从 torrent 解析出 infohash');
        }
        const dn = parseTorrentNameFromUrl(link);
        return `magnet:?xt=urn:btih:${hash}${dn ? `&dn=${encodeURIComponent(dn)}` : ''}`;
    }

    async function resolveMagnetFromSource(source) {
        const link = normalizeSourceLink(source);
        if (!link) throw new Error('链接为空');
        if (/^magnet:\?/i.test(link)) return link;
        if (isLikelyTorrentUrl(link)) return convertTorrentUrlToMagnet(link);
        throw new Error('仅支持 magnet 或 torrent 链接');
    }

    function buildPayload(task, magnet) {
        return {
            event: 'magnet',
            task_name: task.name,
            savepath: task.savepath,
            delayTime: task.delaySeconds,
            title: parseMagnetTitle(magnet),
            sharetitle: '',
            refresh_target_type: 'file',
            magnet,
            link_url: magnet,
            link_type: 'magnet',
            created_at: new Date().toISOString()
        };
    }

    function randomHex(bytesLength) {
        const bytes = new Uint8Array(bytesLength);
        if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
            window.crypto.getRandomValues(bytes);
            return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
        }
        let fallback = '';
        for (let i = 0; i < bytesLength * 2; i += 1) fallback += Math.floor(Math.random() * 16).toString(16);
        return fallback;
    }

    function arrayBufferToHex(buffer) {
        const bytes = new Uint8Array(buffer);
        return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    }

    async function hmacSha256Hex(secret, message) {
        if (!window.crypto || !window.crypto.subtle || typeof TextEncoder === 'undefined') {
            throw new Error('当前页面不支持 WebCrypto HMAC');
        }
        const encoder = new TextEncoder();
        const key = await window.crypto.subtle.importKey(
            'raw',
            encoder.encode(secret),
            { name: 'HMAC', hash: 'SHA-256' },
            false,
            ['sign']
        );
        const signBuffer = await window.crypto.subtle.sign('HMAC', key, encoder.encode(message));
        return arrayBufferToHex(signBuffer);
    }

    async function buildSignedHeaders(secret, bodyText) {
        const ts = String(Math.floor(Date.now() / 1000));
        const nonce = randomHex(16);
        const signatureBase = `${ts}.${nonce}.${bodyText}`;
        const sign = await hmacSha256Hex(secret, signatureBase);
        return {
            'X-Webhook-Ts': ts,
            'X-Webhook-Nonce': nonce,
            'X-Webhook-Sign': sign
        };
    }

    function postJson(url, headers, bodyText) {
        return new Promise((resolve) => {
            GM_xmlhttpRequest({
                method: 'POST',
                url,
                headers,
                data: bodyText,
                timeout: 18000,
                onload: (res) => resolve({
                    ok: res.status >= 200 && res.status < 300,
                    status: res.status,
                    body: String(res.responseText || '')
                }),
                onerror: () => resolve({ ok: false, status: 0, body: '网络错误' }),
                ontimeout: () => resolve({ ok: false, status: 0, body: '请求超时' })
            });
        });
    }

    function activeTasks() {
        return tasks.filter((t) => t.enabled && t.name && t.webhookUrl && t.savepath);
    }

    async function chooseTask(candidates, sourceLink) {
        if (!candidates.length) return null;
        if (candidates.length === 1) return candidates[0];
        const source = normalizeSourceLink(sourceLink);
        const currentTitle = parseMagnetTitle(source) || parseTorrentNameFromUrl(source);
        const currentHash = extractMagnetHash(source) || tryExtractBtihFromUrl(source);
        const torrentHint = isLikelyTorrentUrl(source) && !/^magnet:\?/i.test(source)
            ? '类型：torrent 链接（将自动转换为磁力）'
            : '';
        const previewLine = currentTitle
            ? `标题：${currentTitle}`
            : (currentHash ? `Hash：${currentHash.slice(0, 12)}...` : (torrentHint || '请点击一个任务'));

        return new Promise((resolve) => {
            const existed = document.getElementById('mh-task-picker-overlay');
            if (existed && existed.parentNode) existed.parentNode.removeChild(existed);

            const overlay = document.createElement('div');
            overlay.id = 'mh-task-picker-overlay';
            overlay.style.cssText = [
                'position:fixed',
                'inset:0',
                'z-index:2147483647',
                'background:rgba(2,6,23,.72)',
                'backdrop-filter:blur(2px)',
                'display:flex',
                'align-items:center',
                'justify-content:center',
                'padding:14px'
            ].join(';');

            overlay.innerHTML = `
                <div style="width:min(620px, calc(100vw - 20px));max-height:calc(100vh - 24px);overflow:auto;background:#020617;border:1px solid #334155;border-radius:14px;box-shadow:0 26px 60px rgba(0,0,0,.45);padding:14px;color:#e2e8f0;font:13px/1.5 Arial,sans-serif;">
                    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
                        <div>
                            <div style="font-size:16px;font-weight:800;color:#f8fafc;">选择要推送的任务</div>
                            <div style="margin-top:2px;font-size:12px;color:#94a3b8;">${escapeHtml(previewLine)}</div>
                        </div>
                        <button type="button" data-mh-picker-action="cancel" style="padding:6px 11px;border-radius:9px;border:1px solid #475569;background:#1e293b;color:#e2e8f0;cursor:pointer;">取消</button>
                    </div>
                    <div style="margin-top:10px;display:flex;flex-direction:column;gap:8px;">
                        ${candidates.map((task) => `
                            <button type="button" data-mh-picker-action="pick" data-task-id="${escapeHtml(task.id)}" style="text-align:left;padding:10px 12px;border-radius:10px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;cursor:pointer;transition:all .16s ease;">
                                <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap;">
                                    <div style="font-size:13px;font-weight:700;color:#f8fafc;">${escapeHtml(task.name)}</div>
                                    <div style="font-size:11px;color:#93c5fd;">+${Number(task.delaySeconds || 0)}s</div>
                                </div>
                                <div style="margin-top:4px;font-size:12px;color:#cbd5e1;">${escapeHtml(task.savepath)}</div>
                                <div style="margin-top:2px;font-size:11px;color:#94a3b8;">${escapeHtml(task.webhookUrl)}</div>
                            </button>
                        `).join('')}
                    </div>
                </div>
            `;

            const done = (task) => {
                document.removeEventListener('keydown', onKeydown, true);
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                resolve(task || null);
            };

            const onKeydown = (event) => {
                if (event.key !== 'Escape') return;
                event.preventDefault();
                done(null);
            };

            document.addEventListener('keydown', onKeydown, true);
            overlay.addEventListener('click', (event) => {
                if (event.target === overlay) {
                    done(null);
                    return;
                }
                const btn = event.target.closest('[data-mh-picker-action]');
                if (!btn) return;
                const action = String(btn.dataset.mhPickerAction || '').trim();
                if (action === 'cancel') {
                    done(null);
                    return;
                }
                if (action === 'pick') {
                    const taskId = String(btn.dataset.taskId || '').trim();
                    const picked = candidates.find((item) => item.id === taskId) || null;
                    done(picked);
                }
            });

            document.body.appendChild(overlay);
        });
    }

    function setButtonState(button, state) {
        if (!button) return;
        if (state === 'busy') {
            button.textContent = '...';
            button.style.background = '#f59e0b';
            button.disabled = true;
            return;
        }
        if (state === 'error') {
            button.textContent = '115';
            button.style.background = '#ef4444';
            button.disabled = false;
            window.setTimeout(() => {
                button.style.background = '#2777F8';
            }, 1300);
            return;
        }
        button.textContent = '115';
        button.style.background = '#2777F8';
        button.disabled = false;
    }

    async function pushMagnet(task, sourceLink, button) {
        const secret = getSecret();
        if (!secret) {
            await showPageAlert('请先配置签名密钥', { title: '需要配置' });
            setButtonState(button, 'idle');
            return;
        }
        setButtonState(button, 'busy');
        try {
            const source = normalizeSourceLink(sourceLink);
            const fromTorrent = isLikelyTorrentUrl(source) && !/^magnet:\?/i.test(source);
            const magnet = await resolveMagnetFromSource(source);
            const payload = buildPayload(task, magnet);
            const bodyText = JSON.stringify(payload);
            const signHeaders = await buildSignedHeaders(secret, bodyText);
            const result = await postJson(task.webhookUrl, {
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/plain, */*',
                ...signHeaders
            }, bodyText);
            if (!result.ok) {
                const tail = result.body ? `\n${String(result.body).slice(0, 200)}` : '';
                showToast(`推送失败: ${result.status || '网络错误'}${tail}`, 'error');
                setButtonState(button, 'error');
                return;
            }
            showToast(fromTorrent ? `已转换 torrent 并推送到任务: ${task.name}` : `已推送到任务: ${task.name}`);
            setButtonState(button, 'idle');
        } catch (err) {
            showToast(`推送失败: ${err.message || '未知错误'}`, 'error');
            setButtonState(button, 'error');
        }
    }

    function createPushButton(sourceLink) {
        const source = normalizeSourceLink(sourceLink);
        const fromTorrent = isLikelyTorrentUrl(source) && !/^magnet:\?/i.test(source);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = BTN_CLASS;
        button.textContent = '115';
        button.title = fromTorrent ? '选择任务，自动转换 torrent 后推送 webhook' : '选择任务并推送 webhook';
        button.style.cssText = BTN_STYLE;

        button.addEventListener('mouseenter', () => {
            button.style.transform = 'scale(1.08)';
        });
        button.addEventListener('mouseleave', () => {
            button.style.transform = 'scale(1)';
        });

        button.addEventListener('click', async (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (button.disabled) return;
            const list = activeTasks();
            if (!list.length) {
                await showPageAlert('没有可用任务，请先通过菜单配置任务并启用', { title: '暂无可用任务' });
                return;
            }
            const task = await chooseTask(list, source);
            if (!task) return;
            await pushMagnet(task, source, button);
        });

        return button;
    }

    function createCopyButton(sourceLink) {
        const source = normalizeSourceLink(sourceLink);
        const meta = getShareLinkMeta(source) || {
            copyTitle: '复制分享链接',
            copiedMessage: '链接已复制',
            baseColor: '#16a34a'
        };
        const button = document.createElement('button');
        button.type = 'button';
        button.className = COPY_BTN_CLASS;
        button.textContent = '复制';
        button.title = meta.copyTitle;
        button.style.cssText = BTN_STYLE
            .replace('background:#2777F8', `background:${meta.baseColor}`)
            .replace('min-width:32px', 'min-width:38px');

        button.addEventListener('mouseenter', () => {
            button.style.transform = 'scale(1.08)';
        });
        button.addEventListener('mouseleave', () => {
            button.style.transform = 'scale(1)';
        });

        button.addEventListener('click', async (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (button.disabled) return;
            setButtonState(button, 'busy');
            button.textContent = '复制中';
            try {
                await copyTextToClipboard(source);
                button.style.background = meta.baseColor;
                button.textContent = '已复制';
                showToast(meta.copiedMessage);
                window.setTimeout(() => {
                    button.textContent = '复制';
                    button.style.background = meta.baseColor;
                    button.disabled = false;
                }, 900);
            } catch (err) {
                showToast(`复制失败: ${err.message || '未知错误'}`, 'error');
                button.textContent = '复制';
                button.style.background = '#ef4444';
                button.disabled = false;
                window.setTimeout(() => {
                    button.style.background = meta.baseColor;
                }, 1200);
            }
        });

        return button;
    }

    function shouldSkipTextNode(node) {
        const parent = node.parentElement;
        if (!parent) return true;
        if (parent.closest(`.${WRAP_CLASS}`)) return true;
        const tag = parent.tagName;
        if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' || tag === 'TEXTAREA') return true;
        if (tag === 'A') {
            const href = String(parent.getAttribute('href') || '');
            if (href.includes('magnet:?') || isLikelyTorrentUrl(href) || isLikelyShareUrl(href)) return true;
        }
        const style = window.getComputedStyle(parent);
        if (style.display === 'none' || style.visibility === 'hidden') return true;
        return false;
    }

    function processTextNode(node) {
        if (!node || node[NODE_MARK]) return;
        node[NODE_MARK] = true;
        if (shouldSkipTextNode(node)) return;
        const raw = String(node.textContent || '');
        if (!hasDetectableSourceText(raw)) return;
        DETECTABLE_LINK_REGEX.lastIndex = 0;

        const matches = Array.from(raw.matchAll(DETECTABLE_LINK_REGEX));
        if (!matches.length) return;

        const fragment = document.createDocumentFragment();
        let offset = 0;
        for (const match of matches) {
            const link = normalizeSourceLink(match[0]);
            if (!link) continue;
            const idx = match.index || 0;
            if (idx > offset) fragment.appendChild(document.createTextNode(raw.slice(offset, idx)));

            const wrap = document.createElement('span');
            wrap.className = WRAP_CLASS;
            wrap.style.cssText = 'display:inline-flex;align-items:center;white-space:nowrap;';

            const textSpan = document.createElement('span');
            textSpan.textContent = match[0];
            wrap.appendChild(textSpan);
            const actionBtn = isLikelyShareUrl(link) ? createCopyButton(link) : createPushButton(link);
            wrap.appendChild(actionBtn);
            fragment.appendChild(wrap);

            offset = idx + match[0].length;
        }
        if (offset < raw.length) fragment.appendChild(document.createTextNode(raw.slice(offset)));

        if (node.parentNode) node.parentNode.replaceChild(fragment, node);
    }

    function processAnchor(anchor) {
        if (!anchor || anchor.dataset.mhMagnetBound === '1' || anchor.dataset.mhLinkBound === '1') return;
        const href = String(anchor.getAttribute('href') || '');
        const matchedMagnet = href.match(MAGNET_REGEX);
        const source = matchedMagnet && matchedMagnet[0]
            ? normalizeSourceLink(matchedMagnet[0])
            : normalizeSourceLink(href);
        if (!source) return;
        let button = null;
        if (/^magnet:\?/i.test(source) || isLikelyTorrentUrl(source)) {
            button = createPushButton(source);
        } else if (isLikelyShareUrl(source)) {
            button = createCopyButton(source);
        }
        if (!button) return;
        anchor.insertAdjacentElement('afterend', button);
        anchor.dataset.mhMagnetBound = '1';
        anchor.dataset.mhLinkBound = '1';
    }

    function scanPage() {
        if (!document.body) return;

        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        textNodes.forEach(processTextNode);

        document.querySelectorAll(
            'a[href*="magnet:?"], a[href*=".torrent"], a[href*="info_hash="], a[href*="btih:"], a[href*="115.com/s/"], a[href*="115cdn.com/s/"], a[href*="anxia.com/s/"], a[href*="pan.quark.cn/s/"], a[href*="www.quark.cn/s/"]'
        ).forEach(processAnchor);
    }

    function managerElements() {
        return {
            overlay: document.getElementById('mh-manager-overlay'),
            secretInput: document.getElementById('mh-manager-secret'),
            secretSaveBtn: document.getElementById('mh-manager-secret-save'),
            addTaskBtn: document.getElementById('mh-manager-task-add'),
            summary: document.getElementById('mh-manager-summary'),
            list: document.getElementById('mh-manager-list'),
            closeBtn: document.getElementById('mh-manager-close')
        };
    }

    function validateManagerTask(task) {
        if (!task.name) return '任务名称不能为空';
        if (!task.webhookUrl || !isHttpUrl(task.webhookUrl)) return '请求地址必须是 http:// 或 https://';
        if (!task.savepath) return 'savepath 不能为空';
        return '';
    }

    function resetManagerEditorState() {
        managerEditorState = { mode: 'none', taskId: '' };
    }

    function openNewTaskEditor() {
        managerEditorState = { mode: 'new', taskId: '' };
    }

    function openEditTaskEditor(taskId) {
        managerEditorState = { mode: 'edit', taskId: String(taskId || '') };
    }

    function isTaskEditorOpened(taskId) {
        return managerEditorState.mode === 'edit' && managerEditorState.taskId === String(taskId || '');
    }

    function renderTaskEditor(taskRaw, mode) {
        const task = normalizeTask(taskRaw || {});
        const safeTaskId = escapeHtml(task.id || '');
        const title = mode === 'new' ? '新增任务' : '编辑任务';
        const saveAction = mode === 'new' ? 'save-new' : 'save-edit';
        const cancelAction = mode === 'new' ? 'cancel-new' : 'cancel-edit';
        const taskIdAttr = mode === 'edit' ? ` data-task-id="${safeTaskId}"` : '';
        return `
            <div class="mh-task-editor" data-editor-mode="${mode}"${taskIdAttr} style="margin-top:10px;padding:10px;border:1px solid #334155;border-radius:10px;background:#020617;">
                <div style="font-size:12px;font-weight:700;color:#f8fafc;">${title}</div>
                <div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                    <input data-editor-field="name" type="text" placeholder="任务名称，例如：自存电影" value="${escapeHtml(task.name || '')}" style="padding:8px 10px;border:1px solid #475569;border-radius:8px;background:#020617;color:#f8fafc;outline:none;">
                    <input data-editor-field="webhookUrl" type="text" placeholder="请求地址，例如：http://IP:18080/webhook/任务名" value="${escapeHtml(task.webhookUrl || '')}" style="padding:8px 10px;border:1px solid #475569;border-radius:8px;background:#020617;color:#f8fafc;outline:none;">
                    <input data-editor-field="savepath" type="text" placeholder="savepath，例如：自存影视/电影" value="${escapeHtml(task.savepath || '')}" style="padding:8px 10px;border:1px solid #475569;border-radius:8px;background:#020617;color:#f8fafc;outline:none;">
                    <input data-editor-field="delaySeconds" type="number" min="0" step="1" value="${Number(task.delaySeconds || 0)}" style="padding:8px 10px;border:1px solid #475569;border-radius:8px;background:#020617;color:#f8fafc;outline:none;">
                </div>
                <div style="margin-top:8px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
                    <label style="display:flex;align-items:center;gap:6px;color:#cbd5e1;cursor:pointer;">
                        <input data-editor-field="enabled" type="checkbox" ${task.enabled ? 'checked' : ''}>
                        启用该任务
                    </label>
                    <div style="display:flex;gap:8px;">
                        <button type="button" data-mh-action="${cancelAction}"${taskIdAttr} style="padding:7px 11px;border-radius:8px;border:1px solid #475569;background:#1e293b;color:#e2e8f0;cursor:pointer;">取消</button>
                        <button type="button" data-mh-action="${saveAction}"${taskIdAttr} style="padding:7px 11px;border-radius:8px;border:1px solid #334155;background:#0f766e;color:#ecfeff;cursor:pointer;">保存</button>
                    </div>
                </div>
            </div>
        `;
    }

    function collectTaskFromEditor(editorEl, fallbackRaw) {
        if (!editorEl) return null;
        const fallback = normalizeTask(fallbackRaw || {});
        const nameInput = editorEl.querySelector('[data-editor-field="name"]');
        const webhookInput = editorEl.querySelector('[data-editor-field="webhookUrl"]');
        const savepathInput = editorEl.querySelector('[data-editor-field="savepath"]');
        const delayInput = editorEl.querySelector('[data-editor-field="delaySeconds"]');
        const enabledInput = editorEl.querySelector('[data-editor-field="enabled"]');
        if (!nameInput || !webhookInput || !savepathInput || !delayInput) return null;
        return normalizeTask({
            id: fallback.id || makeTaskId(),
            name: nameInput.value,
            webhookUrl: webhookInput.value,
            savepath: savepathInput.value,
            delaySeconds: delayInput.value,
            enabled: enabledInput ? !!enabledInput.checked : fallback.enabled
        });
    }

    function upsertTask(taskRaw) {
        const task = normalizeTask(taskRaw || {});
        const next = [...tasks];
        const index = next.findIndex((item) => item.id === task.id);
        if (index >= 0) next[index] = task;
        else next.push(task);
        saveTasks(next);
    }

    function renderManagerTaskList() {
        const els = managerElements();
        if (!els.list || !els.summary) return;
        const total = tasks.length;
        const enabled = tasks.filter((task) => task.enabled).length;
        els.summary.textContent = total
            ? `共 ${total} 个任务，已启用 ${enabled} 个。默认只显示任务，点击“新增任务”或“编辑”才会展开编辑区。`
            : '暂无任务。点击“新增任务”可展开编辑区。';
        if (els.addTaskBtn) {
            const newMode = managerEditorState.mode === 'new';
            els.addTaskBtn.textContent = newMode ? '收起新增' : '新增任务';
            els.addTaskBtn.style.background = newMode ? '#1e293b' : '#0f766e';
            els.addTaskBtn.style.borderColor = newMode ? '#475569' : '#334155';
        }

        const blocks = [];
        if (managerEditorState.mode === 'new') {
            blocks.push(renderTaskEditor({ id: makeTaskId(), enabled: true }, 'new'));
        }

        if (!total) {
            blocks.push('<div style="padding:14px;border:1px dashed #475569;border-radius:10px;color:#94a3b8;background:#020617;">暂无任务</div>');
            els.list.innerHTML = blocks.join('');
            return;
        }

        blocks.push(tasks.map((task) => `
            <div style="border:1px solid #334155;border-radius:10px;padding:10px;background:#0f172a;color:#e2e8f0;">
                <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap;">
                    <div style="font-size:13px;font-weight:700;">
                        ${escapeHtml(task.name)}
                        <span style="margin-left:8px;padding:2px 8px;border-radius:999px;font-size:11px;${task.enabled ? 'background:rgba(16,185,129,.16);color:#6ee7b7;border:1px solid rgba(16,185,129,.28);' : 'background:rgba(148,163,184,.16);color:#cbd5e1;border:1px solid rgba(148,163,184,.28);'}">${task.enabled ? '启用' : '停用'}</span>
                    </div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">
                        <button type="button" data-mh-action="edit" data-task-id="${escapeHtml(task.id)}" style="padding:4px 10px;border-radius:8px;border:1px solid #475569;background:#1e293b;color:#e2e8f0;cursor:pointer;">编辑</button>
                        <button type="button" data-mh-action="toggle" data-task-id="${escapeHtml(task.id)}" style="padding:4px 10px;border-radius:8px;border:1px solid #475569;background:#1e293b;color:#e2e8f0;cursor:pointer;">${task.enabled ? '停用' : '启用'}</button>
                        <button type="button" data-mh-action="delete" data-task-id="${escapeHtml(task.id)}" style="padding:4px 10px;border-radius:8px;border:1px solid rgba(248,113,113,.42);background:rgba(127,29,29,.28);color:#fecaca;cursor:pointer;">删除</button>
                    </div>
                </div>
                <div style="margin-top:8px;font-size:12px;line-height:1.6;color:#cbd5e1;">
                    <div>地址：${escapeHtml(task.webhookUrl)}</div>
                    <div>路径：${escapeHtml(task.savepath)} | 延时：${Number(task.delaySeconds || 0)} 秒</div>
                </div>
                ${isTaskEditorOpened(task.id) ? renderTaskEditor(task, 'edit') : ''}
            </div>
        `).join(''));
        els.list.innerHTML = blocks.join('');
    }

    function ensureManagerModal() {
        if (document.getElementById('mh-manager-overlay')) return;
        const overlay = document.createElement('div');
        overlay.id = 'mh-manager-overlay';
        overlay.style.cssText = [
            'position:fixed',
            'inset:0',
            'z-index:2147483646',
            'background:rgba(2,6,23,.75)',
            'backdrop-filter:blur(2px)',
            'display:none',
            'padding:18px'
        ].join(';');
        overlay.innerHTML = `
            <div style="width:min(900px, calc(100vw - 24px));max-height:calc(100vh - 36px);overflow:auto;margin:0 auto;background:#020617;border:1px solid #334155;border-radius:14px;box-shadow:0 26px 60px rgba(0,0,0,.45);padding:16px 16px 18px 16px;color:#e2e8f0;font:13px/1.5 Arial,sans-serif;">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;">
                    <div style="font-size:16px;font-weight:800;color:#f8fafc;">115-media-hub助手 · 任务管理器</div>
                    <button id="mh-manager-close" type="button" style="padding:6px 11px;border-radius:9px;border:1px solid #475569;background:#1e293b;color:#e2e8f0;cursor:pointer;">关闭</button>
                </div>
                <div style="margin-top:10px;padding:10px;border-radius:10px;background:rgba(30,41,59,.55);border:1px solid rgba(71,85,105,.5);color:#cbd5e1;">
                    用途：配置油猴脚本推送任务（请求地址、savepath、延时）和签名密钥。签名密钥需与后台的 Webhook 签名密钥一致。
                </div>

                <div style="margin-top:12px;padding:12px;border-radius:10px;border:1px solid #334155;background:#0b1220;">
                    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                        <input id="mh-manager-secret" type="text" placeholder="签名密钥（留空可清空）" style="flex:1;min-width:220px;padding:8px 10px;border:1px solid #475569;border-radius:8px;background:#020617;color:#f8fafc;outline:none;">
                        <button id="mh-manager-secret-save" type="button" style="padding:8px 12px;border-radius:8px;border:1px solid #334155;background:#2563eb;color:#fff;cursor:pointer;">保存密钥</button>
                    </div>
                </div>

                <div style="margin-top:12px;padding:12px;border-radius:10px;border:1px solid #334155;background:#0b1220;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
                    <div style="font-size:12px;color:#cbd5e1;">默认只显示任务和新增按钮，编辑区按需展开。</div>
                    <button id="mh-manager-task-add" type="button" style="padding:8px 12px;border-radius:8px;border:1px solid #334155;background:#0f766e;color:#ecfeff;cursor:pointer;">新增任务</button>
                </div>

                <div style="margin-top:12px;font-size:12px;color:#94a3b8;" id="mh-manager-summary"></div>
                <div id="mh-manager-list" style="margin-top:8px;display:flex;flex-direction:column;gap:8px;"></div>
            </div>
        `;
        document.body.appendChild(overlay);

        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) closeTaskManager();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape') return;
            const els = managerElements();
            if (!els.overlay || els.overlay.style.display === 'none') return;
            closeTaskManager();
        });

        const els = managerElements();
        if (els.closeBtn) {
            els.closeBtn.addEventListener('click', closeTaskManager);
        }
        if (els.secretSaveBtn && els.secretInput) {
            els.secretSaveBtn.addEventListener('click', () => {
                const next = String(els.secretInput.value || '').trim();
                setSecret(next);
                showToast(next ? '签名密钥已保存' : '签名密钥已清空');
            });
        }
        if (els.addTaskBtn) {
            els.addTaskBtn.addEventListener('click', () => {
                if (managerEditorState.mode === 'new') resetManagerEditorState();
                else openNewTaskEditor();
                renderManagerTaskList();
            });
        }
        if (els.list) {
            els.list.addEventListener('click', async (event) => {
                const btn = event.target.closest('[data-mh-action]');
                if (!btn) return;
                const action = String(btn.dataset.mhAction || '').trim();
                const taskId = String(btn.dataset.taskId || '').trim();
                if (action === 'save-new') {
                    const editor = btn.closest('.mh-task-editor');
                    const draft = collectTaskFromEditor(editor, { id: makeTaskId(), enabled: true });
                    if (!draft) {
                        showToast('读取新增表单失败', 'error');
                        return;
                    }
                    const validationError = validateManagerTask(draft);
                    if (validationError) {
                        showToast(validationError, 'error');
                        return;
                    }
                    upsertTask(draft);
                    resetManagerEditorState();
                    renderManagerTaskList();
                    showToast(`任务已新增: ${draft.name}`);
                    return;
                }
                if (action === 'cancel-new') {
                    resetManagerEditorState();
                    renderManagerTaskList();
                    return;
                }
                if (action === 'save-edit') {
                    const task = tasks.find((item) => item.id === taskId);
                    if (!task) {
                        showToast('任务不存在或已删除', 'error');
                        resetManagerEditorState();
                        renderManagerTaskList();
                        return;
                    }
                    const editor = btn.closest('.mh-task-editor');
                    const draft = collectTaskFromEditor(editor, task);
                    if (!draft) {
                        showToast('读取编辑表单失败', 'error');
                        return;
                    }
                    const validationError = validateManagerTask(draft);
                    if (validationError) {
                        showToast(validationError, 'error');
                        return;
                    }
                    upsertTask(draft);
                    resetManagerEditorState();
                    renderManagerTaskList();
                    showToast(`任务已更新: ${draft.name}`);
                    return;
                }
                if (action === 'cancel-edit') {
                    resetManagerEditorState();
                    renderManagerTaskList();
                    return;
                }

                const task = tasks.find((item) => item.id === taskId);
                if (!task) return;
                if (action === 'edit') {
                    if (isTaskEditorOpened(task.id)) resetManagerEditorState();
                    else openEditTaskEditor(task.id);
                    renderManagerTaskList();
                    return;
                }
                if (action === 'toggle') {
                    upsertTask({ ...task, enabled: !task.enabled });
                    renderManagerTaskList();
                    showToast(`任务已${task.enabled ? '停用' : '启用'}: ${task.name}`);
                    return;
                }
                if (action === 'delete') {
                    if (!(await showPageConfirm(`确认删除任务“${task.name}”？`))) return;
                    saveTasks(tasks.filter((item) => item.id !== task.id));
                    if (isTaskEditorOpened(task.id)) resetManagerEditorState();
                    renderManagerTaskList();
                    showToast(`任务已删除: ${task.name}`);
                }
            });
        }
    }

    function openTaskManager() {
        ensureManagerModal();
        const els = managerElements();
        if (!els.overlay || !els.secretInput) return;
        els.overlay.style.display = 'block';
        els.secretInput.value = getSecret();
        resetManagerEditorState();
        renderManagerTaskList();
    }

    function closeTaskManager() {
        const els = managerElements();
        if (!els.overlay) return;
        els.overlay.style.display = 'none';
    }

    function registerMenus() {
        if (typeof GM_registerMenuCommand !== 'function') return;
        GM_registerMenuCommand(`${APP_NAME}：打开任务管理器`, openTaskManager);
    }

    function init() {
        registerMenus();

        if (!getSecret() || !activeTasks().length) {
            showToast('首次使用请先在油猴菜单打开“任务管理器”配置密钥和任务', 'error');
        }

        scanPage();

        let timer = null;
        const observer = new MutationObserver(() => {
            if (timer) window.clearTimeout(timer);
            timer = window.setTimeout(scanPage, 260);
        });
        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
