// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ActionArea from '../components/ActionArea'
import EventBar from '../components/EventBar'
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
  it('keeps global tool callbacks distinct behind accessible icon commands', () => {
    const onSave = vi.fn()
    const onNewGame = vi.fn()
    const onOpenContinuity = vi.fn()
    render(
      <ResourceBar
        state={gameState()}
        prevState={null}
        onSave={onSave}
        onShowSaves={() => {}}
        onNewGame={onNewGame}
        onOpenAiSettings={() => {}}
        onOpenChat={() => {}}
        onOpenContinuity={onOpenContinuity}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '存档' }))
    fireEvent.click(screen.getByRole('button', { name: '查看世界分支、书签和活动' }))
    fireEvent.click(screen.getByRole('button', { name: '开始新局' }))
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onOpenContinuity).toHaveBeenCalledTimes(1)
    expect(onNewGame).toHaveBeenCalledTimes(1)
  })

  it('distinguishes expandable reports from scripted event actions', () => {
    const onScriptClick = vi.fn()
    render(
      <EventBar
        events={[
          event(),
          event({ name: '军议急报', is_scripted: true, choices: [{ label: '固守', description: '据城固守', decrees: [] }] }),
        ]}
        pendingMemorials={2}
        onScriptClick={onScriptClick}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /漕运迟滞/ }))
    expect(screen.getByText('漕粮未能如期抵达。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /军议急报/ }))
    expect(onScriptClick).toHaveBeenCalledWith(expect.objectContaining({ name: '军议急报' }))
  })

  it('preserves the target-prefixed free-text command contract and tab state', () => {
    const onFreeText = vi.fn()
    render(
      <ActionArea
        state={gameState()}
        loading={false}
        hasBlockingEvent={false}
        onDecree={() => {}}
        onFreeText={onFreeText}
        onAdvanceMonth={() => {}}
        advanceMonthInFlight={false}
        currentModal={null}
        targetRegion="江南"
      />,
    )

    const militaryTab = screen.getByRole('tab', { name: '军事' })
    fireEvent.click(militaryTab)
    expect(militaryTab.getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(militaryTab, { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: '外交' }).getAttribute('aria-selected')).toBe('true')
    fireEvent.change(screen.getByPlaceholderText('输入政令（如：整顿军备）'), { target: { value: '整修河堤' } })
    fireEvent.click(screen.getByRole('button', { name: '下令' }))
    expect(onFreeText).toHaveBeenCalledWith('【目标地区：江南】整修河堤')
  })

  it('returns focus to the command that opened a canceled edict dialog', async () => {
    render(
      <ActionArea
        state={gameState()}
        loading={false}
        hasBlockingEvent={false}
        onDecree={() => {}}
        onFreeText={() => {}}
        onAdvanceMonth={() => {}}
        advanceMonthInFlight={false}
        currentModal={null}
      />,
    )

    const trigger = document.querySelector<HTMLButtonElement>('.decree-btn')
    expect(trigger).not.toBeNull()
    trigger?.focus()
    fireEvent.click(trigger!)
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })
})
