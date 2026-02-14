import { useEffect, useState, useCallback, useRef } from 'react'
import { useStore } from './hooks/store'
import { api, ApiError } from './api/client'
import type { StructuredDecree, DecreeResponse, GameState, GameEvent, DecreeType } from './types/game'
import ResourceBar from './components/ResourceBar'
import RegionMap from './components/RegionMap'
import FactionPanel from './components/FactionPanel'
import MinisterPanel from './components/MinisterPanel'
import EventBar from './components/EventBar'
import ActionArea from './components/ActionArea'
import NarrativeModal from './components/NarrativeModal'
import GameOverScreen from './components/GameOverScreen'
import MultiConfirm from './components/MultiConfirm'
import SavePanel from './components/SavePanel'
import ScriptEventModal from './components/ScriptEventModal'
import DebatePanel from './components/DebatePanel'
import './App.css'

type RightTab = 'faction' | 'minister'

function App() {
  const {
    state, loading, error, narrative, gameOver, prevState,
    capabilities, debateResult, debateLoading, selectedTopic,
    setState, setLoading, setError, setNarrative, setGameOver, setPrevState,
    setCapabilities, setDebateResult, setDebateLoading, setSelectedTopic,
    reset,
  } = useStore()

  const [delta, setDelta] = useState<Record<string, number>>({})
  const [showSaves, setShowSaves] = useState(false)
  const [pendingMulti, setPendingMulti] = useState<StructuredDecree[] | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [scriptEvent, setScriptEvent] = useState<GameEvent | null>(null)
  const [rightTab, setRightTab] = useState<RightTab>('faction')
  const [prefilledDecree, setPrefilledDecree] = useState<StructuredDecree | null>(null)
  const [prefilledKeywords, setPrefilledKeywords] = useState<string[]>([])
  const toastTimer = useRef<number>(0)
  const capsFetched = useRef(false)
  const capsFetchInFlight = useRef(false)

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 3000)
  }, [])

  const fetchCapabilities = useCallback(async () => {
    if (capsFetched.current || capsFetchInFlight.current) return
    capsFetchInFlight.current = true
    try {
      const c = await api.getCapabilities()
      setCapabilities(c)
      capsFetched.current = true
    } catch {
      capsFetched.current = false
    } finally {
      capsFetchInFlight.current = false
    }
  }, [setCapabilities])

  // Fetch initial state
  useEffect(() => {
    api.getState()
      .then((s) => setState(s))
      .catch(() => {
        api.newGame().then((s) => setState(s)).catch((e) => showToast(e instanceof ApiError ? e.message : '连接后端失败'))
      })
  }, [setState, showToast])

  // Fetch capabilities (with retry on next interaction if failed)
  useEffect(() => {
    void fetchCapabilities()
  }, [fetchCapabilities])

  // Cleanup toast timer
  useEffect(() => () => { window.clearTimeout(toastTimer.current) }, [])

  // Auto-open blocking scripted events
  useEffect(() => {
    if (!state || scriptEvent || loading) return
    const blocking = state.active_events.find(e => e.is_scripted && e.choices.length > 0)
    if (blocking) setScriptEvent(blocking)
  }, [state, scriptEvent, loading])

  async function executeDecrees(decrees: StructuredDecree[], sourceScriptId?: string) {
    if (!state) return
    setLoading(true)
    setError(null)
    setPrevState(state)
    try {
      const res: DecreeResponse = await api.decree(decrees, sourceScriptId)
      setState(res.state)
      setDelta(res.delta)
      setNarrative(res.narrative)
      if (res.game_over) setGameOver(res.game_over)
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          showToast('正在处理上一道政令，请稍候')
        } else {
          const ai = e.body.details?.ai_narrative
          if (ai) setNarrative(ai)
          else showToast(e.body.message)
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

  async function handleDebateStart(topic: string, category: DecreeType) {
    setDebateLoading(true)
    setSelectedTopic(topic)
    try {
      const result = await api.startDebate(topic, category)
      setDebateResult(result)
    } catch (e) {
      setSelectedTopic(null)
      showToast(e instanceof ApiError ? e.body.message : '廷推失败')
    } finally {
      setDebateLoading(false)
    }
  }

  function handleDebateAdopt(decree: StructuredDecree, keywords: string[]) {
    setDebateResult(null)
    setSelectedTopic(null)
    setPrefilledDecree(decree)
    setPrefilledKeywords(keywords)
  }

  async function handleDebateSilence() {
    setDebateResult(null)
    setSelectedTopic(null)
    try {
      const res = await api.silenceDebate()
      setState(res.state)
      if (res.prestige_change > 0) showToast(`威望 +${res.prestige_change}`)
    } catch (e) {
      showToast(e instanceof ApiError ? e.body.message : '操作失败')
    }
  }

  async function handleNewGame() {
    if (state && state.decree_count > 0 && !confirm('当前进度未保存，确认开始新局？')) return
    try {
      const s = await api.newGame()
      reset()
      setState(s)
      capsFetched.current = false
      void fetchCapabilities()
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

  function handleLoadSave(s: GameState, migrationNote?: string) {
    reset()
    setState(s)
    setShowSaves(false)
    setScriptEvent(null)
    capsFetched.current = false
    void fetchCapabilities()
    if (migrationNote) showToast(migrationNote)
  }

  const hasBlockingEvent = !!state?.active_events.some(e => e.is_scripted && e.choices.length > 0)

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
        <div className="right-panel">
          <div className="right-panel-tabs">
            <button
              className={`rp-tab${rightTab === 'faction' ? ' active' : ''}`}
              onClick={() => setRightTab('faction')}
            >派系</button>
            <button
              className={`rp-tab${rightTab === 'minister' ? ' active' : ''}`}
              onClick={() => setRightTab('minister')}
            >大臣</button>
          </div>
          <div className="right-panel-body">
            {rightTab === 'faction'
              ? <FactionPanel factions={state.factions} />
              : <MinisterPanel ministers={state.ministers} />
            }
          </div>
        </div>
      </div>
      <div className="bottom-panel">
        <EventBar events={state.active_events} onScriptClick={setScriptEvent} />
        <ActionArea
          state={state}
          loading={loading}
          capabilities={capabilities}
          hasBlockingEvent={hasBlockingEvent}
          debateLoading={debateLoading}
          onDecree={executeDecrees}
          onFreeText={handleFreeText}
          onDebateStart={handleDebateStart}
          prefilledDecree={prefilledDecree}
          prefilledKeywords={prefilledKeywords}
          onPrefilledClear={() => { setPrefilledDecree(null); setPrefilledKeywords([]) }}
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

      {scriptEvent && (
        <ScriptEventModal
          event={scriptEvent}
          state={state}
          onChoose={(decrees, scriptId) => {
            setScriptEvent(null)
            executeDecrees(decrees, scriptId)
          }}
        />
      )}

      {debateResult && selectedTopic && (
        <DebatePanel
          result={debateResult}
          topic={selectedTopic}
          onAdopt={handleDebateAdopt}
          onSilence={handleDebateSilence}
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
