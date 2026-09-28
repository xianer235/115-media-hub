(function (global) {
    'use strict';

    const statuses = {
        queued: '排队中', running: '执行中', waiting: '等待后续同步',
        completed: '已完成', no_change: '无变化', partial: '部分完成',
        failed: '失败', cancelled: '已中断', pending: '等待处理', skipped: '未处理',
        manual_required: '等待系统补扫', rollback_failed: '回退失败',
    };
    const sources = {
        manual: '手动操作', retry: '重新运行', cron: '定时执行',
        resource: '资源导入', subscription: '订阅任务', webhook: '推送通知',
        change: '网盘变更', auto_rescan: '系统补扫',
        offline: '离线下载完成', recovery: '恢复任务', import: '导入完成',
        inbox_dispatch: '接收夹分发',
        system: '系统',
    };
    const runKinds = {
        scan: '目录同步', inbox: '接收夹整理', change: '变更同步',
    };
    const runKindChips = {
        inbox: { label: '接收夹整理', tone: 'inbox' },
        scan: { label: '目录同步', tone: 'scan' },
        change: { label: '变更同步', tone: 'change' },
    };
    const ACTIVE_STATUSES = ['queued', 'running', 'waiting'];
    const PROBLEM_STATUSES = ['failed', 'partial', 'pending', 'manual_required', 'rollback_failed'];
    // 结果区最多显示三个关键数字：先“结果”，再“影响面”。
    const KEY_METRICS = [
        ['moved', '成功分发'], ['left', '留在接收夹'], ['generated', '新增本地文件'],
        ['deleted', '删除本地文件'], ['failed_dirs', '失败目录'], ['failed', '失败变更'],
    ];
    const operations = {
        queued: '已加入队列', merged: '已合并请求', started: '开始执行',
        waiting: '等待后续同步', finished: '本次运行结束',
        downstream_finished: '后续同步结束', retry: '重新运行', resettled: '重新结算',
        identified: '识别完成', read_dir: '读取目录', write: '新增播放文件',
        delete: '删除播放文件', sync: '同步播放文件', generate: '新增播放文件',
        rename: '网盘重命名', move: '网盘移动', merge: '网盘合并',
        create: '网盘新增', remote_change: '网盘变更',
        organize: '整理媒体', auto_organize: '整理媒体',
        leave_in_inbox: '保留在接收夹', scan: '扫描目录',
        change: '网盘变更', change_failed: '网盘变更',
        cleanup: '清理残留',
        delegated: '本地播放文件（后续任务生成）',
    };
    const fields = {
        old_name: '原名称', new_name: '新名称', old_path: '原路径', new_path: '新路径',
        original_name: '原文件名', match_source: '识别来源', confidence: '置信度',
        match_reason: '识别理由', tmdb_id: 'TMDB ID', identified_year: '识别年份',
        path: '文件路径', strm_path: '本地播放文件', remote_path: '网盘文件',
        scope: '本次范围', target: '目标目录', task_name: '监控任务', name: '名称',
        reason: '原因', error: '错误说明', detail: '详细说明', summary: '处理结果',
        auto_summary: '自动整理', subjects: '识别结果', source_ref: '来源记录',
        scraper_job_id: '整理任务编号', job_id: '任务编号', generated: '新增或更新',
        deleted: '删除文件', skipped: '跳过文件', failed_dirs: '失败目录',
        succeeded_actions: '成功操作', failed_actions: '失败操作',
        completed: '已完成事件', failed: '失败事件', discarded: '已结束事件',
        manual_required: '等待系统补扫', moved: '已分发', left: '留在接收夹',
        moved_items: '分发明细', left_items: '未处理明细',
        monitor_sync_events: '后续同步事件', children: '后续任务数', paths: '目录',
        cancelled: '已中断', cancelled_before_start: '执行前取消', requested: '请求数量',
    };
    const REMOTE_ACTIONS = {
        organize: '整理', rename: '重命名', move: '移动', merge: '合并',
        create: '新增', delete: '删除', change: '变更', remote_change: '变更',
        auto_organize: '自动整理',
    };
    const STRM_ACTIONS = {
        write: '新增', generate: '新增', delete: '删除', sync: '同步', change: '更新',
    };

    const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
    const count = value => Array.isArray(value) ? value.length : Math.max(0, Number(value) || 0);
    const status = (value, run = {}) => {
        if (value === 'cancelled') return run?.started_at ? '已中断' : '已取消';
        if (value === 'waiting') {
            if (run?.run_kind === 'inbox') return '执行中 · 等待子任务';
            if (run?.run_kind === 'change') return '执行中 · 等待补扫';
        }
        return statuses[value] || '状态待确认';
    };
    const tone = value => ['completed', 'no_change'].includes(value) ? 'success'
        : ['failed', 'rollback_failed'].includes(value) ? 'error'
        : ['partial', 'pending', 'manual_required', 'skipped'].includes(value) ? 'warning'
        : ['queued', 'running', 'waiting'].includes(value) ? 'active' : 'muted';
    const time = value => String(value || '').replace('T', ' ') || '未记录时间';
    const timeOnly = value => {
        const text = time(value);
        const parts = text.split(' ');
        return parts.length > 1 ? parts[1] : text;
    };
    const eventDetail = event => (event?.detail && typeof event.detail === 'object') ? event.detail : {};
    const eventOperation = event => String(event?.operation || '');

    function sourceText(run) {
        const entries = Array.isArray(run?.sources) && run.sources.length
            ? run.sources : [{ source: run?.source || 'system' }];
        return [...new Set(entries.map(item => sources[item?.source] || '其他来源'))].join('、');
    }

    function runKindText(run) {
        const kind = String(run?.run_kind || '').trim();
        if (runKinds[kind]) return runKinds[kind];
        // 兜底：老记录 / 缺字段的下游运行，用来源推断更贴近实际的类型。
        const source = String(run?.source || '').trim();
        if (source === 'inbox_dispatch' || source === 'auto_rescan') return runKinds.scan;
        if (source === 'change') return runKinds.change;
        return '文件夹监控';
    }

    function runKindChip(run) {
        const chip = runKindChips[run?.run_kind];
        if (!chip) return '';
        return `<span class="monitor-run-kind-chip is-${chip.tone}">${escape(chip.label)}</span>`;
    }

    function parentContextText(run) {
        const task = String(run?.parent_task_name || '').trim();
        if (!task) return '';
        const subject = String(run?.parent_subject || '').trim();
        return `来自接收夹整理：${task}${subject ? ` · ${subject}` : ''}`;
    }

    // 变更同步与它委托出去的独立目录同步是同一次分发的前后两阶段：列表把这一对
    // 合并成一行（以目录同步为主体），用副行说明上游那一步做了什么。
    function upstreamText(upstream) {
        const item = upstream && typeof upstream === 'object' ? upstream : {};
        if (!String(item.id || '').trim()) return '';
        const kind = runKindText({ run_kind: item.run_kind, source: item.source }) || '变更同步';
        const conclusion = String(item.summary || '').trim();
        return `上游：${kind}${conclusion ? ` · ${conclusion}` : ''}`;
    }

    function upstreamRow(upstream) {
        const item = upstream && typeof upstream === 'object' ? upstream : {};
        const runId = String(item.id || '').trim();
        if (!runId) return '';
        const kind = runKindText({ run_kind: item.run_kind, source: item.source }) || '变更同步';
        const conclusion = String(item.summary || '').trim() || '已同步网盘变更';
        const rawTime = String(item.finished_at || item.started_at || item.queued_at || '').trim();
        const timeText = rawTime ? timeOnly(rawTime) : '';
        return `<button type="button" class="monitor-run-upstream-row" data-run-id="${escape(runId)}">
            <span class="monitor-run-upstream-kind">上游 · ${escape(kind)}</span>
            <span class="monitor-run-upstream-main">${escape(conclusion)}</span>
            ${timeText ? `<span class="monitor-run-upstream-time">${escape(timeText)}</span>` : ''}
        </button>`;
    }

    function scopeText(scope, snapshot = {}) {
        if (typeof scope === 'string') return scope;
        if (scope?.kind === 'paths') return (scope.paths || []).join('、') || '指定目录';
        if (scope?.kind === 'events') return '本次文件变更涉及的目录';
        if (scope?.kind === 'task') return snapshot.scan_path ? `全部目录：${snapshot.scan_path}` : '全部目录';
        return '';
    }

    function scopeHtml(scope, snapshot = {}) {
        if (scope?.kind === 'paths' && Array.isArray(scope.paths) && scope.paths.length) {
            return `<div class="monitor-run-scope-paths">${scope.paths.map(path => `<div class="monitor-run-scope-path">${escape(path)}</div>`).join('')}</div>`;
        }
        const text = scopeText(scope, snapshot);
        return text ? escape(text) : '';
    }

    function duration(run) {
        const start = Date.parse(String(run?.started_at || '').replace(' ', 'T'));
        const end = Date.parse(String(run?.finished_at || '').replace(' ', 'T'));
        if (!Number.isFinite(start) || !Number.isFinite(end)) return '';
        const seconds = Math.max(0, Math.round((end - start) / 1000));
        return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
    }

    function summary(run) {
        const recorded = String(run?.summary || '').trim();
        if (recorded && /[\u3400-\u9fff]/.test(recorded)) return recorded;
        return {
            queued: '已加入队列，等待开始。', running: '任务正在执行，结果会持续更新。',
            waiting: '本阶段已完成，正在等待后续同步。', completed: '本次任务已完成。',
            no_change: '检查完成，没有需要更新的内容。', partial: '部分内容未完成，请查看下面的记录。',
            failed: '任务未能完成，请查看下面的记录。',
            cancelled: run?.started_at ? '任务已中断，已完成的操作会保留。' : '任务已取消，尚未开始执行。',
        }[run?.status] || '暂未记录执行结果。';
    }

    function metrics(result = {}) {
        return KEY_METRICS
            .filter(([key]) => count(result[key]) > 0)
            .slice(0, 3)
            .map(([key, label]) => ({
                label,
                value: count(result[key]),
                warning: ['left', 'failed_dirs', 'failed'].includes(key),
            }));
    }

    // 早期记录只留下数量（没有逐条问题事件），用它补一句“未完成什么”。
    function derivedIssues(run) {
        if (!['partial', 'failed'].includes(String(run?.status || ''))) return [];
        const result = run?.result || {};
        return [
            ['failed_dirs', '读取失败的目录', '个'],
            ['manual_required', '等待系统补扫', '处'],
            ['left', '仍留在接收夹', '项'],
            ['failed', '处理失败的变更', '条'],
        ].filter(([key]) => count(result[key]) > 0)
            .map(([key, label, unit]) => `${label} ${count(result[key])} ${unit}`);
    }

    function valueHtml(key, value) {
        if (key === 'scope') return scopeHtml(value);
        if (typeof value === 'boolean') return value ? '是' : '否';
        if (Array.isArray(value)) return value.map(item => `<div class="monitor-run-value-item">${valueHtml(key, item)}</div>`).join('');
        if (value && typeof value === 'object') {
            const title = String(value.name || value.path || value.reason || '').trim();
            return escape(title || '已记录详细信息');
        }
        if (['error', 'detail', 'reason', 'summary', 'auto_summary'].includes(key)) {
            const text = String(value || '');
            if (!/[\u3400-\u9fff]/.test(text) && /[a-z]/i.test(text)) {
                const friendly = /timed?\s*out|timeout/i.test(text) ? '请求超时，请检查连接后重试。'
                    : /permission|forbidden|unauthorized/i.test(text) ? '访问被拒绝，请检查授权或目录权限。'
                    : /not found|no such file/i.test(text) ? '未找到目标，请检查文件或目录是否仍然存在。'
                    : '服务返回异常信息，请检查连接或任务配置。';
                return `${escape(friendly)}<details class="monitor-run-diagnostic" open><summary>原始诊断信息</summary><pre>${escape(text)}</pre></details>`;
            }
        }
        return escape(value);
    }

    function detailRows(detail) {
        if (!detail || typeof detail !== 'object') return '';
        return Object.entries(detail).filter(([key, value]) => fields[key]
            && value !== null && value !== undefined && value !== ''
            && !(key === 'path' && detail.strm_path === value)
            && !(['old_name', 'new_name'].includes(key) && detail[key.replace('_name', '_path')])
            && !(Array.isArray(value) && !value.length))
            .map(([key, value]) => `<div class="monitor-run-detail-row"><dt>${escape(fields[key])}</dt><dd>${valueHtml(key, value)}</dd></div>`).join('');
    }

    function badge(value, run) {
        return `<span class="monitor-run-status tone-${tone(value)}">${escape(status(value, run))}</span>`;
    }

    function pathPair(detail) {
        const oldPath = String(detail?.old_path || '').trim();
        const newPath = String(detail?.new_path || '').trim();
        if (oldPath && newPath && oldPath !== newPath) return `${oldPath} → ${newPath}`;
        return newPath || oldPath;
    }

    function fileName(event) {
        const detail = eventDetail(event);
        const raw = String(detail.strm_path || detail.path || event?.title || '').trim();
        return raw.replace(/\\/g, '/').split('/').pop() || raw;
    }

    function isProblemEvent(event) {
        const category = String(event?.category || '');
        if (category === 'problem') return true;
        return ['remote', 'strm'].includes(category) && PROBLEM_STATUSES.includes(String(event?.status || ''));
    }

    function isFileEvent(event) {
        return String(event?.category || '') === 'strm';
    }

    function childItemsOf(run, detail) {
        const descendants = Array.isArray(detail?.descendants) ? detail.descendants : [];
        if (descendants.length) return descendants;
        return Array.isArray(detail?.children) ? detail.children : [];
    }

    function runKindKey(run) {
        const kind = String(run?.run_kind || '').trim();
        if (runKinds[kind]) return kind;
        // 老记录缺 run_kind 时按来源推断，保证页签与任务类型匹配。
        const source = String(run?.source || '').trim();
        if (source === 'inbox_dispatch' || source === 'auto_rescan') return 'scan';
        if (source === 'change') return 'change';
        return '';
    }

    // 页签按任务类型匹配：接收夹整理没有本地文件，目录同步没有网盘操作（自动整理除外）。
    function tabDefsFor(run, counts = {}) {
        const kind = runKindKey(run);
        const hasRemote = count(counts.remote) > 0;
        const hasStrm = count(counts.strm) > 0;
        const tabs = [['', '概览', '']];
        const showRemote = kind === 'inbox' || kind === 'change' || (kind === '' && hasRemote) || (kind === 'scan' && hasRemote);
        if (showRemote) tabs.push(['remote', '网盘变更', 'remote']);
        if (kind === 'scan' || kind === 'change' || (kind === '' && hasStrm)) {
            tabs.push(['strm', '本地文件', 'strm']);
        }
        tabs.push(['problem', '问题', 'problem']);
        return tabs;
    }

    function resolveTab(detail, active) {
        const tabs = tabDefsFor(detail?.run || {}, detail?.counts || {});
        const wanted = String(active || '');
        return tabs.some(([key]) => key === wanted) ? wanted : '';
    }

    function tabsHtml(detail, active) {
        const run = detail?.run || {};
        const counts = detail?.counts || {};
        const tabs = tabDefsFor(run, counts);
        const current = resolveTab(detail, active);
        return tabs.map(([key, label, countKey]) => {
            const total = countKey ? count(counts[countKey]) : null;
            const isActive = current === key;
            return `<button type="button" role="tab" aria-selected="${isActive ? 'true' : 'false'}" class="monitor-run-tab${isActive ? ' is-active' : ''}" data-monitor-run-tab="${key}" onclick="setMonitorRunTab('${key}')">${escape(label)}${total === null ? '' : ` <span class="monitor-run-tab-count">${total}</span>`}</button>`;
        }).join('');
    }

    function stepsHtml(steps) {
        if (!steps.length) return '';
        const icons = { done: '✓', current: '●', todo: '○', stopped: '✕' };
        return `<ol class="monitor-run-steps">${steps.map((step, index) => `
            <li class="monitor-run-step is-${step.state}">
                <span class="monitor-run-step-dot" aria-hidden="true">${icons[step.state] || '○'}</span>
                <span class="monitor-run-step-body">
                    <span class="monitor-run-step-name">${escape(step.name)}</span>
                    ${step.note ? `<span class="monitor-run-step-note">${escape(step.note)}</span>` : ''}
                </span>
            </li>${index < steps.length - 1 ? '<li class="monitor-run-step-arrow" aria-hidden="true">→</li>' : ''}`).join('')}</ol>`;
    }

    // 接收夹整理只覆盖「识别 → 整理移动」两步；STRM 生成属于独立的目录同步任务。
    function inboxSteps(run, events) {
        if (String(run?.run_kind || '') !== 'inbox') return [];
        const result = run?.result || {};
        const moved = count(result.moved);
        const left = count(result.left);
        const state = String(run?.status || '');
        const identified = (Array.isArray(events) ? events : []).some(
            event => String(event?.category || '') === 'process' && eventOperation(event) === 'identified'
        ) || Boolean(String(run?.subject || '').trim() && String(run.subject) !== '识别中');
        const active = ACTIVE_STATUSES.includes(state);
        const interrupted = ['cancelled', 'failed'].includes(state);
        const first = identified ? 'done' : (state === 'queued' ? 'todo' : (interrupted ? 'stopped' : 'current'));
        let second = 'todo';
        if (['waiting', 'completed', 'no_change'].includes(state)) second = 'done';
        else if (state === 'partial') second = moved > 0 ? 'done' : 'stopped';
        else if (interrupted) second = 'stopped';
        else if (active && identified) second = 'current';
        const dispatchNote = moved || left
            ? `分发 ${moved} 项${left ? ` · 留在接收夹 ${left} 项` : ''}`
            : (['completed', 'no_change', 'partial'].includes(state) ? '没有需要分发的条目' : '移动到电影 / 电视剧目录');
        return [
            {
                name: '识别', state: first,
                note: identified ? '已识别影视内容' : (state === 'queued' ? '排队中' : '识别接收夹内容'),
            },
            { name: '整理移动', state: second, note: dispatchNote },
        ];
    }

    function loadMoreLine(detail, loaded, total) {
        const more = detail?.has_more
            ? '<button type="button" class="monitor-run-load-more log-header-btn" onclick="loadMoreMonitorRunEvents()">加载更多</button>'
            : '';
        return `<div class="monitor-run-shown">已显示 ${loaded} / 共 ${total} 条${more ? ` ${more}` : ''}</div>`;
    }

    function emptyBlock(text) {
        return `<div class="monitor-run-empty">${escape(text)}</div>`;
    }

    function eventRow({ action, main, extra = '', timeText = '', tone: rowTone = '', id = '' }) {
        return `<div class="monitor-run-event-row${rowTone ? ` is-${rowTone}` : ''}"${id ? ` data-run-id="${escape(id)}"` : ''}>
            <span class="monitor-run-event-action">${escape(action)}</span>
            <span class="monitor-run-event-body">
                <span class="monitor-run-event-main">${escape(main)}</span>
                ${extra ? `<span class="monitor-run-event-extra">${extra}</span>` : ''}
            </span>
            ${timeText ? `<time class="monitor-run-event-time">${escape(timeText)}</time>` : ''}
        </div>`;
    }

    // 明细字段（原位置 / 名称、新位置 / 名称、网盘 / 本地路径）统一按“标签 + 值”渲染。
    function eventFields(pairs) {
        const rows = (Array.isArray(pairs) ? pairs : []).filter(([, value]) => String(value ?? '').trim());
        if (!rows.length) return '';
        return `<dl class="monitor-run-event-fields">${rows.map(([label, value]) => `<div class="monitor-run-field"><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>`;
    }

    function baseName(path) {
        const text = String(path || '').trim().replace(/\\/g, '/');
        return text.split('/').pop() || text;
    }

    function remoteRow(event) {
        const detail = eventDetail(event);
        const operation = eventOperation(event);
        const action = REMOTE_ACTIONS[operation] || String(detail.operation_label || '').replace(/^网盘/, '') || '网盘变更';
        const main = String(detail.new_name || '').trim()
            || baseName(detail.new_path)
            || String(event?.title || '').trim()
            || '已记录网盘变更';
        const confidence = count(detail.confidence);
        const fields = eventFields([
            ['原位置', detail.old_path],
            ['原名称', detail.original_name || detail.old_name],
            ['新位置', detail.new_path],
            ['新名称', detail.new_name],
            ['识别来源', detail.match_source],
            ['置信度', confidence ? `${confidence}` : ''],
            ['删除本地文件', count(detail.deleted) ? `${count(detail.deleted)} 个` : ''],
            ['生成本地文件', count(detail.generated) ? `${count(detail.generated)} 个` : ''],
            ['成功动作', count(detail.succeeded_actions) ? `${count(detail.succeeded_actions)} 个` : ''],
        ]);
        return eventRow({
            action, main, extra: fields,
            timeText: timeOnly(event?.created_at),
            tone: PROBLEM_STATUSES.includes(String(event?.status || '')) ? 'problem' : '',
        });
    }

    function strmRow(event) {
        const detail = eventDetail(event);
        const operation = eventOperation(event);
        const action = STRM_ACTIONS[operation] || '处理';
        if (operation === 'sync') {
            const scope = String(detail.scope || '').trim();
            const title = String(event?.title || '').trim();
            const bits = [];
            if (count(detail.generated)) bits.push(`新增或更新 ${count(detail.generated)} 个`);
            if (count(detail.deleted)) bits.push(`删除 ${count(detail.deleted)} 个`);
            const main = title && title !== 'STRM 同步' ? title : (scope || title || '本地播放文件同步');
            const extras = [];
            if (main !== scope && scope) extras.push(scope);
            if (bits.length) extras.push(bits.join(' · '));
            return eventRow({
                action,
                main,
                extra: escape(extras.join(' · ')),
                timeText: timeOnly(event?.created_at),
            });
        }
        // 目录扫描的事件直接带本地 / 网盘路径；变更同步的文件级事件用 new_path / old_path
        // 表示本地 STRM 路径，用 new_remote_path / old_remote_path 表示网盘路径。
        const fullPath = String(
            detail.strm_path || detail.path || detail.new_path || detail.old_path || ''
        ).trim();
        const remotePath = String(
            detail.remote_path || detail.new_remote_path || detail.old_remote_path || ''
        ).trim();
        const fields = eventFields([
            ['网盘位置', remotePath],
            ['网盘名称', baseName(remotePath)],
            ['本地位置', fullPath],
            ['本地名称', baseName(fullPath)],
        ]);
        return eventRow({
            action,
            main: fileName(event),
            extra: fields,
            timeText: timeOnly(event?.created_at),
            tone: PROBLEM_STATUSES.includes(String(event?.status || '')) ? 'problem' : '',
        });
    }

    function problemRow(event) {
        const detail = eventDetail(event);
        const operation = eventOperation(event);
        const action = operations[operation] || (String(event?.category || '') === 'problem' ? '问题' : '网盘变更');
        const main = String(event?.title || '').trim() || action;
        const raw = String(detail.reason || detail.error || detail.detail || detail.summary || '').trim();
        return eventRow({
            action,
            main,
            extra: raw ? `<span class="monitor-run-event-reason">${valueHtml('error', raw)}</span>` : '',
            timeText: timeOnly(event?.created_at),
            tone: 'problem',
        });
    }

    function remoteSection(title, events) {
        if (!events.length) return '';
        return `<div class="monitor-run-subsection">${escape(title)}</div>${events.map(remoteRow).join('')}`;
    }

    function remoteHtml(run, events, detail) {
        const kind = String(run?.run_kind || '');
        const remoteEvents = (Array.isArray(events) ? events : []).filter(
            event => String(event?.category || '') === 'remote'
        );
        const total = count(detail?.counts?.remote ?? remoteEvents.length);
        if (!remoteEvents.length) return emptyBlock('本次运行没有网盘变更。');
        let body = '';
        if (kind === 'inbox') {
            const organize = remoteEvents.filter(event => ['organize', 'rename'].includes(eventOperation(event)));
            const dispatch = remoteEvents.filter(event => !['organize', 'rename'].includes(eventOperation(event)));
            body = remoteSection('整理重命名', organize) + remoteSection('移动到监控文件夹', dispatch);
        } else if (kind === 'scan') {
            body = remoteSection('自动整理', remoteEvents);
        } else {
            body = remoteSection('网盘变更', remoteEvents);
        }
        return `${body}${loadMoreLine(detail, remoteEvents.length, total)}`;
    }

    function delegatedNote(run, events) {
        const delegated = (Array.isArray(events) ? events : []).find(
            event => String(event?.category || '') === 'process' && eventOperation(event) === 'delegated'
        );
        if (!delegated) return '';
        const detail = eventDetail(delegated);
        const waiting = count(detail.children);
        const independent = count(detail.independent_children);
        if (waiting) return `本地播放文件由后续自动补扫生成：等待 ${waiting} 个目录补扫完成（见「概览」的结论）。`;
        if (independent) return `本次运行没有直接生成本地播放文件；由 ${independent} 项独立的目录同步任务生成，各自留有单独记录。`;
        return '';
    }

    function strmHtml(run, events, detail) {
        const kind = String(run?.run_kind || '');
        const strmEvents = (Array.isArray(events) ? events : []).filter(isFileEvent);
        const total = count(detail?.counts?.strm ?? strmEvents.length);
        if (!strmEvents.length) {
            if (kind === 'inbox') {
                return emptyBlock('接收夹整理只负责识别与移动，本地播放文件由独立的目录同步任务生成。');
            }
            return emptyBlock(delegatedNote(run, events) || '本次运行没有本地文件变更。');
        }
        return `${strmEvents.map(strmRow).join('')}${loadMoreLine(detail, strmEvents.length, total)}`;
    }

    function problemHtml(run, events, detail) {
        const derived = derivedIssues(run);
        const problemEvents = (Array.isArray(events) ? events : []).filter(isProblemEvent);
        const total = count(detail?.counts?.problem ?? problemEvents.length);
        if (!derived.length && !problemEvents.length) return emptyBlock('本次运行没有问题。');
        const derivedLine = derived.length
            ? `<p class="monitor-run-derived-line tone-warning">未完成内容：${escape(derived.join('；'))}</p>`
            : '';
        return `${derivedLine}${problemEvents.map(problemRow).join('')}${problemEvents.length ? loadMoreLine(detail, problemEvents.length, total) : ''}`;
    }

    function legacyChildren(run, detail) {
        if (String(run?.run_kind || '') !== 'inbox') return '';
        const children = childItemsOf(run, detail);
        if (!children.length) return '';
        return `<div class="monitor-run-subsection">后续任务（历史记录）</div>${children.map(child => eventRow({
            action: runKindText(child),
            main: String(child?.subject || child?.task_name || '后续任务'),
            extra: escape(status(child?.status, child)),
            timeText: timeOnly(child?.queued_at || child?.started_at || ''),
            id: child?.id,
        })).join('')}`;
    }

    function inboxItemsHtml(run, detail) {
        if (String(run?.run_kind || '') !== 'inbox') return '';
        const items = Array.isArray(detail?.inbox_items) ? detail.inbox_items : [];
        if (!items.length) return '';
        const rows = items.map(item => {
            const original = String(item?.original_name || '').trim();
            const organized = String(item?.new_name || '').trim();
            const source = String(item?.match_source || '').trim();
            const confidence = count(item?.confidence);
            const meta = [source, confidence ? `${confidence}` : ''].filter(Boolean).join(' · ');
            return `<div class="monitor-run-inbox-pair">
                <span class="monitor-run-inbox-original">${escape(original)}</span>
                <span class="monitor-run-inbox-arrow" aria-hidden="true">→</span>
                <span class="monitor-run-inbox-organized">${escape(organized)}</span>
                ${meta ? `<span class="monitor-run-inbox-meta">${escape(meta)}</span>` : ''}
            </div>`;
        }).join('');
        return `<div class="monitor-run-subsection">已整理条目</div><div class="monitor-run-inbox-pairs">${rows}</div>`;
    }

    function overviewHtml(run, detail, events) {
        const stats = metrics(run?.result);
        const derived = derivedIssues(run);
        const scope = scopeHtml(run?.scope, run?.task_snapshot);
        const used = duration(run);
        const metaItems = [
            used ? `用时 ${used}` : '',
            `触发：${sourceText(run)}`,
            parentContextText(run),
        ].filter(Boolean).join(' · ');
        const meta = [
            scope ? `<span class="monitor-run-scope-label">范围：</span>${scope}` : '',
            metaItems ? `<span class="monitor-run-meta-items">${escape(metaItems)}</span>` : '',
        ].filter(Boolean).join('');
        const retry = ['failed', 'partial'].includes(String(run?.status || '')) && run?.run_kind === 'scan';
        const cancel = String(run?.status || '') === 'queued' && run?.run_kind !== 'inbox';
        return `${stepsHtml(inboxSteps(run, events))}
            ${inboxItemsHtml(run, detail)}
            <section class="monitor-run-simple">
                <div class="monitor-run-outcome"><h4>运行结果</h4><span class="monitor-run-outcome-tags">${runKindChip(run)}${badge(run?.status, run)}</span></div>
                <p class="monitor-run-simple-summary">${escape(summary(run))}</p>
                ${derived.length ? `<p class="monitor-run-derived-line tone-warning">未完成内容：${escape(derived.join('；'))}</p>` : ''}
                ${stats.length ? `<dl class="monitor-run-simple-metrics">${stats.map(item => `<div${item.warning ? ' class="tone-warning"' : ''}><dt>${escape(item.label)}</dt><dd>${item.value}</dd></div>`).join('')}</dl>` : ''}
                ${meta ? `<div class="monitor-run-simple-meta">${meta}</div>` : ''}
                ${upstreamRow(detail?.upstream_change)}
                ${legacyChildren(run, detail)}
                ${retry || cancel ? `<div class="monitor-run-detail-actions">${retry ? '<button type="button" class="monitor-run-detail-action" onclick="retryMonitorRun()">按原范围重新运行</button>' : ''}${cancel ? '<button type="button" class="monitor-run-detail-action is-cancel" onclick="cancelMonitorRun()">取消排队</button>' : ''}</div>` : ''}
            </section>`;
    }

    // 详情按当前页签渲染：四个页签互斥，计数取 counts，事件按快照分页。
    function detailHtml(detail, category) {
        const run = detail?.run || {};
        const events = Array.isArray(detail?.events) ? detail.events : [];
        // 切到当前运行不适用的页签（例如接收夹的历史本地文件页签）时回到概览。
        const active = resolveTab(detail, category);
        const stale = detail?.stale
            ? '<button type="button" class="monitor-run-new-records" onclick="reloadMonitorRunDetail()">有新记录，点击刷新</button>'
            : '';
        let body = '';
        if (active === 'remote') body = remoteHtml(run, events, detail);
        else if (active === 'strm') body = strmHtml(run, events, detail);
        else if (active === 'problem') body = problemHtml(run, events, detail);
        else body = overviewHtml(run, detail, events);
        return `${stale}<div class="monitor-run-tab-panel" role="tabpanel">${body}</div>`;
    }

    // 列表第一眼只保留：任务/对象名、状态、一句结论和类型标签。
    function listRow(run) {
        const runId = String(run?.id || '');
        const upstream = upstreamText(run?.upstream_change);
        return `<div class="monitor-run-group" data-run-group="${escape(runId)}">
            <button type="button" class="monitor-run-row" data-run-id="${escape(runId)}">
                <span class="monitor-run-main"><span class="monitor-run-title">${escape(run?.task_name || '文件夹监控')} <i>·</i> ${escape(run?.subject || '全部目录')}</span>
                <span class="monitor-run-result">${escape(summary(run))}</span>
                ${upstream ? `<span class="monitor-run-upstream">${escape(upstream)}</span>` : ''}</span>
                <span class="monitor-run-side">${runKindChip(run)}${badge(run?.status, run)}<span class="monitor-run-open">查看详情</span></span>
            </button>
        </div>`;
    }

    global.MonitorRunView = {
        statuses, sources, runKinds, escape, count, status, tone, time, sourceText, runKindText, runKindKey,
        parentContextText, upstreamText, upstreamRow, scopeText, scopeHtml, duration, summary, metrics, derivedIssues, isProblemEvent,
        tabDefsFor, resolveTab, tabsHtml, detailHtml, listRow, valueHtml, detailRows,
    };
})(window);
