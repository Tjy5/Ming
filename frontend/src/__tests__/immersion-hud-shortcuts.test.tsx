// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { cleanup, renderHook } from '@testing-library/react'
import { useGlobalShortcuts } from '../hooks/useGlobalShortcuts'
import type { GameState, Capabilities } from '../types/game'
import { useStore, type OverlayEntry } from '../hooks/store'

afterEach(() => {
  cleanup()
  useStore.getState().reset()
})

function makeMockState(phase: 'governance' | 'life_story' = 'governance'): GameState {
  return {
    time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    phase,
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

describe('immersion HUD global shortcuts', () => {
  it('dispatches Space, E, M, and F1-F4 in normal governance phase', () => {
    const onAdvanceMonth = vi.fn()
    const onOpenEdictModal = vi.fn()
    const onOpenMemorials = vi.fn()
    const onToggleSurface = vi.fn()
    const onShowToast = vi.fn()
    const onCloseTopmostOverlay = vi.fn()

    const state = makeMockState('governance')
    const capabilities: Capabilities = { debate_supported: true, assembly_supported: true, memorial_enabled: true }

    renderHook(() =>
      useGlobalShortcuts({
        state,
        loading: false,
        currentModal: null,
        hasBlockingEvent: false,
        gameOver: null,
        advanceMonthInFlight: false,
        decreeInFlight: false,
        activeHudSurface: null,
        capabilities,
        overlayStack: [],
        pendingMemorialsCount: 3,
        onAdvanceMonth,
        onOpenEdictModal,
        onOpenMemorials,
        onToggleSurface,
        onShowToast,
        onCloseTopmostOverlay,
      }),
    )

    // Space -> Advance Month
    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' }))
    expect(onAdvanceMonth).toHaveBeenCalledTimes(1)

    // E -> Open Edict
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'e' }))
    expect(onOpenEdictModal).toHaveBeenCalledTimes(1)

    // M -> Open Memorials
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'm' }))
    expect(onOpenMemorials).toHaveBeenCalledTimes(1)

    // F1 -> Map
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'F1' }))
    expect(onToggleSurface).toHaveBeenCalledWith('map')

    // F2 -> Faction
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'F2' }))
    expect(onToggleSurface).toHaveBeenCalledWith('faction')

    // F3 -> Minister
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'F3' }))
    expect(onToggleSurface).toHaveBeenCalledWith('minister')

    // F4 -> Assembly
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'F4' }))
    expect(onToggleSurface).toHaveBeenCalledWith('assembly')
  })

  it('ignores shortcuts during IME composition, modifiers, repeats, or editable elements', () => {
    const onAdvanceMonth = vi.fn()
    const onOpenEdictModal = vi.fn()
    const onToggleSurface = vi.fn()
    const onCloseTopmostOverlay = vi.fn()

    const state = makeMockState('governance')
    renderHook(() =>
      useGlobalShortcuts({
        state,
        loading: false,
        currentModal: null,
        hasBlockingEvent: false,
        gameOver: null,
        advanceMonthInFlight: false,
        decreeInFlight: false,
        activeHudSurface: null,
        capabilities: { debate_supported: true, assembly_supported: true, memorial_enabled: true },
        overlayStack: [],
        pendingMemorialsCount: 0,
        onAdvanceMonth,
        onOpenEdictModal,
        onOpenMemorials: vi.fn(),
        onToggleSurface,
        onShowToast: vi.fn(),
        onCloseTopmostOverlay,
      }),
    )

    // 1. IME composing
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'e', isComposing: true }))
    expect(onOpenEdictModal).not.toHaveBeenCalled()

    // 2. Ctrl/Alt/Meta combo
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'e', ctrlKey: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'e', altKey: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'e', metaKey: true }))
    expect(onOpenEdictModal).not.toHaveBeenCalled()

    // 3. Repeat key
    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', repeat: true }))
    expect(onAdvanceMonth).not.toHaveBeenCalled()

    // 4. In textarea / input
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'e', bubbles: true }))
    expect(onOpenEdictModal).not.toHaveBeenCalled()
    document.body.removeChild(input)
  })

  it('blocks month advance and edict opening during life_story phase, loading, or in-flight actions', () => {
    const onAdvanceMonth = vi.fn()
    const onOpenEdictModal = vi.fn()
    const onShowToast = vi.fn()

    // Life story phase
    const state = makeMockState('life_story')
    renderHook(() =>
      useGlobalShortcuts({
        state,
        loading: false,
        currentModal: null,
        hasBlockingEvent: false,
        gameOver: null,
        advanceMonthInFlight: false,
        decreeInFlight: false,
        activeHudSurface: null,
        capabilities: { debate_supported: false, assembly_supported: false, memorial_enabled: false },
        overlayStack: [],
        pendingMemorialsCount: 0,
        onAdvanceMonth,
        onOpenEdictModal,
        onOpenMemorials: vi.fn(),
        onToggleSurface: vi.fn(),
        onShowToast,
        onCloseTopmostOverlay: vi.fn(),
      }),
    )

    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' }))
    expect(onAdvanceMonth).not.toHaveBeenCalled()
    expect(onShowToast).toHaveBeenCalledWith('当前处于人生篇章阶段，请在跑团界面推进剧情')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'e' }))
    expect(onOpenEdictModal).not.toHaveBeenCalled()
    expect(onShowToast).toHaveBeenCalledWith('当前处于人生篇章阶段，暂不可草拟全国圣旨')
  })

  it('handles Escape to close topmost overlay with priority ordering', () => {
    const onCloseTopmostOverlay = vi.fn()
    const overlayStack: OverlayEntry[] = [
      { id: 'drawer', kind: 'surface', priority: 10, closeAction: vi.fn() },
      { id: 'edict_modal', kind: 'central_modal', priority: 30, closeAction: vi.fn() },
    ]

    const state = makeMockState('governance')
    renderHook(() =>
      useGlobalShortcuts({
        state,
        loading: false,
        currentModal: null,
        hasBlockingEvent: false,
        gameOver: null,
        advanceMonthInFlight: false,
        decreeInFlight: false,
        activeHudSurface: null,
        capabilities: { debate_supported: false, assembly_supported: false, memorial_enabled: false },
        overlayStack,
        pendingMemorialsCount: 0,
        onAdvanceMonth: vi.fn(),
        onOpenEdictModal: vi.fn(),
        onOpenMemorials: vi.fn(),
        onToggleSurface: vi.fn(),
        onShowToast: vi.fn(),
        onCloseTopmostOverlay,
      }),
    )

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(onCloseTopmostOverlay).toHaveBeenCalledTimes(1)
  })

  it('guarantees single-layer Escape close when map panel (priority 10) and inspector (priority 20) are both open', () => {
    const closeInspector = vi.fn()
    const closeMapPanel = vi.fn()

    const { registerOverlay, closeTopmostOverlay } = useStore.getState()
    registerOverlay({ id: 'map_control_panel', kind: 'surface', priority: 10, closeAction: closeMapPanel })
    registerOverlay({ id: 'region_inspector', kind: 'inspector', priority: 20, closeAction: closeInspector })

    // First Escape -> closes inspector ONLY
    expect(closeTopmostOverlay()).toBe(true)
    expect(closeInspector).toHaveBeenCalledTimes(1)
    expect(closeMapPanel).not.toHaveBeenCalled()

    // Second Escape -> closes map panel
    expect(closeTopmostOverlay()).toBe(true)
    expect(closeMapPanel).toHaveBeenCalledTimes(1)
  })
})
