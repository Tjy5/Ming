// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api/client'
import AiSettingsModal from '../components/AiSettingsModal'
import type {
  AISettings,
  AISettingsAssessmentResponse,
  AISettingsTestResponse,
  ErrorResponse,
} from '../types/game'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

vi.mock('../api/client', () => ({
  api: {
    getAiSettings: vi.fn(),
    updateAiSettings: vi.fn(),
    deleteAiSettings: vi.fn(),
    listAiModels: vi.fn(),
    testAiConnection: vi.fn(),
    assessAiCapability: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number
    body: ErrorResponse

    constructor(status: number, body: ErrorResponse) {
      super(body.message)
      this.status = status
      this.body = body
    }
  },
}))

const getAiSettingsMock = vi.mocked(api.getAiSettings)
const updateAiSettingsMock = vi.mocked(api.updateAiSettings)
const testAiConnectionMock = vi.mocked(api.testAiConnection)
const assessAiCapabilityMock = vi.mocked(api.assessAiCapability)

function effectiveSettings(overrides: Partial<AISettings> = {}): AISettings {
  return {
    provider: 'openai',
    provider_type: 'openai',
    api_key: '********',
    base_url: 'https://api.example.com/v1',
    model: 'main-model',
    simple_model: null,
    enable_thinking: false,
    enable_thinking_simple: false,
    thinking_config: null,
    thinking_config_simple: null,
    provider_options: ['openai', 'google', 'h', 'Z'],
    sources: {
      provider: 'saved',
      api_key: 'saved',
      base_url: 'saved',
      model: 'saved',
    },
    effective: true,
    status: 'effective',
    assessment: null,
    ...overrides,
  }
}

function testResponse(overrides: Partial<AISettingsTestResponse> = {}): AISettingsTestResponse {
  return {
    ok: true,
    message: '实际生成可用，当前草稿已验证。',
    latency_ms: 321,
    request_id: 'ai_test_request',
    verification_token: 'verification-token-1234567890',
    expires_at: '2099-08-09T12:00:00Z',
    verified_config: {
      provider: 'openai',
      provider_type: 'openai',
      base_url: 'https://api.example.com/v1',
      model: 'main-model',
      simple_model: null,
      enable_thinking: false,
      enable_thinking_simple: false,
      thinking_config: null,
      thinking_config_simple: null,
    },
    ...overrides,
  }
}

function highRiskAssessment(): AISettingsAssessmentResponse {
  return {
    tier: 'high_risk',
    calls_completed: 4,
    usage: { input_tokens: 80, output_tokens: 40 },
    assessed_at: '2026-08-09T10:00:00Z',
    validator_version: 'v1',
    stopped_by_transport: false,
    config_matches: true,
    request_id: 'ai_assess_request',
    results: [
      { scenario: 'structured_schema', status: 'pass', explanation: '结构完整。' },
      { scenario: 'state_grounding', status: 'warn', explanation: '状态引用有限。' },
      { scenario: 'causal_adjudication', status: 'fail', explanation: '长期风险缺失。' },
      { scenario: 'short_memory', status: 'pass', explanation: '事实保持。' },
    ],
  }
}

function apiError(overrides: Partial<ErrorResponse> = {}): ApiError {
  return new ApiError(502, {
    error_code: 'invalid_api_key',
    message: '认证失败，当前 API Key 无法使用。',
    details: null,
    fix_hint: '重新复制 API Key。',
    request_id: 'ai_error_request',
    provider_summary: 'HTTP 401 · AuthenticationError · provider request upstream_1',
    retryable: false,
    ...overrides,
  })
}

async function renderModal(onSaved = vi.fn()) {
  const onClose = vi.fn()
  render(<AiSettingsModal onClose={onClose} onSaved={onSaved} />)
  expect(await screen.findByText('当前已生效')).toBeTruthy()
  return { onClose, onSaved }
}

beforeEach(() => {
  vi.clearAllMocks()
  getAiSettingsMock.mockResolvedValue(effectiveSettings())
  updateAiSettingsMock.mockResolvedValue(effectiveSettings())
})

