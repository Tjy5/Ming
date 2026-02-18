import { useEffect, useState, useCallback, useRef } from 'react'
import { useStore } from './hooks/store'
import { api, ApiError } from './api/client'
import type { StructuredDecree, DecreeResponse, GameState, GameEvent, DecreeType, DebateResult, MinisterReaction, TurnSummary, CourtAssembly } from './types/game'
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
import MemorialPanel from './components/MemorialPanel'
import CourtAssemblyView from './components/CourtAssemblyView'
import AiSettingsModal from './components/AiSettingsModal'
import './App.css'

type RightTab = 'faction' | 'minister' | 'assembly'
type NarrativePayload = {
  narrative: string
  delta: Record<string, number>
  ministerReactions?: MinisterReaction[]
  turnSummary?: TurnSummary
}

function App() {
  const {
    state, loading, error, gameOver, prevState,
    capabilities, debateLoading, currentModal,
    setState, setLoading, setError, setGameOver, setPrevState,
    setCapabilities, setDebateLoading,
    pushModal, popModal, clearModals, reset,
  } = useStore()

  const [showSaves, setShowSaves] = useState(false)
  const [showAiSettings, setShowAiSettings] = useState(false)
  const [pendingMulti, setPendingMulti] = useState<StructuredDecree[] | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [rightTab, setRightTab] = useState<RightTab>('faction')
  const [prefilledDecree, setPrefilledDecree] = useState<StructuredDecree | null>(null)
  const [prefilledKeywords, setPrefilledKeywords] = useState<string[]>([])
  const [lastReactions, setLastReactions] = useState<MinisterReaction[]>([])
  const [assemblyLoading, setAssemblyLoading] = useState(false)
  const toastTimer = useRef<number>(0)
  const capsFetched = useRef(false)
  const capsFetchInFlight = useRef(false)
  const decreeInFlight = useRef(false)
  const blockingPushedFor = useRef<string | null>(null)

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 3000)
  }, [])

  function queueTurnResultModals(res: DecreeResponse) {
    pushModal({
      type: 'narrative',
      priority: 50,
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
  }

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
    if (!state || loading) return
    const blocking = state.active_events.find(
      e => e.is_scripted && e.is_blocking && e.choices.length > 0,
    )
    if (blocking && blockingPushedFor.current !== blocking.script_id) {
      blockingPushedFor.current = blocking.script_id
      pushModal({ type: 'script_event_blocking', priority: 90, payload: blocking })
    } else if (!blocking) {
      blockingPushedFor.current = null
    }
  }, [state, loading, pushModal])

  async function executeDecrees(decrees: StructuredDecree[], sourceScriptId?: string, freeText?: string): Promise<string | null> {
    if (!state) return 'no_state'
    if (decreeInFlight.current) {
      showToast('正在处理上一道政令，请稍候')
      return 'in_flight'
    }
    decreeInFlight.current = true
    setLoading(true)
    setError(null)
    setPrevState(state)
    try {
      const res = await api.decree(decrees, sourceScriptId, freeText)
      setState(res.state)
      if (res.minister_reactions?.length) setLastReactions(res.minister_reactions)
      if (res.game_over) {
        setGameOver(res.game_over)
      } else {
        queueTurnResultModals(res)
      }
      return null
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.body.error_code === 'FREEFORM_EMPTY') {
          return 'FREEFORM_EMPTY'
        }
        if (e.status === 409) {
          showToast(e.body.message || '正在处理上一道政令，请稍候')
        } else {
          const aiRaw = e.body.details?.ai_narrative
          const ai = typeof aiRaw === 'string' ? aiRaw : null
          if (ai) pushModal({ type: 'narrative', priority: 50, payload: { narrative: ai, delta: {} } })
          else showToast(e.body.message)
        }
      } else {
        showToast('网络错误，请重试')
      }
      return 'error'
    } finally {
      decreeInFlight.current = false
      setLoading(false)
    }
  }

  async function handleFreeText(text: string) {
    if (!state) return
    const trimmed = text.trim()
    if (!trimmed) return
    if (trimmed.length > 200) {
      showToast('政令文本过长（最多200字）')
      return
    }
    await executeDecrees([], undefined, trimmed)
  }

  async function handleDebateStart(topic: string, category: DecreeType) {
    setDebateLoading(true)
    try {
      const result = await api.startDebate(topic, category)
      pushModal({ type: 'debate', priority: 20, payload: { result, topic } })
    } catch (e) {
      showToast(e instanceof ApiError ? e.body.message : '廷推失败')
    } finally {
      setDebateLoading(false)
    }
  }

  function handleDebateAdopt(decree: StructuredDecree, keywords: string[]) {
    popModal()
    setPrefilledDecree(decree)
    setPrefilledKeywords(keywords)
  }

  async function handleDebateSilence() {
    popModal()
    try {
      const res = await api.silenceDebate()
      setState(res.state)
      if (res.prestige_change > 0) showToast(`威望 +${res.prestige_change}`)
    } catch (e) {
      showToast(e instanceof ApiError ? e.body.message : '操作失败')
    }
  }

  async function handleMemorialResolve(id: string, action: 'approved' | 'rejected' | 'deferred') {
    try {
      setLoading(true)
      const res = await api.resolveMemorial(id, action)
      setState(res.state)
      const pendingAfter = res.state.memorials?.filter(m => m.status === 'pending' || m.status === 'deferred') ?? []
      if (currentModal?.type === 'memorial' && pendingAfter.length === 0) {
        popModal()
      }
      const labels = { approved: '准奏', rejected: '驳回', deferred: '留中' }
      showToast(`奏折已${labels[action]}`)
    } catch (e) {
      showToast(e instanceof ApiError ? e.body.message : '操作失败')
    } finally {
      setLoading(false)
    }
  }

  async function handleConveneAssembly(topic: string, decreeType: DecreeType) {
    setAssemblyLoading(true)
    try {
      const assembly = await api.conveneAssembly(topic, decreeType)
      pushModal({ type: 'assembly', priority: 20, payload: assembly })
    } catch (e) {
      showToast(e instanceof ApiError ? e.body.message : '朝会召集失败')
    } finally {
      setAssemblyLoading(false)
    }
  }

  async function handleAdoptSuggestion(index: number) {
    popModal()
    setLoading(true)
    try {
      const res: DecreeResponse = await api.adoptSuggestion(index)
      setState(res.state)
      if (res.minister_reactions?.length) setLastReactions(res.minister_reactions)
      if (res.game_over) {
        setGameOver(res.game_over)
      } else {
        queueTurnResultModals(res)
      }
    } catch (e) {
      showToast(e instanceof ApiError ? e.body.message : '采纳失败')
    } finally {
      setLoading(false)
    }
  }

  async function handleAssemblySilence() {
    popModal()
    try {
      const res = await api.silenceAssembly()
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
    clearModals()
    blockingPushedFor.current = null
    capsFetched.current = false
    void fetchCapabilities()
    if (migrationNote) showToast(migrationNote)
  }

  function handleAiSettingsSaved(message: string) {
    setShowAiSettings(false)
    showToast(message)
    capsFetched.current = false
    void fetchCapabilities()
  }

  const hasBlockingEvent = !!state?.active_events.some(
    e => e.is_scripted && e.is_blocking && e.choices.length > 0,
  )
  const pendingMemorials = state?.memorials?.filter(m => m.status === 'pending' || m.status === 'deferred') ?? []

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
        onOpenAiSettings={() => setShowAiSettings(true)}
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
            <button
              className={`rp-tab${rightTab === 'assembly' ? ' active' : ''}`}
              onClick={() => setRightTab('assembly')}
            >朝议</button>
          </div>
          <div className="right-panel-body">
            {rightTab === 'faction' && <FactionPanel factions={state.factions} />}
            {rightTab === 'minister' && <MinisterPanel ministers={state.ministers} reactions={lastReactions} />}
            {rightTab === 'assembly' && (
              <CourtAssemblyView
                state={state}
                capabilities={capabilities}
                loading={assemblyLoading}
                onConvene={handleConveneAssembly}
                onAdopt={handleAdoptSuggestion}
                onSilence={handleAssemblySilence}
              />
            )}
          </div>
        </div>
      </div>
      <div className="bottom-panel">
        <EventBar
          events={state.active_events}
          pendingMemorials={pendingMemorials.length}
          onScriptClick={(e) => pushModal({ type: 'script_event', priority: 10, payload: e })}
          onMemorialClick={() => {
            if (pendingMemorials.length) pushModal({ type: 'memorial', priority: 30, payload: pendingMemorials })
          }}
        />
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
          <div className="streaming-panel">
            <div className="streaming-header">
              <div className="spinner" />
              <span>正在处理政令……</span>
            </div>
          </div>
        </div>
      )}

      {currentModal?.type === 'narrative' && !gameOver && (() => {
        const p = currentModal.payload as NarrativePayload
        return (
          <NarrativeModal
            narrative={p.narrative}
            delta={p.delta}
            ministerReactions={p.ministerReactions}
            turnSummary={p.turnSummary}
            onClose={popModal}
          />
        )
      })()}

      {currentModal?.type === 'memorial' && (
        <MemorialPanel
          memorials={pendingMemorials}
          onResolve={handleMemorialResolve}
          onClose={popModal}
        />
      )}

      {currentModal?.type === 'assembly' && (
        <CourtAssemblyView
          assembly={currentModal.payload as CourtAssembly}
          onAdopt={handleAdoptSuggestion}
          onSilence={handleAssemblySilence}
          onClose={popModal}
          asModal
        />
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

      {(currentModal?.type === 'script_event_blocking' || currentModal?.type === 'script_event') && (
        <ScriptEventModal
          event={currentModal.payload as GameEvent}
          onChoose={async (decrees, scriptId, freeText) => {
            const errorCode = await executeDecrees(decrees, scriptId, freeText)
            if (!errorCode) popModal()
            return errorCode
          }}
        />
      )}

      {currentModal?.type === 'debate' && (
        <DebatePanel
          result={(currentModal.payload as { result: DebateResult; topic: string }).result}
          topic={(currentModal.payload as { result: DebateResult; topic: string }).topic}
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

      {showAiSettings && (
        <AiSettingsModal
          onClose={() => setShowAiSettings(false)}
          onSaved={handleAiSettingsSaved}
        />
      )}

      {toast && <div className="toast">{toast}</div>}

      {error && <div className="toast">{error}</div>}
    </div>
  )
}

export default App
