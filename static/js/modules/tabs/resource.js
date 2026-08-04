export async function ensureTabData(context) {
    context.moduleVisitState.resource = true;
    if (!context.isResourceStateHydrated()) {
        await context.refreshResourceState();
    }
}

export async function refreshResourceState({
    allowSearch = true,
    keywordOverride = null,
    searchId = '',
    signal = null,
    compact = false,
    getResourceState,
    getResourceJobsStateRequest,
    isDirectImportInput,
    setResourceStateHydrated,
    applyResourceState,
    rejectResourceJobsRequest,
} = {}) {
    let jobRequest = null;
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
        params.set('search_source', String(currentResourceState.search_source || 'tg').trim() || 'tg');
        params.set('provider_filter', 'all');
        if (searchId) params.set('search_id', String(searchId || '').trim());
        jobRequest = typeof getResourceJobsStateRequest === 'function'
            ? (getResourceJobsStateRequest() || {})
            : {};
        const jobStatus = String(jobRequest.status || 'all').trim() || 'all';
        const jobOffset = Math.max(0, Number(jobRequest.offset || 0) || 0);
        const jobLimit = Math.max(1, Number(jobRequest.limit || 20) || 20);
        params.set('job_status', jobStatus);
        params.set('job_offset', String(jobOffset));
        params.set('job_limit', String(jobLimit));
        if (compact && !shouldSearchChannels) params.set('compact', '1');
        const endpoint = params.toString() ? `/resource/state?${params.toString()}` : '/resource/state';
        const data = window.MediaHubApi?.getJson
            ? await window.MediaHubApi.getJson(endpoint, signal ? { signal } : undefined)
            : await (async () => {
                const res = await fetch(endpoint, signal ? { signal } : undefined);
                if (!res.ok) return null;
                return res.json();
            })();
        if (!data) return null;
        if (typeof setResourceStateHydrated === 'function') setResourceStateHydrated(true);
        if (typeof applyResourceState === 'function') {
            applyResourceState(data, { compactUpdate: !!compact, jobRequest });
        }
        return data;
    } catch (e) {
        if (e?.name === 'AbortError') throw e;
        if (typeof rejectResourceJobsRequest === 'function') rejectResourceJobsRequest(jobRequest, e);
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

function normalizeResourceItemStatusFromJob(status) {
    const normalized = String(status || '').trim().toLowerCase();
    if (normalized === 'running') return 'importing';
    if (normalized === 'pending') return 'queued';
    if (['queued', 'importing', 'submitted', 'completed', 'failed'].includes(normalized)) return normalized;
    return '';
}

function buildResourceItemStatusByJob(jobs = [], activeJobs = []) {
    const statusByResourceId = new Map();
    [...(Array.isArray(jobs) ? jobs : []), ...(Array.isArray(activeJobs) ? activeJobs : [])].forEach((job) => {
        const resourceId = Number(job?.resource_id || 0) || 0;
        if (!resourceId || statusByResourceId.has(resourceId)) return;
        const status = normalizeResourceItemStatusFromJob(job?.status || '');
        if (status) statusByResourceId.set(resourceId, status);
    });
    return statusByResourceId;
}

function applyResourceJobStatusesToItems(items = [], statusByResourceId = new Map()) {
    if (!statusByResourceId.size || !Array.isArray(items)) return items;
    let changed = false;
    const nextItems = items.map((item) => {
        const resourceId = Number(item?.id || 0) || 0;
        const status = statusByResourceId.get(resourceId);
        if (!resourceId || !status || String(item?.status || '') === status) return item;
        changed = true;
        return { ...item, status };
    });
    return changed ? nextItems : items;
}

function applyResourceJobStatusesToSections(sections = [], statusByResourceId = new Map()) {
    if (!statusByResourceId.size || !Array.isArray(sections)) return sections;
    let changed = false;
    const nextSections = sections.map((section) => {
        const items = Array.isArray(section?.items) ? section.items : [];
        const nextItems = applyResourceJobStatusesToItems(items, statusByResourceId);
        if (nextItems === items) return section;
        changed = true;
        return { ...section, items: nextItems };
    });
    return changed ? nextSections : sections;
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
    const nextJobStatusByResourceId = buildResourceItemStatusByJob(nextJobs, nextActiveJobs);
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
        items: applyResourceJobStatusesToItems(currentResourceState.items || [], nextJobStatusByResourceId),
        channel_sections: applyResourceJobStatusesToSections(currentResourceState.channel_sections || [], nextJobStatusByResourceId),
        search_sections: applyResourceJobStatusesToSections(currentResourceState.search_sections || [], nextJobStatusByResourceId),
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

export async function refreshResourceJobsOnly({
    applyResourceJobsState,
    buildResourceJobsStateUrl,
    getResourceJobsStateRequest,
    rejectResourceJobsRequest,
    requestOptions = {},
} = {}) {
    let jobRequest = null;
    try {
        jobRequest = typeof getResourceJobsStateRequest === 'function'
            ? (getResourceJobsStateRequest(requestOptions) || {})
            : {};
        const endpoint = typeof buildResourceJobsStateUrl === 'function'
            ? buildResourceJobsStateUrl(jobRequest)
            : '/resource/jobs/state';
        const data = window.MediaHubApi?.getJson
            ? await window.MediaHubApi.getJson(endpoint)
            : await (async () => {
                const res = await fetch(endpoint);
                if (!res.ok) return null;
                return res.json();
            })();
        if (!data) return null;
        if (typeof applyResourceJobsState === 'function') applyResourceJobsState(data, { jobRequest });
        return data;
    } catch (e) {
        if (typeof rejectResourceJobsRequest === 'function') rejectResourceJobsRequest(jobRequest, e);
        return null;
    }
}
