import { useEffect } from 'react'
import type { Capabilities, DecreeResponse, GameState, Minister, MinisterReaction } from '../types/game'
import FactionPanel from './FactionPanel'
import MinisterPanel from './MinisterPanel'
import CourtAssemblyView from './CourtAssemblyView'
import MissionPanel from './MissionPanel'
import DesktopIcon, { type DesktopIconName } from './DesktopIcon'

export type CourtDrawerTab = 'faction' | 'minister' | 'assembly'

const COURT_TABS: { id: CourtDrawerTab; label: string; icon: DesktopIconName }[] = [
  { id: 'faction', label: '派系', icon: 'branch' },
  { id: 'minister', label: '大臣', icon: 'users' },
  { id: 'assembly', label: '朝议', icon: 'archive' },
]

interface Props {
  isOpen: boolean
  activeTab: CourtDrawerTab
  onTabChange: (tab: CourtDrawerTab) => void
  onToggle: () => void
  onClose: () => void
  state: GameState
  capabilities: Capabilities
  lastReactions: MinisterReaction[]
  onMinisterClick: (minister: Minister) => void
  onShowOfficialRank: () => void
  onStateUpdate: (state: GameState) => void
  onAdoptionResult: (response: DecreeResponse) => void
  onShowToast: (msg: string) => void
}

interface CourtDrawerHandlesProps {
  isOpen: boolean
  activeTab: CourtDrawerTab
  onTabChange: (tab: CourtDrawerTab) => void
}

export function CourtDrawerHandles({ isOpen, activeTab, onTabChange }: CourtDrawerHandlesProps) {
  return (
    <div className="court-drawer-handles" role="group" aria-label="朝廷抽屉控制">
      {COURT_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`rail-icon-button drawer-tab-handle${isOpen && activeTab === tab.id ? ' active' : ''}`}
          onClick={() => onTabChange(tab.id)}
          title={`打开${tab.label}面板`}
          aria-label={tab.label}
          aria-expanded={isOpen && activeTab === tab.id}
        >
          <DesktopIcon name={tab.icon} size={21} />
          <span className="rail-tooltip" aria-hidden="true">{tab.label}</span>
        </button>
      ))}
    </div>
  )
}

export default function CourtDrawer({
  isOpen,
  activeTab,
  onTabChange,
  onClose,
  state,
  capabilities,
  lastReactions,
  onMinisterClick,
  onShowOfficialRank,
  onStateUpdate,
  onAdoptionResult,
  onShowToast,
}: Props) {
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  const handleTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, tabId: CourtDrawerTab) => {
    const currentIndex = COURT_TABS.findIndex((item) => item.id === tabId)
    const direction = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    const nextIndex =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? COURT_TABS.length - 1
          : direction
            ? (currentIndex + direction + COURT_TABS.length) % COURT_TABS.length
            : null
    if (nextIndex === null) return

    event.preventDefault()
    const nextTab = COURT_TABS[nextIndex]
    onTabChange(nextTab.id)
    window.setTimeout(() => document.getElementById(`court-tab-${nextTab.id}`)?.focus(), 0)
  }

  return (
    <>
      {/* 展开后的抽屉及遮罩 */}
      {isOpen && (
        <>
          <div className="court-drawer-backdrop" onClick={onClose} aria-hidden="true" />
          <aside className="court-drawer-container" role="dialog" aria-labelledby="court-drawer-title" aria-modal="true">
            <header className="court-drawer-header">
              <div className="court-drawer-header-title" id="court-drawer-title">
                <DesktopIcon name="users" />
                <span>朝廷理政 · {COURT_TABS.find((t) => t.id === activeTab)?.label}</span>
              </div>
              <button
                type="button"
                className="court-drawer-close"
                onClick={onClose}
                aria-label="关闭朝廷抽屉"
                title="关闭 (ESC)"
              >
                ×
              </button>
            </header>

            <nav className="court-drawer-tabs" role="tablist" aria-label="朝廷管理标签">
              {COURT_TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`court-tab-${tab.id}`}
                  className={`court-drawer-tab-btn${activeTab === tab.id ? ' active' : ''}`}
                  aria-selected={activeTab === tab.id}
                  onClick={() => onTabChange(tab.id)}
                  onKeyDown={(e) => handleTabKeyDown(e, tab.id)}
                >
                  {tab.label}
                </button>
              ))}
              <button
                type="button"
                className="court-drawer-tab-btn unavailable"
                role="tab"
                aria-selected={false}
                disabled
                title="阶层数据尚未接入当前世界"
                aria-label="阶层，尚未接入"
              >
                阶层
              </button>
              <button
                type="button"
                className="court-drawer-tab-btn unavailable"
                role="tab"
                aria-selected={false}
                disabled
                title="军队数据尚未接入当前世界"
                aria-label="军队，尚未接入"
              >
                军队
              </button>
            </nav>

            <div className="court-drawer-body">
              <div className="court-drawer-tools">
                <button type="button" onClick={onShowOfficialRank} title="查看并任免官职">
                  <DesktopIcon name="archive" />
                  <span>官职任免</span>
                </button>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>阶层与军队演化中</span>
              </div>

              <MissionPanel ministers={state.ministers} />

              {activeTab === 'faction' && <FactionPanel factions={state.factions} />}

              {activeTab === 'minister' && (
                <MinisterPanel
                  ministers={state.ministers}
                  reactions={lastReactions}
                  onMinisterClick={onMinisterClick}
                  onEmptyAction={() => onTabChange('assembly')}
                />
              )}

              {activeTab === 'assembly' && (
                <CourtAssemblyView
                  state={state}
                  capabilities={capabilities}
                  loading={false}
                  onStateUpdate={onStateUpdate}
                  onAdoptionResult={onAdoptionResult}
                  onShowToast={onShowToast}
                />
              )}
            </div>
          </aside>
        </>
      )}
    </>
  )
}
