import { useState } from 'react'
import type { Minister } from '../../types/game'
import { getPortraitUrl } from '../../utils/portraits'
import { FACTION_COLORS } from '../constants/factions'

interface PortraitProps {
  minister?: Minister
  name?: string
  faction?: string
  size?: number | string
  className?: string
  onClick?: () => void
}

function toSize(v: number | string | undefined): string | undefined {
  if (v === undefined) return undefined
  return typeof v === 'number' ? `${v}px` : v
}

export function Portrait({ minister, name, faction, size, className, onClick }: PortraitProps) {
  const [loadFailed, setLoadFailed] = useState(false)

  const displayName = minister?.name || name || '?'
  const displayFaction = minister?.faction || faction || '中立派'

  const [prevName, setPrevName] = useState('')
  if (displayName !== prevName) {
    setPrevName(displayName)
    setLoadFailed(false)
  }

  const sizeStyle = size ? { width: toSize(size), height: toSize(size) } : undefined

  if (loadFailed) {
    const bg = FACTION_COLORS[displayFaction] ?? '#555'
    return (
      <div
        className={`mp-avatar mp-placeholder ${className || ''}`}
        style={{ backgroundColor: bg, ...sizeStyle }}
        onClick={onClick}
      >
        {displayName.charAt(0)}
      </div>
    )
  }

  return (
    <img
      className={`mp-avatar ${className || ''}`}
      src={getPortraitUrl(displayName)}
      alt={displayName}
      style={sizeStyle}
      onError={() => setLoadFailed(true)}
      onClick={onClick}
    />
  )
}
