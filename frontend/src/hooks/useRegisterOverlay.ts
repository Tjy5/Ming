import { useEffect, useRef } from 'react'
import { useStore, type OverlayEntry } from './store'

export function useRegisterOverlay(
  isOpen: boolean,
  {
    id,
    kind,
    priority,
    openerId,
    openerRef,
    closeAction,
  }: Omit<OverlayEntry, 'closeAction'> & { closeAction: () => void },
) {
  const registerOverlay = useStore((s) => s.registerOverlay)
  const unregisterOverlay = useStore((s) => s.unregisterOverlay)
  const closeActionRef = useRef(closeAction)

  useEffect(() => {
    closeActionRef.current = closeAction
  }, [closeAction])

  useEffect(() => {
    if (!isOpen) {
      unregisterOverlay(id)
      return
    }

    registerOverlay({
      id,
      kind,
      priority,
      openerId,
      openerRef,
      closeAction: () => closeActionRef.current(),
    })

    return () => {
      unregisterOverlay(id)
    }
  }, [isOpen, id, kind, priority, openerId, openerRef, registerOverlay, unregisterOverlay])
}
