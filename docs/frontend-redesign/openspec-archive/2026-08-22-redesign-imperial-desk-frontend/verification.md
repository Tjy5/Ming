# Desktop Verification Record

## Scope

This change is closed as a desktop-game visual redesign. The accepted reference viewports are 1024x768, 1440x900, and 1920x1080. Mobile/tablet layout, touch-equivalent controls, software-keyboard behavior, and the broader five-viewport matrix are deferred to a future change.

## Implementation

- `ba3adcc` — `feat(frontend): redesign the imperial desk experience`
- `de57889` — `test(frontend): cover compact desktop viewport`
- Rollback baseline: `bccd72e`

## Checks

- `npm run lint` passed.
- `npm run build` passed.
- `npm run test -- --maxWorkers=1` passed: 27 files, 153 tests.
- Deterministic desktop visual capture passed at 1024x768, 1440x900, and 1920x1080.
- Real desktop chat submission produced an assistant response.
- Browser checks found no page-level overflow or console errors in the captured governance states.
- Compatibility audit confirmed route, shortcut, label, map SVG, Zustand, API/SSE, and overlay contracts were preserved.

## Evidence

Visual evidence is stored under `.trellis/tasks/redesign-imperial-desk-frontend/research/`:

- `baseline-1024x768-after.png`
- `baseline-1440x900-before.png`
- `baseline-1440x900-after.png`
- `baseline-1920x1080-before.png`
- `baseline-1920x1080-after.png`

## Accepted Follow-up

The compatibility-first stylesheet layer remains intentionally centralized in `frontend/src/styles/imperial-redesign.css`. Full legacy stylesheet decomposition, dead-code cleanup, mobile/tablet composition, and additional state baselines are separate follow-up work.
