import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'

import type { AdminEvent } from '../../stores/adminStore'
import { useAdminStore } from '../../stores/adminStore'
import {
  DECREE_TYPES,
  DIPLOMACY_TARGETS,
  REGION_NAMES,
  TARGET_REQUIRED,
} from '../../types/game'
import type {
  DecreeType,
  PersonnelAction,
} from '../../types/game'

const STATE_FIELDS = [
  'national_treasury',
  'imperial_treasury',
  'grain',
  'population',
  'military_strength',
  'civil_morale',
  'military_morale',
  'court_prestige',
] as const

const REGION_FIELDS = [
  'stability',
  'garrison',
  'civil_morale',
  'rebellion_risk',
  'disaster_level',
  'tax_collected',
  'tax_rate',
] as const

const FACTION_FIELDS = [
  'satisfaction',
  'influence',
  'rebellion_risk',
] as const

type ConditionMode = 'none' | 'json' | 'and' | ConditionLeafType
type ConditionLeafType =
  | 'minister_alive'
  | 'minister_removed'
  | 'minister_active'
  | 'script_resolved'
  | 'state_field_lt'
  | 'state_field_gt'
  | 'region_field_lt'
  | 'region_field_gt'
  | 'faction_field_lt'
  | 'faction_field_gt'

const CONDITION_LEAF_TYPES: ConditionLeafType[] = [
  'minister_alive',
  'minister_removed',
  'minister_active',
  'script_resolved',
  'state_field_lt',
  'state_field_gt',
  'region_field_lt',
  'region_field_gt',
  'faction_field_lt',
  'faction_field_gt',
]

interface ConditionClauseDraft {
  type: ConditionLeafType
  name: string
  script_id: string
  field: string
  region: string
  faction: string
  value: number
}

interface ConditionFormState {
  mode: ConditionMode
  clause: ConditionClauseDraft
  andClauses: ConditionClauseDraft[]
  jsonText: string
}

interface DecreeDraft {
  type: DecreeType
  target: string
  sub_action: PersonnelAction
  position: string
  parametersText: string
}

interface ChoiceDraft {
  label: string
  description: string
  decrees: DecreeDraft[]
  loyaltyEffects: Array<{ name: string; value: number }>
  stateEffects: Array<{ key: string; value: number }>
}

interface EditorState {
  mode: 'create' | 'edit'
  originalScriptId?: string
  value: AdminEvent
}

function emptyEvent(): AdminEvent {
  return {
    script_id: '',
    trigger_year: 1627,
    trigger_month: 8,
    title: '',
    is_blocking: false,
    rich_description: '',
    historical_hint: '',
    condition: null,
    choices: [
      {
        label: '默认选项',
        description: '',
        decrees: [],
        loyalty_effects: [],
        state_effects: {},
      },
    ],
  }
}

function parseJsonOrThrow<T>(raw: string, label: string): T {
  try {
    return JSON.parse(raw) as T
  } catch (error) {
    throw new Error(`${label} JSON 解析失败：${error instanceof Error ? error.message : String(error)}`)
  }
}

