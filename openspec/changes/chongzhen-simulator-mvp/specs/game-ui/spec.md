## ADDED Requirements

### Requirement: Main layout structure
The game UI SHALL use a fixed layout with 4 zones: top resource bar (full width), center-left map view (70% width), center-right faction panel (30% width), bottom area split into event bar and action area.

#### Scenario: Layout rendering
- **WHEN** the game page loads
- **THEN** all 4 zones are visible without scrolling on a 1920x1080 viewport

### Requirement: Resource bar
The top resource bar SHALL display: 钱粮 (treasury), 人口 (population), 军备 (military_supply), 民心 (civil_morale), 军心 (military_morale), 朝廷威望 (court_prestige), and current game time (崇祯N年N月). Each value SHALL show a numeric display and a colored progress bar.

#### Scenario: Resource update animation
- **WHEN** a decree result is received with changed resource values
- **THEN** the resource bar values SHALL animate from old to new values (transition duration 500ms), with increases shown in green and decreases in red

### Requirement: Region map view
The map view SHALL display 8 clickable region blocks arranged in a simplified geographic layout. Each block shows: region name, stability value, control status, and threat indicator. Block background color SHALL reflect stability (green > 60, yellow 30~60, red < 30).

#### Scenario: Region click interaction
- **WHEN** player clicks a region block
- **THEN** a tooltip/popover shows detailed region info: garrison count, tax contribution, active threats, recent events

#### Scenario: Region status change
- **WHEN** a region's stability changes after a decree
- **THEN** the block's background color transitions to reflect the new stability level

### Requirement: Faction panel
The right panel SHALL list all 4 factions with: faction name, satisfaction bar (0~100), influence bar (0~100), rebellion risk indicator. Factions with rebellion_risk > 60 SHALL be highlighted in red.

#### Scenario: Faction panel update
- **WHEN** decree results change faction values
- **THEN** the satisfaction and rebellion_risk bars animate to new values

### Requirement: Event bar
The bottom event bar SHALL display the most recent 5 events in chronological order. Each event shows: event title, urgency level (高/中/低 with color coding), and brief description. Clicking an event expands its full AI narrative.

#### Scenario: New event display
- **WHEN** a decree generates chain events
- **THEN** new events appear at the top of the event bar with a brief highlight animation

### Requirement: Action area
The action area SHALL contain: 8 fixed decree buttons arranged in 2 rows of 4, and a text input field with a submit button. The action area SHALL be disabled during decree processing (loading state).

#### Scenario: Loading state
- **WHEN** a decree is being processed
- **THEN** all buttons and the input field are disabled, and a loading indicator is shown

#### Scenario: AI narrative display
- **WHEN** decree processing completes
- **THEN** the AI narrative text is displayed in a modal or expandable panel with the state changes summary
