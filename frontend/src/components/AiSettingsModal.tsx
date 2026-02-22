import { useEffect, useMemo, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { api, ApiError } from '../api/client'
import type { AIProvider, AISettings } from '../types/game'

interface Props {
  onClose: () => void
  onSaved: (message: string) => void
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type ThinkingConfig = Record<string, any>
/* eslint-enable @typescript-eslint/no-explicit-any */

const PROVIDER_LABELS: Record<string, string> = {
  mock: 'Mock',
  openai: 'OpenAI',
  google: 'Google',
  h: 'Hotaru',
  Z: 'Z',
}

function getEffectiveProviderType(provider: AIProvider, providerType: string): string {
  if (provider === 'openai') return 'openai'
  if (provider === 'google') return 'gemini'
  if (provider === 'Z') return 'openai'
  if (provider === 'h') return 'openai'
  return (providerType || 'openai').toLowerCase()
}

export default function AiSettingsModal({ onClose, onSaved }: Props) {
  const [provider, setProvider] = useState<AIProvider>('mock')
  const [providerType, setProviderType] = useState('openai')
  const [customProviderInput, setCustomProviderInput] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [simpleModel, setSimpleModel] = useState('')
  // Removed unused enableThinking state
  // Removed unused enableThinkingSimple state
  const [thinkingConfig, setThinkingConfig] = useState<ThinkingConfig>({})
  const [thinkingConfigSimple, setThinkingConfigSimple] = useState<ThinkingConfig>({})
  const [providerOptions, setProviderOptions] = useState<AIProvider[]>(['mock', 'openai', 'google', 'h', 'Z'])
  const [cache, setCache] = useState<Partial<Record<AIProvider, AISettings>>>({})
  const [models, setModels] = useState<string[]>([])
  const [modelsSource, setModelsSource] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [fetchingModels, setFetchingModels] = useState(false)
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')

  const isMock = provider === 'mock'
  const showBaseUrl = provider !== 'mock'
  const showApiKey = provider !== 'mock'
  const showModel = provider !== 'mock'

  const providerChoices = useMemo<AIProvider[]>(
    () => {
      const choices: AIProvider[] = providerOptions.length ? [...providerOptions] : ['mock', 'openai', 'google', 'h', 'Z']
      if (!choices.includes('custom')) {
        choices.push('custom')
      }
      return choices
    },
    [providerOptions],
  )

  const applySettings = (settings: AISettings) => {
    const nextThinkingConfig = settings.thinking_config
      ? { ...settings.thinking_config }
      : (settings.enable_thinking ? { enable_thinking: true } : {})
    const nextThinkingConfigSimple = settings.thinking_config_simple
      ? { ...settings.thinking_config_simple }
      : (settings.enable_thinking_simple ? { enable_thinking: true } : {})
    setProvider(settings.provider)
    setProviderType(settings.provider_type || 'openai')
    setApiKey(settings.api_key || '')
    setBaseUrl(settings.base_url || '')
    setModel(settings.model || '')
    setSimpleModel(settings.simple_model || '')
    // Removed unused setEnableThinking
    // Removed unused setEnableThinkingSimple
    setThinkingConfig(nextThinkingConfig)
    setThinkingConfigSimple(nextThinkingConfigSimple)
    setProviderOptions(settings.provider_options)
    setCache((prev) => ({ ...prev, [settings.provider]: settings }))
  }

  async function loadSettings(targetProvider?: AIProvider) {
    try {
      setError('')
      const settings = await api.getAiSettings(targetProvider)
      applySettings(settings)
      setModels([])
      setModelsSource('')
      setHint('')
    } catch (e) {
      setError(e instanceof ApiError ? e.body.message : '读取AI配置失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSettings()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleProviderChange(nextProvider: AIProvider) {
    if (nextProvider === 'custom') {
      setProvider('custom')
      setProviderType('openai')
      setApiKey('')
      setBaseUrl('')
      setModel('')
      setSimpleModel('')
      // Removed unused setEnableThinking
      // Removed unused setEnableThinkingSimple
      setThinkingConfig({})
      setThinkingConfigSimple({})
      setModels([])
      setModelsSource('')
      setHint('')
      return
    }
    setProvider(nextProvider)
    const cached = cache[nextProvider]
    if (cached) {
      applySettings(cached)
      return
    }
    setLoading(true)
    await loadSettings(nextProvider)
  }

  async function handleSave() {
    if (provider === 'custom' || !provider.trim()) {
      setError('请输入自定义供应商名称')
      return
    }
    setSaving(true)
    setError('')
    setHint('')
    try {
      const effectiveType = getEffectiveProviderType(provider, providerType)

      // 从 thinkingConfig 中提取 enable_thinking 值
      let derivedEnableThinking = false
      if (effectiveType === 'deepseek') {
        derivedEnableThinking = thinkingConfig?.thinking?.type === 'enabled'
      } else if (effectiveType === 'gemini') {
        derivedEnableThinking = !!thinkingConfig?.thinkingLevel
      } else if (effectiveType === 'anthropic') {
        derivedEnableThinking = !!thinkingConfig?.type
      } else if (effectiveType === 'openai') {
        derivedEnableThinking = !!thinkingConfig?.reasoning_effort
      } else {
        derivedEnableThinking = thinkingConfig?.enable_thinking === true
      }

      // 从 thinkingConfigSimple 中提取 enable_thinking_simple 值
      let derivedEnableThinkingSimple = false
      if (effectiveType === 'deepseek') {
        derivedEnableThinkingSimple = thinkingConfigSimple?.thinking?.type === 'enabled'
      } else if (effectiveType === 'gemini') {
        derivedEnableThinkingSimple = !!thinkingConfigSimple?.thinkingLevel
      } else if (effectiveType === 'anthropic') {
        derivedEnableThinkingSimple = !!thinkingConfigSimple?.type
      } else if (effectiveType === 'openai') {
        derivedEnableThinkingSimple = !!thinkingConfigSimple?.reasoning_effort
      } else {
        derivedEnableThinkingSimple = thinkingConfigSimple?.enable_thinking === true
      }

      const saved = await api.updateAiSettings({
        provider,
        provider_type: providerType,
        api_key: showApiKey ? (apiKey || null) : null,
        base_url: showBaseUrl ? (baseUrl || null) : null,
        model: showModel ? (model || null) : null,
        simple_model: showModel ? (simpleModel || null) : null,
        enable_thinking: showModel ? derivedEnableThinking : null,
        enable_thinking_simple: showModel ? derivedEnableThinkingSimple : null,
        thinking_config: showModel ? thinkingConfig : null,
        thinking_config_simple: showModel ? thinkingConfigSimple : null,
      })
      applySettings(saved)
      onSaved(`AI配置已更新：${PROVIDER_LABELS[saved.provider]} / ${saved.model || '未设置模型'}`)
    } catch (e) {
      setError(e instanceof ApiError ? e.body.message : '保存AI配置失败')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (window.confirm(`真的要删除自定义供应商 ${provider} 吗？`)) {
      setSaving(true)
      setError('')
      try {
        const resetSettings = await api.deleteAiSettings(provider)
        applySettings(resetSettings)
        onSaved(`已删除自定义供应商: ${provider}`)
      } catch (e) {
        setError(e instanceof ApiError ? e.body.message : '删除失败')
      } finally {
        setSaving(false)
      }
    }
  }

  async function handleFetchModels() {
    setFetchingModels(true)
    setError('')
    setHint('')
    try {
      const res = await api.listAiModels({
        provider,
        provider_type: providerType,
        api_key: showApiKey ? (apiKey || null) : null,
        base_url: showBaseUrl ? (baseUrl || null) : null,
      })
      setModels(res.models)
      setModelsSource(res.source)
      setHint(res.models.length ? `共获取 ${res.models.length} 个模型` : '未返回模型列表')
    } catch (e) {
      setError(e instanceof ApiError ? e.body.message : '获取模型列表失败')
    } finally {
      setFetchingModels(false)
    }
  }

  function renderThinkingConfig(
    currentProvider: AIProvider,
    currentProviderType: string,
    config: ThinkingConfig,
    setConfig: Dispatch<SetStateAction<ThinkingConfig>>,
    label: string,
  ) {
    if (currentProvider === 'mock') return null

    const effectiveType = getEffectiveProviderType(currentProvider, currentProviderType)

    if (effectiveType === 'deepseek') {
      const thinkingType = config?.thinking?.type === 'enabled' ? 'enabled' : 'disabled'
      return (
        <label className="ai-field">
          <span>{label}思考模式</span>
          <select
            value={thinkingType}
            onChange={(e) => {
              const next = e.target.value
              setConfig(next === 'enabled' ? { thinking: { type: 'enabled' } } : {})
            }}
            disabled={saving}
          >
            <option value="disabled">禁用</option>
            <option value="enabled">启用</option>
          </select>
        </label>
      )
    }

    if (effectiveType === 'gemini') {
      const rawLevel = typeof config?.thinkingLevel === 'string' ? config.thinkingLevel : ''
      const levelMap: Record<string, string> = {
        LOW: 'Low',
        MEDIUM: 'Medium',
        HIGH: 'High',
      }
      const thinkingLevel = levelMap[rawLevel.toUpperCase()] || ''

      return (
        <label className="ai-field">
          <span>{label}思考等级</span>
          <select
            value={thinkingLevel}
            onChange={(e) => {
              const next = e.target.value
              setConfig(next ? { thinkingLevel: next } : {})
            }}
            disabled={saving}
          >
            <option value="">不启用</option>
            <option value="Low">Low</option>
            <option value="Medium">Medium</option>
            <option value="High">High</option>
          </select>
        </label>
      )
    }

    if (effectiveType === 'anthropic') {
      const thinkingType = config?.type === 'enabled'
        ? 'enabled'
        : (config?.type === 'adaptive' ? 'adaptive' : '')

      return (
        <label className="ai-field">
          <span>{label}思考类型</span>
          <select
            value={thinkingType}
            onChange={(e) => {
              const next = e.target.value
              setConfig(next ? { type: next } : {})
            }}
            disabled={saving}
          >
            <option value="">不启用</option>
            <option value="adaptive">Adaptive</option>
            <option value="enabled">Enabled</option>
          </select>
        </label>
      )
    }

    if (effectiveType === 'openai') {
      const rawEffort = typeof config?.reasoning_effort === 'string' ? config.reasoning_effort : ''
      const effortMap: Record<string, string> = {
        LOW: 'low',
        MEDIUM: 'medium',
        HIGH: 'high',
      }
      const reasoningEffort = effortMap[rawEffort.toUpperCase()] || ''

      return (
        <label className="ai-field">
          <span>{label}推理强度</span>
          <select
            value={reasoningEffort}
            onChange={(e) => {
              const next = e.target.value
              setConfig(next ? { reasoning_effort: next } : {})
            }}
            disabled={saving}
          >
            <option value="">不启用</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
      )
    }

    const enabled = config?.enable_thinking === true
    return (
      <label className="ai-thinking-toggle">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => {
            setConfig(e.target.checked ? { enable_thinking: true } : {})
          }}
          disabled={saving}
        />
        <span>{label}启用思考 (enable_thinking)</span>
      </label>
    )
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal ai-settings-modal" onClick={(e) => e.stopPropagation()}>
        <h3>AI 设置</h3>

        {loading ? (
          <p>读取配置中...</p>
        ) : (
          <div className="ai-settings-form">
            <label className="ai-field">
              <span>供应商</span>
              <div className="ai-provider-row">
                <select
                  value={providerChoices.includes(provider) ? provider : 'custom'}
                  onChange={(e) => void handleProviderChange(e.target.value as AIProvider)}
                  disabled={saving || loading}
                >
                  {providerChoices.map((option) => (
                    <option key={option} value={option}>{
                      option === 'custom' ? '自定义 (Custom)...' : (PROVIDER_LABELS[option] ?? option)
                    }</option>
                  ))}
                </select>
                {(provider !== 'mock' && provider !== 'custom') && (
                  <button
                    className="modal-btn ai-delete-provider-btn"
                    onClick={handleDelete}
                    disabled={saving}
                    title={`删除供应商 ${provider}`}
                  >
                    删除
                  </button>
                )}
              </div>
            </label>

            {(!providerChoices.includes(provider) || provider === 'custom') && (
              <label className="ai-field">
                <span>自定义标识</span>
                <input
                  value={provider === 'custom' ? customProviderInput : provider}
                  onChange={(e) => {
                    const val = e.target.value.trim()
                    setCustomProviderInput(val)
                    if (val) {
                      setProvider(val as AIProvider)
                    } else {
                      setProvider('custom')
                    }
                  }}
                  placeholder="例如: deepseek"
                  disabled={saving || loading}
                />
              </label>
            )}

            {provider !== 'mock' && (
              <label className="ai-field">
                <span>提供商类型</span>
                <select
                  value={providerType}
                  onChange={(e) => setProviderType(e.target.value)}
                  disabled={saving || loading}
                >
                  <option value="openai">OpenAI 兼容</option>
                  <option value="openai-response">OpenAI Responses</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="gemini">Gemini</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </label>
            )}

            {showApiKey && (
              <label className="ai-field">
                <span>API Key</span>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="输入 API Key"
                  disabled={saving}
                />
              </label>
            )}

            {showBaseUrl && (
              <label className="ai-field">
                <span>Base URL</span>
                <input
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="例如 https://api.openai.com/v1"
                  disabled={saving}
                />
              </label>
            )}

            {showModel && (
              <>
                <label className="ai-field">
                  <span>主模型</span>
                  <input
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="思考模型 (例如 deepseek-reasoner)"
                    disabled={saving}
                  />
                </label>
                {renderThinkingConfig(provider, providerType, thinkingConfig, setThinkingConfig, '主模型')}
                <label className="ai-field">
                  <span>基础模型</span>
                  <input
                    value={simpleModel}
                    onChange={(e) => setSimpleModel(e.target.value)}
                    placeholder="选填: 日常非思考模型 (例如 deepseek-chat)"
                    disabled={saving}
                  />
                </label>
                {renderThinkingConfig(provider, providerType, thinkingConfigSimple, setThinkingConfigSimple, '基础模型')}
              </>
            )}

            {!isMock && (
              <div className="ai-model-tools">
                <button
                  className="modal-btn"
                  onClick={handleFetchModels}
                  disabled={fetchingModels || saving}
                >
                  {fetchingModels ? '拉取中...' : '获取模型列表'}
                </button>
                {modelsSource && <span className="ai-model-source">来源: {modelsSource}</span>}
              </div>
            )}

            {models.length > 0 && (
              <div className="ai-model-list">
                {models.map((name) => (
                  <div key={name} className="ai-model-item-group">
                    <span className="ai-model-name">{name}</span>
                    <button
                      className={`ai-model-btn${model === name ? ' active' : ''}`}
                      onClick={() => setModel(name)}
                      disabled={saving}
                      title="设为主模型"
                    >
                      主
                    </button>
                    <button
                      className={`ai-model-btn${simpleModel === name ? ' active' : ''}`}
                      onClick={() => setSimpleModel(name)}
                      disabled={saving}
                      title="设为基础模型"
                    >
                      基
                    </button>
                  </div>
                ))}
              </div>
            )}

            {hint && <p className="ai-hint">{hint}</p>}
          </div>
        )}

        {error && <p className="ai-error">{error}</p>}

        <div className="modal-actions">
          <button className="modal-btn" onClick={onClose} disabled={saving}>关闭</button>
          <button className="modal-btn primary" onClick={handleSave} disabled={loading || saving}>
            {saving ? '保存中...' : '保存并应用'}
          </button>
        </div>
      </div>
    </div>
  )
}
