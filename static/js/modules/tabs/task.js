let treeLastRunning = false;
let treeModalEditingId = '';
let treeTaskCache = [];

function escapeHtml(value = '') {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function normalizeRelativeFolderPath(value = '') {
    return String(value || '')
        .split(/[\\/]+/)
        .map(part => part.trim())
        .filter(Boolean)
        .join('/');
}

function showToast(message, options = {}) {
    if (typeof window.showToast === 'function') {
        window.showToast(message, { tone: 'warn', duration: 2600, ...options });
    }
}

async function loadTreeTasks() {
    const data = await window.MediaHubApi.getJson('/tree/tasks');
    const tasks = Array.isArray(data?.tasks) ? data.tasks : [];
    treeTaskCache = tasks;
    const container = document.getElementById('tree-tasks-container');
    if (!container) return;
    if (!tasks.length) {
        container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">还没有目录树任务，点击“新增目录树任务”即可创建。</div>';
        return;
    }
    container.innerHTML = tasks.map((task, index) => `
        <div class="tree-task-card bg-slate-900/50 p-4 rounded-2xl border border-slate-800" data-tree-task-id="${escapeHtml(task.id || '')}">
            <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                    <div class="text-sm font-bold text-white break-all">${escapeHtml(task.folder_path || '--')}</div>
                    <div class="text-xs text-sky-400 mt-1 break-all">${escapeHtml(task.tree_name || '--')}</div>
                    <div class="text-[11px] text-slate-500 mt-1">
                        父文件夹路径前缀: ${escapeHtml(task.prefix || '（空）')} &nbsp;|&nbsp; 排除层级: ${Number(task.exclude ?? 1)}
                        ${task.last_remote_sha1 ? `&nbsp;|&nbsp; sha1: ${escapeHtml(String(task.last_remote_sha1).slice(0, 12))}…` : ''}
                    </div>
                </div>
                <div class="flex flex-wrap gap-2 shrink-0">
                    <button type="button" data-tree-task-action="run" data-tree-task-id="${escapeHtml(task.id || '')}" class="tree-task-action-btn tree-task-action-btn-run px-3 py-2 text-xs font-bold">生成并同步</button>
                    <button type="button" data-tree-task-action="full" data-tree-task-id="${escapeHtml(task.id || '')}" class="tree-task-action-btn tree-task-action-btn-full px-3 py-2 text-xs font-bold">全量重写</button>
                    <button type="button" data-tree-task-action="edit" data-tree-task-id="${escapeHtml(task.id || '')}" class="tree-task-action-btn tree-task-action-btn-edit px-3 py-2 text-xs font-bold">编辑</button>
                    <button type="button" data-tree-task-action="delete" data-tree-task-id="${escapeHtml(task.id || '')}" class="tree-task-action-btn tree-task-action-btn-delete px-3 py-2 text-xs font-bold">删除</button>
                </div>
            </div>
        </div>
    `).join('');
}

async function loadTreeStrategy() {
    const cfg = await window.MediaHubApi.getJson('/get_settings');
    const sha1Skip = document.getElementById('tree_sha1_skip');
    const syncClean = document.getElementById('tree_sync_clean');
    if (sha1Skip) sha1Skip.checked = !!cfg?.sha1_skip;
    if (syncClean) syncClean.checked = !!cfg?.sync_clean;
}

async function saveTreeStrategy() {
    const sha1Skip = document.getElementById('tree_sha1_skip');
    const syncClean = document.getElementById('tree_sync_clean');
    try {
        await window.MediaHubApi.postJson('/save_settings', {
            sha1_skip: sha1Skip ? !!sha1Skip.checked : true,
            sync_clean: syncClean ? !!syncClean.checked : true,
        });
    } catch (error) {
        showToast(`同步策略保存失败：${error?.message || error}`);
    }
}

async function fillTreeTaskDefaults(folderPath, { fillName = false } = {}) {
    if (!folderPath) return;
    try {
        const data = await window.MediaHubApi.getJson(`/tree/task-defaults?folder_path=${encodeURIComponent(folderPath)}`);
        const defaults = data?.defaults || {};
        const nameInput = document.getElementById('tree_task_name');
        const prefixInput = document.getElementById('tree_task_prefix');
        const excludeInput = document.getElementById('tree_task_exclude');
        if (fillName && nameInput) nameInput.value = defaults.tree_name || '';
        if (prefixInput) prefixInput.value = defaults.prefix || '';
        if (excludeInput) excludeInput.value = String(defaults.exclude ?? 1);
    } catch (error) {
        showToast(`自动填充失败：${error?.message || error}`);
    }
}

function openTreeTaskModal(task = null) {
    treeModalEditingId = task ? String(task.id || '') : '';
    const title = document.getElementById('tree-task-modal-title');
    if (title) title.innerText = task ? '编辑目录树任务' : '新增目录树任务';
    const folderInput = document.getElementById('tree_folder_path');
    const nameInput = document.getElementById('tree_task_name');
    const prefixInput = document.getElementById('tree_task_prefix');
    const excludeInput = document.getElementById('tree_task_exclude');
    if (folderInput) folderInput.value = task?.folder_path || '';
    if (nameInput) nameInput.value = task?.tree_name || '';
    if (prefixInput) prefixInput.value = '';
    if (excludeInput) excludeInput.value = '1';
    const modal = document.getElementById('tree-task-modal');
    if (modal) modal.classList.remove('hidden');
    if (folderInput?.value) {
        void fillTreeTaskDefaults(folderInput.value, { fillName: !task });
    }
}

function closeTreeTaskModal() {
    treeModalEditingId = '';
    const modal = document.getElementById('tree-task-modal');
    if (modal) modal.classList.add('hidden');
}

function handleTreeFolderPicked(selection = {}) {
    const folderPath = normalizeRelativeFolderPath(selection?.path || '');
    const folderInput = document.getElementById('tree_folder_path');
    if (!folderPath) {
        showToast('请选择一个文件夹');
        return;
    }
    if (folderInput) folderInput.value = folderPath;
    void fillTreeTaskDefaults(folderPath, { fillName: true });
}

async function saveTreeTask() {
    const folderPath = normalizeRelativeFolderPath(document.getElementById('tree_folder_path')?.value || '');
    const treeName = String(document.getElementById('tree_task_name')?.value || '').trim();
    if (!folderPath) {
        showToast('请先选择 115 文件夹');
        return;
    }
    const payload = { folder_path: folderPath };
    if (treeName) payload.tree_name = treeName;
    try {
        if (treeModalEditingId) {
            await window.MediaHubApi.postJson(`/tree/tasks/${encodeURIComponent(treeModalEditingId)}`, payload);
            showToast('目录树任务已更新', { tone: 'success' });
        } else {
            await window.MediaHubApi.postJson('/tree/tasks', payload);
            showToast('目录树任务已添加', { tone: 'success' });
        }
        closeTreeTaskModal();
        await loadTreeTasks();
    } catch (error) {
        showToast(`保存失败：${error?.message || error}`);
    }
}

async function runTreeTaskAction(action, taskId) {
    const endpointMap = { run: '/run', full: '/full' };
    const endpoint = endpointMap[action];
    if (!endpoint) return;
    try {
        await window.MediaHubApi.postJson(`/tree/tasks/${encodeURIComponent(taskId)}${endpoint}`, {});
        showToast('目录树任务已触发', { tone: 'success' });
    } catch (error) {
        showToast(`触发失败：${error?.message || error}`);
    }
}

async function deleteTreeTask(taskId) {
    const confirmed = typeof window.showAppConfirm === 'function'
        ? await window.showAppConfirm('确定删除该目录树任务吗？（不会删除网盘里的树文件）')
        : true;
    if (!confirmed) return;
    try {
        await window.MediaHubApi.requestJson(`/tree/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
        await loadTreeTasks();
    } catch (error) {
        showToast(`删除失败：${error?.message || error}`);
    }
}

function bindTreePageEvents() {
    const taskList = document.getElementById('tree-tasks-container');
    if (taskList && !taskList.dataset.bound) {
        taskList.dataset.bound = '1';
        taskList.addEventListener('click', (event) => {
            const button = event.target.closest('[data-tree-task-action]');
            if (!button) return;
            const action = String(button.dataset.treeTaskAction || '').trim();
            const taskId = String(button.dataset.treeTaskId || '').trim();
            if (action === 'delete') {
                void deleteTreeTask(taskId);
            } else if (action === 'run' || action === 'full') {
                void runTreeTaskAction(action, taskId);
            } else if (action === 'edit') {
                const task = treeTaskCache.find(item => String(item?.id || '') === taskId);
                openTreeTaskModal(task || null);
            }
        });
    }
    document.getElementById('tree-task-add-btn')?.addEventListener('click', () => openTreeTaskModal());
    document.getElementById('tree-task-modal-close')?.addEventListener('click', closeTreeTaskModal);
    document.getElementById('tree-task-cancel-btn')?.addEventListener('click', closeTreeTaskModal);
    document.getElementById('tree-task-save-btn')?.addEventListener('click', () => void saveTreeTask());
    document.getElementById('tree-folder-pick-btn')?.addEventListener('click', () => {
        if (typeof window.openSubscriptionFolderModal === 'function') {
            window.openSubscriptionFolderModal(handleTreeFolderPicked, '115');
        } else {
            showToast('文件管理器未就绪，请稍后重试');
        }
    });
    document.getElementById('tree-sync-all-btn')?.addEventListener('click', async () => {
        try {
            await window.MediaHubApi.postJson('/tree/sync-all', {});
            showToast('全部同步已触发', { tone: 'success' });
        } catch (error) {
            showToast(`触发失败：${error?.message || error}`);
        }
    });
    ['tree_sha1_skip', 'tree_sync_clean'].forEach((id) => {
        document.getElementById(id)?.addEventListener('change', () => void saveTreeStrategy());
    });
}

export async function ensureTabData(context) {
    if (!context.moduleVisitState.task) {
        await context.refreshMainLogs();
        context.moduleVisitState.task = true;
    }
    bindTreePageEvents();
    await Promise.allSettled([loadTreeTasks(), loadTreeStrategy()]);
}

export function updateButtonState({
    running = false,
    btnTexts = [],
    setIsRunning,
} = {}) {
    const nextRunning = !!running;
    if (typeof setIsRunning === 'function') setIsRunning(nextRunning);
    document.querySelectorAll('.btn-ctrl').forEach((btn, index) => {
        btn.classList.toggle('btn-disabled', nextRunning);
        btn.innerText = nextRunning ? '⏳ 任务运行中...' : String(btnTexts[index] || btn.innerText || '');
    });
    document.querySelectorAll('[data-tree-task-action]').forEach((btn) => {
        btn.disabled = nextRunning;
        btn.classList.toggle('opacity-50', nextRunning);
    });
}

export async function triggerTask({
    local = false,
    full = false,
    isRunning = false,
    btnTexts = [],
    setIsRunning,
} = {}) {
    if (isRunning) return false;
    try {
        await window.MediaHubApi.postJson('/tree/sync-all', {});
        if (typeof setIsRunning === 'function') setIsRunning(true);
        return true;
    } catch (error) {
        showToast(`触发失败：${error?.message || error}`);
        return false;
    }
}

export function applyMainState(data, {
    getIsRunning,
    btnTexts = [],
    setIsRunning,
    getLastLogSignature,
    setLastLogSignature,
    buildLogSignature,
    getLogEntryClass,
    formatLogHtml,
} = {}) {
    if (!data) return;

    const isRunning = typeof getIsRunning === 'function' ? !!getIsRunning() : false;
    if (data.running !== isRunning) {
        updateButtonState({ running: !!data.running, btnTexts, setIsRunning });
    }
    if (treeLastRunning && !data.running) {
        void loadTreeTasks();
    }
    treeLastRunning = !!data.running;

    const logBox = document.getElementById('log-box');
    const logs = Array.isArray(data.logs) ? data.logs : [];
    const formatter = typeof buildLogSignature === 'function'
        ? buildLogSignature
        : ((items, itemFormatter) => `${Array.isArray(items) ? items.length : 0}:${typeof itemFormatter === 'function' ? itemFormatter(items?.[items.length - 1]) : ''}`);
    const logSignature = formatter(logs, (item) => `${item?.level || 'info'}:${item?.text || ''}`);
    const lastLogSignature = typeof getLastLogSignature === 'function' ? String(getLastLogSignature() || '') : '';
    if (logBox && logSignature !== lastLogSignature) {
        const getEntryClass = typeof getLogEntryClass === 'function' ? getLogEntryClass : (() => '');
        const renderLogHtml = typeof formatLogHtml === 'function' ? formatLogHtml : ((item) => String(item?.text || ''));
        logBox.innerHTML = logs.map(item => `<div class="${getEntryClass(item)}">${renderLogHtml(item)}</div>`).join('');
        logBox.scrollTop = logBox.scrollHeight;
        if (typeof setLastLogSignature === 'function') setLastLogSignature(logSignature);
    }

    const progress = data.progress || {};
    const stepEl = document.getElementById('prog-step');
    if (stepEl) stepEl.innerText = progress.step || '空闲';
    const percentEl = document.getElementById('prog-percent');
    if (percentEl) percentEl.innerText = `${Number(progress.percent || 0)}%`;
    const barEl = document.getElementById('prog-bar');
    if (barEl) barEl.style.width = `${Number(progress.percent || 0)}%`;
    const detailEl = document.getElementById('prog-detail');
    if (detailEl) detailEl.innerText = progress.detail || '等待指令';
}

export async function refreshMainLogs({ applyMainState, compact = false } = {}) {
    try {
        const endpoint = compact ? '/tree/logs?compact=1' : '/tree/logs';
        const data = await window.MediaHubApi.getJson(endpoint);
        if (typeof applyMainState === 'function') {
            await applyMainState(data);
        }
    } catch (e) {}
}

export async function clearMainLogs({
    setLastLogSignature,
    refreshMainLogs,
} = {}) {
    await window.MediaHubApi.postJson('/tree/logs/clear');
    if (typeof setLastLogSignature === 'function') setLastLogSignature('');
    if (typeof refreshMainLogs === 'function') {
        await refreshMainLogs();
    }
}
