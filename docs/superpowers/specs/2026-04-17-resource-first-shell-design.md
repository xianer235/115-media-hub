# Resource-First Shell Design

Date: 2026-04-17
Project: 115 Media Hub
Status: Approved for planning

## Summary

This redesign removes the separate dashboard-style homepage and turns the application into a resource-first workspace. After login, users land directly in resource exploration. The application keeps one shared information architecture across desktop and mobile, but uses different layout variants per device. Desktop favors a left navigation shell and wide content stream. Mobile favors a top tool bar and bottom five-item navigation. Both variants keep resource exploration as the primary workspace, surface quick links on the first screen, and move global tools into a stable shell instead of mixing them into the resource content area.

The visual direction is controlled liquid glass. The shell uses glass layers, soft highlights, and restrained translucency. The resource result area stays more solid and readable than the shell so content remains the visual priority. Performance and maintainability are first-class requirements. The redesign must reduce first-load work, split the current monolithic frontend into shell and module boundaries, and avoid expensive glass effects on content-heavy lists.

## Goals

1. Make resource exploration the default and dominant workflow after login.
2. Keep search and sync always available without letting the control area dominate the screen.
3. Preserve quick link access and quick link management as fixed first-screen tools.
4. Keep subscription, monitor, tree, and settings as independent module pages.
5. Separate shell-level concerns from module-level rendering and state.
6. Improve first-load performance by only initializing shell and resource exploration on login.
7. Introduce a liquid glass visual language without reducing readability or scroll performance.

## Non-Goals

1. Do not build a new analytics-heavy homepage or command dashboard.
2. Do not merge subscription, monitor, tree, and settings into the resource page workflow.
3. Do not create separate desktop and mobile products with different navigation semantics.
4. Do not rely on heavy blur, heavy shadows, or full-screen glass layers for the main content stream.
5. Do not redesign backend APIs in this phase unless needed to support shell summaries or lazy module loading.

## Confirmed Product Decisions

### Primary landing behavior

- After login, the application always opens resource exploration.
- The application no longer treats a separate homepage as the main landing page.

### Resource page hierarchy

- The top of the resource page is a thin search and sync strip.
- Quick links and quick link management are fixed, visible, and first-screen.
- Most visible space is reserved for the resource result board.
- The default resource board is grouped by channel or source and behaves like a browsable content stream.
- Search results appear only after a user executes search and temporarily replace the default grouped stream.

### Module structure

- Subscription, monitor, tree, and settings remain independent module pages.
- About does not occupy a primary navigation slot.

### Global tools

- Desktop shell order: sign-in status, task center, theme toggle, account or more menu.
- Mobile shell keeps task center and theme toggle directly visible.
- Mobile more menu contains sign-in status, about, and logout.

### Mobile navigation

- Mobile bottom navigation contains five primary modules: resource, subscription, monitor, tree, and settings.
- Labels should stay compact: resource, subscription, monitor, tree, settings.

### Visual direction

- The shell uses controlled liquid glass.
- The resource result board uses lower-transparency solid surfaces for readability.

## Information Architecture

The application is organized as one stable shell plus independent module workspaces.

### Shared shell responsibilities

The shell owns:

- primary module navigation
- global tool area
- task center trigger and badge
- theme toggle
- sign-in summary
- account or more menu
- device-specific navigation scaffolding

The shell does not own resource list rendering, subscription task rendering, monitor task rendering, or settings form rendering. Those belong to module-level views.

### Desktop layout

Desktop uses a three-zone shell:

1. A compact left navigation rail for primary module switching.
2. A top-right shell tool cluster for sign-in summary, task center, theme toggle, and account or more menu.
3. A dominant main content region that defaults to resource exploration.

The left navigation should stay narrow and stable. It should not expand into a dashboard. About remains secondary and should live in a low-frequency shell area instead of the main module rail.

### Mobile layout

Mobile uses:

1. A compact top tool bar for task center, theme toggle, and more menu.
2. A bottom five-item primary navigation bar.
3. A single-column module content area.

Mobile must preserve direct access to tree and settings in the bottom navigation. More menu is only for low-frequency global actions.

## Resource Exploration Workspace

Resource exploration is the default workspace and the highest-priority screen in the product.

### Page composition

The resource workspace consists of four persistent regions and two conditional regions.

Persistent regions:

