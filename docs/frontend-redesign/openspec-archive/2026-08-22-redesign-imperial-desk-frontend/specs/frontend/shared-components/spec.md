> Final scope: the shared interaction changes are applied to the delivered desktop surfaces; mobile/tablet touch behavior is deferred.

## MODIFIED Requirements

### Requirement: Base Modal Composition
All modal dialogs SHALL compose the shared `.modal-overlay > .modal` base structure or a themed `[data-overlay-root="modal"] > [data-overlay-panel]` extension, register with the shared overlay stack, move focus to a meaningful initial control or heading, trap focus while topmost, and restore focus to their opener when closed.

#### Scenario: Modal styling composition
- **WHEN** a modal dialog renders
- **THEN** it uses one allowed root/panel structure and provides `role=dialog`, `aria-modal=true`, an accessible title, `aria-label` on close buttons, and overlay-stack registration

#### Scenario: Meaningful initial focus
- **WHEN** a modal opens as the topmost overlay
- **THEN** focus moves to its designated primary field, safe action, or titled panel rather than remaining behind the overlay or landing on an arbitrary destructive control

#### Scenario: Topmost Escape handling
- **WHEN** multiple registered dialogs or popovers are open and the player presses Escape
- **THEN** only the topmost closable overlay closes and focus returns to the control that opened it

#### Scenario: Reduced-motion modal feedback
- **WHEN** `prefers-reduced-motion: reduce` is active
- **THEN** modal entrance, crisis pulse, and seal feedback use non-moving visual states without removing information or blocking commands

## ADDED Requirements

### Requirement: Accessible Form Composition
Every shared text, select, and choice control MUST have a stable accessible name, visible instructions when context is not self-evident, associated validation feedback, and a semantic form submission path where submission is supported.

#### Scenario: Text entry control
- **WHEN** a player encounters a text field or textarea
- **THEN** it has a programmatically associated label that remains available after text is entered and does not rely on placeholder text as its only name

#### Scenario: Validation failure
- **WHEN** submitted input is invalid
- **THEN** focus or an accessible error summary identifies the affected field, the entered value remains available for correction, and the error is programmatically associated with the control

#### Scenario: Keyboard form submission
- **WHEN** a form supports submission and the focused control uses its documented submit gesture
- **THEN** the same guarded submit action runs as the visible primary button and invokes the underlying handler at most once

### Requirement: Consistent Status and Feedback Semantics
Shared loading, success, warning, error, empty, and disabled states SHALL combine visual treatment with accessible text or status semantics and MUST NOT depend on color, motion, emoji, or an unlabeled icon alone.

#### Scenario: Asynchronous action in progress
- **WHEN** a player starts an asynchronous action
- **THEN** the initiating control exposes its busy or disabled state, duplicate activation is prevented, and bounded progress text is available to assistive technology

#### Scenario: Action error
- **WHEN** an asynchronous action fails
- **THEN** a non-stale accessible alert describes the failure, recoverable input remains intact, and the control becomes available again when retry is valid

#### Scenario: Icon-only control
- **WHEN** a shared control displays only an icon or historical symbol
- **THEN** it has a stable accessible name and visible tooltip or adjacent label wherever the icon meaning is not already explicit

### Requirement: Stable Action Surfaces
Primary action surfaces SHALL remain visually and spatially distinct from narrative or reference content and MUST adapt without covering the current status, error, or only available continuation action.

#### Scenario: Narrow viewport action surface
- **WHEN** a shared action footer or composer renders on a narrow viewport
- **THEN** it participates in the page reading order or uses bounded sticky positioning without clipping content behind it
