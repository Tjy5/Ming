import type { DecreeType } from '../types/game'

export type DecreeCategory = 'domestic' | 'military' | 'diplomacy' | 'other'
export type DecreeCategoryTab = '内政' | '军事' | '外交' | '其他'

export const DECREE_CATEGORY_MAP: Record<DecreeType, DecreeCategory> = {
  tax_increase: 'domestic',
  tax_decrease: 'domestic',
  disaster_relief: 'domestic',
  harsh_punishment: 'domestic',
  recruit_troops: 'military',
  disband_troops: 'military',
  diplomacy: 'diplomacy',
  personnel: 'other',
}

export const CATEGORY_TABS: DecreeCategoryTab[] = ['内政', '军事', '外交', '其他']

export const TAB_TO_CATEGORY: Record<DecreeCategoryTab, DecreeCategory> = {
  内政: 'domestic',
  军事: 'military',
  外交: 'diplomacy',
  其他: 'other',
}

export const CATEGORY_DECREES: Record<DecreeCategoryTab, DecreeType[]> = {
  内政: ['tax_increase', 'tax_decrease', 'disaster_relief', 'harsh_punishment'],
  军事: ['recruit_troops', 'disband_troops'],
  外交: ['diplomacy'],
  其他: ['personnel'],
}
