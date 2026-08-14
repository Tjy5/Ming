// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import RegionInspector from '../components/RegionInspector'
import type { GameEvent, Region } from '../types/game'

const region: Region = {
  name: '河南江北行省', stability: 70, garrison: 1000, control: '朝廷', threat: 'none',
  tax_contribution: 'high', civil_morale: 60, rebellion_risk: 10, tax_rate: 0.5,
  tax_collected: 100, disaster_level: 0,
}

const event: GameEvent = {
  name: '河工告急', description: '堤防需要修缮', urgency: '高', triggered_year: 1356,
  triggered_month: 3, rich_description: '', choices: [], is_scripted: false,
  is_blocking: false, script_id: null,
}

describe('RegionInspector', () => {
  it('renders live event and entity projections for the selected region', () => {
    render(
      <RegionInspector
        region={region}
        sourceRegions={[{ ...region, name: '应天' }, { ...region, name: '两淮', stability: 64 }]}
        activeEvents={[event]}
        entityRegistry={{ person: {
          entity_id: 'person', display_name: '临时代理', entity_type: 'person', status: 'active', available: true,
          source: { kind: 'system', reference: 'test', summary: 'test' }, permissions: [], relationships: [], knowledge_boundaries: [],
          roles: [], identity_summary: '代理', controlled_faction_id: null, location_entity_id: null, freedom_status: 'free',
        } as never }}
        onClose={vi.fn()}
        onAct={vi.fn()}
      />,
    )
    expect(screen.getByText('河工告急')).toBeTruthy()
    expect(screen.getByText('临时代理')).toBeTruthy()
    expect(screen.getByText('历史行政区')).toBeTruthy()
    expect(screen.getByText('应天')).toBeTruthy()
    expect(screen.getByText('两淮')).toBeTruthy()
    expect(screen.getByRole('button', { name: '对该行政区施政' })).toBeTruthy()
  })
})
