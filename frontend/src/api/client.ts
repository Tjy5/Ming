import type { GameState, StructuredDecree, DecreeResponse, SaveEntry, HistoryPage, ErrorResponse, DebateResult, Capabilities, Minister, DecreeType } from '../types/game'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

class ApiError extends Error {
  constructor(public status: number, public body: ErrorResponse) {
    super(body.message)
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

  decree: (decrees: StructuredDecree[], sourceScriptId?: string) =>
    request<DecreeResponse>('/decree', {
      method: 'POST',
      body: JSON.stringify({ decrees, source_script_id: sourceScriptId ?? null }),
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
}

export { ApiError }
