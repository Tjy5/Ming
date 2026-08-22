import type { Region } from '../types/game'
import type { GovernanceDivisionStatus } from '../data/map/geography'

export type ViewMode = 'standard' | 'disaster' | 'morale' | 'rebellion' | 'tax_rate' | 'tax_collected'
export type MapLevel = 'high' | 'mid' | 'low'

export interface MapLegendEntry {
  readonly level: MapLevel
  readonly label: string
  readonly range: string
}

export interface MapModePresentation {
  readonly label: string
  readonly title: string
  readonly description: string
  readonly legend: readonly MapLegendEntry[]
}

export const VIEW_MODES: readonly ViewMode[] = [
  'standard', 'disaster', 'morale', 'rebellion', 'tax_rate', 'tax_collected',
]

export const MAP_MODE_PRESENTATIONS: Readonly<Record<ViewMode, MapModePresentation>> = {
  standard: {
    label: '标准',
    title: '治势总览',
    description: '以稳定度判断各地治理承压程度',
    legend: [
      { level: 'high', label: '稳固', range: '61–100' },
      { level: 'mid', label: '承压', range: '30–60' },
      { level: 'low', label: '危急', range: '0–29' },
    ],
  },
  disaster: {
    label: '灾情',
    title: '灾情态势',
    description: '灾害越轻，区域恢复能力越强',
    legend: [
      { level: 'high', label: '轻微', range: '0–19' },
      { level: 'mid', label: '严峻', range: '20–50' },
      { level: 'low', label: '重灾', range: '51–100' },
    ],
  },
  morale: {
    label: '民心',
    title: '民心向背',
    description: '显示百姓对当前治理的支持程度',
    legend: [
      { level: 'high', label: '归附', range: '61–100' },
      { level: 'mid', label: '观望', range: '30–60' },
      { level: 'low', label: '离散', range: '0–29' },
    ],
  },
  rebellion: {
    label: '动乱',
    title: '动乱风险',
    description: '风险越低，地方秩序越可控',
    legend: [
      { level: 'high', label: '安定', range: '0–19' },
      { level: 'mid', label: '躁动', range: '20–50' },
      { level: 'low', label: '将乱', range: '51–100' },
    ],
  },
  tax_rate: {
    label: '税率',
    title: '税赋完成',
    description: '比较各地本期税赋完成比例',
    legend: [
      { level: 'high', label: '充足', range: '81–100%' },
      { level: 'mid', label: '尚可', range: '50–80%' },
      { level: 'low', label: '不足', range: '0–49%' },
    ],
  },
  tax_collected: {
    label: '赋税',
    title: '实征赋税',
    description: '按本期实征额在各地区中的位次着色',
    legend: [
      { level: 'high', label: '前列', range: '前 2' },
      { level: 'mid', label: '中位', range: '第 3–6' },
      { level: 'low', label: '后列', range: '其余/未征' },
    ],
  },
}

const TAX_LABELS = { low: '低', medium: '中', high: '高' } as const
const THREAT_LABELS: Record<string, string> = { none: '无', 元军: '元军', 汉军: '汉军', 吴军: '吴军', 民变: '民变', 土司: '土司', 海盗: '海盗' }

function threeLevel(value: number, low: number, high: number): MapLevel {
  if (value > high) return 'high'
  if (value >= low) return 'mid'
  return 'low'
}

export function isDivisionInCrisis(status: GovernanceDivisionStatus): boolean {
  if (!status.region) return false
  return status.region.rebellion_risk > 50 || status.region.disaster_level > 50
}

export function getDivisionMainThreat(status: GovernanceDivisionStatus): string {
  const hit = status.sourceRegions.find((region) => region.threat !== 'none')
  return hit ? hit.threat : 'none'
}

export function levelColor(level: MapLevel): string {
  if (level === 'high') return 'var(--green)'
  if (level === 'mid') return 'var(--yellow)'
  return 'var(--red)'
}

