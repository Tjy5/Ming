import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { AIProvider, AISettings } from '../types/game'

interface Props {
  onClose: () => void
  onSaved: (message: string) => void
}

const PROVIDER_LABELS: Record<AIProvider, string> = {
  mock: 'Mock',
  openai: 'OpenAI',
  google: 'Google',
  h: 'Hotaru',
  Z: 'Z',
}

export default function AiSettingsModal({ onClose, onSaved }: Props) {
  const [provider, setProvider] = useState<AIProvider>('mock')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
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
    () => providerOptions.length ? providerOptions : ['mock', 'openai', 'google', 'h', 'Z'],
    [providerOptions],
  )

  const applySettings = (settings: AISettings) => {
    setProvider(settings.provider)
    setApiKey(settings.api_key || '')
    setBaseUrl(settings.base_url || '')
    setModel(settings.model || '')
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
    setSaving(true)
    setError('')
    setHint('')
    try {
      const saved = await api.updateAiSettings({
        provider,
        api_key: showApiKey ? (apiKey || null) : null,
        base_url: showBaseUrl ? (baseUrl || null) : null,
        model: showModel ? (model || null) : null,
      })
      applySettings(saved)
      onSaved(`AI配置已更新：${PROVIDER_LABELS[saved.provider]} / ${saved.model || '未设置模型'}`)
    } catch (e) {
      setError(e instanceof ApiError ? e.body.message : '保存AI配置失败')
    } finally {
      setSaving(false)
    }
  }

  async function handleFetchModels() {
    setFetchingModels(true)
    setError('')
    setHint('')
    try {
      const res = await api.listAiModels({
        provider,
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
              <select
                value={provider}
                onChange={(e) => void handleProviderChange(e.target.value as AIProvider)}
                disabled={saving}
              >
                {providerChoices.map((option) => (
                  <option key={option} value={option}>{PROVIDER_LABELS[option] ?? option}</option>
                ))}
              </select>
            </label>

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
              <label className="ai-field">
                <span>模型</span>
                <input
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="例如 qwen3.5-plus-2026-02-15"
                  disabled={saving}
                />
              </label>
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
                  <button
                    key={name}
                    className={`ai-model-item${model === name ? ' active' : ''}`}
                    onClick={() => setModel(name)}
                    disabled={saving}
                  >
                    {name}
                  </button>
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
