import { useOverview, useServer } from '../api/queries'
import { Icon } from '../components/Icon'
import { formatBytes, formatDuration, formatPercent, formatRate } from '../lib/format'
import { linePath } from '../lib/spark'
import { collectNotices, usageTone } from '../lib/status'
import type { StreamStatus } from '../lib/useEventSource'
import { clockDate, clockTime, useNow } from '../lib/useNow'
import { useDesktop } from './state'

// Widgets show the last ten minutes (the server samples every 5 s).
const RECENT = 120
const W = 120
const H = 28

function MiniSpark({ values, max, tone }: { values: (number | null)[]; max?: number; tone: 'series-1' | 'series-2' }) {
  const recent = values.slice(-RECENT)
  const peak = Math.max(0, ...recent.filter((v): v is number => v !== null))
  const top = max ?? (peak > 0 ? peak * 1.15 : 1)
  const line = linePath(recent, top, W, H, 2)
  return (
    <svg className="wspark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      {recent.length > 1 && (
        <>
          <path className={`spark-area ${tone}`} d={`${line}L${W},${H}L0,${H}Z`} />
          <path className={`spark-line ${tone}`} d={line} vectorEffect="non-scaling-stroke" />
        </>
      )}
    </svg>
  )
}

/** Clock, host vitals and Docker at a glance, on the desktop behind the windows. */
export function Widgets({ live }: { live: StreamStatus }) {
  return (
    <aside className="widgets" aria-label="Widgets">
      <ClockWidget />
      <SystemWidget />
      <NetworkWidget />
      <StorageWidget />
      <DockerWidget live={live} />
    </aside>
  )
}

function ClockWidget() {
  const now = useNow()
  return (
    <div className="widget clock">
      <time className="clock-time" dateTime={now.toISOString()}>
        {clockTime(now)}
      </time>
      <div className="clock-date">{clockDate(now)}</div>
    </div>
  )
}

function SystemWidget() {
  const server = useServer()
  const desktop = useDesktop()
  const stats = server.data
  const mem = stats?.memory ? (stats.memory.used / stats.memory.total) * 100 : null
  return (
    <button type="button" className="widget" onClick={() => desktop.open({ app: 'server' })}>
      <div className="widget-label">
        System
        {stats?.host.uptime_seconds != null && <span>up {formatDuration(stats.host.uptime_seconds)}</span>}
      </div>
      <div className="wrow">
        <span>CPU</span>
        <span className="wtrack">
          <MiniSpark values={stats?.history.cpu ?? []} max={100} tone="series-1" />
        </span>
        <span className={`wval ${usageTone(stats?.cpu.percent)}`}>{formatPercent(stats?.cpu.percent)}</span>
      </div>
      <div className="wrow">
        <span>MEM</span>
        <span className="wtrack">
          <MiniSpark values={stats?.history.memory ?? []} max={100} tone="series-2" />
        </span>
        <span className={`wval ${usageTone(mem)}`}>{formatPercent(mem)}</span>
      </div>
      {stats?.cpu.load && (
        <div className="wfoot">
          load {stats.cpu.load.map((l) => l.toFixed(2)).join(' · ')}
          {stats.host.cpus ? ` · ${stats.host.cpus} CPUs` : ''}
        </div>
      )}
    </button>
  )
}

function NetworkWidget() {
  const server = useServer()
  const desktop = useDesktop()
  const stats = server.data
  if (stats && !stats.network) return null
  const rx = stats?.network?.reduce((sum, i) => sum + (i.rx_rate ?? 0), 0)
  const tx = stats?.network?.reduce((sum, i) => sum + (i.tx_rate ?? 0), 0)
  return (
    <button type="button" className="widget" onClick={() => desktop.open({ app: 'server' })}>
      <div className="widget-label">Network</div>
      <div className="wrow">
        <span className="series-1" >
          <Icon name="arrowDown" size={15} />
          <span className="sr-only">In</span>
        </span>
        <span className="wtrack">
          <MiniSpark values={stats?.history.rx ?? []} tone="series-1" />
        </span>
        <span className="wval">{formatRate(rx)}</span>
      </div>
      <div className="wrow">
        <span className="series-2" >
          <Icon name="arrowUp" size={15} />
          <span className="sr-only">Out</span>
        </span>
        <span className="wtrack">
          <MiniSpark values={stats?.history.tx ?? []} tone="series-2" />
        </span>
        <span className="wval">{formatRate(tx)}</span>
      </div>
    </button>
  )
}

function StorageWidget() {
  const server = useServer()
  const desktop = useDesktop()
  const disk = server.data?.disk
  const docker = server.data?.docker_disk
  if (!disk) return null
  const used = (disk.used / disk.total) * 100
  const rows: [string, number][] = docker
    ? [
        ['Images', docker.images],
        ['Build cache', docker.build_cache],
        ['Volumes', docker.volumes],
      ]
    : []
  return (
    <button type="button" className="widget" onClick={() => desktop.open({ app: 'server' })}>
      <div className="widget-label">
        Disk
        <span>{formatBytes(disk.free)} free</span>
      </div>
      <div className="wdisk">
        <span className="wbar">
          <span className={usageTone(used)} style={{ width: `${Math.min(100, used)}%` }} />
        </span>
        <span className={`wval ${usageTone(used)}`}>{formatPercent(used)}</span>
      </div>
      {rows.map(([name, size]) => (
        <div key={name} className="wline">
          <span className="muted">{name}</span>
          <span>{formatBytes(size)}</span>
        </div>
      ))}
    </button>
  )
}

function DockerWidget({ live }: { live: StreamStatus }) {
  const overview = useOverview()
  const desktop = useDesktop()
  const data = overview.data
  if (!data) return null
  const alerts = collectNotices(data).filter((n) => n.tone === 'bad').length
  return (
    <button type="button" className="widget" onClick={() => desktop.open({ app: 'projects' })}>
      <div className="widget-label">
        Docker
        <span className={`live-state ${live}`}>
          <span className={`live-dot ${live}`} aria-hidden />
          {live === 'live' ? 'live' : 'offline'}
        </span>
      </div>
      <div className="wdocker">
        <div>
          <div className="wbig">
            {data.docker.running}
            <span className="muted">/{data.docker.total}</span>
          </div>
          <div className="muted small">running</div>
        </div>
        <div>
          <div className="wbig">{data.projects.length}</div>
          <div className="muted small">projects</div>
        </div>
        <div>
          <div className={`wbig${alerts ? ' bad' : ''}`}>{alerts}</div>
          <div className="muted small">warnings</div>
        </div>
      </div>
      <div className="wfoot">Docker {data.docker.version}</div>
    </button>
  )
}
