// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import LifeStoryPage from '../pages/LifeStoryPage'
import { trpgApi } from '../api/trpg'
import { api } from '../api/client'
import type { ApiCharacterSheet, ActResponse } from '../types/trpg'
import type { GameState } from '../types/game'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const getCharacterMock = vi.mocked(trpgApi.getCharacter)
const actMock = vi.mocked(trpgApi.act)
const getStateMock = vi.mocked(api.getState)

let storeState: GameState | null
const setStateMock = vi.fn()

vi.mock('../api/trpg', () => ({
  trpgApi: {
    getCharacter: vi.fn(),
    act: vi.fn(),
  },
}))

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

vi.mock('../hooks/store', () => ({
  useStore: (selector: (s: unknown) => unknown) => selector({ state: storeState, setState: setStateMock }),
}))

function characterSheet(): ApiCharacterSheet {
  return {
    name: '朱元璋',
    is_player: true,
    background: '濠州钟离人，自幼家贫，投身义军。',
    attrs: { 政治: 62, 军事: 71, 学识: 45, 交际: 58, 体力: 66, 胆略: 74 },
    skills: { 统兵: 68, 察言观色: 52 },
    traits: ['雄猜果决'],
    status: ['风餐露宿'],
    skill_points: 6,
    growth_points: 3,
  }
}

function actResponse(overrides: Partial<ActResponse> = {}): ActResponse {
  return {
    roll: { roll: 37, target: 55, tier: 'success', dc: 0, attr_name: '胆略', skill_name: null },
    narrative: '**令行禁止**，士卒肃然。',
    options: [{ option_id: 'opt-2', label: '犒赏三军', description: '开仓放粮，提振士气' }],
    state_changes: {},
    source: 'ai',
    phase: 'life_story',
    chapter: 'yingtian',
    chapter_title: '集庆立基',
    chapter_turns: 1,
    pacing: { turns_taken: 1, min_turns: 1, max_turns: 3, may_advance: true, must_advance: false },
    frozen: false,
    growth: null,
    convergence_hook: null,
    time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    ...overrides,
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
    factions: [], regions: [], ministers: [], active_events: [],
    history_log: [], decree_count: 0, event_cooldowns: {},
    resolved_script_ids: [],
    decrees_this_month: {},
  }
}

beforeEach(() => {
  // jsdom 不实现 scrollIntoView，NarrativeFeed 滚动定位需要桩
  Element.prototype.scrollIntoView = vi.fn()
  vi.clearAllMocks()
  storeState = {
    ...governanceState(),
    phase: 'life_story',
  }
  getCharacterMock.mockResolvedValue({
    player: characterSheet(),
    key_figures: [],
    growth_log: [],
    phase: 'life_story',
    chapter: 'yingtian',
    chapter_title: '集庆立基',
  })
  getStateMock.mockResolvedValue({ ...governanceState(), history_total_count: 0 })
})

afterEach(() => {
  cleanup()
})

async function submitFreeText(text: string): Promise<void> {
  const input = screen.getByPlaceholderText(/自由行动/)
  await act(async () => {
    fireEvent.change(input, { target: { value: text } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)
  })
}

describe('LifeStoryPage 渲染与选项交互', () => {
  it('渲染角色卡、篇章信息与章节标题', async () => {
    render(<LifeStoryPage />)

    expect(await screen.findByText('角色卡 · 朱元璋')).toBeTruthy()
    expect(screen.getByText(/濠州钟离人/)).toBeTruthy()
    expect(screen.getByText('集庆立基')).toBeTruthy()
    expect(screen.getByText('成长点')).toBeTruthy()
  })

  it('自由行动提交 → 调用 act → 叙事流更新', async () => {
    actMock.mockResolvedValue(actResponse())
    render(<LifeStoryPage />)

    await submitFreeText('趁夜色翻墙，去镇上讨口饭吃')
    expect(actMock).toHaveBeenCalledTimes(1)
    expect(actMock).toHaveBeenCalledWith({ action_text: '趁夜色翻墙，去镇上讨口饭吃' })

    expect(await screen.findByText('令行禁止', { exact: false })).toBeTruthy()
    expect(screen.getByText('成功 · 胆略 · 骰面 37 / 目标 55')).toBeTruthy()
    expect(screen.getByText('犒赏三军')).toBeTruthy()
  })

  it('点击分支选项 → act 调用 → 叙事流继续追加', async () => {
    actMock
      .mockResolvedValueOnce(actResponse())
      .mockResolvedValueOnce(actResponse({
        narrative: '**犒赏既毕**，士气大振。',
        options: [],
        chapter_turns: 2,
      }))

    render(<LifeStoryPage />)
    await submitFreeText('先整军')
    const optionBtn = await screen.findByText('犒赏三军')
    await act(async () => {
      fireEvent.click(optionBtn)
    })

    expect(actMock).toHaveBeenCalledTimes(2)
    expect(actMock).toHaveBeenLastCalledWith({
      action_text: '犒赏三军——开仓放粮，提振士气',
    })
    expect(await screen.findByText('犒赏既毕', { exact: false })).toBeTruthy()
  })

  it('act 响应 phase 切换（life_story → governance）后展示过渡剧情', async () => {
    actMock.mockResolvedValue(actResponse({
      narrative: '局势已定，改元称制，新的篇章由此展开。',
      options: [],
      phase: 'governance',
      chapter: 'governance',
      chapter_title: '应天称制',
    }))

    render(<LifeStoryPage />)
    await submitFreeText('开府建衙，定都应天')

    expect(await screen.findByText('时局已变 · 新的篇章')).toBeTruthy()
    expect(getStateMock).toHaveBeenCalled()
    expect(screen.getByText('进入治理模拟')).toBeTruthy()
    expect(actMock).toHaveBeenCalledWith({ action_text: '开府建衙，定都应天' })
  })

  it('无角色卡时显示空态提示', async () => {
    getCharacterMock.mockResolvedValue({
      player: null,
      key_figures: [],
      growth_log: [],
      phase: 'life_story',
      chapter: 'yingtian',
      chapter_title: '集庆立基',
    })

    render(<LifeStoryPage />)
    expect(await screen.findByText('角色卡尚未生成…')).toBeTruthy()
  })
})
