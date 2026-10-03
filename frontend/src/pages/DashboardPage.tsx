import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { keys, useImportProject, useOverview, useServer } from '../api/queries'
import type { Container, ContainerUsage, UnmanagedGroup } from '../api/types'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ContainerTable } from '../components/ContainerTable'
import { formatBytes, formatPercent } from '../lib/format'
import { useContainerActions } from '../lib/useContainerActions'
import { useEventSource } from '../lib/useEventSource'

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

function countWarnings(containers: Container[]) {
  return containers.reduce((n, c) => n + c.warnings.length, 0)
}

export function DashboardPage() {
  const overview = useOverview()
  const server = useServer()
  const live = useLiveOverview()
  const actions = useContainerActions()
  const usage = new Map<string, ContainerUsage>(
    (server.data?.containers ?? []).map((u) => [u.id, u]),
  )

  if (overview.isPending) return <p className="muted">Loading…</p>
  if (overview.isError) return <p className="error-text">{overview.error.message}</p>

  const { docker, projects, unmanaged } = overview.data
  const allContainers = [...projects, ...unmanaged].flatMap((g) => g.containers)
  const warnings = countWarnings(allContainers)

  return (
    <>
      <div className="summary">
        <div className="stat">
          <span className="stat-value">
            {docker.running}/{docker.total}
          </span>
          <span className="stat-label">containers running</span>
        </div>
        <div className="stat">
          <span className="stat-value">{projects.length}</span>
          <span className="stat-label">projects</span>
        </div>
        <div className={`stat ${warnings ? 'stat-bad' : ''}`}>
          <span className="stat-value">{warnings}</span>
          <span className="stat-label">warnings</span>
        </div>
        <ServerStats />
        <div className="spacer" />
        <span className="muted small">
          Docker {docker.version} · events {live === 'live' ? 'live' : live}
        </span>
      </div>

      {actions.error && (
        <div className="banner bad" role="alert">
          {actions.error}
          <button type="button" className="btn ghost small" onClick={actions.clearError}>
            Dismiss
          </button>
        </div>
      )}

      <section>
        <h2>Projects</h2>
        {projects.length === 0 && (
          <p className="muted">
            No projects registered yet. Import one from the list below to control it.
          </p>
        )}
        {projects.map((p) => (
          <div className="card" key={p.slug}>
            <div className="card-head">
              <Link to={`/projects/${p.slug}`} className="card-title">
                {p.display_name}
              </Link>
              {p.domain && <span className="muted small">{p.domain}</span>}
              {p.port && <span className="muted small mono">127.0.0.1:{p.port}</span>}
              {p.is_self && <span className="badge neutral">this panel</span>}
              <div className="spacer" />
              <Link to={`/projects/${p.slug}`} className="btn small">
                Open
              </Link>
            </div>
            <ContainerTable containers={p.containers} onAction={actions.container} usage={usage} />
          </div>
        ))}
      </section>

      {unmanaged.length > 0 && (
        <section>
          <h2>Not registered</h2>
          <p className="muted small">
            Running on the server but unknown to webos. These are view-only until imported.
          </p>
          {unmanaged.map((g) => (
            <UnmanagedCard key={g.compose_project ?? '(none)'} group={g} usage={usage} />
          ))}
        </section>
      )}

      <ConfirmDialog request={actions.confirm} onClose={actions.clearConfirm} />
    </>
  )
}

/** CPU, memory and disk at a glance; the Server page has the detail. */
function ServerStats() {
  const server = useServer()
  if (!server.data) return null
  const { cpu, memory, disk } = server.data
  // [key, value, label]
  const tiles: [string, string, string][] = [
    ['cpu', formatPercent(cpu.percent), cpu.load ? `CPU · load ${cpu.load[0].toFixed(2)}` : 'CPU'],
    [
      'memory',
      memory ? formatPercent((memory.used / memory.total) * 100) : '—',
      memory ? `memory · ${formatBytes(memory.used)} of ${formatBytes(memory.total)}` : 'memory',
    ],
    [
      'disk',
      disk ? formatPercent((disk.used / disk.total) * 100) : '—',
      disk ? `disk · ${formatBytes(disk.free)} free` : 'disk',
    ],
  ]
  return (
    <>
      {tiles.map(([key, value, label]) => (
        <Link key={key} to="/server" className="stat stat-link" title="Open the Server page">
          <span className="stat-value">{value}</span>
          <span className="stat-label">{label}</span>
        </Link>
      ))}
    </>
  )
}

function UnmanagedCard({ group, usage }: { group: UnmanagedGroup; usage: Map<string, ContainerUsage> }) {
  const importProject = useImportProject()
  const [error, setError] = useState<string | null>(null)
  const name = group.compose_project

  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title">{name ?? 'Standalone containers'}</span>
        {group.working_dir && <span className="muted small mono">{group.working_dir}</span>}
        {group.is_self && <span className="badge neutral">this panel</span>}
        <div className="spacer" />
        {name && (
          <button
            type="button"
            className="btn small primary"
            disabled={importProject.isPending}
            onClick={() =>
              importProject.mutate(
                { compose_project: name },
                { onError: (e) => setError(e.message) },
              )
            }
          >
            Import
          </button>
        )}
      </div>
      {error && <p className="error-text pad">{error}</p>}
      {!name && (
        <p className="muted small pad">
          Started without Docker Compose, so there is no project to import.
        </p>
      )}
      <ContainerTable containers={group.containers} usage={usage} />
    </div>
  )
}
