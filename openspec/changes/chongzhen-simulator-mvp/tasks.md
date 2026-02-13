## 1. Project Scaffolding

- [x] 1.1 Initialize Python backend project (FastAPI + uvicorn + SQLite dependencies, pydantic)
- [x] 1.2 Initialize React frontend project (Vite + TypeScript)
- [x] 1.3 Create project directory structure (backend: models/, engine/, ai/, api/, db/; frontend: components/, hooks/, types/, api/)
- [x] 1.4 Create one-click startup script (start.bat) that launches both frontend and backend
- [x] 1.5 Create .env.example with AI provider configuration (default: mock)

## 2. Game State Model (backend)

- [x] 2.1 Define GameState Pydantic model with all fields: time, resources, indicators, factions, regions, active_events, history_log, decree_count, event_cooldowns
- [x] 2.2 Define Faction model (satisfaction/influence/rebellion_risk 0~100) with initial values for 4 factions per spec
- [x] 2.3 Define Region model (stability 0~100, garrison>=0, control enum 朝廷/失控/沦陷, threat enum none/后金/民变/土司/海盗, tax_contribution low/medium/high) with initial values for 8 regions per spec
- [x] 2.4 Define StructuredDecree model (type enum of 8 types, target optional, sub_action optional, parameters optional)
- [x] 2.5 Define DecreeResponse model (updated state, delta attribution map, narrative, newly_triggered_events, game_time, game_over flag)
- [x] 2.6 Define unified error response model (error_code, message, details)
- [x] 2.7 Implement GameState factory function creating initial state (崇祯1年1月)
- [x] 2.8 Implement value clamping utility with floor() rounding (resources 0~200, indicators/faction/region 0~100)

## 3. Rule Engine (backend)

- [x] 3.1 Implement complete decree effect lookup table (8 types × 6 resource/indicator fields per spec table)
- [x] 3.2 Implement complete faction stance modifier matrix (4 factions × 8 decree types per spec table)
- [x] 3.3 Implement decree precondition check table (8 types with specific conditions per spec)
- [x] 3.4 Implement decree target validation matrix (disaster_relief→region, personnel→person+sub_action, diplomacy→后金/蒙古/朝鲜)
- [x] 3.5 Implement passive drift application (threat regions -3 stability, low treasury→military_morale -1, unstable regions→civil_morale -2, high rebellion→court_prestige -1)
- [x] 3.6 Implement decree base effect application function with delta attribution tracking
- [x] 3.7 Implement faction reaction calculation: floor(stance_modifier * influence/100) for satisfaction, floor(abs(sat_change) * 0.3) for rebellion_risk increase, floor(sat_change * 0.2) for decrease
- [x] 3.8 Implement region impact propagation (tax_increase 3-tier stability penalty, recruit_troops threat region bonus, etc. per spec)
- [x] 3.9 Implement region control state machine (朝廷→失控 at stability<10, 失控→沦陷 at stability=0, 失控→朝廷 at stability>30)
- [x] 3.10 Implement chain event detection with 5 defined events, cooldown tracking (3 months), max 1 detection round, sequential application
- [x] 3.11 Implement event lifecycle (6-month duration, urgency assignment by effect magnitude)
- [x] 3.12 Implement time progression (month +1, year rollover at month>12)
- [x] 3.13 Implement game end condition check (3 defeat conditions + 1 victory condition per spec)
- [x] 3.14 Integrate into process_decree(state, decree) -> DecreeResult with full delta attribution map

## 4. AI Narrative Layer (backend)

- [x] 4.1 Define AIProvider abstract interface (generate_narrative with delta_attribution input, parse_free_input returning list[StructuredDecree])
- [x] 4.2 Implement MockProvider deterministic template-based narrative generation (8 decree type templates with value substitution from attribution map)
- [x] 4.3 Implement MockProvider keyword-based free input parsing with negation detection (不要/别/勿/禁止) and multi-intent support
- [x] 4.4 Implement MockProvider in-character rejection narrative templates
- [x] 4.5 Create AI provider factory with config-based selection (env var AI_PROVIDER=mock|openai|claude|ollama)
- [x] 4.6 Implement provider failure fallback with 10s timeout and 3 retries (narrative: fallback text; parse: error message)
- [x] 4.7 Implement prompt injection defense (validate AI parse output against 8-type decree enum)

## 5. Save System (backend)

- [x] 5.1 Create SQLite database schema (saves table: id INTEGER PRIMARY KEY, name TEXT, game_time TEXT, created_at TEXT ISO8601 UTC, state_json TEXT)
- [x] 5.2 Implement save_game(state, name) with auto-generated name "崇祯X年X月-存档" if name is empty
- [x] 5.3 Implement load_game(save_id) with JSON deserialization error handling (return error_code "corrupt_save" on failure)
- [x] 5.4 Implement list_saves() sorted by created_at desc, max 20 entries
- [x] 5.5 Implement delete_save(save_id) with not-found handling (HTTP 404)
- [x] 5.6 Implement auto-save logic (every 5 decrees, non-blocking, failure does not block decree execution)
- [x] 5.7 Implement DB error handling (disk full/lock: return HTTP 500 with error_code "storage_error")

