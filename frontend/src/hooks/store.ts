import type { RefObject } from 'react'
import { create } from 'zustand'
import type { GameState, DecreeType, PreconditionRule, Capabilities, ModalItem, ModalType } from '../types/game'
import { PRECONDITIONS, DEFAULT_CAPABILITIES } from '../types/game'

export const MODAL_PRIORITIES: Record<ModalType, number> = {
  game_over: 100,
  script_event_blocking: 90,
  narrative: 95,
  turn_summary: 40,
  memorial: 30,
  assembly: 20,
  script_event: 10,
}

export type HudSurface = 'map' | 'camera' | 'faction' | 'minister' | 'assembly' | null

export type OverlayKind =
  | 'nested_modal'
  | 'central_modal'
  | 'inspector'
  | 'menu'
  | 'surface'

export interface OverlayEntry {
  id: string
  kind: OverlayKind
  priority: number
  openerRef?: RefObject<HTMLElement | null>
  openerId?: string | null
  closeAction?: () => void
}

type OverlayOpener = Pick<OverlayEntry, 'openerRef' | 'openerId'>

// Modal domain objects stay free of DOM handles while their queue identity preserves focus metadata.
const modalOpeners = new WeakMap<ModalItem, OverlayOpener>()

function createCentralModalOverlay(modal: ModalItem, closeAction: () => void): OverlayEntry {
  return {
    id: 'central_current_modal',
    kind: 'central_modal',
    priority: 30,
    ...modalOpeners.get(modal),
    closeAction,
  }
}

function replaceCentralModalOverlay(stack: OverlayEntry[], overlay: OverlayEntry): OverlayEntry[] {
  return [...stack.filter((entry) => entry.id !== 'central_current_modal'), overlay]
}

export function restoreOpenerFocus(openerRef?: RefObject<HTMLElement | null>, openerId?: string | null) {
  window.setTimeout(() => {
    const opener = openerRef?.current
    if (opener && typeof opener.focus === 'function' && document.body.contains(opener)) {
      opener.focus()
      return
    }
    if (openerId) {
      const el = document.getElementById(openerId) || document.querySelector<HTMLElement>(`[data-opener-id="${openerId}"]`)
      if (el && typeof el.focus === 'function' && document.body.contains(el)) {
        el.focus()
        return
      }
    }
    const fallback =
      document.querySelector<HTMLElement>('[data-hud-fallback-focus]') ||
      document.querySelector<HTMLElement>('.hud-edict-btn') ||
      document.querySelector<HTMLElement>('.hud-advance-btn') ||
      document.querySelector<HTMLElement>('.primary-command-strip button') ||
      document.querySelector<HTMLElement>('.unified-control-rail button') ||
      document.querySelector<HTMLElement>('.toolbar-actions button')

    if (fallback && typeof fallback.focus === 'function') {
      fallback.focus()
    }
  }, 0)
}

interface Store {
  state: GameState | null
  loading: boolean
  error: string | null
  gameOver: { result: 'victory' | 'defeat'; message: string } | null
  prevState: GameState | null
  capabilities: Capabilities
  modalQueue: ModalItem[]
  currentModal: ModalItem | null
  activeHudSurface: HudSurface
  overlayStack: OverlayEntry[]

  setState: (s: GameState) => void
  setLoading: (v: boolean) => void
  setError: (e: string | null) => void
  setGameOver: (g: { result: 'victory' | 'defeat'; message: string } | null) => void
  setPrevState: (s: GameState | null) => void
  setCapabilities: (c: Capabilities) => void
  pushModal: (item: ModalItem, opener?: OverlayOpener) => void
  popModal: () => void
  clearModals: () => void
  setActiveHudSurface: (surface: HudSurface, openerId?: string | null) => void
  registerOverlay: (entry: OverlayEntry) => void
  unregisterOverlay: (id: string) => void
  closeTopmostOverlay: () => boolean
  isTopmostOverlay: (id: string) => boolean
  reset: () => void
}

function insertModalByPriority(queue: ModalItem[], modal: ModalItem): ModalItem[] {
  const next = [...queue]
  let i = next.length
  while (i > 0 && next[i - 1].priority < modal.priority) i--
  next.splice(i, 0, modal)
  return next
}

