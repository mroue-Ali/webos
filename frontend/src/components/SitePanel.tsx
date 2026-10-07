import { useEffect, useRef, useState } from 'react'
import {
  useDeployments,
  useDiscardDraft,
  useReadEnv,
  useRedeploy,
  useRemoveSite,
  useUpdateEnv,
  useUpdateSite,
} from '../api/queries'
import type { Project } from '../api/types'
import { AppLink } from '../desktop/AppLink'
import { useWindow } from '../desktop/state'
import { formatDateTime } from '../lib/format'
import { ConfirmDialog, type ConfirmRequest } from './ConfirmDialog'
import { DeployLog, DeployStatusBadge } from './DeployLog'

const TRIGGER_LABEL = { create: 'first deploy', manual: 'deploy now', auto: 'auto-deploy', env: 'env change' }

/** Deploys, history, environment and removal for a site webos deployed. */
export function SitePanel({ project }: { project: Project }) {
  if (project.state === 'draft') return <DraftBanner project={project} />
  return (
    <>
      <DeployCard project={project} />
      <EnvCard project={project} />
      <LayerCard project={project} />
      <RemoveCard project={project} />
    </>
  )
}

function DraftBanner({ project }: { project: Project }) {
  const discard = useDiscardDraft()
  const win = useWindow()
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)
  return (
    <div className="banner">
      <span>This site's setup isn't finished: it hasn't been deployed yet.</span>
      <AppLink className="btn primary small" to={{ app: 'new', site: project.slug }}>
        Continue setup
      </AppLink>
      <button
        type="button"
        className="btn small danger"
        onClick={() =>
          setConfirm({
            title: `Discard ${project.slug}?`,
            body: <p>Deletes the cloned code and anything started for it.</p>,
            confirmLabel: 'Discard',
            danger: true,
            onConfirm: async () => {
              await discard.mutateAsync(project.slug)
              win?.close()
            },
          })
        }
      >
        Discard
      </button>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  )
}

