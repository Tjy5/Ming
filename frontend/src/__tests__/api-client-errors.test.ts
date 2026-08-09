import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request } from '../api/client'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('API client safe error normalization', () => {
  it('keeps only the typed AI diagnostic fields from an error envelope', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      detail: {
        error_code: 'invalid_api_key',
        message: '认证失败。',
        fix_hint: '重新复制 API Key。',
        request_id: 'ai_request_1',
        provider_summary: 'HTTP 401 · AuthenticationError',
        retryable: false,
        ignored_raw_response: 'sensitive upstream body',
      },
    }), { status: 502, headers: { 'Content-Type': 'application/json' } }))

    let caught: unknown
    try {
      await request('/settings/ai/test', { method: 'POST' })
    } catch (error) {
      caught = error
    }

    expect(caught).toBeInstanceOf(ApiError)
    const apiError = caught as ApiError
    expect(apiError.body).toEqual({
      error_code: 'invalid_api_key',
      message: '认证失败。',
      details: null,
      fix_hint: '重新复制 API Key。',
      request_id: 'ai_request_1',
      provider_summary: 'HTTP 401 · AuthenticationError',
      retryable: false,
    })
    expect(apiError.body).not.toHaveProperty('ignored_raw_response')
  })

  it('preserves AbortError instead of converting cancellation into a network failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new DOMException('aborted', 'AbortError'))

    await expect(request('/settings/ai/test')).rejects.toMatchObject({ name: 'AbortError' })
  })
})
