## ADDED Requirements

### Requirement: Decree type enumeration
The rule engine SHALL support exactly 8 decree types: tax_increase (加税), tax_decrease (减税), recruit_troops (增兵), disband_troops (裁兵), personnel (任免, covers both appoint and dismiss), diplomacy (外交), disaster_relief (赈灾), harsh_punishment (严刑). The "personnel" type uses a sub-action field (appoint/dismiss) to distinguish.

#### Scenario: Personnel decree with sub-action
- **WHEN** a decree of type "personnel" with sub_action="dismiss" and target="袁崇焕" is submitted
- **THEN** the engine processes it as a dismissal with the personnel effect table entry

### Requirement: Complete decree effect table
The rule engine SHALL maintain the following base effect table (all values are integers):

| Decree Type | Treasury | Population | Military Supply | Civil Morale | Military Morale | Court Prestige |
|---|---|---|---|---|---|---|
| tax_increase | +15 | 0 | 0 | -8 | 0 | 0 |
| tax_decrease | -10 | 0 | 0 | +6 | 0 | -3 |
| recruit_troops | -20 | -5 | +15 | -3 | +8 | 0 |
| disband_troops | +5 | +3 | -10 | +2 | -10 | -5 |
| personnel | -5 | 0 | 0 | 0 | 0 | +5 |
| diplomacy | -10 | 0 | 0 | 0 | +3 | +8 |
| disaster_relief | -30 | +5 | 0 | +12 | 0 | +5 |
| harsh_punishment | 0 | -3 | 0 | -10 | +5 | +3 |

#### Scenario: Tax increase base effects
- **WHEN** decree "tax_increase" is submitted
- **THEN** the engine applies: treasury +15, civil_morale -8

#### Scenario: Disaster relief base effects
- **WHEN** decree "disaster_relief" is submitted
- **THEN** the engine applies: treasury -30, population +5, civil_morale +12, court_prestige +5

#### Scenario: Unknown decree type rejection
- **WHEN** a decree type not in the 8-type enumeration is submitted
- **THEN** the engine SHALL reject it with error "未知政令类型"

### Requirement: Decree preconditions
Each decree type SHALL have preconditions that MUST be satisfied before execution. If preconditions fail, the decree is rejected and game state remains unchanged.

| Decree Type | Precondition |
|---|---|
| tax_increase | civil_morale > 10 |
| tax_decrease | treasury > 20 |
| recruit_troops | treasury >= 20 AND population >= 10 |
| disband_troops | military_supply > 10 |
| personnel | court_prestige > 10 |
| diplomacy | treasury >= 10 |
| disaster_relief | treasury >= 30 |
| harsh_punishment | court_prestige > 5 |

#### Scenario: Precondition failure
- **WHEN** decree "disaster_relief" is submitted and treasury=20 (< 30)
- **THEN** the engine rejects with error "国库不足，无法赈灾（需要钱粮≥30，当前20）"

### Requirement: Decree target matrix
Decrees that require a target region or person SHALL be defined as follows: disaster_relief (requires target region), personnel (requires target person name and sub_action), diplomacy (requires target: one of 后金/蒙古/朝鲜). All other decree types have no target requirement.

#### Scenario: Missing required target
- **WHEN** decree "disaster_relief" is submitted without a target region
- **THEN** the engine rejects with error "赈灾需要指定目标区域"

### Requirement: Complete faction stance modifier table
The rule engine SHALL use the following stance modifier matrix (integer values):

| Faction | tax_increase | tax_decrease | recruit_troops | disband_troops | personnel | diplomacy | disaster_relief | harsh_punishment |
|---|---|---|---|---|---|---|---|---|
| 东林党 | -12 | +8 | -5 | +3 | +6 | +4 | +10 | -15 |
| 阉党残余 | +5 | -8 | +3 | -3 | -8 | -5 | -3 | +12 |
| 勋贵集团 | -3 | +5 | -8 | +8 | +3 | +6 | +2 | -5 |
| 边将势力 | +3 | -5 | +10 | -12 | -3 | +8 | 0 | +5 |

