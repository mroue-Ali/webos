import type { MouseEvent, ReactNode } from 'react'
import { targetPath, type Target } from './apps'
import { useDesktop } from './state'

/**
 * A link that opens a window. It's a real link, so middle-click and "open in new tab" load
 * the same window in a fresh tab.
 */
export function AppLink({
  to,
  className,
  title,
  children,
}: {
  to: Target
  className?: string
  title?: string
  children: ReactNode
}) {
  const desktop = useDesktop()
  function onClick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    desktop.open(to)
  }
  return (
    <a href={targetPath(to)} className={className} title={title} onClick={onClick}>
      {children}
    </a>
  )
}
