(function (global) {
    async function triggerRefresh(ctx, jobId) {
        const res = await fetch('/resource/jobs/refresh', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ job_id: jobId })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) return alert(`❌ ${data.msg || '触发刷新失败'}`);
        await ctx.refreshResourceState();
        alert('✅ 已触发文件夹监控任务');
    }

    async function triggerCancel(ctx, jobId) {
        if (!confirm('确定要取消这个导入任务吗？')) return;
        const res = await fetch('/resource/jobs/cancel', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ job_id: jobId })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
            ctx.showToast(`取消失败：${data.msg || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            return;
        }
        await ctx.refreshResourceState();
        ctx.showToast(`任务 #${jobId} 已取消`, { tone: 'success', duration: 2600, placement: 'top-center' });
    }

    async function triggerRetry(ctx, jobId) {
        const res = await fetch('/resource/jobs/retry', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ job_id: jobId })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
            ctx.showToast(`重试失败：${data.msg || '请稍后重试'}`, { tone: 'error', duration: 3200, placement: 'top-center' });
            return;
        }
        await ctx.refreshResourceState();
        ctx.showToast(`已创建重试任务 #${Number(data.job_id || 0) || '--'}`, { tone: 'success', duration: 2800, placement: 'top-center' });
    }

    global.ResourceJobActions = {
        triggerRefresh,
        triggerCancel,
        triggerRetry,
    };
})(window);
