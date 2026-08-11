import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { api, ApiError } from '../api/client'
import type {
  AdoptSuggestionRequest,
  AssemblyPetition,
  AssemblySpeech,
  Capabilities,
  CourtAssembly,
  DecreeResponse,
  DecreeType,
  GameState,
  PolicySuggestion,
} from '../types/game'
import { DECREE_LABELS, DECREE_TYPES } from '../types/game'
import { isAbortError, showCancelToast } from '../utils/toast'

/* ── Props interfaces ── */
interface PanelProps {
  state: GameState
  capabilities: Capabilities
  loading: boolean
  onStateUpdate: (state: GameState) => void
  onAdoptionResult?: (response: DecreeResponse) => void
  onShowToast?: (msg: string) => void
}

interface ModalProps {
  assembly: CourtAssembly
  onStateUpdate: (state: GameState) => void
  onAdoptionResult?: (response: DecreeResponse) => void
  onClose: () => void
  onShowToast?: (msg: string) => void
  asModal: true
}

type Props = PanelProps | ModalProps

function isModal(p: Props): p is ModalProps {
  return 'asModal' in p && p.asModal === true
}

/* ── Main component ── */
export default function CourtAssemblyView(props: Props) {
  if (isModal(props)) {
    return (
      <div className="modal-overlay" onClick={props.onClose}>
        <motion.div
          className="modal assembly-modal"
          onClick={e => e.stopPropagation()}
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
        >
          <AssemblyFlow
            initialAssembly={props.assembly}
            onStateUpdate={props.onStateUpdate}
            onAdoptionResult={props.onAdoptionResult}
            onClose={props.onClose}
            onShowToast={props.onShowToast}
          />
        </motion.div>
      </div>
    )
  }

  return <AssemblyPanel {...props} />
}

/* ── Panel mode (right sidebar tab) ── */
function AssemblyPanel({
  state,
  capabilities,
  loading,
  onStateUpdate,
  onAdoptionResult,
  onShowToast,
}: PanelProps) {
  const [selectedType, setSelectedType] = useState<DecreeType>(DECREE_TYPES[0])
  const [showFlow, setShowFlow] = useState(false)
  const [assembly, setAssembly] = useState<CourtAssembly | null>(null)
  const [panelLoading, setPanelLoading] = useState(false)
  const [panelError, setPanelError] = useState<string | null>(null)

  const activeMinisters = state.ministers.filter((m) => m.status === 'active').length
  const canConvene = !loading && !panelLoading

  async function handleStartAssembly() {
    if (!canConvene) return
    setPanelLoading(true)
    setPanelError(null)
    try {
      const data = await api.startAssembly()
      setAssembly({
        ...data,
        decree_type: data.decree_type ?? selectedType,
      })
      setShowFlow(true)
    } catch (e) {
      setPanelError(e instanceof ApiError ? e.body.message : '朝会召集失败')
    } finally {
      setPanelLoading(false)
    }
  }

  if (showFlow && assembly) {
    return (
      <AssemblyFlow
        initialAssembly={assembly}
        onStateUpdate={onStateUpdate}
        onAdoptionResult={onAdoptionResult}
        onClose={() => {
          setShowFlow(false)
          setAssembly(null)
        }}
        onShowToast={onShowToast}
      />
    )
  }

  return (
    <div className="assembly-panel">
      <div className="assembly-convene-section">
        <div className="as-title">召集朝会</div>
        {!capabilities.assembly_supported && (
          <div className="assembly-error">当前配置显示朝会可能不可用，仍可尝试召集</div>
        )}
        {activeMinisters < 10 && (
          <div className="assembly-error">在朝大臣不足 10 人，无法召开朝会</div>
        )}
        {panelError && (
          <div className="assembly-error">{panelError}</div>
        )}
        <select
          className="assembly-select"
          value={selectedType}
          onChange={e => setSelectedType(e.target.value as DecreeType)}
        >
          {DECREE_TYPES.map(dt => (
            <option key={dt} value={dt}>{DECREE_LABELS[dt]}</option>
          ))}
        </select>
        <button
          className="assembly-start-btn"
          disabled={!canConvene}
          onClick={handleStartAssembly}
        >
          {(loading || panelLoading) ? '召集中...' : '召开朝会'}
        </button>
      </div>
    </div>
  )
}

/* ── Assembly flow (multi-phase state machine) ── */
interface AssemblyFlowProps {
  initialAssembly: CourtAssembly
  onStateUpdate: (state: GameState) => void
  onAdoptionResult?: (response: DecreeResponse) => void
  onClose: () => void
  onShowToast?: (msg: string) => void
}

