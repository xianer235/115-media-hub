(function (global) {
    'use strict';

    const statuses = {
        queued: '排队中', running: '执行中', waiting: '等待后续同步',
        completed: '已完成', no_change: '无变化', partial: '部分完成',
        failed: '失败', cancelled: '已中断', pending: '等待处理', skipped: '未处理',
        manual_required: '等待补扫', rollback_failed: '回退失败',
    };
    const sources = {
        manual: '手动触发', retry: '重新运行', cron: '定时触发',
        resource: '资源导入', subscription: '订阅任务', webhook: '外部通知',
        change: '检测到网盘变更', auto_rescan: '系统补扫',
        offline: '离线下载完成', recovery: '恢复任务', import: '资源导入',
        inbox_dispatch: '接收夹分发',
        system: '系统触发',
    };
    const runKinds = {
        scan: '目录扫描与 STRM', inbox: '接收夹整理与分发', change: '增量变更同步',
    };
    const operations = {
        queued: '已加入队列', merged: '已合并请求', started: '开始执行',
        waiting: '等待后续同步', finished: '本次运行结束',
        downstream_finished: '后续同步结束', retry: '重新运行', resettled: '重新结算',
        identified: '识别完成', read_dir: '检查目录', write: '写入本地播放文件',
        delete: '删除本地播放文件', sync: '同步本地播放文件',
        rename: '网盘重命名', move: '网盘移动', merge: '网盘合并',
        create: '网盘新增', remote_change: '检测到网盘变更',
        organize: '整理媒体', auto_organize: '自动整理',
        leave_in_inbox: '保留在接收夹', scan: '扫描任务', change: '文件变更同步',
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
        manual_required: '待补扫事件', moved: '已分发', left: '留在接收夹',
        moved_items: '分发明细', left_items: '未处理明细',
        monitor_sync_events: '后续同步事件', children: '后续任务数', paths: '目录',
        cancelled: '已中断', cancelled_before_start: '执行前取消', requested: '请求数量',
    };

    const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
    const count = value => Array.isArray(value) ? value.length : Math.max(0, Number(value) || 0);
    const status = (value, run = {}) => {
        if (value === 'cancelled') return run?.started_at ? '已中断' : '已取消';
        return statuses[value] || '状态待确认';
    };
    const tone = value => ['completed', 'no_change'].includes(value) ? 'success'
        : ['failed', 'rollback_failed'].includes(value) ? 'error'
        : ['partial', 'pending', 'manual_required', 'skipped'].includes(value) ? 'warning'
        : ['queued', 'running', 'waiting'].includes(value) ? 'active' : 'muted';
    const time = value => String(value || '').replace('T', ' ') || '未记录时间';

    function sourceText(run) {
        const entries = Array.isArray(run?.sources) && run.sources.length
            ? run.sources : [{source: run?.source || 'system'}];
        return [...new Set(entries.map(item => sources[item?.source] || '其他来源'))].join('、');
    }

    function runKindText(run) {
        return runKinds[run?.run_kind] || '文件夹监控';
    }

    function parentContextText(run) {
        const task = String(run?.parent_task_name || '').trim();
        if (!task) return '';
        const subject = String(run?.parent_subject || '').trim();
        return `来自接收夹整理：${task}${subject ? ` · ${subject}` : ''}`;
    }

    function scopeText(scope, snapshot = {}) {
        if (typeof scope === 'string') return scope;
        if (scope?.kind === 'paths') return (scope.paths || []).join('、') || '指定目录';
        if (scope?.kind === 'events') return '本次文件变更涉及的目录';
        if (scope?.kind === 'task') return snapshot.scan_path ? `全部目录：${snapshot.scan_path}` : '全部目录';
        return '未记录具体范围';
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
            no_change: '检查完成，没有需要更新的内容。', partial: '部分内容未完成，请查看问题明细。',
            failed: '任务未能完成，请查看问题明细。',
            cancelled: run?.started_at ? '任务已中断，已完成的操作会保留。' : '任务已取消，尚未开始执行。',
        }[run?.status] || '暂未记录执行结果。';
    }

    function metrics(result = {}) {
        return [
            ['generated', '新增或更新'], ['deleted', '删除文件'], ['moved', '已分发'],
            ['left', '未处理'], ['failed_dirs', '失败目录'], ['failed', '失败事件'],
        ].filter(([key]) => count(result[key]) > 0).map(([key, label]) => ({
            label, value: count(result[key]), warning: ['left', 'failed_dirs', 'failed'].includes(key),
        }));
    }

    // 早期记录只留下数量（没有逐条问题事件），这里把结果字段翻译成同样的“需要处理”提示，
    // 免得界面显示“部分完成 / 失败”却告出“没有任何问题”。
    function derivedIssues(run) {
        if (!['partial', 'failed'].includes(String(run?.status || ''))) return [];
        const result = run?.result || {};
        return [
            ['failed_dirs', '读取失败的目录', '个'],
            ['manual_required', '需要手动监控', '处'],
            ['left', '仍留在接收夹', '项'],
            ['failed', '处理失败的变更', '条'],
        ].filter(([key]) => count(result[key]) > 0)
            .map(([key, label, unit]) => ({ label, value: `${count(result[key])} ${unit}` }));
    }

    function derivedIssueBlock(run) {
        const items = derivedIssues(run);
        if (!items.length) return '';
        return `<div class="monitor-run-derived-issues">
            <p>这次运行没有完整结束。以下数量来自运行结果，记录里没有对应的逐条明细：</p>
            <dl class="monitor-run-detail-grid">${items.map(item => `<div class="monitor-run-detail-row"><dt>${escape(item.label)}</dt><dd>${escape(item.value)}</dd></div>`).join('')}</dl>
            <p>建议按原范围重新运行，或在任务卡片上查看“需补扫 / 需手动监控”提示后再处理。</p></div>`;
    }

    // 标签上的数字要能对上页面内容：问题标签在没有逐条问题事件、但有未完成数量时，
    // 也必须显示这些条目，而不是永远显示 0。
    function tabCount(detail, category) {
        const key = category || 'process';
        const recorded = count((detail?.counts || {})[key]);
        if (key !== 'problem') return recorded;
        return Math.max(recorded, derivedIssues(detail?.run || {}).length);
    }

    function valueHtml(key, value) {
        if (key === 'scope') return escape(scopeText(value));
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

    function eventCard(event, index) {
        const operation = String(event?.operation || '');
        const isProcess = event?.category === 'process';
        let label = status(event?.status);
        let stateTone = tone(event?.status);
        if (isProcess && ['queued', 'merged', 'started', 'waiting'].includes(operation)) {
            label = {queued: '已入队', merged: '已合并', started: '已开始', waiting: '已进入等待'}[operation];
            stateTone = 'muted';
        }
        const title = operations[operation] || (isProcess ? '执行记录' : '处理文件');
        const name = !isProcess ? String(event?.title || '') : '';
        const rows = detailRows(event?.detail);
        return `<article class="monitor-run-step tone-${stateTone}">
            <span class="monitor-run-step-index" aria-hidden="true">${index + 1}</span>
            <div class="monitor-run-step-content"><div class="monitor-run-step-head">
                <strong>${escape(title)}</strong><span class="monitor-run-step-state">${escape(label)}</span>
                <time>${escape(time(event?.created_at))}</time></div>
                ${name ? `<div class="monitor-run-event-name">${escape(name)}</div>` : ''}
                ${rows ? `<details class="monitor-run-event-details" open><summary>查看明细</summary><dl class="monitor-run-detail-grid">${rows}</dl></details>` : ''}
            </div></article>`;
    }

    function listRow(run) {
        const stats = metrics(run?.result);
        const parentContext = parentContextText(run);
        return `<button type="button" class="monitor-run-row" data-run-id="${escape(run?.id)}">
            <span class="monitor-run-main"><span class="monitor-run-title">${escape(run?.task_name || '文件夹监控')} <i>·</i> ${escape(run?.subject || '全部目录')}</span>
            <span class="monitor-run-meta">流程：${escape(runKindText(run))} · 启动：${escape(sourceText(run))} · ${escape(time(run?.queued_at || run?.started_at))}${duration(run) ? ` · 用时 ${escape(duration(run))}` : ''}</span>
            ${parentContext ? `<span class="monitor-run-meta">${escape(parentContext)}</span>` : ''}
            <span class="monitor-run-result">${escape(summary(run))}</span>
            ${stats.length ? `<span class="monitor-run-inline-metrics">${stats.map(item => `<span${item.warning ? ' class="tone-warning"' : ''}>${item.label} <b>${item.value}</b></span>`).join('')}</span>` : ''}
            </span><span class="monitor-run-side">${badge(run?.status, run)}<span class="monitor-run-open">查看详情</span>
            ${count(run?.child_count) ? `<span class="monitor-run-child-count">后续 ${count(run.child_count)} 项</span>` : ''}</span></button>`;
    }

    function relations(items, title) {
        if (!items?.length) return '';
        return `<section class="monitor-run-detail-section"><h4>${title}</h4>${items.map(item => `<button type="button" class="monitor-run-child" data-run-id="${escape(item.id)}"><span>${escape(item.task_name || '监控')} · ${escape(item.subject || '全部目录')}</span>${badge(item.status)}<span aria-hidden="true">查看</span></button>`).join('')}</section>`;
    }

    // 详情里的下游带层级（增量变更同步 → 自动补扫），缩进显示整条链路。
    function descendantRelations(items, title) {
        if (!items?.length) return '';
        return `<section class="monitor-run-detail-section"><h4>${title}</h4>${items.map(item => {
            const depth = Math.max(1, Math.min(4, Number(item?.depth || 1) || 1));
            return `<button type="button" class="monitor-run-child${depth > 1 ? ' is-nested' : ''}" style="--run-depth:${depth}" data-run-id="${escape(item.id)}"><span>${escape(item.task_name || '监控')} · ${escape(item.subject || '全部目录')}</span>${badge(item.status)}<span aria-hidden="true">查看</span></button>`;
        }).join('')}</section>`;
    }

    function detailHtml(detail, category) {
        const run = detail?.run || {};
        const events = detail?.events || [];
        const counts = detail?.counts || {};
        const stats = metrics(run.result);
        const retry = ['failed', 'partial'].includes(run.status) && run.run_kind === 'scan';
        const cancel = run.status === 'queued' && run.run_kind !== 'inbox';
        const overview = !category || category === 'process';
        const problemCount = count(counts.problem);
        const derived = derivedIssues(run);
        const derivedOnly = category === 'problem' && !events.length && derived.length > 0;
        const title = ({remote: '网盘操作', strm: '本地播放文件', problem: '需要处理的问题'})[category] || '执行过程';
        return `<section class="monitor-run-detail-summary">
            <div class="monitor-run-outcome"><h4>运行结果</h4>${badge(run.status, run)}</div>
            <p>${escape(summary(run))}</p>
            ${stats.length ? `<dl class="monitor-run-metrics">${stats.map(item => `<div${item.warning ? ' class="tone-warning"' : ''}><dt>${item.label}</dt><dd>${item.value}<small> 项</small></dd></div>`).join('')}</dl>` : ''}
            <dl class="monitor-run-context"><div><dt>本次范围</dt><dd>${escape(scopeText(run.scope, run.task_snapshot))}</dd></div>
            ${duration(run) ? `<div><dt>执行用时</dt><dd>${escape(duration(run))}</dd></div>` : ''}</dl>
            ${retry || cancel ? `<div class="monitor-run-detail-actions">${retry ? '<button type="button" class="monitor-run-detail-action" onclick="retryMonitorRun()">按原范围重新运行</button><span class="monitor-run-action-note">会重新检查本次记录中的全部范围。</span>' : ''}${cancel ? '<button type="button" class="monitor-run-detail-action is-cancel" onclick="cancelMonitorRun()">取消排队</button>' : ''}</div>` : ''}
        </section>
        ${overview && (problemCount || derived.length) ? `<button class="monitor-run-problem-link" type="button" onclick="switchMonitorRunDetail('problem')">${problemCount ? `${problemCount} 条问题记录` : `${derived.length} 项未完成内容`}，查看原因与影响 <span aria-hidden="true">查看</span></button>` : ''}
        ${overview ? (detail.descendants?.length ? descendantRelations(detail.descendants, '后续同步') : relations(detail.children, '后续同步')) + relations(detail.parents, '来源运行') + relations(detail.related, '原运行记录') : ''}
        <section class="monitor-run-detail-section"><div class="monitor-run-section-head"><h4>${title}</h4><span>${derivedOnly ? '来自运行结果' : `已显示 ${events.length} / ${count(detail.total ?? events.length)} 条`}</span></div>
        ${events.length ? `<div class="monitor-run-timeline">${events.map((event, index) => eventCard(event, index)).join('')}</div>` : (category === 'problem' ? (derived.length ? derivedIssueBlock(run) : '<div class="monitor-run-empty">暂无问题记录。</div>') : '<div class="monitor-run-empty">本次运行尚未记录此类操作。</div>')}
        ${detail.has_more ? '<button type="button" class="monitor-run-load-more log-header-btn" onclick="loadMoreMonitorRunEvents()">加载更多记录</button>' : ''}</section>`;
    }

    global.MonitorRunView = {
        statuses, sources, runKinds, escape, count, status, tone, time, sourceText, runKindText, parentContextText, scopeText,
        duration, summary, metrics, detailRows, eventCard, listRow, detailHtml, derivedIssues, tabCount,
    };
})(window);
