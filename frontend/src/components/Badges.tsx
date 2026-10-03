import type { Container, Warning } from '../api/types'

const WARNING_TEXT: Record<Warning, { label: string; help: string }> = {
  public_port: {
    label: 'public port',
    help: 'Published on every interface. Docker writes its own firewall rules, so ufw does not block this port. Bind it to 127.0.0.1 instead.',
  },
  restarting: { label: 'restarting', help: 'The container keeps crashing and being restarted.' },
  unhealthy: { label: 'unhealthy', help: 'Its health check is failing.' },
  exited_error: { label: 'crashed', help: 'It exited with a non-zero code.' },
  oom_killed: { label: 'out of memory', help: 'The kernel killed it for using too much memory.' },
}

export function StateBadge({ container }: { container: Container }) {
  const { state, health, exit_code } = container
  let tone = 'neutral'
  if (state === 'running') tone = health === 'unhealthy' ? 'bad' : 'good'
  else if (state === 'restarting') tone = 'warn'
  else if ((state === 'exited' || state === 'dead') && exit_code) tone = 'bad'

  const label =
    state === 'exited' && exit_code !== null ? `exited (${exit_code})` : state
  return (
    <span className={`badge ${tone}`}>
      <span className="dot" aria-hidden />
      {label}
      {health && state === 'running' && <span className="badge-sub">{health}</span>}
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
