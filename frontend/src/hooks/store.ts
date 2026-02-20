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
  debate: 20,
  script_event: 10,
}

interface Store {
  state: GameState | null
  loading: boolean
  error: string | null
  gameOver: { result: 'victory' | 'defeat'; message: string } | null
  prevState: GameState | null
  capabilities: Capabilities
  debateLoading: boolean
  modalQueue: ModalItem[]
  currentModal: ModalItem | null

  setState: (s: GameState) => void
  setLoading: (v: boolean) => void
  setError: (e: string | null) => void
  setGameOver: (g: { result: 'victory' | 'defeat'; message: string } | null) => void
  setPrevState: (s: GameState | null) => void
  setCapabilities: (c: Capabilities) => void
  setDebateLoading: (v: boolean) => void
  pushModal: (item: ModalItem) => void
  popModal: () => void
  clearModals: () => void
  reset: () => void
}

function insertModalByPriority(queue: ModalItem[], modal: ModalItem): ModalItem[] {
  const next = [...queue]
  let i = next.length
  while (i > 0 && next[i - 1].priority < modal.priority) i--
  next.splice(i, 0, modal)
  return next
}

export const useStore = create<Store>((set) => ({
  state: null,
  loading: false,
  error: null,
  gameOver: null,
  prevState: null,
  capabilities: DEFAULT_CAPABILITIES,
  debateLoading: false,
  modalQueue: [],
  currentModal: null,

  setState: (s) => set({ state: s }),
  setLoading: (v) => set({ loading: v }),
  setError: (e) => set({ error: e }),
  setGameOver: (g) => set({ gameOver: g }),
  setPrevState: (s) => set({ prevState: s }),
  setCapabilities: (c) => set({ capabilities: c }),
  setDebateLoading: (v) => set({ debateLoading: v }),

  pushModal: (item) => set((s) => {
    const m = { ...item, priority: item.priority ?? MODAL_PRIORITIES[item.type] }
    if (!s.currentModal) return { currentModal: m }
    if (m.priority > s.currentModal.priority) {
      return {
        currentModal: m,
        modalQueue: insertModalByPriority(s.modalQueue, s.currentModal),
      }
    }
    return { modalQueue: insertModalByPriority(s.modalQueue, m) }
  }),
  popModal: () => set((s) => {
    if (s.modalQueue.length === 0) return { currentModal: null }
    const [next, ...rest] = s.modalQueue
    return { currentModal: next, modalQueue: rest }
  }),
  clearModals: () => set({ currentModal: null, modalQueue: [] }),

  reset: () => set({
    state: null, loading: false, error: null,
    gameOver: null, prevState: null, capabilities: DEFAULT_CAPABILITIES,
    debateLoading: false, currentModal: null, modalQueue: [],
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
