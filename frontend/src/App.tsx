import { useEffect, useState, useCallback, useRef } from 'react'
import { useStore } from './hooks/store'
import { api, ApiError } from './api/client'
import type { StructuredDecree, DecreeResponse, GameState } from './types/game'
import ResourceBar from './components/ResourceBar'
import RegionMap from './components/RegionMap'
import FactionPanel from './components/FactionPanel'
import EventBar from './components/EventBar'
import ActionArea from './components/ActionArea'
import NarrativeModal from './components/NarrativeModal'
import GameOverScreen from './components/GameOverScreen'
import MultiConfirm from './components/MultiConfirm'
import SavePanel from './components/SavePanel'
import './App.css'

function App() {
  const {
    state, loading, error, narrative, gameOver, prevState,
    setState, setLoading, setError, setNarrative, setGameOver, setPrevState, reset,
  } = useStore()

  const [delta, setDelta] = useState<Record<string, number>>({})
  const [showSaves, setShowSaves] = useState(false)
  const [pendingMulti, setPendingMulti] = useState<StructuredDecree[] | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<number>(0)

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 3000)
  }, [])

  useEffect(() => {
    api.getState()
      .then((s) => setState(s))
      .catch(() => {
        api.newGame().then((s) => setState(s)).catch((e) => showToast(e instanceof ApiError ? e.message : '连接后端失败'))
      })
  }, [setState, showToast])

  async function executeDecrees(decrees: StructuredDecree[]) {
    if (!state) return
    setLoading(true)
    setError(null)
    setPrevState(state)
    try {
      const res: DecreeResponse = await api.decree(decrees)
      setState(res.state)
      setDelta(res.delta)
      setNarrative(res.narrative)
      if (res.game_over) {
        setGameOver(res.game_over)
      }
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          showToast('正在处理上一道政令，请稍候')
        } else {
          const narrative = e.body.details?.ai_narrative
          if (narrative) {
            setNarrative(narrative)
          } else {
            showToast(e.body.message)
          }
        }
      } else {
        showToast('网络错误，请重试')
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleFreeText(text: string) {
    if (!state) return
    setLoading(true)
    try {
      const parsed = await api.parseFreeText(text)
      if (parsed.length === 0) {
        showToast('无法理解此政令')
      } else if (parsed.length === 1) {
        await executeDecrees(parsed)
        return
      } else {
        setPendingMulti(parsed)
      }
    } catch (e) {
      showToast(e instanceof ApiError ? e.body.message : '解析失败')
    } finally {
      setLoading(false)
    }
  }

  async function handleNewGame() {
    if (state && state.decree_count > 0 && !confirm('当前进度未保存，确认开始新局？')) return
    try {
      const s = await api.newGame()
      reset()
      setState(s)
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : '创建新局失败')
    }
  }

  async function handleSave() {
    try {
      await api.save()
      showToast('存档成功')
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : '存档失败')
    }
  }

  function handleLoadSave(s: GameState) {
    reset()
    setState(s)
    setShowSaves(false)
  }

  if (!state) {
    return (
      <div className="loading-overlay">
        <div className="spinner" />
      </div>
    )
  }

  return (
    <div className="game-layout">
      <ResourceBar
        state={state}
        prevState={prevState}
        onSave={handleSave}
        onShowSaves={() => setShowSaves(true)}
        onNewGame={handleNewGame}
      />
      <div className="main-area">
        <RegionMap regions={state.regions} />
        <FactionPanel factions={state.factions} />
      </div>
      <div className="bottom-panel">
        <EventBar events={state.active_events} />
        <ActionArea
          state={state}
          loading={loading}
          onDecree={executeDecrees}
          onFreeText={handleFreeText}
        />
      </div>

      {loading && (
        <div className="loading-overlay">
          <div className="spinner" />
        </div>
      )}

      {narrative && !gameOver && (
        <NarrativeModal narrative={narrative} delta={delta} onClose={() => setNarrative(null)} />
      )}

      {gameOver && (
        <GameOverScreen
          result={gameOver.result}
          message={gameOver.message}
          state={state}
          onNewGame={handleNewGame}
        />
      )}

      {pendingMulti && (
        <MultiConfirm
          decrees={pendingMulti}
          onConfirm={() => {
            const d = pendingMulti
            setPendingMulti(null)
            executeDecrees(d)
          }}
          onCancel={() => setPendingMulti(null)}
        />
      )}

      {showSaves && (
        <SavePanel
          onLoad={handleLoadSave}
          onClose={() => setShowSaves(false)}
          hasUnsaved={state.decree_count > 0}
        />
      )}

      {toast && <div className="toast">{toast}</div>}

      {error && <div className="toast">{error}</div>}
    </div>
  )
}

export default App
