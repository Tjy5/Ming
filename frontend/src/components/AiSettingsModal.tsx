import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  AIProvider,
  AISettings,
  AISettingsAssessmentResponse,
  AISettingsAssessmentSummary,
  AISettingsTestResponse,
  ErrorResponse,
} from '../types/game'
import {
  buildAiSettingsDraft,
  draftFromSettings,
  draftIdentity,
  emptyCustomDraft,
  fixedProviderType,
  getEffectiveProviderType,
  isAbortError,
  validateAiSettingsDraft,
} from './aiSettingsLogic'
import type {
  AiSettingsDraftState,
  AiSettingsFieldErrors,
  ThinkingConfig,
} from './aiSettingsLogic'
import { useStore } from '../hooks/store'
import { useFocusTrap } from '../hooks/useFocusTrap'

interface Props {
  onClose: () => void
  onSaved: (message: string) => void
}

type TestStatus = 'idle' | 'testing' | 'verified' | 'error' | 'cancelled' | 'expired'
type AssessmentStatus = 'idle' | 'running' | 'complete' | 'error' | 'cancelled'
type AssessmentReport = AISettingsAssessmentSummary & { request_id?: string }

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  google: 'Google',
  h: 'Hotaru',
  Z: 'Z',
}

const SOURCE_LABELS: Record<string, string> = {
  saved: '已保存',
  provider_default: '供应商默认',
  legacy_env: '旧配置草稿',
  missing: '缺失',
}

const ASSESSMENT_TIER_LABELS: Record<AssessmentReport['tier'], string> = {
  excellent: '优秀',
  usable: '可用',
  high_risk: '高风险',
  unassessed: '未评估',
}

const ASSESSMENT_SCENARIO_LABELS: Record<string, string> = {
  structured_schema: '结构化输出',
  state_grounding: '当前状态依据',
  causal_adjudication: '开放因果裁决',
  short_memory: '短期记忆',
}

const ASSESSMENT_STATUS_LABELS: Record<string, string> = {
  pass: '通过',
  warn: '警告',
  fail: '失败',
}

const FIELD_ERROR_IDS = {
  provider: 'ai-provider-error',
  provider_type: 'ai-provider-type-error',
  api_key: 'ai-api-key-error',
  base_url: 'ai-base-url-error',
  model: 'ai-model-error',
} as const

const INITIAL_DRAFT: AiSettingsDraftState = {
  provider: 'openai',
  providerType: 'openai',
  apiKey: '',
  baseUrl: '',
  model: '',
  simpleModel: '',
  thinkingConfig: {},
  thinkingConfigSimple: {},
}

function localError(message: string, fixHint: string): ErrorResponse {
  return {
    error_code: 'invalid_ai_settings',
    message,
    details: null,
    fix_hint: fixHint,
    request_id: null,
    provider_summary: null,
    retryable: false,
  }
}

function errorFromUnknown(error: unknown, fallbackMessage: string): ErrorResponse {
  if (error instanceof ApiError) return error.body
  return {
    error_code: 'client_error',
    message: fallbackMessage,
    details: null,
    fix_hint: '确认后端服务正在运行后再手动重试。',
    request_id: null,
    provider_summary: null,
    retryable: true,
  }
}

function renderDiagnostic(title: string, error: ErrorResponse | null) {
  if (!error) return null
  const hasDetails = !!(error.provider_summary || error.request_id)
  return (
    <div className="ai-diagnostic" role="alert">
      <strong>{title}</strong>
      <p>{error.message}</p>
      {error.fix_hint && <p className="ai-diagnostic-fix">建议：{error.fix_hint}</p>}
      {error.retryable && <p className="ai-diagnostic-retry">修正后可手动重试；系统不会自动重发。</p>}
      {hasDetails && (
        <details className="ai-diagnostic-details">
          <summary>排障详情</summary>
          {error.provider_summary && <p>供应商摘要：{error.provider_summary}</p>}
          {error.request_id && <p>请求编号：{error.request_id}</p>}
        </details>
      )}
    </div>
  )
}

function endpointHost(baseUrl: string): string {
  try {
    return new URL(baseUrl).host
  } catch {
    return baseUrl || '未设置地址'
  }
}

function formatDateTime(raw: string | null | undefined): string {
  if (!raw) return '未知时间'
  const timestamp = Date.parse(raw)
  if (!Number.isFinite(timestamp)) return raw
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(timestamp))
}

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider
}

function hasFieldErrors(errors: AiSettingsFieldErrors): boolean {
  return Object.keys(errors).length > 0
}

