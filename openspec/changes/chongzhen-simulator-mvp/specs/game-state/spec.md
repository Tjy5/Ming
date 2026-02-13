## ADDED Requirements

### Requirement: Game state data model
The system SHALL maintain a GameState object containing: time (year, month), resources (treasury, population, military_supply), global indicators (civil_morale, military_morale, court_prestige), factions array, regions array, active_events array, and history_log array. All numeric fields SHALL be integers within defined bounds.

#### Scenario: Initial state creation
- **WHEN** a new game is started
- **THEN** the system creates a GameState with time set to 崇祯1年1月, treasury=100, population=100, military_supply=80, civil_morale=60, military_morale=70, court_prestige=75

#### Scenario: Resource bounds enforcement
- **WHEN** any resource or indicator value is calculated
- **THEN** the value SHALL be clamped to its defined range (resources: 0~200, indicators: 0~100). All intermediate calculations SHALL use floor() rounding before clamping. Clamping is applied as the final step after all modifiers

### Requirement: Faction model
The system SHALL define exactly 4 factions: 东林党 (initial satisfaction=72, influence=65, rebellion_risk=5), 阉党残余 (satisfaction=30, influence=25, rebellion_risk=15), 勋贵集团 (satisfaction=55, influence=40, rebellion_risk=8), 边将势力 (satisfaction=61, influence=50, rebellion_risk=12). Each faction has satisfaction (0~100), influence (0~100), rebellion_risk (0~100).

#### Scenario: Faction state initialization
- **WHEN** a new game is started
- **THEN** all 4 factions are created with their defined initial values

#### Scenario: Rebellion risk threshold
- **WHEN** a faction's rebellion_risk exceeds 80
- **THEN** the system SHALL flag that faction as "叛乱预警" in the active_events

### Requirement: Region model
The system SHALL define 8 regions: 京畿 (stability=80, garrison=50000, threat=none, tax_contribution=medium), 辽东 (stability=40, garrison=30000, threat=后金, tax_contribution=low), 陕西 (stability=25, garrison=5000, threat=民变, tax_contribution=low), 江南 (stability=85, garrison=10000, tax_contribution=high, threat=none), 中原 (stability=60, garrison=15000, threat=none, tax_contribution=medium), 山东 (stability=70, garrison=12000, threat=none, tax_contribution=medium), 云贵 (stability=50, garrison=8000, threat=土司, tax_contribution=low), 川蜀 (stability=65, garrison=10000, threat=none, tax_contribution=medium). Each region has stability (0~100), garrison (integer >= 0), control (朝廷/失控/沦陷), threat (enum: none/后金/民变/土司/海盗), tax_contribution (low/medium/high).

#### Scenario: Region initialization
- **WHEN** a new game is started
- **THEN** all 8 regions are created with defined initial values, all controlled by 朝廷

#### Scenario: Region loss of control
- **WHEN** a region's stability drops to 0 (strictly equal to 0)
- **THEN** the region's control SHALL change from 失控 to 沦陷

#### Scenario: Region becomes unstable
- **WHEN** a region's stability drops below 10 (stability < 10) and control is 朝廷
- **THEN** the region's control SHALL change to 失控

#### Scenario: Region recovery
- **WHEN** a region's stability rises above 30 (stability > 30) and control is 失控
- **THEN** the region's control SHALL change back to 朝廷

### Requirement: Game end conditions
The game SHALL end when any of the following conditions are met. Defeat: all 8 regions have control=沦陷, OR court_prestige reaches 0, OR game time reaches 崇祯17年3月 (March 1644). Victory: all regions have control=朝廷 AND no faction has rebellion_risk > 20 AND court_prestige > 80.

#### Scenario: Defeat by total collapse
- **WHEN** after a decree, all 8 regions have control=沦陷
- **THEN** the game ends with defeat message "社稷倾覆，大明亡矣"

#### Scenario: Defeat by prestige loss
- **WHEN** court_prestige reaches 0
- **THEN** the game ends with defeat message "天子威严尽失，朝纲崩坏"

#### Scenario: Defeat by historical deadline
- **WHEN** game time reaches 崇祯17年3月
- **THEN** the game ends with defeat message "甲申之变，历史重演"

#### Scenario: Victory
- **WHEN** all regions control=朝廷 AND all factions rebellion_risk <= 20 AND court_prestige > 80
- **THEN** the game ends with victory message "中兴大明，力挽狂澜"

### Requirement: Passive monthly drift
Each month (each decree execution), before applying decree effects, the system SHALL apply passive drift to the GameState. Drift rules: regions with threat != none have stability drift of -3/month; military_morale drifts -1/month if treasury < 50; civil_morale drifts -2/month if any region has stability < 20; court_prestige drifts -1/month if any faction rebellion_risk > 60.

#### Scenario: Threatened region drift
- **WHEN** a new month begins and 辽东 has threat=后金
- **THEN** 辽东 stability decreases by 3 before decree effects are applied

#### Scenario: Low treasury military morale drift
- **WHEN** a new month begins and treasury=30 (< 50)
- **THEN** military_morale decreases by 1 before decree effects are applied

### Requirement: History log pagination
The history_log SHALL grow unbounded in storage, but API responses SHALL return only the most recent 20 entries. A separate endpoint SHALL provide paginated access to full history.

#### Scenario: API response truncation
- **WHEN** GET /api/state is called and history_log has 100 entries
- **THEN** the response includes only the 20 most recent entries with a total_count=100 field

### Requirement: Time progression
The system SHALL track game time as year (崇祯N年) and month (1~12). Each decree execution advances time by 1 month. When month exceeds 12, year increments and month resets to 1.

#### Scenario: Month advancement
- **WHEN** a decree is executed in 崇祯1年12月
- **THEN** time advances to 崇祯2年1月

### Requirement: History log
The system SHALL append every decree and its resulting state changes to the history_log array. Each entry contains: timestamp (game time), decree description, state delta (before/after values), and AI narrative text.

#### Scenario: History recording
- **WHEN** a decree is executed
- **THEN** a history entry is appended with the decree details, all numeric changes, and the AI narrative
