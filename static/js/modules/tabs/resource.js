export async function ensureTabData(context) {
    context.moduleVisitState.resource = true;
    if (!context.isResourceStateHydrated()) {
        await context.refreshResourceState();
    }
}

export async function refreshResourceState({
    allowSearch = true,
    keywordOverride = null,
    getResourceState,
    isDirectImportInput,
    setResourceStateHydrated,
    applyResourceState,
} = {}) {
    try {
        const currentResourceState = typeof getResourceState === 'function' ? (getResourceState() || {}) : {};
        const activeKeyword = typeof keywordOverride === 'string'
            ? keywordOverride.trim()
            : String(currentResourceState.search || '').trim();
        const shouldSearchChannels = !!activeKeyword
            && typeof isDirectImportInput === 'function'
            && !isDirectImportInput(activeKeyword)
            && allowSearch;
        const params = new URLSearchParams();
        if (shouldSearchChannels) params.set('q', activeKeyword);
        const endpoint = params.toString() ? `/resource/state?${params.toString()}` : '/resource/state';
        const res = await fetch(endpoint);
        if (!res.ok) return null;
        const data = await res.json();
        if (typeof setResourceStateHydrated === 'function') setResourceStateHydrated(true);
        if (typeof applyResourceState === 'function') applyResourceState(data);
        return data;
    } catch (e) {
        return null;
    }
}

export function hasActiveResourceJobs({ getResourceState } = {}) {
    const currentResourceState = typeof getResourceState === 'function' ? (getResourceState() || {}) : {};
    const jobs = Array.isArray(currentResourceState?.jobs) ? currentResourceState.jobs : [];
    const activeCount = Number(currentResourceState?.job_counts?.active ?? currentResourceState?.stats?.active_job_count ?? 0) || 0;
    if (activeCount > 0) return true;
    return jobs.some((job) => {
        const status = String(job?.status || '').trim().toLowerCase();
        return ['pending', 'running', 'queued', 'importing', 'submitted'].includes(status);
    });
}

export function applyResourceJobsState(data, {
    getResourceState,
    setResourceState,
    getResourceJobCounts,
    syncResourceMonitorTaskOptions,
    renderResourceJobs,
    syncResourceJobModalTrigger,
    renderResourceBoard,
    renderResourceBoardHint,
    isResourceTabActive,
} = {}) {
    if (!data || typeof data !== 'object') return;
    const currentResourceState = typeof getResourceState === 'function' ? (getResourceState() || {}) : {};
    const nextJobs = Array.isArray(data.jobs) ? data.jobs : (currentResourceState.jobs || []);
    const nextActiveJobs = Array.isArray(data.active_jobs) ? data.active_jobs : (currentResourceState.active_jobs || []);
    const nextMonitorTasks = Array.isArray(data.monitor_tasks) ? data.monitor_tasks : (currentResourceState.monitor_tasks || []);
    const incomingStats = data.stats && typeof data.stats === 'object' ? data.stats : {};
    const nextJobCounts = data.job_counts && typeof data.job_counts === 'object'
        ? data.job_counts
        : (currentResourceState.job_counts || {});
    const nextJobPagination = data.pagination && typeof data.pagination === 'object'
        ? data.pagination
        : (currentResourceState.job_pagination || {});
    const fallbackCounts = typeof getResourceJobCounts === 'function'
        ? (getResourceJobCounts(nextJobs) || {})
        : {};
    const nextState = {
        ...currentResourceState,
        jobs: nextJobs,
        active_jobs: nextActiveJobs,
        job_counts: nextJobCounts,
        job_pagination: nextJobPagination,
        monitor_tasks: nextMonitorTasks,
        stats: {
            ...(currentResourceState.stats || {}),
            total_job_count: Number(incomingStats.total_job_count ?? nextJobCounts.total ?? fallbackCounts.total ?? 0),
            active_job_count: Number(incomingStats.active_job_count ?? nextJobCounts.active ?? fallbackCounts.active ?? 0),
            completed_job_count: Number(incomingStats.completed_job_count ?? nextJobCounts.completed ?? fallbackCounts.completed ?? 0),
            failed_job_count: Number(incomingStats.failed_job_count ?? nextJobCounts.failed ?? fallbackCounts.failed ?? 0),
        }
    };
    if (typeof setResourceState === 'function') setResourceState(nextState);
    if (typeof syncResourceMonitorTaskOptions === 'function') {
        syncResourceMonitorTaskOptions(document.getElementById('resource_job_savepath')?.value || '');
    }
    if (typeof renderResourceJobs === 'function') renderResourceJobs();
    if (typeof syncResourceJobModalTrigger === 'function') syncResourceJobModalTrigger();
    if (typeof isResourceTabActive === 'function' ? isResourceTabActive() : false) {
        if (typeof renderResourceBoard === 'function') renderResourceBoard();
        if (typeof renderResourceBoardHint === 'function') renderResourceBoardHint();
    }
}

export async function refreshResourceJobsOnly({ applyResourceJobsState, buildResourceJobsStateUrl } = {}) {
    try {
        const endpoint = typeof buildResourceJobsStateUrl === 'function'
            ? buildResourceJobsStateUrl()
            : '/resource/jobs/state';
        const res = await fetch(endpoint);
        if (!res.ok) return null;
        const data = await res.json();
        if (typeof applyResourceJobsState === 'function') applyResourceJobsState(data);
        return data;
    } catch (e) {
        return null;
    }
}
