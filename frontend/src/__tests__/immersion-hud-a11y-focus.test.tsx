// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react'
import CourtDrawer from '../components/CourtDrawer'
import ResourceBar from '../components/ResourceBar'
import { useStore } from '../hooks/store'
import type { GameState } from '../types/game'

beforeEach(() => useStore.getState().reset())

afterEach(() => {
  cleanup()
  useStore.getState().reset()
  vi.restoreAllMocks()
})

function makeMockState(): GameState {
  return {
    time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    phase: 'governance',
    chapter: 'warlord',
    chapter_turns: 0,
    national_treasury: 500,
    imperial_treasury: 100,
    grain: 2000,
    population: 8000,
    military_strength: 200,
    civil_morale: 60,
    military_morale: 60,
    court_prestige: 55,
    ministers: [],
    factions: [],
    regions: [],
    active_events: [],
    history_log: [],
    decree_count: 0,
    decrees_this_month: {},
    event_cooldowns: {},
    resolved_script_ids: [],
    memorials: [],
  }
}

describe('immersion HUD ARIA and focus management', () => {
  it('manages roving tabindex and cyclic ArrowLeft / ArrowRight / Home / End navigation in CourtDrawer tablist', () => {
    const onTabChange = vi.fn()
    render(
      <CourtDrawer
        isOpen={true}
        activeTab="faction"
        onTabChange={onTabChange}
        onClose={vi.fn()}
        state={makeMockState()}
        capabilities={{ debate_supported: true, assembly_supported: true, memorial_enabled: true }}
        lastReactions={[]}
        onMinisterClick={vi.fn()}
        onShowOfficialRank={vi.fn()}
        onStateUpdate={vi.fn()}
        onAdoptionResult={vi.fn()}
        onShowToast={vi.fn()}
      />,
    )

    const factionTab = screen.getByRole('tab', { name: '派系' })
    const ministerTab = screen.getByRole('tab', { name: '大臣' })
    const assemblyTab = screen.getByRole('tab', { name: '朝议' })

    // Active tab has tabIndex 0, inactive tabs have tabIndex -1
    expect(factionTab.getAttribute('tabindex')).toBe('0')
    expect(ministerTab.getAttribute('tabindex')).toBe('-1')
    expect(assemblyTab.getAttribute('tabindex')).toBe('-1')

    // ArrowRight moves from faction -> minister
    fireEvent.keyDown(factionTab, { key: 'ArrowRight' })
    expect(onTabChange).toHaveBeenCalledWith('minister')

    // Home moves to first tab (faction)
    fireEvent.keyDown(ministerTab, { key: 'Home' })
    expect(onTabChange).toHaveBeenCalledWith('faction')

    // End moves to last valid tab (assembly)
    fireEvent.keyDown(factionTab, { key: 'End' })
    expect(onTabChange).toHaveBeenCalledWith('assembly')

    // ArrowLeft on faction cycles to last tab (assembly)
    fireEvent.keyDown(factionTab, { key: 'ArrowLeft' })
    expect(onTabChange).toHaveBeenCalledWith('assembly')
  })

  it('restores palace settings focus and schedules it once for a stack close', async () => {
    render(
      <ResourceBar
        state={makeMockState()}
        prevState={null}
        onSave={vi.fn()}
        onShowSaves={vi.fn()}
        onNewGame={vi.fn()}
        onOpenAiSettings={vi.fn()}
        onOpenChat={vi.fn()}
        onOpenGuide={vi.fn()}
      />,
    )

    const trigger = screen.getByRole('button', { name: '宫禁设置' })
    trigger.focus()
    fireEvent.click(trigger)

    expect(screen.getByRole('menu', { name: '宫禁设置菜单' })).toBeTruthy()

    // Close button click restores focus
    const closeBtn = screen.getByRole('button', { name: '关闭设置菜单' })
    fireEvent.click(closeBtn)

    expect(screen.queryByRole('menu', { name: '宫禁设置菜单' })).toBeNull()
    await waitFor(() => expect(document.activeElement).toBe(trigger))

    fireEvent.click(trigger)
    const reopenedCloseBtn = screen.getByRole('button', { name: '关闭设置菜单' })
    reopenedCloseBtn.focus()
    const setTimeoutSpy = vi.spyOn(window, 'setTimeout')
    setTimeoutSpy.mockClear()
    act(() => {
      expect(useStore.getState().closeTopmostOverlay()).toBe(true)
    })
    expect(setTimeoutSpy).toHaveBeenCalledTimes(1)
    setTimeoutSpy.mockRestore()
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })

  it('unregisters and closes strictly one layer at a time from store overlayStack', () => {
    const closeAction1 = vi.fn()
    const closeAction2 = vi.fn()
    const closeAction3 = vi.fn()

    const { registerOverlay, closeTopmostOverlay } = useStore.getState()

    // Push 3 overlays with different priorities
    registerOverlay({ id: 'surface_1', kind: 'surface', priority: 10, closeAction: closeAction1 })
    registerOverlay({ id: 'inspector_2', kind: 'inspector', priority: 20, closeAction: closeAction2 })
    registerOverlay({ id: 'modal_3', kind: 'central_modal', priority: 30, closeAction: closeAction3 })

    // First closeTopmostOverlay -> closes modal_3 (priority 30)
    closeTopmostOverlay()
    expect(closeAction3).toHaveBeenCalledTimes(1)
    expect(closeAction2).not.toHaveBeenCalled()
    expect(closeAction1).not.toHaveBeenCalled()

    // Second closeTopmostOverlay -> closes inspector_2 (priority 20)
    closeTopmostOverlay()
    expect(closeAction2).toHaveBeenCalledTimes(1)
    expect(closeAction1).not.toHaveBeenCalled()

    // Third closeTopmostOverlay -> closes surface_1 (priority 10)
    closeTopmostOverlay()
    expect(closeAction1).toHaveBeenCalledTimes(1)
  })
})
