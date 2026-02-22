import { useEffect } from 'react'

import AdminAuthGate from '../components/admin/AdminAuthGate'
import BackupManager from '../components/admin/BackupManager'
import EventManager from '../components/admin/EventManager'
import MinisterManager from '../components/admin/MinisterManager'
import PositionManager from '../components/admin/PositionManager'
import { useAdminStore } from '../stores/adminStore'
import '../styles/admin.css'

const TABS = [
  { key: 'ministers', label: '官员管理' },
  { key: 'events', label: '剧情事件' },
  { key: 'positions', label: '官职只读' },
  { key: 'backup', label: '备份导入导出' },
] as const

export default function AdminPage() {
  const {
    isAuthenticated,
    activeTab,
    setActiveTab,
    loadAll,
    initialized,
    loading,
    error,
    clearError,
    logout,
  } = useAdminStore()

  useEffect(() => {
    if (!isAuthenticated || initialized) return
    void loadAll()
  }, [isAuthenticated, initialized, loadAll])

  const onLogout = () => {
    sessionStorage.removeItem('admin_auth_password')
    logout()
  }

  return (
    <div className="admin-root">
      <AdminAuthGate>
        <header className="admin-header">
          <div>
            <h1>管理员管理页</h1>
            <p>管理官员、剧情事件与数据备份。</p>
          </div>
          <div className="admin-header-actions">
            <button className="admin-button" onClick={() => void loadAll()} disabled={loading}>
              刷新
            </button>
            <button className="admin-button danger" onClick={onLogout}>
              退出登录
            </button>
          </div>
        </header>

        <nav className="admin-nav">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              className={`admin-nav-item${activeTab === tab.key ? ' active' : ''}`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <main className="admin-main">
          {loading && !initialized && <div className="admin-auth-loading">正在加载管理数据…</div>}
          {!loading && activeTab === 'ministers' && <MinisterManager />}
          {!loading && activeTab === 'events' && <EventManager />}
          {!loading && activeTab === 'positions' && <PositionManager />}
          {!loading && activeTab === 'backup' && <BackupManager />}
        </main>

        {error && (
          <div className="admin-error-bar" onClick={clearError} title="点击关闭">
            {error}
          </div>
        )}
      </AdminAuthGate>
    </div>
  )
}

