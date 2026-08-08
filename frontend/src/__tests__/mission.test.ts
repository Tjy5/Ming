import { describe, expect, it } from 'vitest'
import { collectMissionCompletions } from '../hooks/useAdvanceMonth'
import type { GameState, Minister } from '../types/game'

function minister(overrides: Partial<Minister>): Minister {
  return {
    name: '李善长',
    faction: '幕府文臣',
    personality_tags: [],
    abilities: { civil: 80, military: 40, diplomacy: 60, administration: 70, knowledge: 60, politics: 75 },
    status: 'active',
    loyalty: 80,
    corruption: 10,
    ambition: 30,
    influence: 30,
    positions: ['左丞相'],
    is_eunuch: false,
    entry_year: 1356,
    entry_month: 8,
    historical_note: '',
    ...overrides,
  }
}

function state(ministers: Minister[]): GameState {
  return {
    time: { year: 1356, month: 1, era_name: '至正', era_year: 16 },
    phase: 'governance',
    chapter: 'warlord',
    chapter_turns: 0,
    national_treasury: 20,
    imperial_treasury: 10,
    grain: 500,
    population: 15000,
    military_strength: 40,
    civil_morale: 60,
    military_morale: 70,
    court_prestige: 75,
    factions: [],
    regions: [],
    ministers,
    active_events: [],
    history_log: [],
    decree_count: 0,
    decrees_this_month: {},
    event_cooldowns: {},
    resolved_script_ids: [],
  }
}

describe('mission completion detection', () => {
  it('reports mission completion when a minister returns active', () => {
    const before = state([
      minister({
        status: 'on_mission',
        current_mission: {
          name: '督修两淮屯田',
          progress_months: 1,
          total_months: 2,
          cost: 5,
          effects: {},
        },
      }),
    ])
    const after = state([minister({ status: 'active', current_mission: null })])

    expect(collectMissionCompletions(before, after)).toEqual([
      { ministerName: '李善长', missionName: '督修两淮屯田' },
    ])
  })

  it('does not report incomplete or cancelled missions as completions', () => {
    const before = state([
      minister({
        status: 'on_mission',
        current_mission: {
          name: '督修两淮屯田',
          progress_months: 1,
          total_months: 2,
          cost: 5,
          effects: {},
        },
      }),
    ])
    const stillOnMission = state([
      minister({
        status: 'on_mission',
        current_mission: {
          name: '督修两淮屯田',
          progress_months: 2,
          total_months: 2,
          cost: 5,
          effects: {},
        },
      }),
    ])

    expect(collectMissionCompletions(before, stillOnMission)).toEqual([])
  })
})