function AssemblyFlow({
  initialAssembly,
  onStateUpdate,
  onAdoptionResult,
  onClose,
  onShowToast,
}: AssemblyFlowProps) {
  const [assembly, setAssembly] = useState<CourtAssembly>(initialAssembly)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const handleStartDebate = async (topic: string) => {
    setLoading(true)
    setError(null)
    if (abortControllerRef.current) abortControllerRef.current.abort()
    abortControllerRef.current = new AbortController()
    try {
      const data = await api.startAssemblyDebate(topic, assembly.decree_type ?? undefined, abortControllerRef.current.signal)
      setAssembly(data)
    } catch (e) {
      if (isAbortError(e)) {
        if (onShowToast) showCancelToast(onShowToast)
      } else {
        setError(e instanceof ApiError ? e.body.message : '议政失败')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleImperialRage = async (faction: string) => {
    setLoading(true)
    setError(null)
    if (abortControllerRef.current) abortControllerRef.current.abort()
    abortControllerRef.current = new AbortController()
    try {
      const data = await api.imperialRage(faction, abortControllerRef.current.signal)
      setAssembly(data.assembly)
      onStateUpdate(data.state)
    } catch (e) {
      if (isAbortError(e)) {
        if (onShowToast) showCancelToast(onShowToast)
      } else {
        setError(e instanceof ApiError ? e.body.message : '震怒失败')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleStartVote = async () => {
    setLoading(true)
    setError(null)
    if (abortControllerRef.current) abortControllerRef.current.abort()
    abortControllerRef.current = new AbortController()
    try {
      const data = await api.startAssemblyVote(assembly.decree_type ?? undefined, abortControllerRef.current.signal)
      setAssembly(data.assembly)
    } catch (e) {
      if (isAbortError(e)) {
        if (onShowToast) showCancelToast(onShowToast)
      } else {
        setError(e instanceof ApiError ? e.body.message : '廷推失败')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleAdoptSuggestion = async (payload: AdoptSuggestionRequest) => {
    setLoading(true)
    setError(null)
    if (abortControllerRef.current) abortControllerRef.current.abort()
    abortControllerRef.current = new AbortController()
    try {
      const data = await api.adoptSuggestion(payload, abortControllerRef.current.signal)
      onClose()
      if (onAdoptionResult) onAdoptionResult(data)
      else onStateUpdate(data.state)
      onShowToast?.('已依据当前世界重新结算，候选文字未被当作结果承诺')
    } catch (e) {
      if (isAbortError(e)) {
        if (onShowToast) showCancelToast(onShowToast)
      } else {
        setError(e instanceof ApiError ? e.body.message : '候选方案采用失败')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleSkipAll = async () => {
    setLoading(true)
    setError(null)
    if (abortControllerRef.current) abortControllerRef.current.abort()
    abortControllerRef.current = new AbortController()
    try {
      const fallbackTopic = (assembly.current_topic || assembly.topic || '暂缓议题').trim()
      const debated = await api.startAssemblyDebate(
        fallbackTopic || '暂缓议题',
        assembly.decree_type ?? undefined,
        abortControllerRef.current.signal,
      )
      const voted = await api.startAssemblyVote(debated.decree_type ?? assembly.decree_type ?? undefined, abortControllerRef.current.signal)
      setAssembly(voted.assembly)
      const { assembly: next, state } = await api.finalizeAssembly('dismiss', abortControllerRef.current.signal)
      setAssembly(next)
      onStateUpdate(state)
    } catch (e) {
      if (isAbortError(e)) {
        if (onShowToast) showCancelToast(onShowToast)
      } else {
        setError(e instanceof ApiError ? e.body.message : '退回失败')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleFinalize = async (decision: 'adopt' | 'override' | 'dismiss') => {
    setLoading(true)
    setError(null)
    if (abortControllerRef.current) abortControllerRef.current.abort()
    abortControllerRef.current = new AbortController()
    try {
      const { assembly: next, state } = await api.finalizeAssembly(decision, abortControllerRef.current.signal)
      setAssembly(next)
      onStateUpdate(state)
    } catch (e) {
      if (isAbortError(e)) {
        if (onShowToast) showCancelToast(onShowToast)
      } else {
        setError(e instanceof ApiError ? e.body.message : '结议失败')
      }
    } finally {
      setLoading(false)
    }
  }

  // Auto-close when assembly becomes idle
  useEffect(() => {
    if (assembly.phase === 'idle') {
      const timer = setTimeout(onClose, 500)
      return () => clearTimeout(timer)
    }
  }, [assembly.phase, onClose])

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) abortControllerRef.current.abort()
    }
  }, [])

  const renderPhase = () => {
    switch (assembly.phase) {
      case 'petition':
        return (
          <PetitionPhaseView
            petitions={assembly.petitions || []}
            onStartDebate={handleStartDebate}
            onSkipAll={handleSkipAll}
            loading={loading}
          />
        )
      case 'debate':
        return (
          <DebatePhaseView
            assembly={assembly}
            onRage={handleImperialRage}
            onAdoptSuggestion={handleAdoptSuggestion}
            onStartVote={handleStartVote}
            loading={loading}
          />
        )
      case 'vote':
        return (
          <VotePhaseView
            assembly={assembly}
            onProceedToDecree={() => setAssembly({ ...assembly, phase: 'decree' })}
            loading={loading}
          />
        )
      case 'decree':
        return (
          <DecreePhaseView
            finalDecision={assembly.final_decision ?? null}
            onFinalize={handleFinalize}
            loading={loading}
          />
        )
      default:
        return null
    }
  }

  return (
    <div className={`court-assembly-view ${assembly.phase}-phase`}>
      <div className="assembly-header">
        <h2 className="assembly-title">皇極殿朝議</h2>
        <div className="assembly-phase-indicator">
          {['petition', 'debate', 'vote', 'decree'].map(p => (
            <span
              key={p}
              className={`phase-dot ${assembly.phase === p ? 'active' : ''}`}
              title={p}
            />
          ))}
        </div>
      </div>

      {error && (
        <div className="assembly-error">
          {error}
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      <AnimatePresence mode="wait">
        <motion.div
          key={assembly.phase}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="phase-container"
        >
          {renderPhase()}
        </motion.div>
      </AnimatePresence>

      <div className="assembly-footer">
        <button className="assembly-close-btn" onClick={onClose}>
          退朝
        </button>
      </div>
    </div>
  )
}

/* ── Phase views ── */
function PetitionPhaseView({
  petitions,
  onStartDebate,
  onSkipAll,
  loading,
}: {
  petitions: AssemblyPetition[]
  onStartDebate: (topic: string) => void
  onSkipAll: () => void
  loading: boolean
}) {
  return (
    <div className="petition-view">
      <h3 className="phase-title">奏事阶段</h3>
      {petitions.length === 0 ? (
        <div className="empty-state">
          <p>今日无大臣上奏</p>
        </div>
      ) : (
        <div className="petition-list">
          {petitions.map((p, i) => (
            <motion.div
              key={i}
              className="petition-card"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.1 }}
              whileHover={{ scale: 1.02 }}
            >
              <div className="petition-meta">
                <span className="minister-name">{p.minister_name}</span>
                <span
                  className={`urgency-badge urg-${
                    p.urgency === '高' ? 'high' : p.urgency === '中' ? 'mid' : 'low'
                  }`}
                >
                  {p.urgency}
                </span>
              </div>
              <p className="petition-content">{p.content}</p>
              <button
                className="petition-btn"
                onClick={() => onStartDebate(p.content)}
                disabled={loading}
              >
                听取奏报
              </button>
            </motion.div>
          ))}
        </div>
      )}
      <div className="phase-actions">
        <button className="skip-btn" onClick={onSkipAll} disabled={loading}>
          退回全部奏章
        </button>
      </div>
    </div>
  )
}

function DebatePhaseView({
  assembly,
  onRage,
  onAdoptSuggestion,
  onStartVote,
  loading,
}: {
  assembly: CourtAssembly
  onRage: (faction: string) => void
  onAdoptSuggestion: (payload: AdoptSuggestionRequest) => Promise<void>
  onStartVote: () => void
  loading: boolean
}) {
  const supports = assembly.speeches?.filter(s => s.stance === '赞成') || []
  const opposes = assembly.speeches?.filter(s => s.stance === '反对') || []
  const neutrals = assembly.speeches?.filter(s => s.stance === '中立') || []

  return (
    <div className="debate-view">
      <h3 className="phase-title">议政阶段</h3>
      <div className="debate-topic-box">
        <div className="topic-label">议政主题</div>
        <div className="topic-text">{assembly.current_topic || assembly.topic}</div>
      </div>

      <div className="debate-columns">
        <div className="debate-col support">
          <h4>主张采纳 ({supports.length})</h4>
          {supports.map((s, i) => (
            <SpeechCard key={i} speech={s} onRage={() => onRage(s.faction)} />
          ))}
        </div>
        <div className="debate-col oppose">
          <h4>主张驳回 ({opposes.length})</h4>
          {opposes.map((s, i) => (
            <SpeechCard key={i} speech={s} onRage={() => onRage(s.faction)} />
          ))}
        </div>
      </div>

      {neutrals.length > 0 && (
        <div className="debate-neutral">
          <h4>中立观点 ({neutrals.length})</h4>
          <div className="neutral-speeches">
            {neutrals.map((s, i) => (
              <SpeechCard key={i} speech={s} onRage={() => onRage(s.faction)} />
            ))}
          </div>
        </div>
      )}

      <SuggestionCandidates
        suggestions={assembly.suggestions || []}
        onAdopt={onAdoptSuggestion}
        loading={loading}
      />

      <div className="phase-actions">
        {!assembly.rage_used && (
          <button className="rage-btn" onClick={() => onRage('all')} disabled={loading}>
            龙颜大怒
          </button>
        )}
        <button className="next-btn" onClick={onStartVote} disabled={loading}>
          进入廷推
        </button>
      </div>
    </div>
  )
}

function SuggestionCandidates({
  suggestions,
  onAdopt,
  loading,
}: {
  suggestions: PolicySuggestion[]
  onAdopt: (payload: AdoptSuggestionRequest) => Promise<void>
  loading: boolean
}) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editedText, setEditedText] = useState('')
  const [freeText, setFreeText] = useState('')

  const startEditing = (suggestion: PolicySuggestion, index: number) => {
    setEditingIndex(index)
    setEditedText(`${suggestion.title}：${suggestion.description}`.slice(0, 200))
  }

  const provenancePayload = (suggestion: PolicySuggestion, index: number) => {
    if (!suggestion.suggestion_id || !suggestion.source_version_id) return null
    return {
      suggestion_index: index,
      suggestion_id: suggestion.suggestion_id,
      source_version_id: suggestion.source_version_id,
    }
  }

  return (
    <section className="assembly-suggestions" aria-label="朝议候选方案">
      <div className="suggestion-section-heading">
        <h4>候选方案</h4>
        <span>仅供启发；提交时按当前世界重新结算</span>
      </div>

      {suggestions.length === 0 && (
        <div className="suggestion-empty">本轮没有形成候选，仍可自由输入行动。</div>
      )}

      {suggestions.map((suggestion, index) => {
        const provenance = provenancePayload(suggestion, index)
        const isEditing = editingIndex === index
        return (
          <article className="suggestion-card" key={suggestion.suggestion_id ?? index}>
            <div className="sg-head">
              <span className="sg-title">{suggestion.title}</span>
              <span className="sg-decree-type">{DECREE_LABELS[suggestion.related_decree.type]}</span>
            </div>
            <p className="sg-desc">{suggestion.description}</p>
            {suggestion.supporter_names.length > 0 && (
              <div className="sg-supporters">在朝支持：{suggestion.supporter_names.join('、')}</div>
            )}
            <details className="sg-rationale">
              <summary>查看可核验依据</summary>
              <ul>
                {(suggestion.rationale_factors || []).map((factor) => (
                  <li key={`${factor.fact_reference}:${factor.label}`} data-fact-reference={factor.fact_reference}>
                    <strong>{factor.label}：</strong>{factor.value}
                  </li>
                ))}
              </ul>
            </details>
            {!provenance && (
              <div className="suggestion-provenance-warning">旧存档候选缺少来源版本，请重新召开朝议。</div>
            )}
            <div className="suggestion-actions">
              <button
                className="sg-adopt-btn"
                disabled={loading || !provenance}
                onClick={() => provenance && void onAdopt({ mode: 'original', ...provenance })}
              >
                原样采用
              </button>
              <button
                className="sg-edit-btn"
                disabled={loading || !provenance}
                onClick={() => startEditing(suggestion, index)}
              >
                编辑采用
              </button>
            </div>
            {isEditing && provenance && (
              <div className="suggestion-editor">
                <label htmlFor={`suggestion-edit-${index}`}>编辑行动意图（政令类型仍沿用此候选）</label>
                <textarea
                  id={`suggestion-edit-${index}`}
                  value={editedText}
                  maxLength={200}
                  onChange={(event) => setEditedText(event.target.value)}
                />
                <div className="suggestion-editor-footer">
                  <span>{editedText.length}/200</span>
                  <button
                    disabled={loading || !editedText.trim()}
                    onClick={() => void onAdopt({
                      mode: 'edited',
                      ...provenance,
                      edited_text: editedText.trim(),
                    })}
                  >
                    确认编辑并采用
                  </button>
                </div>
              </div>
            )}
          </article>
        )
      })}

      <div className="suggestion-free-input">
        <label htmlFor="assembly-free-input">不采用候选，自由输入行动</label>
        <textarea
          id="assembly-free-input"
          value={freeText}
          maxLength={200}
          placeholder="写下你的行动；候选方案不是允许行动的边界"
          onChange={(event) => setFreeText(event.target.value)}
        />
        <div className="suggestion-editor-footer">
          <span>{freeText.length}/200</span>
          <button
            disabled={loading || !freeText.trim()}
            onClick={() => void onAdopt({ mode: 'free_input', free_text: freeText.trim() })}
          >
            提交自由行动
          </button>
        </div>
      </div>
    </section>
  )
}

function SpeechCard({ speech, onRage }: { speech: AssemblySpeech; onRage: () => void }) {
  return (
    <motion.div
      className="speech-card"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div className="speech-header">
        <span className="minister-name">{speech.minister_name}</span>
        <span className="faction-tag">{speech.faction}</span>
        <button className="rage-mini-btn" onClick={onRage} title="斥责">
          怒
        </button>
      </div>
      <div className="speech-content">{speech.content}</div>
    </motion.div>
  )
}

function VotePhaseView({
  assembly,
  onProceedToDecree,
  loading,
}: {
  assembly: CourtAssembly
  onProceedToDecree: () => void
  loading: boolean
}) {
  const votes = assembly.votes || []
  const supportCount = votes.filter(v => v.vote === '赞成').length
  const opposeCount = votes.filter(v => v.vote === '反对').length
  const abstainCount = votes.filter(v => v.vote === '弃权').length
  const total = votes.length || 1

  return (
    <div className="vote-view">
      <h3 className="phase-title">廷推阶段</h3>
      <div className="vote-stats">
        <div className="stat-row">
          <span className="stat-label">赞成</span>
          <div className="stat-bar">
            <div
              className="fill support"
              style={{ width: `${(supportCount / total) * 100}%` }}
            />
          </div>
          <span className="stat-count">{supportCount}</span>
        </div>
        <div className="stat-row">
          <span className="stat-label">反对</span>
          <div className="stat-bar">
            <div
              className="fill oppose"
              style={{ width: `${(opposeCount / total) * 100}%` }}
            />
          </div>
          <span className="stat-count">{opposeCount}</span>
        </div>
        <div className="stat-row">
          <span className="stat-label">弃权</span>
          <div className="stat-bar">
            <div
              className="fill abstain"
              style={{ width: `${(abstainCount / total) * 100}%` }}
            />
          </div>
          <span className="stat-count">{abstainCount}</span>
        </div>
      </div>

      <div className="vote-list">
        {votes.map((v, i) => (
          <div key={i} className="vote-item">
            <span className="voter">{v.minister_name}:</span>
            <span
              className={`vote-val ${
                v.vote === '赞成' ? 'pos' : v.vote === '反对' ? 'neg' : 'neu'
              }`}
            >
              {v.vote}
            </span>
            <span className="vote-reason">{v.reason}</span>
          </div>
        ))}
      </div>

      <div className="phase-actions">
        <button className="next-btn" onClick={onProceedToDecree} disabled={loading}>
          进入钦定
        </button>
      </div>
    </div>
  )
}

function DecreePhaseView({
  finalDecision,
  onFinalize,
  loading,
}: {
  finalDecision: string | null
  onFinalize: (decision: 'adopt' | 'override' | 'dismiss') => void
  loading: boolean
}) {
  if (finalDecision) {
    const label = finalDecision === 'adopt'
      ? '准奏'
      : finalDecision === 'override'
        ? '乾纲独断'
        : '寝议驳回'
    return (
      <div className="decree-view">
        <h3 className="phase-title">钦定阶段</h3>
        <div className="empty-state">
          <p>本次朝议已完成钦定：{label}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="decree-view">
      <h3 className="phase-title">钦定阶段</h3>
      <div className="decree-options">
        <button
          className="decree-opt-btn"
          onClick={() => onFinalize('adopt')}
          disabled={loading}
        >
          <span className="opt-title">准奏 (从众)</span>
          <span className="opt-desc">采纳廷议多数派意见，各派系关系趋于稳定</span>
        </button>
        <button
          className="decree-opt-btn"
          onClick={() => onFinalize('override')}
          disabled={loading}
        >
          <span className="opt-title">乾纲独断</span>
          <span className="opt-desc">无视廷议结果强行实施，将极大损耗威望与各派忠诚</span>
        </button>
        <button
          className="decree-opt-btn"
          onClick={() => onFinalize('dismiss')}
          disabled={loading}
        >
          <span className="opt-title">寝议驳回</span>
          <span className="opt-desc">此事再议，暂不作处分</span>
        </button>
      </div>
    </div>
  )
}
