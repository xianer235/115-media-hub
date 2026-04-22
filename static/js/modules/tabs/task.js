export async function ensureTabData(context) {
    if (!context.moduleVisitState.task) {
        await context.refreshMainLogs();
        context.moduleVisitState.task = true;
    }
}
