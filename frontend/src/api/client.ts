import type {
  GameState,
  StructuredDecree,
  DecreeResponse,
  SaveEntry,
  HistoryPage,
  ErrorResponse,
  DebateResult,
  Capabilities,
  DialogueResponse,
  Minister,
  DecreeType,
  CourtAssembly,
  MemorialStatus,
  MemorialResolveResponse,
  AISettings,
  AIModelListResponse,
  AIProvider,
  ChatStreamEvent,
  ChatDonePayload,
  ChatIntent,
  ChatGameOver,
  MinisterReaction,
} from '../types/game'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

interface AdvanceMonthResponse {
  state: GameState
  triggered_events: string[]
  game_over: { result: 'victory' | 'defeat'; message: string } | null
  new_ministers: Minister[]
}

class ApiError extends Error {
  status: number
  body: ErrorResponse

  constructor(status: number, body: ErrorResponse) {
    super(body.message)
    this.status = status
    this.body = body
  }
}

type DecreeStreamMessage =
  | { event: 'progress'; data: { stage: string; message: string } }
  | { event: 'narrative'; data: { chunk: string } }
  | { event: 'memorial'; data: { memorial_id: string; title: string; chunk: string } }
  | { event: 'error'; data: { status: number; detail: ErrorResponse } }
  | { event: 'final'; data: { response: DecreeResponse } }

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null
}

function normalizeErrorBody(raw: unknown, status: number): ErrorResponse {
  if (isRecord(raw)) {
    const errorCode = typeof raw.error_code === 'string' ? raw.error_code : 'network_error'
    const message = typeof raw.message === 'string' ? raw.message : `HTTP ${status}`
    const details = isRecord(raw.details) ? raw.details : null
    return { error_code: errorCode, message, details }
  }
  return { error_code: 'network_error', message: `HTTP ${status}`, details: null }
}

function normalizeStringArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

function normalizeMinisterReactions(raw: unknown): MinisterReaction[] {
  if (!Array.isArray(raw)) return []
  const reactions: MinisterReaction[] = []
  for (const item of raw) {
    if (!isRecord(item)) continue
    const minister_name = typeof item.minister_name === 'string' ? item.minister_name : ''
    const faction = typeof item.faction === 'string' ? item.faction : ''
    const reaction_type = typeof item.reaction_type === 'string' ? item.reaction_type : ''
    const reaction_text = typeof item.reaction_text === 'string' ? item.reaction_text : ''
    const loyalty_change = typeof item.loyalty_change === 'number' ? item.loyalty_change : 0
    reactions.push({
      minister_name,
      faction,
      reaction_type,
      reaction_text,
      loyalty_change,
    })
  }
  return reactions
}

function normalizeChatIntent(raw: unknown): ChatIntent {
  const intent = String(raw ?? '').trim()
  if (intent === 'query' || intent === 'advance_month') return intent
  return 'execute'
}

function normalizeChatGameOver(raw: unknown): ChatGameOver | null {
  if (!isRecord(raw)) return null
  const result = String(raw.result ?? '').trim()
  if (result !== 'victory' && result !== 'defeat') return null
  const message = typeof raw.message === 'string' ? raw.message : ''
  return { result, message }
}

function normalizeChatDonePayload(payload: Record<string, unknown>): ChatDonePayload {
  const done: ChatDonePayload = {
    reply: typeof payload.reply === 'string' ? payload.reply : '',
    state: (payload.state as GameState),
    effects_applied: typeof payload.effects_applied === 'boolean' ? payload.effects_applied : false,
    minister_reactions: normalizeMinisterReactions(payload.minister_reactions),
    triggered_events: normalizeStringArray(payload.triggered_events),
    new_ministers: normalizeStringArray(payload.new_ministers),
    game_over: normalizeChatGameOver(payload.game_over),
  }

  if (typeof payload.narrative === 'string') {
    done.narrative = payload.narrative
  }
  if ('intent' in payload) {
    done.intent = normalizeChatIntent(payload.intent)
  }
  return done
}

async function toApiError(res: Response): Promise<ApiError> {
  const raw = await res.json().catch(() => null)
  const body = isRecord(raw) && 'detail' in raw ? normalizeErrorBody(raw.detail, res.status) : normalizeErrorBody(raw, res.status)
  return new ApiError(res.status, body)
}

