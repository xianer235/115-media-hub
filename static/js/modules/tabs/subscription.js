export async function ensureTabData(context) {
    if (!context.moduleVisitState.subscription) {
        await context.refreshSubscriptionState();
        context.moduleVisitState.subscription = true;
    }
}

export function applySubscriptionState(data, {
    forceRender = false,
    getSubscriptionState,
    setSubscriptionState,
    getIntroExpanded,
    setIntroExpanded,
    pruneTaskIntroExpanded,
    buildSubscriptionRenderKey,
    getLastSubscriptionRenderKey,
    setLastSubscriptionRenderKey,
    renderSubscriptionTasks,
    renderSubscriptionLogs,
} = {}) {
    if (!data) return;
    const currentSubscriptionState = typeof getSubscriptionState === 'function' ? (getSubscriptionState() || {}) : {};
    const nextState = {
        ...currentSubscriptionState,
        ...data,
        tasks: Array.isArray(data.tasks) ? data.tasks : (currentSubscriptionState.tasks || []),
        logs: Array.isArray(data.logs) ? data.logs : (currentSubscriptionState.logs || []),
        queued: Array.isArray(data.queued) ? data.queued : (currentSubscriptionState.queued || []),
        next_runs: data.next_runs || currentSubscriptionState.next_runs || {},
        summary: data.summary || currentSubscriptionState.summary || { step: '空闲', detail: '等待订阅任务' }
    };
    if (typeof setSubscriptionState === 'function') setSubscriptionState(nextState);

    const expandedMap = typeof getIntroExpanded === 'function' ? getIntroExpanded() : {};
    if (typeof setIntroExpanded === 'function' && typeof pruneTaskIntroExpanded === 'function') {
        setIntroExpanded(pruneTaskIntroExpanded(expandedMap, nextState.tasks));
    }

    const stepEl = document.getElementById('subscription-summary-step');
    if (stepEl) stepEl.innerText = nextState.summary?.step || '空闲';
    const detailEl = document.getElementById('subscription-summary-detail');
    if (detailEl) detailEl.innerText = nextState.summary?.detail || '等待订阅任务';

    const renderKey = typeof buildSubscriptionRenderKey === 'function' ? buildSubscriptionRenderKey(nextState) : '';
    const lastRenderKey = typeof getLastSubscriptionRenderKey === 'function' ? String(getLastSubscriptionRenderKey() || '') : '';
    if (forceRender || renderKey !== lastRenderKey) {
        if (typeof renderSubscriptionTasks === 'function') renderSubscriptionTasks();
        if (typeof setLastSubscriptionRenderKey === 'function') setLastSubscriptionRenderKey(renderKey);
    }
    if (typeof renderSubscriptionLogs === 'function') renderSubscriptionLogs();
}

export async function refreshSubscriptionState({ applySubscriptionState } = {}) {
    try {
        const res = await fetch('/subscription/status');
        if (!res.ok) return;
        const data = await res.json();
        if (typeof applySubscriptionState === 'function') applySubscriptionState(data);
    } catch (e) {}
}

export async function clearSubscriptionLogs({
    setLastSubscriptionLogSignature,
    refreshSubscriptionState,
} = {}) {
    const res = await fetch('/subscription/logs/clear', { method: 'POST' });
    if (!res.ok) return;
    if (typeof setLastSubscriptionLogSignature === 'function') setLastSubscriptionLogSignature('');
    if (typeof refreshSubscriptionState === 'function') {
        await refreshSubscriptionState();
    }
}
