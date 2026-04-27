import { describe, expect, it } from 'vitest'
import { collectMissionCompletions } from '../hooks/useAdvanceMonth'
import type { GameState, Minister } from '../types/game'

function minister(overrides: Partial<Minister>): Minister {
  return {
    name: '徐光启',
    faction: '东林党',
    personality_tags: [],
    abilities: { civil: 80, military: 40, diplomacy: 60 },
    status: 'active',
    loyalty: 80,
    positions: ['礼部尚书'],
    is_eunuch: false,
    entry_year: 1627,
    entry_month: 8,
    historical_note: '',
    ...overrides,
  }
}

function state(ministers: Minister[]): GameState {
  return {
    time: { year: 1628, month: 1, era_name: '崇祯', era_year: 1 },
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
          name: '研制火炮',
          progress_months: 1,
          total_months: 2,
          cost: 5,
          effects: {},
        },
      }),
    ])
    const after = state([minister({ status: 'active', current_mission: null })])

    expect(collectMissionCompletions(before, after)).toEqual([
      { ministerName: '徐光启', missionName: '研制火炮' },
    ])
  })

  it('does not report incomplete or cancelled missions as completions', () => {
    const before = state([
      minister({
        status: 'on_mission',
        current_mission: {
          name: '研制火炮',
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
          name: '研制火炮',
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
