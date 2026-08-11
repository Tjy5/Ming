import { afterEach, describe, expect, it, vi } from 'vitest'
import { trpgApi } from '../api/trpg'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('TRPG API contract', () => {
  it('sends the stable option id with the selected action', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    await trpgApi.act({ action_text: '整肃军纪', option_id: 'opt-1' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toMatch(/\/api\/trpg\/act$/)
    expect(JSON.parse(String(init?.body))).toMatchObject({
      action_text: '整肃军纪',
      option_id: 'opt-1',
    })
  })

  it('calls the settlement-bound narrative endpoint without an action payload', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    await trpgApi.regenerateNarrative(
      '00000000-0000-0000-0000-000000000001',
      { path_id: 'trpg_gm_action', topic_id: 'trpg' },
    )

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toMatch(/\/api\/settlements\/00000000-0000-0000-0000-000000000001\/narrative$/)
    expect(JSON.parse(String(init?.body))).toEqual({
      path_id: 'trpg_gm_action',
      topic_id: 'trpg',
    })
    expect(JSON.parse(String(init?.body))).not.toHaveProperty('action_text')
  })
})
