import type { Container, Warning } from '../api/types'
import { containerStatus, WARNING_TEXT } from '../lib/status'

export function StateBadge({ container }: { container: Container }) {
  const { label, tone } = containerStatus(container)
  return (
    <span className={`badge ${tone}`}>
      <span className="dot" aria-hidden />
      {label}
      {container.health && container.state === 'running' && (
        <span className="badge-sub">{container.health}</span>
      )}
    </span>
  )
}

export function WarningBadges({ warnings }: { warnings: Warning[] }) {
  return (
    <>
      {warnings.map((w) => (
        <span key={w} className="badge bad" title={WARNING_TEXT[w].help}>
          {WARNING_TEXT[w].label}
        </span>
      ))}
    </>
  )
}
