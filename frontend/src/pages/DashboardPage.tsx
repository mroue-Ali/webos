import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { keys, useImportProject, useOverview } from '../api/queries'
import type { Container, UnmanagedGroup } from '../api/types'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ContainerTable } from '../components/ContainerTable'
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
  const live = useLiveOverview()
  const actions = useContainerActions()

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
            <ContainerTable containers={p.containers} onAction={actions.container} />
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
            <UnmanagedCard key={g.compose_project ?? '(none)'} group={g} />
          ))}
        </section>
      )}

      <ConfirmDialog request={actions.confirm} onClose={actions.clearConfirm} />
    </>
  )
}

function UnmanagedCard({ group }: { group: UnmanagedGroup }) {
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
      <ContainerTable containers={group.containers} />
    </div>
  )
}
