## Context

See `proposal.md` for motivation and the delta specs for normative behavior.

The frontend already contains the right historical ingredients but not one governing visual system. Governance uses hard-edged paper, map, seal, and archival treatments; LifeStory and supporting routes frequently use larger rounded cards, stronger shadows, and product-style composition. The useful base tokens live in a large `app-core.css`, while colors, radii, shadows, and paper-noise treatments are also repeated locally. This makes small visual adjustments unpredictable and lets page-specific CSS drift.

The most important visual defect for this desktop game is inconsistent hierarchy across LifeStory and governance. LifeStory needs a readable narrative/action composition at desktop widths, while governance's resource bar, decorative map layers, inspector, command rail, alerts, and bottom HUD compete for the same visual priority.

Useful interaction foundations already exist: Zustand owns global HUD/overlay state, shared focus-trap and overlay registration hooks are available, Vitest covers component behavior, and the Playwright configuration can launch a deterministic local backend plus Vite. The redesign should extend those foundations rather than introduce a second UI framework or state path.

Constraints:

- No gameplay, backend, database, route, phase, shortcut, or API-contract changes.
- No external fonts or network-loaded image assets.
- Existing Chinese primary labels and analytics-sensitive identifiers remain stable.
- `childhood-offscript-ai-rail` owns scripted-event tracks, choices, deferral, and writeback semantics; this change only owns presentation and accessibility integration.
- The visual direction is a targeted evolution with approximate dials of design variance 6/10, motion intensity 4/10, and visual density 7/10.
- Final acceptance is desktop-only at 1024x768, 1440x900, and 1920x1080. Mobile/tablet, touch-equivalent controls, and software-keyboard behavior are deferred.

## Goals / Non-Goals

**Goals:**

- Establish one semantic visual foundation that makes route-specific composition feel related without making every screen identical.
- Replace accidental CSS variation with small, documented scales for color roles, type, spacing, shape, elevation, texture, focus, and motion.
- Make LifeStory genuinely usable as a desktop narrative surface before broader visual refinement.
- Give governance a clear priority order while preserving its information density and historical map identity.
- Reuse one accessible interaction model for forms, status feedback, dialogs, action surfaces, and focus return.
- Land the redesign in reviewable slices protected by deterministic semantic and visual acceptance checks.

**Non-Goals:**

- Replacing the custom historical UI with Material, shadcn, Bootstrap, Tailwind presets, or a generic dashboard kit.
- Rewriting the map geometry, changing metric calculations, removing commands, or simplifying governance data semantics.
- Redesigning scripted-event domain behavior owned by the active AI change.
- Creating a universal `Card` abstraction or forcing every route into one DOM layout.
- Guaranteeing pixel-identical font rasterization across operating systems; layout and state behavior are the stable contract.
- Introducing a dark/light theme switch, downloadable fonts, or a new animation library.
- Completing mobile/tablet composition, touch equivalence, or software-keyboard handling in this change.
- Performing a one-shot decomposition of every legacy stylesheet and selector.

## Decisions

### 1. Evolve toward an “imperial desk / central archive” system

Paper is the reading field, ink is the information hierarchy, cinnabar marks command and urgency, gold denotes rank or prestige, and teal separates analytical or geographic context. Map textures, seals, dividers, and portraits act as a small number of compositional anchors rather than being repeated on every container.

The interface keeps relatively high information density, but each viewport gets one dominant task surface. Governance remains map-first; LifeStory remains narrative-first; supporting routes use one strong archival panel rather than a grid of equally weighted cards. This preserves the game's identity while removing the visual noise and generic product styling found in the current cross-page mix.

Alternative considered: a visual greenfield or modern SaaS design system. Rejected because it would erase the strongest existing product identity and make dense strategy information feel interchangeable with an administration dashboard.

### 2. Use a compatibility-first semantic visual layer

Create one ordered compatibility-first style layer for the delivered desktop scope. It contains the raw historical palette, semantic color/type/spacing/radius/elevation/texture/focus/motion roles, shared surface treatments, and feature overrides. A later cleanup may split these roles into separate files after each consumer is migrated.

Existing root names such as `--bg-dark`, `--bg-panel`, `--bg-card`, `--text-main`, `--text-dim`, and `--accent-red` remain as aliases during migration. New code consumes semantic roles such as surface, text, border, action, focus, positive, warning, and danger rather than raw color values.

The base scale uses a 4px spacing rhythm, three regular radii (2px, 4px, 8px), a badge-only pill radius, and three elevation levels. Essential text never falls below 12 CSS pixels. Heading sizes may use bounded `clamp()` values, while long narrative text uses a stable reading size and line height. A single reusable paper-noise treatment replaces duplicated pseudo-elements.

`app-core.css` remains available for legacy consumers. The delivered change imports the new layer after the existing application styles so the migrated desktop surfaces can adopt the visual system without a risky one-shot stylesheet rewrite.

Alternative considered: preserve all existing CSS and only add override files. Rejected because specificity growth would make the redesign fragile and leave the duplicated visual language intact.

