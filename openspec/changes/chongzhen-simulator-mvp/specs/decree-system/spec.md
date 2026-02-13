## ADDED Requirements

### Requirement: Fixed decree buttons
The system SHALL provide 8 fixed decree buttons: 加税 (tax_increase), 减税 (tax_decrease), 增兵 (recruit_troops), 裁兵 (disband_troops), 任免 (personnel), 外交 (diplomacy), 赈灾 (disaster_relief), 严刑 (harsh_punishment). Each button submits a structured decree to the backend. Buttons that require targets SHALL open a target selection dialog before submission.

#### Scenario: Simple button decree submission
- **WHEN** player clicks the "加税" button
- **THEN** the system sends POST /api/decree with body {type: "tax_increase"} to the backend

#### Scenario: Decree with target selection
- **WHEN** player clicks "赈灾" button
- **THEN** the system opens a region selection dialog listing all 8 regions. Player selects a region, then the system sends {type: "disaster_relief", target: "陕西"}

#### Scenario: Personnel decree flow
- **WHEN** player clicks "任免" button
- **THEN** the system opens a dialog with sub_action selection (任命/罢免) and a text field for the target person name

#### Scenario: Diplomacy decree flow
- **WHEN** player clicks "外交" button
- **THEN** the system opens a dialog with target selection (后金/蒙古/朝鲜)

#### Scenario: Button disabled state
- **WHEN** a decree's precondition is not met (e.g., treasury < 30 for disaster_relief)
- **THEN** the corresponding button SHALL be visually disabled with a tooltip showing the reason

### Requirement: Free text input
The system SHALL provide a text input field where players can type arbitrary decree text in Chinese. The input SHALL be sent to the AI parsing endpoint. If parsing returns multiple decrees (multi-intent), the system SHALL display a confirmation dialog showing all parsed decrees before execution.

#### Scenario: Single intent free text submission
- **WHEN** player types "加征辽饷" and presses Enter
- **THEN** the system sends to POST /api/decree/parse, receives [{type: "tax_increase", target: "辽东"}], and proceeds with execution

#### Scenario: Multi-intent free text submission
- **WHEN** player types "加税并且招兵" and presses Enter
- **THEN** the system sends to POST /api/decree/parse, receives [{type: "tax_increase"}, {type: "recruit_troops"}], displays a confirmation dialog "将依次执行：1.加税 2.增兵（各推进1个月），确认？", and upon confirmation executes sequentially

#### Scenario: Multi-intent partial failure
- **WHEN** multi-intent execution is in progress and the 2nd decree fails precondition check
- **THEN** the 1st decree's effects are kept (already committed), the 2nd decree is rejected with error message, and remaining decrees are cancelled

#### Scenario: Parse failure handling
- **WHEN** the AI parser returns an error for the free text input
- **THEN** the system displays the error message to the player and does NOT advance game time

### Requirement: Decree execution flow
The system SHALL process decrees through: precondition check → passive drift application → rule engine calculation → chain event detection → AI narrative generation → state update → game end check → auto-save check → UI refresh. For multi-intent inputs, this entire flow repeats for each decree in sequence.

#### Scenario: Complete decree cycle
- **WHEN** a valid decree is submitted
- **THEN** the backend returns a DecreeResponse containing: updated GameState (with history_log truncated to last 20), state delta with attribution map, AI narrative text, newly_triggered_events array, new game time, and game_over flag (null if game continues, or {result: "victory"|"defeat", message: string})

#### Scenario: Invalid decree rejection
- **WHEN** a decree fails precondition check
- **THEN** the system returns HTTP 422 with body {error_code: "precondition_failed", reason: string, ai_narrative: string (in-character rejection)} and game state remains unchanged

#### Scenario: Game over after decree
- **WHEN** a decree execution results in a game end condition being met
- **THEN** the response includes game_over field and the UI displays the end screen with the result message and final statistics

### Requirement: API contract
All API endpoints SHALL use snake_case field naming. Timestamps SHALL use ISO8601 format in UTC. Error responses SHALL use a unified structure: {error_code: string, message: string, details: object|null}. Successful responses return HTTP 200. Validation errors return HTTP 422. Server errors return HTTP 500.

#### Scenario: Unified error format
- **WHEN** any API endpoint encounters an error
- **THEN** the response body follows {error_code: "precondition_failed"|"parse_error"|"invalid_decree"|"save_not_found"|"internal_error", message: string, details: object|null}

### Requirement: Concurrency control
The backend SHALL use a simple mutex lock on the game state. Only one decree can be processed at a time. Concurrent requests SHALL receive HTTP 409 with error_code "decree_in_progress".

#### Scenario: Concurrent decree rejection
- **WHEN** a decree request arrives while another is being processed
- **THEN** the system returns HTTP 409 with {error_code: "decree_in_progress", message: "正在处理上一道政令，请稍候"}
