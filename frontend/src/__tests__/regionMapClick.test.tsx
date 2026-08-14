// @vitest-environment jsdom
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import { act, cleanup, render, screen, fireEvent } from '@testing-library/react'
import RegionMap from '../components/RegionMap'
import { EAST_ASIA_POLITICAL_GRID } from '../data/map/eastAsiaPoliticalGrid'
import { EAST_ASIA_REFERENCE_BASEMAP } from '../data/map/eastAsiaReferenceBasemap'
import type { Region } from '../types/game'

let resizeObserverCallback: ResizeObserverCallback | null = null

class ResizeObserverMock {
  constructor(callback: ResizeObserverCallback) {
    resizeObserverCallback = callback
  }

  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  resizeObserverCallback = null
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function resizeMap(width: number, height: number) {
  const callback = resizeObserverCallback
  if (!callback) throw new Error('RegionMap did not register its ResizeObserver')
  const contentRect = {
    x: 0, y: 0, top: 0, left: 0,
    right: width, bottom: height, width, height,
    toJSON: () => ({}),
  } as DOMRectReadOnly
  act(() => callback([{ contentRect } as ResizeObserverEntry], {} as ResizeObserver))
}

function makeRegion(name: string): Region {
  return {
    name, stability: 50, garrison: 10000,
    control: '朝廷', threat: 'none', tax_contribution: 'medium',
    civil_morale: 50, rebellion_risk: 20, tax_rate: 0.5,
    tax_collected: 30, disaster_level: 10,
  }
}

describe('RegionMap administrative governance interaction', () => {
  it('directly paints current geographic units as historical polities and Yuan divisions', () => {
    const { container } = render(<RegionMap regions={[makeRegion('应天')]} />)
    expect(container.querySelectorAll('.east-asia-reference-basemap path')).toHaveLength(EAST_ASIA_REFERENCE_BASEMAP.features.length)
    expect(container.querySelector('.east-asia-reference-basemap button')).toBeNull()
    expect(container.querySelector('.east-asia-reference-basemap')?.getAttribute('aria-hidden')).toBe('true')
    expect(container.querySelectorAll('.historical-polity-label')).toHaveLength(9)
    expect(container.querySelectorAll('.east-asia-country-grid [data-country-id]')).toHaveLength(EAST_ASIA_POLITICAL_GRID.countries.length)
    expect(container.querySelectorAll('.china-historical-admin-grid [data-province-paint-id]')).toHaveLength(EAST_ASIA_POLITICAL_GRID.chinaProvinces.length)
    expect(container.querySelectorAll('[data-polity-paint-id]')).toHaveLength(10)
    expect(container.querySelectorAll('[data-admin-division-id]').length).toBeGreaterThan(20)
    expect(container.querySelectorAll('.yuan-administrative-labels text')).toHaveLength(12)
    expect(screen.getByText('察合台汗国')).toBeTruthy()
    expect(screen.getByText('高丽')).toBeTruthy()
    expect(screen.getByText('日本')).toBeTruthy()
    expect(screen.getByText('河南江北行省')).toBeTruthy()
    expect(screen.getByText('宣政院辖地')).toBeTruthy()
    const tibetanPolities = screen.getByText('吐蕃诸部')
    const xuanzheng = screen.getByText('宣政院辖地')
    expect(tibetanPolities.parentElement?.classList.contains('prominence-local')).toBe(true)
    expect(tibetanPolities.parentElement?.getAttribute('data-label-role')).toBe('local-context')
    expect(Number.parseFloat(tibetanPolities.style.fontSize)).toBeLessThan(Number.parseFloat(xuanzheng.style.fontSize))
    expect(screen.getByLabelText('地图图层图例').textContent).toContain('周边政权')
    expect(screen.getByLabelText('地图图层图例').textContent).toContain('元代政区')
    expect(screen.getByLabelText('地图图层图例').textContent).toContain('可治理行政区')
    expect(screen.getByText(/约 14 世纪中叶历史归组/)).toBeTruthy()
    expect(screen.getByText(/点击有治理数据的行政区轮廓/)).toBeTruthy()
    expect(container.querySelectorAll('[data-label-fit="fallback"]')).toHaveLength(0)
    expect(Array.from(container.querySelectorAll('[data-outline-ids]')).every((label) => Boolean(label.getAttribute('data-outline-ids')))).toBe(true)
    expect(screen.queryByText(/河北省|河南省|湖北省|广东省/)).toBeNull()
  })

  it('keeps local atmosphere assets decorative, pointer-inert, and below authoritative map layers', () => {
    const { container } = render(<RegionMap regions={[makeRegion('应天')]} />)
    const svg = container.querySelector('.geographic-map svg')
    const atmosphere = svg?.querySelector('.map-atmosphere')
    const basemap = svg?.querySelector('.east-asia-reference-basemap')
    const countryGrid = svg?.querySelector('.east-asia-country-grid')
    const administrativeGrid = svg?.querySelector('.china-historical-admin-grid')
    const coastline = svg?.querySelector('.east-asia-coastline')
    const governanceDivisions = svg?.querySelector('.yuan-governance-divisions')
    const images = atmosphere?.querySelectorAll('image')

    expect(svg?.getAttribute('preserveAspectRatio')).toBe('xMidYMid meet')
    expect(atmosphere?.getAttribute('aria-hidden')).toBe('true')
    expect(atmosphere?.getAttribute('pointer-events')).toBe('none')
    expect(images).toHaveLength(2)
    expect(Array.from(images ?? []).map((image) => image.getAttribute('href'))).toEqual([
      '/map/atmosphere/v1/paper-water-wash-v1.webp',
      '/map/atmosphere/v1/terrain-drybrush-v1.webp',
    ])
    expect(svg && atmosphere && basemap && (atmosphere.compareDocumentPosition(basemap) & Node.DOCUMENT_POSITION_FOLLOWING)).toBeTruthy()
    expect(svg && basemap && countryGrid && (basemap.compareDocumentPosition(countryGrid) & Node.DOCUMENT_POSITION_FOLLOWING)).toBeTruthy()
    expect(svg && countryGrid && administrativeGrid && (countryGrid.compareDocumentPosition(administrativeGrid) & Node.DOCUMENT_POSITION_FOLLOWING)).toBeTruthy()
    expect(svg && administrativeGrid && coastline && (administrativeGrid.compareDocumentPosition(coastline) & Node.DOCUMENT_POSITION_FOLLOWING)).toBeTruthy()
    expect(svg && coastline && governanceDivisions && (coastline.compareDocumentPosition(governanceDivisions) & Node.DOCUMENT_POSITION_FOLLOWING)).toBeTruthy()
    expect(svg?.querySelector('.map-water')).toBeTruthy()
    expect(governanceDivisions?.querySelectorAll('.map-governance-division')).toHaveLength(12)
    expect(governanceDivisions?.querySelectorAll('path').length).toBeGreaterThan(20)
  })

  it('calls onDivisionClick with the clicked administrative division', () => {
    const onClick = vi.fn()
    const regions = [makeRegion('应天'), makeRegion('集庆')]
    const { getByRole } = render(<RegionMap regions={regions} onDivisionClick={onClick} />)
    const block = getByRole('button', { name: /河南江北行省，所辖治理地区：应天/ })
    fireEvent.click(block)
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({
      division: expect.objectContaining({ name: '河南江北行省' }),
      sourceRegions: [expect.objectContaining({ name: '应天' })],
    }))
  })

  it('renders safely when onDivisionClick is omitted', () => {
    const regions = [makeRegion('应天')]
    const { container } = render(<RegionMap regions={regions} />)
    const block = container.querySelector('[data-governance-division-id="henan-jiangbei"]')
    expect(block).toBeTruthy()
    if (block) fireEvent.click(block)
    expect(true).toBe(true)
  })

  it('supports keyboard activation on a mapped administrative division', () => {
    const onClick = vi.fn()
    const { getByRole } = render(<RegionMap regions={[makeRegion('应天')]} onDivisionClick={onClick} />)
    fireEvent.keyDown(getByRole('button', { name: /河南江北行省/ }), { key: 'Enter' })
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ division: expect.objectContaining({ name: '河南江北行省' }) }))
  })

  it('supports Space activation on a mapped governance node', () => {
    const onClick = vi.fn()
    const { getByRole } = render(<RegionMap regions={[makeRegion('应天')]} onDivisionClick={onClick} />)
    fireEvent.keyDown(getByRole('button', { name: /河南江北行省/ }), { key: ' ' })
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ division: expect.objectContaining({ name: '河南江北行省' }) }))
  })

  it('renders distinct mode context, legends, and region summaries for all six views', () => {
    const region = {
      ...makeRegion('应天'),
      stability: 47,
      disaster_level: 18,
      civil_morale: 63,
      rebellion_risk: 29,
      tax_rate: 0.74,
      tax_collected: 1234,
    }
    const { container, getByRole } = render(<RegionMap regions={[region]} />)
    const expected = [
      ['标准', '治势总览', '稳定 47'],
      ['灾情', '灾情态势', '灾情 18'],
      ['民心', '民心向背', '民心 63'],
      ['动乱', '动乱风险', '风险 29'],
      ['税率', '税赋完成', '完成 74%'],
      ['赋税', '实征赋税', '实征 1,234'],
    ]

    for (const [buttonLabel, title, value] of expected) {
      fireEvent.click(getByRole('button', { name: buttonLabel }))
      expect(getByRole('heading', { name: title })).toBeTruthy()
      expect(container.querySelectorAll('.map-legend [data-legend-level]')).toHaveLength(3)
      expect(container.querySelector('[data-governance-division-id="henan-jiangbei"]')?.getAttribute('aria-label')).toContain(value)
      expect(getByRole('button', { name: buttonLabel }).getAttribute('aria-pressed')).toBe('true')
      expect(container.querySelectorAll('.map-view-controls [aria-pressed="true"]')).toHaveLength(1)
    }
  })

  it('places court navigation at the map top-left and keeps map tools in the right rail', () => {
    const { container, getByRole, getByLabelText } = render(
      <RegionMap
        regions={[makeRegion('应天')]}
        railControls={<div role="group" aria-label="朝廷抽屉控制" />}
      />,
    )
    const primaryStrip = getByRole('navigation', { name: '朝廷管理' })
    const courtControls = getByRole('group', { name: '朝廷抽屉控制' })
    const rail = getByRole('complementary', { name: '地图控制' })
    expect(primaryStrip.contains(courtControls)).toBe(true)
    expect(container.querySelector('.geographic-map')?.contains(primaryStrip)).toBe(true)
    expect(rail.contains(courtControls)).toBe(false)
    expect(Array.from(rail.children).map((child) => child.getAttribute('aria-label'))).toEqual([
      '地图模式',
      '地图镜头',
    ])

    const modeButtons = Array.from(getByRole('group', { name: '地图模式' }).querySelectorAll('button'))
    expect(modeButtons.map((button) => button.getAttribute('aria-label'))).toEqual([
      '标准', '灾情', '民心', '动乱', '税率', '赋税',
    ])
    expect(modeButtons.map((button) => button.textContent)).toEqual([
      '标准', '灾情', '民心', '动乱', '税率', '赋税',
    ])
    expect(modeButtons.every((button) => button.querySelector('.rail-button-label'))).toBe(true)
    expect(rail.querySelector('.desktop-icon')).toBeNull()
    expect(rail.querySelector('.rail-tooltip')).toBeNull()
    expect(modeButtons[0].getAttribute('aria-pressed')).toBe('true')

    const camera = getByRole('group', { name: '地图镜头' })
    expect(Array.from(camera.querySelectorAll('button')).map((button) => button.getAttribute('aria-label'))).toEqual([
      '缩小地图', '放大地图', '重置地图视图',
    ])
    expect(Array.from(camera.querySelectorAll('button')).map((button) => button.textContent)).toEqual([
      '缩小', '放大', '复位',
    ])
    expect(Array.from(rail.querySelectorAll('.rail-section-title')).map((title) => title.textContent)).toEqual([
      '地图', '镜头',
    ])
    expect(getByLabelText('当前地图缩放比例').textContent).toBe('100%')
    expect(container.querySelector('.geographic-map .map-zoom-controls')).toBeNull()
    expect(rail.contains(camera)).toBe(true)
  })

  it('zooms with controls and resets to the full East Asia view', () => {
    const { container, getByRole, getByText } = render(<RegionMap regions={[makeRegion('应天')]} />)
    const svg = container.querySelector('.geographic-map svg')
    expect(svg?.getAttribute('viewBox')).toBe('0 0 1200 650')
    expect(getByRole('button', { name: '缩小地图' }).hasAttribute('disabled')).toBe(true)

    fireEvent.click(getByRole('button', { name: '放大地图' }))
    expect(svg?.getAttribute('viewBox')).toBe('120 65 960 520')
    expect(svg?.getAttribute('data-map-zoom')).toBe('1.25')
    expect(getByText('125%')).toBeTruthy()

    fireEvent.click(getByRole('button', { name: '重置地图视图' }))
    expect(svg?.getAttribute('viewBox')).toBe('0 0 1200 650')
    expect(getByText('100%')).toBeTruthy()
  })

  it('zooms toward the pointer with the mouse wheel', () => {
    const { container } = render(<RegionMap regions={[makeRegion('应天')]} />)
    const svg = container.querySelector('.geographic-map svg') as SVGSVGElement
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 1200, bottom: 650, width: 1200, height: 650,
      toJSON: () => ({}),
    })

    fireEvent.wheel(svg, { deltaY: -100, clientX: 900, clientY: 325 })
    const [x, , width] = (svg.getAttribute('viewBox') ?? '').split(' ').map(Number)
    expect(x).toBeGreaterThan(0)
    expect(width).toBeLessThan(1200)
    expect(svg.getAttribute('data-map-zoom')).toBe('1.15')
  })

  it('matches a tall container and allows panning at the base fill zoom', () => {
    const { container, getByRole } = render(<RegionMap regions={[makeRegion('应天')]} />)
    const svg = container.querySelector('.geographic-map svg') as SVGSVGElement
    resizeMap(400, 800)

    const initialView = (svg.getAttribute('viewBox') ?? '').split(' ').map(Number)
    expect(initialView[2] / initialView[3]).toBeCloseTo(0.5, 4)
    expect(initialView[3]).toBe(650)
    expect(svg.getAttribute('data-map-zoom')).toBe('1.00')

    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 400, bottom: 800, width: 400, height: 800,
      toJSON: () => ({}),
    })
    Object.defineProperty(svg, 'setPointerCapture', { configurable: true, value: vi.fn() })
    Object.defineProperty(svg, 'hasPointerCapture', { configurable: true, value: vi.fn(() => false) })

    fireEvent.pointerDown(svg, { button: 0, pointerId: 7, clientX: 200, clientY: 400 })
    fireEvent.pointerMove(svg, { pointerId: 7, clientX: 300, clientY: 400 })
    const pannedView = (svg.getAttribute('viewBox') ?? '').split(' ').map(Number)
    expect(pannedView[0]).toBeLessThan(initialView[0])
    expect(getByRole('button', { name: '重置地图视图' }).hasAttribute('disabled')).toBe(false)

    fireEvent.click(getByRole('button', { name: '重置地图视图' }))
    expect(svg.getAttribute('viewBox')).toBe(initialView.join(' '))
  })

  it('preserves camera center and zoom when the map surface changes aspect ratio', () => {
    const { container, getByRole } = render(<RegionMap regions={[makeRegion('应天')]} />)
    const svg = container.querySelector('.geographic-map svg') as SVGSVGElement
    resizeMap(1000, 500)
    fireEvent.click(getByRole('button', { name: '放大地图' }))

    const before = (svg.getAttribute('viewBox') ?? '').split(' ').map(Number)
    const centerBefore = [before[0] + before[2] / 2, before[1] + before[3] / 2]
    resizeMap(500, 1000)
    const after = (svg.getAttribute('viewBox') ?? '').split(' ').map(Number)
    const centerAfter = [after[0] + after[2] / 2, after[1] + after[3] / 2]

    expect(svg.getAttribute('data-map-zoom')).toBe('1.25')
    expect(after[2] / after[3]).toBeCloseTo(0.5, 4)
    expect(centerAfter[0]).toBeCloseTo(centerBefore[0], 2)
    expect(centerAfter[1]).toBeCloseTo(centerBefore[1], 2)
  })

  it('exposes selected, threat, control, missing, unmapped, and duplicate states explicitly', () => {
    const threatened = { ...makeRegion('应天'), control: '沦陷' as const, threat: '元军' as const }
    const duplicate = makeRegion('集庆')
    const unmapped = makeRegion('不存在')
    const { container } = render(
      <RegionMap regions={[threatened, duplicate, unmapped]} highlightDivisionId="henan-jiangbei" />,
    )

    const selected = container.querySelector('[data-governance-division-id="henan-jiangbei"]')
    expect(selected?.classList.contains('selected')).toBe(true)
    expect(selected?.classList.contains('has-threat')).toBe(true)
    expect(selected?.getAttribute('data-control')).toBe('沦陷')
    expect(selected?.getAttribute('data-threat')).toBe('元军')
    expect(container.querySelectorAll('[data-state="missing"]')).toHaveLength(11)
    expect(container.querySelector('[data-warning-kind="unmapped"]')?.textContent).toContain('不存在')
    expect(container.querySelector('[data-warning-kind="duplicate"]')?.textContent).toContain('集庆')
  })

  it('mirrors pointer and focus hover state onto the administrative outline group', () => {
    const { container, getByRole } = render(<RegionMap regions={[makeRegion('应天')]} />)
    const button = getByRole('button', { name: /河南江北行省，所辖治理地区：应天，控制：朝廷，治势总览/ })
    const feature = container.querySelector('[data-governance-division-id="henan-jiangbei"]')

    fireEvent.mouseEnter(button)
    expect(feature?.classList.contains('hovered')).toBe(true)
    fireEvent.mouseLeave(button)
    expect(feature?.classList.contains('hovered')).toBe(false)
    fireEvent.focus(button)
    expect(feature?.classList.contains('hovered')).toBe(true)
    fireEvent.blur(button)
    expect(feature?.classList.contains('hovered')).toBe(false)
  })
})