### 3. Use a thin application shell and semantic primitives, not a component factory

Introduce only the shared structures that carry observable behavior across routes:

- page frame and page heading hierarchy;
- field label, help, and error association;
- status message for loading, success, warning, error, and empty states;
- action surface for composers and primary decisions;
- dialog surface integrated with the existing overlay stack;
- visually hidden text, focus ring, icon-control label, and bounded tooltip helpers.

Feature components keep their own meaningful names and compositions. A governance metric, character trait, chat message, and continuity branch do not become variants of a universal card. Primitives accept content and state but do not own game data, routing, submission, or duplicate open-state booleans.

The document title remains `大明：开国风云`, and the default Vite favicon is replaced by a local, historically appropriate mark derived without a network asset.

Alternative considered: make a broad internal component library before touching pages. Rejected because abstraction would be guessed from current inconsistencies; primitives should be extracted from concrete LifeStory and governance adoption.

### 4. Recompose desktop LifeStory around reading order

Desktop uses a bounded character column and a flexible `minmax(0, 1fr)` narrative/action column. The page root allows vertical document flow instead of hiding overflow. The narrative feed receives the dominant width and a bounded reading measure; the character sheet is supporting context rather than an equal visual competitor.

Mobile reading order and conditional sticky behavior are deferred. The desktop action surface remains in normal document flow and the narrative column retains the dominant reading measure.

The free-action composer becomes a semantic form with a persistent label and one guarded submit path. Loading and non-blocking dice feedback use status regions; errors use alerts and preserve the draft. Chapter transitions and endings use the shared overlay stack, meaningful initial focus, focus containment, and deterministic resolution focus.

The scripted-event decision body is consumed as a shared view when the active AI change supplies it. This change may style its host and satisfy layout/focus contracts but does not introduce a second choice model or fallback API.

Alternative considered: keep broad mobile behavior in this change. Rejected because the current product decision is to finish and validate the desktop game first; mobile behavior belongs in a separately scoped change.

### 5. Give governance an explicit layer and layout contract

The top bar retains all eight metrics, the four existing groups, the 56px desktop height, urgent badges, direct dialogue/跑团/memorial entries, and the palace settings menu. The visual order becomes value and urgency first, trend second, short label third, and explanatory detail on demand. Secondary tools remain in the existing menu instead of competing with every metric.

The map uses a fixed visual stack:

1. paper/map ground;
2. historical geography and subdued texture;
3. governance fills;
4. selected, focused, and crisis state;
5. labels and bounded tooltip;
6. inspector and active command surfaces.

Selection and keyboard focus outrank hover. Crisis keeps a static cinnabar outline, icon, and text; pulse is optional enhancement only while a qualifying crisis is active. Decorative texture and shadow never share the same strength as a selected or urgent state.

Governance geometry is coordinated through shared layout variables for top-bar height, command-rail width, expanded-panel width, bottom-HUD height, and safe inset. The inspector, tooltip, map description, active rail panel, and bottom HUD consume those values instead of maintaining unrelated fixed offsets. Mutually exclusive surfaces continue to use the existing Zustand authority.

Alternative considered: remove layers and simplify the map to a flat diagram. Rejected because geography and material richness are part of the game's strategy identity; the problem is ungoverned priority, not the existence of layers.

### 6. Adopt supporting routes by role, not by visual cloning

Mode selection acts as the ceremonial entry; chat is a correspondence desk; continuity is an archive of branches; settings and save/load are administrative records. They share tokens, page hierarchy, controls, state feedback, and motion rules while retaining compositions suited to their tasks.

Each route gets one primary panel, one obvious next action, and bounded secondary explanation. Large rounded cards, repeated heavy shadows, emoji-only alerts, and disconnected decorative backgrounds are removed. Existing route paths, labels, callbacks, and loaded state remain unchanged.

Alternative considered: apply governance HUD chrome to every route. Rejected because the map command surface is context-specific and would reduce narrative and administrative readability.

### 7. Make accessibility behavior part of every visual primitive

The shared interaction contract includes:

- visible `:focus-visible` treatment with sufficient contrast on paper and map surfaces;
- a persistent programmatic label for every input, including free-action and scripted-event text areas;
- `role="status"` or a polite live region for non-blocking progress and `role="alert"` for actionable failures;
- at least 44x44 CSS-pixel touch targets for isolated icon controls where layout permits, with spacing preventing accidental activation;
- dialog title association, meaningful initial focus, topmost-only Escape, focus containment, and opener restoration;
- text or accessible names alongside every icon, color, motion, or historical symbol that communicates state;
- no focus movement for ordinary narrative, dice, or metric updates.

Existing overlay and shortcut authorities are extended, not replaced. A component may own ephemeral presentation details, but it cannot create a second source for whether a global surface is open.

Alternative considered: perform a final accessibility pass after visual work. Rejected because focus, DOM order, action placement, and modal structure determine the composition and are expensive to retrofit.

### 8. Use motion sparingly and centrally

