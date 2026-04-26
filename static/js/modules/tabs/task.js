export async function ensureTabData(context) {
    if (!context.moduleVisitState.task) {
        await context.refreshMainLogs();
        context.moduleVisitState.task = true;
    }
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
}

export async function triggerTask({
    local = false,
    full = false,
    isRunning = false,
    btnTexts = [],
    setIsRunning,
} = {}) {
    if (isRunning) return false;
    const data = await window.MediaHubApi.postJson('/start', { use_local: !!local, force_full: !!full }).catch(() => null);
    if (data?.status === 'started') {
        updateButtonState({ running: true, btnTexts, setIsRunning });
        return true;
    }
    return false;
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

    const nextRunContainer = document.getElementById('next-run-container');
    const nextRunTime = document.getElementById('next-run-time');
    if (data.next_run) {
        if (nextRunContainer) nextRunContainer.classList.remove('hidden');
        if (nextRunTime) nextRunTime.innerText = data.next_run;
    } else if (nextRunContainer) {
        nextRunContainer.classList.add('hidden');
    }
}

export async function refreshMainLogs({ applyMainState } = {}) {
    try {
        const data = await window.MediaHubApi.getJson('/logs');
        if (typeof applyMainState === 'function') {
            await applyMainState(data);
        }
    } catch (e) {}
}

export async function clearMainLogs({
    setLastLogSignature,
    refreshMainLogs,
} = {}) {
    await window.MediaHubApi.postJson('/logs/clear');
    if (typeof setLastLogSignature === 'function') setLastLogSignature('');
    if (typeof refreshMainLogs === 'function') {
        await refreshMainLogs();
    }
}