function DeployCard({ project }: { project: Project }) {
  const deployments = useDeployments(project.slug, project.deploying)
  const redeploy = useRedeploy()
  const update = useUpdateSite(project.slug)
  const [picked, setPicked] = useState<number | null>(null)
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)
  const latest = deployments.data?.[0]
  const shown = picked ?? (latest?.status === 'running' ? latest.id : null)

  return (
    <section className="card">
      <div className="card-head">
        <span className="card-title">Deployments</span>
        <span className="muted small">
          branch <code>{project.branch}</code>
          {project.deployed_commit && (
            <>
              {' '}· live commit <code>{project.deployed_commit.slice(0, 7)}</code>
            </>
          )}
        </span>
        {project.deploying && <span className="badge warn">deploying…</span>}
        <div className="spacer" />
        <label className="check inline">
          <input
            type="checkbox"
            checked={project.auto_deploy}
            disabled={update.isPending}
            onChange={(e) => update.mutate({ auto_deploy: e.target.checked })}
          />
          <span>Auto-deploy new commits</span>
        </label>
        <button
          type="button"
          className="btn primary small"
          disabled={project.deploying || redeploy.isPending}
          onClick={() =>
            setConfirm({
              title: `Deploy ${project.slug} now?`,
              body: (
                <p>
                  Pulls the latest commit on <code>{project.branch}</code>, rebuilds and restarts.
                  Expect a short interruption.
                </p>
              ),
              confirmLabel: 'Deploy',
              onConfirm: async () => setPicked((await redeploy.mutateAsync(project.slug)).deployment_id),
            })
          }
        >
          Deploy now
        </button>
      </div>
      {deployments.data && deployments.data.length === 0 && <p className="muted pad">No deployments yet.</p>}
      {deployments.data && deployments.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Trigger</th>
                <th>Status</th>
                <th>Commit</th>
                <th>By</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {deployments.data.slice(0, 10).map((d) => (
                <tr key={d.id} className={d.id === shown ? 'selected' : undefined}>
                  <td className="small nowrap">{formatDateTime(d.started_at)}</td>
                  <td className="small">{TRIGGER_LABEL[d.trigger]}</td>
                  <td>
                    <DeployStatusBadge status={d.status} />
                  </td>
                  <td className="small">
                    {d.commit && <code>{d.commit.slice(0, 7)}</code>} {d.subject}
                    {d.error && <div className="error-text">{d.error}</div>}
                  </td>
                  <td className="small">{d.actor}</td>
                  <td>
                    <button type="button" className="btn small" onClick={() => setPicked(d.id)}>
                      Log
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {shown !== null && (
        <div className="pad">
          <DeployLog key={shown} deploymentId={shown} />
        </div>
      )}
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </section>
  )
}

function EnvCard({ project }: { project: Project }) {
  const read = useReadEnv(project.slug)
  const save = useUpdateEnv(project.slug)
  const [text, setText] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)

  return (
    <section className="card settings">
      <h2>Environment</h2>
      <p className="muted small">
        The site's <code>{project.env_file ?? '.env'}</code> on the server. Opening it is
        recorded in the audit log, because it holds the site's secrets.
      </p>
      {text === null ? (
        <button
          type="button"
          className="btn"
          disabled={read.isPending}
          onClick={() => read.mutate(undefined, { onSuccess: (env) => setText(env.content) })}
        >
          Show and edit
        </button>
      ) : (
        <>
          <textarea
            className="mono env-editor"
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            rows={Math.min(20, text.split('\n').length + 2)}
            aria-label="Environment variables"
          />
          <div className="form-actions">
            {save.error && <span className="error-text">{save.error.message}</span>}
            {save.isSuccess && <span className="muted small">Saved; redeploying.</span>}
            <button type="button" className="btn" onClick={() => setText(null)}>
              Hide
            </button>
            <button
              type="button"
              className="btn primary"
              disabled={project.deploying || save.isPending}
              onClick={() =>
                setConfirm({
                  title: 'Save and restart?',
                  body: <p>The containers are recreated with the new values (a short interruption).</p>,
                  confirmLabel: 'Save and restart',
                  onConfirm: () => save.mutateAsync(text),
                })
              }
            >
              Save and restart
            </button>
          </div>
        </>
      )}
      {read.error && <p className="error-text">{read.error.message}</p>}
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </section>
  )
}

function LayerCard({ project }: { project: Project }) {
  const update = useUpdateSite(project.slug)
  const [text, setText] = useState(project.override ?? '')
  return (
    <section className="card settings">
      <details className="note">
        <summary>
          <strong>Production layer</strong>{' '}
          <span className="muted small">(docker-compose.webos.yml, used from the next deploy)</span>
        </summary>
        <textarea
          className="mono override-editor"
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          rows={Math.min(24, text.split('\n').length + 2)}
          aria-label="Production layer"
        />
        <div className="form-actions">
          {update.error && <span className="error-text">{update.error.message}</span>}
          {update.isSuccess && <span className="muted small">Saved. Deploy to apply it.</span>}
          <button
            type="button"
            className="btn primary"
            disabled={!text.trim() || text === project.override || update.isPending}
            onClick={() => update.mutate({ override: text })}
          >
            Save
          </button>
        </div>
      </details>
    </section>
  )
}

function RemoveCard({ project }: { project: Project }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="card settings">
      <div className="danger-zone">
        <div>
          <strong>Remove site</strong>
          <p className="muted small">
            Stops it and removes its nginx site and certificate. Optionally deletes its data and
            code too.
          </p>
        </div>
        <button type="button" className="btn danger" onClick={() => setOpen(true)}>
          Remove site
        </button>
      </div>
      {open && <RemoveDialog project={project} onClose={() => setOpen(false)} />}
    </section>
  )
}

function RemoveDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const remove = useRemoveSite(project.slug)
  const win = useWindow()
  const [typed, setTyped] = useState('')
  const [deleteVolumes, setDeleteVolumes] = useState(false)
  const [deleteFiles, setDeleteFiles] = useState(false)
  const [code, setCode] = useState('')

  useEffect(() => {
    ref.current?.showModal()
  }, [])

  return (
    <dialog ref={ref} className="dialog" onClose={onClose}>
      <h2>Remove {project.slug}?</h2>
      <div className="dialog-body">
        <p>
          {project.domain ? <code>{project.domain}</code> : 'The site'} stops answering. This can't
          be undone.
        </p>
        <label className="check">
          <input type="checkbox" checked={deleteVolumes} onChange={(e) => setDeleteVolumes(e.target.checked)} />
          <span>
            Also delete its Docker volumes: <strong>databases and uploads are gone for good</strong>
          </span>
        </label>
        <label className="check">
          <input type="checkbox" checked={deleteFiles} onChange={(e) => setDeleteFiles(e.target.checked)} />
          <span>Also delete the project folder (code and .env) from the server</span>
        </label>
        <label className="field">
          Type <code>{project.slug}</code> to confirm
          <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
        </label>
        <label className="field">
          Authenticator code (only if 2FA is on)
          <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} inputMode="numeric" maxLength={6} />
        </label>
      </div>
      {remove.error && <p className="error-text pre">{remove.error.message}</p>}
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose} disabled={remove.isPending}>
          Cancel
        </button>
        <button
          type="button"
          className="btn danger"
          disabled={typed !== project.slug || remove.isPending}
          onClick={() =>
            remove.mutate(
              { delete_files: deleteFiles, delete_volumes: deleteVolumes, code: code || undefined },
              { onSuccess: () => win?.close() },
            )
          }
        >
          {remove.isPending ? 'Removing…' : 'Remove site'}
        </button>
      </div>
    </dialog>
  )
}
