import { useEffect, useState, useCallback, useRef } from 'react'
import { useStore } from './hooks/store'
import { api, ApiError } from './api/client'
import type { StructuredDecree, GameState, GameEvent, DecreeType, DebateResult, MinisterReaction, TurnSummary, CourtAssembly, Minister } from './types/game'
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
import MinisterDialogue from './components/MinisterDialogue'
import OfficialRankModal from './components/OfficialRankModal'
import { useDecreeExecution } from './hooks/useDecreeExecution'
import { useAdvanceMonth } from './hooks/useAdvanceMonth'
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
  const [showOfficialRank, setShowOfficialRank] = useState(false)
  const [pendingMulti, setPendingMulti] = useState<StructuredDecree[] | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [rightTab, setRightTab] = useState<RightTab>('faction')
  const [prefilledDecree, setPrefilledDecree] = useState<StructuredDecree | null>(null)
  const [prefilledKeywords, setPrefilledKeywords] = useState<string[]>([])
  const [lastReactions, setLastReactions] = useState<MinisterReaction[]>([])
  const toastTimer = useRef<number>(0)
  const capsFetched = useRef(false)
  const capsFetchInFlight = useRef(false)
  const memorialResolveInFlight = useRef(false)
  const blockingPushedFor = useRef<string | null>(null)
  const [memorialResolving, setMemorialResolving] = useState(false)
  const [dialogueMinisterName, setDialogueMinisterName] = useState<string | null>(null)

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
    if (memorialResolveInFlight.current) return
    memorialResolveInFlight.current = true
    try {
      setMemorialResolving(true)
      setLoading(true)
      const res = await api.resolveMemorial(id, action)
      setState(res.state)
      const pendingAfter = res.state.memorials?.filter(m => m.status === 'pending' || m.status === 'deferred') ?? []
      if (currentModal?.type === 'memorial' && pendingAfter.length === 0) {
        popModal()
      }
      const labels = { approved: '准奏', rejected: '驳回', deferred: '留中' }
      showToast(`奏折已${labels[action]}`)
      return { narrative: res.narrative, delta: res.delta }
    } catch (e) {
      if (e instanceof ApiError && (e.body.error_code === 'memorial_not_found' || e.body.error_code === 'already_resolved')) {
        try {
          const latest = await api.getState()
          setState(latest)
          const pendingAfter = latest.memorials?.filter(m => m.status === 'pending' || m.status === 'deferred') ?? []
          if (currentModal?.type === 'memorial' && pendingAfter.length === 0) {
            popModal()
          }
          showToast('奏折状态已更新，请重新批阅')
        } catch {
          showToast(e.body.message)
        }
      } else {
        showToast(e instanceof ApiError ? e.body.message : '操作失败')
      }
    } finally {
      setLoading(false)
      setMemorialResolving(false)
      memorialResolveInFlight.current = false
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

  function handleMinisterClick(minister: Minister) {
    if (minister.status === 'not_yet_entered' || minister.status === 'idle' || minister.status === 'removed') {
      showToast('该大臣当前不可对话')
      return
    }
    setDialogueMinisterName(minister.name)
  }

  function handleAiSettingsSaved(message: string) {
    setShowAiSettings(false)
    showToast(message)
    capsFetched.current = false
    void fetchCapabilities()
  }

  function removeScriptModalById(scriptId: string) {
    useStore.setState((s) => {
      const isTargetScriptModal = (m: typeof s.currentModal) =>
        !!m &&
        (m.type === 'script_event' || m.type === 'script_event_blocking') &&
        (m.payload as GameEvent).script_id === scriptId

      if (isTargetScriptModal(s.currentModal)) {
        if (s.modalQueue.length === 0) {
          return { currentModal: null }
        }
        const [next, ...rest] = s.modalQueue
        return { currentModal: next, modalQueue: rest }
      }

      const filtered = s.modalQueue.filter((m) => !isTargetScriptModal(m))
      if (filtered.length === s.modalQueue.length) {
        return {}
      }
      return { modalQueue: filtered }
    })
  }

  const hasBlockingEvent = !!state?.active_events.some(
    e => e.is_scripted && e.is_blocking && e.choices.length > 0,
  )
  const {
    decreeInFlight,
    executeDecrees,
    handleFreeText,
  } = useDecreeExecution({
    state,
    setState,
    setLoading,
    setError,
    setPrevState,
    setGameOver,
    pushModal,
    showToast,
    onReactions: setLastReactions,
  })
  const {
    advanceMonthInFlight,
    handleAdvanceMonth,
  } = useAdvanceMonth({
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
  })
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
            <button
              className="rp-tab"
              onClick={() => setShowOfficialRank(true)}
            >官职</button>
          </div>
          <div className="right-panel-body">
            {rightTab === 'faction' && <FactionPanel factions={state.factions} />}
            {rightTab === 'minister' && <MinisterPanel ministers={state.ministers} reactions={lastReactions} onMinisterClick={handleMinisterClick} />}
            {rightTab === 'assembly' && (
              <CourtAssemblyView
                state={state}
                capabilities={capabilities}
                loading={false}
                onStateUpdate={setState}
                onShowToast={showToast}
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
        <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
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
          <button
            className="decree-btn"
            disabled={loading || !!currentModal || hasBlockingEvent || advanceMonthInFlight || decreeInFlight}
            onClick={handleAdvanceMonth}
            style={{ margin: '0 10px 10px 10px', height: '36px', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
          >
            {advanceMonthInFlight && <div className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px' }} />}
            进入下月
          </button>
        </div>
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
          memorials={state?.memorials?.filter(m => m.status !== 'rejected') ?? []}
          resolving={memorialResolving}
          onResolve={handleMemorialResolve}
          onClose={popModal}
        />
      )}

      {currentModal?.type === 'assembly' && (
        <CourtAssemblyView
          assembly={currentModal.payload as CourtAssembly}
          onStateUpdate={setState}
          onClose={popModal}
          onShowToast={showToast}
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
          onBack={popModal}
          onChoose={async (decrees, scriptId, freeText, loyaltyEffects, stateEffects) => {
            const errorCode = await executeDecrees(decrees, scriptId, freeText, loyaltyEffects, stateEffects)
            if (!errorCode) removeScriptModalById(scriptId)
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

      {showOfficialRank && (
        <OfficialRankModal
          ministers={state.ministers}
          onClose={() => setShowOfficialRank(false)}
          onAppoint={async (name, position) => {
            await executeDecrees([{ type: 'personnel', sub_action: 'appoint', target: name, parameters: { position } }])
          }}
        />
      )}

      {dialogueMinisterName && state && (
        <MinisterDialogue
          minister={state.ministers.find(m => m.name === dialogueMinisterName) || null}
          onClose={() => setDialogueMinisterName(null)}
          onStateUpdate={setState}
        />
      )}

      {toast && <div className="toast">{toast}</div>}

      {error && <div className="toast">{error}</div>}
    </div>
  )
}

export default App