#### Scenario: Faction reaction calculation
- **WHEN** decree "tax_increase" is executed
- **THEN** 东林党 satisfaction changes by floor(-12 * 65/100) = floor(-7.8) = -8; rebellion_risk changes by floor(abs(-8) * 0.3) = floor(2.4) = +2

#### Scenario: Positive faction reaction
- **WHEN** decree "disaster_relief" is executed
- **THEN** 东林党 satisfaction changes by floor(10 * 65/100) = floor(6.5) = +6; rebellion_risk changes by floor(-6 * 0.2) = floor(-1.2) = -2

#### Scenario: Zero satisfaction change
- **WHEN** a faction's stance_modifier is 0 for the executed decree type
- **THEN** that faction's satisfaction and rebellion_risk remain unchanged

### Requirement: Region impact propagation
The rule engine SHALL propagate decree effects to regions based on the following rules:

For tax_increase: regions with stability < 30 get stability -15; regions with 30 <= stability < 60 get stability -8; regions with stability >= 60 get stability -5.
For tax_decrease: all regions get stability +3.
For recruit_troops: regions with threat != none get stability +5, garrison +2000.
For disband_troops: regions with garrison > 10000 get garrison -3000.
For disaster_relief: target region gets stability +20 (in addition to base effects).
For harsh_punishment: regions with stability < 40 get stability -8; regions with stability >= 60 get stability +3.
For personnel/diplomacy: no direct region impact.

#### Scenario: Tax increase on unstable region
- **WHEN** decree "tax_increase" is executed and 陕西 has stability=25 (< 30)
- **THEN** 陕西 stability decreases by 15

#### Scenario: Tax increase on stable region
- **WHEN** decree "tax_increase" is executed and 江南 has stability=85 (>= 60)
- **THEN** 江南 stability decreases by 5

#### Scenario: Tax increase on mid-stability region
- **WHEN** decree "tax_increase" is executed and 中原 has stability=45 (30 <= x < 60)
- **THEN** 中原 stability decreases by 8

### Requirement: Chain event detection rules
The rule engine SHALL check chain event triggers ONCE after applying all decree effects and passive drift. Chain events do NOT trigger further chain events (max 1 detection round per decree). Multiple chain events MAY trigger in the same round. Chain events have a cooldown of 3 months (same event cannot trigger again within 3 months of last trigger).

Chain event definitions:
1. "流寇势力扩大": trigger when 陕西 stability < 20 AND civil_morale < 40. Effects: 中原 stability -10, 陕西 stability -5.
2. "边军哗变": trigger when military_morale < 25 AND treasury < 20. Effects: 辽东 stability -20, 边将势力 rebellion_risk +25.
3. "朝堂危机": trigger when any faction rebellion_risk > 80 AND court_prestige < 30. Effects: court_prestige -15, all factions rebellion_risk +10.
4. "江南税变": trigger when treasury < 10 AND 江南 stability > 50. Effects: 江南 stability -15, treasury +10 (emergency levy).
5. "后金入寇": trigger when 辽东 stability < 15 AND military_supply < 30. Effects: 辽东 stability -20, 京畿 stability -10, military_morale -15.

#### Scenario: Chain event cooldown
- **WHEN** "流寇势力扩大" triggered in 崇祯2年3月 and conditions are still met in 崇祯2年4月
- **THEN** the event does NOT trigger again (cooldown until 崇祯2年6月)

#### Scenario: Multiple chain events same round
- **WHEN** after decree processing, both "流寇势力扩大" and "边军哗变" conditions are met
- **THEN** both events trigger and their effects are applied sequentially (流寇 first, then 边军)

#### Scenario: No recursive chain events
- **WHEN** chain event "朝堂危机" increases all rebellion_risk by +10, causing another faction to exceed 80
- **THEN** no additional chain event detection occurs this round

### Requirement: Delta attribution map
The rule engine SHALL return a delta attribution map alongside the total state delta. The attribution map breaks down each numeric change by source: base_effect, faction_reaction, region_impact, chain_event, passive_drift. This enables the AI to generate accurate causal narratives.

#### Scenario: Attribution map structure
- **WHEN** decree "tax_increase" is processed
- **THEN** the attribution map includes entries like {treasury: {base_effect: +15}, civil_morale: {base_effect: -8}, 陕西_stability: {region_impact: -15}, 东林党_satisfaction: {faction_reaction: -8}}

