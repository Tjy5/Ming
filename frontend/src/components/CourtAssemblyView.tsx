import { useState } from 'react'
import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import type { GameState, Capabilities, DecreeType, CourtAssembly } from '../types/game'
import { DECREE_LABELS, DECREE_TYPES, DEBATE_TOPICS } from '../types/game'

/* ── Inline panel mode (right panel tab) ── */
interface PanelProps {
  state: GameState
  capabilities: Capabilities
  loading: boolean
  onConvene: (topic: string, decreeType: DecreeType) => void
  onAdopt: (index: number) => void
  onSilence: () => void
}

/* ── Modal mode (from modal queue) ── */
interface ModalProps {
  assembly: CourtAssembly
  onAdopt: (index: number) => void
  onSilence: () => void
  onClose: () => void
  asModal: true
}

type Props = PanelProps | ModalProps

function isModal(p: Props): p is ModalProps {
  return 'asModal' in p && p.asModal === true
}

/* ── Assembly result view (shared) ── */
function AssemblyResult({ assembly, onAdopt, onSilence, onClose }: {
  assembly: CourtAssembly
  onAdopt: (index: number) => void
  onSilence: () => void
  onClose?: () => void
}) {
  const [confirmIdx, setConfirmIdx] = useState<number | null>(null)

  return (
    <div className="assembly-result">
      <div className="assembly-topic">议题: {assembly.topic}</div>
      <div className="assembly-participants">
        {assembly.participants.map(p => (
          <div key={p.name} className="assembly-participant">
            <span className="ap-name">{p.name}</span>
            <span className="ap-faction">({p.faction})</span>
            {p.position && <span className="ap-position">{p.position}</span>}
          </div>
        ))}
      </div>

      {assembly.debate_text && (
        <div className="assembly-debate">
          <Markdown>{assembly.debate_text}</Markdown>
        </div>
      )}

      {assembly.consensus && (
        <div className="assembly-consensus">共识: {assembly.consensus}</div>
      )}

      {assembly.suggestions.length > 0 && (
        <div className="assembly-suggestions">
          <div className="as-title">政策建议</div>
          {assembly.suggestions.map((s, i) => (
            <div key={i} className="suggestion-card">
              <div className="sg-head">
                <span className="sg-title">{s.title}</span>
                {s.supporter_names.length > 0 && (
                  <span className="sg-supporters">{s.supporter_names.join('、')}附议</span>
                )}
              </div>
              <div className="sg-desc">{s.description}</div>
              {confirmIdx === i ? (
                <div className="sg-confirm">
                  <span>确认采纳此策？</span>
                  <button className="mem-btn mem-approve" onClick={() => onAdopt(i)}>确认</button>
                  <button className="mem-btn mem-defer" onClick={() => setConfirmIdx(null)}>取消</button>
                </div>
              ) : (
                <button className="sg-adopt-btn" onClick={() => setConfirmIdx(i)}>采纳此策</button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="assembly-actions">
        {!assembly.silenced && (
          <button className="mem-btn mem-reject" onClick={onSilence}>喝止群臣</button>
        )}
        {onClose && <button className="modal-btn primary" onClick={onClose}>退朝</button>}
      </div>
    </div>
  )
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
          <h3 className="assembly-header">朝会议政</h3>
          <AssemblyResult
            assembly={props.assembly}
            onAdopt={props.onAdopt}
            onSilence={props.onSilence}
            onClose={props.onClose}
          />
        </motion.div>
      </div>
    )
  }

  return <AssemblyPanel {...props} />
}

/* ── Panel mode (right sidebar tab) ── */
function AssemblyPanel({ state, capabilities, loading, onConvene, onAdopt, onSilence }: PanelProps) {
  const [selectedType, setSelectedType] = useState<DecreeType>(DECREE_TYPES[0])
  const [lastAssembly, setLastAssembly] = useState<CourtAssembly | null>(null)

  const topics = DEBATE_TOPICS[selectedType] ?? []
  const canConvene = capabilities.assembly_supported && !loading

  function handleConvene(topic: string) {
    onConvene(topic, selectedType)
  }

  // Sync last_assembly from state if available (via API response)
  const stateAssembly = (state as unknown as { last_assembly?: CourtAssembly }).last_assembly
  const displayAssembly = stateAssembly ?? lastAssembly

  return (
    <div className="assembly-panel">
      <div className="assembly-convene-section">
        <div className="as-title">召集朝会</div>
        <select
          className="assembly-select"
          value={selectedType}
          onChange={e => setSelectedType(e.target.value as DecreeType)}
        >
          {DECREE_TYPES.map(dt => (
            <option key={dt} value={dt}>{DECREE_LABELS[dt]}</option>
          ))}
        </select>
        <div className="assembly-topic-list">
          {topics.map(t => (
            <button
              key={t.topic}
              className="assembly-topic-btn"
              disabled={!canConvene}
              onClick={() => handleConvene(t.topic)}
            >
              {loading ? '召集中...' : t.topic}
            </button>
          ))}
        </div>
      </div>

      {displayAssembly && (
        <AssemblyResult
          assembly={displayAssembly}
          onAdopt={onAdopt}
          onSilence={onSilence}
        />
      )}
    </div>
  )
}
