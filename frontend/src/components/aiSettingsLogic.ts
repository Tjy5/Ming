import type {
  AIProvider,
  AISettings,
  AISettingsTestRequest,
} from '../types/game'

export type ThinkingConfigValue = string | boolean | number
export type ThinkingConfig = Record<string, ThinkingConfigValue>

export interface AiSettingsDraftState {
  provider: AIProvider
  providerType: string
  apiKey: string
  baseUrl: string
  model: string
  simpleModel: string
  thinkingConfig: ThinkingConfig
  thinkingConfigSimple: ThinkingConfig
}

export type AiSettingsField = 'provider' | 'provider_type' | 'api_key' | 'base_url' | 'model'
export type AiSettingsFieldErrors = Partial<Record<AiSettingsField, string>>

const FIXED_PROVIDER_TYPES: Record<string, string> = {
  openai: 'openai',
  google: 'google',
  h: 'openai',
  Z: 'openai',
}

const SUPPORTED_PROVIDER_TYPES = new Set([
  'openai',
  'openai-response',
  'deepseek',
  'google',
  'anthropic',
])

export function fixedProviderType(provider: AIProvider): string | null {
  return FIXED_PROVIDER_TYPES[provider] ?? null
}

export function getEffectiveProviderType(provider: AIProvider, providerType: string): string {
  const fixed = fixedProviderType(provider)
  if (fixed) return fixed
  const normalized = (providerType || 'openai').trim().toLowerCase()
  return normalized === 'gemini' ? 'google' : normalized
}

export function draftFromSettings(settings: AISettings): AiSettingsDraftState {
  const provider = settings.provider as AIProvider
  return {
    provider,
    providerType: getEffectiveProviderType(provider, settings.provider_type),
    apiKey: settings.api_key,
    baseUrl: settings.base_url,
    model: settings.model,
    simpleModel: settings.simple_model ?? '',
    thinkingConfig: { ...(settings.thinking_config ?? {}) },
    thinkingConfigSimple: { ...(settings.thinking_config_simple ?? {}) },
  }
}

export function emptyCustomDraft(): AiSettingsDraftState {
  return {
    provider: 'custom',
    providerType: 'openai',
    apiKey: '',
    baseUrl: '',
    model: '',
    simpleModel: '',
    thinkingConfig: {},
    thinkingConfigSimple: {},
  }
}

function normalizeThinkingConfig(config: ThinkingConfig): ThinkingConfig | null {
  const entries = Object.entries(config).sort(([left], [right]) => left.localeCompare(right))
  return entries.length ? Object.fromEntries(entries) : null
}

function thinkingEnabled(providerType: string, config: ThinkingConfig): boolean {
  if (providerType === 'google') return typeof config.thinkingLevel === 'string' && !!config.thinkingLevel
  if (providerType === 'anthropic' || providerType === 'deepseek') {
    return config.type === 'enabled' || config.type === 'adaptive'
  }
  return (
    (typeof config.reasoning_effort === 'string' && !!config.reasoning_effort)
    || config.enable_thinking === true
  )
}

export function buildAiSettingsDraft(draft: AiSettingsDraftState): AISettingsTestRequest {
  const providerType = getEffectiveProviderType(draft.provider, draft.providerType)
  return {
    provider: draft.provider.trim(),
    provider_type: providerType,
    api_key: draft.apiKey.trim() || null,
    base_url: draft.baseUrl.trim() || null,
    model: draft.model.trim() || null,
    simple_model: draft.simpleModel.trim() || null,
    enable_thinking: thinkingEnabled(providerType, draft.thinkingConfig),
    enable_thinking_simple: thinkingEnabled(providerType, draft.thinkingConfigSimple),
    thinking_config: normalizeThinkingConfig(draft.thinkingConfig),
    thinking_config_simple: normalizeThinkingConfig(draft.thinkingConfigSimple),
  }
}

export function draftIdentity(draft: AiSettingsDraftState): string {
  return JSON.stringify(buildAiSettingsDraft(draft))
}

function parseIpv4(hostname: string): number[] | null {
  const parts = hostname.split('.')
  if (parts.length !== 4 || parts.some((part) => !/^\d{1,3}$/.test(part))) return null
  const values = parts.map(Number)
  return values.every((value) => value >= 0 && value <= 255) ? values : null
}

function isObviouslyNonPublicHost(rawHostname: string): boolean {
  const hostname = rawHostname.replace(/^\[|\]$/g, '').toLowerCase()
  if (
    hostname === 'localhost'
    || hostname.endsWith('.localhost')
    || hostname.endsWith('.local')
  ) return true

  const ipv4 = parseIpv4(hostname)
  if (ipv4) {
    const [first, second] = ipv4
    return (
      first === 0
      || first === 10
      || first === 127
      || (first === 100 && second >= 64 && second <= 127)
      || (first === 169 && second === 254)
      || (first === 172 && second >= 16 && second <= 31)
      || (first === 192 && second === 168)
      || (first === 198 && (second === 18 || second === 19))
      || first >= 224
    )
  }

  if (!hostname.includes(':')) return false
  if (hostname.includes('%')) return true
  if (hostname === '::' || hostname === '::1') return true
  if (/^(fc|fd)/.test(hostname) || /^fe[89ab]/.test(hostname) || /^ff/.test(hostname)) return true
  if (hostname.startsWith('2001:db8')) return true
  if (hostname.startsWith('::ffff:')) {
    return isObviouslyNonPublicHost(hostname.slice('::ffff:'.length))
  }
  return false
}

export function validateAiSettingsDraft(draft: AiSettingsDraftState): AiSettingsFieldErrors {
  const errors: AiSettingsFieldErrors = {}
  const provider = draft.provider.trim()
  const providerType = getEffectiveProviderType(draft.provider, draft.providerType)

  if (!provider || provider === 'custom') {
    errors.provider = '请输入自定义供应商标识。'
  }
  if (!SUPPORTED_PROVIDER_TYPES.has(providerType)) {
    errors.provider_type = '请选择受支持且与供应商协议匹配的 Provider Type。'
  }
  if (!draft.apiKey.trim()) {
    errors.api_key = 'API Key 必填。'
  }
  if (!draft.model.trim()) {
    errors.model = '主模型必填。'
  }

  const baseUrl = draft.baseUrl.trim()
  if (!baseUrl) {
    errors.base_url = 'Base URL 必填。'
  } else {
    try {
      const parsed = new URL(baseUrl)
      if (parsed.protocol !== 'https:') {
        errors.base_url = '只支持公网 HTTPS Base URL。'
      } else if (parsed.username || parsed.password || baseUrl.includes('?') || baseUrl.includes('#')) {
        errors.base_url = 'Base URL 不能包含账号、query 或 fragment。'
      } else if (!parsed.hostname || isObviouslyNonPublicHost(parsed.hostname)) {
        errors.base_url = 'Base URL 必须指向公网地址，不能使用本机或私网。'
      }
    } catch {
      errors.base_url = '请输入完整、有效的 HTTPS Base URL。'
    }
  }

  return errors
}

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}
