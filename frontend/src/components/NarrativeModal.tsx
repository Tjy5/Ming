const FIELD_LABELS: Record<string, string> = {
  treasury: '钱粮', population: '人口', military_supply: '军备',
  civil_morale: '民心', military_morale: '军心', court_prestige: '威望',
  stability: '稳定度', rebellion_risk: '叛乱度', tax_collected: '税收',
  disaster_level: '灾害', tax_rate: '税率', garrison: '驻军',
  satisfaction: '满意度',
}

function resolveLabel(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key]

  for (const field in FIELD_LABELS) {
    if (key.endsWith(`_${field}`)) {
      const prefix = key.slice(0, key.length - field.length - 1)
      return `${prefix}${FIELD_LABELS[field]}`
    }
  }
  return key
}

interface Props {
  narrative: string
  delta: Record<string, number>
  onClose: () => void
}

export default function NarrativeModal({ narrative, delta, onClose }: Props) {
  const entries = Object.entries(delta).filter(([, v]) => v !== 0)

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>圣旨已下</h3>
        <p>{narrative}</p>
        {entries.length > 0 && (
          <>
            <h3>数值变化</h3>
            <ul className="delta-list">
              {entries.map(([key, val]) => (
                <li key={key}>
                  <span>{resolveLabel(key)}</span>
                  <span className={val > 0 ? 'delta-pos' : 'delta-neg'}>
                    {val > 0 ? '+' : ''}{val}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
        <div className="modal-actions">
          <button className="modal-btn primary" onClick={onClose}>知道了</button>
        </div>
      </div>
    </div>
  )
}
