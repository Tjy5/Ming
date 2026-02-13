import { create } from 'zustand'
import type { GameState, DecreeType, PreconditionRule } from '../types/game'
import { PRECONDITIONS } from '../types/game'

interface Store {
  state: GameState | null
  loading: boolean
  error: string | null
  narrative: string | null
  gameOver: { result: 'victory' | 'defeat'; message: string } | null
  prevState: GameState | null

  setState: (s: GameState) => void
  setLoading: (v: boolean) => void
  setError: (e: string | null) => void
  setNarrative: (n: string | null) => void
  setGameOver: (g: { result: 'victory' | 'defeat'; message: string } | null) => void
  setPrevState: (s: GameState | null) => void
  reset: () => void
}

export const useStore = create<Store>((set) => ({
  state: null,
  loading: false,
  error: null,
  narrative: null,
  gameOver: null,
  prevState: null,

  setState: (s) => set({ state: s }),
  setLoading: (v) => set({ loading: v }),
  setError: (e) => set({ error: e }),
  setNarrative: (n) => set({ narrative: n }),
  setGameOver: (g) => set({ gameOver: g }),
  setPrevState: (s) => set({ prevState: s }),
  reset: () => set({ state: null, loading: false, error: null, narrative: null, gameOver: null, prevState: null }),
}))

function evalRule(state: GameState, rule: PreconditionRule): boolean {
  const val = state[rule.field] as number
  return rule.op === '>' ? val > rule.threshold : val >= rule.threshold
}

export function checkPrecondition(state: GameState, type: DecreeType): boolean {
  return PRECONDITIONS[type].every((r) => evalRule(state, r))
}
