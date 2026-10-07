import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'

/** Where a dock popover opens: centred over `x`, its bottom edge `bottom` px up from the viewport's. */
export interface Anchor {
  x: number
  bottom: number
}

/** A panel above the dock. Clicking elsewhere or pressing Escape closes it. */
export function Popover({
  anchor,
  width,
  label,
  className,
  onClose,
  children,
}: {
  anchor: Anchor
  width: number
  label: string
  className?: string
  onClose: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    ref.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const position = { '--x': `${anchor.x}px`, '--w': `${width}px`, bottom: anchor.bottom } as CSSProperties
  return (
    <>
      <div className="scrim" onClick={onClose} aria-hidden />
      <div
        ref={ref}
        className={className ? `popover ${className}` : 'popover'}
        role="dialog"
        aria-label={label}
        tabIndex={-1}
        style={position}
      >
        {children}
      </div>
    </>
  )
}
