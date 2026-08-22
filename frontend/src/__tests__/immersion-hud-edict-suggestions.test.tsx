// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { cleanup, render, screen, fireEvent } from '@testing-library/react'
import ImperialEdictModal from '../components/ImperialEdictModal'
import type { GameState, Region } from '../types/game'

afterEach(cleanup)

function makeMockState(regions: Partial<Region>[] = [], treasury = 500, grain = 2000): GameState {
  const defaultRegions: Region[] = [
    {
      name: '两淮',
      garrison: 30000,
      stability: 80,
      disaster_level: 20,
      control: '朝廷',
      threat: 'none',
      rebellion_risk: 10,
      civil_morale: 75,
      tax_collected: 8000,
      tax_contribution: 'medium',
      tax_rate: 0.5,
      ...regions[0],
    },
  ]

  return {
    time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    phase: 'governance',
    chapter: 'warlord',
    chapter_turns: 0,
    national_treasury: treasury,
    imperial_treasury: 100,
    grain: grain,
    population: 8000,
    military_strength: 200,
    civil_morale: 60,
    military_morale: 60,
    court_prestige: 55,
    ministers: [],
    factions: [],
    regions: defaultRegions,
    active_events: [],
    history_log: [],
    decree_count: 0,
    decrees_this_month: {},
    event_cooldowns: {},
    resolved_script_ids: [],
    memorials: [],
  }
}

describe('immersion HUD edict pain points and suggestions', () => {
  it('derives ranked pain points and prefill-only suggestions for targeted region in crisis', () => {
    const state = makeMockState([
      {
        name: '河南江北行省',
        disaster_level: 65,
        rebellion_risk: 55,
        threat: '元军',
        civil_morale: 10,
      },
    ], 500, 2000)

    const onDecree = vi.fn()
    const onFreeText = vi.fn()

    render(
      <ImperialEdictModal
        isOpen={true}
        onClose={vi.fn()}
        state={state}
        loading={false}
        hasBlockingEvent={false}
        targetRegion="河南江北行省"
        targetRegionMembers={['两淮', '应天']}
        onDecree={onDecree}
        onFreeText={onFreeText}
      />,
    )

    // Verify pain points are derived
    expect(screen.getByText(/灾情严重（灾害等级 65）/)).toBeTruthy()
    expect(screen.getByText(/动乱失序（叛乱风险 55%/)).toBeTruthy()
    expect(screen.getByText(/外患威胁：元军/)).toBeTruthy()

    // Clicking prefill suggestion should only set text / modal state, NOT submit
    const suggestBtn = screen.getByRole('button', { name: /预填建议：【河南江北行省】开仓赈济/ })
    fireEvent.click(suggestBtn)

    expect(onDecree).not.toHaveBeenCalled()
    expect(onFreeText).not.toHaveBeenCalled()
  })

  it('displays "局势平稳" when target region has no critical pain points', () => {
    const calmState = makeMockState([
      {
        name: '河南江北行省',
        disaster_level: 10,
        rebellion_risk: 10,
        threat: 'none',
        civil_morale: 80,
      },
    ])

    render(
      <ImperialEdictModal
        isOpen={true}
        onClose={vi.fn()}
        state={calmState}
        loading={false}
        hasBlockingEvent={false}
        targetRegion="河南江北行省"
        onDecree={vi.fn()}
        onFreeText={vi.fn()}
      />,
    )

    expect(screen.getByText(/局势平稳（该行政区各项指标平稳/)).toBeTruthy()
  })

  it('keeps draft intact and displays error message when decree submission fails', async () => {
    const state = makeMockState()
    const onFreeText = vi.fn().mockReturnValue(Promise.resolve('national_treasury_insufficient'))
    const onClose = vi.fn()

    render(
      <ImperialEdictModal
        isOpen={true}
        onClose={onClose}
        state={state}
        loading={false}
        hasBlockingEvent={false}
        targetRegion="两淮"
        onDecree={vi.fn()}
        onFreeText={onFreeText}
      />,
    )

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '拨付银两' } })

    fireEvent.click(screen.getByRole('button', { name: /御批 · 颁布诏书/ }))

    // Modal is NOT closed, draft text is preserved and error message is displayed
    const errorAlert = await screen.findByText(/政令提交未完成：national_treasury_insufficient，草稿已保留。/)
    expect(errorAlert).toBeTruthy()
    expect(onClose).not.toHaveBeenCalled()
    expect(textarea.value).toBe('拨付银两')
  })
})
