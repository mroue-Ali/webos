import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { keys, useImportProject, useOverview, useServer } from '../api/queries'
import type { Container, ContainerUsage, Project, UnmanagedGroup } from '../api/types'
import { WarningBadges } from '../components/Badges'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Icon } from '../components/Icon'
import { AppLink } from '../desktop/AppLink'
import { useDesktop, useLive } from '../desktop/state'
import { formatBytes, formatPercent } from '../lib/format'
import { containerStatus, projectStatus, stackStatus } from '../lib/status'
import { useContainerActions } from '../lib/useContainerActions'

type Usage = Map<string, ContainerUsage>

/** The container whose logs a project's "Logs" button opens: a troubled one first. */
function logsContainer(containers: Container[]): Container | undefined {
  return containers.find((c) => c.warnings.length > 0) ?? containers.find((c) => c.state === 'running') ?? containers[0]
}

export function ProjectsPage() {
  const overview = useOverview()
  const server = useServer()
  const live = useLive()
  const actions = useContainerActions()
  const client = useQueryClient()
  const usage: Usage = new Map((server.data?.containers ?? []).map((u) => [u.id, u]))

  if (overview.isPending) return <p className="muted">Loading…</p>
  if (overview.isError) return <p className="error-text">{overview.error.message}</p>

  const { docker, projects, unmanaged } = overview.data
  const warnings = [...projects, ...unmanaged].flatMap((g) => g.containers).reduce((n, c) => n + c.warnings.length, 0)

  return (
    <>
      <div className="app-toolbar">
        <div className="chips">
          <span className="chip">
            <strong>
              {docker.running}/{docker.total}
            </strong>
            containers running
          </span>
          <span className="chip">
            <strong>{projects.length}</strong> projects
          </span>
          {warnings > 0 && (
            <span className="chip bad">
              <strong>{warnings}</strong> {warnings === 1 ? 'warning' : 'warnings'}
            </span>
          )}
          <span className="chip" title={`Docker ${docker.version}`}>
            <span className={`live-dot ${live}`} aria-hidden />
            {live === 'live' ? 'Live' : live === 'connecting' ? 'Connecting…' : 'Disconnected'}
          </span>
        </div>
        <div className="spacer" />
        <button
          type="button"
          className="btn ghost small"
          onClick={() => {
            void client.invalidateQueries({ queryKey: keys.overview })
            void client.invalidateQueries({ queryKey: ['server'] })
          }}
        >
          <Icon name="refresh" size={15} />
          Refresh
        </button>
        <AppLink to={{ app: 'new' }} className="btn primary small">
          <Icon name="plus" size={15} />
          New site
        </AppLink>
      </div>

      {actions.error && (
        <div className="banner bad" role="alert">
          {actions.error}
          <button type="button" className="btn ghost small" onClick={actions.clearError}>
            Dismiss
          </button>
        </div>
      )}

      {projects.length === 0 && (
        <p className="muted">No projects registered yet. Import one from the list below to control it.</p>
      )}
      <div className="pgrid">
        {projects.map((p) => (
          <ProjectCard key={p.slug} project={p} usage={usage} onAction={actions.project} />
        ))}
      </div>

      {unmanaged.length > 0 && (
        <section>
          <h2 className="section-title">Not registered</h2>
          <p className="muted small">
            Running on the server but unknown to webos. These are view-only until imported.
          </p>
          <div className="pgrid">
            {unmanaged.map((g) => (
              <UnmanagedCard key={g.compose_project ?? '(none)'} group={g} />
            ))}
          </div>
        </section>
      )}

      <ConfirmDialog request={actions.confirm} onClose={actions.clearConfirm} />
    </>
  )
}

function ServiceList({ containers }: { containers: Container[] }) {
  if (containers.length === 0) return <p className="svc-empty muted small">No containers.</p>
  return (
    <ul className="svc-list">
      {containers.map((c) => {
        const status = containerStatus(c)
        return (
          <li key={c.id}>
            <span className={`status-dot small ${status.tone}`} aria-hidden />
            <span className="svc-name" title={`${c.name} · ${c.image}`}>
              {c.service ?? c.name}
            </span>
            <WarningBadges warnings={c.warnings} />
            <span className={`svc-state ${status.tone}`}>{status.label}</span>
          </li>
        )
      })}
    </ul>
  )
}

