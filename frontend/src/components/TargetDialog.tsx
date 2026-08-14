import { useState } from 'react'
import type { DecreeType, StructuredDecree, PersonnelAction } from '../types/game'
import { GOVERNANCE_REGION_NAMES, DIPLOMACY_TARGETS } from '../types/game'

interface Props {
  type: DecreeType
  onConfirm: (decree: StructuredDecree) => void
  onCancel: () => void
}

export default function TargetDialog({ type, onConfirm, onCancel }: Props) {
  const [personName, setPersonName] = useState('')
  const [subAction, setSubAction] = useState<PersonnelAction>('appoint')

  if (type === 'disaster_relief') {
    return (
      <div className="modal-overlay" onClick={onCancel}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <h3>赈灾 — 选择目标区域</h3>
          <div className="target-list">
            {GOVERNANCE_REGION_NAMES.map((name) => (
              <button key={name} className="target-option" onClick={() => onConfirm({ type, target: name })}>
                {name}
              </button>
            ))}
          </div>
          <div className="modal-actions">
            <button className="modal-btn" onClick={onCancel}>取消</button>
          </div>
        </div>
      </div>
    )
  }

  if (type === 'diplomacy') {
    return (
      <div className="modal-overlay" onClick={onCancel}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <h3>外交 — 选择目标</h3>
          <div className="target-list">
            {DIPLOMACY_TARGETS.map((name) => (
              <button key={name} className="target-option" onClick={() => onConfirm({ type, target: name })}>
                {name}
              </button>
            ))}
          </div>
          <div className="modal-actions">
            <button className="modal-btn" onClick={onCancel}>取消</button>
          </div>
        </div>
      </div>
    )
  }

  if (type === 'personnel') {
    return (
      <div className="modal-overlay" onClick={onCancel}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <h3>任免 — 指定人物</h3>
          <div className="personnel-form">
            <select value={subAction} onChange={(e) => setSubAction(e.target.value as PersonnelAction)}>
              <option value="appoint">任命</option>
              <option value="dismiss">罢免</option>
            </select>
            <input
              placeholder="输入人物名称"
              value={personName}
              onChange={(e) => setPersonName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && personName.trim() && onConfirm({ type, target: personName.trim(), sub_action: subAction })}
            />
          </div>
          <div className="modal-actions">
            <button className="modal-btn" onClick={onCancel}>取消</button>
            <button
              className="modal-btn primary"
              disabled={!personName.trim()}
              onClick={() => onConfirm({ type, target: personName.trim(), sub_action: subAction })}
            >
              确认
            </button>
          </div>
        </div>
      </div>
    )
  }

  return null
}
