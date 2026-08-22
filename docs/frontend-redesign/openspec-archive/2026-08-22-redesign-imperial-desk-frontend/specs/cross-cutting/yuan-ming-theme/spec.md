> Final scope: this change covers the desktop game experience. Mobile/tablet composition and touch/software-keyboard behavior are deferred.

## MODIFIED Requirements

### Requirement: Yuan-Ming CSS Variable Palette
The application SHALL expose a unified semantic theme that retains the established rice-paper backgrounds, ink text, cinnabar accents, gold and teal support colors, and historical map materials while defining reusable roles for surfaces, text hierarchy, borders, focus, success, warning, error, spacing, typography, radius, shadow, texture, and motion.

#### Scenario: Theme tokens in root
- **WHEN** the application styles load
- **THEN** `:root` retains `--bg-dark`, `--bg-panel`, `--bg-card`, `--text-main`, `--text-dim`, and `--accent-red` and also defines semantic roles sufficient for interactive, status, elevation, spacing, typography, radius, and motion states

#### Scenario: Cross-page semantic state
- **WHEN** the same focus, loading, success, warning, error, selected, or disabled state appears on different frontend routes
- **THEN** it uses the same semantic visual meaning even when the containing component has a route-specific composition

## ADDED Requirements

### Requirement: Historical Material Hierarchy
The Yuan-Ming theme SHALL use paper, ink, seal, gold, teal, map, and portrait treatments to clarify information hierarchy and MUST keep decorative texture subordinate to text, state, and command legibility.

#### Scenario: Dense governance surface
- **WHEN** map texture, region state, labels, alerts, controls, and overlays are visible together
- **THEN** actionable controls and current state remain distinguishable from decoration at default browser zoom and text retains accessible contrast

#### Scenario: Narrative surface
- **WHEN** a player reads long-form 跑团 or chat content
- **THEN** decoration frames a bounded readable text measure without placing repeated texture or heavy shadow behind every content block

### Requirement: Restrained Shape and Elevation Language
The theme MUST use a small documented set of corner, border, and elevation roles and SHALL reserve pills, large radii, and heavy shadows for semantics that require them rather than applying them as generic card styling.

#### Scenario: Supporting page adoption
- **WHEN** mode selection, continuity, chat, settings, or save/load surfaces are rendered
- **THEN** their containers use the same restrained shape and elevation hierarchy as governance and 跑团 instead of an unrelated rounded product-card language

### Requirement: Motion Communicates State
Frontend motion SHALL communicate a transition, changed value, active crisis, or direct response to player input and MUST provide a non-moving equivalent when reduced motion is requested.

#### Scenario: Idle screen
- **WHEN** no value changes, transition runs, active crisis requires attention, or player input is being acknowledged
- **THEN** the interface does not run attention-seeking infinite animation solely for decoration

#### Scenario: Reduced motion preference
- **WHEN** `prefers-reduced-motion: reduce` is active
- **THEN** movement and pulsing stop while static color, outline, icon, text, and state changes preserve all information
