import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { MODE_SELECT_OPERATION_FLAG } from '../constants/modeSelect'
import type { GameEvent, GameState } from '../types/game'
import './ModeSelectPage.css'

function findBlockingEvent(state: GameState | null): GameEvent | null {
  if (!state) return null
  return state.active_events.find(
    (event) => event.is_scripted && event.is_blocking && event.choices.length > 0,
  ) ?? null
}

export default function ModeSelectPage() {
  const navigate = useNavigate()
  const [gameState, setGameState] = useState<GameState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.getState()
      .then((state) => {
        if (cancelled) return
        setGameState(state)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        const message = err instanceof ApiError ? err.body.message : '读取朝局失败'
        setError(message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [])

  const blockingEvent = useMemo(() => findBlockingEvent(gameState), [gameState])

  useEffect(() => {
    if (loading || error || !gameState) return
    if (!blockingEvent) navigate('/', { replace: true })
  }, [blockingEvent, error, gameState, loading, navigate])

  const handleChatMode = () => {
    sessionStorage.removeItem(MODE_SELECT_OPERATION_FLAG)
    navigate('/chat')
  }

  const handleOperationMode = () => {
    sessionStorage.setItem(
      MODE_SELECT_OPERATION_FLAG,
      blockingEvent?.script_id ?? 'pending',
    )
    navigate('/', { replace: true })
  }

  return (
    <div className="mode-select-page">
      <div className="mode-select-card">
        <p className="mode-select-kicker">元末乱世 · 起局时刻</p>
        <h1>主公欲以何种方式统驭朝局？</h1>
        <p className="mode-select-intro">
          阻断剧情事件已触发。可先听谋臣详述局势，或直接进入操作面板裁断政务。
        </p>

        {loading && <p className="mode-select-note" role="status">正在载入当前局势…</p>}
        {!loading && error && <p className="mode-select-error" role="alert">{error}</p>}

        {!loading && !error && blockingEvent && (
          <div className="mode-select-event">
            <h2>当前关键事件</h2>
            <strong>{blockingEvent.name}</strong>
            <p>{blockingEvent.description || '局势骤变，亟需裁断。'}</p>
          </div>
        )}

        <div className="mode-select-actions">
          <button
            type="button"
            className="mode-select-btn is-chat"
            onClick={handleChatMode}
            disabled={loading || !!error}
          >
            以对话方式体验朝政
          </button>
          <button
            type="button"
            className="mode-select-btn is-op"
            onClick={handleOperationMode}
            disabled={loading || !!error}
          >
            以操作面板管理朝政
          </button>
        </div>

        <button
          type="button"
          className="mode-select-back"
          onClick={() => navigate('/', { replace: true })}
        >
          返回朝堂
        </button>
      </div>
    </div>
  )
}
