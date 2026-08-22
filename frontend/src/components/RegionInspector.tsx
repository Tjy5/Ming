import { useEffect, useRef } from 'react'
import type { GameEvent, GameState, Region } from '../types/game'
import { useRegisterOverlay } from '../hooks/useRegisterOverlay'

interface Props {
  region: Region
  sourceRegions: readonly Region[]
  entityRegistry?: GameState['entity_registry']
  activeEvents?: GameEvent[]
  versionId?: string | null
  onClose: () => void
  onAct: () => void
}

export default function RegionInspector({ region, sourceRegions, entityRegistry, activeEvents = [], versionId, onClose, onAct }: Props) {
  const closeButton = useRef<HTMLButtonElement | null>(null)
  const activeEntities = Object.values(entityRegistry ?? {}).filter(entity => entity.status === 'active' && entity.available)

  useEffect(() => {
    closeButton.current?.focus()
  }, [region.name])

  useRegisterOverlay(true, {
    id: 'region_inspector',
    kind: 'inspector',
    priority: 20,
    closeAction: onClose,
  })

  return (
    <aside className="region-inspector" aria-label={`${region.name}行政区检查器`}>
      <div className="region-inspector-header">
        <div>
          <p className="region-inspector-kicker">历史行政区</p>
          <h2>{region.name}</h2>
        </div>
        <button ref={closeButton} type="button" className="inspector-close" aria-label="关闭地区检查器" onClick={onClose}>×</button>
      </div>
      <div className="region-inspector-actions">
        <button type="button" className="modal-btn primary" onClick={onAct}>对该行政区施政</button>
      </div>
      <section aria-labelledby="region-members-heading">
        <h3 id="region-members-heading">所辖治理地区</h3>
        <ul className="region-inspector-list region-member-list">
          {sourceRegions.map(sourceRegion => (
            <li key={sourceRegion.name}>
              {sourceRegion.name}
              <span>稳定 {sourceRegion.stability} · 民心 {sourceRegion.civil_morale}</span>
            </li>
          ))}
        </ul>
        <p className="region-inspector-muted">下列总览由这些剧本地区汇总，施政时会同时作用于所辖地区。</p>
      </section>
      <section aria-labelledby="region-control-heading">
        <h3 id="region-control-heading">控制与风险</h3>
        <dl className="region-inspector-grid">
          <div><dt>控制状态</dt><dd>{region.control}</dd></div>
          <div><dt>稳定度</dt><dd>{region.stability}</dd></div>
          <div><dt>民心</dt><dd>{region.civil_morale}</dd></div>
          <div><dt>动乱风险</dt><dd>{region.rebellion_risk}</dd></div>
          <div><dt>灾害等级</dt><dd>{region.disaster_level}</dd></div>
          <div><dt>税率</dt><dd>{Math.round(region.tax_rate * 100)}%</dd></div>
        </dl>
      </section>
      <section aria-labelledby="region-garrison-heading">
        <h3 id="region-garrison-heading">驻军概览</h3>
        <p className="region-inspector-stat">{region.garrison.toLocaleString()} 人</p>
        <p className="region-inspector-muted">威胁：{region.threat === 'none' ? '暂无已知威胁' : region.threat}</p>
      </section>
      <section aria-labelledby="region-resource-heading">
        <h3 id="region-resource-heading">核心资源</h3>
        <p>赋税贡献：{region.tax_contribution === 'high' ? '高' : region.tax_contribution === 'medium' ? '中' : '低'}</p>
        <p>已征税额：{region.tax_collected.toLocaleString()}</p>
      </section>
      <section aria-labelledby="region-events-heading">
        <h3 id="region-events-heading">活跃事件与主体</h3>
        {activeEvents.length > 0 ? (
          <ul className="region-inspector-list">
            {activeEvents.slice(0, 4).map(event => <li key={event.script_id ?? event.name}>{event.name}<span>{event.urgency}</span></li>)}
          </ul>
        ) : <p className="region-inspector-muted">当前没有待处理事件。</p>}
        {activeEntities.length > 0 ? (
          <ul className="region-inspector-list">
            {activeEntities.slice(0, 6).map(entity => <li key={entity.entity_id}>{entity.display_name}<span>{entity.entity_type}</span></li>)}
          </ul>
        ) : <p className="region-inspector-muted">当前世界登记主体为空，可从朝议接纳接替者。</p>}
        {versionId && <p className="region-inspector-version">世界版本 {versionId.slice(0, 8)}</p>}
      </section>
    </aside>
  )
}
