import { useMemo } from 'react'

import { useAdminStore } from '../../stores/adminStore'

export default function PositionManager() {
  const { positions } = useAdminStore()

  const grouped = useMemo(() => {
    const map = new Map<string, typeof positions>()
    for (const position of positions) {
      const list = map.get(position.category) ?? []
      list.push(position)
      map.set(position.category, list)
    }
    for (const list of map.values()) {
      list.sort((a, b) => b.weight - a.weight || a.name.localeCompare(b.name))
    }
    return map
  }, [positions])

  return (
    <div className="admin-card">
      {Array.from(grouped.entries()).map(([category, items]) => (
        <section key={category} className="admin-event-group">
          <h3>{category}</h3>
          <table className="admin-table">
            <thead>
              <tr>
                <th>官职</th>
                <th>权重</th>
                <th>唯一</th>
                <th>别名</th>
                <th>现任持有者</th>
              </tr>
            </thead>
            <tbody>
              {items.map((position) => (
                <tr key={position.name}>
                  <td>{position.name}</td>
                  <td>{position.weight}</td>
                  <td>{position.unique ? '是' : '否'}</td>
                  <td>{position.aliases.join('、') || '-'}</td>
                  <td>{position.holders.join('、') || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  )
}

