# Desktop Imperial Desk Redesign

This document is the Git-tracked handoff for the archived OpenSpec change
`redesign-imperial-desk-frontend`.

## Scope

The delivered change applies the `design-taste-frontend` direction to the
desktop game experience: an imperial-desk / central-archive visual system with
paper map surfaces, an ink framework, cinnabar actions, restrained gold and
teal support states, and clearer command hierarchy.

Accepted desktop reference viewports:

- 1024x768
- 1440x900
- 1920x1080

Mobile/tablet layout, touch-equivalent controls, software-keyboard behavior,
the five-viewport mobile-inclusive matrix, and full legacy stylesheet cleanup
are explicitly deferred to a future change.

## Traceability

- Baseline: `bccd72e` (`chore: checkpoint current work before frontend redesign`)
- Implementation: `ba3adcc` (`feat(frontend): redesign the imperial desk experience`)
- Desktop coverage: `de57889` (`test(frontend): cover compact desktop viewport`)
- OpenSpec archive: `openspec/changes/archive/2026-08-22-redesign-imperial-desk-frontend`

The OpenSpec planning root is maintained at the workspace level outside this
Git checkout. The archive path above is the canonical local planning record;
this file keeps the scope and rollback references in the code repository.

## Verification

- `npm run lint` passed.
- `npm run build` passed.
- `npm run test -- --maxWorkers=1` passed: 27 files, 153 tests.
- Deterministic desktop visual capture passed at all three accepted viewports.
- Real desktop chat submission returned an assistant response.
- Browser checks found no page-level overflow or console errors in captured
  governance states.
- Route, shortcut, label, map SVG, Zustand, API/SSE, and overlay contracts
  were audited and preserved.

Visual evidence was captured under the workspace task directory:
`.trellis/tasks/redesign-imperial-desk-frontend/research/`.
