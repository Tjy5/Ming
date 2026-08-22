// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import ResourceBar from '../components/ResourceBar'
import type { GameState } from '../types/game'

afterEach(cleanup)

function makeState(): GameState {
  return {
    time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    national_treasury: 500, imperial_treasury: 100, grain: 2000, population: 8000,
    military_strength: 200, civil_morale: 60, military_morale: 60, court_prestige: 55,
    ministers: [], factions: [], regions: [], active_events: [],
  } as unknown as GameState
}

describe('ResourceBar hover info', () => {
  it('shows resource explanation in title', () => {
    render(
      <ResourceBar
        state={makeState()}
        prevState={null}
        onSave={() => {}}
        onShowSaves={() => {}}
        onNewGame={() => {}}
        onOpenAiSettings={() => {}}
        onOpenChat={() => {}}
      />
    )
    const item = screen.getByTitle(/国库：税收与赏赐之和/)
    expect(item).toBeTruthy()
  })

  it('renders guide button in settings menu when onOpenGuide provided', () => {
    render(
      <ResourceBar
        state={makeState()}
        prevState={null}
        onSave={() => {}}
        onShowSaves={() => {}}
        onNewGame={() => {}}
        onOpenAiSettings={() => {}}
        onOpenChat={() => {}}
        onOpenGuide={() => {}}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: '宫禁设置' }))
    expect(screen.getByText('指引')).toBeTruthy()
  })
})
