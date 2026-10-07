import { useQueryClient } from '@tanstack/react-query'
import { memo, useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { keys, useOverview } from '../api/queries'
import type { Project } from '../api/types'
import { collectNotices, projectHue } from '../lib/status'
import { useEventSource } from '../lib/useEventSource'
import { AuditPage } from '../pages/AuditPage'
import { LogsPage } from '../pages/LogsPage'
import { NewSitePage } from '../pages/NewSitePage'
import { ProjectPage } from '../pages/ProjectPage'
import { ProjectsPage } from '../pages/ProjectsPage'
import { ServerPage } from '../pages/ServerPage'
import { APPS, targetPath, type Target } from './apps'
import { DesktopIcons } from './DesktopIcons'
import { Dock, type Look, type PanelKind } from './Dock'
import { Launcher } from './Launcher'
import { Notifications } from './Notifications'
import type { Anchor } from './Popover'
import { Spotlight } from './Spotlight'
import {
  DesktopContext,
  estimateArea,
  frameRect,
  initialDesktop,
  LiveContext,
  reducer,
  saveDesktop,
  topWindow,
  type DesktopApi,
  type Size,
  type Snap,
} from './state'
import { Widgets } from './Widgets'
import { WindowFrame } from './Window'

type Panel = { kind: PanelKind; anchor: Anchor } | { kind: 'spotlight' } | null

/** Refetch the overview shortly after Docker reports a container event. */
function useLiveOverview() {
  const client = useQueryClient()
  const timer = useRef<number | undefined>(undefined)
  return useEventSource('/api/events', ['container'], () => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(
      () => void client.invalidateQueries({ queryKey: keys.overview }),
      400,
    )
  })
}

function describe(target: Target, projects: Map<string, Project>): Look {
  const app = APPS[target.app]
  switch (target.app) {
    case 'project':
      return { title: projects.get(target.slug)?.display_name ?? target.slug, icon: 'globe', hue: projectHue(target.slug) }
    case 'logs':
      return {
        title: `Logs · ${projects.get(target.slug)?.display_name ?? target.slug}`,
        icon: 'logs',
        hue: projectHue(target.slug),
      }
    case 'new':
      return { title: target.site ? `New site · ${target.site}` : app.title, icon: app.icon, hue: app.hue }
    default:
      return { title: app.title, icon: app.icon, hue: app.hue }
  }
}

/** A window's page. Memoised on the target, so moving or focusing the window skips it. */
const AppContent = memo(function AppContent({ target }: { target: Target }) {
  switch (target.app) {
    case 'projects':
      return <ProjectsPage />
    case 'server':
      return <ServerPage />
    case 'audit':
      return <AuditPage />
    case 'new':
      return <NewSitePage site={target.site} />
    case 'project':
      return <ProjectPage slug={target.slug} />
    case 'logs':
      return <LogsPage slug={target.slug} container={target.container} />
  }
})

