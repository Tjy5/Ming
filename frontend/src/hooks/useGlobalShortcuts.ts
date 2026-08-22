import { useEffect, useLayoutEffect, useRef } from 'react'
import type { Capabilities, GameState, ModalItem } from '../types/game'
import type { HudSurface, OverlayEntry } from './store'

export interface GlobalShortcutsOptions {
  state: GameState | null
  loading: boolean
  currentModal: ModalItem | null
  hasBlockingEvent: boolean
  gameOver: { result: 'victory' | 'defeat'; message: string } | null
  advanceMonthInFlight: boolean
  decreeInFlight: boolean
  activeHudSurface: HudSurface
  capabilities: Capabilities
  overlayStack: OverlayEntry[]
  pendingMemorialsCount: number
  onAdvanceMonth: () => void
  onOpenEdictModal: () => void
  onOpenMemorials: () => void
  onToggleSurface: (surface: 'map' | 'camera' | 'faction' | 'minister' | 'assembly') => void
  onShowToast: (msg: string) => void
  onCloseTopmostOverlay: () => boolean
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tagName = target.tagName
  if (tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT') {
    return true
  }
  if (target.isContentEditable || target.closest('[contenteditable="true"]')) {
    return true
  }
  if (target.closest('.monaco-editor') || target.closest('.cm-editor')) {
    return true
  }
  return false
}

export function useGlobalShortcuts(options: GlobalShortcutsOptions) {
  const optionsRef = useRef(options)
  useLayoutEffect(() => {
    optionsRef.current = options
  })

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const opts = optionsRef.current

      // 1. Escape is handled across inputs unless composing or default prevented
      if (event.key === 'Escape') {
        if (event.isComposing || event.defaultPrevented) return
        const closed = opts.onCloseTopmostOverlay()
        if (closed) {
          event.preventDefault()
        }
        return
      }

      // 2. Universal guards for Space / E / M / F1-F4
      if (event.isComposing) return
      if (event.ctrlKey || event.altKey || event.metaKey) return
      if (event.repeat) return
      if (isEditableTarget(event.target)) return

      const key = event.key
      const code = event.code

      // Check Space: advance month
      if (key === ' ' || code === 'Space') {
        if (event.shiftKey) return
        if (opts.state?.phase === 'life_story') {
          opts.onShowToast('当前处于人生篇章阶段，请在跑团界面推进剧情')
          return
        }
        if (
          opts.loading ||
          opts.currentModal ||
          opts.hasBlockingEvent ||
          opts.gameOver ||
          opts.advanceMonthInFlight ||
          opts.decreeInFlight ||
          opts.overlayStack.length > 0
        ) {
          return
        }
        event.preventDefault()
        opts.onAdvanceMonth()
        return
      }

      // Check 'e' or 'E': Open Edict Modal
      if (key === 'e' || key === 'E' || code === 'KeyE') {
        if (event.shiftKey) return
        if (opts.state?.phase === 'life_story') {
          opts.onShowToast('当前处于人生篇章阶段，暂不可草拟全国圣旨')
          return
        }
        if (opts.currentModal || opts.gameOver || opts.loading) return
        event.preventDefault()
        opts.onOpenEdictModal()
        return
      }

      // Check 'm' or 'M': Open Memorials
      if (key === 'm' || key === 'M' || code === 'KeyM') {
        if (event.shiftKey) return
        if (opts.currentModal || opts.gameOver || opts.loading) return
        event.preventDefault()
        if (opts.pendingMemorialsCount > 0) {
          opts.onOpenMemorials()
        } else {
          opts.onShowToast('暂无待批奏折')
        }
        return
      }

      // Check F1: Toggle Map mode surface
      if (key === 'F1' || code === 'F1') {
        if (opts.currentModal || opts.gameOver) return
        event.preventDefault()
        opts.onToggleSurface('map')
        return
      }

      // Check F2: Toggle Faction surface
      if (key === 'F2' || code === 'F2') {
        if (opts.currentModal || opts.gameOver) return
        event.preventDefault()
        opts.onToggleSurface('faction')
        return
      }

      // Check F3: Toggle Minister surface
      if (key === 'F3' || code === 'F3') {
        if (opts.currentModal || opts.gameOver) return
        event.preventDefault()
        opts.onToggleSurface('minister')
        return
      }

      // Check F4: Toggle Assembly surface
      if (key === 'F4' || code === 'F4') {
        if (opts.currentModal || opts.gameOver) return
        event.preventDefault()
        if (opts.capabilities.assembly_supported) {
          opts.onToggleSurface('assembly')
        } else {
          opts.onShowToast('朝议功能尚未开启')
        }
        return
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])
}