export const useStore = create<Store>((set, get) => ({
  state: null,
  loading: false,
  error: null,
  gameOver: null,
  prevState: null,
  capabilities: DEFAULT_CAPABILITIES,
  modalQueue: [],
  currentModal: null,
  activeHudSurface: null,
  overlayStack: [],

  setState: (s) => set({ state: s }),
  setLoading: (v) => set({ loading: v }),
  setError: (e) => set({ error: e }),
  setGameOver: (g) => set({ gameOver: g }),
  setPrevState: (s) => set({ prevState: s }),
  setCapabilities: (c) => set({ capabilities: c }),

  pushModal: (item, opener) => set((s) => {
    const m = { ...item, priority: item.priority ?? MODAL_PRIORITIES[item.type] } as ModalItem
    if (opener) modalOpeners.set(m, opener)

    if (!s.currentModal) {
      const centralOverlay = createCentralModalOverlay(m, () => get().popModal())
      return {
        currentModal: m,
        overlayStack: replaceCentralModalOverlay(s.overlayStack, centralOverlay),
      }
    }
    if (m.priority > s.currentModal.priority) {
      const centralOverlay = createCentralModalOverlay(m, () => get().popModal())
      return {
        currentModal: m,
        modalQueue: insertModalByPriority(s.modalQueue, s.currentModal),
        overlayStack: replaceCentralModalOverlay(s.overlayStack, centralOverlay),
      }
    }
    return {
      modalQueue: insertModalByPriority(s.modalQueue, m),
    }
  }),
  popModal: () => set((s) => {
    if (s.modalQueue.length === 0) {
      return {
        currentModal: null,
        overlayStack: s.overlayStack.filter((e) => e.id !== 'central_current_modal'),
      }
    }
    const [next, ...rest] = s.modalQueue
    const centralOverlay = createCentralModalOverlay(next, () => get().popModal())
    return {
      currentModal: next,
      modalQueue: rest,
      overlayStack: replaceCentralModalOverlay(s.overlayStack, centralOverlay),
    }
  }),
  clearModals: () => set((s) => ({
    currentModal: null,
    modalQueue: [],
    overlayStack: s.overlayStack.filter((e) => e.id !== 'central_current_modal'),
  })),

  setActiveHudSurface: (surface, openerId) => set((s) => {
    const stackWithoutSurface = s.overlayStack.filter((e) => e.id !== 'hud_surface')
    if (!surface) {
      return { activeHudSurface: null, overlayStack: stackWithoutSurface }
    }
    const surfaceOverlay: OverlayEntry = {
      id: 'hud_surface',
      kind: 'surface',
      priority: 10,
      openerId: openerId ?? `rail-btn-${surface}`,
      closeAction: () => get().setActiveHudSurface(null),
    }
    return {
      activeHudSurface: surface,
      overlayStack: [...stackWithoutSurface, surfaceOverlay],
    }
  }),

  registerOverlay: (entry) => set((s) => {
    const filtered = s.overlayStack.filter((e) => e.id !== entry.id)
    return { overlayStack: [...filtered, entry] }
  }),

  unregisterOverlay: (id) => set((s) => ({
    overlayStack: s.overlayStack.filter((e) => e.id !== id),
  })),

  closeTopmostOverlay: () => {
    const stack = get().overlayStack
    if (stack.length === 0) return false

    const indexed = stack.map((entry, index) => ({ entry, index }))
    indexed.sort((a, b) => {
      if (b.entry.priority !== a.entry.priority) {
        return b.entry.priority - a.entry.priority
      }
      return b.index - a.index
    })

    const top = indexed[0].entry
    set({
      overlayStack: stack.filter((e) => e.id !== top.id),
    })

    try {
      top.closeAction?.()
    } catch (err) {
      console.error('Error in closeAction:', err)
    }

    restoreOpenerFocus(top.openerRef, top.openerId)
    return true
  },

  isTopmostOverlay: (id: string) => {
    const stack = get().overlayStack
    if (stack.length === 0) return false
    const indexed = stack.map((entry, index) => ({ entry, index }))
    indexed.sort((a, b) => {
      if (b.entry.priority !== a.entry.priority) {
        return b.entry.priority - a.entry.priority
      }
      return b.index - a.index
    })
    return indexed[0].entry.id === id
  },

  reset: () => set({
    state: null, loading: false, error: null,
    gameOver: null, prevState: null, capabilities: DEFAULT_CAPABILITIES,
    currentModal: null, modalQueue: [], activeHudSurface: null, overlayStack: [],
  }),
}))

function evalRule(state: GameState, rule: PreconditionRule): boolean {
  const val = state[rule.field]
  if (typeof val !== 'number') return false
  return rule.op === '>' ? val > rule.threshold : val >= rule.threshold
}

export function checkPrecondition(state: GameState, type: DecreeType): boolean {
  const rules = PRECONDITIONS[type]
  if (!rules) return false
  return rules.every((r) => evalRule(state, r))
}
