import { useQueryClient } from '@tanstack/react-query'
import { useLayoutEffect, useRef, useState } from 'react'
import { useDeployment } from '../api/queries'
import type { Deployment } from '../api/types'
import { useEventSource } from '../lib/useEventSource'
import { LogText } from './LogText'

export function DeployStatusBadge({ status }: { status: Deployment['status'] }) {
  const tone = status === 'ok' ? 'good' : status === 'failed' ? 'bad' : 'warn'
  const label = status === 'ok' ? 'succeeded' : status === 'failed' ? 'failed' : 'running'
  return (
    <span className={`badge ${tone}`}>
      <span className="dot" aria-hidden />
      {label}
    </span>
  )
}

/**
 * A deployment's log, streamed live while it runs. The server replays the log from the
 * start on every connect, so the view resets on (re)connect instead of duplicating lines.
 */
export function DeployLog({
  deploymentId,
  onFinished,
}: {
  deploymentId: number
  onFinished?: (deployment: Deployment) => void
}) {
  const [lines, setLines] = useState<string[]>([])
  const detail = useDeployment(deploymentId)
  const client = useQueryClient()
  const scroller = useRef<HTMLDivElement>(null)
  const [finished, setFinished] = useState(false)

  useEventSource(
    `/api/deployments/${deploymentId}/stream`,
    ['line'],
    (name, data) => {
      if (name === 'line') {
        setLines((prev) => [...prev, (data as { text: string }).text])
      } else if (name === 'end' && !finished) {
        setFinished(true)
        void detail.refetch().then((result) => {
          if (result.data) onFinished?.(result.data)
        })
        void client.invalidateQueries({ queryKey: ['deployments'] })
        void client.invalidateQueries({ queryKey: ['overview'] })
      }
    },
    { closeOnEnd: true, onOpen: () => setLines([]) },
  )

  useLayoutEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  const status = detail.data && finished ? detail.data.status : 'running'
  return (
    <div className="logs deploy-log">
      <div className="logs-toolbar">
        <strong>Deployment #{deploymentId}</strong>
        <DeployStatusBadge status={status} />
        {detail.data?.error && finished && (
          <span className="error-text small">{detail.data.error}</span>
        )}
      </div>
      <div className="logs-body mono" ref={scroller}>
        {lines.length === 0 && <div className="muted pad">Waiting for output…</div>}
        {lines.map((line, i) => (
          <div
            key={i}
            className={`log-line${line.startsWith('==> ') ? ' step' : ''}${line.startsWith('!! ') ? ' error' : ''}`}
          >
            <span className="log-text">
              <LogText text={line} />
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
