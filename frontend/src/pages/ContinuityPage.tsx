// World continuity console: branches, immutable versions, bookmarks, retention, and activities.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import {
  worldsApi,
  type Activity,
  type SettlementFacts,
  type WorldBookmarkRef,
  type WorldBranchRef,
  type WorldRetentionResponse,
  type WorldVersionRef,
} from '../api/worlds'
import { useStore } from '../hooks/store'
import type { GameState } from '../types/game'
import './ContinuityPage.css'

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function statusLabel(status: Activity['status']): string {
  const labels: Record<Activity['status'], string> = {
    in_progress: '进行中',
    awaiting_player_decision: '等待决策',
    paused: '已暂停',
    cancelled: '已取消',
    failed: '失败',
    completed: '已完成',
  }
  return labels[status]
}

export default function ContinuityPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { state, setState } = useStore()
  const [branches, setBranches] = useState<WorldBranchRef[]>([])
  const [versions, setVersions] = useState<WorldVersionRef[]>([])
  const [bookmarks, setBookmarks] = useState<WorldBookmarkRef[]>([])
  const [retention, setRetention] = useState<WorldRetentionResponse | null>(null)
  const [selectedActivity, setSelectedActivity] = useState<Activity | null>(null)
  const [settlement, setSettlement] = useState<SettlementFacts | null>(null)
  const [selectedBranchId, setSelectedBranchId] = useState('')
  const [selectedVersionId, setSelectedVersionId] = useState('')
  const [bookmarkName, setBookmarkName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [collectingRetention, setCollectingRetention] = useState(false)

  const identity = state?.world_metadata
  const gameId = identity?.game_id ?? searchParams.get('game_id') ?? ''
  const currentBranchId = selectedBranchId || identity?.branch_id || ''
  const currentVersionId = selectedVersionId || identity?.version_id || ''
  const activities = state?.activities ?? []

  const loadGraph = useCallback(async (branchId: string = currentBranchId) => {
    if (!gameId) return
    setLoading(true)
    setError(null)
    try {
      const branchResponse = await worldsApi.listBranches(gameId)
      const nextBranches = branchResponse.branches ?? []
      setBranches(nextBranches)
      const branch = branchId || nextBranches.find((item) => item.status === 'active')?.branch_id || nextBranches[0]?.branch_id || ''
      if (branch) setSelectedBranchId(branch)
      const [versionResponse, bookmarkResponse, retentionResponse] = await Promise.all([
        branch ? worldsApi.listVersions(gameId, branch) : Promise.resolve({ versions: [] }),
        worldsApi.listBookmarks(gameId, branch || undefined),
        worldsApi.retentionReport(gameId, branch || undefined),
      ])
      const nextVersions = versionResponse.versions ?? []
      setVersions(nextVersions)
      setBookmarks(bookmarkResponse.bookmarks ?? [])
      setRetention(retentionResponse)
      setSelectedVersionId((current) => current || nextVersions[0]?.version_id || '')
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.body.message : '世界线数据加载失败'
      setError(message)
      console.warn('[continuity] failed to load world graph', cause)
    } finally {
      setLoading(false)
    }
  }, [currentBranchId, gameId])

  useEffect(() => {
    if (state || gameId) return
    api.getState()
      .then((next) => setState(next))
      .catch((cause) => {
        setError(cause instanceof ApiError ? cause.body.message : '无法读取当前世界')
        console.warn('[continuity] failed to load state', cause)
      })
  }, [gameId, setState, state])

  useEffect(() => {
    if (gameId) void loadGraph()
  }, [gameId, loadGraph])

  const activeBranch = useMemo(
    () => branches.find((branch) => branch.branch_id === currentBranchId) ?? null,
    [branches, currentBranchId],
  )

  async function switchBranch(branchId: string) {
    if (!gameId || branchId === currentBranchId) return
    setLoading(true)
    setError(null)
    try {
      const response = await worldsApi.switchBranch(gameId, branchId)
      setState(response.state as unknown as GameState)
      setSelectedBranchId(response.branch.branch_id)
      setSelectedVersionId(response.version.version_id)
      setNotice('已切换世界线；原分支仍保留。')
      await loadGraph(response.branch.branch_id)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.body.message : '切换世界线失败')
      console.warn('[continuity] failed to switch branch', cause)
    } finally {
      setLoading(false)
    }
  }

  async function forkVersion(versionId: string) {
    if (!gameId) return
    setLoading(true)
    setError(null)
    try {
      const response = await worldsApi.forkVersion(gameId, versionId)
      setState(response.state as unknown as GameState)
      setSelectedBranchId(response.branch.branch_id)
      setSelectedVersionId(response.version.version_id)
      setNotice('已从历史版本派生新世界线。')
      await loadGraph(response.branch.branch_id)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.body.message : '派生世界线失败')
      console.warn('[continuity] failed to fork version', cause)
    } finally {
      setLoading(false)
    }
  }

  async function createBookmark() {
    const name = bookmarkName.trim()
    if (!gameId || !currentBranchId || !currentVersionId || !name) return
    setLoading(true)
    try {
      await worldsApi.createBookmark(gameId, {
        game_id: gameId,
        branch_id: currentBranchId,
        version_id: currentVersionId,
        name,
      })
      setBookmarkName('')
      setNotice('书签已保护该版本。')
      await loadGraph(currentBranchId)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.body.message : '创建书签失败')
      console.warn('[continuity] failed to create bookmark', cause)
    } finally {
      setLoading(false)
    }
  }

  async function deleteBookmark(bookmark: WorldBookmarkRef) {
    if (!gameId) return
    setLoading(true)
    try {
      await worldsApi.deleteBookmark(gameId, bookmark.bookmark_id)
      setBookmarks((items) => items.filter((item) => item.bookmark_id !== bookmark.bookmark_id))
      setNotice('书签已删除；版本仍受其他引用规则保护。')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.body.message : '删除书签失败')
      console.warn('[continuity] failed to delete bookmark', cause)
    } finally {
      setLoading(false)
    }
  }

  async function continueActivity(activity: Activity) {
    if (!gameId || !currentBranchId || !currentVersionId) return
    setLoading(true)
    try {
      const response = await worldsApi.continueActivity(activity.activity_id, {
        game_id: gameId,
        branch_id: currentBranchId,
        expected_parent_version_id: currentVersionId,
        max_checkpoints: 4,
      })
      setState(response.state as unknown as GameState)
      setSelectedActivity(response.activity)
      setNotice(response.processing ? '活动已推进至下一检查点。' : '活动已完成处理。')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.body.message : '推进活动失败')
      console.warn('[continuity] failed to continue activity', cause)
    } finally {
      setLoading(false)
    }
  }

  async function showSettlement(settlementId: string) {
    try {
      setSettlement(await worldsApi.getSettlement(settlementId))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.body.message : '结算详情读取失败')
      console.warn('[continuity] failed to load settlement', cause)
    }
  }

  async function collectRetention() {
    if (!gameId || !currentBranchId || collectingRetention) return
    setCollectingRetention(true)
    setError(null)
    try {
      const result = await worldsApi.collectRetention(gameId, {
        branch_id: currentBranchId,
        recent_limit: 100,
        enabled: true,
      })
      const deletedCount = result.deleted_version_ids?.length ?? 0
      setNotice(deletedCount
        ? `已完成事务清理，删除 ${deletedCount} 个版本。`
        : '事务清理已完成；当前没有可安全删除的版本。')
      await loadGraph(currentBranchId)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.body.message : '执行保留清理失败')
      console.warn('[continuity] failed to collect retention', cause)
    } finally {
      setCollectingRetention(false)
    }
  }

  if (!gameId) {
    return (
      <main className="continuity-page">
        <header className="continuity-header">
          <button className="continuity-back" onClick={() => navigate('/')}>返回游戏</button>
          <h1>世界连续性</h1>
        </header>
        <section className="continuity-empty" role="status">
          当前存档尚未提供版本图标识。请从已启用世界版本的游戏局进入此页。
        </section>
      </main>
    )
  }

  return (
    <main className="continuity-page">
      <header className="continuity-header">
        <div>
          <button className="continuity-back" onClick={() => navigate('/')}>返回游戏</button>
          <h1>世界连续性</h1>
          <p className="continuity-subtitle">不可变版本、分支书签与进行中活动</p>
        </div>
        <div className="continuity-identity">
          <span>世界 {gameId.slice(0, 8)}</span>
          <span>当前分支 {currentBranchId ? currentBranchId.slice(0, 8) : '—'}</span>
          <button className="continuity-refresh" onClick={() => void loadGraph()} disabled={loading}>刷新</button>
        </div>
      </header>

      {error && <div className="continuity-alert error" role="alert">{error}</div>}
      {notice && <div className="continuity-alert" role="status">{notice}</div>}
      {loading && <div className="continuity-alert" role="status" aria-label="正在同步世界连续性">正在同步世界连续性……</div>}

      <section className="continuity-grid">
        <article className="continuity-card continuity-branches">
          <div className="card-heading"><h2>世界分支</h2><span>{branches.length} 条</span></div>
          <div className="branch-list">
            {branches.map((branch) => (
              <div className={`branch-row${branch.branch_id === currentBranchId ? ' selected' : ''}`} key={branch.branch_id}>
                <div>
                  <strong>{branch.branch_id.slice(0, 8)}</strong>
                  <small>{branch.status === 'active' ? '可继续' : '已归档'} · head {branch.head_version_id.slice(0, 8)}</small>
                </div>
                <div className="row-actions">
                  {branch.branch_id !== currentBranchId && <button onClick={() => void switchBranch(branch.branch_id)}>切换</button>}
                  <button onClick={() => { setSelectedBranchId(branch.branch_id); setSelectedVersionId(branch.head_version_id); void loadGraph(branch.branch_id) }}>查看</button>
                </div>
              </div>
            ))}
            {!branches.length && <p className="muted">暂无分支记录。</p>}
          </div>
          {activeBranch && <p className="muted branch-hint">分支创建于 {formatDate(activeBranch.created_at)}。加载历史版本会派生新分支，不覆盖原线。</p>}
        </article>

        <article className="continuity-card continuity-versions">
          <div className="card-heading"><h2>版本链</h2><span>{versions.length} 个节点</span></div>
          <div className="version-list">
            {versions.map((version) => (
              <button
                className={`version-row${version.version_id === currentVersionId ? ' selected' : ''}`}
                key={version.version_id}
                onClick={() => setSelectedVersionId(version.version_id)}
              >
                <span className="version-dot" />
                <span className="version-copy">
                  <strong>{version.version_id.slice(0, 8)}</strong>
                  <small>{formatDate(version.created_at)} · {version.settlement_id ? `结算 ${version.settlement_id.slice(0, 8)}` : '世界根'}</small>
                </span>
                {version.protected && <span className="protected-tag">保护</span>}
              </button>
            ))}
            {!versions.length && <p className="muted">该分支暂无版本。</p>}
          </div>
          {currentVersionId && <button className="primary-action" onClick={() => void forkVersion(currentVersionId)}>从此版本开新线</button>}
        </article>

        <article className="continuity-card continuity-bookmarks">
          <div className="card-heading"><h2>书签</h2><span>永久保护</span></div>
          <div className="bookmark-create">
            <input value={bookmarkName} onChange={(event) => setBookmarkName(event.target.value)} placeholder="例如：权力真空后的朝议" aria-label="书签名称" />
            <button className="primary-action" onClick={() => void createBookmark()} disabled={!bookmarkName.trim() || !currentVersionId}>保护当前版本</button>
          </div>
          <div className="bookmark-list">
            {bookmarks.map((bookmark) => (
              <div className="bookmark-row" key={bookmark.bookmark_id}>
                <div><strong>{bookmark.name}</strong><small>{bookmark.version_id.slice(0, 8)} · {formatDate(bookmark.created_at)}</small></div>
                <button onClick={() => void forkVersion(bookmark.version_id)}>从书签开线</button>
                <button className="danger-action" onClick={() => void deleteBookmark(bookmark)}>删除</button>
              </div>
            ))}
            {!bookmarks.length && <p className="muted">还没有手动书签。</p>}
          </div>
        </article>

        <article className="continuity-card continuity-retention">
          <div className="card-heading"><h2>保留计划</h2><span>事务清理</span></div>
          {retention ? (
            <div className="retention-summary">
              <div><strong>{retention.protected_version_ids?.length ?? 0}</strong><span>保护版本</span></div>
              <div><strong>{retention.monthly_recovery_version_ids?.length ?? 0}</strong><span>月度恢复点</span></div>
              <div><strong>{retention.delete_version_ids?.length ?? 0}</strong><span>可清理节点</span></div>
            </div>
          ) : <p className="muted">暂无保留报告。</p>}
          <button className="primary-action" onClick={() => void collectRetention()} disabled={collectingRetention || !currentBranchId}>
            {collectingRetention ? '清理中……' : '执行事务清理'}
          </button>
          <p className="muted">共享祖先只保存一份；分支根、书签、重大事件和终局前版本始终受保护。</p>
        </article>

        <article className="continuity-card continuity-activities">
          <div className="card-heading"><h2>进行中活动</h2><span>{activities.length} 项</span></div>
          {activities.map((activity) => (
            <div className="activity-row" key={activity.activity_id}>
              <div className="activity-main">
                <strong>{activity.intent}</strong>
                <small>{activity.kind} · {statusLabel(activity.status)} · 已耗时 {activity.elapsed_hours} 小时 / 剩余 {activity.remaining_hours} 小时</small>
                {activity.target_summary && <small>目标：{activity.target_summary}</small>}
              </div>
              <div className="row-actions">
                <button onClick={() => setSelectedActivity(activity)}>详情</button>
                {activity.status === 'in_progress' && <button className="primary-action" onClick={() => void continueActivity(activity)}>推进检查点</button>}
              </div>
            </div>
          ))}
          {!activities.length && <p className="muted">当前没有需要检查的长期活动。</p>}
        </article>
      </section>

      {selectedActivity && (
        <section className="continuity-detail" aria-live="polite">
          <div className="card-heading"><h2>活动详情</h2><button onClick={() => setSelectedActivity(null)}>关闭</button></div>
          <p>{selectedActivity.intent} · {statusLabel(selectedActivity.status)}</p>
          <p className="muted">开始于 {selectedActivity.started_at.absolute_hour} 时，计划 {selectedActivity.planned_elapsed_hours} 小时；检查点 {selectedActivity.checkpoint_sequence}。</p>
          {selectedActivity.checkpoints?.map((checkpoint) => (
            <div className="checkpoint-row" key={checkpoint.checkpoint_id}>
              <span>#{checkpoint.sequence} {checkpoint.status === 'completed' ? '已完成' : '待处理'}</span>
              {checkpoint.settlement_id && <button onClick={() => void showSettlement(checkpoint.settlement_id!)}>查看结算</button>}
            </div>
          ))}
        </section>
      )}

      {settlement && (
        <section className="continuity-detail" aria-live="polite">
          <div className="card-heading"><h2>结算事实</h2><button onClick={() => setSettlement(null)}>关闭</button></div>
          <p>结算 {settlement.settlement_id.slice(0, 12)} · 结果版本 {settlement.result_version_id?.slice(0, 12) ?? '—'}</p>
          <p>{settlement.result_tier} · 即时变化 {settlement.immediate_changes?.length ?? 0} 项 · 长期风险 {settlement.long_term_risks?.length ?? 0} 项</p>
        </section>
      )}
    </main>
  )
}
