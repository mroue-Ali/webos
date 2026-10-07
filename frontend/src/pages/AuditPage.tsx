import { useState } from 'react'
import { useAudit } from '../api/queries'
import type { AuditEvent } from '../api/types'
import { formatDateTime } from '../lib/format'

const ACTIONS = [
  ['', 'All actions'],
  ['auth.', 'Sign-ins'],
  ['container.', 'Containers'],
  ['project.', 'Projects'],
  ['user.', 'User changes'],
] as const

function outcomeTone(e: AuditEvent) {
  return e.outcome === 'ok' ? 'good' : e.outcome === 'error' ? 'bad' : 'neutral'
}

function details(e: AuditEvent) {
  const params = Object.entries(e.params)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' ')
  return [e.error, params].filter(Boolean).join(' · ')
}

export function AuditPage() {
  const [action, setAction] = useState('')
  const [target, setTarget] = useState('')
  const audit = useAudit(action, target.trim())
  const events = audit.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <>
      <div className="page-head">
        <p className="muted small page-intro">
          Every sign-in attempt and every change, newest first. Actions write a “started” row and
          then an “ok” or “error” row. Rows can't be edited or deleted.
        </p>
        <div className="row-actions">
          <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action">
            {ACTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <input
            type="search"
            placeholder="Exact target, e.g. shop-web"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            aria-label="Target"
          />
        </div>
      </div>

      <div className="card">
        {audit.isError && <p className="error-text pad">{audit.error.message}</p>}
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Target</th>
                <th>Outcome</th>
                <th>Details</th>
                <th>Who / from</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td className="small nowrap">{formatDateTime(e.ts)}</td>
                  <td className="mono small">{e.action}</td>
                  <td className="small">{e.target}</td>
                  <td>
                    <span className={`badge ${outcomeTone(e)}`}>{e.outcome}</span>
                  </td>
                  <td className="small mono wrap">{details(e)}</td>
                  <td className="small" title={e.user_agent ?? undefined}>
                    {e.actor ?? '—'}
                    <div className="muted">{e.ip}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!audit.isPending && events.length === 0 && <p className="muted pad">Nothing yet.</p>}
      </div>
      {audit.hasNextPage && (
        <button
          type="button"
          className="btn"
          onClick={() => audit.fetchNextPage()}
          disabled={audit.isFetchingNextPage}
        >
          Load older
        </button>
      )}
    </>
  )
}