## 6. API Endpoints (backend)

- [x] 6.1 POST /api/game/new - Create new game, reset auto-save counter, return initial GameState
- [x] 6.2 POST /api/decree - Execute decree(s), return DecreeResponse with attribution map + narrative + game_over flag. Support sequential multi-decree execution
- [x] 6.3 POST /api/decree/parse - Parse free text into list[StructuredDecree] (parse only, no execution)
- [x] 6.4 GET /api/state - Get current GameState with history_log truncated to last 20 entries + total_count
- [x] 6.5 GET /api/history?offset=0&limit=20 - Paginated full history access
- [x] 6.6 POST /api/save - Save current game (optional body: {name: string})
- [x] 6.7 GET /api/saves - List all saves
- [x] 6.8 POST /api/load/{save_id} - Load a save
- [x] 6.9 DELETE /api/save/{save_id} - Delete a save
- [x] 6.10 Configure CORS middleware (allow localhost:5173 in dev)
- [x] 6.11 Implement mutex lock middleware for decree endpoints (HTTP 409 on concurrent requests)

## 7. Frontend - Layout & Components

- [x] 7.1 Create main game layout (4-zone CSS grid: top resource bar, center-left map 70%, center-right faction panel 30%, bottom event+action area)
- [x] 7.2 Implement ResourceBar component (treasury/population/military_supply/civil_morale/military_morale/court_prestige + 崇祯N年N月 display, colored progress bars)
- [x] 7.3 Implement RegionMap component (8 clickable blocks in geographic layout, color-coded: green stability>60, yellow 30~60, red <30, with control/threat indicators)
- [x] 7.4 Implement FactionPanel component (4 factions with satisfaction/influence bars, rebellion_risk>60 red highlight, rebellion_risk>80 flashing warning)
- [x] 7.5 Implement EventBar component (recent 5 events, urgency color: 高=red, 中=yellow, 低=gray, click to expand narrative)
- [x] 7.6 Implement ActionArea component (8 decree buttons in 2x4 grid with disabled state + tooltip, text input + submit button)
- [x] 7.7 Implement target selection dialogs (region picker for disaster_relief, person input for personnel, target picker for diplomacy)
- [x] 7.8 Implement NarrativeModal (AI narrative text + state change summary with attribution breakdown)
- [x] 7.9 Implement GameOverScreen (victory/defeat message + final statistics + new game button)
- [x] 7.10 Implement multi-intent confirmation dialog ("将依次执行：1.X 2.Y，确认？")

## 8. Frontend - State & API Integration

- [x] 8.1 Create TypeScript type definitions matching all backend models (GameState, Faction, Region, StructuredDecree, DecreeResponse, DeltaAttribution, ErrorResponse, etc.)
- [x] 8.2 Create API client module (fetch wrapper for all endpoints with unified error handling)
- [x] 8.3 Implement game state management (zustand store with GameState + loading/error states)
- [x] 8.4 Wire simple decree buttons to POST /api/decree, update store on response, handle disabled state from preconditions
- [x] 8.5 Wire target-required buttons to open selection dialog → POST /api/decree with target
- [x] 8.6 Wire free text input to POST /api/decree/parse → confirmation (if multi) → sequential POST /api/decree
- [x] 8.7 Implement resource bar animation (CSS transition 500ms, green for increase, red for decrease)
- [x] 8.8 Implement region click tooltip/popover (garrison, tax_contribution, threats, recent events)
- [x] 8.9 Implement save/load UI panel (save list, save button, load with unsaved progress warning, delete with confirmation)
- [x] 8.10 Implement game over flow (detect game_over in response → show GameOverScreen)
- [x] 8.11 Implement new game flow (with unsaved progress warning)

## 9. Integration & Polish

- [x] 9.1 End-to-end test: new game → decree → verify state update + attribution map → verify narrative display
- [x] 9.2 End-to-end test: save game → load game → verify state restoration
- [x] 9.3 End-to-end test: free text single intent → parse → execute → verify
- [x] 9.4 End-to-end test: free text multi-intent → parse → confirm → sequential execute → verify time advancement
- [x] 9.5 End-to-end test: game over conditions (defeat by prestige=0, defeat by all regions 沦陷, victory)
- [x] 9.6 End-to-end test: passive drift effects visible in attribution map
- [x] 9.7 Implement loading state (disable all controls during decree processing, show spinner)
- [x] 9.8 Implement error handling for API failures (network error toast, retry button, HTTP 409 handling)
- [x] 9.9 Verify 30-minute continuous play stability (no memory leaks, no state corruption, history_log pagination working)
