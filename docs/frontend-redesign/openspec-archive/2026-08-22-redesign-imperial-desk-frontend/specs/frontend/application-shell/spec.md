> Final scope: reference acceptance for this change is desktop-only at 1024x768, 1440x900, and 1920x1080. Mobile/tablet composition is deferred.

## Purpose

The application shell defines the coherent page-level identity, responsive composition, stable navigation contract, and observable UI-state behavior shared by primary and supporting frontend routes.

## ADDED Requirements

### Requirement: Coherent Cross-Route Experience
The frontend SHALL present governance, 跑团, mode selection, chat, continuity, settings, save/load, and guide surfaces as parts of one Yuan-Ming game interface with a consistent hierarchy of page title, primary content, contextual information, and actions.

#### Scenario: Supporting route opened
- **WHEN** a player opens a supporting route or surface outside the main governance and 跑团 views
- **THEN** it retains the same paper, ink, cinnabar, gold, and teal identity and uses the same interaction-state language as the primary game views

#### Scenario: Cross-route return
- **WHEN** a player returns from a supporting route to governance or 跑团
- **THEN** the destination retains its existing route, phase, game state, and primary action labels without a visually unrelated intermediate shell

### Requirement: Responsive Page Composition
Every delivered desktop route SHALL adapt its information hierarchy to the supported desktop viewport without clipping primary content, creating page-level horizontal overflow, or making the only continuation or close action unreachable.

#### Scenario: Reference viewport acceptance
- **WHEN** a route is rendered at 1440x900, 1024x768, or 1920x1080
- **THEN** its title, primary content, current status, and at least one valid next or close action remain visible or reachable through normal vertical scrolling

### Requirement: Stable Route and Control Compatibility
The redesign MUST preserve existing route paths, phase-driven redirection, Chinese primary labels, shortcut mappings, analytics-sensitive identifiers, and action semantics unless a separate capability change explicitly modifies them.

#### Scenario: Existing deep link
- **WHEN** a player loads any previously supported frontend route directly
- **THEN** the same route resolves to the same game mode or supporting experience as before the redesign

#### Scenario: Existing visible command
- **WHEN** a player activates a retained command by pointer, touch, keyboard, or shortcut
- **THEN** it invokes the same state transition or action path and does not create a styling-only duplicate behavior

### Requirement: Observable and Recoverable Page States
Every page-level loading, empty, error, and submission state MUST identify the affected operation, expose its status accessibly, preserve recoverable player input, and provide an available next action when recovery is possible.

#### Scenario: Page data is loading
- **WHEN** a route is waiting for required data
- **THEN** it displays a bounded loading state that preserves the surrounding page context and communicates progress without indefinite decorative motion

#### Scenario: Recoverable page error
- **WHEN** required data or an action fails without ending the game
- **THEN** an accessible error identifies what failed, retains relevant player input or selection, and offers retry, dismiss, or safe navigation as supported by the existing flow

#### Scenario: Valid empty state
- **WHEN** a supporting screen has no records or available items
- **THEN** it explains the empty condition and keeps the appropriate return or creation action reachable instead of rendering a blank decorative panel
