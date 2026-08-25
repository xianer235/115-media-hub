(function (global) {
    const DEFAULT_PAGE_SIZE = 10;
    function normalizeFilter(value) {
        const normalized = String(value || 'all').trim().toLowerCase();
        return ['all', 'active', 'submitted', 'completed', 'failed'].includes(normalized) ? normalized : 'all';
    }

    function normalizePositiveInteger(value, fallback, maximum) {
        const normalized = Math.floor(Number(value) || 0);
        if (normalized <= 0) return fallback;
        return Math.min(maximum, normalized);
    }

    function buildActiveSignature(jobs) {
        return (Array.isArray(jobs) ? jobs : [])
            .map((job) => `${Number(job?.id || 0) || 0}:${String(job?.status || '').trim().toLowerCase()}`)
            .sort()
            .join('|');
    }

    function create(options = {}) {
        const pageSize = normalizePositiveInteger(options.pageSize, DEFAULT_PAGE_SIZE, 100);
        let filter = normalizeFilter(options.filter || 'all');
        let page = 1;
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
                page,
                pageSize,
                jobs,
                activeJobs,
                pagination: {
                    ...pagination,
                    status: filter,
                    page,
                    page_size: pageSize,
                },
                loading,
                error,
            };
        }

        function begin({ status = filter, page: requestedPage = page, reset = false, mode = 'page' } = {}) {
            const nextFilter = normalizeFilter(status);
            if (reset || nextFilter !== filter) {
                filter = nextFilter;
                page = 1;
            }
            page = reset ? 1 : Math.max(1, Math.floor(Number(requestedPage) || 1));
            requestRevision += 1;
            activeRequestRevision = requestRevision;
            loading = true;
            error = '';
            return {
                status: filter,
                page,
                page_size: pageSize,
                revision: requestRevision,
                mode: mode === 'poll' ? 'poll' : 'page',
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
            jobs = incomingJobs;
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
        };
    }

    global.ResourceJobState = {
        DEFAULT_PAGE_SIZE,
        create,
    };
})(window);