function parseObjectJson(raw: string, label: string): Record<string, unknown> {
  const parsed = parseJsonOrThrow<unknown>(raw || '{}', label)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label} 必须为对象`)
  }
  return parsed as Record<string, unknown>
}

function toInt(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : fallback
}

function defaultClause(type: ConditionLeafType = 'minister_alive'): ConditionClauseDraft {
  return {
    type,
    name: '',
    script_id: '',
    field: type.startsWith('state_')
      ? STATE_FIELDS[0]
      : type.startsWith('region_')
        ? REGION_FIELDS[0]
        : FACTION_FIELDS[0],
    region: REGION_NAMES[0],
    faction: '',
    value: 0,
  }
}

function parseLeafClause(raw: unknown): ConditionClauseDraft | null {
  if (!raw || typeof raw !== 'object') return null
  const node = raw as Record<string, unknown>
  if (typeof node.type !== 'string') return null
  if (!CONDITION_LEAF_TYPES.includes(node.type as ConditionLeafType)) return null
  const type = node.type as ConditionLeafType
  const clause = defaultClause(type)

  if (type === 'minister_alive' || type === 'minister_removed' || type === 'minister_active') {
    if (typeof node.name !== 'string') return null
    clause.name = node.name
    return clause
  }
  if (type === 'script_resolved') {
    if (typeof node.script_id !== 'string') return null
    clause.script_id = node.script_id
    return clause
  }
  if (type === 'state_field_lt' || type === 'state_field_gt') {
    if (typeof node.field !== 'string' || typeof node.value !== 'number') return null
    clause.field = node.field
    clause.value = Math.trunc(node.value)
    return clause
  }
  if (type === 'region_field_lt' || type === 'region_field_gt') {
    if (typeof node.region !== 'string' || typeof node.field !== 'string' || typeof node.value !== 'number') return null
    clause.region = node.region
    clause.field = node.field
    clause.value = Math.trunc(node.value)
    return clause
  }
  if (typeof node.faction !== 'string' || typeof node.field !== 'string' || typeof node.value !== 'number') return null
  clause.faction = node.faction
  clause.field = node.field
  clause.value = Math.trunc(node.value)
  return clause
}

function conditionToForm(condition: AdminEvent['condition']): ConditionFormState {
  if (condition === null) {
    return {
      mode: 'none',
      clause: defaultClause(),
      andClauses: [defaultClause()],
      jsonText: 'null',
    }
  }

  const leaf = parseLeafClause(condition)
  if (leaf) {
    return {
      mode: leaf.type,
      clause: leaf,
      andClauses: [defaultClause()],
      jsonText: JSON.stringify(condition, null, 2),
    }
  }

  if (typeof condition === 'object' && condition) {
    const node = condition as Record<string, unknown>
    if (node.type === 'and' && Array.isArray(node.conditions)) {
      const parsed = node.conditions.map(parseLeafClause)
      if (parsed.length > 0 && parsed.every(Boolean)) {
        return {
          mode: 'and',
          clause: defaultClause(),
          andClauses: parsed as ConditionClauseDraft[],
          jsonText: JSON.stringify(condition, null, 2),
        }
      }
    }
  }

  return {
    mode: 'json',
    clause: defaultClause(),
    andClauses: [defaultClause()],
    jsonText: JSON.stringify(condition, null, 2),
  }
}

function renderLeafClause(clause: ConditionClauseDraft): Record<string, unknown> {
  if (clause.type === 'minister_alive' || clause.type === 'minister_removed' || clause.type === 'minister_active') {
    const name = clause.name.trim()
    if (!name) throw new Error(`${clause.type} 需要 name`)
    return { type: clause.type, name }
  }
  if (clause.type === 'script_resolved') {
    const scriptId = clause.script_id.trim()
    if (!scriptId) throw new Error('script_resolved 需要 script_id')
    return { type: clause.type, script_id: scriptId }
  }
  if (clause.type === 'state_field_lt' || clause.type === 'state_field_gt') {
    if (!clause.field.trim()) throw new Error(`${clause.type} 需要 field`)
    return { type: clause.type, field: clause.field.trim(), value: Math.trunc(clause.value) }
  }
  if (clause.type === 'region_field_lt' || clause.type === 'region_field_gt') {
    if (!clause.region.trim()) throw new Error(`${clause.type} 需要 region`)
    if (!clause.field.trim()) throw new Error(`${clause.type} 需要 field`)
    return {
      type: clause.type,
      region: clause.region.trim(),
      field: clause.field.trim(),
      value: Math.trunc(clause.value),
    }
  }
  if (!clause.faction.trim()) throw new Error(`${clause.type} 需要 faction`)
  if (!clause.field.trim()) throw new Error(`${clause.type} 需要 field`)
  return {
    type: clause.type,
    faction: clause.faction.trim(),
    field: clause.field.trim(),
    value: Math.trunc(clause.value),
  }
}

function buildCondition(form: ConditionFormState): AdminEvent['condition'] {
  if (form.mode === 'none') return null
  if (form.mode === 'json') {
    return parseJsonOrThrow<Record<string, unknown> | null>(form.jsonText, 'condition')
  }
  if (form.mode === 'and') {
    if (form.andClauses.length === 0) throw new Error('and 条件至少需要 1 个子条件')
    return {
      type: 'and',
      conditions: form.andClauses.map(renderLeafClause),
    }
  }
  return renderLeafClause({ ...form.clause, type: form.mode })
}

function describeCondition(condition: AdminEvent['condition']): string {
  if (condition === null) return '无条件（总是触发）'
  if (!condition || typeof condition !== 'object') return '条件格式无效'
  const node = condition as Record<string, unknown>
  const type = node.type
  if (type === 'minister_alive') return `大臣仍在：${String(node.name ?? '')}`
  if (type === 'minister_removed') return `大臣已罢免：${String(node.name ?? '')}`
  if (type === 'minister_active') return `大臣在朝：${String(node.name ?? '')}`
  if (type === 'script_resolved') return `剧情已解决：${String(node.script_id ?? '')}`
  if (type === 'state_field_lt') return `国家字段 ${String(node.field ?? '')} < ${String(node.value ?? '')}`
  if (type === 'state_field_gt') return `国家字段 ${String(node.field ?? '')} > ${String(node.value ?? '')}`
  if (type === 'region_field_lt') return `地区 ${String(node.region ?? '')} 的 ${String(node.field ?? '')} < ${String(node.value ?? '')}`
  if (type === 'region_field_gt') return `地区 ${String(node.region ?? '')} 的 ${String(node.field ?? '')} > ${String(node.value ?? '')}`
  if (type === 'faction_field_lt') return `派系 ${String(node.faction ?? '')} 的 ${String(node.field ?? '')} < ${String(node.value ?? '')}`
  if (type === 'faction_field_gt') return `派系 ${String(node.faction ?? '')} 的 ${String(node.field ?? '')} > ${String(node.value ?? '')}`
  if (type === 'and' && Array.isArray(node.conditions)) {
    return node.conditions.map((item) => describeCondition(item as Record<string, unknown>)).join(' 且 ')
  }
  return '条件格式无效'
}

function decreeToDraft(raw: Record<string, unknown>): DecreeDraft {
  const type = typeof raw.type === 'string' && DECREE_TYPES.includes(raw.type as DecreeType)
    ? raw.type as DecreeType
    : 'tax_increase'
  const target = typeof raw.target === 'string' ? raw.target : ''
  const subAction = raw.sub_action === 'dismiss' || raw.sub_action === 'execute' ? raw.sub_action : 'appoint'

  let position = ''
  let params: Record<string, unknown> = {}
  if (raw.parameters && typeof raw.parameters === 'object' && !Array.isArray(raw.parameters)) {
    params = { ...(raw.parameters as Record<string, unknown>) }
    if (typeof params.position === 'string') {
      position = params.position
      delete params.position
    }
  }

  return {
    type,
    target,
    sub_action: subAction,
    position,
    parametersText: JSON.stringify(params, null, 2),
  }
}

function decreeFromDraft(
  draft: DecreeDraft,
  choiceIndex: number,
  decreeIndex: number,
): Record<string, unknown> {
  const payload: Record<string, unknown> = { type: draft.type }
  const requiredTarget = TARGET_REQUIRED[draft.type]
  const target = draft.target.trim()
  if (requiredTarget && target) {
    payload.target = target
  }
  if (draft.type === 'personnel') {
    payload.sub_action = draft.sub_action
  }

  const parameters = parseObjectJson(
    draft.parametersText || '{}',
    `choices[${choiceIndex}].decrees[${decreeIndex}].parameters`,
  )
  if (draft.type === 'personnel' && draft.sub_action === 'appoint') {
    const position = draft.position.trim()
    if (position) parameters.position = position
  }
  if (Object.keys(parameters).length > 0) {
    payload.parameters = parameters
  }
  return payload
}

function choiceToDraft(choice: AdminEvent['choices'][number]): ChoiceDraft {
  return {
    label: choice.label,
    description: choice.description,
    decrees: (choice.decrees ?? []).map((item) => decreeToDraft(item)),
    loyaltyEffects: (choice.loyalty_effects ?? []).map(([name, value]) => ({ name, value })),
    stateEffects: Object.entries(choice.state_effects ?? {}).map(([key, value]) => ({ key, value })),
  }
}

function choiceFromDraft(draft: ChoiceDraft, index: number): AdminEvent['choices'][number] {
  const label = draft.label.trim()
  if (!label) throw new Error(`choices[${index}] 缺少 label`)

  const decrees = draft.decrees.map((item, decreeIndex) => decreeFromDraft(item, index, decreeIndex))
  const loyalty_effects = draft.loyaltyEffects
    .map((item) => [item.name.trim(), Math.trunc(item.value)] as [string, number])
    .filter(([name]) => !!name)
  const state_effects = draft.stateEffects.reduce<Record<string, number>>((acc, item) => {
    const key = item.key.trim()
    if (key) acc[key] = Math.trunc(item.value)
    return acc
  }, {})

  return {
    label,
    description: draft.description,
    decrees,
    loyalty_effects,
    state_effects,
  }
}

function defaultDecreeDraft(type: DecreeType = 'tax_increase'): DecreeDraft {
  return {
    type,
    target: '',
    sub_action: 'appoint',
    position: '',
    parametersText: '{}',
  }
}

function defaultChoiceDraft(): ChoiceDraft {
  return {
    label: '新选项',
    description: '',
    decrees: [],
    loyaltyEffects: [],
    stateEffects: [],
  }
}

export default function EventManager() {
  const { events, ministers, createEvent, updateEvent, deleteEvent } = useAdminStore()
  const [search, setSearch] = useState('')
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [conditionForm, setConditionForm] = useState<ConditionFormState>({
    mode: 'none',
    clause: defaultClause(),
    andClauses: [defaultClause()],
    jsonText: 'null',
  })
  const [choiceDrafts, setChoiceDrafts] = useState<ChoiceDraft[]>([])
  const [choiceIndex, setChoiceIndex] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const ministerNames = useMemo(
    () => Array.from(new Set(ministers.map((item) => item.name))).sort((a, b) => a.localeCompare(b)),
    [ministers],
  )
  const factionNames = useMemo(
    () => Array.from(new Set(ministers.map((item) => item.faction))).sort((a, b) => a.localeCompare(b)),
    [ministers],
  )
  const scriptIds = useMemo(
    () => Array.from(new Set(events.map((item) => item.script_id))).sort((a, b) => a.localeCompare(b)),
    [events],
  )

  const filtered = useMemo(() => {
    const needle = search.trim()
    return events.filter((event) => !needle || event.script_id.includes(needle) || event.title.includes(needle))
  }, [events, search])

  const grouped = useMemo(() => {
    const result = new Map<string, AdminEvent[]>()
    const sorted = [...filtered].sort((a, b) => {
      if (a.trigger_year !== b.trigger_year) return a.trigger_year - b.trigger_year
      if (a.trigger_month !== b.trigger_month) return a.trigger_month - b.trigger_month
      return a.script_id.localeCompare(b.script_id)
    })
    for (const item of sorted) {
      const key = `${item.trigger_year}年${item.trigger_month}月`
      result.set(key, [...(result.get(key) ?? []), item])
    }
    return result
  }, [filtered])

  const conditionPreview = useMemo(() => {
    try {
      const condition = buildCondition(conditionForm)
      return describeCondition(condition)
    } catch (error) {
      return `条件预览失败：${error instanceof Error ? error.message : String(error)}`
    }
  }, [conditionForm])

  const applyEditorState = (value: AdminEvent, mode: 'create' | 'edit', originalScriptId?: string) => {
    setEditor({ mode, originalScriptId, value })
    setConditionForm(conditionToForm(value.condition))
    setChoiceDrafts(value.choices.map((item) => choiceToDraft(item)))
    setChoiceIndex(0)
    setActionError(null)
  }

  const openCreate = () => {
    applyEditorState(emptyEvent(), 'create')
  }

  const openEdit = (event: AdminEvent) => {
    const value = JSON.parse(JSON.stringify(event)) as AdminEvent
    applyEditorState(value, 'edit', event.script_id)
  }

  const onDelete = async (scriptId: string) => {
    if (!window.confirm(`确认删除事件 ${scriptId}？`)) return
    setActionError(null)
    try {
      await deleteEvent(scriptId)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '删除事件失败')
    }
  }

  const activeChoice = choiceDrafts[choiceIndex] ?? null

  const updateActiveChoice = (updater: (choice: ChoiceDraft) => ChoiceDraft) => {
    setChoiceDrafts((prev) => prev.map((choice, index) => (
      index === choiceIndex ? updater(choice) : choice
    )))
  }

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!editor) return

    setSubmitting(true)
    setActionError(null)
    try {
      const condition = buildCondition(conditionForm)
      const choices = choiceDrafts.map((choice, index) => choiceFromDraft(choice, index))
      if (choices.length === 0) throw new Error('choices 至少需要一个选项')

      const payload: AdminEvent = {
        ...editor.value,
        script_id: editor.value.script_id.trim(),
        title: editor.value.title.trim(),
        historical_hint: editor.value.historical_hint.trim(),
        condition,
        choices,
      }

      if (editor.mode === 'create') {
        await createEvent(payload)
      } else {
        await updateEvent(editor.originalScriptId ?? payload.script_id, payload)
      }
      setEditor(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '保存事件失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="admin-card">
      <div className="admin-toolbar">
        <input
          className="admin-input"
          placeholder="按 script_id / 标题搜索"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <button className="admin-button" onClick={openCreate}>新增事件</button>
      </div>

      <div className="admin-event-groups">
        {Array.from(grouped.entries()).map(([period, items]) => (
          <section key={period} className="admin-event-group">
            <h3>{period}</h3>
            <table className="admin-table">
              <thead>
                <tr><th>script_id</th><th>标题</th><th>阻断</th><th>选项数</th><th>操作</th></tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.script_id}>
                    <td>{item.script_id}</td>
                    <td>{item.title}</td>
                    <td>{item.is_blocking ? '是' : '否'}</td>
                    <td>{item.choices.length}</td>
                    <td className="admin-actions">
                      <button className="admin-button small" onClick={() => openEdit(item)}>编辑</button>
                      <button className="admin-button small danger" onClick={() => void onDelete(item.script_id)}>删除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
      </div>

      {actionError && <div className="admin-error">{actionError}</div>}

      {editor && (
        <div className="admin-modal-overlay" onClick={() => setEditor(null)}>
          <div className="admin-modal admin-modal-wide" onClick={(event) => event.stopPropagation()}>
            <h3>{editor.mode === 'create' ? '新增事件' : `编辑事件：${editor.originalScriptId}`}</h3>
            <form className="admin-form" onSubmit={onSubmit}>
              <label>
                script_id
                <input
                  className="admin-input"
                  value={editor.value.script_id}
                  onChange={(event) => setEditor({ ...editor, value: { ...editor.value, script_id: event.target.value } })}
                  required
                  disabled={editor.mode === 'edit'}
                />
              </label>
              <label>
                标题
                <input
                  className="admin-input"
                  value={editor.value.title}
                  onChange={(event) => setEditor({ ...editor, value: { ...editor.value, title: event.target.value } })}
                  required
                />
              </label>
              <label>
                触发年份
                <input
                  className="admin-input"
                  type="number"
                  min={1621}
                  max={1644}
                  value={editor.value.trigger_year}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, trigger_year: toInt(event.target.value, editor.value.trigger_year) },
                  })}
                />
              </label>
              <label>
                触发月份
                <input
                  className="admin-input"
                  type="number"
                  min={1}
                  max={12}
                  value={editor.value.trigger_month}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, trigger_month: toInt(event.target.value, editor.value.trigger_month) },
                  })}
                />
              </label>
              <label className="admin-checkbox">
                <input
                  type="checkbox"
                  checked={editor.value.is_blocking}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, is_blocking: event.target.checked },
                  })}
                />
                阻断事件（必须处理）
              </label>
              <label>
                rich_description
                <textarea
                  className="admin-textarea"
                  rows={6}
                  value={editor.value.rich_description}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, rich_description: event.target.value },
                  })}
                />
              </label>
              <label>
                historical_hint
                <textarea
                  className="admin-textarea"
                  rows={4}
                  value={editor.value.historical_hint}
                  onChange={(event) => setEditor({
                    ...editor,
                    value: { ...editor.value, historical_hint: event.target.value },
                  })}
                />
              </label>
              <div className="admin-form-section">
                <h4>Condition 编辑器</h4>
                <label>
                  type
                  <select
                    className="admin-select"
                    value={conditionForm.mode}
                    onChange={(event) => {
                      const mode = event.target.value as ConditionMode
                      setConditionForm((prev) => {
                        if (mode === 'and' && prev.andClauses.length === 0) {
                          return { ...prev, mode, andClauses: [defaultClause()] }
                        }
                        if (CONDITION_LEAF_TYPES.includes(mode as ConditionLeafType)) {
                          return { ...prev, mode, clause: defaultClause(mode as ConditionLeafType) }
                        }
                        return { ...prev, mode }
                      })
                    }}
                  >
                    <option value="none">none</option>
                    {CONDITION_LEAF_TYPES.map((type) => (
                      <option key={type} value={type}>{type}</option>
                    ))}
                    <option value="and">and</option>
                    <option value="json">json</option>
                  </select>
                </label>

                {conditionForm.mode === 'json' && (
                  <label>
                    condition JSON
                    <textarea
                      className="admin-textarea code"
                      rows={8}
                      value={conditionForm.jsonText}
                      onChange={(event) => setConditionForm((prev) => ({ ...prev, jsonText: event.target.value }))}
                    />
                  </label>
                )}

                {conditionForm.mode !== 'none' && conditionForm.mode !== 'json' && conditionForm.mode !== 'and' && (
                  <div className="admin-subpanel">
                    <div className="admin-inline-grid">
                      {(conditionForm.mode === 'minister_alive' || conditionForm.mode === 'minister_removed' || conditionForm.mode === 'minister_active') && (
                        <label>
                          name
                          <input
                            className="admin-input"
                            list="admin-minister-name-list"
                            value={conditionForm.clause.name}
                            onChange={(event) => setConditionForm((prev) => ({
                              ...prev,
                              clause: { ...prev.clause, name: event.target.value },
                            }))}
                          />
                        </label>
                      )}

                      {conditionForm.mode === 'script_resolved' && (
                        <label>
                          script_id
                          <input
                            className="admin-input"
                            list="admin-script-id-list"
                            value={conditionForm.clause.script_id}
                            onChange={(event) => setConditionForm((prev) => ({
                              ...prev,
                              clause: { ...prev.clause, script_id: event.target.value },
                            }))}
                          />
                        </label>
                      )}

                      {(conditionForm.mode === 'state_field_lt' || conditionForm.mode === 'state_field_gt') && (
                        <>
                          <label>
                            field
                            <select
                              className="admin-select"
                              value={conditionForm.clause.field}
                              onChange={(event) => setConditionForm((prev) => ({
                                ...prev,
                                clause: { ...prev.clause, field: event.target.value },
                              }))}
                            >
                              {STATE_FIELDS.map((field) => (
                                <option key={field} value={field}>{field}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            value
                            <input
                              className="admin-input"
                              type="number"
                              value={conditionForm.clause.value}
                              onChange={(event) => setConditionForm((prev) => ({
                                ...prev,
                                clause: { ...prev.clause, value: toInt(event.target.value, prev.clause.value) },
                              }))}
                            />
                          </label>
                        </>
                      )}

                      {(conditionForm.mode === 'region_field_lt' || conditionForm.mode === 'region_field_gt') && (
                        <>
                          <label>
                            region
                            <select
                              className="admin-select"
                              value={conditionForm.clause.region}
                              onChange={(event) => setConditionForm((prev) => ({
                                ...prev,
                                clause: { ...prev.clause, region: event.target.value },
                              }))}
                            >
                              {REGION_NAMES.map((region) => (
                                <option key={region} value={region}>{region}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            field
                            <select
                              className="admin-select"
                              value={conditionForm.clause.field}
                              onChange={(event) => setConditionForm((prev) => ({
                                ...prev,
                                clause: { ...prev.clause, field: event.target.value },
                              }))}
                            >
                              {REGION_FIELDS.map((field) => (
                                <option key={field} value={field}>{field}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            value
                            <input
                              className="admin-input"
                              type="number"
                              value={conditionForm.clause.value}
                              onChange={(event) => setConditionForm((prev) => ({
                                ...prev,
                                clause: { ...prev.clause, value: toInt(event.target.value, prev.clause.value) },
                              }))}
                            />
                          </label>
                        </>
                      )}

                      {(conditionForm.mode === 'faction_field_lt' || conditionForm.mode === 'faction_field_gt') && (
                        <>
                          <label>
                            faction
                            <input
                              className="admin-input"
                              list="admin-faction-name-list"
                              value={conditionForm.clause.faction}
                              onChange={(event) => setConditionForm((prev) => ({
                                ...prev,
                                clause: { ...prev.clause, faction: event.target.value },
                              }))}
                            />
                          </label>
                          <label>
                            field
                            <select
                              className="admin-select"
                              value={conditionForm.clause.field}
                              onChange={(event) => setConditionForm((prev) => ({
                                ...prev,
                                clause: { ...prev.clause, field: event.target.value },
                              }))}
                            >
                              {FACTION_FIELDS.map((field) => (
                                <option key={field} value={field}>{field}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            value
                            <input
                              className="admin-input"
                              type="number"
                              value={conditionForm.clause.value}
                              onChange={(event) => setConditionForm((prev) => ({
                                ...prev,
                                clause: { ...prev.clause, value: toInt(event.target.value, prev.clause.value) },
                              }))}
                            />
                          </label>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {conditionForm.mode === 'and' && (
                  <div className="admin-subpanel">
                    {conditionForm.andClauses.map((clause, index) => (
                      <div key={`and-${index}`} className="admin-subpanel">
                        <div className="admin-subpanel-head">
                          <strong>{`子条件 ${index + 1}`}</strong>
                          <button
                            type="button"
                            className="admin-button small danger"
                            onClick={() => setConditionForm((prev) => ({
                              ...prev,
                              andClauses: prev.andClauses.length > 1
                                ? prev.andClauses.filter((_, idx) => idx !== index)
                                : prev.andClauses,
                            }))}
                            disabled={conditionForm.andClauses.length <= 1}
                          >
                            删除
                          </button>
                        </div>
                        <div className="admin-inline-grid">
                          <label>
                            type
                            <select
                              className="admin-select"
                              value={clause.type}
                              onChange={(event) => setConditionForm((prev) => ({
                                ...prev,
                                andClauses: prev.andClauses.map((item, idx) => (
                                  idx === index ? defaultClause(event.target.value as ConditionLeafType) : item
                                )),
                              }))}
                            >
                              {CONDITION_LEAF_TYPES.map((type) => (
                                <option key={type} value={type}>{type}</option>
                              ))}
                            </select>
                          </label>
                          {(clause.type === 'minister_alive' || clause.type === 'minister_removed' || clause.type === 'minister_active') && (
                            <label>
                              name
                              <input
                                className="admin-input"
                                list="admin-minister-name-list"
                                value={clause.name}
                                onChange={(event) => setConditionForm((prev) => ({
                                  ...prev,
                                  andClauses: prev.andClauses.map((item, idx) => (
                                    idx === index ? { ...item, name: event.target.value } : item
                                  )),
                                }))}
                              />
                            </label>
                          )}
                          {clause.type === 'script_resolved' && (
                            <label>
                              script_id
                              <input
                                className="admin-input"
                                list="admin-script-id-list"
                                value={clause.script_id}
                                onChange={(event) => setConditionForm((prev) => ({
                                  ...prev,
                                  andClauses: prev.andClauses.map((item, idx) => (
                                    idx === index ? { ...item, script_id: event.target.value } : item
                                  )),
                                }))}
                              />
                            </label>
                          )}
                          {(clause.type === 'state_field_lt' || clause.type === 'state_field_gt') && (
                            <>
                              <label>
                                field
                                <select
                                  className="admin-select"
                                  value={clause.field}
                                  onChange={(event) => setConditionForm((prev) => ({
                                    ...prev,
                                    andClauses: prev.andClauses.map((item, idx) => (
                                      idx === index ? { ...item, field: event.target.value } : item
                                    )),
                                  }))}
                                >
                                  {STATE_FIELDS.map((field) => (
                                    <option key={field} value={field}>{field}</option>
                                  ))}
                                </select>
                              </label>
                              <label>
                                value
                                <input
                                  className="admin-input"
                                  type="number"
                                  value={clause.value}
                                  onChange={(event) => setConditionForm((prev) => ({
                                    ...prev,
                                    andClauses: prev.andClauses.map((item, idx) => (
                                      idx === index ? { ...item, value: toInt(event.target.value, item.value) } : item
                                    )),
                                  }))}
                                />
                              </label>
                            </>
                          )}
                          {(clause.type === 'region_field_lt' || clause.type === 'region_field_gt') && (
                            <>
                              <label>
                                region
                                <select
                                  className="admin-select"
                                  value={clause.region}
                                  onChange={(event) => setConditionForm((prev) => ({
                                    ...prev,
                                    andClauses: prev.andClauses.map((item, idx) => (
                                      idx === index ? { ...item, region: event.target.value } : item
                                    )),
                                  }))}
                                >
                                  {REGION_NAMES.map((region) => (
                                    <option key={region} value={region}>{region}</option>
                                  ))}
                                </select>
                              </label>
                              <label>
                                field
                                <select
                                  className="admin-select"
                                  value={clause.field}
                                  onChange={(event) => setConditionForm((prev) => ({
                                    ...prev,
                                    andClauses: prev.andClauses.map((item, idx) => (
                                      idx === index ? { ...item, field: event.target.value } : item
                                    )),
                                  }))}
                                >
                                  {REGION_FIELDS.map((field) => (
                                    <option key={field} value={field}>{field}</option>
                                  ))}
                                </select>
                              </label>
                              <label>
                                value
                                <input
                                  className="admin-input"
                                  type="number"
                                  value={clause.value}
                                  onChange={(event) => setConditionForm((prev) => ({
                                    ...prev,
                                    andClauses: prev.andClauses.map((item, idx) => (
                                      idx === index ? { ...item, value: toInt(event.target.value, item.value) } : item
                                    )),
                                  }))}
                                />
                              </label>
                            </>
                          )}
                          {(clause.type === 'faction_field_lt' || clause.type === 'faction_field_gt') && (
                            <>
                              <label>
                                faction
                                <input
                                  className="admin-input"
                                  list="admin-faction-name-list"
                                  value={clause.faction}
                                  onChange={(event) => setConditionForm((prev) => ({
                                    ...prev,
                                    andClauses: prev.andClauses.map((item, idx) => (
                                      idx === index ? { ...item, faction: event.target.value } : item
                                    )),
                                  }))}
                                />
                              </label>
                              <label>
                                field
                                <select
                                  className="admin-select"
                                  value={clause.field}
                                  onChange={(event) => setConditionForm((prev) => ({
                                    ...prev,
                                    andClauses: prev.andClauses.map((item, idx) => (
                                      idx === index ? { ...item, field: event.target.value } : item
                                    )),
                                  }))}
                                >
                                  {FACTION_FIELDS.map((field) => (
                                    <option key={field} value={field}>{field}</option>
                                  ))}
                                </select>
                              </label>
                              <label>
                                value
                                <input
                                  className="admin-input"
                                  type="number"
                                  value={clause.value}
                                  onChange={(event) => setConditionForm((prev) => ({
                                    ...prev,
                                    andClauses: prev.andClauses.map((item, idx) => (
                                      idx === index ? { ...item, value: toInt(event.target.value, item.value) } : item
                                    )),
                                  }))}
                                />
                              </label>
                            </>
                          )}
                        </div>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="admin-button small"
                      onClick={() => setConditionForm((prev) => ({
                        ...prev,
                        andClauses: [...prev.andClauses, defaultClause()],
                      }))}
                    >
                      新增子条件
                    </button>
                  </div>
                )}

                <div className="admin-hint">预览：{conditionPreview}</div>
              </div>
              <div className="admin-form-section">
                <h4>Choices 子编辑器</h4>
                <div className="admin-actions">
                  {choiceDrafts.map((choice, index) => (
                    <button
                      key={`choice-tab-${index}`}
                      type="button"
                      className={`admin-button small${index === choiceIndex ? ' primary' : ''}`}
                      onClick={() => setChoiceIndex(index)}
                    >
                      {`选项${index + 1} ${choice.label ? `(${choice.label})` : ''}`}
                    </button>
                  ))}
                  <button
                    type="button"
                    className="admin-button small"
                    onClick={() => {
                      setChoiceDrafts((prev) => {
                        const next = [...prev, defaultChoiceDraft()]
                        setChoiceIndex(next.length - 1)
                        return next
                      })
                    }}
                  >
                    新增选项
                  </button>
                  <button
                    type="button"
                    className="admin-button small"
                    disabled={choiceDrafts.length <= 1 || choiceIndex <= 0}
                    onClick={() => setChoiceDrafts((prev) => {
                      if (choiceIndex <= 0) return prev
                      const next = [...prev]
                      const current = next[choiceIndex]
                      next[choiceIndex] = next[choiceIndex - 1]
                      next[choiceIndex - 1] = current
                      setChoiceIndex(choiceIndex - 1)
                      return next
                    })}
                  >
                    上移
                  </button>
                  <button
                    type="button"
                    className="admin-button small"
                    disabled={choiceDrafts.length <= 1 || choiceIndex >= choiceDrafts.length - 1}
                    onClick={() => setChoiceDrafts((prev) => {
                      if (choiceIndex >= prev.length - 1) return prev
                      const next = [...prev]
                      const current = next[choiceIndex]
                      next[choiceIndex] = next[choiceIndex + 1]
                      next[choiceIndex + 1] = current
                      setChoiceIndex(choiceIndex + 1)
                      return next
                    })}
                  >
                    下移
                  </button>
                  <button
                    type="button"
                    className="admin-button small danger"
                    disabled={choiceDrafts.length <= 1}
                    onClick={() => {
                      if (choiceDrafts.length <= 1) return
                      setChoiceDrafts((prev) => prev.filter((_, idx) => idx !== choiceIndex))
                      setChoiceIndex((prev) => Math.max(0, prev - 1))
                    }}
                  >
                    删除当前
                  </button>
                </div>

                {activeChoice && (
                  <div className="admin-subpanel">
                    <label>
                      label
                      <input
                        className="admin-input"
                        value={activeChoice.label}
                        onChange={(event) => updateActiveChoice((choice) => ({
                          ...choice,
                          label: event.target.value,
                        }))}
                      />
                    </label>
                    <label>
                      description
                      <textarea
                        className="admin-textarea"
                        rows={3}
                        value={activeChoice.description}
                        onChange={(event) => updateActiveChoice((choice) => ({
                          ...choice,
                          description: event.target.value,
                        }))}
                      />
                    </label>

                    <div className="admin-subpanel">
                      <div className="admin-subpanel-head">
                        <strong>decrees</strong>
                        <button
                          type="button"
                          className="admin-button small"
                          onClick={() => updateActiveChoice((choice) => ({
                            ...choice,
                            decrees: [...choice.decrees, defaultDecreeDraft()],
                          }))}
                        >
                          添加 decree
                        </button>
                      </div>

                      {activeChoice.decrees.length === 0 && <div className="admin-hint">暂无 decree</div>}
                      {activeChoice.decrees.map((decree, decreeIndex) => (
                        <div key={`decree-${decreeIndex}`} className="admin-subpanel">
                          <div className="admin-subpanel-head">
                            <span>{`decree ${decreeIndex + 1}`}</span>
                            <div className="admin-actions">
                              <button
                                type="button"
                                className="admin-button small"
                                disabled={decreeIndex <= 0}
                                onClick={() => updateActiveChoice((choice) => {
                                  if (decreeIndex <= 0) return choice
                                  const next = [...choice.decrees]
                                  const current = next[decreeIndex]
                                  next[decreeIndex] = next[decreeIndex - 1]
                                  next[decreeIndex - 1] = current
                                  return { ...choice, decrees: next }
                                })}
                              >
                                上移
                              </button>
                              <button
                                type="button"
                                className="admin-button small"
                                disabled={decreeIndex >= activeChoice.decrees.length - 1}
                                onClick={() => updateActiveChoice((choice) => {
                                  if (decreeIndex >= choice.decrees.length - 1) return choice
                                  const next = [...choice.decrees]
                                  const current = next[decreeIndex]
                                  next[decreeIndex] = next[decreeIndex + 1]
                                  next[decreeIndex + 1] = current
                                  return { ...choice, decrees: next }
                                })}
                              >
                                下移
                              </button>
                              <button
                                type="button"
                                className="admin-button small danger"
                                onClick={() => updateActiveChoice((choice) => ({
                                  ...choice,
                                  decrees: choice.decrees.filter((_, idx) => idx !== decreeIndex),
                                }))}
                              >
                                删除
                              </button>
                            </div>
                          </div>

                          <div className="admin-inline-grid">
                            <label>
                              type
                              <select
                                className="admin-select"
                                value={decree.type}
                                onChange={(event) => updateActiveChoice((choice) => ({
                                  ...choice,
                                  decrees: choice.decrees.map((item, idx) => (
                                    idx === decreeIndex
                                      ? { ...item, type: event.target.value as DecreeType, target: '' }
                                      : item
                                  )),
                                }))}
                              >
                                {DECREE_TYPES.map((type) => (
                                  <option key={type} value={type}>{type}</option>
                                ))}
                              </select>
                            </label>

                            {(TARGET_REQUIRED[decree.type] === 'person' || TARGET_REQUIRED[decree.type] === 'region' || TARGET_REQUIRED[decree.type] === 'diplomacy_target') && (
                              <label>
                                target
                                {TARGET_REQUIRED[decree.type] === 'region' ? (
                                  <select
                                    className="admin-select"
                                    value={decree.target}
                                    onChange={(event) => updateActiveChoice((choice) => ({
                                      ...choice,
                                      decrees: choice.decrees.map((item, idx) => (
                                        idx === decreeIndex ? { ...item, target: event.target.value } : item
                                      )),
                                    }))}
                                  >
                                    <option value="">请选择</option>
                                    {REGION_NAMES.map((region) => (
                                      <option key={region} value={region}>{region}</option>
                                    ))}
                                  </select>
                                ) : TARGET_REQUIRED[decree.type] === 'diplomacy_target' ? (
                                  <select
                                    className="admin-select"
                                    value={decree.target}
                                    onChange={(event) => updateActiveChoice((choice) => ({
                                      ...choice,
                                      decrees: choice.decrees.map((item, idx) => (
                                        idx === decreeIndex ? { ...item, target: event.target.value } : item
                                      )),
                                    }))}
                                  >
                                    <option value="">请选择</option>
                                    {DIPLOMACY_TARGETS.map((target) => (
                                      <option key={target} value={target}>{target}</option>
                                    ))}
                                  </select>
                                ) : (
                                  <input
                                    className="admin-input"
                                    list="admin-minister-name-list"
                                    value={decree.target}
                                    onChange={(event) => updateActiveChoice((choice) => ({
                                      ...choice,
                                      decrees: choice.decrees.map((item, idx) => (
                                        idx === decreeIndex ? { ...item, target: event.target.value } : item
                                      )),
                                    }))}
                                  />
                                )}
                              </label>
                            )}

                            {decree.type === 'personnel' && (
                              <label>
                                sub_action
                                <select
                                  className="admin-select"
                                  value={decree.sub_action}
                                  onChange={(event) => updateActiveChoice((choice) => ({
                                    ...choice,
                                    decrees: choice.decrees.map((item, idx) => (
                                      idx === decreeIndex
                                        ? { ...item, sub_action: event.target.value as PersonnelAction }
                                        : item
                                    )),
                                  }))}
                                >
                                  <option value="appoint">appoint</option>
                                  <option value="dismiss">dismiss</option>
                                  <option value="execute">execute</option>
                                </select>
                              </label>
                            )}

                            {decree.type === 'personnel' && decree.sub_action === 'appoint' && (
                              <label>
                                appoint.position
                                <input
                                  className="admin-input"
                                  value={decree.position}
                                  onChange={(event) => updateActiveChoice((choice) => ({
                                    ...choice,
                                    decrees: choice.decrees.map((item, idx) => (
                                      idx === decreeIndex ? { ...item, position: event.target.value } : item
                                    )),
                                  }))}
                                />
                              </label>
                            )}
                          </div>

                          <label>
                            parameters JSON（额外参数）
                            <textarea
                              className="admin-textarea code"
                              rows={4}
                              value={decree.parametersText}
                              onChange={(event) => updateActiveChoice((choice) => ({
                                ...choice,
                                decrees: choice.decrees.map((item, idx) => (
                                  idx === decreeIndex ? { ...item, parametersText: event.target.value } : item
                                )),
                              }))}
                            />
                          </label>
                        </div>
                      ))}
                    </div>

                    <div className="admin-subpanel">
                      <div className="admin-subpanel-head">
                        <strong>loyalty_effects</strong>
                        <button
                          type="button"
                          className="admin-button small"
                          onClick={() => updateActiveChoice((choice) => ({
                            ...choice,
                            loyaltyEffects: [...choice.loyaltyEffects, { name: '', value: 0 }],
                          }))}
                        >
                          添加
                        </button>
                      </div>
                      {activeChoice.loyaltyEffects.length === 0 && <div className="admin-hint">暂无 loyalty_effect</div>}
                      {activeChoice.loyaltyEffects.map((effect, effectIndex) => (
                        <div key={`loyalty-${effectIndex}`} className="admin-inline-grid">
                          <label>
                            minister
                            <input
                              className="admin-input"
                              list="admin-minister-name-list"
                              value={effect.name}
                              onChange={(event) => updateActiveChoice((choice) => ({
                                ...choice,
                                loyaltyEffects: choice.loyaltyEffects.map((item, idx) => (
                                  idx === effectIndex ? { ...item, name: event.target.value } : item
                                )),
                              }))}
                            />
                          </label>
                          <label>
                            delta
                            <input
                              className="admin-input"
                              type="number"
                              value={effect.value}
                              onChange={(event) => updateActiveChoice((choice) => ({
                                ...choice,
                                loyaltyEffects: choice.loyaltyEffects.map((item, idx) => (
                                  idx === effectIndex ? { ...item, value: toInt(event.target.value, item.value) } : item
                                )),
                              }))}
                            />
                          </label>
                          <button
                            type="button"
                            className="admin-button small danger"
                            onClick={() => updateActiveChoice((choice) => ({
                              ...choice,
                              loyaltyEffects: choice.loyaltyEffects.filter((_, idx) => idx !== effectIndex),
                            }))}
                          >
                            删除
                          </button>
                        </div>
                      ))}
                    </div>

                    <div className="admin-subpanel">
                      <div className="admin-subpanel-head">
                        <strong>state_effects</strong>
                        <button
                          type="button"
                          className="admin-button small"
                          onClick={() => updateActiveChoice((choice) => ({
                            ...choice,
                            stateEffects: [...choice.stateEffects, { key: '', value: 0 }],
                          }))}
                        >
                          添加
                        </button>
                      </div>
                      {activeChoice.stateEffects.length === 0 && <div className="admin-hint">暂无 state_effect</div>}
                      {activeChoice.stateEffects.map((effect, effectIndex) => (
                        <div key={`state-${effectIndex}`} className="admin-inline-grid">
                          <label>
                            key
                            <input
                              className="admin-input"
                              value={effect.key}
                              onChange={(event) => updateActiveChoice((choice) => ({
                                ...choice,
                                stateEffects: choice.stateEffects.map((item, idx) => (
                                  idx === effectIndex ? { ...item, key: event.target.value } : item
                                )),
                              }))}
                            />
                          </label>
                          <label>
                            delta
                            <input
                              className="admin-input"
                              type="number"
                              value={effect.value}
                              onChange={(event) => updateActiveChoice((choice) => ({
                                ...choice,
                                stateEffects: choice.stateEffects.map((item, idx) => (
                                  idx === effectIndex ? { ...item, value: toInt(event.target.value, item.value) } : item
                                )),
                              }))}
                            />
                          </label>
                          <button
                            type="button"
                            className="admin-button small danger"
                            onClick={() => updateActiveChoice((choice) => ({
                              ...choice,
                              stateEffects: choice.stateEffects.filter((_, idx) => idx !== effectIndex),
                            }))}
                          >
                            删除
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
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

      <datalist id="admin-minister-name-list">
        {ministerNames.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      <datalist id="admin-faction-name-list">
        {factionNames.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      <datalist id="admin-script-id-list">
        {scriptIds.map((scriptId) => (
          <option key={scriptId} value={scriptId} />
        ))}
      </datalist>
    </div>
  )
}