function parseDecreeStreamMessage(frame: string): DecreeStreamMessage | null {
  let eventName = 'message'
  const dataLines: string[] = []
  for (const rawLine of frame.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
      continue
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  if (!dataLines.length) return null
  let payload: unknown
  try {
    payload = JSON.parse(dataLines.join('\n'))
  } catch {
    return null
  }

  if (!isRecord(payload)) return null

  if (eventName === 'progress') {
    const stage = typeof payload.stage === 'string' ? payload.stage : 'processing'
    const message = typeof payload.message === 'string' ? payload.message : ''
    return { event: 'progress', data: { stage, message } }
  }
  if (eventName === 'narrative') {
    const chunk = typeof payload.chunk === 'string' ? payload.chunk : ''
    return { event: 'narrative', data: { chunk } }
  }
  if (eventName === 'memorial') {
    const memorialId = typeof payload.memorial_id === 'string' ? payload.memorial_id : ''
    const title = typeof payload.title === 'string' ? payload.title : ''
    const chunk = typeof payload.chunk === 'string' ? payload.chunk : ''
    return { event: 'memorial', data: { memorial_id: memorialId, title, chunk } }
  }
  if (eventName === 'error') {
    const status = typeof payload.status === 'number' ? payload.status : 500
    const detail = normalizeErrorBody(payload.detail, status)
    return { event: 'error', data: { status, detail } }
  }
  if (eventName === 'final' && isRecord(payload.response)) {
    return { event: 'final', data: { response: payload.response as unknown as DecreeResponse } }
  }
  return null
}

function parseChatStreamMessage(frame: string): ChatStreamEvent | null {
  let eventName = 'message'
  const dataLines: string[] = []
  for (const rawLine of frame.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
      continue
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  if (!dataLines.length) return null
  let payload: unknown
  try {
    payload = JSON.parse(dataLines.join('\n'))
  } catch {
    return null
  }
  if (!isRecord(payload)) return null

  if (eventName === 'intent') {
    const intent = normalizeChatIntent(payload.intent)
    const confidence = typeof payload.confidence === 'number' ? payload.confidence : 0
    const reason = typeof payload.reason === 'string' ? payload.reason : ''
    return { event: 'intent', data: { intent, confidence, reason } }
  }
  if (eventName === 'narrative_chunk') {
    const chunk = typeof payload.chunk === 'string' ? payload.chunk : ''
    return { event: 'narrative_chunk', data: { chunk } }
  }
  if (eventName === 'effects') {
    const summary = typeof payload.summary === 'string' ? payload.summary : ''
    const delta: Record<string, number> = {}
    if (isRecord(payload.delta)) {
      for (const [key, value] of Object.entries(payload.delta)) {
        if (typeof value === 'number') delta[key] = value
      }
    }
    return { event: 'effects', data: { delta, summary } }
  }
  if (eventName === 'reactions') {
    return {
      event: 'reactions',
      data: { minister_reactions: normalizeMinisterReactions(payload.minister_reactions) },
    }
  }
  if (eventName === 'state' && isRecord(payload.state)) {
    return { event: 'state', data: { state: payload.state as unknown as GameState } }
  }
  if (eventName === 'done') {
    const done = normalizeChatDonePayload(payload)
    return { event: 'done', data: done }
  }
  if (eventName === 'error') {
    const status = typeof payload.status === 'number' ? payload.status : 500
    const detail = normalizeErrorBody(payload.detail, status)
    return { event: 'error', data: { status, detail } }
  }
  return null
}

function consumeSseFrames<T>(
  source: string,
  parser: (frame: string) => T | null,
  onMessage: (message: T) => void,
): string {
  let buffer = source
  // Supports both LF and CRLF SSE separators.
  while (true) {
    let sepIndex = buffer.indexOf('\n\n')
    let sepLen = 2
    const crlfIndex = buffer.indexOf('\r\n\r\n')
    if (crlfIndex !== -1 && (sepIndex === -1 || crlfIndex < sepIndex)) {
      sepIndex = crlfIndex
      sepLen = 4
    }
    if (sepIndex === -1) break

    const frame = buffer.slice(0, sepIndex).trim()
    buffer = buffer.slice(sepIndex + sepLen)
    if (!frame) continue
    const message = parser(frame)
    if (message) onMessage(message)
  }
  return buffer
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') throw e
    throw new ApiError(0, { error_code: 'network_error', message: '网络连接失败，请检查后端服务', details: null })
  }
  if (!res.ok) {
    throw await toApiError(res)
  }
  return res.json()
}

export const api = {
  newGame: (signal?: AbortSignal) => request<GameState>('/game/new', { method: 'POST', signal }),

  decree: (
    decrees: StructuredDecree[],
    sourceScriptId?: string,
    freeText?: string,
    signal?: AbortSignal,
    loyaltyEffects?: [string, number][],
    stateEffects?: Record<string, number>,
  ) =>
    request<DecreeResponse>('/decree', {
      method: 'POST',
      signal,
      body: JSON.stringify({
        decrees,
        source_script_id: sourceScriptId ?? null,
        free_text: freeText ?? null,
        loyalty_effects: loyaltyEffects ?? null,
        state_effects: stateEffects ?? null,
      }),
    }),

  decreeStream: async (
    decrees: StructuredDecree[],
    sourceScriptId: string | undefined,
    freeText: string | undefined,
    onEvent: (event: DecreeStreamMessage) => void,
    loyaltyEffects?: [string, number][],
    stateEffects?: Record<string, number>,
  ): Promise<DecreeResponse> => {
    let res: Response
    try {
      res = await fetch(`${BASE}/decree/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decrees,
          source_script_id: sourceScriptId ?? null,
          free_text: freeText ?? null,
          loyalty_effects: loyaltyEffects ?? null,
          state_effects: stateEffects ?? null,
        }),
      })
    } catch {
      throw new ApiError(0, { error_code: 'network_error', message: '网络连接失败，请检查后端服务', details: null })
    }

    if (!res.ok) throw await toApiError(res)
    if (!res.body) {
      throw new ApiError(500, { error_code: 'stream_unavailable', message: '浏览器不支持流式响应', details: null })
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResponse: DecreeResponse | null = null

    const handleMessage = (event: DecreeStreamMessage) => {
      onEvent(event)
      if (event.event === 'error') {
        throw new ApiError(event.data.status, event.data.detail)
      }
      if (event.event === 'final') {
        finalResponse = event.data.response
      }
    }

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        buffer = consumeSseFrames(buffer, parseDecreeStreamMessage, handleMessage)
      }
      buffer += decoder.decode()
      buffer = consumeSseFrames(buffer, parseDecreeStreamMessage, handleMessage)
    } catch (e) {
      await reader.cancel().catch(() => { })
      throw e
    } finally {
      reader.releaseLock()
    }

    if (finalResponse) return finalResponse
    throw new ApiError(500, {
      error_code: 'stream_incomplete',
      message: '流式响应未返回最终结果',
      details: null,
    })
  },

  chatStream: async (
    message: string,
    onEvent: (event: ChatStreamEvent) => void,
  ): Promise<ChatDonePayload> => {
    let res: Response
    try {
      res = await fetch(`${BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      })
    } catch {
      throw new ApiError(0, { error_code: 'network_error', message: '网络连接失败，请检查后端服务', details: null })
    }

    if (!res.ok) throw await toApiError(res)
    if (!res.body) {
      throw new ApiError(500, { error_code: 'stream_unavailable', message: '浏览器不支持流式响应', details: null })
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let donePayload: ChatDonePayload | null = null

    const handleMessage = (event: ChatStreamEvent) => {
      onEvent(event)
      if (event.event === 'error') {
        throw new ApiError(event.data.status, event.data.detail)
      }
      if (event.event === 'done') {
        donePayload = event.data
      }
    }

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        buffer = consumeSseFrames(buffer, parseChatStreamMessage, handleMessage)
      }
      buffer += decoder.decode()
      buffer = consumeSseFrames(buffer, parseChatStreamMessage, handleMessage)
    } catch (e) {
      await reader.cancel().catch(() => { })
      throw e
    } finally {
      reader.releaseLock()
    }

    if (donePayload) return donePayload
    throw new ApiError(500, {
      error_code: 'stream_incomplete',
      message: '聊天流未返回最终结果',
      details: null,
    })
  },

  parseFreeText: (text: string) =>
    request<StructuredDecree[]>('/decree/parse', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  getState: () => request<GameState & { history_total_count: number }>('/state'),

  getHistory: (offset = 0, limit = 20) =>
    request<HistoryPage>(`/history?offset=${offset}&limit=${limit}`),

  save: (name?: string) =>
    request<{ save_id: number }>('/save', {
      method: 'POST',
      body: JSON.stringify({ name: name ?? null }),
    }),

  listSaves: () => request<SaveEntry[]>('/saves'),

  loadSave: (id: number) =>
    request<GameState & { migration_applied?: boolean; migration_note?: string }>(`/load/${id}`, { method: 'POST' }),

  deleteSave: (id: number) =>
    request<{ ok: boolean }>(`/save/${id}`, { method: 'DELETE' }),

  startDebate: (topic: string, category: DecreeType) =>
    request<DebateResult>('/debate/start', {
      method: 'POST',
      body: JSON.stringify({ topic, category }),
    }),

  silenceDebate: () =>
    request<{ state: GameState; prestige_change: number }>('/debate/silence', { method: 'POST' }),

  getCapabilities: () =>
    request<Capabilities>('/capabilities'),

  getMinisters: () =>
    request<Minister[]>('/ministers'),

  ministerDialogue: (name: string, message: string, conversationId?: string) =>
    request<DialogueResponse>(`/minister/${encodeURIComponent(name)}/dialogue`, {
      method: 'POST',
      body: JSON.stringify({ message, conversation_id: conversationId ?? null }),
    }),

  resolveMemorial: (id: string, action: MemorialStatus) =>
    request<MemorialResolveResponse>(`/memorial/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),

  // Multi-phase assembly APIs
  startAssembly: () =>
    request<CourtAssembly>('/assembly/start', { method: 'POST' }),

  startAssemblyDebate: (topic: string, decreeType?: DecreeType | null, signal?: AbortSignal) =>
    request<CourtAssembly>('/assembly/debate', {
      method: 'POST',
      signal,
      body: JSON.stringify({ topic, decree_type: decreeType ?? null }),
    }),

  startAssemblyVote: (decreeType?: DecreeType | null, signal?: AbortSignal) =>
    request<{ assembly: CourtAssembly; support_count: number; oppose_count: number; abstain_count: number }>('/assembly/vote', {
      method: 'POST',
      signal,
      body: JSON.stringify({ decree_type: decreeType ?? null }),
    }),

  finalizeAssembly: (decision: 'adopt' | 'override' | 'dismiss', signal?: AbortSignal) =>
    request<{
      assembly: CourtAssembly
      state: GameState
      majority_vote: string
      vote_counts: Record<string, number>
      faction_changes: Record<string, number>
      decree_effects?: unknown
    }>('/assembly/decree', {
      method: 'POST',
      signal,
      body: JSON.stringify({ decision }),
    }),

  imperialRage: (targetFaction: string, signal?: AbortSignal) =>
    request<{ state: GameState; assembly: CourtAssembly; effects: Record<string, number> }>('/assembly/rage', {
      method: 'POST',
      signal,
      body: JSON.stringify({ target_faction: targetFaction }),
    }),

  // Legacy assembly APIs (kept for backward compatibility)
  conveneAssembly: (topic: string, decreeType: DecreeType) =>
    request<CourtAssembly>('/court-assembly/convene', {
      method: 'POST',
      body: JSON.stringify({ topic, decree_type: decreeType }),
    }),

  adoptSuggestion: (suggestionIndex: number) =>
    request<DecreeResponse>('/court-assembly/adopt', {
      method: 'POST',
      body: JSON.stringify({ suggestion_index: suggestionIndex }),
    }),

  silenceAssembly: () =>
    request<{ state: GameState; prestige_change: number }>('/court-assembly/silence', { method: 'POST' }),

  getSettings: () =>
    request<{ rule_parse_fallback: boolean }>('/settings'),

  updateSettings: (settings: { rule_parse_fallback: boolean }) =>
    request<{ rule_parse_fallback: boolean }>('/settings', {
      method: 'POST',
      body: JSON.stringify(settings),
    }),

  getAiSettings: (provider?: AIProvider) =>
    request<AISettings>(`/settings/ai${provider ? `?provider=${encodeURIComponent(provider)}` : ''}`),

  updateAiSettings: (payload: {
    provider: AIProvider
    provider_type?: string | null
    api_key?: string | null
    base_url?: string | null
    model?: string | null
    simple_model?: string | null
    enable_thinking?: boolean | null
    enable_thinking_simple?: boolean | null
    thinking_config?: Record<string, string | boolean | number> | null
    thinking_config_simple?: Record<string, string | boolean | number> | null
  }) =>
    request<AISettings>('/settings/ai', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  deleteAiSettings: (provider: AIProvider) =>
    request<AISettings>(`/settings/ai?provider=${encodeURIComponent(provider)}`, { method: 'DELETE' }),

  listAiModels: (payload: {
    provider?: AIProvider
    provider_type?: string | null
    api_key?: string | null
    base_url?: string | null
  }) =>
    request<AIModelListResponse>('/settings/ai/models', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // 08-07-improve-ai-settings-page：真实链路探测（最小 chat completion）
  testAiConnection: (payload: {
    provider?: AIProvider
    provider_type?: string | null
    api_key?: string | null
    base_url?: string | null
    model?: string | null
  }) =>
    request<{ ok: boolean; error_code: string | null; message: string; latency_ms: number }>('/settings/ai/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  advanceMonth: (signal?: AbortSignal) => request<AdvanceMonthResponse>('/advance-month', { method: 'POST', signal }),
}

export { ApiError }
export type { DecreeStreamMessage, ChatStreamEvent, AdvanceMonthResponse }
