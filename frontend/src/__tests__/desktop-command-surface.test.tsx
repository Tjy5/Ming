// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Ck3EventFeed from '../components/Ck3EventFeed'
import ImperialEdictModal from '../components/ImperialEdictModal'
import CommandHud from '../components/CommandHud'
import ResourceBar from '../components/ResourceBar'
import type { GameEvent, GameState } from '../types/game'

function gameState(): GameState {
  return {
    time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    phase: 'governance', chapter: 'warlord', chapter_turns: 0,
    national_treasury: 500, imperial_treasury: 100, grain: 2000, population: 8000,
    military_strength: 200, civil_morale: 60, military_morale: 60, court_prestige: 55,
    ministers: [], factions: [], regions: [], active_events: [], history_log: [],
    decree_count: 0, decrees_this_month: {}, event_cooldowns: {}, resolved_script_ids: [],
  }
}

function event(overrides: Partial<GameEvent> = {}): GameEvent {
  return {
    name: '漕运迟滞',
    description: '漕粮未能如期抵达。',
    urgency: '中',
    is_scripted: false,
    is_blocking: false,
    choices: [],
    ...overrides,
  } as GameEvent
}

afterEach(cleanup)

describe('desktop command and report surfaces', () => {
  it('keeps global tool callbacks and CK3 alert badges distinct behind accessible icon commands', () => {
    const onSave = vi.fn()
    const onNewGame = vi.fn()
    const onOpenContinuity = vi.fn()
    const onMemorialClick = vi.fn()
    const onBlockingEventClick = vi.fn()
    render(
      <ResourceBar
        state={gameState()}
        prevState={null}
        pendingMemorials={2}
        onMemorialClick={onMemorialClick}
        blockingEvents={1}
        onBlockingEventClick={onBlockingEventClick}
        onSave={onSave}
        onShowSaves={() => {}}
        onNewGame={onNewGame}
        onOpenAiSettings={() => {}}
        onOpenChat={() => {}}
        onOpenContinuity={onOpenContinuity}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '宫禁设置' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '存档' }))
    fireEvent.click(screen.getByRole('button', { name: '宫禁设置' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '连续性分支' }))
    fireEvent.click(screen.getByRole('button', { name: '宫禁设置' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '开始新局' }))
    fireEvent.click(screen.getByRole('button', { name: /奏折待批/ }))
    fireEvent.click(screen.getByRole('button', { name: /关键剧情待决/ }))

    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onOpenContinuity).toHaveBeenCalledTimes(1)
    expect(onNewGame).toHaveBeenCalledTimes(1)
    expect(onMemorialClick).toHaveBeenCalledTimes(1)
    expect(onBlockingEventClick).toHaveBeenCalledTimes(1)
  })

  it('distinguishes expandable reports from scripted event actions in CK3EventFeed', () => {
    const onScriptClick = vi.fn()
    render(
      <Ck3EventFeed
        events={[
          event(),
          event({ name: '军议急报', is_scripted: true, choices: [{ label: '固守', description: '据城固守', decrees: [] }] }),
        ]}
        onScriptClick={onScriptClick}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /漕运迟滞/ }))
    expect(document.querySelector('.ck3-event-expanded')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /军议急报/ }))
    expect(onScriptClick).toHaveBeenCalledWith(expect.objectContaining({ name: '军议急报' }))
  })

  it('preserves the target-prefixed free-text command contract and tab state in ImperialEdictModal', () => {
    const onFreeText = vi.fn()
    const onClose = vi.fn()
    render(
      <ImperialEdictModal
        isOpen={true}
        onClose={onClose}
        state={gameState()}
        loading={false}
        hasBlockingEvent={false}
        targetRegion="河南江北行省"
        targetRegionMembers={['两淮', '应天', '太平', '镇江', '平江']}
        onDecree={() => {}}
        onFreeText={onFreeText}
      />,
    )

    const militaryTab = screen.getByRole('tab', { name: /军事/ })
    fireEvent.click(militaryTab)
    expect(militaryTab.getAttribute('aria-selected')).toBe('true')

    const textarea = screen.getByPlaceholderText(/向【河南江北行省】颁布政令/)
    fireEvent.change(textarea, { target: { value: '整修河堤' } })
    fireEvent.click(screen.getByRole('button', { name: /御批 · 颁布诏书/ }))
    expect(onFreeText).toHaveBeenCalledWith('【目标行政区：河南江北行省；所辖治理地区：两淮、应天、太平、镇江、平江】整修河堤')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('triggers edict opening and month advance from CommandHud', () => {
    const onOpenEdictModal = vi.fn()
    const onAdvanceMonth = vi.fn()
    render(
      <CommandHud
        state={gameState()}
        loading={false}
        hasBlockingEvent={false}
        advanceMonthInFlight={false}
        currentModal={null}
        targetRegion="两淮"
        isLifeStory={false}
        onOpenEdictModal={onOpenEdictModal}
        onAdvanceMonth={onAdvanceMonth}
        onOpenTrpg={() => {}}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /御笔草诏/ }))
    expect(onOpenEdictModal).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: '推进月份' }))
    expect(onAdvanceMonth).toHaveBeenCalledTimes(1)
  })
})