export default function AiSettingsModal({ onClose, onSaved }: Props) {
  const [effectiveSettings, setEffectiveSettings] = useState<AISettings | null>(null)
  const [draft, setDraft] = useState<AiSettingsDraftState>(INITIAL_DRAFT)
  const [providerOptions, setProviderOptions] = useState<AIProvider[]>(['openai', 'google', 'h', 'Z'])
  const [cache, setCache] = useState<Record<string, AISettings>>({})
  const [models, setModels] = useState<string[]>([])
  const [modelsSource, setModelsSource] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [fetchingModels, setFetchingModels] = useState(false)
  const [hint, setHint] = useState('')
  const [loadError, setLoadError] = useState<ErrorResponse | null>(null)
  const [modelError, setModelError] = useState<ErrorResponse | null>(null)
  const [saveError, setSaveError] = useState<ErrorResponse | null>(null)
  const [testError, setTestError] = useState<ErrorResponse | null>(null)
  const [assessmentError, setAssessmentError] = useState<ErrorResponse | null>(null)
  const [testStatus, setTestStatus] = useState<TestStatus>('idle')
  const [testDetail, setTestDetail] = useState('')
  const [verification, setVerification] = useState<AISettingsTestResponse | null>(null)
  const [assessmentStatus, setAssessmentStatus] = useState<AssessmentStatus>('idle')
  const [assessment, setAssessment] = useState<AssessmentReport | null>(null)
  const [assessmentInvalidated, setAssessmentInvalidated] = useState(false)
  const [modelQuery, setModelQuery] = useState('')
  const [manualModel, setManualModel] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const draftRef = useRef(draft)
  const loadRequestIdRef = useRef(0)
  const testRequestIdRef = useRef(0)
  const assessmentRequestIdRef = useRef(0)
  const testControllerRef = useRef<AbortController | null>(null)
  const assessmentControllerRef = useRef<AbortController | null>(null)

  const fieldErrors = useMemo(() => validateAiSettingsDraft(draft), [draft])
  const currentDraftIdentity = useMemo(() => draftIdentity(draft), [draft])
  const providerChoices = useMemo<AIProvider[]>(() => {
    const choices = Array.from(new Set(providerOptions.length
      ? providerOptions
      : ['openai', 'google', 'h', 'Z'])) as AIProvider[]
    if (!choices.includes('custom')) choices.push('custom')
    return choices
  }, [providerOptions])

  const testRunning = testStatus === 'testing'
  const assessmentRunning = assessmentStatus === 'running'
  const fieldsDisabled = loading || saving || fetchingModels || testRunning || assessmentRunning
  const verificationValid = verification !== null
  const canSave = !loading && !saving && verificationValid && !hasFieldErrors(fieldErrors)
  const canAssess = verificationValid && !hasFieldErrors(fieldErrors) && !saving && !testRunning
  const canFetchModels = !(
    fieldErrors.provider
    || fieldErrors.provider_type
    || fieldErrors.api_key
    || fieldErrors.base_url
  )
  const providerTypeLocked = fixedProviderType(draft.provider) !== null

  useEffect(() => {
    draftRef.current = draft
  }, [draft])

  useEffect(() => {
    void loadSettings()
    return () => {
      loadRequestIdRef.current += 1
      testRequestIdRef.current += 1
      assessmentRequestIdRef.current += 1
      testControllerRef.current?.abort()
      assessmentControllerRef.current?.abort()
    }
    // Initial load and request cleanup intentionally run only for this modal instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const panelRef = useRef<HTMLDivElement | null>(null)
  useFocusTrap({ active: true, containerRef: panelRef, overlayId: 'ai_settings_modal' })

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || saving) return
      const stack = useStore.getState().overlayStack
      if (stack.length > 0 && !useStore.getState().isTopmostOverlay('ai_settings_modal')) return
      testControllerRef.current?.abort()
      assessmentControllerRef.current?.abort()
      onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose, saving])

  useEffect(() => {
    if (!verification) return
    const expiresAt = Date.parse(verification.expires_at)
    if (!Number.isFinite(expiresAt)) {
      setVerification(null)
      setTestStatus('expired')
      setTestDetail('草稿验证已过期，请重新测试。')
      return
    }

    let timer: number | undefined
    const scheduleExpiry = () => {
      const remaining = expiresAt - Date.now()
      if (remaining <= 0) {
        setVerification(null)
        setTestStatus('expired')
        setTestDetail('草稿验证已过期，请重新测试。')
        return
      }
      timer = window.setTimeout(scheduleExpiry, Math.min(remaining, 2_147_483_647))
    }
    scheduleExpiry()
    return () => {
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [verification])

  function clearDraftBoundResults() {
    setVerification(null)
    setTestStatus('idle')
    setTestDetail('')
    setTestError(null)
    setAssessment(null)
    setAssessmentStatus('idle')
    setAssessmentError(null)
    setAssessmentInvalidated(true)
    setSaveError(null)
  }

  function updateDraft(patch: Partial<AiSettingsDraftState>) {
    setDraft((current) => ({ ...current, ...patch }))
    clearDraftBoundResults()
  }

  function applySettingsToDraft(settings: AISettings, updateEffective: boolean) {
    const nextDraft = draftFromSettings(settings)
    const options = (settings.provider_options ?? ['openai', 'google', 'h', 'Z']) as AIProvider[]
    setDraft(nextDraft)
    setProviderOptions(options)
    setCache((current) => ({ ...current, [settings.provider]: settings }))
    setModels([])
    setModelsSource('')
    setModelQuery('')
    setManualModel('')
    setHint('')
    setVerification(null)
    setTestStatus('idle')
    setTestDetail('')
    setTestError(null)
    setSaveError(null)
    const loadedAssessment = settings.assessment?.config_matches ? settings.assessment : null
    setAssessment(loadedAssessment)
    setAssessmentStatus(loadedAssessment ? 'complete' : 'idle')
    setAssessmentInvalidated(false)
    setAssessmentError(null)
    if (updateEffective || settings.effective) setEffectiveSettings(settings)
  }

  async function loadSettings(targetProvider?: AIProvider) {
    const requestId = ++loadRequestIdRef.current
    try {
      setLoadError(null)
      const settings = await api.getAiSettings(targetProvider)
      if (requestId !== loadRequestIdRef.current) return
      applySettingsToDraft(settings, targetProvider === undefined)
    } catch (error) {
      if (requestId !== loadRequestIdRef.current) return
      setLoadError(errorFromUnknown(error, '读取 AI 配置失败。'))
    } finally {
      if (requestId === loadRequestIdRef.current) setLoading(false)
    }
  }

  async function handleProviderChange(nextProvider: AIProvider) {
    setModels([])
    setModelsSource('')
    setHint('')
    clearDraftBoundResults()
    if (nextProvider === 'custom') {
      setDraft(emptyCustomDraft())
      return
    }

    const cached = cache[nextProvider]
    if (cached) {
      applySettingsToDraft(cached, false)
      return
    }

    setDraft({
      ...INITIAL_DRAFT,
      provider: nextProvider,
      providerType: fixedProviderType(nextProvider) ?? 'openai',
    })
    setLoading(true)
    await loadSettings(nextProvider)
  }

  function verificationIsCurrent(): boolean {
    if (!verification) return false
    const expiresAt = Date.parse(verification.expires_at)
    if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      setVerification(null)
      setTestStatus('expired')
      setTestDetail('草稿验证已过期，请重新测试。')
      return false
    }
    return true
  }

  async function handleSave() {
    if (!verificationIsCurrent() || hasFieldErrors(fieldErrors) || !verification) {
      setSaveError(localError(
        '当前草稿不能保存并应用。',
        '修正字段并完成一次真实连接测试后再保存。',
      ))
      return
    }

    setSaving(true)
    setSaveError(null)
    try {
      const saved = await api.updateAiSettings({
        ...buildAiSettingsDraft(draft),
        verification_token: verification.verification_token,
      })
      applySettingsToDraft(saved, true)
      onSaved(`AI 配置已生效：${providerLabel(saved.provider)} / ${saved.model}`)
    } catch (error) {
      const diagnostic = errorFromUnknown(error, '保存并应用 AI 配置失败。')
      setSaveError(diagnostic)
      if (['ai_test_required', 'ai_test_expired', 'ai_test_mismatch', 'ai_test_used'].includes(diagnostic.error_code)) {
        setVerification(null)
        setTestStatus(diagnostic.error_code === 'ai_test_expired' ? 'expired' : 'idle')
        setTestDetail('验证凭证已失效，请重新测试当前草稿。')
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!window.confirm(`真的要删除供应商 ${draft.provider} 的配置吗？`)) return
    setSaving(true)
    setSaveError(null)
    try {
      const resetSettings = await api.deleteAiSettings(draft.provider)
      applySettingsToDraft(resetSettings, true)
      onSaved(`已删除供应商配置：${providerLabel(draft.provider)}`)
    } catch (error) {
      setSaveError(errorFromUnknown(error, '删除 AI 配置失败。'))
    } finally {
      setSaving(false)
    }
  }

  async function handleFetchModels() {
    if (!canFetchModels || fetchingModels) {
      setModelError(localError(
        '当前配置还不能获取模型列表。',
        '先填写供应商、API Key 与公网 HTTPS Base URL。',
      ))
      return
    }
    setFetchingModels(true)
    setModelError(null)
    setHint('')
    try {
      const res = await api.listAiModels({
        provider: draft.provider,
        provider_type: getEffectiveProviderType(draft.provider, draft.providerType),
        api_key: draft.apiKey.trim() || null,
        base_url: draft.baseUrl.trim() || null,
      })
      const nextModels = res.models ?? []
      setModels(nextModels)
      setModelsSource(res.source)
      setHint(nextModels.length
        ? `共获取 ${nextModels.length} 个模型；列表仅供辅助，仍需真实连接测试。`
        : '供应商未返回模型列表；这不代表实际生成可用。')
    } catch (error) {
      setModelError(errorFromUnknown(error, '获取模型列表失败。'))
    } finally {
      setFetchingModels(false)
    }
  }

  async function handleTestConnection() {
    if (testControllerRef.current || hasFieldErrors(fieldErrors)) {
      if (hasFieldErrors(fieldErrors)) {
        setTestError(localError(
          '当前草稿字段无效，无法测试。',
          '修正表单中标出的字段后再发起真实测试。',
        ))
      }
      return
    }

    const requestId = ++testRequestIdRef.current
    const controller = new AbortController()
    const snapshot = draft
    const snapshotIdentity = currentDraftIdentity
    testControllerRef.current = controller
    setVerification(null)
    setTestStatus('testing')
    setTestDetail('正在发起一次真实最小生成；不会自动重试或切换模型。')
    setTestError(null)
    setSaveError(null)

    try {
      const response = await api.testAiConnection(buildAiSettingsDraft(snapshot), controller.signal)
      if (
        requestId !== testRequestIdRef.current
        || controller.signal.aborted
        || draftIdentity(draftRef.current) !== snapshotIdentity
      ) return
      setVerification(response)
      setTestStatus('verified')
      setTestDetail(`${response.message} 耗时 ${response.latency_ms}ms。`)
    } catch (error) {
      if (requestId !== testRequestIdRef.current) return
      setVerification(null)
      if (isAbortError(error) || controller.signal.aborted) {
        setTestStatus('cancelled')
        setTestDetail('测试已取消；若供应商已收到请求，仍可能产生少量费用，但系统不会自动重发。')
      } else {
        setTestStatus('error')
        setTestError(errorFromUnknown(error, '测试连接失败。'))
      }
    } finally {
      if (testControllerRef.current === controller) testControllerRef.current = null
    }
  }

  function cancelTest() {
    const controller = testControllerRef.current
    if (!controller) return
    testRequestIdRef.current += 1
    controller.abort()
    if (testControllerRef.current === controller) testControllerRef.current = null
    setTestStatus('cancelled')
    setTestDetail('测试已取消；若供应商已收到请求，仍可能产生少量费用，但系统不会自动重发。')
  }

  async function handleAssessment() {
    if (assessmentControllerRef.current || !canAssess || !verificationIsCurrent()) return

    const requestId = ++assessmentRequestIdRef.current
    const controller = new AbortController()
    const snapshot = draft
    const snapshotIdentity = currentDraftIdentity
    assessmentControllerRef.current = controller
    setAssessmentStatus('running')
    setAssessmentError(null)

    try {
      const response: AISettingsAssessmentResponse = await api.assessAiCapability(
        buildAiSettingsDraft(snapshot),
        controller.signal,
      )
      if (
        requestId !== assessmentRequestIdRef.current
        || controller.signal.aborted
        || draftIdentity(draftRef.current) !== snapshotIdentity
      ) return
      setAssessment(response)
      setAssessmentInvalidated(false)
      setAssessmentStatus('complete')
    } catch (error) {
      if (requestId !== assessmentRequestIdRef.current) return
      if (isAbortError(error) || controller.signal.aborted) {
        setAssessmentStatus('cancelled')
      } else {
        setAssessmentStatus('error')
        setAssessmentError(errorFromUnknown(error, '模型能力评估失败。'))
      }
    } finally {
      if (assessmentControllerRef.current === controller) assessmentControllerRef.current = null
    }
  }

  function cancelAssessment() {
    const controller = assessmentControllerRef.current
    if (!controller) return
    assessmentRequestIdRef.current += 1
    controller.abort()
    if (assessmentControllerRef.current === controller) assessmentControllerRef.current = null
    setAssessmentStatus('cancelled')
  }

  function handleClose() {
    testControllerRef.current?.abort()
    assessmentControllerRef.current?.abort()
    onClose()
  }

  function renderFieldError(field: keyof AiSettingsFieldErrors) {
    const message = fieldErrors[field]
    return message
      ? <span id={FIELD_ERROR_IDS[field]} className="ai-field-error">{message}</span>
      : null
  }

  function renderThinkingConfig(
    config: ThinkingConfig,
    onChange: (next: ThinkingConfig) => void,
    label: string,
  ) {
    const effectiveType = getEffectiveProviderType(draft.provider, draft.providerType)
    if (effectiveType === 'deepseek') {
      const thinkingType = config.type === 'enabled' ? 'enabled' : 'disabled'
      return (
        <label className="ai-field">
          <span>{label}思考模式</span>
          <select
            value={thinkingType}
            onChange={(event) => onChange(event.target.value === 'enabled' ? { type: 'enabled' } : {})}
            disabled={fieldsDisabled}
          >
            <option value="disabled">禁用</option>
            <option value="enabled">启用</option>
          </select>
        </label>
      )
    }

    if (effectiveType === 'google') {
      const rawLevel = typeof config.thinkingLevel === 'string' ? config.thinkingLevel : ''
      const levelMap: Record<string, string> = { LOW: 'Low', MEDIUM: 'Medium', HIGH: 'High' }
      const thinkingLevel = levelMap[rawLevel.toUpperCase()] || ''
      return (
        <label className="ai-field">
          <span>{label}思考等级</span>
          <select
            value={thinkingLevel}
            onChange={(event) => onChange(event.target.value ? { thinkingLevel: event.target.value } : {})}
            disabled={fieldsDisabled}
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
      const thinkingType = config.type === 'enabled'
        ? 'enabled'
        : (config.type === 'adaptive' ? 'adaptive' : '')
      return (
        <label className="ai-field">
          <span>{label}思考类型</span>
          <select
            value={thinkingType}
            onChange={(event) => onChange(event.target.value ? { type: event.target.value } : {})}
            disabled={fieldsDisabled}
          >
            <option value="">不启用</option>
            <option value="adaptive">Adaptive</option>
            <option value="enabled">Enabled</option>
          </select>
        </label>
      )
    }

    if (effectiveType === 'openai' || effectiveType === 'openai-response') {
      const rawEffort = typeof config.reasoning_effort === 'string' ? config.reasoning_effort : ''
      const effortMap: Record<string, string> = { LOW: 'low', MEDIUM: 'medium', HIGH: 'high' }
      const reasoningEffort = effortMap[rawEffort.toUpperCase()] || ''
      return (
        <label className="ai-field">
          <span>{label}推理强度</span>
          <select
            value={reasoningEffort}
            onChange={(event) => onChange(event.target.value ? { reasoning_effort: event.target.value } : {})}
            disabled={fieldsDisabled}
          >
            <option value="">不启用</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
      )
    }

    const enabled = config.enable_thinking === true
    return (
      <label className="ai-thinking-toggle">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => onChange(event.target.checked ? { enable_thinking: true } : {})}
          disabled={fieldsDisabled}
        />
        <span>{label}启用思考 (enable_thinking)</span>
      </label>
    )
  }

  const assessmentCalls = assessment?.calls_completed ?? (assessmentRunning ? 1 : 0)
  const effectiveSources = effectiveSettings?.sources ?? {}
  const filteredModels = models.filter((name) => name.toLowerCase().includes(modelQuery.trim().toLowerCase()))
  const hasDraftChanges = verification === null && !loading

  return (
    <div className="modal-overlay" onClick={handleClose} data-overlay-root="modal">
      <div
        ref={panelRef}
        className="modal ai-settings-modal"
        role="dialog"
        aria-modal="true"
        data-overlay-panel="true"
        aria-labelledby="ai-settings-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 id="ai-settings-title">AI 设置</h3>

        {effectiveSettings && (
          <section className={`ai-runtime-status ${effectiveSettings.effective ? 'effective' : 'required'}`}>
            <strong>{effectiveSettings.effective ? '当前已生效' : '当前未生效'}</strong>
            <span>
              {providerLabel(effectiveSettings.provider)} · {effectiveSettings.model || '未设置模型'} · {endpointHost(effectiveSettings.base_url)}
            </span>
            <details>
              <summary>配置来源</summary>
              <p>
                Provider：{SOURCE_LABELS[effectiveSources.provider] ?? effectiveSources.provider ?? '未知'}；
                API Key：{SOURCE_LABELS[effectiveSources.api_key] ?? effectiveSources.api_key ?? '未知'}；
                模型：{SOURCE_LABELS[effectiveSources.model] ?? effectiveSources.model ?? '未知'}
              </p>
            </details>
          </section>
        )}

        {renderDiagnostic('读取配置失败', loadError)}

        {loading ? (
          <p role="status" aria-label="读取 AI 配置中">读取配置中...</p>
        ) : (
          <div className="ai-settings-layout">
            <aside className="ai-provider-sidebar" aria-label="供应商列表">
              <div className="ai-provider-sidebar-header">
                <span>供应商</span>
                <button
                  type="button"
                  className="ai-icon-action"
                  onClick={() => void handleProviderChange('custom')}
                  disabled={fieldsDisabled}
                  title="添加自定义供应商"
                  aria-label="添加自定义供应商"
                >
                  +
                </button>
              </div>
              <div className="ai-provider-list">
                {providerChoices.map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`ai-provider-item${draft.provider === option ? ' active' : ''}`}
                    onClick={() => void handleProviderChange(option)}
                    disabled={fieldsDisabled}
                  >
                    <span className="ai-provider-dot" aria-hidden="true" />
                    <span>{option === 'custom' ? '自定义供应商' : providerLabel(option)}</span>
                    {effectiveSettings?.provider === option && <small>当前</small>}
                  </button>
                ))}
              </div>
              <p className="ai-provider-sidebar-note">选择供应商后，在右侧编辑连接与模型。</p>
            </aside>

            <section className="ai-provider-detail" aria-labelledby="ai-provider-detail-title">
              <div className="ai-provider-detail-heading">
                <div>
                  <span className="ai-eyebrow">Provider detail</span>
                  <h4 id="ai-provider-detail-title">{providerLabel(draft.provider)}</h4>
                </div>
                <span className={`ai-draft-badge${verificationValid ? ' verified' : ''}`}>
                  {verificationValid ? '已验证' : hasDraftChanges ? '待验证' : '未验证'}
                </span>
              </div>

          <div className="ai-settings-form">
            <label className="ai-field">
              <span>供应商</span>
              <div className="ai-provider-row">
                <select
                  value={providerChoices.includes(draft.provider) ? draft.provider : 'custom'}
                  onChange={(event) => void handleProviderChange(event.target.value as AIProvider)}
                  disabled={fieldsDisabled}
                >
                  {providerChoices.map((option) => (
                    <option key={option} value={option}>
                      {option === 'custom' ? '自定义 (Custom)...' : providerLabel(option)}
                    </option>
                  ))}
                </select>
                {draft.provider !== 'custom' && (
                  <button
                    type="button"
                    className="modal-btn ai-delete-provider-btn"
                    onClick={() => void handleDelete()}
                    disabled={saving || testRunning || assessmentRunning}
                    title={`删除供应商 ${draft.provider}`}
                  >
                    删除
                  </button>
                )}
              </div>
              {draft.provider !== 'custom' && renderFieldError('provider')}
            </label>

            {(!providerChoices.includes(draft.provider) || draft.provider === 'custom') && (
              <label className="ai-field">
                <span>自定义标识</span>
                <input
                  value={draft.provider === 'custom' ? '' : draft.provider}
                  onChange={(event) => updateDraft({
                    provider: (event.target.value || 'custom') as AIProvider,
                  })}
                  placeholder="例如: deepseek"
                  disabled={fieldsDisabled}
                  aria-invalid={!!fieldErrors.provider}
                  aria-describedby={fieldErrors.provider ? FIELD_ERROR_IDS.provider : undefined}
                />
                {renderFieldError('provider')}
              </label>
            )}

            <label className="ai-field">
              <span>Provider Type</span>
              <select
                value={getEffectiveProviderType(draft.provider, draft.providerType)}
                onChange={(event) => updateDraft({ providerType: event.target.value })}
                disabled={fieldsDisabled || providerTypeLocked}
                aria-invalid={!!fieldErrors.provider_type}
                aria-describedby={fieldErrors.provider_type ? FIELD_ERROR_IDS.provider_type : undefined}
              >
                <option value="openai">OpenAI 兼容</option>
                <option value="openai-response">OpenAI Responses</option>
                <option value="deepseek">DeepSeek</option>
                <option value="google">Gemini / Google</option>
                <option value="anthropic">Anthropic</option>
              </select>
              {providerTypeLocked && <span className="ai-field-note">内置供应商的协议类型固定。</span>}
              {renderFieldError('provider_type')}
            </label>

            <label className="ai-field">
              <span>API Key</span>
              <input
                type="password"
                autoComplete="new-password"
                value={draft.apiKey}
                onChange={(event) => updateDraft({ apiKey: event.target.value })}
                placeholder="输入 API Key"
                disabled={fieldsDisabled}
                aria-invalid={!!fieldErrors.api_key}
                aria-describedby={fieldErrors.api_key ? FIELD_ERROR_IDS.api_key : undefined}
              />
              {renderFieldError('api_key')}
            </label>

            <label className="ai-field">
              <span>Base URL</span>
              <input
                value={draft.baseUrl}
                onChange={(event) => updateDraft({ baseUrl: event.target.value })}
                placeholder="例如 https://api.openai.com/v1"
                disabled={fieldsDisabled}
                aria-invalid={!!fieldErrors.base_url}
                aria-describedby={fieldErrors.base_url ? FIELD_ERROR_IDS.base_url : undefined}
              />
              {renderFieldError('base_url')}
            </label>

            <label className="ai-field">
              <span>主模型</span>
              <input
                value={draft.model}
                onChange={(event) => updateDraft({ model: event.target.value })}
                placeholder="例如 gpt-5-mini"
                disabled={fieldsDisabled}
                aria-invalid={!!fieldErrors.model}
                aria-describedby={fieldErrors.model ? FIELD_ERROR_IDS.model : undefined}
              />
              {renderFieldError('model')}
            </label>
            <label className="ai-field">
              <span>基础模型</span>
              <input
                value={draft.simpleModel}
                onChange={(event) => updateDraft({ simpleModel: event.target.value })}
                placeholder="选填：日常非思考模型"
                disabled={fieldsDisabled}
              />
            </label>
            <div className="ai-model-tools">
              <button
                type="button"
                className="modal-btn"
                onClick={() => void handleFetchModels()}
                disabled={fetchingModels || saving || testRunning || assessmentRunning || !canFetchModels}
              >
                {fetchingModels ? '拉取中...' : '获取模型列表（辅助）'}
              </button>
              {modelsSource && <span className="ai-model-source">来源：{modelsSource}</span>}
            </div>
            {hint && <p className="ai-hint">{hint}</p>}
            {renderDiagnostic('模型列表获取失败', modelError)}

            <div className="ai-model-picker">
              <div className="ai-model-picker-header">
                <div>
                  <strong>模型选择器</strong>
                  <span>{models.length ? `${filteredModels.length} / ${models.length} 个模型` : '可拉取或手动添加模型'}</span>
                </div>
                <input
                  className="ai-model-search"
                  value={modelQuery}
                  onChange={(event) => setModelQuery(event.target.value)}
                  placeholder="搜索模型"
                  aria-label="搜索模型"
                  disabled={fieldsDisabled}
                />
              </div>
              {filteredModels.length > 0 && (
              <div className="ai-model-list">
                {filteredModels.map((name) => (
                  <div key={name} className="ai-model-item-group">
                    <span className="ai-model-name">{name}</span>
                    <button
                      type="button"
                      className={`ai-model-btn${draft.model === name ? ' active' : ''}`}
                      onClick={() => updateDraft({ model: name })}
                      disabled={fieldsDisabled}
                      title="设为主模型"
                    >
                      主
                    </button>
                    <button
                      type="button"
                      className={`ai-model-btn${draft.simpleModel === name ? ' active' : ''}`}
                      onClick={() => updateDraft({ simpleModel: name })}
                      disabled={fieldsDisabled}
                      title="设为基础模型"
                    >
                      基
                    </button>
                  </div>
                ))}
              </div>
              )}
              <div className="ai-manual-model-row">
                <input
                  value={manualModel}
                  onChange={(event) => setManualModel(event.target.value)}
                  placeholder="手动添加模型 ID"
                  aria-label="手动添加模型 ID"
                  disabled={fieldsDisabled}
                />
                <button
                  type="button"
                  className="modal-btn"
                  onClick={() => {
                    const value = manualModel.trim()
                    if (!value) return
                    updateDraft({ model: value })
                    setModels((current) => current.includes(value) ? current : [...current, value])
                    setManualModel('')
                  }}
                  disabled={fieldsDisabled || !manualModel.trim()}
                >
                  添加并设为主模型
                </button>
              </div>
            </div>

            <button
              type="button"
              className="ai-advanced-toggle"
              onClick={() => setAdvancedOpen((open) => !open)}
              aria-expanded={advancedOpen}
            >
              <span>高级思考配置</span><span aria-hidden="true">{advancedOpen ? '收起' : '展开'}</span>
            </button>
            {advancedOpen && (
              <div className="ai-advanced-drawer">
                <p>思考能力按 Provider Type 映射到兼容的请求字段。</p>
                {renderThinkingConfig(
                  draft.thinkingConfig,
                  (next) => updateDraft({ thinkingConfig: next }),
                  '主模型',
                )}
                {renderThinkingConfig(
                  draft.thinkingConfigSimple,
                  (next) => updateDraft({ thinkingConfigSimple: next }),
                  '基础模型',
                )}
              </div>
            )}

            <section className="ai-action-card" aria-labelledby="ai-test-heading">
              <div className="ai-action-card-header">
                <div>
                  <strong id="ai-test-heading">测试连接</strong>
                  <p>会产生一次极少量 Token 的真实生成；最多一次调用，不自动重试或切换模型。</p>
                </div>
                <div className="ai-action-buttons">
                  <button
                    type="button"
                    className="modal-btn"
                    onClick={() => void handleTestConnection()}
                    disabled={testRunning || assessmentRunning || saving || hasFieldErrors(fieldErrors)}
                  >
                    {testRunning ? '测试中...' : '测试连接（1 次）'}
                  </button>
                  {testRunning && (
                    <button type="button" className="modal-btn ai-cancel-btn" onClick={cancelTest}>
                      取消测试
                    </button>
                  )}
                </div>
              </div>

              {testStatus === 'testing' && <p className="ai-progress" role="status">{testDetail}</p>}
              {testStatus === 'verified' && verification && (
                <div className="ai-verification-status verified">
                  <strong>草稿已验证</strong>
                  <span>
                    {providerLabel(verification.verified_config.provider)} · {verification.verified_config.model} · {endpointHost(verification.verified_config.base_url)}
                  </span>
                  <span>有效至 {formatDateTime(verification.expires_at)} · 请求编号 {verification.request_id}</span>
                  <p>{testDetail}</p>
                </div>
              )}
              {(testStatus === 'idle' || testStatus === 'expired') && !verification && (
                <p className={testStatus === 'expired' ? 'ai-warning' : 'ai-hint'}>
                  {testStatus === 'expired' ? testDetail : '草稿未验证；保存并应用保持禁用。'}
                </p>
              )}
              {testStatus === 'cancelled' && <p className="ai-warning">{testDetail}</p>}
              {renderDiagnostic('连接测试失败', testError)}
            </section>

            <section className="ai-action-card" aria-labelledby="ai-assessment-heading">
              <div className="ai-action-card-header">
                <div>
                  <strong id="ai-assessment-heading">评估模型能力（可选）</strong>
                  <p>额外最多 4 次真实生成，检查结构、状态依据、开放因果和短期记忆。</p>
                </div>
                <div className="ai-action-buttons">
                  <button
                    type="button"
                    className="modal-btn"
                    onClick={() => void handleAssessment()}
                    disabled={!canAssess || assessmentRunning}
                    title={verificationValid ? '评估当前已验证草稿' : '先完成连接测试'}
                  >
                    {assessmentRunning ? '评估中...' : '评估能力（最多 4 次）'}
                  </button>
                  {assessmentRunning && (
                    <button type="button" className="modal-btn ai-cancel-btn" onClick={cancelAssessment}>
                      取消评估
                    </button>
                  )}
                </div>
              </div>

              {(assessmentRunning || assessmentStatus === 'complete') && (
                <div className="ai-assessment-progress" role={assessmentRunning ? 'status' : undefined}>
                  <div className="ai-progress-track" aria-label={`能力评估进度 ${assessmentCalls} / 4`}>
                    <span style={{ width: `${Math.min(100, assessmentCalls * 25)}%` }} />
                  </div>
                  <span>
                    {assessmentRunning
                      ? '已启动第 1 / 4 项；服务端正在串行执行，完成后显示实际调用数。'
                      : `已完成 ${assessmentCalls} / 4 次调用。`}
                  </span>
                </div>
              )}

              {assessmentStatus === 'cancelled' && (
                <p className="ai-warning">评估已取消；不会自动继续剩余场景或重新发起。</p>
              )}
              {assessmentInvalidated && !assessment && (
                <p className="ai-warning">配置已变化，原能力结果已失效；当前草稿为未评估。</p>
              )}
              {!assessment && !assessmentInvalidated && assessmentStatus === 'idle' && (
                <p className="ai-hint">当前草稿未评估；未评估或高风险都不会阻止保存。</p>
              )}

              {assessment && (
                <div className={`ai-assessment-result tier-${assessment.tier}`}>
                  <div className="ai-assessment-summary">
                    <strong>评估结果：{ASSESSMENT_TIER_LABELS[assessment.tier]}</strong>
                    <span>{formatDateTime(assessment.assessed_at)}</span>
                  </div>
                  <ul>
                    {(assessment.results ?? []).map((result) => (
                      <li key={result.scenario} className={`status-${result.status}`}>
                        <strong>{ASSESSMENT_SCENARIO_LABELS[result.scenario] ?? result.scenario}</strong>
                        <span>{ASSESSMENT_STATUS_LABELS[result.status] ?? result.status} · {result.explanation}</span>
                      </li>
                    ))}
                  </ul>
                  {assessment.usage && (
                    <p>用量：输入 {assessment.usage.input_tokens} / 输出 {assessment.usage.output_tokens} Token</p>
                  )}
                  {assessment.stopped_by_transport && (
                    <p className="ai-warning">评估因 transport/鉴权/额度问题提前停止，未执行后续场景。</p>
                  )}
                  {assessment.request_id && (
                    <details className="ai-diagnostic-details">
                      <summary>排障详情</summary>
                      <p>请求编号：{assessment.request_id}</p>
                    </details>
                  )}
                </div>
              )}
              {renderDiagnostic('能力评估失败', assessmentError)}
              <p className="ai-assessment-disclaimer">
                结果仅提示有限合同风险，不能保证所有开放剧情质量，也不评价文风或正史路线。
              </p>
            </section>
          </div>
            </section>
          </div>
        )}

        {renderDiagnostic('保存并应用失败', saveError)}

        <div className="modal-actions">
          <button type="button" className="modal-btn" onClick={handleClose} disabled={saving}>关闭</button>
          <button
            type="button"
            className="modal-btn primary"
            onClick={() => void handleSave()}
            disabled={!canSave}
            title={canSave ? '应用当前已验证草稿' : '先修正字段并测试当前草稿'}
          >
            {saving ? '保存中...' : '保存并应用'}
          </button>
        </div>
      </div>
    </div>
  )
}
