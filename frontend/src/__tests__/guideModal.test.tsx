// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import GuideModal, { shouldAutoOpenGuide } from '../components/GuideModal'

describe('GuideModal', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  it('renders nothing when closed', () => {
    render(<GuideModal open={false} onClose={() => {}} />)
    expect(screen.queryByTestId('guide-modal')).toBeNull()
  })

  it('renders sections and responds to next/close', () => {
    const onClose = () => {}
    render(<GuideModal open={true} onClose={onClose} />)
    expect(screen.getByTestId('guide-modal')).toBeTruthy()
    expect(screen.getByText('顶部数据栏')).toBeTruthy()
    fireEvent.click(screen.getByText('下一步'))
    expect(screen.getByText('天下地图')).toBeTruthy()
    // 标记已看
    expect(localStorage.getItem('ming_guide_seen')).toBe('1')
  })

  it('shouldAutoOpenGuide true when not seen', () => {
    expect(shouldAutoOpenGuide()).toBe(true)
    localStorage.setItem('ming_guide_seen', '1')
    expect(shouldAutoOpenGuide()).toBe(false)
  })
})
