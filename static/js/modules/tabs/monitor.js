export async function ensureTabData(context) {
    if (!context.moduleVisitState.monitor) {
        await context.refreshMonitorState();
        context.moduleVisitState.monitor = true;
    }
}

function mergeMonitorLogSegments(currentState, data) {
    const incoming = Array.isArray(data?.log_segments) ? data.log_segments : null;
    if (!incoming) return Array.isArray(currentState?.log_segments) ? currentState.log_segments : [];

    const current = Array.isArray(currentState?.log_segments) ? currentState.log_segments : [];
    const previousTotal = Number(currentState?.log_segment_total || 0) || current.length;
    const nextTotal = Number(data?.log_segment_total || 0) || incoming.length;
    if (nextTotal < previousTotal || current.length <= incoming.length) return incoming;

    const incomingIds = new Set(incoming.map((segment) => String(segment?.id || '')).filter(Boolean));
    const older = current.filter((segment) => {
        const id = String(segment?.id || '');
        return id && !incomingIds.has(id);
    });
    return [...older, ...incoming];
}

function setMonitorSummary(summary) {
    const step = String(summary?.step || '空闲').trim() || '空闲';
    const detail = String(summary?.detail || '等待监控任务').trim() || '等待监控任务';
    const fullText = `当前状态：${step} / ${detail}`;

    const summaryStep = document.getElementById('monitor-summary-step');
    if (summaryStep) summaryStep.innerText = step;
    const summaryDetail = document.getElementById('monitor-summary-detail');
    if (summaryDetail) {
        summaryDetail.innerText = detail;
        summaryDetail.setAttribute('title', detail);
    }
    const summaryPill = document.getElementById('monitor-summary-pill');
    if (summaryPill) {
        summaryPill.setAttribute('title', fullText);
        summaryPill.setAttribute('aria-label', fullText);
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
    if (currentMonitorState.run_filtered || currentMonitorState.run_loading || Number(currentMonitorState.run_page || 1) > 1) {
        data = {
            ...data,
            runs: currentMonitorState.runs,
            run_has_more: currentMonitorState.run_has_more,
            run_next_cursor: currentMonitorState.run_next_cursor,
        };
    }
    const logSegments = mergeMonitorLogSegments(currentMonitorState, data);
    const logSegmentTotal = Number(data.log_segment_total || currentMonitorState.log_segment_total || logSegments.length) || logSegments.length;
    const nextState = {
        ...currentMonitorState,
        ...data,
        tasks: Array.isArray(data.tasks) ? data.tasks : (currentMonitorState.tasks || []),
        logs: Array.isArray(data.logs) ? data.logs : (currentMonitorState.logs || []),
        log_segments: logSegments,
        log_segment_total: logSegmentTotal,
        log_segment_has_more: logSegments.length < logSegmentTotal,
        runs: Array.isArray(data.runs) ? data.runs : (currentMonitorState.runs || []),
        run_has_more: data.run_has_more !== undefined ? !!data.run_has_more : !!currentMonitorState.run_has_more,
        run_next_cursor: data.run_next_cursor ?? currentMonitorState.run_next_cursor ?? '',
        run_retention: data.run_retention || currentMonitorState.run_retention || { mode: 'longterm', days: 30 },
        queued: Array.isArray(data.queued) ? data.queued : (currentMonitorState.queued || []),
        next_runs: data.next_runs || currentMonitorState.next_runs || {},
        summary: data.summary || currentMonitorState.summary || { step: '空闲', detail: '等待监控任务' }
    };
    if (typeof setMonitorState === 'function') setMonitorState(nextState);

    const expandedMap = typeof getIntroExpanded === 'function' ? getIntroExpanded() : {};
    if (typeof setIntroExpanded === 'function' && typeof pruneTaskIntroExpanded === 'function') {
        setIntroExpanded(pruneTaskIntroExpanded(expandedMap, nextState.tasks));
    }

    setMonitorSummary(nextState.summary);

    const renderKey = typeof buildMonitorRenderKey === 'function' ? buildMonitorRenderKey(nextState) : '';
    const lastRenderKey = typeof getLastMonitorRenderKey === 'function' ? String(getLastMonitorRenderKey() || '') : '';
    if (forceRender || renderKey !== lastRenderKey) {
        if (typeof renderMonitorTasks === 'function') renderMonitorTasks();
        if (typeof setLastMonitorRenderKey === 'function') setLastMonitorRenderKey(renderKey);
    }
    if (typeof renderMonitorLogs === 'function') renderMonitorLogs();
    if (typeof afterApply === 'function') afterApply(nextState);
}

export async function refreshMonitorState({ applyMonitorState, compact = false } = {}) {
    try {
        const endpoint = compact ? '/monitor/status?compact=1' : '/monitor/status';
        const data = await window.MediaHubApi.getJson(endpoint);
        if (typeof applyMonitorState === 'function') applyMonitorState(data);
    } catch (e) {}
}

export async function clearMonitorLogs({
    setLastMonitorLogSignature,
    refreshMonitorState,
} = {}) {
    await window.MediaHubApi.postJson('/monitor/logs/clear');
    if (typeof setLastMonitorLogSignature === 'function') setLastMonitorLogSignature('');
    if (typeof refreshMonitorState === 'function') {
        await refreshMonitorState();
    }
}
