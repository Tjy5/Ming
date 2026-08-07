import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'

import type { AdminPosition } from '../../stores/adminStore'
import type { Minister } from '../../types/game'
import { useAdminStore } from '../../stores/adminStore'

interface EditorState {
  mode: 'create' | 'edit'
  originalName?: string
  value: Minister
}

const STATUS_OPTIONS: Minister['status'][] = ['active', 'idle', 'removed', 'not_yet_entered', 'on_mission']

function emptyMinister(): Minister {
  return {
    name: '',
    faction: '中立派',
    personality_tags: [],
    abilities: {
      civil: 50,
      military: 50,
      diplomacy: 50,
    },
    status: 'idle',
    loyalty: 50,
    positions: [],
    is_eunuch: false,
    entry_year: 1356,
    entry_month: 8,
    historical_note: '',
    current_mission: null,
  }
}

function toInt(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : fallback
}

function validateMinisterDraft(
  minister: Minister,
  positions: AdminPosition[],
  originalName?: string,
): string | null {
  const tags = minister.personality_tags ?? []
  const isNobleMinister = tags.includes('勋贵') || minister.faction === '勋贵集团'
  const isHanlin = tags.includes('翰林')
  const isMilitary = tags.includes('武将')
  const selfNames = new Set([minister.name.trim(), originalName ?? ''].filter(Boolean))
  const positionMap = new Map(positions.map((item) => [item.name, item]))

  for (const positionName of minister.positions) {
    const info = positionMap.get(positionName)
    if (!info) return `未知官职：${positionName}`

    const isEunuchRole = info.category === 'EUNUCH'
    if (Boolean(minister.is_eunuch) !== isEunuchRole) {
      return isEunuchRole
        ? `${positionName} 仅允许太监担任`
        : `${positionName} 不允许太监担任`
    }

    if (isNobleMinister && info.category !== 'NOBLE') {
      return `勋贵身份仅可担任勋戚官职，当前官职不合法：${positionName}`
    }
    if (!isNobleMinister && info.category === 'NOBLE') {
      return `${positionName} 仅允许勋贵身份担任`
    }

    if (positionName.includes('大学士') && !isHanlin) {
      return `${positionName} 需要具备“翰林”标签`
    }
    if (positionName.includes('巡抚') && isMilitary) {
      return `“武将”标签不可担任巡抚职位（${positionName}）`
    }

    if (info.unique) {
      const conflicts = info.holders.filter((holder) => !selfNames.has(holder))
      if (conflicts.length > 0) {
        return `${positionName} 为唯一官职，当前持有者：${conflicts.join('、')}`
      }
    }
  }

  return null
}

