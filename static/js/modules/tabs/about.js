export async function ensureTabData(context) {
    if (!context.versionInfo?.checked_at) {
        await context.refreshVersionInfo(false);
    }
    context.moduleVisitState.about = true;
}
