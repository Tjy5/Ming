import { useRef } from 'react'
import type { StructuredDecree } from '../types/game'
import { DECREE_LABELS } from '../types/game'
import { useFocusTrap } from '../hooks/useFocusTrap'

interface Props {
  decrees: StructuredDecree[]
  onConfirm: () => void
  onCancel: () => void
}

export default function MultiConfirm({ decrees, onConfirm, onCancel }: Props) {
  const panelRef = useRef<HTMLDivElement | null>(null)

  useFocusTrap({
    active: true,
    containerRef: panelRef,
    overlayId: 'multi_confirm_modal',
  })

  return (
    <div className="modal-overlay" onClick={onCancel} data-overlay-root="modal">
      <div
        ref={panelRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        data-overlay-panel="true"
        aria-labelledby="multi-confirm-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="multi-confirm-title">确认执行多道政令</h3>
        <p>将依次执行以下政令：</p>
        <ol className="confirm-list">
          {decrees.map((d, i) => (
            <li key={i}>
              {DECREE_LABELS[d.type]}
              {d.target ? ` → ${d.target}` : ''}
            </li>
          ))}
        </ol>
        <p className="confirm-note">共 {decrees.length} 道政令</p>
        <div className="modal-actions">
          <button className="modal-btn" onClick={onCancel}>取消</button>
          <button className="modal-btn primary" onClick={onConfirm}>确认下令</button>
        </div>
      </div>
    </div>
  )
}
