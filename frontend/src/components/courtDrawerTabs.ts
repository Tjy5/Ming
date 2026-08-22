export type CourtDrawerTab = 'faction' | 'minister' | 'assembly'

export const COURT_TABS: { id: CourtDrawerTab; label: string; shortcut?: string }[] = [
  { id: 'faction', label: '派系', shortcut: 'F2' },
  { id: 'minister', label: '大臣', shortcut: 'F3' },
  { id: 'assembly', label: '朝议', shortcut: 'F4' },
]
