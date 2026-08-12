import { test, expect } from '@playwright/test'

test.describe('public lifecycle continuity @continuity', () => {
  test('diverge → remove roster → vacuum → successor → govern → save/load', async ({ page }, testInfo) => {
    test.skip(process.env.MING_E2E_MODE !== 'offline', 'deterministic lifecycle fixture only')

    const evidence = {
      scenario: 'diverge-remove-roster-vacuum-successor-govern-save-load',
      project: testInfo.project.name,
      steps: [],
    }
    const api = async (path, init = {}) => {
      const response = await page.request.fetch(`http://127.0.0.1:8000/api${path}`, init)
      const body = await response.json().catch(() => null)
      if (!response.ok()) {
        throw new Error(`${init.method || 'GET'} ${path}: ${body?.detail?.error_code || response.status()}`)
      }
      return body
    }
    const action = async (state, rawText, actionKind = 'free_action') => api('/actions', {
      method: 'POST',
      data: {
        schema_version: 1,
        game_id: state.world_metadata.game_id,
        branch_id: state.world_metadata.branch_id,
        expected_parent_version_id: state.world_metadata.version_id,
        client_action_id: crypto.randomUUID(),
        raw_text: rawText,
        action_kind: actionKind,
        mode: state.phase,
      },
    })

    await page.goto('/')
    const initial = await api('/game/new', { method: 'POST' })
    expect(initial.world_metadata.game_id).toBeTruthy()
    expect(initial.world_metadata.version_id).toBeTruthy()
    evidence.steps.push({ name: 'new_game', version_id: initial.world_metadata.version_id })

    // Historical divergence is a normal intent, not a route-specific branch.
    const diverged = await action(initial, '拒绝旧朝称号，在河港建立不依赖旧势力的商路')
    expect(diverged.result.facts.settlement_id).toBeTruthy()
    expect(diverged.result.version.parent_version_id).toBe(initial.world_metadata.version_id)
    evidence.steps.push({
      name: 'historical_divergence',
      settlement_id: diverged.result.facts.settlement_id,
      version_id: diverged.result.version.version_id,
    })

    // A pre-vacuum bookmark is the recovery point used after the roster is
    // removed; manual save is a protected version bookmark, not a legacy copy.
    const save = await api('/save', {
      method: 'POST',
      data: { name: '偏史分歧恢复点' },
    })
    expect(save.bookmark.version_id).toBe(diverged.result.version.version_id)
    evidence.steps.push({ name: 'bookmark', bookmark_id: save.bookmark.bookmark_id })

    let state = diverged.state
    // The roster contract treats currently present (idle/active) actors as
    // the governance roster; future/not-yet-entered historical records are
    // not candidates and must not be interpreted as surviving successors.
    const activeMinisters = state.ministers.filter((minister) => (
      minister.status !== 'removed'
      && minister.status !== 'not_yet_entered'
      // The legacy freeform compatibility parser accepts a 2–4 character
      // person token; longer historical names are outside this fixture's
      // public removal command and remain untouched by design.
      && minister.name.length <= 4
    ))
    const predefinedMinisterNames = activeMinisters.map((minister) => minister.name)
    expect(activeMinisters.length).toBeGreaterThan(0)
    for (const minister of activeMinisters) {
      const response = await api('/decree', {
        method: 'POST',
        data: { free_text: `斩杀${minister.name}` },
      })
      state = response.state
      // Decree preconditions are monthly gameplay rules.  Advancing through
      // the same public clock endpoint keeps each removal a real settlement
      // instead of bypassing the policy guard with test-only state writes.
      const advanced = await api('/advance-month', { method: 'POST' })
      state = advanced.state
    }
    for (const minister of state.ministers.filter((candidate) => predefinedMinisterNames.includes(candidate.name) && candidate.status !== 'removed')) {
      const response = await api('/decree', { method: 'POST', data: { free_text: `斩杀${minister.name}` } })
      state = response.state
      state = (await api('/advance-month', { method: 'POST' })).state
    }
    expect(predefinedMinisterNames.every((name) => {
      const minister = state.ministers.find((candidate) => candidate.name === name)
      return minister?.status === 'removed'
    })).toBe(true)
    evidence.steps.push({ name: 'remove_predefined_roster', removed_count: activeMinisters.length })

    // The assembly route owns the public continuity trigger.  It commits a
    // successor person and a non-person authority before returning participants.
    const assembly = await api('/assembly/start', { method: 'POST' })
    expect(assembly.settlement_id).toBeTruthy()
    expect(assembly.participants.length).toBeGreaterThanOrEqual(2)
    const dynamicParticipants = assembly.participants.filter((participant) => participant.entity_id)
    expect(dynamicParticipants.length).toBeGreaterThan(0)
    evidence.steps.push({
      name: 'power_vacuum_successor',
      settlement_id: assembly.settlement_id,
      context_version_id: assembly.context_version_id,
      entity_ids: dynamicParticipants.map((participant) => participant.entity_id),
    })

    await api('/assembly/petition', { method: 'POST' })
    const debate = await api('/assembly/debate', {
      method: 'POST',
      data: { topic: '由新议事机构统筹河港治理', decree_type: 'personnel' },
    })
    expect(debate.context_version_id).toBeTruthy()
    await api('/assembly/vote', { method: 'POST', data: { decree_type: 'personnel' } })
    const governed = await api('/state')
    expect(governed.last_assembly.phase).toBeTruthy()
    evidence.steps.push({ name: 'governance', settlement_id: debate.settlement_id, version_id: debate.context_version_id })

    state = governed
    const retention = await api(`/worlds/${state.world_metadata.game_id}/retention?branch_id=${state.world_metadata.branch_id}&recent_limit=100`)
    expect(retention.protected_version_ids.length).toBeGreaterThan(0)
    evidence.steps.push({ name: 'vacuum_retention_report', protected_versions: retention.protected_version_ids.length })

    const saves = await api('/saves')
    expect(saves.some((entry) => entry.bookmark_id === save.bookmark.bookmark_id)).toBe(true)
    const versions = await api(`/worlds/${state.world_metadata.game_id}/${state.world_metadata.branch_id}/versions`)
    expect(versions.versions.length).toBeGreaterThan(2)

    // Reload is intentionally public browser state, not a direct engine call.
    await page.reload()
    const reloaded = await api('/state')
    expect(reloaded.world_metadata.version_id).toBe(state.world_metadata.version_id)
    expect(predefinedMinisterNames.every((name) => {
      const minister = reloaded.ministers.find((candidate) => candidate.name === name)
      return minister?.status === 'removed'
    })).toBe(true)
    expect(reloaded.last_assembly.participants.some((participant) => participant.entity_id)).toBe(true)
    evidence.steps.push({ name: 'reload', version_id: reloaded.world_metadata.version_id })

    await testInfo.attach('continuity-evidence.json', {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    })
  })
})
