import { create } from 'zustand'
import type { GameState, DecreeType, PreconditionRule, Capabilities, DebateResult } from '../types/game'
import { PRECONDITIONS } from '../types/game'

interface Store {
  state: GameState | null
  loading: boolean
  error: string | null
  narrative: string | null
  gameOver: { result: 'victory' | 'defeat'; message: string } | null
  prevState: GameState | null
  capabilities: Capabilities
  debateResult: DebateResult | null
  debateLoading: boolean
  selectedTopic: string | null

  setState: (s: GameState) => void
  setLoading: (v: boolean) => void
  setError: (e: string | null) => void
  setNarrative: (n: string | null) => void
  setGameOver: (g: { result: 'victory' | 'defeat'; message: string } | null) => void
  setPrevState: (s: GameState | null) => void
  setCapabilities: (c: Capabilities) => void
  setDebateResult: (r: DebateResult | null) => void
  setDebateLoading: (v: boolean) => void
  setSelectedTopic: (t: string | null) => void
  reset: () => void
}

const DEFAULT_CAPABILITIES: Capabilities = { debate_supported: false, portrait_supported: false }

export const useStore = create<Store>((set) => ({
  state: null,
  loading: false,
  error: null,
  narrative: null,
  gameOver: null,
  prevState: null,
  capabilities: DEFAULT_CAPABILITIES,
  debateResult: null,
  debateLoading: false,
  selectedTopic: null,

  setState: (s) => set({ state: s }),
  setLoading: (v) => set({ loading: v }),
  setError: (e) => set({ error: e }),
  setNarrative: (n) => set({ narrative: n }),
  setGameOver: (g) => set({ gameOver: g }),
  setPrevState: (s) => set({ prevState: s }),
  setCapabilities: (c) => set({ capabilities: c }),
  setDebateResult: (r) => set({ debateResult: r }),
  setDebateLoading: (v) => set({ debateLoading: v }),
  setSelectedTopic: (t) => set({ selectedTopic: t }),
  reset: () => set({
    state: null, loading: false, error: null, narrative: null,
    gameOver: null, prevState: null, debateResult: null,
    debateLoading: false, selectedTopic: null,
  }),
}))

function evalRule(state: GameState, rule: PreconditionRule): boolean {
  const val = state[rule.field] as number
  return rule.op === '>' ? val > rule.threshold : val >= rule.threshold
}

export function checkPrecondition(state: GameState, type: DecreeType): boolean {
  return PRECONDITIONS[type].every((r) => evalRule(state, r))
}
