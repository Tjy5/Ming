import { describe, expect, it } from 'vitest'
import type { Minister } from '../types/game'
import {
  DEFAULT_EXPANDED_FACTIONS,
  FACTION_ORDER,
  filterPanelMinisters,
  getDisplayFactions,
  groupMinistersByFaction,
  toggleExpandedFaction,
} from '../components/ministerPanelLogic'

function makeMinister(index: number, overrides: Partial<Minister> = {}): Minister {
  return {
    name: `大臣${index}`,
    faction: FACTION_ORDER[index % FACTION_ORDER.length],
    personality_tags: ['谨慎'],
    abilities: { civil: 50, military: 40, diplomacy: 45 },
    status: 'active',
    loyalty: 50,
    positions: [index % 2 === 0 ? '东阁大学士' : '辽东巡抚'],
    is_eunuch: false,
    entry_year: 1627,
    entry_month: 8,
    historical_note: '测试大臣。',
    ...overrides,
  }
}

function largeRoster(): Minister[] {
  const ministers = Array.from({ length: 104 }, (_, index) => makeMinister(index))
  ministers.push(makeMinister(104, { name: '兵部检索目标', positions: ['兵部尚书'] }))
  ministers.push(makeMinister(105, { name: '已革兵部旧臣', positions: ['兵部尚书'], status: 'removed' }))
  ministers.push(makeMinister(106, { name: '未登场兵部候补', positions: ['兵部尚书'], status: 'not_yet_entered' }))
  return ministers
}

describe('MinisterPanel roster logic', () => {
  it('searches a 100+ roster by position without returning removed ministers', () => {
    const ministers = largeRoster()
    expect(ministers.length).toBeGreaterThanOrEqual(100)

    const matches = filterPanelMinisters(ministers, '兵部尚书', true).map(m => m.name)

    expect(matches).toContain('兵部检索目标')
    expect(matches).toContain('未登场兵部候补')
    expect(matches).not.toContain('已革兵部旧臣')
  })

  it('hides not-yet-entered ministers unless the panel toggle is enabled', () => {
    const ministers = largeRoster()

    expect(filterPanelMinisters(ministers, '', false).map(m => m.name)).not.toContain('未登场兵部候补')
    expect(filterPanelMinisters(ministers, '', true).map(m => m.name)).toContain('未登场兵部候补')
  })

  it('groups a large roster by faction in display order', () => {
    const grouped = groupMinistersByFaction(largeRoster())
    const displayFactions = getDisplayFactions(grouped)

    expect(displayFactions).toEqual(FACTION_ORDER)
    for (const faction of FACTION_ORDER) {
      expect(grouped[faction].length).toBeGreaterThan(0)
    }
  })

  it('tracks collapsed and expanded faction sections', () => {
    const initialExpanded = new Set(DEFAULT_EXPANDED_FACTIONS)
    expect(initialExpanded.has(FACTION_ORDER[0])).toBe(true)
    expect(initialExpanded.has(FACTION_ORDER[3])).toBe(false)

    const afterOpening = toggleExpandedFaction(initialExpanded, FACTION_ORDER[3])
    expect(afterOpening.has(FACTION_ORDER[3])).toBe(true)

    const afterClosing = toggleExpandedFaction(afterOpening, FACTION_ORDER[0])
    expect(afterClosing.has(FACTION_ORDER[0])).toBe(false)
  })
})
