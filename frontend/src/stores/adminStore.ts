import { create } from 'zustand'

import type { Minister } from '../types/game'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

export type AdminTab = 'ministers' | 'events' | 'positions' | 'backup'

export interface AdminPosition {
  name: string
  category: string
  weight: number
  unique: boolean
  aliases: string[]
  holders: string[]
}

export interface AdminEventChoice {
  label: string
  description: string
  decrees: Array<Record<string, unknown>>
  loyalty_effects: [string, number][]
  state_effects: Record<string, number>
}

export interface AdminEvent {
  script_id: string
  trigger_year: number
  trigger_month: number
  title: string
  is_blocking: boolean
  rich_description: string
  historical_hint: string
  condition: Record<string, unknown> | null
  choices: AdminEventChoice[]
}

export interface AdminExportBundle {
  ministers: Minister[]
  events: AdminEvent[]
  positions: Record<string, {
    category: string
    weight: number
    unique: boolean
    aliases: string[]
  }>
  meta?: Record<string, unknown>
}

export interface AdminImportValidationResult {
  ok: boolean
  ministers_count: number
  events_count: number
}

class AdminApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function normalizeErrorMessage(raw: unknown, fallback: string): string {
  if (raw && typeof raw === 'object') {
    const detail = (raw as { detail?: unknown }).detail
    if (detail && typeof detail === 'object') {
      const message = (detail as { message?: unknown }).message
      if (typeof message === 'string' && message.trim()) return message
    }
    const message = (raw as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message
  }
  return fallback
}

async function adminRequest<T>(
  path: string,
  password: string,
  init?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Admin-Password': password,
    ...(init?.headers as Record<string, string> | undefined),
  }
  const response = await fetch(`${BASE}/admin${path}`, {
    ...init,
    headers,
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new AdminApiError(response.status, normalizeErrorMessage(body, `HTTP ${response.status}`))
  }

  return response.json() as Promise<T>
}

interface AdminState {
  isAuthenticated: boolean
  password: string
  activeTab: AdminTab
  searchQuery: string
  ministers: Minister[]
  events: AdminEvent[]
  positions: AdminPosition[]
  loading: boolean
  error: string | null
  initialized: boolean

  login: (password: string) => Promise<boolean>
  logout: () => void
  setActiveTab: (tab: AdminTab) => void
  setSearchQuery: (query: string) => void
  clearError: () => void

  loadAll: () => Promise<void>
  fetchMinisters: () => Promise<void>
  fetchEvents: () => Promise<void>
  fetchPositions: () => Promise<void>

  createMinister: (minister: Minister) => Promise<void>
  updateMinister: (name: string, minister: Minister) => Promise<void>
  deleteMinister: (name: string) => Promise<void>

  createEvent: (event: AdminEvent) => Promise<void>
  updateEvent: (scriptId: string, event: AdminEvent) => Promise<void>
  deleteEvent: (scriptId: string) => Promise<void>

  exportData: () => Promise<AdminExportBundle>
  validateImportData: (bundle: AdminExportBundle) => Promise<AdminImportValidationResult>
  importData: (bundle: AdminExportBundle) => Promise<void>
}

export const useAdminStore = create<AdminState>((set, get) => ({
  isAuthenticated: false,
  password: '',
  activeTab: 'ministers',
  searchQuery: '',
  ministers: [],
  events: [],
  positions: [],
  loading: false,
  error: null,
  initialized: false,

  login: async (password: string) => {
    const trimmed = password.trim()
    if (!trimmed) {
      set({ error: '请输入管理员密码' })
      return false
    }
    set({ loading: true, error: null })
    try {
      await adminRequest<{ ok: boolean }>('/verify', trimmed)
      set({
        isAuthenticated: true,
        password: trimmed,
        loading: false,
      })
      return true
    } catch (error) {
      set({
        loading: false,
        isAuthenticated: false,
        error: error instanceof Error ? error.message : '登录失败',
      })
      return false
    }
  },

  logout: () => {
    set({
      isAuthenticated: false,
      password: '',
      ministers: [],
      events: [],
      positions: [],
      initialized: false,
      error: null,
      searchQuery: '',
    })
  },

  setActiveTab: (tab) => set({ activeTab: tab }),
  setSearchQuery: (query) => set({ searchQuery: query }),
  clearError: () => set({ error: null }),

  loadAll: async () => {
    const { password } = get()
    if (!password) return
    set({ loading: true, error: null })
    try {
      const [ministers, events, positions] = await Promise.all([
        adminRequest<Minister[]>('/ministers', password),
        adminRequest<AdminEvent[]>('/events', password),
        adminRequest<AdminPosition[]>('/positions', password),
      ])
      set({
        ministers,
        events,
        positions,
        loading: false,
        initialized: true,
      })
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : '加载管理数据失败',
      })
    }
  },

  fetchMinisters: async () => {
    const { password } = get()
    if (!password) return
    const ministers = await adminRequest<Minister[]>('/ministers', password)
    set({ ministers })
  },

  fetchEvents: async () => {
    const { password } = get()
    if (!password) return
    const events = await adminRequest<AdminEvent[]>('/events', password)
    set({ events })
  },

  fetchPositions: async () => {
    const { password } = get()
    if (!password) return
    const positions = await adminRequest<AdminPosition[]>('/positions', password)
    set({ positions })
  },

  createMinister: async (minister) => {
    const { password } = get()
    await adminRequest('/ministers', password, {
      method: 'POST',
      body: JSON.stringify(minister),
    })
    await get().fetchMinisters()
    await get().fetchPositions()
  },

  updateMinister: async (name, minister) => {
    const { password } = get()
    await adminRequest(`/ministers/${encodeURIComponent(name)}`, password, {
      method: 'PUT',
      body: JSON.stringify(minister),
    })
    await get().fetchMinisters()
    await get().fetchPositions()
  },

  deleteMinister: async (name) => {
    const { password } = get()
    await adminRequest(`/ministers/${encodeURIComponent(name)}`, password, {
      method: 'DELETE',
    })
    await get().fetchMinisters()
    await get().fetchPositions()
  },

  createEvent: async (event) => {
    const { password } = get()
    await adminRequest('/events', password, {
      method: 'POST',
      body: JSON.stringify(event),
    })
    await get().fetchEvents()
  },

  updateEvent: async (scriptId, event) => {
    const { password } = get()
    await adminRequest(`/events/${encodeURIComponent(scriptId)}`, password, {
      method: 'PUT',
      body: JSON.stringify(event),
    })
    await get().fetchEvents()
  },

  deleteEvent: async (scriptId) => {
    const { password } = get()
    await adminRequest(`/events/${encodeURIComponent(scriptId)}`, password, {
      method: 'DELETE',
    })
    await get().fetchEvents()
  },

  exportData: async () => {
    const { password } = get()
    return adminRequest<AdminExportBundle>('/export', password)
  },

  validateImportData: async (bundle) => {
    const { password } = get()
    return adminRequest<AdminImportValidationResult>('/import/validate', password, {
      method: 'POST',
      body: JSON.stringify(bundle),
    })
  },

  importData: async (bundle) => {
    const { password } = get()
    await adminRequest('/import', password, {
      method: 'POST',
      body: JSON.stringify(bundle),
    })
    await get().loadAll()
  },
}))

export { AdminApiError }
