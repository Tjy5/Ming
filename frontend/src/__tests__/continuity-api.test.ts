import { afterEach, describe, expect, it, vi } from 'vitest'
import { worldsApi } from '../api/worlds'

afterEach(() => vi.restoreAllMocks())

describe('world continuity API adapters', () => {
  it('uses generated branch/version paths and preserves query scope', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ branches: [] }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))

    await worldsApi.listBranches('game/1')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/worlds/game%2F1/branches',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    )

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ versions: [] }), { status: 200 }))
    await worldsApi.listVersions('game/1', 'branch 2')
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://127.0.0.1:8000/api/worlds/game%2F1/branches/branch%202/versions',
      expect.anything(),
    )
  })

  it('creates and deletes a bookmark with the generated request shape', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ bookmark: { bookmark_id: 'b1' } }),
      { status: 200 },
    ))
    await worldsApi.createBookmark('g1', { game_id: 'g1', branch_id: 'b1', version_id: 'v1', name: '朝议' })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/worlds/g1/bookmarks',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ game_id: 'g1', branch_id: 'b1', version_id: 'v1', name: '朝议' }) }),
    )

    fetchMock.mockResolvedValueOnce(new Response('null', { status: 200 }))
    await worldsApi.deleteBookmark('g1', 'b1')
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://127.0.0.1:8000/api/worlds/g1/bookmarks/b1',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('encodes retention filters and activity continuation payloads', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({}), { status: 200 }))
    await worldsApi.retentionReport('g1', 'branch/2', 100)
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://127.0.0.1:8000/api/worlds/g1/retention?branch_id=branch%2F2&recent_limit=100',
      expect.anything(),
    )

    await worldsApi.continueActivity('activity/3', {
      game_id: 'g1',
      branch_id: 'b1',
      expected_parent_version_id: 'v1',
      max_checkpoints: 4,
    })
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://127.0.0.1:8000/api/activities/activity%2F3/continue',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
