// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { cleanup, render, screen, fireEvent } from '@testing-library/react'
import GuideModal from '../components/GuideModal'
import { shouldAutoOpenGuide } from '../components/guideModalLogic'
import { useStore } from '../hooks/store'

describe('GuideModal', () => {
  beforeEach(() => {
    localStorage.clear()
    useStore.getState().reset()
  })
  afterEach(() => {
    cleanup()
    localStorage.clear()
    useStore.getState().reset()
  })

  it('renders nothing when closed', () => {
    render(<GuideModal open={false} onClose={() => {}} />)
    expect(screen.queryByTestId('guide-modal')).toBeNull()
  })

  it('renders sections and responds to next/close', () => {
    const onClose = () => {}
    render(<GuideModal open={true} onClose={onClose} />)
    expect(screen.getByTestId('guide-modal')).toBeTruthy()
    expect(useStore.getState().overlayStack.filter((entry) => entry.id === 'guide_modal')).toHaveLength(1)
    expect(screen.getByRole('dialog', { name: '界面指引' }).classList.contains('modal')).toBe(true)
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

  it('closes on Escape and returns focus to the opener', () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const onClose = vi.fn()
    const { unmount } = render(<GuideModal open={true} onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    unmount()
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })
})
