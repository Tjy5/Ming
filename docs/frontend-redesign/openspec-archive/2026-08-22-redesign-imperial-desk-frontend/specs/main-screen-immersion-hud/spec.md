> Final scope: this archived change validates desktop governance HUD behavior at 1024x768, 1440x900, and 1920x1080. Mobile/touch-specific behavior remains in the existing or future dedicated scope.

## ADDED Requirements

### Requirement: HUD Visual Priority and Layer Restraint
The governance HUD SHALL maintain a stable priority from urgent state and active command, through selected region and current values, to reference labels and decoration, and MUST avoid simultaneous treatments that make those levels visually indistinguishable.

#### Scenario: Idle governance map
- **WHEN** no crisis, value transition, or direct player feedback is active
- **THEN** the resource bar, map, command rail, inspector, and bottom HUD use static states and no decorative layer repeatedly demands attention

#### Scenario: Active command surface
- **WHEN** a map, court, inspector, resource-detail, or edict surface opens
- **THEN** its opener and panel receive clear active priority while inactive controls, texture, and historical ornament recede without becoming unavailable

#### Scenario: Multiple urgent states
- **WHEN** more than one resource or region requires attention
- **THEN** the HUD communicates each urgent state without stacking continuous animations, obscuring labels, or displacing stable command targets

### Requirement: Inspector and HUD Reading Space
The governance HUD MUST allocate non-competing reading space for the region inspector, active rail surface, resource detail, and bottom command area so the highest-priority open surface remains operable.

#### Scenario: Region inspector beside bottom HUD
- **WHEN** a region inspector is open while the bottom command HUD is available
- **THEN** the inspector's title, key values, close control, and available region action are not covered by the HUD

#### Scenario: Rail panel replaces competing surface
- **WHEN** a rail surface opens while another mutually exclusive rail surface is active
- **THEN** the previous rail surface closes and the new panel uses the reserved reading area rather than layering two full panels over the map

## MODIFIED Requirements

### Requirement: 响应式无重叠验收 (Responsive Non-overlap)
HUD SHALL 在 1440x900、1024x768 和 1920x1080 视口保持可操作、无不受控重叠、无页面级横向溢出，并支持键盘-only 与 reduced-motion。

#### Scenario: 固定视口视觉验收
- **WHEN** 在任一规定桌面视口依次打开资源菜单、地图 surface、朝廷抽屉、地区检查器和草诏台
- **THEN** 当前主要内容、关闭控件和至少一条后续操作路径保持可见且可交互，动态内容不得改变导轨或按钮的稳定尺寸

#### Scenario: 检查器与 HUD 共存验收
- **WHEN** 在任一规定视口打开地区检查器并保留当前可用的导轨与底部命令区
- **THEN** 检查器标题、关键数值、关闭入口和至少一项地区后续操作不被遮挡，页面不产生横向溢出

#### Scenario: 文字缩放验收
- **WHEN** 浏览器文本缩放达到 200%
- **THEN** 关键国力值、紧急状态、当前 surface 标题和关闭入口仍可读取与操作，允许受控换行或局部滚动但不得裁切唯一操作路径
