export async function ensureTabData(context) {
    if (!context.moduleVisitState.subscription) {
        await context.refreshSubscriptionState();
        context.moduleVisitState.subscription = true;
    }
}