function ProjectCard({
  project: p,
  usage,
  onAction,
}: {
  project: Project
  usage: Usage
  onAction: (slug: string, action: 'start' | 'stop' | 'restart') => void
}) {
  const desktop = useDesktop()
  const status = projectStatus(p)
  const running = p.containers.filter((c) => c.state === 'running')
  const cpu = running.reduce((sum, c) => sum + (usage.get(c.id)?.cpu_percent ?? 0), 0)
  const memory = running.reduce((sum, c) => sum + (usage.get(c.id)?.memory_used ?? 0), 0)
  const draft = p.managed && p.state === 'draft'
  const logs = logsContainer(p.containers)

  return (
    <article className={`pcard ${status.tone}`}>
      <header className="pcard-head">
        <span className={`status-dot ${status.tone}`} aria-hidden />
        <AppLink to={{ app: 'project', slug: p.slug }} className="pcard-title">
          {p.display_name}
        </AppLink>
        <span className={`pill ${status.tone}`}>{status.label}</span>
      </header>

      <div className="pcard-meta">
        {p.domain ? (
          <a href={`https://${p.domain}`} target="_blank" rel="noreferrer noopener">
            {p.domain}
            <Icon name="external" size={12} />
          </a>
        ) : (
          <span>no domain</span>
        )}
        {p.port && <span className="mono">:{p.port}</span>}
        {running.length > 0 && usage.size > 0 && (
          <span title="CPU is a share of the whole server">
            CPU {formatPercent(cpu)} · {formatBytes(memory)}
          </span>
        )}
        {p.is_self && <span className="badge neutral">this panel</span>}
      </div>

      <ServiceList containers={p.containers} />

      <footer className="pcard-actions">
        {draft && (
          <AppLink to={{ app: 'new', site: p.slug }} className="btn small primary">
            Continue setup
          </AppLink>
        )}
        {!p.is_self && p.containers.length > 0 && !draft && (
          <>
            {running.length > 0 && (
              <button type="button" className="btn small" onClick={() => onAction(p.slug, 'restart')}>
                <Icon name="restart" size={14} />
                Restart
              </button>
            )}
            {running.length > 0 ? (
              <button type="button" className="btn small danger" onClick={() => onAction(p.slug, 'stop')}>
                <Icon name="stop" size={14} />
                Stop
              </button>
            ) : (
              <button type="button" className="btn small" onClick={() => onAction(p.slug, 'start')}>
                <Icon name="play" size={14} />
                Start
              </button>
            )}
          </>
        )}
        {logs && (
          <button
            type="button"
            className="btn small"
            onClick={() => desktop.open({ app: 'logs', slug: p.slug, container: logs.name })}
          >
            <Icon name="logs" size={14} />
            Logs
          </button>
        )}
      </footer>
    </article>
  )
}

function UnmanagedCard({ group }: { group: UnmanagedGroup }) {
  const importProject = useImportProject()
  const [error, setError] = useState<string | null>(null)
  const name = group.compose_project
  const status = stackStatus(group.containers)

  return (
    <article className="pcard unmanaged">
      <header className="pcard-head">
        <span className={`status-dot ${status.tone}`} aria-hidden />
        <span className="pcard-title">{name ?? 'Standalone containers'}</span>
        <span className={`pill ${status.tone}`}>{status.label}</span>
      </header>
      <div className="pcard-meta">
        {group.working_dir ? <span className="mono">{group.working_dir}</span> : <span>no working directory</span>}
        {group.is_self && <span className="badge neutral">this panel</span>}
      </div>
      <ServiceList containers={group.containers} />
      {error && <p className="error-text small">{error}</p>}
      <footer className="pcard-actions">
        {name ? (
          <button
            type="button"
            className="btn small primary"
            disabled={importProject.isPending}
            onClick={() => importProject.mutate({ compose_project: name }, { onError: (e) => setError(e.message) })}
          >
            Import
          </button>
        ) : (
          <span className="muted small">Started without Docker Compose, so there is no project to import.</span>
        )}
      </footer>
    </article>
  )
}
