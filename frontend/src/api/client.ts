import type { GameState, StructuredDecree, DecreeResponse, SaveEntry, HistoryPage, ErrorResponse, DebateResult, Capabilities, Minister, DecreeType, CourtAssembly, MemorialStatus } from '../types/game'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

class ApiError extends Error {
  status: number
  body: ErrorResponse

  constructor(status: number, body: ErrorResponse) {
    super(body.message)
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError(0, { error_code: 'network_error', message: '网络连接失败，请检查后端服务', details: null })
  }
  if (!res.ok) {
    const raw = await res.json().catch(() => null)
    const body = raw?.detail ?? raw ?? { error_code: 'network_error', message: `HTTP ${res.status}` }
    throw new ApiError(res.status, body)
  }
  return res.json()
}

export const api = {
  newGame: () => request<GameState>('/game/new', { method: 'POST' }),

  decree: (decrees: StructuredDecree[], sourceScriptId?: string, freeText?: string) =>
    request<DecreeResponse>('/decree', {
      method: 'POST',
      body: JSON.stringify({
        decrees,
        source_script_id: sourceScriptId ?? null,
        free_text: freeText ?? null,
      }),
    }),

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

  resolveMemorial: (id: string, action: MemorialStatus) =>
    request<{ state: GameState; action: string }>(`/memorial/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),

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
}

export { ApiError }
