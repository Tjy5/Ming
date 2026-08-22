import { useRef, useState } from 'react'
import type { DecreeType, StructuredDecree, PersonnelAction } from '../types/game'
import { GOVERNANCE_REGION_NAMES, DIPLOMACY_TARGETS } from '../types/game'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { useRegisterOverlay } from '../hooks/useRegisterOverlay'

interface Props {
  type: DecreeType
  onConfirm: (decree: StructuredDecree) => void
  onCancel: () => void
}

export default function TargetDialog({ type, onConfirm, onCancel }: Props) {
  const [personName, setPersonName] = useState('')
  const [subAction, setSubAction] = useState<PersonnelAction>('appoint')
  const panelRef = useRef<HTMLDivElement | null>(null)
  const targets = type === 'disaster_relief'
    ? GOVERNANCE_REGION_NAMES
    : type === 'diplomacy'
      ? DIPLOMACY_TARGETS
      : null
  const isOpen = !!targets || type === 'personnel'

  useRegisterOverlay(isOpen, {
    id: 'target_dialog',
    kind: 'nested_modal',
    priority: 40,
    closeAction: onCancel,
  })

  useFocusTrap({
    active: isOpen,
    containerRef: panelRef,
    overlayId: 'target_dialog',
  })

  if (targets) {
    const title = type === 'disaster_relief' ? '赈灾 — 选择目标区域' : '外交 — 选择目标'
    return (
      <div className="modal-overlay" onClick={onCancel} data-overlay-root="modal">
        <div
          ref={panelRef}
          className="modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="target-dialog-title"
          data-overlay-panel="true"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 id="target-dialog-title">{title}</h3>
          <div className="target-list">
            {targets.map((name) => (
              <button type="button" key={name} className="target-option" onClick={() => onConfirm({ type, target: name })}>
                {name}
              </button>
            ))}
          </div>
          <div className="modal-actions">
            <button type="button" className="modal-btn" onClick={onCancel}>取消</button>
          </div>
        </div>
      </div>
    )
  }

  if (type === 'personnel') {
    return (
      <div className="modal-overlay" onClick={onCancel} data-overlay-root="modal">
        <div
          ref={panelRef}
          className="modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="target-dialog-title"
          data-overlay-panel="true"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 id="target-dialog-title">任免 — 指定人物</h3>
          <div className="personnel-form">
            <select aria-label="任免方式" value={subAction} onChange={(e) => setSubAction(e.target.value as PersonnelAction)}>
              <option value="appoint">任命</option>
              <option value="dismiss">罢免</option>
            </select>
            <input
              aria-label="人物名称"
              placeholder="输入人物名称"
              value={personName}
              onChange={(e) => setPersonName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && personName.trim() && onConfirm({ type, target: personName.trim(), sub_action: subAction })}
            />
          </div>
          <div className="modal-actions">
            <button type="button" className="modal-btn" onClick={onCancel}>取消</button>
            <button
              type="button"
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
