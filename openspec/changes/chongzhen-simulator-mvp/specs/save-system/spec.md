## ADDED Requirements

### Requirement: Save game state
The system SHALL save the complete GameState to SQLite as a serialized JSON blob with metadata: save_id (auto-increment), save_name (user-provided or auto-generated), game_time (崇祯N年N月), created_at (real timestamp), and the full GameState JSON.

#### Scenario: Manual save
- **WHEN** player clicks "存档" button
- **THEN** the current GameState is persisted to SQLite with an auto-generated name "崇祯X年X月-存档" and the save appears in the save list

#### Scenario: Auto-save
- **WHEN** every 5 decrees are executed
- **THEN** the system automatically saves with name "自动存档-崇祯X年X月"

### Requirement: Load game state
The system SHALL restore a complete GameState from a saved record, replacing the current in-memory state entirely.

#### Scenario: Load from save list
- **WHEN** player selects a save from the save list and clicks "读档"
- **THEN** the GameState is restored to the saved state, UI updates to reflect all values, and game time resets to the saved time

#### Scenario: Load confirmation
- **WHEN** player attempts to load while current game has unsaved progress
- **THEN** the system SHALL prompt "当前进度未保存，确认读档？" with confirm/cancel options

### Requirement: Save list management
The system SHALL display a list of all saves sorted by created_at descending. Maximum 20 saves; when limit is reached, the oldest non-auto-save is highlighted for deletion.

#### Scenario: Save list display
- **WHEN** player opens the save/load panel
- **THEN** all saves are listed with: save_name, game_time, created_at, and a delete button

#### Scenario: Delete save
- **WHEN** player clicks delete on a save entry
- **THEN** the save is permanently removed from SQLite after confirmation

### Requirement: New game
The system SHALL provide a "新游戏" option that creates a fresh GameState with all initial values and clears the current session.

#### Scenario: New game with existing progress
- **WHEN** player clicks "新游戏" while a game is in progress
- **THEN** the system prompts "是否保存当前进度？" with save/discard/cancel options

### Requirement: Save/Load round-trip fidelity
The save/load system SHALL guarantee exact state restoration. load(save(state)) SHALL produce a GameState that is field-by-field identical to the original state, including: all numeric values, faction order, region order, active_events, history_log entries, event_cooldowns, and decree_count.

#### Scenario: Round-trip with boundary values
- **WHEN** a GameState with treasury=0, civil_morale=100, 陕西 stability=0 (control=沦陷), and 3 active events is saved and loaded
- **THEN** the loaded state is identical to the saved state on all fields

#### Scenario: Round-trip with large history
- **WHEN** a GameState with 200 history_log entries is saved and loaded
- **THEN** all 200 entries are preserved with identical content

#### Scenario: Double load idempotency
- **WHEN** the same save is loaded twice consecutively
- **THEN** the in-memory GameState after both loads is identical
