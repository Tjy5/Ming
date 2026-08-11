// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { api } from '../api/client'
import { useStore } from '../hooks/store'
import type { CourtAssembly, DecreeResponse, GameState } from '../types/game'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function gameState(nationalTreasury: number): GameState {
  return {
    time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    phase: 'governance',
    chapter: 'warlord',
    chapter_turns: 0,
    national_treasury: nationalTreasury,
    imperial_treasury: 8,
    grain: 420,
    population: 1600,
    military_strength: 18,
    civil_morale: 62,
    military_morale: 68,
    court_prestige: 62,
    factions: [],
    regions: [],
    ministers: [],
    active_events: [],
    history_log: [],
    decree_count: 1,
    decrees_this_month: {},
    event_cooldowns: {},
    resolved_script_ids: [],
  }
}

function assembly(): CourtAssembly {
  return {
    phase: 'debate',
    topic: '是否加征赋税',
    current_topic: '是否加征赋税',
    decree_type: 'tax_increase',
    participants: [],
    petitions: [],
    speeches: [],
    votes: [],
    suggestions: [{
      title: '朝议方案1',
      description: '提交后依据当前世界重新结算。',
      related_decree: { type: 'tax_increase' },
      supporter_names: [],
      suggestion_id: 'suggestion-1',
      source_game_id: 'game-1',
      source_branch_id: 'branch-1',
      source_version_id: 'version-1',
      rationale_factors: [],
    }],
    debate_text: '朝议已完成。',
    consensus: 'support',
    silenced: false,
    rage_used: false,
    silenced_factions: [],
    final_decision: null,
  }
}

function adoptionResponse(): DecreeResponse {
  return {
    state: gameState(37),
    delta: { national_treasury: 15 },
    attribution: {},
    narrative: '新税制已按本次结算生效。',
    newly_triggered_events: [],
    game_time: gameState(37).time,
    game_over: null,
    minister_reactions: [],
    turn_summary: {
      year: 1356,
      month: 3,
      era_name: '至正',
      era_year: 16,
      commentary: '本次结算后国库存银为三十七万两。',
      major_events: ['新税制落地'],
      indicator_trends: [{ name: 'national_treasury', before: 22, after: 37 }],
      faction_changes: [],
      region_changes: [],
      minister_changes: [],
      pending_memorials_count: 0,
    },
    memorial_triggers: [],
    narrative_status: 'validated',
    narrative_path_id: 'structured_action',
    settlement_id: 'settlement-adoption-1',
    context_version_id: 'version-adoption-2',
    suggestion_adoption_mode: 'original',
    suggestion_id: 'suggestion-1',
    suggestion_source_version_id: 'version-1',
    suggestion_evaluation_version_id: 'version-adoption-2',
    suggestion_was_stale: true,
    suggestion_rationale_factors: [],
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.setItem('ming_guide_seen', '1')
  useStore.getState().reset()
})

afterEach(() => {
  cleanup()
  useStore.getState().reset()
})

describe('App adoption result integrity', () => {
  it('renders committed state and narrative metadata from the same adoption response', async () => {
    const initialState = gameState(22)
    const response = adoptionResponse()
    vi.spyOn(api, 'getCapabilities').mockResolvedValue({
      debate_supported: true,
      assembly_supported: true,
      memorial_enabled: true,
    })
    vi.spyOn(api, 'getSettings').mockResolvedValue({ rule_parse_fallback: false })
    const adoptSuggestionMock = vi.spyOn(api, 'adoptSuggestion').mockResolvedValue(response)
    useStore.setState({
      state: initialState,
      capabilities: { debate_supported: true, assembly_supported: true, memorial_enabled: true },
      currentModal: { type: 'assembly', priority: 20, payload: assembly() },
    })

    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '原样采用' }))
    })

    await waitFor(() => expect(adoptSuggestionMock).toHaveBeenCalledTimes(1))
    const treasuryItem = screen.getAllByText('国库')
      .map((node) => node.closest('.resource-item'))
      .find((node) => node !== null)
    expect(treasuryItem?.textContent).toContain('37万两')
    expect(treasuryItem?.textContent).not.toContain('22万两')

    const narrative = screen.getByText(response.narrative)
    expect(screen.getByText(/本次结算后国库存银为三十七万两/)).toBeTruthy()
    expect(screen.getByText(/国库: 22 → 37/)).toBeTruthy()
    const modal = narrative.closest('.narrative-modal')
    expect(modal?.getAttribute('data-settlement-id')).toBe(response.settlement_id)
    expect(modal?.getAttribute('data-context-version-id')).toBe(response.context_version_id)
  })
})
