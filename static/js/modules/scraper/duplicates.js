// 媒体库查重面板：找出「同一集/同一部电影存了两份以上」的文件。
//
// 为什么单独一个模块：查重是一整套独立的判定（分组、档位、保留建议、二次校验），
// 塞进 core.js 会继续把那个文件撑大。这里只依赖 core.js 注入的少量工具函数，
// 不直接读它的内部状态。
//
// 交互约定（两条都是刻意设计，别改成「全部自动勾选」）：
// - 「同一份文件」（SHA1 相同）默认勾掉多余副本，一键就能清；
// - 「同集不同版本」默认一个都不勾，只给「每组保留最高画质」按钮——不同音轨、
//   不同字幕组的版本可能都是用户要留的。

const PANEL_ID = 'scraper-duplicates-panel';
const META_ID = 'scraper-duplicates-meta';
const SUMMARY_ID = 'scraper-duplicates-summary';
const LIST_ID = 'scraper-duplicates-list';
const DELETE_BTN_ID = 'scraper-duplicates-delete-btn';

export function createDuplicatesController(deps = {}) {
    const {
        getProvider = () => '115',
        getCid = () => '0',
        showToast = () => {},
        showConfirm = async () => false,
        formatFileSize = (value) => `${value} B`,
        escapeHtml = (value) => String(value ?? ''),
        buildMutationRequestId = () => String(Date.now()),
        onAfterDelete = async () => {},
    } = deps;

    const ui = {
        open: false,
        loading: false,
        result: null,
        error: '',
        picks: new Set(),
        requestId: '',
        // 扫描目标：勾中的文件夹（或勾中文件所在目录）。空 = 退回当前浏览目录。
        targetCid: '',
    };

    function sizeText(bytes) {
        const value = Number(bytes || 0) || 0;
        return value > 0 ? formatFileSize(value) : '0 B';
    }

    function el(id) {
        return document.getElementById(id);
    }

    function groups() {
        return Array.isArray(ui.result?.groups) ? ui.result.groups : [];
    }

    function pickedFiles() {
        const picked = [];
        for (const group of groups()) {
            for (const file of Array.isArray(group.files) ? group.files : []) {
                if (ui.picks.has(String(file.id))) picked.push(file);
            }
        }
        return picked;
    }

    function invalidGroupCount() {
        return groups().filter((group) => {
            const files = Array.isArray(group.files) ? group.files : [];
            if (!files.length) return false;
            return files.every((file) => ui.picks.has(String(file.id)));
        }).length;
    }

    function applyDefaultPicks(result) {
        ui.picks = new Set();
        for (const group of Array.isArray(result?.groups) ? result.groups : []) {
            if (group?.tier !== 'exact') continue;
            for (const file of Array.isArray(group.files) ? group.files : []) {
                if (!file?.recommended_keep) ui.picks.add(String(file.id));
            }
        }
    }

    function renderGroup(group) {
        const files = Array.isArray(group.files) ? group.files : [];
        const pickedInGroup = files.filter((file) => ui.picks.has(String(file.id))).length;
        const invalid = files.length > 0 && pickedInGroup === files.length;
        const badge = group.tier === 'exact'
            ? '<span class="scraper-dup-badge is-exact">同一份文件</span>'
            : '<span class="scraper-dup-badge is-version">同集不同版本</span>';
        const hint = group.tier === 'exact'
            ? (Number(group.reclaimable_bytes || 0) > 0
                ? `可释放 ${sizeText(group.reclaimable_bytes)}`
                : '同一份文件的两份副本')
            : '内容不同，请确认要删哪一份';
        const rows = files.map((file) => {
            const meta = [file.resolution || '', sizeText(file.size)].filter(Boolean).join(' · ');
            const keep = file.recommended_keep
                ? '<span class="scraper-dup-keep">建议保留</span>'
                : '';
            const sha = file.sha1_short
                ? `<span class="scraper-dup-sha" title="SHA1 前 8 位（相同即同一份文件）">${escapeHtml(file.sha1_short)}</span>`
                : '';
            return `<label class="scraper-dup-file${file.recommended_keep ? ' is-keep' : ''}">
                <input type="checkbox" class="ui-checkbox ui-checkbox-sm" data-dup-pick="${escapeHtml(String(file.id))}" ${ui.picks.has(String(file.id)) ? 'checked' : ''}>
                <span class="scraper-dup-file-main">
                    <span class="scraper-dup-file-name">${escapeHtml(file.name || '')}</span>
                    <span class="scraper-dup-file-path">${escapeHtml(file.path || '')}</span>
                </span>
                <span class="scraper-dup-file-meta">${escapeHtml(meta)}${sha}</span>
                ${keep}
            </label>`;
        }).join('');
        return `<div class="scraper-dup-group${invalid ? ' is-invalid' : ''}">
            <div class="scraper-dup-group-head">
                ${badge}
                <span class="scraper-dup-group-label">${escapeHtml(group.label || '')}</span>
                <span class="scraper-dup-group-hint">${files.length} 份 · ${escapeHtml(hint)}</span>
            </div>
            <div class="scraper-dup-file-list">${rows}</div>
            ${invalid ? '<div class="scraper-dup-warn">这一组被全部勾选，会一份都不剩，请至少留一份。</div>' : ''}
        </div>`;
    }

    function renderHints(hints) {
        const items = Array.isArray(hints) ? hints : [];
        if (!items.length) return '';
        const rows = items.map((hint) => {
            const paths = Array.isArray(hint.paths) ? hint.paths : [];
            const counts = hint.episode_counts && typeof hint.episode_counts === 'object' ? hint.episode_counts : {};
            const detail = paths
                .map((path) => `${path}（${Number(counts[path] || 0)} 集）`)
                .join('、');
            return `<li>${escapeHtml(detail)} · 重复 ${Number(hint.shared_episodes || 0)} 集</li>`;
        }).join('');
        return `<div class="scraper-dup-hints">
            <div class="scraper-dup-hints-title">疑似同一部剧存了两个目录（仅提示，不提供批量删除）</div>
            <ul>${rows}</ul>
        </div>`;
    }

    function render() {
        const panel = el(PANEL_ID);
        if (!panel) return;
        const metaEl = el(META_ID);
        const summaryEl = el(SUMMARY_ID);
        const listEl = el(LIST_ID);
        const deleteBtn = el(DELETE_BTN_ID);

        if (ui.loading) {
            if (metaEl) metaEl.textContent = '正在扫描勾选的目录… 目录很大时要等一会儿';
            if (summaryEl) summaryEl.innerHTML = '';
            if (listEl) listEl.innerHTML = '<div class="scraper-dup-empty">读取目录中，请稍候。</div>';
            if (deleteBtn) {
                deleteBtn.disabled = true;
                deleteBtn.textContent = '清理选中 0 项';
            }
            return;
        }

        if (ui.error) {
            if (metaEl) metaEl.textContent = '扫描失败';
            if (summaryEl) summaryEl.innerHTML = '';
            if (listEl) listEl.innerHTML = `<div class="scraper-dup-empty is-error">${escapeHtml(ui.error)}</div>`;
            if (deleteBtn) {
                deleteBtn.disabled = true;
                deleteBtn.textContent = '清理选中 0 项';
            }
            return;
        }

        const result = ui.result;
        if (!result) {
            if (metaEl) metaEl.textContent = '尚未扫描';
            if (summaryEl) summaryEl.innerHTML = '';
            if (listEl) listEl.innerHTML = '';
            if (deleteBtn) {
                deleteBtn.disabled = true;
                deleteBtn.textContent = '清理选中 0 项';
            }
            return;
        }

        const scanned = result.scanned && typeof result.scanned === 'object' ? result.scanned : {};
        const summary = result.summary && typeof result.summary === 'object' ? result.summary : {};
        const groupList = groups();
        const picked = pickedFiles();
        const pickedSize = picked.reduce((total, file) => total + Math.max(0, Number(file.size || 0)), 0);

        if (metaEl) {
            const rootPath = String(result.root_path || '').trim();
            metaEl.textContent = [
                rootPath ? `扫描 ${rootPath}` : '已扫描',
                `${Number(scanned.dirs || 0)} 个文件夹`,
                `${Number(scanned.media_files || 0)} 个视频文件`,
                Number(scanned.failed_dirs || 0) > 0 ? `${Number(scanned.failed_dirs)} 个目录读取失败` : '',
                scanned.truncated ? '已到扫描上限，结果可能不完整' : '',
            ].filter(Boolean).join(' · ');
        }

        if (summaryEl) {
            const hintCount = Array.isArray(result.series_hints) ? result.series_hints.length : 0;
            if (!groupList.length && !hintCount) {
                summaryEl.innerHTML = '';
            } else if (!groupList.length) {
                summaryEl.innerHTML = '这个目录下没发现重复文件。';
            } else {
                const extra = Number(summary.reclaimable_bytes || 0) > 0
                    ? `；其中同一份文件的多余副本可释放 <b>${sizeText(summary.reclaimable_bytes)}</b>`
                    : '';
                summaryEl.innerHTML = `发现 <b>${Number(summary.group_count || groupList.length)}</b> 组重复，涉及 ${Number(summary.duplicate_files || 0)} 个文件${extra}`;
            }
        }

        if (listEl) {
            if (!groupList.length) {
                listEl.innerHTML = '<div class="scraper-dup-empty">没有发现重复文件。</div>' + renderHints(result.series_hints);
            } else {
                listEl.innerHTML = groupList.map(renderGroup).join('') + renderHints(result.series_hints);
            }
        }

        if (deleteBtn) {
            const invalidCount = invalidGroupCount();
            deleteBtn.textContent = `清理选中 ${picked.length} 项`;
            deleteBtn.disabled = picked.length === 0 || invalidCount > 0;
            if (invalidCount > 0) deleteBtn.title = '有分组被全部勾选，每组至少要保留一份';
            else deleteBtn.removeAttribute('title');
        }
    }

    async function scan() {
        if (!ui.open) return;
        ui.loading = true;
        ui.error = '';
        ui.result = null;
        ui.picks = new Set();
        ui.requestId = String(buildMutationRequestId() || '');
        render();
        try {
            const data = await window.MediaHubApi.postJson('/scraper/duplicates/scan', {
                provider: getProvider(),
                cid: ui.targetCid || String(getCid() || '0'),
            });
            ui.result = data && typeof data === 'object' ? data : null;
            if (ui.result) applyDefaultPicks(ui.result);
        } catch (error) {
            ui.error = String(error?.message || '扫描失败');
        } finally {
            ui.loading = false;
            render();
        }
    }

    async function open(target = {}) {
        const panel = el(PANEL_ID);
        if (!panel) return;
        // cid 由调用方指定（勾中的文件夹）；不传就扫当前浏览目录。
        ui.targetCid = String(target?.cid || '').trim();
        panel.classList.remove('hidden');
        ui.open = true;
        await scan();
    }

    function close() {
        const panel = el(PANEL_ID);
        if (panel) panel.classList.add('hidden');
        ui.open = false;
        ui.loading = false;
        ui.error = '';
        ui.result = null;
        ui.picks = new Set();
        ui.targetCid = '';
    }

    function keepBest() {
        if (!ui.result) {
            showToast('还没有扫描结果', { tone: 'warn', duration: 2000, placement: 'top-center' });
            return;
        }
        const next = new Set();
        for (const group of groups()) {
            const files = Array.isArray(group.files) ? group.files : [];
            if (files.length < 2) continue;
            const keep = files.find((file) => file.recommended_keep) || files[0];
            for (const file of files) {
                if (String(file.id) !== String(keep.id)) next.add(String(file.id));
            }
        }
        ui.picks = next;
        render();
        showToast(
            next.size
                ? `已按「每组保留画质最高的一份」勾选 ${next.size} 个文件，确认后点清理`
                : '没有可勾选的多余副本',
            { tone: 'info', duration: 3000, placement: 'top-center' },
        );
    }

    function togglePick(entryId, checked) {
        const id = String(entryId || '').trim();
        if (!id) return;
        if (checked) ui.picks.add(id);
        else ui.picks.delete(id);
        render();
    }

    async function deleteSelected() {
        const picked = pickedFiles();
        if (!picked.length) {
            showToast('请先勾选要删除的文件', { tone: 'warn', duration: 2200, placement: 'top-center' });
            return;
        }
        if (invalidGroupCount() > 0) {
            showToast('有分组被全部勾选，每组至少要保留一份', { tone: 'warn', duration: 3000, placement: 'top-center' });
            return;
        }
        const totalSize = picked.reduce((total, file) => total + Math.max(0, Number(file.size || 0)), 0);
        const ok = await showConfirm(
            `将从网盘删除 ${picked.length} 个文件，共 ${sizeText(totalSize)}。删除后进入网盘回收站，可以恢复。`,
            { title: '确认清理重复文件', confirmText: '删除', tone: 'error' },
        );
        if (!ok) return;
        try {
            const data = await window.MediaHubApi.postJson('/scraper/duplicates/delete', {
                provider: getProvider(),
                groups: groups(),
                delete_ids: picked.map((file) => String(file.id)),
                request_id: ui.requestId,
            });
            const deleted = Number(data?.deleted_count || 0);
            const failed = Number(data?.failed_count || 0);
            showToast(
                failed
                    ? `已删除 ${deleted} 个，${failed} 个失败（可重试）`
                    : `已删除 ${deleted} 个文件，释放 ${sizeText(data?.deleted_size)}`,
                { tone: failed ? 'warn' : 'success', duration: failed ? 4200 : 3200, placement: 'top-center' },
            );
            await onAfterDelete();
            await scan();
        } catch (error) {
            showToast(`清理失败：${error?.message || '未知错误'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
        }
    }

    async function handleAction(action) {
        const normalized = String(action || '').trim();
        if (normalized === 'open-duplicates') return open();
        if (normalized === 'close-duplicates') return close();
        if (normalized === 'dup-rescan') return scan();
        if (normalized === 'dup-keep-best') return keepBest();
        if (normalized === 'dup-delete') return deleteSelected();
        return undefined;
    }

    return {
        open,
        close,
        scan,
        keepBest,
        togglePick,
        deleteSelected,
        handleAction,
    };
}
