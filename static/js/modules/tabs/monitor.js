export async function ensureTabData(context) {
    if (!context.moduleVisitState.monitor) {
        await context.refreshMonitorState();
        context.moduleVisitState.monitor = true;
    }
}