### Requirement: Passive drift application
Before applying decree effects each month, the rule engine SHALL apply passive drift rules: regions with threat != none get stability -3; military_morale -1 if treasury < 50; civil_morale -2 if any region stability < 20; court_prestige -1 if any faction rebellion_risk > 60. Drift is applied before decree effects and included in the delta attribution map under "passive_drift".

#### Scenario: Passive drift before decree
- **WHEN** decree is submitted and 辽东 has threat=后金 and treasury=30
- **THEN** before decree effects: 辽东 stability -3 (threat drift), military_morale -1 (low treasury drift)

### Requirement: Deterministic computation
The rule engine SHALL produce identical output given identical input state and decree. No randomness in core calculations. All formulas SHALL be pure functions of input state. All intermediate calculations use floor() rounding. Clamping (0~100 or 0~200) is applied as the final step.

#### Scenario: Reproducibility
- **WHEN** the same decree is applied to the same GameState twice
- **THEN** the resulting state delta SHALL be byte-identical both times

### Requirement: Event lifecycle
Active events SHALL have a duration of 6 months. After 6 months, events are automatically removed from active_events. Events have an urgency level determined by: 高 if triggered by chain event with any effect magnitude > 15; 中 if effect magnitude 5~15; 低 otherwise.

#### Scenario: Event expiration
- **WHEN** event "流寇势力扩大" was triggered in 崇祯2年3月 and current time is 崇祯2年9月
- **THEN** the event is removed from active_events

#### Scenario: Event urgency assignment
- **WHEN** chain event "后金入寇" triggers with effect 辽东 stability -20 (magnitude > 15)
- **THEN** the event urgency is set to 高

### Requirement: Property-Based Testing invariants
The rule engine implementation SHALL satisfy the following invariants, verifiable through property-based testing:

**Bounds invariants:**
- All resource fields (treasury, population, military_supply) SHALL remain in [0, 200] after any operation
- All indicator fields (civil_morale, military_morale, court_prestige) SHALL remain in [0, 100] after any operation
- All faction fields (satisfaction, influence, rebellion_risk) SHALL remain in [0, 100] after any operation
- All region stability fields SHALL remain in [0, 100] after any operation
- All garrison fields SHALL remain >= 0 after any operation
- Game month SHALL remain in [1, 12] after any time progression
- Faction count SHALL always equal 4; region count SHALL always equal 8

**Determinism invariants:**
- process_decree(state, decree) called twice with identical inputs SHALL produce byte-identical outputs
- clamp(clamp(x)) == clamp(x) for all numeric fields
- Region control state machine applied twice to same input SHALL produce same output

**Monotonicity invariants:**
- Game time SHALL strictly increase by 1 month per successful decree execution
- History log length SHALL be non-decreasing (append-only, failed decrees do not append)
- Chain event cooldown remaining months SHALL monotonically decrease until 0

**Order invariants (explicitly non-commutative):**
- Pipeline order is fixed: passive_drift → base_effect → faction_reaction → region_impact → chain_event → clamp → game_end_check
- Multiple chain events in same round SHALL apply in defined order (流寇→边军→朝堂→江南→后金)
- Decree sequence A;B is NOT guaranteed equal to B;A (order-dependent)

**Round-trip invariants:**
- JSON serialize(deserialize(GameState)) == GameState (save/load fidelity)
- History delta: before_state + delta == after_state (under floor+clamp rules)

**Idempotency invariants:**
- Game end check on same state SHALL always return same result
- Load(save_id) called twice SHALL produce identical in-memory state

#### Scenario: Bounds stress test
- **WHEN** 100 consecutive tax_increase decrees are applied to a fresh game state
- **THEN** all numeric fields remain within their defined bounds after every single decree

#### Scenario: Determinism verification
- **WHEN** process_decree is called 10 times with the same initial state and same decree
- **THEN** all 10 results are byte-identical

#### Scenario: Time monotonicity across year boundary
- **WHEN** decrees are executed from 崇祯1年10月 through 崇祯2年3月
- **THEN** time sequence is strictly: 1年10月, 1年11月, 1年12月, 2年1月, 2年2月, 2年3月
