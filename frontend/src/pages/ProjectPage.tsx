import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useOverview, useServer, useUnregisterProject, useUpdateProject } from '../api/queries'
import type { Project } from '../api/types'
import { ConfirmDialog, type ConfirmRequest } from '../components/ConfirmDialog'
import { ContainerTable } from '../components/ContainerTable'
import { LogViewer } from '../components/LogViewer'
import { useContainerActions } from '../lib/useContainerActions'

export function ProjectPage() {
  const { slug } = useParams()
  const overview = useOverview()
  const server = useServer()
  const actions = useContainerActions()
  const [selected, setSelected] = useState<string | null>(null)
  const usage = new Map((server.data?.containers ?? []).map((u) => [u.id, u]))

  if (overview.isPending) return <p className="muted">Loading…</p>
  if (overview.isError) return <p className="error-text">{overview.error.message}</p>

  const project = overview.data.projects.find((p) => p.slug === slug)
  if (!project) {
    return (
      <p>
        No project named <code>{slug}</code>. <Link to="/">Back to the dashboard</Link>
      </p>
    )
  }

  const logContainer =
    project.containers.find((c) => c.id === selected) ?? project.containers[0] ?? null
  const anyRunning = project.containers.some((c) => c.state === 'running')

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/" className="muted small">
            ← Dashboard
          </Link>
          <h1>{project.display_name}</h1>
          <div className="meta muted small">
            <span>
              compose project <code>{project.compose_project}</code>
            </span>
            {project.working_dir && <code>{project.working_dir}</code>}
            {project.port && <code>127.0.0.1:{project.port}</code>}
            {project.domain && (
              <a href={`https://${project.domain}`} target="_blank" rel="noreferrer noopener">
                {project.domain} ↗
              </a>
            )}
          </div>
        </div>
        {!project.is_self && project.containers.length > 0 && (
          <div className="row-actions">
            <button type="button" className="btn" onClick={() => actions.project(project.slug, 'start')}>
              Start all
            </button>
            <button
              type="button"
              className="btn"
              disabled={!anyRunning}
              onClick={() => actions.project(project.slug, 'restart')}
            >
              Restart all
            </button>
            <button
              type="button"
              className="btn"
              disabled={!anyRunning}
              onClick={() => actions.project(project.slug, 'stop')}
            >
              Stop all
            </button>
          </div>
        )}
      </div>

      {project.is_self && (
        <div className="banner">This is webos itself, so it can be viewed but not stopped or restarted from here.</div>
      )}
      {actions.error && (
        <div className="banner bad" role="alert">
          {actions.error}
          <button type="button" className="btn ghost small" onClick={actions.clearError}>
            Dismiss
          </button>
        </div>
      )}

      <div className="card">
        <ContainerTable
          containers={project.containers}
          onAction={actions.container}
          onLogs={(c) => setSelected(c.id)}
          selectedId={logContainer?.id}
          usage={usage}
        />
      </div>

      {logContainer && <LogViewer key={logContainer.id} container={logContainer} />}

      <ProjectSettings key={project.slug} project={project} />
      <ConfirmDialog request={actions.confirm} onClose={actions.clearConfirm} />
    </>
  )
}

function ProjectSettings({ project }: { project: Project }) {
  const update = useUpdateProject(project.slug)
  const unregister = useUnregisterProject()
  const navigate = useNavigate()
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)
  const [form, setForm] = useState({
    display_name: project.display_name,
    domain: project.domain ?? '',
    repo_url: project.repo_url ?? '',
    port: project.port ? String(project.port) : '',
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    update.mutate({
      display_name: form.display_name.trim(),
      domain: form.domain.trim().toLowerCase() || null,
      repo_url: form.repo_url.trim() || null,
      port: form.port ? Number(form.port) : null,
    })
  }

  const field = (name: keyof typeof form) => ({
    value: form[name],
    onChange: (e: { target: { value: string } }) => setForm({ ...form, [name]: e.target.value }),
  })

  return (
    <section className="card settings">
      <h2>Settings</h2>
      <form className="form-grid" onSubmit={submit}>
        <label>
          Name
          <input {...field('display_name')} required maxLength={80} />
        </label>
        <label>
          Domain
          <input {...field('domain')} placeholder="shop.example.com" />
        </label>
        <label>
          Repository
          <input {...field('repo_url')} placeholder="git@github.com:you/repo.git" />
        </label>
        <label>
          Assigned port
          <input {...field('port')} inputMode="numeric" placeholder="8002" />
        </label>
        <div className="form-actions">
          {update.error && <span className="error-text">{update.error.message}</span>}
          {update.isSuccess && <span className="muted small">Saved.</span>}
          <button type="submit" className="btn primary" disabled={update.isPending}>
            Save
          </button>
        </div>
      </form>

      <div className="danger-zone">
        <div>
          <strong>Unregister project</strong>
          <p className="muted small">
            webos forgets it. Containers, files and nginx config are left exactly as they are.
          </p>
        </div>
        <button
          type="button"
          className="btn danger"
          onClick={() =>
            setConfirm({
              title: `Unregister ${project.slug}?`,
              body: <p>It moves to “Not registered” on the dashboard. Nothing on the server changes.</p>,
              confirmLabel: 'Unregister',
              danger: true,
              onConfirm: async () => {
                await unregister.mutateAsync(project.slug)
                navigate('/')
              },
            })
          }
        >
          Unregister
        </button>
      </div>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </section>
  )
}
