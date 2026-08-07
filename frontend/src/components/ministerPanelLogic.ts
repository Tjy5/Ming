import type { Minister } from '../types/game'

export const FACTION_ORDER = [
  '淮西勋将', '幕府文臣', '江南士绅', '龙凤政权',
  '汉政权', '吴政权', '元廷', '东南群雄',
]

export const DEFAULT_EXPANDED_FACTIONS = FACTION_ORDER.slice(0, 3)

export function filterPanelMinisters(
  ministers: Minister[] | null | undefined,
  searchTerm: string,
  showNotEntered: boolean,
): Minister[] {
  if (!Array.isArray(ministers)) return []

  return ministers.filter(m => {
    if (m.status === 'removed') return false
    if (!showNotEntered && m.status === 'not_yet_entered') return false
    if (searchTerm) {
      const q = searchTerm.toLowerCase()
      return m.name.toLowerCase().includes(q) || m.positions?.join(' ').toLowerCase().includes(q)
    }
    return true
  })
}

export function groupMinistersByFaction(ministers: Minister[]): Record<string, Minister[]> {
  return ministers.reduce<Record<string, Minister[]>>((acc, m) => {
    ;(acc[m.faction] ??= []).push(m)
    return acc
  }, {})
}

export function getDisplayFactions(grouped: Record<string, Minister[]>): string[] {
  const knownFactions = FACTION_ORDER.filter(f => grouped[f]?.length)
  const unknownFactions = Object.keys(grouped)
    .filter(f => !FACTION_ORDER.includes(f))
    .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
  return [...knownFactions, ...unknownFactions]
}

export function toggleExpandedFaction(expanded: ReadonlySet<string>, factionName: string): Set<string> {
  const next = new Set(expanded)
  if (next.has(factionName)) next.delete(factionName)
  else next.add(factionName)
  return next
}