export default function MinisterManager() {
  const {
    ministers,
    positions,
    searchQuery,
    setSearchQuery,
    createMinister,
    updateMinister,
    deleteMinister,
  } = useAdminStore()

  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [factionFilter, setFactionFilter] = useState<string>('all')
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [tagsInput, setTagsInput] = useState('')

  const factions = useMemo(() => {
    const list = new Set(ministers.map((item) => item.faction))
    return Array.from(list).sort((a, b) => a.localeCompare(b))
  }, [ministers])

  const filtered = useMemo(() => {
    return ministers.filter((minister) => {
      if (searchQuery && !minister.name.includes(searchQuery.trim())) return false
      if (statusFilter !== 'all' && minister.status !== statusFilter) return false
      if (factionFilter !== 'all' && minister.faction !== factionFilter) return false
      return true
    })
  }, [ministers, searchQuery, statusFilter, factionFilter])

  const openCreate = () => {
    const value = emptyMinister()
    setTagsInput('')
    setActionError(null)
    setEditor({ mode: 'create', value })
  }

  const openEdit = (minister: Minister) => {
    setTagsInput(minister.personality_tags.join('、'))
    setActionError(null)
    setEditor({
      mode: 'edit',
      originalName: minister.name,
      value: JSON.parse(JSON.stringify(minister)) as Minister,
    })
  }

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!editor) return

    const normalized = {
      ...editor.value,
      positions: Array.from(new Set(editor.value.positions)),
      personality_tags: tagsInput
        .split(/[、,\s]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    }
    const validationError = validateMinisterDraft(normalized, positions, editor.originalName)
    if (validationError) {
      setActionError(validationError)
      return
    }

    setSubmitting(true)
    setActionError(null)
    try {
      if (editor.mode === 'create') {
        await createMinister(normalized)
      } else {
        await updateMinister(editor.originalName ?? normalized.name, normalized)
      }
      setEditor(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '保存大臣失败')
    } finally {
      setSubmitting(false)
    }
  }

  const onDelete = async (name: string) => {
    if (!window.confirm(`确认删除大臣 ${name}？`)) return
    setActionError(null)
    try {
      await deleteMinister(name)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '删除大臣失败')
    }
  }

  return (
    <div className="admin-card">
      <div className="admin-toolbar">
        <input
          className="admin-input"
          placeholder="按姓名搜索"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
        <select
          className="admin-select"
          value={factionFilter}
          onChange={(event) => setFactionFilter(event.target.value)}
        >
          <option value="all">全部派系</option>
          {factions.map((faction) => (
            <option key={faction} value={faction}>{faction}</option>
          ))}
        </select>
        <select
          className="admin-select"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
        >
          <option value="all">全部状态</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>{status}</option>
          ))}
        </select>
        <button className="admin-button" onClick={openCreate}>新增大臣</button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>姓名</th>
            <th>派系</th>
            <th>官职</th>
            <th>状态</th>
            <th>忠诚</th>
            <th>能力</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((minister) => (
            <tr key={minister.name}>
              <td>{minister.name}</td>
              <td>{minister.faction}</td>
              <td>{minister.positions.join('、') || '-'}</td>
              <td>{minister.status}</td>
              <td>{minister.loyalty}</td>
              <td>{minister.abilities.civil}/{minister.abilities.military}/{minister.abilities.diplomacy}</td>
              <td className="admin-actions">
                <button className="admin-button small" onClick={() => openEdit(minister)}>编辑</button>
                <button className="admin-button small danger" onClick={() => void onDelete(minister.name)}>删除</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {actionError && <div className="admin-error">{actionError}</div>}

      {editor && (
        <div className="admin-modal-overlay" onClick={() => setEditor(null)}>
          <div className="admin-modal" onClick={(event) => event.stopPropagation()}>
            <h3>{editor.mode === 'create' ? '新增大臣' : `编辑大臣：${editor.originalName}`}</h3>
            <form className="admin-form" onSubmit={onSubmit}>
              <label>
                姓名
                <input
                  className="admin-input"
                  value={editor.value.name}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, name: event.target.value },
                  })}
                  required
                />
              </label>
              <label>
                派系
                <input
                  className="admin-input"
                  value={editor.value.faction}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, faction: event.target.value },
                  })}
                  required
                />
              </label>
              <label>
                状态
                <select
                  className="admin-select"
                  value={editor.value.status}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, status: event.target.value as Minister['status'] },
                  })}
                >
                  {STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>{status}</option>
                  ))}
                </select>
              </label>
              <label>
                忠诚
                <input
                  className="admin-input"
                  type="number"
                  min={0}
                  max={100}
                  value={editor.value.loyalty}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, loyalty: toInt(event.target.value, editor.value.loyalty) },
                  })}
                />
              </label>
              <label>
                标签（用 `、` 或逗号分隔）
                <input
                  className="admin-input"
                  value={tagsInput}
                  onChange={(event) => setTagsInput(event.target.value)}
                />
              </label>
              <label>
                官职（可多选）
                <select
                  className="admin-select"
                  multiple
                  size={8}
                  value={editor.value.positions}
                  onChange={(event) => {
                    const next = Array.from(event.target.selectedOptions).map((option) => option.value)
                    setEditor({ ...editor, value: { ...editor.value, positions: next } })
                  }}
                >
                  {positions.map((position) => (
                    <option key={position.name} value={position.name}>
                      {position.name} [{position.category}]
                    </option>
                  ))}
                </select>
              </label>
              <label>
                文治
                <input
                  className="admin-input"
                  type="number"
                  min={0}
                  max={100}
                  value={editor.value.abilities.civil}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: {
                      ...editor.value,
                      abilities: {
                        ...editor.value.abilities,
                        civil: toInt(event.target.value, editor.value.abilities.civil),
                      },
                    },
                  })}
                />
              </label>
              <label>
                武略
                <input
                  className="admin-input"
                  type="number"
                  min={0}
                  max={100}
                  value={editor.value.abilities.military}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: {
                      ...editor.value,
                      abilities: {
                        ...editor.value.abilities,
                        military: toInt(event.target.value, editor.value.abilities.military),
                      },
                    },
                  })}
                />
              </label>
              <label>
                外交
                <input
                  className="admin-input"
                  type="number"
                  min={0}
                  max={100}
                  value={editor.value.abilities.diplomacy}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: {
                      ...editor.value,
                      abilities: {
                        ...editor.value.abilities,
                        diplomacy: toInt(event.target.value, editor.value.abilities.diplomacy),
                      },
                    },
                  })}
                />
              </label>
              <label>
                是否太监
                <input
                  type="checkbox"
                  checked={editor.value.is_eunuch}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, is_eunuch: event.target.checked },
                  })}
                />
              </label>
              <label>
                入朝年份
                <input
                  className="admin-input"
                  type="number"
                  value={editor.value.entry_year}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, entry_year: toInt(event.target.value, editor.value.entry_year) },
                  })}
                />
              </label>
              <label>
                入朝月份
                <input
                  className="admin-input"
                  type="number"
                  min={1}
                  max={12}
                  value={editor.value.entry_month}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, entry_month: toInt(event.target.value, editor.value.entry_month) },
                  })}
                />
              </label>
              <label>
                历史注释
                <textarea
                  className="admin-textarea"
                  value={editor.value.historical_note}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, historical_note: event.target.value },
                  })}
                  rows={4}
                />
              </label>
              {actionError && <div className="admin-error">{actionError}</div>}
              <div className="admin-form-actions">
                <button className="admin-button" type="button" onClick={() => setEditor(null)}>取消</button>
                <button className="admin-button primary" type="submit" disabled={submitting}>
                  {submitting ? '保存中…' : '保存'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
