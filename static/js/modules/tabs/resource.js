export async function ensureTabData(context) {
    context.moduleVisitState.resource = true;
    if (!context.isResourceStateHydrated()) {
        await context.refreshResourceState();
    }
}