afterEach(() => {
  cleanup()
})

describe('AiSettingsModal verification and apply lifecycle', () => {
  it('requires one real test, carries the full draft, then applies with the issued token', async () => {
    const onSaved = vi.fn()
    testAiConnectionMock.mockResolvedValue(testResponse())
    await renderModal(onSaved)

    const saveButton = screen.getByRole('button', { name: '保存并应用' }) as HTMLButtonElement
    expect(saveButton.disabled).toBe(true)
    expect(screen.getByText(/一次极少量 Token/)).toBeTruthy()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '测试连接（1 次）' }))
    })

    expect(await screen.findByText('草稿已验证')).toBeTruthy()
    expect(testAiConnectionMock).toHaveBeenCalledTimes(1)
    expect(testAiConnectionMock.mock.calls[0][0]).toEqual({
      provider: 'openai',
      provider_type: 'openai',
      api_key: '********',
      base_url: 'https://api.example.com/v1',
      model: 'main-model',
      simple_model: null,
      enable_thinking: false,
      enable_thinking_simple: false,
      thinking_config: null,
      thinking_config_simple: null,
    })
    expect(testAiConnectionMock.mock.calls[0][1]).toBeInstanceOf(AbortSignal)
    expect(saveButton.disabled).toBe(false)

    await act(async () => {
      fireEvent.click(saveButton)
    })

    expect(updateAiSettingsMock).toHaveBeenCalledTimes(1)
    expect(updateAiSettingsMock.mock.calls[0][0]).toMatchObject({
      provider: 'openai',
      model: 'main-model',
      verification_token: 'verification-token-1234567890',
    })
    expect(onSaved).toHaveBeenCalledWith('AI 配置已生效：OpenAI / main-model')
  })

  it('invalidates verification and assessment immediately when any bound field changes', async () => {
    testAiConnectionMock.mockResolvedValue(testResponse())
    assessAiCapabilityMock.mockResolvedValue(highRiskAssessment())
    await renderModal()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '测试连接（1 次）' }))
    })
    await screen.findByText('草稿已验证')

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '评估能力（最多 4 次）' }))
    })
    expect(await screen.findByText('评估结果：高风险')).toBeTruthy()
    expect((screen.getByRole('button', { name: '保存并应用' }) as HTMLButtonElement).disabled).toBe(false)
    expect(assessAiCapabilityMock.mock.calls[0][0]).not.toHaveProperty('verification_token')

    fireEvent.change(screen.getByLabelText('主模型', { selector: 'input' }), {
      target: { value: 'changed-model' },
    })

    expect(screen.getByText(/配置已变化，原能力结果已失效/)).toBeTruthy()
    expect(screen.queryByText('草稿已验证')).toBeNull()
    expect(screen.queryByText('评估结果：高风险')).toBeNull()
    expect((screen.getByRole('button', { name: '保存并应用' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('expires an already-returned token and never enables apply', async () => {
    testAiConnectionMock.mockResolvedValue(testResponse({ expires_at: '2000-01-01T00:00:00Z' }))
    await renderModal()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '测试连接（1 次）' }))
    })

    expect(await screen.findByText('草稿验证已过期，请重新测试。')).toBeTruthy()
    expect((screen.getByRole('button', { name: '保存并应用' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('prevents duplicate in-flight tests and supports cancel followed by an immediate retry', async () => {
    const signals: AbortSignal[] = []
    testAiConnectionMock.mockImplementation((_payload, signal) => new Promise((_resolve, reject) => {
      if (!signal) throw new Error('missing AbortSignal')
      signals.push(signal)
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    }))
    await renderModal()

    const testButton = screen.getByRole('button', { name: '测试连接（1 次）' })
    fireEvent.click(testButton)
    fireEvent.click(testButton)
    expect(testAiConnectionMock).toHaveBeenCalledTimes(1)

    fireEvent.click(await screen.findByRole('button', { name: '取消测试' }))
    expect(await screen.findByText(/测试已取消/)).toBeTruthy()
    expect(signals[0].aborted).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: '测试连接（1 次）' }))
    expect(testAiConnectionMock).toHaveBeenCalledTimes(2)
    expect(signals[1].aborted).toBe(false)
  })

  it('keeps assessment optional, shows real progress/results, and cancels without consuming save permission', async () => {
    testAiConnectionMock.mockResolvedValue(testResponse())
    let assessmentSignal: AbortSignal | undefined
    assessAiCapabilityMock.mockImplementation((_payload, signal) => new Promise((_resolve, reject) => {
      assessmentSignal = signal
      signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    }))
    await renderModal()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '测试连接（1 次）' }))
    })
    await screen.findByText('草稿已验证')

    fireEvent.click(screen.getByRole('button', { name: '评估能力（最多 4 次）' }))
    expect(await screen.findByText(/已启动第 1 \/ 4 项/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '取消评估' }))

    expect(await screen.findByText(/评估已取消/)).toBeTruthy()
    expect(assessmentSignal?.aborted).toBe(true)
    expect((screen.getByRole('button', { name: '保存并应用' }) as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('AiSettingsModal validation and safe diagnostics', () => {
  it('rejects non-HTTPS/private endpoints and missing key/model before any paid test', async () => {
    await renderModal()
    const baseInput = screen.getByLabelText('Base URL')
    const keyInput = screen.getByLabelText('API Key')
    const modelInput = screen.getByLabelText('主模型', { selector: 'input' })

    fireEvent.change(baseInput, { target: { value: 'http://127.0.0.1:8000/v1' } })
    expect(screen.getByText('只支持公网 HTTPS Base URL。')).toBeTruthy()
    fireEvent.change(baseInput, { target: { value: 'https://192.168.1.20/v1' } })
    expect(screen.getByText(/必须指向公网地址/)).toBeTruthy()
    fireEvent.change(keyInput, { target: { value: '' } })
    fireEvent.change(modelInput, { target: { value: '' } })

    expect(screen.getByText('API Key 必填。')).toBeTruthy()
    expect(screen.getByText('主模型必填。')).toBeTruthy()
    expect((screen.getByRole('button', { name: '测试连接（1 次）' }) as HTMLButtonElement).disabled).toBe(true)
    expect(testAiConnectionMock).not.toHaveBeenCalled()
  })

  it('uses server diagnostics, keeps details folded, and separates test errors from save errors', async () => {
    testAiConnectionMock.mockRejectedValueOnce(apiError())
    await renderModal()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '测试连接（1 次）' }))
    })

    expect(await screen.findByText('认证失败，当前 API Key 无法使用。')).toBeTruthy()
    expect(screen.getByText('建议：重新复制 API Key。')).toBeTruthy()
    const details = screen.getByText('排障详情').closest('details') as HTMLDetailsElement
    expect(details.open).toBe(false)
    fireEvent.click(screen.getByText('排障详情'))
    expect(details.open).toBe(true)
    expect(screen.getByText(/请求编号：ai_error_request/)).toBeTruthy()
    expect(screen.getByText(/HTTP 401 · AuthenticationError/)).toBeTruthy()

    testAiConnectionMock.mockResolvedValueOnce(testResponse())
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '测试连接（1 次）' }))
    })
    await screen.findByText('草稿已验证')
    updateAiSettingsMock.mockRejectedValueOnce(apiError({
      error_code: 'ai_settings_conflict',
      message: 'AI 配置文件在保存期间被其他操作修改。',
      fix_hint: '重新加载设置后再保存。',
      request_id: 'ai_save_request',
      provider_summary: null,
      retryable: true,
    }))

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '保存并应用' }))
    })

    expect(await screen.findByText('保存并应用失败')).toBeTruthy()
    expect(screen.getByText('AI 配置文件在保存期间被其他操作修改。')).toBeTruthy()
    expect(screen.queryByText('连接测试失败')).toBeNull()
  })
})
