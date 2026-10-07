import { useMemo, useRef, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { Icon, type IconName } from '../components/Icon'
import { frameRect, MIN_H, MIN_W, useDesktop, WindowContext, type Rect, type Size, type Snap, type Win } from './state'

const EDGES = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as const

function applyRect(el: HTMLElement, r: Rect) {
  el.style.left = `${r.x}px`
  el.style.top = `${r.y}px`
  el.style.width = `${r.w}px`
  el.style.height = `${r.h}px`
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), Math.max(min, max))

/** Phones get full-screen windows with no dragging. */
const isCompact = () => window.matchMedia('(max-width: 720px)').matches

/**
 * Follows one pointer from pointerdown to pointerup. Moves and resizes are written straight
 * to the element and committed to the desktop once, on release, so the page inside doesn't
 * re-render on every pixel.
 */
function track(event: ReactPointerEvent<HTMLElement>, onMove: (e: PointerEvent) => void, onEnd: () => void) {
  const handle = event.currentTarget
  handle.setPointerCapture(event.pointerId)
  const move = (e: PointerEvent) => onMove(e)
  const end = () => {
    handle.removeEventListener('pointermove', move)
    handle.removeEventListener('pointerup', end)
    handle.removeEventListener('pointercancel', end)
    onEnd()
  }
  handle.addEventListener('pointermove', move)
  handle.addEventListener('pointerup', end)
  handle.addEventListener('pointercancel', end)
}

export function WindowFrame({
  win,
  area,
  focused,
  title,
  icon,
  hue,
  fill,
  onSnapPreview,
  children,
}: {
  win: Win
  area: Size
  focused: boolean
  title: string
  icon: IconName
  hue: string
  fill?: boolean
  onSnapPreview: (snap: Snap | null) => void
  children: ReactNode
}) {
  const desktop = useDesktop()
  const ref = useRef<HTMLElement>(null)
  const rect = frameRect(win, area)
  const { key, minimized } = win
  const windowApi = useMemo(() => ({ key, minimized, close: () => desktop.close(key) }), [key, minimized, desktop])

  function startMove(event: ReactPointerEvent<HTMLElement>) {
    const el = ref.current
    if (!el || event.button !== 0 || isCompact()) return
    if ((event.target as HTMLElement).closest('button')) return
    const origin = el.parentElement!.getBoundingClientRect()
    const startX = event.clientX
    const startY = event.clientY
    let base = rect
    let current = rect
    let detached = win.snap === null
    let moved = false
    let snap: Snap | null = null

    track(
      event,
      (e) => {
        const dx = e.clientX - startX
        const dy = e.clientY - startY
        if (!moved && Math.hypot(dx, dy) < 4) return
        if (!moved) {
          moved = true
          el.dataset.moving = ''
        }
        if (!detached) {
          // Dragging a maximised window restores its size under the pointer.
          detached = true
          const w = Math.min(win.rect.w, area.w)
          const h = Math.min(win.rect.h, area.h)
          const grab = (startX - origin.left - base.x) / base.w
          base = { w, h, x: startX - origin.left - grab * w, y: base.y }
        }
        current = {
          ...base,
          x: clamp(base.x + dx, 120 - base.w, area.w - 120),
          y: clamp(base.y + dy, 0, area.h - 44),
        }
        applyRect(el, current)
        const px = e.clientX - origin.left
        const py = e.clientY - origin.top
        const next: Snap | null = py <= 2 ? 'full' : px <= 2 ? 'left' : px >= area.w - 3 ? 'right' : null
        if (next !== snap) {
          snap = next
          onSnapPreview(next)
        }
      },
      () => {
        if (!moved) return
        onSnapPreview(null)
        delete el.dataset.moving
        // React only writes styles that changed since its last render, so set the final
        // geometry here too: dropping a maximised window back on the top edge changes nothing
        // React can see. A snapped window remembers where it floated before.
        const floating = snap ? win.rect : current
        applyRect(el, frameRect({ rect: floating, snap }, area))
        desktop.place(key, floating, snap)
      },
    )
  }

  function startResize(event: ReactPointerEvent<HTMLElement>) {
    const el = ref.current
    if (!el || event.button !== 0) return
    event.stopPropagation()
    const dir = event.currentTarget.dataset.dir ?? ''
    const startX = event.clientX
    const startY = event.clientY
    const base = rect
    let current = rect
    el.dataset.moving = ''

    track(
      event,
      (e) => {
        const dx = e.clientX - startX
        const dy = e.clientY - startY
        let { x, y, w, h } = base
        if (dir.includes('e')) w = clamp(base.w + dx, MIN_W, area.w - base.x)
        if (dir.includes('s')) h = clamp(base.h + dy, MIN_H, area.h - base.y)
        if (dir.includes('w')) {
          w = clamp(base.w - dx, MIN_W, base.x + base.w)
          x = base.x + base.w - w
        }
        if (dir.includes('n')) {
          h = clamp(base.h - dy, MIN_H, base.y + base.h)
          y = base.y + base.h - h
        }
        current = { x, y, w, h }
        applyRect(el, current)
      },
      () => {
        delete el.dataset.moving
        desktop.place(key, current, null)
      },
    )
  }

  const titleId = `win-${key.replace(/[^a-z0-9-]/gi, '-')}`
  return (
    <section
      ref={ref}
      className={`window${focused ? ' focused' : ''}${minimized ? ' minimized' : ''}${win.snap ? ' snapped' : ''}`}
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h, zIndex: win.z * 2 }}
      aria-labelledby={titleId}
      inert={minimized}
      onPointerDownCapture={() => desktop.focus(key)}
    >
      <header
        className="titlebar"
        onPointerDown={startMove}
        onDoubleClick={(e) => {
          if (!(e.target as HTMLElement).closest('button')) desktop.toggleMaximize(key)
        }}
      >
        <div className="lights">
          <button type="button" className="light close" aria-label="Close" onClick={() => desktop.close(key)}>
            <Icon name="close" size={9} />
          </button>
          <button type="button" className="light min" aria-label="Minimize" onClick={() => desktop.minimize(key)}>
            <Icon name="minus" size={9} />
          </button>
          <button
            type="button"
            className="light max"
            aria-label={win.snap ? 'Restore' : 'Maximize'}
            onClick={() => desktop.toggleMaximize(key)}
          >
            <Icon name="maximize" size={9} />
          </button>
        </div>
        <h2 className="window-title" id={titleId}>
          <span className={`hue-${hue} window-icon`}>
            <Icon name={icon} size={15} />
          </span>
          <span className="window-title-text">{title}</span>
        </h2>
        <div />
      </header>
      <div className={`window-body${fill ? ' fill' : ''}`}>
        <WindowContext.Provider value={windowApi}>{children}</WindowContext.Provider>
      </div>
      {!win.snap &&
        EDGES.map((dir) => (
          <div key={dir} className={`rz rz-${dir}`} data-dir={dir} onPointerDown={startResize} aria-hidden />
        ))}
    </section>
  )
}

