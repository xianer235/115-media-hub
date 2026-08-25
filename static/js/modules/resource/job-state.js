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
        let pageIntentRevision = 0;
        let activePageRequestRevision = 0;
        let activePollRequestRevision = 0;
        let activePageRequestPending = false;
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
            const requestMode = mode === 'poll' ? 'poll' : 'page';
            if (reset || nextFilter !== filter) {
                filter = nextFilter;
                page = 1;
            }
            page = reset ? 1 : Math.max(1, Math.floor(Number(requestedPage) || 1));
            requestRevision += 1;
            if (requestMode === 'page') {
                pageIntentRevision += 1;
                activePageRequestRevision = requestRevision;
                activePageRequestPending = true;
            } else {
                activePollRequestRevision = requestRevision;
            }
            loading = true;
            error = '';
            return {
                status: filter,
                page,
                page_size: pageSize,
                revision: requestRevision,
                mode: requestMode,
                page_intent_revision: pageIntentRevision,
            };
        }

        function accept(request, data = {}) {
            const requestRevisionValue = Number(request?.revision || 0);
            const isPoll = request?.mode === 'poll';
            const isStale = request && (
                (isPoll && (
                    requestRevisionValue !== activePollRequestRevision
                    || Number(request.page_intent_revision || 0) !== pageIntentRevision
                    || activePageRequestPending
                ))
                || (!isPoll && (
                    requestRevisionValue !== activePageRequestRevision
                    || Number(request.page_intent_revision || 0) !== pageIntentRevision
                ))
            );
            if (isStale) {
                return { accepted: false, stale: true, needsCalibration: false, ...snapshot() };
            }
            const payload = data && typeof data === 'object' ? data : {};
            const incomingJobs = Array.isArray(payload.jobs) ? payload.jobs : jobs;
            const incomingActiveJobs = Array.isArray(payload.active_jobs) ? payload.active_jobs : activeJobs;
            const priorActiveSignature = buildActiveSignature(activeJobs);
            const nextActiveSignature = buildActiveSignature(incomingActiveJobs);
            jobs = incomingJobs.slice(0, pageSize);
            activeJobs = incomingActiveJobs;
            pagination = payload.pagination && typeof payload.pagination === 'object' ? payload.pagination : pagination;
            if (!isPoll && requestRevisionValue === activePageRequestRevision) {
                activePageRequestPending = false;
            }
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
            const requestRevisionValue = Number(request?.revision || 0);
            const isPoll = request?.mode === 'poll';
            const isStale = request && (
                (isPoll && (
                    requestRevisionValue !== activePollRequestRevision
                    || Number(request.page_intent_revision || 0) !== pageIntentRevision
                    || activePageRequestPending
                ))
                || (!isPoll && (
                    requestRevisionValue !== activePageRequestRevision
                    || Number(request.page_intent_revision || 0) !== pageIntentRevision
                ))
            );
            if (isStale) {
                return { accepted: false, stale: true, ...snapshot() };
            }
            if (!isPoll && requestRevisionValue === activePageRequestRevision) {
                activePageRequestPending = false;
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
