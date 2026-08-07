// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import ModeSelectPage from '../pages/ModeSelectPage'
import { api, ApiError } from '../api/client'
import type { GameState, GameEvent } from '../types/game'

const getStateMock = vi.mocked(api.getState)
const navigateMock = vi.fn()

vi.mock('../api/client', () => ({
  api: { getState: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number
    body: { message: string }
    constructor(status: number, body: { message: string }) {
      super(body.message)
      this.status = status
      this.body = body
    }
  },
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
}))

function blockingEvent(): GameEvent {
  return {
    name: '至正十六年·集庆定鼎',
    description: '朱元璋克集庆，改应天府，立足江东。',
    urgency: '高',
    triggered_year: 1356,
    triggered_month: 3,
    rich_description: '**至正十六年，三月。**',
    is_blocking: true,
    is_scripted: true,
    script_id: 'yingtian-founding-1356-03',
    choices: [
      { label: '整肃军纪，安抚民心', description: '立即着手整饬军纪，招揽贤才', decrees: [] },
    ],
  }
}

function governanceState(): GameState {
  return {
    time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    phase: 'governance',
    chapter: 'warlord',
    chapter_turns: 0,
    national_treasury: 20, imperial_treasury: 10, grain: 500,
    population: 15000, military_strength: 40,
    civil_morale: 60, military_morale: 70, court_prestige: 75,
    factions: [], regions: [], ministers: [], active_events: [blockingEvent()],
    history_log: [], decree_count: 0, event_cooldowns: {},
    resolved_script_ids: [],
    decrees_this_month: {},
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  getStateMock.mockResolvedValue({ ...governanceState(), history_total_count: 0 })
})

afterEach(() => {
  cleanup()
})

describe('ModeSelectPage 元末文案', () => {
  it('渲染元末开局文案与阻断事件', async () => {
    const { container } = render(<ModeSelectPage />)

    expect(await screen.findByText('元末乱世 · 起局时刻')).toBeTruthy()
    expect(screen.getByText('主公欲以何种方式统驭朝局？')).toBeTruthy()
    expect(screen.getByText('至正十六年·集庆定鼎')).toBeTruthy()
    expect(container.textContent).toContain('至正十六年')
    expect(navigateMock).not.toHaveBeenCalled()
  })

  it('无崇祯遗留文案', async () => {
    const { container } = render(<ModeSelectPage />)
    await screen.findByText('元末乱世 · 起局时刻')

    expect(container.textContent).not.toContain('崇祯')
  })

  it('后端报错时展示错误信息且不跳转', async () => {
    getStateMock.mockRejectedValue(new ApiError(500, {
      message: '朝局读取失败',
      error_code: 'internal',
      details: null,
    }))

    render(<ModeSelectPage />)
    expect(await screen.findByText('朝局读取失败')).toBeTruthy()
    expect(navigateMock).not.toHaveBeenCalled()
  })
})