export function Desktop({ username }: { username: string }) {
  const [state, dispatch] = useReducer(reducer, undefined, initialDesktop)
  const areaRef = useRef<HTMLDivElement>(null)
  const [area, setArea] = useState<Size>(estimateArea)
  const [panel, setPanel] = useState<Panel>(null)
  const [snapPreview, setSnapPreview] = useState<{ snap: Snap; z: number } | null>(null)
  const overview = useOverview()
  const live = useLiveOverview()

  useEffect(() => {
    const el = areaRef.current
    if (!el) return
    const observer = new ResizeObserver(() =>
      setArea((a) => (a.w === el.clientWidth && a.h === el.clientHeight ? a : { w: el.clientWidth, h: el.clientHeight })),
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const api = useMemo<DesktopApi>(() => {
    const measure = () => {
      const el = areaRef.current
      return el ? { w: el.clientWidth, h: el.clientHeight } : estimateArea()
    }
    return {
      open: (target) => dispatch({ type: 'open', target, area: measure() }),
      close: (key) => dispatch({ type: 'close', key }),
      focus: (key) => dispatch({ type: 'focus', key }),
      minimize: (key) => dispatch({ type: 'minimize', key }),
      toggleMaximize: (key) => dispatch({ type: 'toggleMax', key }),
      place: (key, rect, snap) => dispatch({ type: 'place', key, rect, snap }),
    }
  }, [])

  useEffect(() => saveDesktop(state), [state])

  const projects = useMemo(
    () => new Map((overview.data?.projects ?? []).map((p) => [p.slug, p])),
    [overview.data],
  )
  const look = useCallback((target: Target) => describe(target, projects), [projects])
  const top = topWindow(state.windows)

  // The address bar and the tab title follow the window in front.
  const topTarget = top?.target
  const topTitle = topTarget ? look(topTarget).title : null
  useEffect(() => {
    const path = topTarget ? targetPath(topTarget) : '/'
    if (window.location.pathname + window.location.search !== path) window.history.replaceState(null, '', path)
    document.title = topTitle ? `${topTitle} · webos` : 'webos'
  }, [topTarget, topTitle])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPanel((p) => (p?.kind === 'spotlight' ? null : { kind: 'spotlight' }))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const notices = useMemo(() => collectNotices(overview.data), [overview.data])
  const alerts = notices.filter((n) => n.tone === 'bad' || n.tone === 'warn').length
  const closePanel = useCallback(() => setPanel(null), [])
  const openSearch = useCallback(() => setPanel({ kind: 'spotlight' }), [])

  return (
    <DesktopContext.Provider value={api}>
      <LiveContext.Provider value={live}>
        <div className="desktop">
          <div className="desk-area" ref={areaRef}>
            <div className="desk-home">
              <DesktopIcons projects={overview.data?.projects ?? []} />
              <Widgets live={live} />
            </div>
            <div className="window-layer">
              {state.windows.map((w) => {
                const { title, icon, hue } = look(w.target)
                return (
                  <WindowFrame
                    key={w.key}
                    win={w}
                    area={area}
                    focused={w.key === top?.key}
                    title={title}
                    icon={icon}
                    hue={hue}
                    fill={APPS[w.target.app].fill}
                    onSnapPreview={(snap) => setSnapPreview(snap ? { snap, z: w.z } : null)}
                  >
                    <AppContent target={w.target} />
                  </WindowFrame>
                )
              })}
              {snapPreview && <SnapPreview snap={snapPreview.snap} z={snapPreview.z} area={area} />}
            </div>
          </div>

          <Dock
            windows={state.windows}
            focusedKey={top?.key ?? null}
            describe={look}
            username={username}
            live={live}
            alerts={alerts}
            panel={panel && panel.kind !== 'spotlight' ? panel.kind : null}
            onPanel={(kind, anchor) => setPanel((p) => (p?.kind === kind ? null : { kind, anchor }))}
            onSearch={openSearch}
          />

          {panel?.kind === 'launcher' && (
            <Launcher anchor={panel.anchor} username={username} onClose={closePanel} onSearch={openSearch} />
          )}
          {panel?.kind === 'notifications' && (
            <Notifications anchor={panel.anchor} notices={notices} live={live} onClose={closePanel} />
          )}
          {panel?.kind === 'spotlight' && <Spotlight onClose={closePanel} />}
        </div>
      </LiveContext.Provider>
    </DesktopContext.Provider>
  )
}

/** Where a window dragged to a screen edge will land, drawn just behind it. */
function SnapPreview({ snap, z, area }: { snap: Snap; z: number; area: Size }) {
  const r = frameRect({ rect: { x: 0, y: 0, w: area.w, h: area.h }, snap }, area)
  return <div className="snap-preview" style={{ left: r.x, top: r.y, width: r.w, height: r.h, zIndex: z * 2 - 1 }} />
}
