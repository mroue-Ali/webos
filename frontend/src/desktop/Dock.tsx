import { useSyncExternalStore, type MouseEvent } from 'react'
import { useServer } from '../api/queries'
import { Icon, type IconName } from '../components/Icon'
import { formatPercent } from '../lib/format'
import { usageTone } from '../lib/status'
import { toggleTheme, useTheme } from '../lib/theme'
import type { StreamStatus } from '../lib/useEventSource'
import { clockDate, clockTime, useNow } from '../lib/useNow'
import type { Target } from './apps'
import type { Anchor } from './Popover'
import { useDesktop, type Win } from './state'

export type PanelKind = 'launcher' | 'notifications'

export interface Look {
  title: string
  icon: IconName
  hue: string
}

function anchorOf(event: MouseEvent<HTMLElement>): Anchor {
  const r = event.currentTarget.getBoundingClientRect()
  return { x: r.left + r.width / 2, bottom: window.innerHeight - r.top + 10 }
}

function subscribeFullscreen(listener: () => void) {
  document.addEventListener('fullscreenchange', listener)
  return () => document.removeEventListener('fullscreenchange', listener)
}

function toggleFullscreen() {
  if (document.fullscreenElement) void document.exitFullscreen()
  else void document.documentElement.requestFullscreen().catch(() => {})
}

export function Dock({
  windows,
  focusedKey,
  describe,
  username,
  live,
  alerts,
  panel,
  onPanel,
  onSearch,
}: {
  windows: Win[]
  focusedKey: string | null
  describe: (target: Target) => Look
  username: string
  live: StreamStatus
  alerts: number
  panel: PanelKind | null
  onPanel: (kind: PanelKind, anchor: Anchor) => void
  onSearch: () => void
}) {
  const desktop = useDesktop()
  const theme = useTheme()
  const fullscreen = useSyncExternalStore(subscribeFullscreen, () => document.fullscreenElement !== null)

  return (
    <div className="dock-wrap">
      <nav className="dock" aria-label="Dock">
        <button
          type="button"
          className={`dock-btn${panel === 'launcher' ? ' active' : ''}`}
          data-tip="Apps"
          aria-label="Apps"
          aria-expanded={panel === 'launcher'}
          onClick={(e) => onPanel('launcher', anchorOf(e))}
        >
          <Icon name="grid" size={21} />
        </button>

        {windows.length > 0 && <span className="dock-sep" aria-hidden />}
        <div className="dock-apps">
          {windows.map((w) => {
            const look = describe(w.target)
            const isFocused = w.key === focusedKey
            return (
              <button
                key={w.key}
                type="button"
                className={`dock-btn dock-app${isFocused ? ' focused' : ''}${w.minimized ? ' minimized' : ''}`}
                data-tip={look.title}
                aria-label={w.minimized ? `${look.title} (minimized)` : look.title}
                aria-pressed={isFocused}
                onClick={() => (isFocused ? desktop.minimize(w.key) : desktop.focus(w.key))}
              >
                <span className={`art small hue-${look.hue}`}>
                  <Icon name={look.icon} size={17} />
                </span>
              </button>
            )
          })}
        </div>

        <span className="dock-sep" aria-hidden />
        <span className="dock-user" title={live === 'live' ? 'Live updates on' : 'Live updates reconnecting'}>
          <span className={`live-dot ${live}`} aria-hidden />
          {username}
        </span>
        <DockStats onOpen={() => desktop.open({ app: 'server' })} />
        <button
          type="button"
          className={`dock-btn${panel === 'notifications' ? ' active' : ''}`}
          data-tip="Notifications"
          aria-label={alerts ? `Notifications, ${alerts} need attention` : 'Notifications'}
          aria-expanded={panel === 'notifications'}
          onClick={(e) => onPanel('notifications', anchorOf(e))}
        >
          <Icon name="bell" size={19} />
          {alerts > 0 && <span className="dock-badge">{alerts > 9 ? '9+' : alerts}</span>}
        </button>
        <button type="button" className="dock-btn" data-tip="Search  Ctrl K" aria-label="Search" onClick={onSearch}>
          <Icon name="search" size={19} />
        </button>
        <button
          type="button"
          className="dock-btn"
          data-tip={theme === 'dark' ? 'Light mode' : 'Dark mode'}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          onClick={toggleTheme}
        >
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={19} />
        </button>
        {document.fullscreenEnabled && (
          <button
            type="button"
            className="dock-btn dock-fullscreen"
            data-tip={fullscreen ? 'Exit full screen' : 'Full screen'}
            aria-label={fullscreen ? 'Exit full screen' : 'Full screen'}
            onClick={toggleFullscreen}
          >
            <Icon name={fullscreen ? 'shrink' : 'expand'} size={19} />
          </button>
        )}
        <DockClock />
      </nav>
    </div>
  )
}

function DockStats({ onOpen }: { onOpen: () => void }) {
  const server = useServer()
  if (!server.data) return null
  const { cpu, memory } = server.data
  const mem = memory ? (memory.used / memory.total) * 100 : null
  return (
    <span className="dock-stats">
      <button type="button" className={`dock-pill ${usageTone(cpu.percent)}`} data-tip="CPU" onClick={onOpen}>
        {formatPercent(cpu.percent)}
      </button>
      <button type="button" className={`dock-pill ${usageTone(mem)}`} data-tip="Memory" onClick={onOpen}>
        {formatPercent(mem)}
      </button>
    </span>
  )
}

function DockClock() {
  const now = useNow()
  return (
    <time className="dock-clock" dateTime={now.toISOString()} title={clockDate(now)}>
      {clockTime(now)}
    </time>
  )
}
