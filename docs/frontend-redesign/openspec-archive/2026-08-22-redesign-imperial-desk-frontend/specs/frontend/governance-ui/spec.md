> Final scope: this change validates governance hierarchy and operation at desktop widths of 1024px and above, with captured evidence at 1024x768, 1440x900, and 1920x1080.

## MODIFIED Requirements

### Requirement: Top Resource Bar Display
The frontend SHALL display all 8 core national metrics with trend indicators, group them as fiscal, livelihood, military, and prestige, keep every existing tool action reachable without viewport overflow, and visually prioritize current values and urgent state over secondary labels and decoration.

#### Scenario: Metric trend visualization
- **WHEN** turn settlement produces state deltas
- **THEN** `ResourceBar` displays updated values with visual trend indicators (up/down/stable)

#### Scenario: Grouped desktop layout
- **WHEN** the governance viewport is at least 1024px wide
- **THEN** the 56px bar displays the four metric groups, calendar, urgent badges, and tool entry points without overlap

#### Scenario: Secondary tool menu
- **WHEN** the player opens the palace settings menu
- **THEN** save, load, fallback, continuity, AI settings, guide, and new-game actions remain reachable while dialogue, TRPG, and urgent memorial actions retain direct entry points

#### Scenario: Readable metric hierarchy
- **WHEN** all metric groups and tool entries are visible at default browser zoom
- **THEN** each metric's name, value, trend, urgent state, and group relationship remain identifiable without requiring hover and no essential text is rendered below 12 CSS pixels

### Requirement: Interactive Region Map and Inspector
The frontend MUST render an SVG map showing regional control, threats, stability, crisis state, and existing aggregated governance metrics with hover/focus preview and clickable inspection while keeping decorative layers subordinate to labels, current state, and active controls.

#### Scenario: Region selection and inspector
- **WHEN** a player clicks a region or governance division on the map
- **THEN** `RegionInspector` opens, its title and primary details remain readable beside the active HUD, and focus returns to the SVG trigger upon closing

#### Scenario: Region hover or focus preview
- **WHEN** a governable division receives mouse hover or keyboard focus
- **THEN** a viewport-bounded tooltip displays existing aggregated control, stability, civil morale, garrison, rebellion risk, and disaster level, plus the first non-none threat in canonical source-region order, without requiring a governor field

#### Scenario: Crisis threshold visualization
- **WHEN** aggregated `rebellion_risk > 50` or `disaster_level > 50`
- **THEN** the division displays a crisis warning with a static equivalent when reduced motion is enabled

#### Scenario: Competing map layers
- **WHEN** region fills, historical boundaries, texture, labels, crisis state, hover state, and a selected region are visible together
- **THEN** the selected or focused region and its label have a clear visual priority and decorative layers do not obscure interactive boundaries or accessible text contrast

#### Scenario: Inspector and command surface coexistence
- **WHEN** the region inspector is open at any reference viewport supported by the governance HUD
- **THEN** its close control, key regional values, and at least one subsequent governance action remain reachable without uncontrolled overlap with the command rail or bottom HUD
