import { useState, useEffect, useRef, useCallback } from 'react'
import type { GameState } from '../types/game'
import { api } from '../api/client'
import HistoricalCalendar from './HistoricalCalendar'
import DesktopIcon from './DesktopIcon'
import { useRegisterOverlay } from '../hooks/useRegisterOverlay'
import { restoreOpenerFocus } from '../hooks/store'

interface Props {
  state: GameState
  prevState: GameState | null
  pendingMemorials?: number
  onMemorialClick?: () => void
  blockingEvents?: number
  onBlockingEventClick?: () => void
  onSave: () => void
  onShowSaves: () => void
  onNewGame: () => void
  onOpenAiSettings: () => void
  onOpenChat: () => void
  onOpenTrpg?: () => void
  onOpenContinuity?: () => void
  onOpenGuide?: () => void
}

interface ResourceDef {
  key: keyof GameState
  label: string
  max: number
  unit: string
}

interface ResourceGroup {
  id: 'fiscal' | 'livelihood' | 'military' | 'prestige'
  name: string
  resources: ResourceDef[]
}

const RESOURCE_GROUPS: ResourceGroup[] = [
  {
    id: 'fiscal',
    name: '财政',
    resources: [
      { key: 'national_treasury', label: '国库', unit: '万两', max: 1000 },
      { key: 'imperial_treasury', label: '内帑', unit: '万两', max: 500 },
    ],
  },
  {
    id: 'livelihood',
    name: '民生',
    resources: [
      { key: 'grain', label: '粮草', unit: '万石', max: 5000 },
      { key: 'population', label: '人口', unit: '万人', max: 20000 },
      { key: 'civil_morale', label: '民心', unit: '%', max: 100 },
    ],
  },
  {
    id: 'military',
    name: '军事',
    resources: [
      { key: 'military_strength', label: '兵力', unit: '万人', max: 500 },
      { key: 'military_morale', label: '军心', unit: '%', max: 100 },
    ],
  },
  {
    id: 'prestige',
    name: '威望',
    resources: [
      { key: 'court_prestige', label: '威望', unit: '%', max: 100 },
    ],
  },
]

const ALL_RESOURCES = RESOURCE_GROUPS.flatMap((g) => g.resources)

const RESOURCE_INFO: Record<string, string> = {
  national_treasury: '国库：税收与赏赐之和，减军费与工程开销。',
  imperial_treasury: '内帑：君主私库，用于特殊赏赐与应急。',
  grain: '粮草：军需与赈灾之本，灾年尤为关键。',
  population: '人口：治下编户，影响赋税与兵源。',
  military_strength: '兵力：常备军，守土与征伐之基。',
  civil_morale: '民心：治下安宁度，过低则生民变。',
  military_morale: '军心：将士效命度，关乎战力。',
  court_prestige: '威望：君主号令之重，影响外交与朝堂。',
}

function barColor(val: number, max: number): string {
  const pct = val / max
  if (pct > 0.6) return 'var(--green)'
  if (pct > 0.3) return 'var(--yellow)'
  return 'var(--red)'
}

