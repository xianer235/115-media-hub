export async function ensureTabData(context) {
    if (!context.moduleVisitState.monitor) {
        await context.refreshMonitorState();
        context.moduleVisitState.monitor = true;
    }
}

export function applyMonitorState(data, {
    forceRender = false,
    getMonitorState,
    setMonitorState,
    getIntroExpanded,
    setIntroExpanded,
    pruneTaskIntroExpanded,
    buildMonitorRenderKey,
    getLastMonitorRenderKey,
    setLastMonitorRenderKey,
    renderMonitorTasks,
    renderMonitorLogs,
    afterApply,
} = {}) {
    if (!data) return;
    const currentMonitorState = typeof getMonitorState === 'function' ? (getMonitorState() || {}) : {};
    const nextState = {
        ...currentMonitorState,
        ...data,
        tasks: Array.isArray(data.tasks) ? data.tasks : (currentMonitorState.tasks || []),
        logs: Array.isArray(data.logs) ? data.logs : (currentMonitorState.logs || []),
        queued: Array.isArray(data.queued) ? data.queued : (currentMonitorState.queued || []),
        next_runs: data.next_runs || currentMonitorState.next_runs || {},
        summary: data.summary || currentMonitorState.summary || { step: '空闲', detail: '等待监控任务' }
    };
    if (typeof setMonitorState === 'function') setMonitorState(nextState);

    const expandedMap = typeof getIntroExpanded === 'function' ? getIntroExpanded() : {};
    if (typeof setIntroExpanded === 'function' && typeof pruneTaskIntroExpanded === 'function') {
        setIntroExpanded(pruneTaskIntroExpanded(expandedMap, nextState.tasks));
    }

    const summaryStep = document.getElementById('monitor-summary-step');
    if (summaryStep) summaryStep.innerText = nextState.summary?.step || '空闲';
    const summaryDetail = document.getElementById('monitor-summary-detail');
    if (summaryDetail) summaryDetail.innerText = nextState.summary?.detail || '等待监控任务';

    const renderKey = typeof buildMonitorRenderKey === 'function' ? buildMonitorRenderKey(nextState) : '';
    const lastRenderKey = typeof getLastMonitorRenderKey === 'function' ? String(getLastMonitorRenderKey() || '') : '';
    if (forceRender || renderKey !== lastRenderKey) {
        if (typeof renderMonitorTasks === 'function') renderMonitorTasks();
        if (typeof setLastMonitorRenderKey === 'function') setLastMonitorRenderKey(renderKey);
    }
    if (typeof renderMonitorLogs === 'function') renderMonitorLogs();
    if (typeof afterApply === 'function') afterApply(nextState);
}

export async function refreshMonitorState({ applyMonitorState } = {}) {
    try {
        const res = await fetch('/monitor/status');
        if (!res.ok) return;
        const data = await res.json();
        if (typeof applyMonitorState === 'function') applyMonitorState(data);
    } catch (e) {}
}

export async function clearMonitorLogs({
    setLastMonitorLogSignature,
    refreshMonitorState,
} = {}) {
    const res = await fetch('/monitor/logs/clear', { method: 'POST' });
    if (!res.ok) return;
    if (typeof setLastMonitorLogSignature === 'function') setLastMonitorLogSignature('');
    if (typeof refreshMonitorState === 'function') {
        await refreshMonitorState();
    }
}