Tokenized durations cover immediate feedback, panel transition, and major state transition. Continuous animation is permitted only for a currently active semantic condition such as a crisis and always has a static equivalent. Hover effects use color, border, or small translation rather than unrelated scaling.

The global reduced-motion layer disables smooth scrolling, panel travel, pulse, seal movement, and decorative parallax while preserving state changes. Framer Motion remains available where already justified, but ordinary component transitions prefer CSS tokens so timing and reduction behavior stay consistent.

Alternative considered: add more motion to make the redesign feel premium. Rejected because persistent movement competes with dense strategy information and harms long-session comfort.

### 9. Pair semantic tests with deterministic browser baselines

Vitest and Testing Library cover behavior that screenshots cannot prove: accessible names, live-region roles, form submission guards, initial focus, Escape order, focus return, disclosure state, route compatibility, and retained callbacks.

The existing deterministic Playwright server is extended with a desktop visual matrix for 1440x900, 1024x768, and 1920x1080. Baselines cover the delivered governance and supporting-route states:

- governance idle, region selected, rail panel open, inspector open, and crisis state;
- LifeStory desktop initial/action states, loading, error, and scripted-event host;
- mode selection, chat, continuity, settings, save/load, and guide at desktop widths.

The harness fixes fixture data, viewport, animation state, and time-dependent labels before capture. Screenshot assertions use region-level masks only for genuinely nondeterministic content; they do not mask layout or controls. Browser checks also assert no page-level horizontal overflow and that key controls intersect the viewport. Mobile/tablet visual baselines are explicitly deferred.

Alternative considered: rely on component snapshots or manual screenshots alone. Rejected because neither catches real layout clipping across the required viewports with sufficient repeatability.

### 10. Keep ownership boundaries explicit during parallel changes

The active AI change may add fields and behavior to the scripted-event decision view. This redesign depends only on its published presentation contract: title, bounded description, declared choices, optional track, optional historical hint, optional free text, pending state, and authoritative result. If that change is not yet merged when implementation starts, the LifeStory host and shared visual primitives land first; the event host integration waits rather than copying unfinished domain logic.

Tests in this redesign assert visual composition, focus, responsive behavior, and unchanged handler calls. Tests in the AI change continue to assert event metadata, blocking/deferral rules, and writeback semantics.

Alternative considered: absorb the scripted-event work into this redesign. Rejected because it would combine AI domain behavior with a cross-route visual migration and make either change difficult to verify or roll back.

## Risks / Trade-offs

- [Token migration leaves old and new styles fighting through specificity] → Import layers in one declared order, migrate one surface at a time, and delete superseded selectors in the same slice.
- [A cleaner governance view accidentally hides essential information] → Preserve every metric and command, test stable labels and callbacks, and move only secondary explanation behind explicit detail surfaces.
- [Mobile sticky actions collide with software keyboards or short landscape viewports] → Default to document flow, enable stickiness only with sufficient height, account for safe areas, and test focused fields in both portrait and landscape.
- [Chinese built-in fonts differ across Windows installations] → Use resilient built-in fallbacks, constrain by readable measure rather than character-perfect line breaks, and keep screenshot assertions focused on layout/state.
- [Visual baselines become noisy and ignored] → Use deterministic fixtures, a small named state matrix, explicit update review, and semantic assertions for behavior.
- [Large stylesheet decomposition causes regressions outside the active page] → Retain compatibility token aliases, keep feature styles locally owned, and run the full frontend suite after every adoption stage.
- [Parallel AI work changes the event host contract] → Treat its delta spec as authoritative, isolate visual host changes, and integrate only after the shared decision view shape is available.
- [A design-system effort grows into endless polish] → Implement in the fixed migration order below and require each stage to satisfy its named specs and baseline states before expanding scope.

## Migration Plan

1. Capture deterministic desktop screenshots and semantic test results at 1440x900, 1024x768, and 1920x1080.
2. Add the compatibility-first semantic visual layer, retain existing root aliases, and adopt focus/reduced-motion behavior without changing game contracts.
3. Normalize the delivered dialogs, fields, statuses, icon controls, and action surfaces on existing overlay and state authorities.
4. Recompose LifeStory's desktop reading/action layout and migrate its free action, feedback, and scripted-event host states.
5. Rebalance the governance resource bar, map layers, inspector, rail, and bottom HUD using the state-priority contract.
6. Adopt the visual system on mode selection, chat, continuity, settings, save/load, guide, and remaining desktop secondary surfaces.
7. Run lint, build, the full Vitest suite, deterministic desktop browser checks, and the desktop visual matrix; remediate clipping, overflow, focus, or console regressions before declaring the delivered scope complete.

Mobile/tablet composition, touch/software-keyboard behavior, full stylesheet decomposition, and the broader five-viewport state matrix remain follow-up work and are not part of this archived change.

Rollback is code-only and requires no data migration. The desktop delivery is independently revertible through `ba3adcc` and `de57889`. Compatibility aliases remain for legacy consumers. If the shared scripted-event view is unavailable or regresses, keep the LifeStory host behind the existing legacy rendering contract rather than reverting unrelated theme work.
