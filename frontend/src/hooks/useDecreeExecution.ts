import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { isAbortError, showCancelToast } from '../utils/toast'
import type { DecreeResponse, GameState, MinisterReaction, StructuredDecree } from '../types/game'
import type { ModalItem } from '../types/game'

type NarrativePayload = {
  narrative: string
  delta: Record<string, number>
  ministerReactions?: MinisterReaction[]
  turnSummary?: DecreeResponse['turn_summary']
}

type UseDecreeExecutionParams = {
  state: GameState | null
  setState: (s: GameState) => void
  setLoading: (v: boolean) => void
  setError: (e: string | null) => void
  setPrevState: (s: GameState | null) => void
  setGameOver: (g: { result: 'victory' | 'defeat'; message: string } | null) => void
  pushModal: (item: ModalItem) => void
  showToast: (msg: string) => void
  onReactions: (reactions: MinisterReaction[]) => void
}

export function useDecreeExecution({
  state,
  setState,
  setLoading,
  setError,
  setPrevState,
  setGameOver,
  pushModal,
  showToast,
  onReactions,
}: UseDecreeExecutionParams) {
  const [decreeInFlight, setDecreeInFlight] = useState(false)
  const decreeAbortController = useRef<AbortController | null>(null)

  const queueTurnResultModals = useCallback((res: DecreeResponse) => {
    pushModal({
      type: 'narrative',
      priority: 95,
      payload: {
        narrative: res.narrative,
        delta: res.delta,
        ministerReactions: res.minister_reactions,
        turnSummary: res.turn_summary ?? undefined,
      } satisfies NarrativePayload,
    })
    if (res.memorial_triggers?.length) {
      showToast(`新增 ${res.memorial_triggers.length} 份奏折，请在下方“奏折”入口批复`)
    }
  }, [pushModal, showToast])

  const executeDecrees = useCallback(async (
    decrees: StructuredDecree[],
    sourceScriptId?: string,
    freeText?: string,
  ): Promise<string | null> => {
    if (!state) return 'no_state'
    if (decreeInFlight) {
      showToast('正在处理上一道政令，请稍候')
      return 'in_flight'
    }
    setDecreeInFlight(true)
    setLoading(true)
    setError(null)
    setPrevState(state)
    if (decreeAbortController.current) decreeAbortController.current.abort()
    decreeAbortController.current = new AbortController()
    try {
      const res = await api.decree(decrees, sourceScriptId, freeText, decreeAbortController.current.signal)
      setState(res.state)
      if (res.minister_reactions?.length) onReactions(res.minister_reactions)
      if (res.game_over) {
        setGameOver(res.game_over)
      } else {
        queueTurnResultModals(res)
      }
      return null
    } catch (e) {
      if (isAbortError(e)) {
        showCancelToast(showToast)
        return 'cancelled'
      }
      if (e instanceof ApiError) {
        if (e.body.error_code === 'FREEFORM_EMPTY') {
          return 'FREEFORM_EMPTY'
        }
        if (e.status === 409) {
          showToast(e.body.message || '正在处理上一道政令，请稍候')
        } else {
          const aiRaw = e.body.details?.ai_narrative
          const ai = typeof aiRaw === 'string' ? aiRaw : null
          if (ai) pushModal({ type: 'narrative', priority: 95, payload: { narrative: ai, delta: {} } })
          else showToast(e.body.message)
        }
      } else {
        showToast('网络错误，请重试')
      }
      return 'error'
    } finally {
      setDecreeInFlight(false)
      setLoading(false)
    }
  }, [
    decreeInFlight,
    onReactions,
    pushModal,
    queueTurnResultModals,
    setError,
    setGameOver,
    setLoading,
    setPrevState,
    setState,
    showToast,
    state,
  ])

  const handleFreeText = useCallback(async (text: string) => {
    if (!state) return
    const trimmed = text.trim()
    if (!trimmed) return
    if (trimmed.length > 200) {
      showToast('政令文本过长（最多200字）')
      return
    }
    await executeDecrees([], undefined, trimmed)
  }, [executeDecrees, showToast, state])

  useEffect(() => {
    return () => {
      if (decreeAbortController.current) decreeAbortController.current.abort()
    }
  }, [])

  return {
    decreeInFlight,
    executeDecrees,
    handleFreeText,
  }
}

