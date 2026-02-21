import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { isAbortError, showCancelToast } from '../utils/toast'
import type { GameEvent, GameState, ModalItem } from '../types/game'

type UseAdvanceMonthParams = {
  state: GameState | null
  loading: boolean
  currentModal: ModalItem | null
  hasBlockingEvent: boolean
  decreeInFlight: boolean
  setState: (s: GameState) => void
  setLoading: (v: boolean) => void
  setError: (e: string | null) => void
  setGameOver: (g: { result: 'victory' | 'defeat'; message: string } | null) => void
  pushModal: (item: ModalItem) => void
  showToast: (msg: string) => void
  onMissionComplete?: (ministerName: string, missionName: string) => void
}

export function useAdvanceMonth({
  state,
  loading,
  currentModal,
  hasBlockingEvent,
  decreeInFlight,
  setState,
  setLoading,
  setError,
  setGameOver,
  pushModal,
  showToast,
  onMissionComplete,
}: UseAdvanceMonthParams) {
  const [advanceMonthInFlight, setAdvanceMonthInFlight] = useState(false)
  const advanceMonthAbortController = useRef<AbortController | null>(null)

  const handleAdvanceMonth = useCallback(async () => {
    if (!state || loading || advanceMonthInFlight || !!currentModal || hasBlockingEvent || decreeInFlight) return
    setAdvanceMonthInFlight(true)
    setLoading(true)
    setError(null)
    if (advanceMonthAbortController.current) advanceMonthAbortController.current.abort()
    advanceMonthAbortController.current = new AbortController()
    try {
      const prevMissions = new Map(
        (state?.ministers ?? [])
          .filter(m => m.status === 'on_mission' && m.current_mission)
          .map(m => [m.name, m.current_mission!.name])
      )
      const res = await api.advanceMonth(advanceMonthAbortController.current.signal)
      setState(res.state)
      // detect mission completions
      if (onMissionComplete) {
        for (const [name, missionName] of prevMissions) {
          const after = res.state.ministers.find(m => m.name === name)
          if (after && after.status === 'active' && !after.current_mission) {
            onMissionComplete(name, missionName)
          }
        }
      }
      if (res.triggered_events?.length) {
        res.triggered_events.forEach((eventName) => {
          const evt = res.state.active_events.find((e) => e.name === eventName)
          if (evt) {
            pushModal({ type: 'script_event', priority: 10, payload: evt as GameEvent })
          }
        })
      }
      showToast(`进入 ${res.state.time.era_name}${res.state.time.era_year}年${res.state.time.month}月`)
      if (res.game_over) {
        setGameOver(res.game_over)
      }
    } catch (e) {
      if (isAbortError(e)) {
        showCancelToast(showToast)
        return
      }
      if (e instanceof ApiError && e.status === 409) {
        showToast(e.body.message || '正在处理，请稍候')
      } else {
        showToast(e instanceof ApiError ? e.body.message : '操作失败')
      }
    } finally {
      setLoading(false)
      setAdvanceMonthInFlight(false)
    }
  }, [
    advanceMonthInFlight,
    currentModal,
    decreeInFlight,
    hasBlockingEvent,
    loading,
    pushModal,
    setError,
    setGameOver,
    setLoading,
    setState,
    showToast,
    state,
  ])

  useEffect(() => {
    return () => {
      if (advanceMonthAbortController.current) advanceMonthAbortController.current.abort()
    }
  }, [])

  return {
    advanceMonthInFlight,
    handleAdvanceMonth,
  }
}

