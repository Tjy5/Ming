import { useEffect, useState } from 'react'
import type { SaveEntry, GameState } from '../types/game'
import { api, ApiError } from '../api/client'

interface Props {
  onLoad: (state: GameState) => void
  onClose: () => void
  hasUnsaved: boolean
}

export default function SavePanel({ onLoad, onClose, hasUnsaved }: Props) {
  const [saves, setSaves] = useState<SaveEntry[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    api.listSaves()
      .then((s) => { if (!cancelled) setSaves(s) })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : '读取存档列表失败') })
    return () => { cancelled = true }
  }, [])

  async function handleLoad(id: number) {
    if (hasUnsaved && !confirm('当前进度未保存，确认读档？')) return
    try {
      const state = await api.loadSave(id)
      onLoad(state)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '读档失败')
    }
  }

  async function handleDelete(id: number) {
    if (!confirm('确认删除此存档？')) return
    try {
      await api.deleteSave(id)
      setSaves((s) => s.filter((x) => x.id !== id))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '删除失败')
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>存档列表</h3>
        {error && <p style={{ color: 'var(--red)' }}>{error}</p>}
        <div className="save-list">
          {saves.length === 0 && <p style={{ fontSize: '0.85rem', color: 'var(--text-dim)' }}>暂无存档</p>}
          {saves.map((s) => (
            <div key={s.id} className="save-item">
              <span>{s.name} ({s.game_time})</span>
              <div>
                <button onClick={() => handleLoad(s.id)}>读取</button>
                <button onClick={() => handleDelete(s.id)}>删除</button>
              </div>
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <button className="modal-btn" onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  )
}