1. Thin search and sync strip.
2. Fixed quick link strip.
3. Main resource result board.
4. Shell-level global tools outside the resource content area.

Conditional regions:

1. Narrow blocking reminder strip for missing critical configuration.
2. Search result mode that replaces the default grouped content stream after search execution.

### Thin search and sync strip

This strip should stay shallow in height and visually lighter than the current large card treatment. It contains:

- search input
- search button
- sync channels button
- compact immediate state such as source count or last sync note

It should not absorb secondary management tools that distract from browsing. It exists to let users search or sync quickly, then return attention to the resource stream.

### Quick link strip

Quick links are fixed first-screen tools and remain visible on first load.

Requirements:

- quick links appear directly below the search and sync strip
- users can open common links immediately
- quick link management has an explicit entry in the strip
- desktop favors horizontal visibility of more items
- mobile supports horizontal scrolling with clear affordance and a visible manage entry

Quick links are not a hidden utility. They are part of the core resource exploration workflow.

### Default content mode

Before search executes, the result board displays grouped channel or source sections as a content stream.

Each section header should show only essential metadata:

- channel or source name
- count or availability summary
- recent sync or freshness summary
- expand or collapse action

Section-level actions must stay restrained. The stream should read as content, not as a dense control panel.

### Search result mode

When a user executes search:

- the content board switches from grouped stream mode to search result mode
- the shell, search strip, and quick link strip remain visually stable
- the user sees current keyword, match count, and a clear action to return to grouped stream mode

Search result mode should feel like a temporary working state, not a separate page. Returning to grouped stream mode must be obvious and fast.

### Blocking reminder behavior

The old onboarding card is removed from the first-screen default hierarchy. If a missing configuration blocks import or sync work, show a narrow contextual reminder below the search area instead of a large onboarding card. The reminder should explain the blocker and provide a direct path to settings.

This keeps resource exploration dominant while still surfacing real blockers.

## Other Module Pages

Subscription, monitor, tree, and settings remain separate module pages within the same shell.

Requirements:

- switching modules should feel like swapping the main workspace inside one application shell
- shell tools remain stable during module changes
- resource exploration should preserve user context when users leave and return

The resource module should preserve:

- current keyword
- whether the user is in grouped stream mode or search result mode
- scroll position when practical
- expanded or collapsed section state when practical

This prevents module switching from feeling destructive.

## Global Tools and Utility Placement

### Desktop

Desktop tool order:

1. sign-in status pill
2. task center trigger with badge
3. theme toggle
4. account or more menu with logout and secondary items

Task center is not a page. It is a global drawer or floating panel accessible from any module without losing the current workspace.

Logout should not remain as a high-contrast always-exposed destructive button. It belongs inside the account or more menu.

### Mobile

Mobile directly exposes:

- task center
- theme toggle

Mobile more menu contains:

- sign-in summary or sign action
- about
- logout

If sign-in requires immediate attention, it may temporarily escalate visually, but it should not permanently displace task center or theme toggle.

## Visual Design System

The style direction is liquid glass control surface, not marketing gloss and not a full-glass interface.

### Material hierarchy

Three material levels are required:

1. Strong glass for shell surfaces: top tool bars, desktop nav, mobile bottom nav, task drawer, floating menus, dialogs.
2. Medium glass for secondary shell surfaces: quick link strip, compact status pills, contextual overlays.
3. Solid or low-transparency panels for content-heavy regions: resource board, grouped sections, list cards, forms.

This hierarchy ensures shell richness without making the content stream blurry or visually unstable.

### Color and contrast

- Base atmosphere uses deep cool tones with subtle gradient motion.
- Primary interaction accents use ice blue and teal.
- Success uses green.
- Warning uses amber.
- Error uses warm red.
- Content text stays high-contrast and should not rely on glow for legibility.

### Motion

Motion should stay restrained and purposeful.

Allowed emphasis:

- search mode transition
- task badge updates
- section expand or collapse
- drawer entry or exit

Avoid long elastic motion, large-scale parallax, or animated glass effects over the content stream.

## Performance and Frontend Structure

The redesign must actively improve structure and runtime behavior, not just appearance.

### Current structural problem

The current frontend concentrates the main interface in one large HTML file, one large CSS file, and one very large JavaScript file. This makes module isolation, targeted rendering, and lazy initialization difficult. The current init flow also eagerly refreshes multiple modules during first load.

