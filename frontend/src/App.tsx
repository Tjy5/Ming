import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from './hooks/store'
import { api, ApiError } from './api/client'
import type { StructuredDecree, GameState, GameEvent, MinisterReaction, TurnSummary, CourtAssembly, Minister } from './types/game'
import ResourceBar from './components/ResourceBar'
import RegionMap from './components/RegionMap'
import CourtDrawer, { CourtDrawerHandles, type CourtDrawerTab } from './components/CourtDrawer'
import Ck3EventFeed from './components/Ck3EventFeed'
import ImperialEdictModal from './components/ImperialEdictModal'
import CommandHud from './components/CommandHud'
import NarrativeModal from './components/NarrativeModal'
import GameOverScreen from './components/GameOverScreen'
import MultiConfirm from './components/MultiConfirm'
import SavePanel from './components/SavePanel'
import ScriptEventModal from './components/ScriptEventModal'
import MemorialPanel from './components/MemorialPanel'
import CourtAssemblyView from './components/CourtAssemblyView'
import AiSettingsModal from './components/AiSettingsModal'
import MinisterDialogue from './components/MinisterDialogue'
import OfficialRankModal from './components/OfficialRankModal'
import GuideModal from './components/GuideModal'
import RegionInspector from './components/RegionInspector'
import { joinRegionsToGovernanceDivisions, type GovernanceDivisionStatus } from './data/map/geography'
import { shouldAutoOpenGuide } from './components/guideModalLogic'
import { MODE_SELECT_OPERATION_FLAG } from './constants/modeSelect'
import { useDecreeExecution } from './hooks/useDecreeExecution'
import { useAdvanceMonth } from './hooks/useAdvanceMonth'
import './App.css'

type NarrativePayload = {
  narrative: string
  delta: Record<string, number>
  ministerReactions?: MinisterReaction[]
  turnSummary?: TurnSummary
  settlementId?: string | null
  contextVersionId?: string | null
}