export function getColorLevel(view: ViewMode, r: Region): MapLevel {
  switch (view) {
    case 'standard': return threeLevel(r.stability, 30, 60)
    case 'disaster':
      if (r.disaster_level < 20) return 'high'
      if (r.disaster_level <= 50) return 'mid'
      return 'low'
    case 'morale': return threeLevel(r.civil_morale, 30, 60)
    case 'rebellion':
      if (r.rebellion_risk < 20) return 'high'
      if (r.rebellion_risk <= 50) return 'mid'
      return 'low'
    case 'tax_rate':
      if (r.tax_rate > 0.8) return 'high'
      if (r.tax_rate >= 0.5) return 'mid'
      return 'low'
    default: return 'mid'
  }
}

export function getTaxCollectedRanks(regions: Region[]): Map<string, MapLevel> {
  const result = new Map<string, MapLevel>()
  if (regions.every(r => r.tax_collected === 0)) {
    regions.forEach(r => result.set(r.name, 'low'))
    return result
  }
  const sorted = [...regions].sort((a, b) => {
    if (b.tax_collected !== a.tax_collected) return b.tax_collected - a.tax_collected
    if (b.stability !== a.stability) return b.stability - a.stability
    return a.name.localeCompare(b.name)
  })
  sorted.forEach((r, i) => {
    if (i < 2) result.set(r.name, 'high')
    else if (i < 6) result.set(r.name, 'mid')
    else result.set(r.name, 'low')
  })
  return result
}

export function getBarPercent(view: ViewMode, r: Region, regions: Region[]): number {
  let v: number
  switch (view) {
    case 'standard': v = r.stability; break
    case 'disaster': v = 100 - r.disaster_level; break
    case 'morale': v = r.civil_morale; break
    case 'rebellion': v = 100 - r.rebellion_risk; break
    case 'tax_rate': v = r.tax_rate * 100; break
    case 'tax_collected': {
      const max = Math.max(...regions.map(x => x.tax_collected), 1)
      v = (r.tax_collected / max) * 100
      break
    }
  }
  return Math.max(0, Math.min(100, v))
}

export function getTooltipText(view: ViewMode, r: Region): string {
  switch (view) {
    case 'standard':
      return `稳定度: ${r.stability} | 驻军: ${r.garrison.toLocaleString()} | 控制: ${r.control}`
    case 'disaster':
      return `灾害等级: ${r.disaster_level} | 威胁: ${THREAT_LABELS[r.threat] ?? r.threat} | 稳定度: ${r.stability}`
    case 'morale':
      return `民心: ${r.civil_morale} | 稳定度: ${r.stability} | 控制: ${r.control}`
    case 'rebellion':
      return `动乱风险: ${r.rebellion_risk} | 驻军: ${r.garrison.toLocaleString()} | 威胁: ${THREAT_LABELS[r.threat] ?? r.threat}`
    case 'tax_rate':
      return `完成率: ${Math.round(r.tax_rate * 100)}% | 税贡: ${TAX_LABELS[r.tax_contribution]} | 稳定度: ${r.stability}`
    case 'tax_collected':
      return `实征: ${r.tax_collected} | 税贡: ${TAX_LABELS[r.tax_contribution]} | 完成率: ${Math.round(r.tax_rate * 100)}%`
  }
}

export function getModeValueLabel(view: ViewMode, r: Region): string {
  switch (view) {
    case 'standard': return `稳定 ${Math.round(r.stability)}`
    case 'disaster': return `灾情 ${Math.round(r.disaster_level)}`
    case 'morale': return `民心 ${Math.round(r.civil_morale)}`
    case 'rebellion': return `风险 ${Math.round(r.rebellion_risk)}`
    case 'tax_rate': return `完成 ${Math.round(r.tax_rate * 100)}%`
    case 'tax_collected': return `实征 ${r.tax_collected.toLocaleString()}`
  }
}
