## Why

Ming already has a distinctive Yuan-Ming paper, ink, cinnabar, gold, teal, map, and portrait identity, but its frontend applies that identity inconsistently and several dense screens sacrifice hierarchy, accessibility, or desktop usability. This change turns the existing language into a coherent, information-first “imperial desk / central archive” experience for the desktop game without changing game semantics.

## Final Scope Decision

The completed scope is desktop-first: governance and supporting routes are validated at 1024x768, 1440x900, and 1920x1080. The product is a desktop game, so mobile/tablet composition, touch-equivalent controls, and software-keyboard behavior are explicitly deferred to a separate future change rather than represented as completed work in this change.

## What Changes

- Establish an application-wide desktop frontend experience foundation for page shells, composition, interaction states, loading/error/empty feedback, keyboard focus, and visual regression baselines.
- Expand the Yuan-Ming theme from a small color palette into a semantic token system for surfaces, ink hierarchy, state colors, typography, spacing, radius, shadow, texture, focus, and motion while retaining the existing historical material identity and zero-external-asset constraint.
- Recompose LifeStory for desktop with a readable narrative column, a stable action surface, accessible free-action input, and semantic transition, ending, loading, and error states.
- Reuse the accessible scripted-event decision view planned by `childhood-offscript-ai-rail` without redefining its event tracks, choice semantics, deferral rules, API payloads, or authoritative writeback behavior.
- Clarify the governance information hierarchy by simplifying resource density, reducing competing map decoration, keeping region inspection readable beside the HUD, and preserving every existing metric, tool, shortcut, route, label, and governance action.
- Bring mode selection, chat, continuity, settings, save/load, guides, and other supporting surfaces into the same visual and interaction system instead of mixing archival game UI with generic rounded product cards.
- Add deterministic desktop visual baselines plus keyboard, focus, reduced-motion, loading, error, empty, submission, and non-overlap acceptance coverage.
- Preserve existing route paths, phase names, Chinese primary labels, shortcut mappings, analytics-sensitive identifiers, API field semantics, game-state ownership, and backend behavior. This change is a frontend redesign, not a gameplay or data-contract migration.

## Capabilities

### New Capabilities

- `frontend/application-shell`: Defines the shared page-level experience, supporting-route composition, responsive invariants, route continuity, state feedback, and cross-route visual acceptance contract.

### Modified Capabilities

- `cross-cutting/yuan-ming-theme`: Extends the historical palette into a semantic, reusable design-token and motion system while retaining the established material identity and asset restrictions.
- `frontend/shared-components`: Adds consistent accessible form, status, action-surface, focus, dialog, and feedback behavior across reusable controls and overlays.
- `frontend/governance-ui`: Refines resource, map, inspector, and court information hierarchy while preserving all existing governance actions and data semantics.
- `frontend/trpg-ui`: Adds a desktop LifeStory composition and accessible free-action, narrative, transition, ending, loading, and error behavior without duplicating scripted-event semantics owned by the active AI change.
- `main-screen-immersion-hud`: Tightens visual hierarchy, layer competition, persistent-motion, panel/HUD coexistence, and fixed-viewport acceptance for the existing governance command surface.

## Impact

- Primary implementation scope: `Ming/frontend/src/pages`, `components`, `styles`, hooks, frontend tests, and small application-shell assets such as document metadata and the local favicon.
- The delivered visual layer is compatibility-first: semantic tokens and feature overrides are centralized in `imperial-redesign.css` while the larger stylesheet decomposition and dead-code cleanup remain follow-up work. No public TypeScript or API contract changes are introduced solely for styling.
- The frontend remains React 19, Vite, TypeScript, and Zustand. No new backend endpoints, database migrations, external fonts, external image dependencies, or gameplay rules are introduced.
- The active `childhood-offscript-ai-rail` change keeps ownership of scripted-event domain behavior. This change owns only the shared visual composition and accessibility integration needed to render that behavior coherently.
- Rollout is complete for the desktop foundation, LifeStory, governance, and supporting-route adoption, with stable desktop baselines protecting the delivered scope. Mobile/tablet work is intentionally deferred.
