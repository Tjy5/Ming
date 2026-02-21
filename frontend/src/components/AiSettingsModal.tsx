import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { AIProvider, AISettings } from '../types/game'

interface Props {
  onClose: () => void
  onSaved: (message: string) => void
}

const PROVIDER_LABELS: Record<string, string> = {
  mock: 'Mock',
  openai: 'OpenAI',
  google: 'Google',
  h: 'Hotaru',
  Z: 'Z',
}

export default function AiSettingsModal({ onClose, onSaved }: Props) {
  const [provider, setProvider] = useState<AIProvider>('mock')
  const [providerType, setProviderType] = useState('openai')
  const [customProviderInput, setCustomProviderInput] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [simpleModel, setSimpleModel] = useState('')
  const [enableThinking, setEnableThinking] = useState(false)
  const [enableThinkingSimple, setEnableThinkingSimple] = useState(false)
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
    setProvider(settings.provider)
    setProviderType(settings.provider_type || 'openai')
    setApiKey(settings.api_key || '')
    setBaseUrl(settings.base_url || '')
    setModel(settings.model || '')
    setSimpleModel(settings.simple_model || '')
    setEnableThinking(settings.enable_thinking ?? false)
    setEnableThinkingSimple(settings.enable_thinking_simple ?? false)
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
      setEnableThinking(false)
      setEnableThinkingSimple(false)
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
      const saved = await api.updateAiSettings({
        provider,
        provider_type: providerType,
        api_key: showApiKey ? (apiKey || null) : null,
        base_url: showBaseUrl ? (baseUrl || null) : null,
        model: showModel ? (model || null) : null,
        simple_model: showModel ? (simpleModel || null) : null,
        enable_thinking: showModel ? enableThinking : null,
        enable_thinking_simple: showModel ? enableThinkingSimple : null,
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

            {!['mock', 'openai', 'google', 'h', 'Z'].includes(provider) && provider !== 'custom' && (
              <label className="ai-field">
                <span>提供商类型</span>
                <select
                  value={providerType}
                  onChange={(e) => setProviderType(e.target.value)}
                  disabled={saving || loading}
                >
                  <option value="openai">OpenAI 兼容</option>
                  <option value="openai-response">OpenAI Responses</option>
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
                <label className="ai-thinking-toggle">
                  <input
                    type="checkbox"
                    checked={enableThinking}
                    onChange={(e) => setEnableThinking(e.target.checked)}
                    disabled={saving}
                  />
                  <span>主模型启用思考 (enable_thinking)</span>
                </label>
                <label className="ai-field">
                  <span>基础模型</span>
                  <input
                    value={simpleModel}
                    onChange={(e) => setSimpleModel(e.target.value)}
                    placeholder="选填: 日常非思考模型 (例如 deepseek-chat)"
                    disabled={saving}
                  />
                </label>
                <label className="ai-thinking-toggle">
                  <input
                    type="checkbox"
                    checked={enableThinkingSimple}
                    onChange={(e) => setEnableThinkingSimple(e.target.checked)}
                    disabled={saving}
                  />
                  <span>基础模型启用思考 (enable_thinking)</span>
                </label>
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