### Target structure

Split the frontend into shell-level and module-level boundaries.

Recommended conceptual boundaries:

- shell layout and navigation
- shell global tools and task center
- resource exploration module
- subscription module
- monitor module
- tree module
- settings module
- shared design tokens and shared component styles

Exact file boundaries are implementation details for the plan, but the architectural separation is required.

### Initialization strategy

On login, initialize only:

- shell summaries needed for global tools
- resource exploration module

Do not fully initialize subscription, monitor, tree, or settings on first load. Those modules should fetch and render on first entry.

### Resource rendering strategy

The resource board should support independent updates for:

- grouped channel or source sections
- search result container
- quick link strip
- blocking reminder strip

Avoid re-rendering the full resource page for every search, sync, expand, or task update. The goal is to keep the shell stable and localize updates to the affected region.

### Styling strategy

Do not keep relying on runtime Tailwind CDN setup for the long-term design. Styles should be local, cacheable, and predictable in production. Liquid glass should be implemented with a limited set of reusable tokens and surface patterns rather than one-off heavy effects.

### Glass performance constraints

- backdrop blur is limited to shell surfaces and overlays
- content-dense cards must not all use backdrop blur
- mobile uses reduced blur, reduced shadow, and reduced reflective treatment
- gradients, subtle borders, and highlight overlays should carry most of the visual effect instead of expensive filters

## Data and State Behavior

State should be split into shell summaries and module detail state.

### Shell summary state

Shell summary state includes:

- sign-in status summary
- task badge and task center summary
- theme preference
- low-frequency app-wide notices such as version badge

This state must stay lightweight and should not trigger full module refreshes.

### Module detail state

Each module owns its own detailed state and rendering lifecycle. Resource exploration owns:

- current grouped sections
- current search result sections
- current keyword
- expanded or collapsed sections
- quick links and quick link management state
- import and resource detail modals

Subscription, monitor, tree, and settings should not refresh as a side effect of logging into resource exploration.

## Error Handling and Empty States

### Resource exploration

- No channels or content available: show a clear empty state in the result board with a direct path to the relevant setup area.
- Missing critical configuration: show a narrow blocking reminder near the search area.
- Search with no results: show a clear no-result state inside search result mode and preserve the action to return to grouped stream mode.
- Partial source failures during search: show a compact explanatory note without collapsing the full board into an error page.

### Global tools

- Task drawer failure should degrade to an inline error inside the drawer, not block the current module.
- Sign-in failure should update the sign-in pill state without disturbing the resource result board.

## Testing and Acceptance Criteria

### Product acceptance

1. Login always lands on resource exploration.
2. First visible resource screen contains shell tools, thin search and sync strip, fixed quick link strip, and grouped content stream.
3. Quick links remain first-screen on desktop and mobile.
4. Resource grouped stream remains the default state until search executes.
5. Subscription, monitor, tree, and settings remain independent module pages.

### Interaction acceptance

1. Desktop module switching does not reflow or rebuild the shell.
2. Mobile keeps task center and theme toggle explicitly visible.
3. Mobile bottom navigation exposes resource, subscription, monitor, tree, and settings directly.
4. Returning to resource exploration preserves enough context to avoid losing user orientation.

### Visual acceptance

1. Shell surfaces clearly read as liquid glass.
2. Resource content remains easy to read and visually prioritized over shell chrome.
3. Glass treatment never makes the grouped resource stream feel soft, blurry, or low-contrast.

### Performance acceptance

1. First load initializes shell and resource exploration only.
2. Non-resource modules do not perform full startup fetches before user entry.
3. Resource scrolling remains smooth on mobile and desktop.
4. Search and grouped-mode switching do not rebuild unrelated shell regions.
5. Glass effects do not create obvious jank on mobile.

### Regression acceptance

The redesign must preserve:

- resource search
- direct import recognition from magnet or supported share links
- channel sync
- resource detail and import entry points
- quick link open and manage flows
- independent subscription, monitor, tree, and settings navigation
- SSE-driven status updates, task badge refreshes, and sign-in summary updates

## Design Outcome

The redesign succeeds when users enter the product and immediately start resource work instead of parsing a general homepage. The shell becomes cleaner and more coherent, quick links stay prominent, desktop and mobile each get an intentional layout, and the liquid glass style improves atmosphere without reducing clarity or speed.
