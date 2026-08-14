import type { ReactNode } from 'react'

export type DesktopIconName =
  | 'alert'
  | 'archive'
  | 'book'
  | 'branch'
  | 'chat'
  | 'chevron'
  | 'clock'
  | 'coins'
  | 'dice'
  | 'document'
  | 'flag'
  | 'folder'
  | 'heart'
  | 'map'
  | 'minus'
  | 'percent'
  | 'plus'
  | 'refresh'
  | 'save'
  | 'settings'
  | 'shield'
  | 'users'

interface Props {
  name: DesktopIconName
  size?: number
}

const PATHS: Record<DesktopIconName, ReactNode> = {
  alert: <><path d="M12 3 2.8 20h18.4z" /><path d="M12 9v5M12 17.5v.5" /></>,
  archive: <><path d="M4 7h16v13H4z" /><path d="M3 3h18v4H3zM9 11h6" /></>,
  book: <><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H11v18H6.5A2.5 2.5 0 0 0 4 22z" /><path d="M20 4.5A2.5 2.5 0 0 0 17.5 2H13v18h4.5A2.5 2.5 0 0 1 20 22z" /></>,
  branch: <><circle cx="6" cy="5" r="2" /><circle cx="18" cy="6" r="2" /><circle cx="6" cy="19" r="2" /><path d="M6 7v10M8 8c5 0 4-2 8-2" /></>,
  chat: <path d="M4 4h16v12H9l-5 4z" />,
  chevron: <path d="m9 6 6 6-6 6" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  coins: <><ellipse cx="9" cy="7" rx="5" ry="3" /><path d="M4 7v4c0 1.7 2.2 3 5 3 1.1 0 2.2-.2 3-.6M4 11v4c0 1.7 2.2 3 5 3" /><ellipse cx="15" cy="14" rx="5" ry="3" /><path d="M10 14v4c0 1.7 2.2 3 5 3s5-1.3 5-3v-4" /></>,
  dice: <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8" cy="8" r="1" fill="currentColor" stroke="none" /><circle cx="16" cy="8" r="1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="8" cy="16" r="1" fill="currentColor" stroke="none" /><circle cx="16" cy="16" r="1" fill="currentColor" stroke="none" /></>,
  document: <><path d="M6 2h9l4 4v16H6z" /><path d="M15 2v5h4M9 12h6M9 16h6" /></>,
  flag: <><path d="M5 22V3" /><path d="M5 4h12l-2 4 2 4H5" /></>,
  folder: <path d="M3 6h7l2 2h9l-2 11H5z" />,
  heart: <path d="M20.8 5.8c-1.7-1.8-4.5-1.8-6.2 0L12 8.5 9.4 5.8a4.3 4.3 0 0 0-6.2 6L12 21l8.8-9.2a4.3 4.3 0 0 0 0-6z" />,
  map: <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z" /><path d="M9 3v15M15 6v15" /></>,
  minus: <path d="M5 12h14" />,
  percent: <><circle cx="7" cy="7" r="2.5" /><circle cx="17" cy="17" r="2.5" /><path d="m19 5-14 14" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  refresh: <><path d="M20 7v5h-5" /><path d="M19 12a7 7 0 1 0-2 5" /></>,
  save: <><path d="M4 3h14l2 2v16H4z" /><path d="M8 3v6h8V3M8 21v-7h8v7" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" /></>,
  shield: <path d="M12 2 20 5v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5z" />,
  users: <><circle cx="9" cy="8" r="3" /><circle cx="17" cy="9" r="2" /><path d="M3 20c0-4 2-7 6-7s6 3 6 7M15 14c3 0 5 2 5 5" /></>,
}

export default function DesktopIcon({ name, size = 15 }: Props) {
  return (
    <svg
      className="desktop-icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  )
}
