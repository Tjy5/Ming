## Scope Reconciliation

The final accepted scope is the desktop game experience at 1024x768, 1440x900, and 1920x1080. The original mobile/tablet tasks were intentionally removed from this change after the product decision to focus on desktop. They are recorded as follow-up work below rather than marked as completed.

## Completed Tasks

### Baseline and Boundaries

- [x] Record frontend lint, build, Vitest, and deterministic desktop visual results.
- [x] Capture before/after governance evidence at 1440x900 and 1920x1080, plus the final 1024x768 compact-desktop capture.
- [x] Inventory and preserve route paths, Chinese primary labels, shortcuts, identifiers, map geometry, state ownership, and action callbacks.

### Desktop Visual Foundation

- [x] Add the compatibility-first semantic Yuan-Ming visual layer with paper, ink, cinnabar, gold, teal, focus, status, spacing, texture, and motion roles.
- [x] Preserve legacy CSS variable aliases and existing application behavior while adopting the new desktop layer.
- [x] Replace default Vite branding with the local imperial seal mark and retain the game document title.
- [x] Add desktop-focused reduced-motion, focus, status, and interaction-state treatments.

### Shared Interaction Surfaces

- [x] Apply consistent desktop page, panel, field, button, loading, empty, and error treatments across redesigned routes.
- [x] Add stable accessible names and status/alert semantics to the delivered text inputs and feedback states.
- [x] Add focus containment and overlay registration to the delivered target and edict dialogs.
- [x] Protect save/load and command submissions against duplicate activation while preserving recoverable state.

### LifeStory and Governance

- [x] Recompose and restyle the desktop LifeStory narrative/action surface without changing story or scripted-event semantics.
- [x] Unify governance resource hierarchy, map framing, rail surfaces, inspector treatment, and bottom command HUD.
- [x] Preserve map SVG geometry, region identifiers, shortcut behavior, Zustand authority, API/SSE semantics, and existing callbacks.
- [x] Verify mutual exclusion and desktop operation of map mode, court, minister, inspector, decree, and management surfaces.

### Supporting Routes and Verification

- [x] Apply the visual system to mode selection, chat, continuity, admin, save/load, and related desktop surfaces.
- [x] Verify real desktop chat submission and assistant response behavior.
- [x] Run lint, production build, 27 Vitest files / 153 tests, desktop visual capture, and console/overflow checks.
- [x] Record the implementation and rollback commits: `ba3adcc` and `de57889`, with baseline `bccd72e`.

## Deferred Follow-up

- Mobile/tablet LifeStory composition, narrow viewport layouts, touch-equivalent controls, and software-keyboard behavior.
- The five-viewport mobile-inclusive visual/state matrix, 200% text-zoom pass, and touch-target audit.
- Full stylesheet decomposition, legacy-selector removal, dead-code cleanup, and broad screenshot coverage for every unvisited state.
