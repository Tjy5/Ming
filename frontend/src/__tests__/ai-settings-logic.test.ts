import { describe, expect, it } from 'vitest'
import {
  buildAiSettingsDraft,
  draftIdentity,
  getEffectiveProviderType,
  validateAiSettingsDraft,
} from '../components/aiSettingsLogic'
import type { AiSettingsDraftState } from '../components/aiSettingsLogic'

function draft(overrides: Partial<AiSettingsDraftState> = {}): AiSettingsDraftState {
  return {
    provider: 'custom-provider',
    providerType: 'openai',
    apiKey: 'sk-test',
    baseUrl: 'https://api.example.com/v1',
    model: 'main-model',
    simpleModel: 'small-model',
    thinkingConfig: {},
    thinkingConfigSimple: {},
    ...overrides,
  }
}

describe('AI settings draft contract', () => {
  it('keeps thinking configuration schema-flat and derives provider flags', () => {
    const payload = buildAiSettingsDraft(draft({
      providerType: 'deepseek',
      thinkingConfig: { type: 'enabled' },
    }))

    expect(payload.provider_type).toBe('deepseek')
    expect(payload.enable_thinking).toBe(true)
    expect(payload.thinking_config).toEqual({ type: 'enabled' })
  })

  it('locks built-in provider families to their canonical protocol', () => {
    expect(getEffectiveProviderType('openai', 'anthropic')).toBe('openai')
    expect(getEffectiveProviderType('google', 'openai')).toBe('google')
    expect(getEffectiveProviderType('h', 'google')).toBe('openai')
    expect(getEffectiveProviderType('Z', 'anthropic')).toBe('openai')
    expect(getEffectiveProviderType('custom-provider', 'gemini')).toBe('google')
  })

  it.each([
    ['http://api.example.com/v1', '只支持公网 HTTPS'],
    ['https://user:pass@api.example.com/v1', '不能包含账号'],
    ['https://api.example.com/v1?key=x', '不能包含账号'],
    ['https://localhost/v1', '必须指向公网地址'],
    ['https://127.0.0.1/v1', '必须指向公网地址'],
    ['https://192.168.1.5/v1', '必须指向公网地址'],
    ['https://[::1]/v1', '必须指向公网地址'],
  ])('rejects unsafe literal endpoint %s', (baseUrl, expected) => {
    expect(validateAiSettingsDraft(draft({ baseUrl })).base_url).toContain(expected)
  })

  it('binds every runtime field into the local request identity', () => {
    const baseline = draftIdentity(draft())
    for (const changed of [
      draft({ provider: 'another-provider' }),
      draft({ providerType: 'anthropic' }),
      draft({ apiKey: 'sk-other' }),
      draft({ baseUrl: 'https://other.example.com/v1' }),
      draft({ model: 'other-model' }),
      draft({ simpleModel: 'other-small-model' }),
      draft({ thinkingConfig: { reasoning_effort: 'low' } }),
      draft({ thinkingConfigSimple: { reasoning_effort: 'high' } }),
    ]) {
      expect(draftIdentity(changed)).not.toBe(baseline)
    }
  })
})
