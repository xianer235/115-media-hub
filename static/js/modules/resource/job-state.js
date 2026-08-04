(function (global) {
    const DEFAULT_WINDOW_SIZE = 20;
    const MAX_WINDOW_SIZE = 25000;
    const ACTIVE_STATUSES = new Set(['pending', 'running', 'submitted']);

    function normalizeFilter(value) {
        const normalized = String(value || 'all').trim().toLowerCase();
        return ['all', 'active', 'submitted', 'completed', 'failed'].includes(normalized) ? normalized : 'all';
    }

    function normalizePositiveInteger(value, fallback, maximum) {
        const normalized = Math.floor(Number(value) || 0);
        if (normalized <= 0) return fallback;
        return Math.min(maximum, normalized);
    }

    function getJobKey(job, index) {
        const id = Number(job?.id || 0) || 0;
        return id > 0 ? `id:${id}` : `fallback:${String(job?.title || '')}:${index}`;
    }

    function isActiveJob(job) {
        return ACTIVE_STATUSES.has(String(job?.status || '').trim().toLowerCase());
    }

    function isJobVisibleInFilter(job, filter) {
        const status = String(job?.status || '').trim().toLowerCase();
        if (filter === 'all') return true;
        if (filter === 'active') return isActiveJob(job);
        return status === filter;
    }

    function mergeJobs(primaryJobs, secondaryJobs) {
        const seen = new Set();
        const merged = [];
        [...(Array.isArray(primaryJobs) ? primaryJobs : []), ...(Array.isArray(secondaryJobs) ? secondaryJobs : [])]
            .forEach((job, index) => {
                const key = getJobKey(job, index);
                if (seen.has(key)) return;
                seen.add(key);
                merged.push(job);
            });
        return merged;
    }

    function buildActiveSignature(jobs) {
        return (Array.isArray(jobs) ? jobs : [])
            .map((job) => `${Number(job?.id || 0) || 0}:${String(job?.status || '').trim().toLowerCase()}`)
            .sort()
            .join('|');
    }

    function create(options = {}) {
        const pageSize = normalizePositiveInteger(options.pageSize, DEFAULT_WINDOW_SIZE, MAX_WINDOW_SIZE);
        const maxWindowSize = normalizePositiveInteger(options.maxWindowSize, MAX_WINDOW_SIZE, MAX_WINDOW_SIZE);
        let filter = normalizeFilter(options.filter || 'all');
        let windowSize = pageSize;
        let jobs = [];
        let activeJobs = [];
        let pagination = {};
        let requestRevision = 0;
        let activeRequestRevision = 0;
        let loading = false;
        let error = '';

        function snapshot() {
            return {
                filter,
                windowSize,
                jobs,
                activeJobs,
                pagination: {
                    ...pagination,
                    status: filter,
                    limit: windowSize,
                    offset: 0,
                    next_offset: jobs.length,
                    loaded_count: jobs.length,
                },
                loading,
                error,
            };
        }

        function begin({ status = filter, reset = false, extend = false, mode = 'window' } = {}) {
            const nextFilter = normalizeFilter(status);
            if (reset || nextFilter !== filter) {
                filter = nextFilter;
                windowSize = pageSize;
            }
            if (extend) {
                windowSize = Math.min(maxWindowSize, windowSize + pageSize);
            }
            requestRevision += 1;
            activeRequestRevision = requestRevision;
            loading = true;
            error = '';
            const requestMode = mode === 'poll' ? 'poll' : 'window';
            return {
                status: filter,
                offset: 0,
                limit: requestMode === 'poll' ? pageSize : windowSize,
                revision: requestRevision,
                mode: requestMode,
            };
        }

        function accept(request, data = {}) {
            if (request && Number(request.revision || 0) !== activeRequestRevision) {
                return { accepted: false, stale: true, needsCalibration: false, ...snapshot() };
            }
            const payload = data && typeof data === 'object' ? data : {};
            const incomingJobs = Array.isArray(payload.jobs) ? payload.jobs : jobs;
            const incomingActiveJobs = Array.isArray(payload.active_jobs) ? payload.active_jobs : activeJobs;
            const priorActiveSignature = buildActiveSignature(activeJobs);
            const nextActiveSignature = buildActiveSignature(incomingActiveJobs);
            const isPoll = request?.mode === 'poll';
            const activeVisibleJobs = filter === 'all' || filter === 'active'
                ? incomingActiveJobs.filter(job => isJobVisibleInFilter(job, filter))
                : [];
            jobs = isPoll
                ? mergeJobs(mergeJobs(incomingJobs, activeVisibleJobs), jobs)
                : incomingJobs;
            activeJobs = incomingActiveJobs;
            pagination = payload.pagination && typeof payload.pagination === 'object' ? payload.pagination : pagination;
            loading = false;
            error = '';
            return {
                accepted: true,
                stale: false,
                needsCalibration: isPoll && priorActiveSignature !== nextActiveSignature,
                ...snapshot(),
            };
        }

        function reject(request, reason) {
            if (request && Number(request.revision || 0) !== activeRequestRevision) {
                return { accepted: false, stale: true, ...snapshot() };
            }
            loading = false;
            error = String(reason?.message || reason || '任务列表加载失败，请稍后重试');
            return { accepted: true, stale: false, ...snapshot() };
        }

        return {
            begin,
            accept,
            reject,
            snapshot,
            get pageSize() { return pageSize; },
            get maxWindowSize() { return maxWindowSize; },
        };
    }

    global.ResourceJobState = {
        DEFAULT_WINDOW_SIZE,
        MAX_WINDOW_SIZE,
        create,
    };
})(window);
