// @vitest-environment jsdom
import type { RefObject } from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRegisterOverlay } from '../hooks/useRegisterOverlay'
import { useStore } from '../hooks/store'

interface HarnessProps {
  openerRef: RefObject<HTMLElement | null>
  onClose: () => void
}

function OverlayHarness({ openerRef, onClose }: HarnessProps) {
  useRegisterOverlay(true, {
    id: 'test_overlay',
    kind: 'menu',
    priority: 20,
    openerRef,
    closeAction: onClose,
  })
  return null
}

beforeEach(() => {
  useStore.getState().reset()
})

afterEach(() => {
  cleanup()
  useStore.getState().reset()
  vi.useRealTimers()
  document.body.replaceChildren()
})

describe('overlay registration lifecycle', () => {
  it('uses the latest ref target and close callback without re-registering', () => {
    vi.useFakeTimers()
    const firstOpener = document.createElement('button')
    const latestOpener = document.createElement('button')
    const insideOverlay = document.createElement('button')
    document.body.append(firstOpener, latestOpener, insideOverlay)
    const openerRef = { current: firstOpener } satisfies RefObject<HTMLElement | null>
    const firstClose = vi.fn()
    const latestClose = vi.fn()

    const { rerender } = render(<OverlayHarness openerRef={openerRef} onClose={firstClose} />)
    const registeredEntry = useStore.getState().overlayStack[0]
    expect(useStore.getState().overlayStack).toHaveLength(1)

    openerRef.current = latestOpener
    rerender(<OverlayHarness openerRef={openerRef} onClose={latestClose} />)
    expect(useStore.getState().overlayStack).toEqual([registeredEntry])

    insideOverlay.focus()
    act(() => {
      expect(useStore.getState().closeTopmostOverlay()).toBe(true)
    })
    expect(firstClose).not.toHaveBeenCalled()
    expect(latestClose).toHaveBeenCalledTimes(1)

    act(() => vi.runOnlyPendingTimers())
    expect(document.activeElement).toBe(latestOpener)
  })

  it('preserves opener metadata when a modal is queued and restored', () => {
    vi.useFakeTimers()
    const opener = document.createElement('button')
    const insideOverlay = document.createElement('button')
    document.body.append(opener, insideOverlay)
    const openerRef = { current: opener } satisfies RefObject<HTMLElement | null>

    useStore.getState().pushModal(
      { type: 'memorial', priority: 30, payload: [] },
      { openerRef },
    )
    useStore.getState().pushModal({
      type: 'narrative',
      priority: 95,
      payload: { narrative: 'test', delta: {} },
    })

    act(() => {
      useStore.getState().closeTopmostOverlay()
    })
    act(() => vi.runOnlyPendingTimers())
    expect(useStore.getState().currentModal?.type).toBe('memorial')
    expect(useStore.getState().overlayStack[0]?.openerRef).toBe(openerRef)

    insideOverlay.focus()
    act(() => {
      useStore.getState().closeTopmostOverlay()
    })
    act(() => vi.runOnlyPendingTimers())
    expect(document.activeElement).toBe(opener)
  })
})
