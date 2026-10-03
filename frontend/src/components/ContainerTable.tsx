import type { Action, Container, Port } from '../api/types'
import { StateBadge, WarningBadges } from './Badges'

/** One entry per published port; Docker lists IPv4 and IPv6 bindings separately. */
function publishedPorts(ports: Port[]): { label: string; public: boolean }[] {
  const seen = new Map<string, { label: string; public: boolean }>()
  for (const p of ports) {
    if (p.public_port === null) continue
    const key = `${p.public_port}/${p.private_port}/${p.protocol}`
    const ip = p.ip.includes(':') ? `[${p.ip}]` : p.ip
    const entry = seen.get(key)
    if (entry) entry.public ||= p.public
    else
      seen.set(key, {
        label: `${ip}:${p.public_port} → ${p.private_port}/${p.protocol}`,
        public: p.public,
      })
  }
  return [...seen.values()]
}

export function ContainerTable({
  containers,
  onAction,
  onLogs,
  selectedId,
}: {
  containers: Container[]
  onAction?: (container: Container, action: Action) => void
  onLogs?: (container: Container) => void
  selectedId?: string
}) {
  if (containers.length === 0) {
    return <p className="muted pad">No containers.</p>
  }
  return (
    <div className="table-wrap">
      <table className="table containers">
        <thead>
          <tr>
            <th>Container</th>
            <th>State</th>
            <th>Status</th>
            <th>Ports</th>
            <th className="num">Restarts</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {containers.map((c) => (
            <tr key={c.id} className={c.id === selectedId ? 'selected' : undefined}>
              <td>
                <div className="strong">{c.name}</div>
                <div className="muted small mono">{c.image}</div>
              </td>
              <td>
                <div className="badges">
                  <StateBadge container={c} />
                  <WarningBadges warnings={c.warnings} />
                </div>
              </td>
              <td className="small">{c.status}</td>
              <td className="small mono">
                {publishedPorts(c.ports).map((p) => (
                  <div key={p.label} className={p.public ? 'bad-text' : undefined}>
                    {p.label}
                  </div>
                ))}
              </td>
              <td className="num">{c.restart_count}</td>
              <td>
                <div className="row-actions">
                  {onLogs && (
                    <button type="button" className="btn small" onClick={() => onLogs(c)}>
                      Logs
                    </button>
                  )}
                  {onAction && c.manageable && (
                    <>
                      {c.state !== 'running' && (
                        <button type="button" className="btn small" onClick={() => onAction(c, 'start')}>
                          Start
                        </button>
                      )}
                      {c.state === 'running' && (
                        <button type="button" className="btn small" onClick={() => onAction(c, 'restart')}>
                          Restart
                        </button>
                      )}
                      {c.state !== 'exited' && c.state !== 'created' && (
                        <button type="button" className="btn small" onClick={() => onAction(c, 'stop')}>
                          Stop
                        </button>
                      )}
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
