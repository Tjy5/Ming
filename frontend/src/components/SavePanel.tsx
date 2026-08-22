import { useEffect, useRef, useState } from 'react'
import type { SaveEntry, GameState } from '../types/game'
import { api, ApiError } from '../api/client'
import { useFocusTrap } from '../hooks/useFocusTrap'

interface Props {
  onLoad: (state: GameState, migrationNote?: string) => void
  onClose: () => void
  hasUnsaved: boolean
}

export default function SavePanel({ onLoad, onClose, hasUnsaved }: Props) {
  const [saves, setSaves] = useState<SaveEntry[]>([])
  const [error, setError] = useState('')
  const [loadingList, setLoadingList] = useState(true)
  const [pendingAction, setPendingAction] = useState<{ kind: 'load' | 'delete'; id: number } | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)

  useFocusTrap({
    active: true,
    containerRef: panelRef,
    overlayId: 'save_panel',
  })

  useEffect(() => {
    let cancelled = false
    api.listSaves()
      .then((s) => { if (!cancelled) setSaves(s) })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : '读取存档列表失败') })
      .finally(() => { if (!cancelled) setLoadingList(false) })
    return () => { cancelled = true }
  }, [])

  async function handleLoad(id: number) {
    if (pendingAction) return
    if (hasUnsaved && !confirm('当前进度未保存，确认读档？')) return
    setError('')
    setPendingAction({ kind: 'load', id })
    try {
      const res = await api.loadSave(id)
      const { migration_applied, migration_note, ...state } = res
      onLoad(state as GameState, migration_applied ? migration_note : undefined)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '读档失败')
    } finally {
      setPendingAction(null)
    }
  }

  async function handleDelete(id: number) {
    if (pendingAction) return
    if (!confirm('确认删除此存档？')) return
    setError('')
    setPendingAction({ kind: 'delete', id })
    try {
      await api.deleteSave(id)
      setSaves((s) => s.filter((x) => x.id !== id))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '删除失败')
    } finally {
      setPendingAction(null)
    }
  }

  return (
    <div className="modal-overlay" onClick={() => !pendingAction && onClose()} data-overlay-root="modal">
      <div
        ref={panelRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        data-overlay-panel="true"
        aria-labelledby="save-panel-title"
        aria-busy={loadingList || !!pendingAction}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="save-panel-title">存档列表</h3>
        {error && <p role="alert" style={{ color: 'var(--red)' }}>{error}</p>}
        <div className="save-list">
          {loadingList && <p role="status" style={{ fontSize: '0.85rem', color: 'var(--text-dim)' }}>正在检索存档…</p>}
          {!loadingList && saves.length === 0 && <p style={{ fontSize: '0.85rem', color: 'var(--text-dim)' }}>暂无存档</p>}
          {saves.map((s) => (
            <div key={s.id} className="save-item">
              <span>{s.name} ({s.game_time})</span>
              <div>
                <button type="button" disabled={!!pendingAction} onClick={() => handleLoad(s.id)}>
                  {pendingAction?.kind === 'load' && pendingAction.id === s.id ? '读取中…' : '读取'}
                </button>
                <button type="button" disabled={!!pendingAction} onClick={() => handleDelete(s.id)}>
                  {pendingAction?.kind === 'delete' && pendingAction.id === s.id ? '删除中…' : '删除'}
                </button>
              </div>
            </div>
          ))}
        </div>
        <button type="button" className="modal-btn" disabled={!!pendingAction} onClick={onClose}>关闭</button>
      </div>
    </div>
  )
}
