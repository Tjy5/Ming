import DesktopIcon, { type DesktopIconName } from './DesktopIcon'

interface Props {
  icon: DesktopIconName
  title: string
  meta?: string
  id?: string
}

export default function SurfaceHeader({ icon, title, meta, id }: Props) {
  return (
    <header className="surface-header">
      <span className="surface-header-icon"><DesktopIcon name={icon} /></span>
      <strong id={id}>{title}</strong>
      {meta && <span className="surface-header-meta">{meta}</span>}
    </header>
  )
}
