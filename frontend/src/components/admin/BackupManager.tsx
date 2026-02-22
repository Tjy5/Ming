import { useMemo, useState } from 'react'
import type { ChangeEvent } from 'react'

import type { AdminExportBundle, AdminImportValidationResult } from '../../stores/adminStore'
import { useAdminStore } from '../../stores/adminStore'

export default function BackupManager() {
  const { exportData, importData, validateImportData } = useAdminStore()
  const [selectedBundle, setSelectedBundle] = useState<AdminExportBundle | null>(null)
  const [validationResult, setValidationResult] = useState<AdminImportValidationResult | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [working, setWorking] = useState(false)

  const preview = useMemo(() => {
    if (!selectedBundle) return null
    return {
      ministers: selectedBundle.ministers?.length ?? 0,
      events: selectedBundle.events?.length ?? 0,
      hasPositions: !!selectedBundle.positions,
      exportedAt: selectedBundle.meta?.exported_at as string | undefined,
    }
  }, [selectedBundle])

  const onExport = async () => {
    setWorking(true)
    setMessage(null)
    setError(null)
    try {
      const bundle = await exportData()
      const filename = `ming-admin-backup-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      anchor.click()
      URL.revokeObjectURL(url)
      setMessage(`已导出 ${filename}`)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '导出失败')
    } finally {
      setWorking(false)
    }
  }

  const onSelectFile = async (event: ChangeEvent<HTMLInputElement>) => {
    setMessage(null)
    setError(null)
    setValidationResult(null)
    const file = event.target.files?.[0]
    if (!file) {
      setSelectedBundle(null)
      return
    }

    setWorking(true)
    try {
      const text = await file.text()
      const parsed = JSON.parse(text) as AdminExportBundle
      if (!parsed || !Array.isArray(parsed.ministers) || !Array.isArray(parsed.events)) {
        throw new Error('文件不包含有效的 ministers/events 结构')
      }
      const validated = await validateImportData(parsed)
      setSelectedBundle(parsed)
      setValidationResult(validated)
      setMessage(`导入预校验通过：ministers ${validated.ministers_count}，events ${validated.events_count}`)
    } catch (parseError) {
      setSelectedBundle(null)
      setValidationResult(null)
      setError(parseError instanceof Error ? parseError.message : '解析导入文件失败')
    } finally {
      setWorking(false)
    }
  }

  const onImport = async () => {
    if (!selectedBundle || !validationResult) {
      setError('请先选择并通过预校验的导入文件')
      return
    }
    if (!window.confirm('确认导入该备份？当前数据将被替换。')) return
    setWorking(true)
    setMessage(null)
    setError(null)
    try {
      await importData(selectedBundle)
      setMessage('导入成功，管理数据已刷新。')
      setSelectedBundle(null)
      setValidationResult(null)
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : '导入失败')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="admin-card">
      <section className="admin-backup-section">
        <h3>导出备份</h3>
        <p>导出 ministers + events + positions 只读快照。</p>
        <button className="admin-button primary" onClick={() => void onExport()} disabled={working}>
          {working ? '处理中…' : '导出 JSON'}
        </button>
      </section>

      <section className="admin-backup-section">
        <h3>导入备份</h3>
        <input
          className="admin-input"
          type="file"
          accept="application/json,.json"
          onChange={(event) => void onSelectFile(event)}
          disabled={working}
        />

        {preview && (
          <div className="admin-import-preview">
            <div>导入预览</div>
            <div>ministers: {preview.ministers}</div>
            <div>events: {preview.events}</div>
            <div>positions snapshot: {preview.hasPositions ? '是' : '否'}</div>
            <div>exported_at: {preview.exportedAt ?? '-'}</div>
            <div>validated: {validationResult ? '是' : '否'}</div>
          </div>
        )}

        <button
          className="admin-button"
          onClick={() => void onImport()}
          disabled={working || !selectedBundle || !validationResult}
        >
          {working ? '处理中…' : '确认导入'}
        </button>
      </section>

      {message && <div className="admin-success">{message}</div>}
      {error && <div className="admin-error">{error}</div>}
    </div>
  )
}
