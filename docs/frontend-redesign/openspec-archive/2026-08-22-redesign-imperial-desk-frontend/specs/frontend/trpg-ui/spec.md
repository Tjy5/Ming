> Final scope: LifeStory visual acceptance in this change is desktop-only. Mobile/tablet composition and software-keyboard behavior are deferred.

## MODIFIED Requirements

### Requirement: Narrative Story Feed and Accessibility
The TRPG page SHALL display GM narrative progression in a bounded, readable feed with clear separation between narration, system feedback, checks, and player actions, and with `aria-live="polite"` accessibility that announces new content without repeatedly reading the entire history.

#### Scenario: Narrative streaming display
- **WHEN** GM narrative text arrives
- **THEN** the newest narrative updates smoothly within a readable text measure, remains distinguishable from earlier turns, and is announced without replacing or clipping prior history

#### Scenario: Long narrative history
- **WHEN** the story feed contains enough turns to exceed the viewport
- **THEN** the feed preserves chronological reading order, allows normal review of earlier turns, and keeps the current action path reachable without collapsing the narrative into an unreadably narrow column

## ADDED Requirements

### Requirement: Desktop LifeStory Composition
LifeStory SHALL present the character sheet, narrative feed, dice or event feedback, and player action surface as a readable desktop composition without fixed-width clipping or page-level horizontal overflow.

#### Scenario: Desktop LifeStory layout
- **WHEN** the viewport is at least 1024px wide
- **THEN** character context, narrative progression, and the current action surface have distinct stable regions and the narrative remains the dominant reading surface

### Requirement: Accessible LifeStory Actions and Outcomes
LifeStory free actions, declared choices, checks, transitions, endings, loading, and errors MUST expose stable names and status semantics, preserve recoverable input, and prevent duplicate submission.

#### Scenario: Free-action entry
- **WHEN** the free-action composer is available
- **THEN** its input has a persistent programmatic label, its submit action is associated with the form, and placeholder text is supplemental rather than the only accessible name

#### Scenario: Action submission in progress
- **WHEN** a player submits a free action or declared choice
- **THEN** the initiating action is locked, progress is communicated accessibly, and the same turn cannot be submitted again until the request resolves

#### Scenario: Recoverable action error
- **WHEN** a submitted action fails without ending the story
- **THEN** an accessible alert preserves the player's input and current narrative context and makes retry or correction available

#### Scenario: Transition or ending overlay
- **WHEN** LifeStory presents a blocking chapter transition or ending
- **THEN** it renders as an accessible titled dialog, receives meaningful initial focus, contains focus while active, and restores focus or moves it to the valid next route when resolved

#### Scenario: Non-blocking status update
- **WHEN** dice, turn, or narrative feedback does not require a modal decision
- **THEN** it uses a non-blocking status region and does not steal focus from the current action control