export default function ResourceBar({
  state,
  prevState,
  pendingMemorials = 0,
  onMemorialClick,
  blockingEvents = 0,
  onBlockingEventClick,
  onSave,
  onShowSaves,
  onNewGame,
  onOpenAiSettings,
  onOpenChat,
  onOpenTrpg,
  onOpenContinuity,
  onOpenGuide,
}: Props) {
  const [fallbackEnabled, setFallbackEnabled] = useState(false)
  const [detailsKey, setDetailsKey] = useState<keyof GameState | null>(null)
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false)
  const detailTrigger = useRef<HTMLButtonElement | null>(null)
  const settingsTriggerRef = useRef<HTMLButtonElement | null>(null)
  const menuPopoverRef = useRef<HTMLDivElement | null>(null)
  const detailsPopoverRef = useRef<HTMLDivElement | null>(null)
  const [detailsPosition, setDetailsPosition] = useState({ top: 60, left: 14 })
  const [settingsPosition, setSettingsPosition] = useState({ top: 60, left: 14 })

  const updateDetailsPosition = useCallback(() => {
    const trigger = detailTrigger.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const width = Math.min(360, window.innerWidth - 28)
    const left = Math.max(14, Math.min(rect.left, window.innerWidth - width - 14))
    const top = Math.min(rect.bottom + 8, window.innerHeight - 440)
    setDetailsPosition({ top: Math.max(14, top), left })
  }, [])

  const updateSettingsPosition = useCallback(() => {
    const trigger = settingsTriggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const width = 220
    const left = Math.max(14, Math.min(rect.right - width, window.innerWidth - width - 14))
    const top = Math.min(rect.bottom + 8, window.innerHeight - 300)
    setSettingsPosition({ top: Math.max(14, top), left })
  }, [])

  useEffect(() => {
    api.getSettings()
      .then((s) => setFallbackEnabled(s.rule_parse_fallback))
      .catch((cause) => {
        console.warn('[resource-bar] failed to load settings', cause)
      })
  }, [])

  const toggleFallback = async () => {
    try {
      const res = await api.updateSettings({ rule_parse_fallback: !fallbackEnabled })
      setFallbackEnabled(res.rule_parse_fallback)
    } catch (cause) {
      console.warn('[resource-bar] failed to update fallback setting', cause)
    }
  }

  // Register resource details overlay
  useRegisterOverlay(!!detailsKey, {
    id: 'resource_details',
    kind: 'inspector',
    priority: 20,
    openerRef: detailTrigger,
    closeAction: () => setDetailsKey(null),
  })

  // Register palace settings menu overlay
  useRegisterOverlay(settingsMenuOpen, {
    id: 'palace_settings_menu',
    kind: 'menu',
    priority: 20,
    openerRef: settingsTriggerRef,
    closeAction: () => setSettingsMenuOpen(false),
  })

  // Outside click & window events
  useEffect(() => {
    if (!detailsKey && !settingsMenuOpen) return

    const handlePointerDown = (e: MouseEvent) => {
      const target = e.target as Node | null
      if (detailsKey && detailsPopoverRef.current && !detailsPopoverRef.current.contains(target) && !detailTrigger.current?.contains(target)) {
        setDetailsKey(null)
      }
      if (settingsMenuOpen && menuPopoverRef.current && !menuPopoverRef.current.contains(target) && !settingsTriggerRef.current?.contains(target)) {
        setSettingsMenuOpen(false)
      }
    }

    const handleResize = () => {
      if (detailsKey) updateDetailsPosition()
      if (settingsMenuOpen) updateSettingsPosition()
    }

    window.addEventListener('pointerdown', handlePointerDown)
    window.addEventListener('resize', handleResize)
    window.addEventListener('scroll', handleResize, true)

    return () => {
      window.removeEventListener('pointerdown', handlePointerDown)
      window.removeEventListener('resize', handleResize)
      window.removeEventListener('scroll', handleResize, true)
    }
  }, [detailsKey, settingsMenuOpen, updateDetailsPosition, updateSettingsPosition])

  const selectedResource = ALL_RESOURCES.find((r) => r.key === detailsKey)
  const selectedValue = selectedResource ? Number(state[selectedResource.key]) : 0
  const selectedPrevious = selectedResource ? Number(prevState?.[selectedResource.key] ?? selectedValue) : selectedValue
  const selectedDiff = selectedValue - selectedPrevious

  return (
    <header className="resource-bar" role="banner">
      <HistoricalCalendar {...state.time} />

      <div className="resource-groups-wrapper" role="region" aria-label="国家实力指标">
        {RESOURCE_GROUPS.map((group) => (
          <div key={group.id} className={`resource-group group-${group.id}`} data-group-id={group.id}>
            <span className="resource-group-tag" aria-hidden="true">{group.name}</span>
            <div className="resource-group-items">
              {group.resources.map(({ key, label, max, unit }) => {
                const val = Number(state[key] ?? 0)
                const prev = prevState ? Number(prevState[key] ?? val) : val
                const diff = val - prev
                const cls = diff > 0 ? 'up' : diff < 0 ? 'down' : ''
                const trendText = diff > 0 ? `↑${diff}` : diff < 0 ? `↓${Math.abs(diff)}` : '持平'
                const percentText = Math.round((val / max) * 100)
                const desc = RESOURCE_INFO[key] || label
                const itemTitle = `${label}：${desc}\n当前：${val}${unit} (${percentText}%) | 近期：${trendText}\n基础档位：0–${max}${unit} | 按 Enter 或点击查看详细构成与来源`

                return (
                  <button
                    type="button"
                    className="resource-item"
                    key={key}
                    title={itemTitle}
                    aria-label={`${label} ${val}${unit}，按 Enter 查看详情`}
                    aria-expanded={detailsKey === key}
                    onClick={(event) => {
                      detailTrigger.current = event.currentTarget
                      setDetailsKey(detailsKey === key ? null : key)
                      if (detailsKey !== key) window.setTimeout(updateDetailsPosition, 0)
                    }}
                  >
                    <div className="resource-label">
                      <span>{label}</span>
                      <span className={`val ${cls}`}>{val}<small>{unit}</small></span>
                    </div>
                    <div className="progress-track" aria-hidden="true">
                      <div
                        className="progress-fill"
                        style={{ width: `${Math.min(100, Math.max(0, (val / max) * 100))}%`, backgroundColor: barColor(val, max) }}
                      />
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {selectedResource && (
        <div
          ref={detailsPopoverRef}
          className="resource-details-popover"
          role="dialog"
          aria-label={`${selectedResource.label}详情`}
          style={{ top: detailsPosition.top, left: detailsPosition.left }}
        >
          <div className="resource-details-header">
            <strong>{selectedResource.label}</strong>
            <button
              type="button"
              className="resource-details-close"
              aria-label="关闭资源详情"
              onClick={() => {
                setDetailsKey(null)
                restoreOpenerFocus(detailTrigger)
              }}
            >
              ×
            </button>
          </div>
          <p className="resource-details-current">
            当前 {selectedValue}{selectedResource.unit}{' '}
            <span className={selectedDiff > 0 ? 'up' : selectedDiff < 0 ? 'down' : ''}>
              {selectedDiff > 0 ? `↑${selectedDiff}` : selectedDiff < 0 ? `↓${Math.abs(selectedDiff)}` : '持平'}
            </span>
          </p>
          <dl>
            <div><dt>基础档位</dt><dd>0–{selectedResource.max}{selectedResource.unit}</dd></div>
            <div><dt>有效档位</dt><dd>{Math.round((selectedValue / selectedResource.max) * 100)}%</dd></div>
            <div><dt>近期变化来源</dt><dd>{selectedDiff === 0 ? '暂无已结算变化' : '上一项已结算行动'}</dd></div>
            <div><dt>生效修正</dt><dd>以当前世界投影为准</dd></div>
            <div><dt>未来收支</dt><dd>仅显示已落库承诺，预测不计入余额</dd></div>
          </dl>
          <p className="resource-details-note">{RESOURCE_INFO[selectedResource.key] || selectedResource.label}</p>
        </div>
      )}

      {(pendingMemorials > 0 || blockingEvents > 0) && (
        <div className="ck3-alerts-bar" aria-label="紧急待办提醒">
          {pendingMemorials > 0 && (
            <button
              type="button"
              className="ck3-alert-badge"
              onClick={onMemorialClick}
              title={`有 ${pendingMemorials} 份奏折待批阅 (快捷键: M)`}
              aria-label={`奏折待批 ${pendingMemorials} 份`}
            >
              <span>📜 奏折待批</span>
              <span className="ck3-alert-badge-count">{pendingMemorials}</span>
            </button>
          )}
          {blockingEvents > 0 && (
            <button
              type="button"
              className="ck3-alert-badge"
              onClick={onBlockingEventClick}
              title={`有 ${blockingEvents} 项关键剧情亟待裁断`}
              aria-label={`关键剧情待决 ${blockingEvents} 项`}
            >
              <span>🚨 剧情决断</span>
              <span className="ck3-alert-badge-count">{blockingEvents}</span>
            </button>
          )}
        </div>
      )}

      <nav className="toolbar-actions" aria-label="全局工具">
        <button
          type="button"
          className="toolbar-btn"
          onClick={onOpenChat}
          title="进入对话模式"
          aria-label="对话"
        >
          <DesktopIcon name="chat" />
          <span>对话</span>
        </button>

        {onOpenTrpg && (
          <button
            type="button"
            className="toolbar-btn"
            onClick={onOpenTrpg}
            title="进入跑团模式"
            aria-label="跑团"
          >
            <DesktopIcon name="dice" />
            <span>跑团</span>
          </button>
        )}

        <button
          ref={settingsTriggerRef}
          id="palace-settings-trigger"
          type="button"
          className={`toolbar-btn${settingsMenuOpen ? ' active-toggle' : ''}`}
          onClick={() => {
            setSettingsMenuOpen((prev) => !prev)
            if (!settingsMenuOpen) window.setTimeout(updateSettingsPosition, 0)
          }}
          title="打开宫禁设置菜单"
          aria-label="宫禁设置"
          aria-haspopup="menu"
          aria-expanded={settingsMenuOpen}
          aria-controls="palace-settings-menu"
        >
          <DesktopIcon name="settings" />
          <span>设置</span>
        </button>
      </nav>

      {settingsMenuOpen && (
        <div
          ref={menuPopoverRef}
          id="palace-settings-menu"
          className="palace-settings-menu-popover"
          role="menu"
          aria-label="宫禁设置菜单"
          style={{ top: settingsPosition.top, left: settingsPosition.left }}
        >
          <div className="palace-menu-header">
            <span>宫禁理政设置</span>
            <button
              type="button"
              className="palace-menu-close"
              aria-label="关闭设置菜单"
              onClick={() => {
                setSettingsMenuOpen(false)
                restoreOpenerFocus(settingsTriggerRef)
              }}
            >
              ×
            </button>
          </div>

          <div className="palace-menu-items">
            <button
              type="button"
              role="menuitem"
              className="palace-menu-item"
              onClick={() => {
                setSettingsMenuOpen(false)
                onSave()
              }}
            >
              <DesktopIcon name="save" />
              <span>存档</span>
            </button>

            <button
              type="button"
              role="menuitem"
              className="palace-menu-item"
              onClick={() => {
                setSettingsMenuOpen(false)
                onShowSaves()
              }}
            >
              <DesktopIcon name="folder" />
              <span>读档</span>
            </button>

            <button
              type="button"
              role="menuitem"
              className={`palace-menu-item${fallbackEnabled ? ' is-active' : ''}`}
              onClick={toggleFallback}
              title={fallbackEnabled ? '本地规则兜底已开启' : '本地规则兜底已关闭'}
            >
              <DesktopIcon name="shield" />
              <span>{fallbackEnabled ? '本地兜底：开' : '本地兜底：关'}</span>
            </button>

            {onOpenContinuity && (
              <button
                type="button"
                role="menuitem"
                className="palace-menu-item"
                onClick={() => {
                  setSettingsMenuOpen(false)
                  onOpenContinuity()
                }}
                title="查看世界分支、书签和活动"
              >
                <DesktopIcon name="branch" />
                <span>连续性分支</span>
              </button>
            )}

            <button
              type="button"
              role="menuitem"
              className="palace-menu-item"
              onClick={() => {
                setSettingsMenuOpen(false)
                onOpenAiSettings()
              }}
              title="打开 AI 设置"
            >
              <DesktopIcon name="settings" />
              <span>AI 设置</span>
            </button>

            {onOpenGuide && (
              <button
                type="button"
                role="menuitem"
                className="palace-menu-item"
                onClick={() => {
                  setSettingsMenuOpen(false)
                  onOpenGuide()
                }}
                title="查看界面操作指引"
              >
                <DesktopIcon name="book" />
                <span>指引</span>
              </button>
            )}

            <hr className="palace-menu-divider" />

            <button
              type="button"
              role="menuitem"
              className="palace-menu-item danger"
              onClick={() => {
                setSettingsMenuOpen(false)
                onNewGame()
              }}
              title="开始新局"
            >
              <DesktopIcon name="refresh" />
              <span>开始新局</span>
            </button>
          </div>
        </div>
      )}
    </header>
  )
}
