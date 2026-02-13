import type { StructuredDecree } from '../types/game'
import { DECREE_LABELS } from '../types/game'

interface Props {
  decrees: StructuredDecree[]
  onConfirm: () => void
  onCancel: () => void
}

export default function MultiConfirm({ decrees, onConfirm, onCancel }: Props) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>确认执行多道政令</h3>
        <p>将依次执行以下政令（每道推进1个月）：</p>
        <ol className="confirm-list">
          {decrees.map((d, i) => (
            <li key={i}>
              {DECREE_LABELS[d.type]}
              {d.target ? ` → ${d.target}` : ''}
            </li>
          ))}
        </ol>
        <p className="confirm-note">共推进 {decrees.length} 个月</p>
        <div className="modal-actions">
          <button className="modal-btn" onClick={onCancel}>取消</button>
          <button className="modal-btn primary" onClick={onConfirm}>确认下旨</button>
        </div>
      </div>
    </div>
  )
}
