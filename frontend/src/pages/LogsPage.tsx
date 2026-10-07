import { useOverview } from '../api/queries'
import { LogViewer } from '../components/LogViewer'
import { useDesktop, useWindow } from '../desktop/state'
import { containerStatus } from '../lib/status'

/**
 * A project's logs in their own window, one tab per container. The stream stops while the
 * window is minimised (browsers allow only a few open connections per site) and starts
 * afresh when it's shown again.
 */
export function LogsPage({ slug, container }: { slug: string; container?: string }) {
  const overview = useOverview()
  const desktop = useDesktop()
  const win = useWindow()

  if (overview.isPending) return <p className="muted pad">Loading…</p>
  if (overview.isError) return <p className="error-text pad">{overview.error.message}</p>

  const project = overview.data.projects.find((p) => p.slug === slug)
  if (!project) {
    return (
      <p className="pad">
        No project named <code>{slug}</code>.{' '}
        <button type="button" className="btn small" onClick={win?.close}>
          Close
        </button>
      </p>
    )
  }
  if (project.containers.length === 0) return <p className="muted pad">This project has no containers.</p>

  // Containers are picked by name, which survives a redeploy (the id doesn't).
  const selected = project.containers.find((c) => c.name === container) ?? project.containers[0]

  return (
    <div className="logs-app">
      <div className="tabs" role="tablist" aria-label="Containers">
        {project.containers.map((c) => (
          <button
            key={c.id}
            type="button"
            role="tab"
            aria-selected={c.id === selected.id}
            className="tab"
            onClick={() => desktop.open({ app: 'logs', slug, container: c.name })}
          >
            <span className={`status-dot small ${containerStatus(c).tone}`} aria-hidden />
            {c.service ?? c.name}
          </button>
        ))}
      </div>
      {win?.minimized ? (
        <p className="muted pad">Paused while minimized.</p>
      ) : (
        <LogViewer key={selected.id} container={selected} />
      )}
    </div>
  )
}
