(function (global) {
    function normalizeHeaders(headers) {
        return Object.assign({}, headers || {});
    }

    async function readJsonResponse(response) {
        const text = await response.text();
        if (!text) return {};
        try {
            return JSON.parse(text);
        } catch (error) {
            if (!response.ok) {
                return { ok: false, msg: text || `HTTP ${response.status}` };
            }
            throw new Error('后端返回内容不是有效 JSON');
        }
    }

    function buildApiError(response, payload) {
        const message = String(
            payload?.msg
            || payload?.message
            || payload?.detail
            || `请求失败（HTTP ${response.status}）`
        ).trim();
        const error = new Error(message || '请求失败');
        error.status = response.status;
        error.payload = payload;
        return error;
    }

    async function requestJson(url, options) {
        const opts = options || {};
        const headers = normalizeHeaders(opts.headers);
        const init = {
            ...opts,
            credentials: opts.credentials || 'same-origin',
            headers,
        };
        if (Object.prototype.hasOwnProperty.call(opts, 'json')) {
            headers['Content-Type'] = headers['Content-Type'] || 'application/json';
            init.body = JSON.stringify(opts.json);
            delete init.json;
        }

        const response = await fetch(url, init);
        const payload = await readJsonResponse(response);
        if (!response.ok || payload?.ok === false) {
            throw buildApiError(response, payload);
        }
        return payload;
    }

    function getJson(url, options) {
        return requestJson(url, {
            ...(options || {}),
            method: 'GET',
        });
    }

    function postJson(url, payload, options) {
        return requestJson(url, {
            ...(options || {}),
            method: 'POST',
            json: payload || {},
        });
    }

    global.MediaHubApi = {
        ...(global.MediaHubApi || {}),
        requestJson,
        getJson,
        postJson,
    };
})(window);