function App() {
  const navigate = useNavigate()
  const {
    state, loading, error, gameOver, prevState,
    capabilities, currentModal,
    setState, setLoading, setError, setGameOver, setPrevState,
    setCapabilities,
    pushModal, popModal, clearModals, reset,
  } = useStore()

  const [showSaves, setShowSaves] = useState(false)
  const [showAiSettings, setShowAiSettings] = useState(false)
  const [showOfficialRank, setShowOfficialRank] = useState(false)
  const [pendingMulti, setPendingMulti] = useState<StructuredDecree[] | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [courtDrawerTab, setCourtDrawerTab] = useState<CourtDrawerTab>('faction')
  const [courtDrawerOpen, setCourtDrawerOpen] = useState(false)
  const [edictModalOpen, setEdictModalOpen] = useState(false)
  const [lastReactions, setLastReactions] = useState<MinisterReaction[]>([])
  const toastTimer = useRef<number>(0)
  const capsFetched = useRef(false)
  const capsFetchInFlight = useRef(false)
  const memorialResolveInFlight = useRef(false)
  const blockingPushedFor = useRef<string | null>(null)
  const [memorialResolving, setMemorialResolving] = useState(false)
  const [dialogueMinisterName, setDialogueMinisterName] = useState<string | null>(null)
  const [selectedDivisionId, setSelectedDivisionId] = useState<string | null>(null)
  const [targetRegion, setTargetRegion] = useState<string | null>(null)
  const [targetRegionMembers, setTargetRegionMembers] = useState<readonly string[]>([])
  const [guideOpen, setGuideOpen] = useState(false)
  const memorialTrigger = useRef<HTMLElement | null>(null)

  const closeRegionInspector = useCallback(() => {
    const divisionId = selectedDivisionId
    setSelectedDivisionId(null)
    if (divisionId) {
      window.setTimeout(() => {
        document.querySelector<SVGGElement>(`[data-governance-division-id="${divisionId}"]`)?.focus()
      }, 0)
    }
  }, [selectedDivisionId])

  const closeMemorialPanel = useCallback(() => {
    popModal()
    window.setTimeout(() => memorialTrigger.current?.focus(), 0)
  }, [popModal])

  useEffect(() => {
    if (shouldAutoOpenGuide()) setGuideOpen(true)
  }, [])

  const governanceDivisions = useMemo(
    () => joinRegionsToGovernanceDivisions(state?.regions ?? []).divisions,
    [state?.regions],
  )
  const selectedDivision = selectedDivisionId
    ? governanceDivisions.find((item) => item.division.id === selectedDivisionId && item.region) ?? null
    : null

  useEffect(() => {
    if (selectedDivisionId && !selectedDivision) setSelectedDivisionId(null)
  }, [selectedDivision, selectedDivisionId])

  const handleDivisionClick = useCallback((item: GovernanceDivisionStatus) => {
    if (item.region) setSelectedDivisionId(item.division.id)
  }, [])

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

  // Fetch initial state（GameRoot 已按 phase 分流并预载时跳过）
  useEffect(() => {
    if (useStore.getState().state) return
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

  // Route blocking scripted events through mode selection.
  useEffect(() => {
    if (!state || loading) return
    const blocking = state.active_events.find(
      e => e.is_scripted && e.is_blocking && e.choices.length > 0,
    )
    if (blocking) {
      const operationFlag = sessionStorage.getItem(MODE_SELECT_OPERATION_FLAG)
      if (operationFlag) {
        if (blockingPushedFor.current !== blocking.script_id) {
          blockingPushedFor.current = blocking.script_id
          pushModal({ type: 'script_event_blocking', priority: 90, payload: blocking })
        }
        sessionStorage.removeItem(MODE_SELECT_OPERATION_FLAG)
        return
      }

      if (blockingPushedFor.current !== blocking.script_id) {
        blockingPushedFor.current = blocking.script_id
        navigate('/mode-select')
      }
    } else if (!blocking) {
      blockingPushedFor.current = null
      sessionStorage.removeItem(MODE_SELECT_OPERATION_FLAG)
    }
  }, [state, loading, navigate, pushModal])

  async function handleMemorialResolve(id: string, action: 'approved' | 'rejected' | 'deferred') {
    if (memorialResolveInFlight.current) return
    memorialResolveInFlight.current = true
    try {
      setMemorialResolving(true)
      setLoading(true)
      const res = await api.resolveMemorial(id, action)
      setState(res.state)
      return {
        narrative: res.narrative ?? undefined,
        delta: res.delta ?? undefined,
      }
    } catch (e) {
      if (e instanceof ApiError && (e.body.error_code === 'memorial_not_found' || e.body.error_code === 'already_resolved')) {
        try {
          const latest = await api.getState()
          setState(latest)
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

  const blockingEvents = useMemo(
    () => state?.active_events.filter(
      e => e.is_scripted && e.is_blocking && e.choices.length > 0,
    ) ?? [],
    [state?.active_events],
  )
  const hasBlockingEvent = blockingEvents.length > 0

  const handleBlockingEventClick = useCallback(() => {
    if (blockingEvents[0]) {
      pushModal({ type: 'script_event_blocking', priority: 90, payload: blockingEvents[0] })
    }
  }, [blockingEvents, pushModal])

  const {
    decreeInFlight,
    applyDecreeResult,
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
    onMissionComplete: (name, missionName) => showToast(`${name} 完成任务：${missionName}`),
  })
  const pendingMemorials = state?.memorials?.filter(m => m.status === 'pending' || m.status === 'deferred') ?? []

  if (!state) {
    return (
      <div className="loading-overlay">
        <div className="spinner" />
      </div>
    )
  }

  const isLifeStory = state.phase === 'life_story'

  return (
    <div className="game-layout">
      <ResourceBar
        state={state}
        prevState={prevState}
        pendingMemorials={pendingMemorials.length}
        onMemorialClick={() => {
          if (pendingMemorials.length) {
            memorialTrigger.current = document.activeElement as HTMLElement | null
            pushModal({ type: 'memorial', priority: 30, payload: pendingMemorials })
          }
        }}
        blockingEvents={blockingEvents.length}
        onBlockingEventClick={handleBlockingEventClick}
        onSave={handleSave}
        onShowSaves={() => setShowSaves(true)}
        onOpenAiSettings={() => setShowAiSettings(true)}
        onOpenChat={() => navigate('/chat')}
        onOpenTrpg={() => navigate('/trpg')}
        onOpenContinuity={() => navigate('/continuity')}
        onOpenGuide={() => setGuideOpen(true)}
        onNewGame={handleNewGame}
      />

      <main className="main-area">
        <div className="map-workspace">
          <RegionMap
            regions={state.regions}
            highlightDivisionId={selectedDivision?.division.id}
            onDivisionClick={handleDivisionClick}
            railControls={(
              <CourtDrawerHandles
                isOpen={courtDrawerOpen}
                activeTab={courtDrawerTab}
                onTabChange={(tab) => {
                  setCourtDrawerTab(tab)
                  setCourtDrawerOpen(true)
                }}
              />
            )}
          />
          {selectedDivision?.region && (
            <RegionInspector
              region={selectedDivision.region}
              sourceRegions={selectedDivision.sourceRegions}
              entityRegistry={state.entity_registry}
              activeEvents={state.active_events}
              versionId={state.world_metadata?.version_id}
              onClose={closeRegionInspector}
              onAct={() => {
                setTargetRegion(selectedDivision.division.name)
                setTargetRegionMembers(selectedDivision.sourceRegions.map((region) => region.name))
                setEdictModalOpen(true)
              }}
            />
          )}
        </div>

        {/* CK3 风格左下角文字消息流 */}
        <Ck3EventFeed
          events={state.active_events}
          onScriptClick={(e) => pushModal({ type: 'script_event', priority: 10, payload: e })}
        />

        {/* 朝廷折叠抽屉面板；入口位于地图右侧控制栏 */}
        <CourtDrawer
          isOpen={courtDrawerOpen}
          activeTab={courtDrawerTab}
          onTabChange={(tab) => {
            setCourtDrawerTab(tab)
            setCourtDrawerOpen(true)
          }}
          onToggle={() => setCourtDrawerOpen((prev) => !prev)}
          onClose={() => setCourtDrawerOpen(false)}
          state={state}
          capabilities={capabilities}
          lastReactions={lastReactions}
          onMinisterClick={handleMinisterClick}
          onShowOfficialRank={() => setShowOfficialRank(true)}
          onStateUpdate={setState}
          onAdoptionResult={(response) => applyDecreeResult(response, state)}
          onShowToast={showToast}
        />

        {/* 底部悬浮行动指令台 */}
        <CommandHud
          state={state}
          loading={loading}
          hasBlockingEvent={hasBlockingEvent}
          advanceMonthInFlight={advanceMonthInFlight}
          currentModal={currentModal}
          targetRegion={targetRegion}
          isLifeStory={isLifeStory}
          onOpenEdictModal={() => setEdictModalOpen(true)}
          onAdvanceMonth={handleAdvanceMonth}
          onOpenTrpg={() => navigate('/trpg')}
        />
      </main>

      {/* 御笔草诏台弹窗（非全屏古风宣纸卷轴） */}
      <ImperialEdictModal
        isOpen={edictModalOpen}
        onClose={() => setEdictModalOpen(false)}
        state={state}
        loading={loading}
        hasBlockingEvent={hasBlockingEvent}
        targetRegion={targetRegion}
        targetRegionMembers={targetRegionMembers}
        onClearTargetRegion={() => {
          setTargetRegion(null)
          setTargetRegionMembers([])
        }}
        onDecree={executeDecrees}
        onFreeText={handleFreeText}
      />

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
            settlementId={p.settlementId}
            contextVersionId={p.contextVersionId}
            onClose={popModal}
          />
        )
      })()}

      {currentModal?.type === 'memorial' && (
        <MemorialPanel
          memorials={state?.memorials ?? []}
          resolving={memorialResolving}
          onResolve={handleMemorialResolve}
          onClose={closeMemorialPanel}
        />
      )}

      {currentModal?.type === 'assembly' && (
        <CourtAssemblyView
          assembly={currentModal.payload as CourtAssembly}
          onStateUpdate={setState}
          onAdoptionResult={(response) => applyDecreeResult(response, state)}
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

      <GuideModal open={guideOpen} onClose={() => setGuideOpen(false)} />

      {toast && <div className="toast">{toast}</div>}

      {error && <div className="toast">{error}</div>}
    </div>
  )
}

export default App
