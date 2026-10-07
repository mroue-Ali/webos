import { useEffect, useState, type ReactNode } from 'react'
import {
  useAgent,
  useCheckDomain,
  useComposeFiles,
  useCreateSite,
  useDeployKey,
  useDeploySite,
  useDiscardDraft,
  useInspect,
  usePreview,
} from '../api/queries'
import type { ComposeService, Deployment, ServiceChoice, SiteConfig } from '../api/types'
import { ConfirmDialog, type ConfirmRequest } from '../components/ConfirmDialog'
import { DeployLog } from '../components/DeployLog'
import { AppLink } from '../desktop/AppLink'
import { useWindow } from '../desktop/state'

type Step = 'repo' | 'app' | 'domain' | 'env' | 'review' | 'deploy'

const STEPS: { id: Step; label: string }[] = [
  { id: 'repo', label: 'Repository' },
  { id: 'app', label: 'App' },
  { id: 'domain', label: 'Domain' },
  { id: 'env', label: 'Environment' },
  { id: 'review', label: 'Review' },
  { id: 'deploy', label: 'Deploy' },
]

const NAME = /^[a-z0-9][a-z0-9-]{0,39}$/

/** https://github.com/owner/repo(.git) -> git@github.com:owner/repo.git, for deploy keys. */
function sshUrl(repo: string): string {
  const match = repo.trim().match(/^https:\/\/github\.com\/([\w.-]+)\/([\w.-]+?)(\.git)?\/?$/)
  return match ? `git@github.com:${match[1]}/${match[2]}.git` : repo.trim()
}

function nameFromRepo(repo: string): string {
  const last = repo.trim().replace(/\.git$/, '').split(/[/:]/).pop() ?? ''
  return last.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)
}

function envKeys(content: string): { key: string; empty: boolean }[] {
  return content
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#') && line.includes('='))
    .map((line) => {
      const [key, ...rest] = line.split('=')
      return { key: key.replace(/^export\s+/, '').trim(), empty: rest.join('=').trim() === '' }
    })
}

function commandText(command: ComposeService['command']): string {
  return Array.isArray(command) ? command.join(' ') : (command ?? '')
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card wizard-card">
      <h2>{title}</h2>
      {children}
    </section>
  )
}

/** The new-site wizard. `site` resumes a draft whose setup wasn't finished. */
export function NewSitePage({ site }: { site?: string }) {
  const resume = site ?? null
  const win = useWindow()
  const agent = useAgent()

  const [step, setStep] = useState<Step>(resume ? 'app' : 'repo')
  const [slug, setSlug] = useState<string | null>(resume)
  const [repoLabel, setRepoLabel] = useState('')
  const [composeFile, setComposeFile] = useState<string | null>(null)
  const [webService, setWebService] = useState('')
  const [containerPort, setContainerPort] = useState('')
  const [choices, setChoices] = useState<Record<string, ServiceChoice>>({})
  const [initialized, setInitialized] = useState<string | null>(null)
  const [domain, setDomain] = useState('')
  const [withWww, setWithWww] = useState(false)
  const [env, setEnv] = useState('')
  const [override, setOverride] = useState('')
  const [autoDeploy, setAutoDeploy] = useState(true)
  const [deploymentId, setDeploymentId] = useState<number | null>(null)
  const [outcome, setOutcome] = useState<Deployment | null>(null)
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)

  const files = useComposeFiles(slug)
  const discard = useDiscardDraft()

  // The first compose file found, unless one was picked.
  const activeCompose = composeFile ?? files.data?.[0] ?? null
  const inspect = useInspect(slug, activeCompose)

  // Take the server's suggestions once per compose file (adjusting state while rendering,
  // React's recommended alternative to an effect for this).
  const data = inspect.data
  if (data && initialized !== data.compose_file) {
    setInitialized(data.compose_file)
    setWebService(data.suggestion.web_service ?? Object.keys(data.services)[0] ?? '')
    setContainerPort(data.suggestion.container_port ? String(data.suggestion.container_port) : '')
    setChoices(
      Object.fromEntries(
        Object.entries(data.suggestion.services).map(([name, c]) => [
          name,
          { keep_volumes: c.keep_volumes, use_image_command: c.use_image_command },
        ]),
      ),
    )
    if (!domain) setDomain(data.domain_suggestion || '')
    if (!env) setEnv(data.env_example)
  }

  const config: SiteConfig | null =
    activeCompose && webService && Number(containerPort) > 0
      ? {
          compose_file: activeCompose,
          env_file: '.env',
          web_service: webService,
          container_port: Number(containerPort),
          services: choices,
        }
      : null
  const aliases = withWww && domain ? [`www.${domain}`] : []

  function askDiscard() {
    if (!slug) return
    setConfirm({
      title: `Discard ${slug}?`,
      body: <p>Deletes the cloned code and anything started for it. Nothing else changes.</p>,
      confirmLabel: 'Discard',
      danger: true,
      onConfirm: async () => {
        await discard.mutateAsync(slug)
        win?.close()
      },
    })
  }

  if (agent.isPending) return <p className="muted">Checking the host helper…</p>
  const agentDown = !agent.data?.available

  const stepIndex = STEPS.findIndex((s) => s.id === step)
  return (
    <>
      <div className="page-head">
        <div>
          <div className="page-title strong">{slug ?? 'Deploy a repository'}</div>
          {repoLabel && <div className="muted small mono">{repoLabel}</div>}
        </div>
        {slug && step !== 'deploy' && (
          <button type="button" className="btn danger" onClick={askDiscard}>
            Discard
          </button>
        )}
      </div>

      {agentDown && (
        <div className="banner bad" role="alert">
          <span>
            The host helper (webos-agent) isn't reachable: {agent.data?.error}. Install it on the
            server once with <code>sudo sh agent/install.sh</code> (see the README).
          </span>
        </div>
      )}

      <ol className="stepper">
        {STEPS.map((s, i) => (
          <li key={s.id} className={i < stepIndex ? 'done' : i === stepIndex ? 'current' : ''}>
            <span className="step-num">{i + 1}</span>
            {s.label}
          </li>
        ))}
      </ol>

      {!agentDown && step === 'repo' && (
        <RepoStep
          onCloned={(created, label) => {
            setSlug(created.slug)
            setRepoLabel(label)
            setComposeFile(created.compose_files[0] ?? null)
            setStep('app')
          }}
        />
      )}

      {!agentDown && step === 'app' && slug && (
        <Section title="Which app to serve">
          {files.isPending && <p className="muted">Reading the repository…</p>}
          {files.data && files.data.length === 0 && (
            <p className="error-text">
              No docker-compose file found in this repository. webos deploys compose projects.
            </p>
          )}
          {files.data && files.data.length > 0 && (
            <label className="field">
              Compose file
              <select value={activeCompose ?? ''} onChange={(e) => setComposeFile(e.target.value)}>
                {files.data.map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </select>
            </label>
          )}
          {inspect.isError && <p className="error-text">{inspect.error.message}</p>}
          {inspect.data && (
            <AppChoices
              services={inspect.data.services}
              violations={inspect.data.violations}
              webService={webService}
              setWebService={setWebService}
              containerPort={containerPort}
              setContainerPort={setContainerPort}
              choices={choices}
              setChoices={setChoices}
            />
          )}
          <div className="wizard-actions">
            <button
              type="button"
              className="btn primary"
              disabled={!config}
              onClick={() => setStep('domain')}
            >
              Next: domain
            </button>
          </div>
        </Section>
      )}

      {!agentDown && step === 'domain' && (
        <DomainStep
          domain={domain}
          setDomain={setDomain}
          withWww={withWww}
          setWithWww={setWithWww}
          serverIps={inspect.data?.server_ips ?? agent.data?.host_ips ?? []}
          onBack={() => setStep('app')}
          onNext={() => setStep('env')}
        />
      )}

      {!agentDown && step === 'env' && (
        <Section title="Environment variables">
          <p className="muted small">
            Saved only to the project's <code>.env</code> file on the server (readable by its
            owner only). webos doesn't keep a copy, and they never appear in logs.
          </p>
          <textarea
            className="mono env-editor"
            value={env}
            onChange={(e) => setEnv(e.target.value)}
            spellCheck={false}
            rows={14}
            placeholder="KEY=value"
            aria-label="Environment variables"
          />
          <EnvWarnings content={env} />
          <div className="wizard-actions">
            <button type="button" className="btn" onClick={() => setStep('domain')}>
              Back
            </button>
            <button type="button" className="btn primary" onClick={() => setStep('review')}>
              Next: review
            </button>
          </div>
        </Section>
      )}

      {!agentDown && step === 'review' && slug && config && (
        <ReviewStep
          slug={slug}
          config={config}
          domain={domain}
          aliases={aliases}
          env={env}
          override={override}
          setOverride={setOverride}
          autoDeploy={autoDeploy}
          setAutoDeploy={setAutoDeploy}
          onBack={() => setStep('env')}
          onStarted={(id) => {
            setOutcome(null)
            setDeploymentId(id)
            setStep('deploy')
          }}
        />
      )}

      {step === 'deploy' && deploymentId !== null && (
        <Section title="Deploying">
          <DeployLog key={deploymentId} deploymentId={deploymentId} onFinished={setOutcome} />
          {outcome?.status === 'ok' && (
            <div className="banner good">
              <span>
                <strong>{slug} is live.</strong> Every push to its branch can now deploy from the
                project page{autoDeploy ? ', and auto-deploy is on' : ''}.
              </span>
              <a className="btn primary small" href={`https://${domain}`} target="_blank" rel="noreferrer noopener">
                Open {domain} ↗
              </a>
              {slug && (
                <AppLink className="btn small" to={{ app: 'project', slug }}>
                  Project page
                </AppLink>
              )}
            </div>
          )}
          {outcome?.status === 'failed' && (
            <div className="banner bad">
              <span>The deployment failed: {outcome.error}</span>
              <button type="button" className="btn small" onClick={() => setStep('review')}>
                Back to review and retry
              </button>
            </div>
          )}
        </Section>
      )}

      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </>
  )
}

function RepoStep({
  onCloned,
}: {
  onCloned: (created: { slug: string; compose_files: string[] }, label: string) => void
}) {
  const [repo, setRepo] = useState('')
  const [branch, setBranch] = useState('main')
  const [name, setName] = useState('')
  const [nameTouched, setNameTouched] = useState(false)
  const [isPrivate, setIsPrivate] = useState(true)
  const [copied, setCopied] = useState(false)
  const deployKey = useDeployKey()
  const create = useCreateSite()

  const cloneUrl = isPrivate ? sshUrl(repo) : repo.trim()
  const effectiveName = nameTouched ? name : nameFromRepo(repo)
  const nameOk = NAME.test(effectiveName)
  const keyReady = !isPrivate || !!deployKey.data

  return (
    <Section title="Where the code lives">
      <div className="form-grid">
        <label className="field wide">
          Repository URL
          <input
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            placeholder="https://github.com/you/app"
            autoFocus
          />
        </label>
        <label className="field">
          Branch
          <input value={branch} onChange={(e) => setBranch(e.target.value)} />
        </label>
        <label className="field">
          Site name
          <input
            value={effectiveName}
            onChange={(e) => {
              setNameTouched(true)
              setName(e.target.value)
            }}
            placeholder="my-app"
          />
          <span className="muted small">
            Lowercase letters, digits, dashes. Also the folder name on the server.
          </span>
        </label>
      </div>

      <fieldset className="choice-row">
        <legend className="muted small">The repository is</legend>
        <label>
          <input type="radio" checked={isPrivate} onChange={() => setIsPrivate(true)} /> Private
        </label>
        <label>
          <input type="radio" checked={!isPrivate} onChange={() => setIsPrivate(false)} /> Public
        </label>
      </fieldset>

      {isPrivate && (
        <div className="deploy-key">
          <p className="small">
            The server needs read access. webos creates a key for this site only; the repository's
            owner adds it once on GitHub under <strong>Settings → Deploy keys → Add deploy key</strong>{' '}
            (leave “Allow write access” off). It's cloned over SSH:{' '}
            <code>{cloneUrl || 'git@github.com:owner/repo.git'}</code>
          </p>
          {!deployKey.data ? (
            <button
              type="button"
              className="btn"
              disabled={!nameOk || deployKey.isPending}
              onClick={() => deployKey.mutate(effectiveName)}
            >
              Create deploy key
            </button>
          ) : (
            <div className="key-box">
              <code className="mono">{deployKey.data.public_key}</code>
              <button
                type="button"
                className="btn small"
                onClick={() => {
                  void navigator.clipboard.writeText(deployKey.data.public_key)
                  setCopied(true)
                }}
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          )}
          {deployKey.error && <p className="error-text">{deployKey.error.message}</p>}
        </div>
      )}

      {create.error && <p className="error-text pre">{create.error.message}</p>}
      <div className="wizard-actions">
        <button
          type="button"
          className="btn primary"
          disabled={!repo.trim() || !branch.trim() || !nameOk || !keyReady || create.isPending}
          onClick={() =>
            create.mutate(
              { name: effectiveName, repo: cloneUrl, branch: branch.trim() },
              { onSuccess: (created) => onCloned(created, `${cloneUrl} (${branch.trim()})`) },
            )
          }
        >
          {create.isPending ? 'Cloning…' : 'Clone repository'}
        </button>
      </div>
    </Section>
  )
}

function AppChoices({
  services,
  violations,
  webService,
  setWebService,
  containerPort,
  setContainerPort,
  choices,
  setChoices,
}: {
  services: Record<string, ComposeService>
  violations: string[]
  webService: string
  setWebService: (name: string) => void
  containerPort: string
  setContainerPort: (port: string) => void
  choices: Record<string, ServiceChoice>
  setChoices: (choices: Record<string, ServiceChoice>) => void
}) {
  function toggleVolume(service: string, target: string, keep: boolean) {
    const all = (services[service].volumes ?? []).map((v) => v.target ?? '')
    const current = choices[service]?.keep_volumes ?? all
    const next = keep ? [...new Set([...current, target])] : current.filter((t) => t !== target)
    const keepVolumes = next.length === all.length ? null : next
    setChoices({ ...choices, [service]: { ...choices[service], keep_volumes: keepVolumes } })
  }

  return (
    <>
      <p className="muted small">
        Pick the service that answers web requests. webos publishes only that one, on
        127.0.0.1; databases and other services stay private inside Docker.
      </p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Web</th>
              <th>Service</th>
              <th>Production settings</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(services).map(([name, svc]) => {
              const choice = choices[name] ?? { keep_volumes: null, use_image_command: false }
              const command = commandText(svc.command)
              return (
                <tr key={name}>
                  <td>
                    <input
                      type="radio"
                      name="web"
                      checked={webService === name}
                      onChange={() => {
                        setWebService(name)
                        const port = svc.ports[0]?.target ?? Number(String(svc.expose[0] ?? '').split('/')[0])
                        if (port) setContainerPort(String(port))
                      }}
                      aria-label={`Serve ${name}`}
                    />
                  </td>
                  <td>
                    <div className="strong">{name}</div>
                    <div className="muted small mono">{svc.image ?? (svc.build ? 'built from the repo' : '')}</div>
                    {svc.ports.length > 0 && (
                      <div className="muted small">
                        container ports {svc.ports.map((p) => p.target).join(', ')}
                      </div>
                    )}
                  </td>
                  <td className="small">
                    {command && (
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={choice.use_image_command}
                          onChange={(e) =>
                            setChoices({
                              ...choices,
                              [name]: { ...choice, use_image_command: e.target.checked },
                            })
                          }
                        />
                        <span>
                          Use the image's own start command instead of <code>{command}</code>
                        </span>
                      </label>
                    )}
                    {(svc.volumes ?? []).map((v) => {
                      const kept = choice.keep_volumes === null || choice.keep_volumes.includes(v.target ?? '')
                      return (
                        <label key={v.target} className="check">
                          <input
                            type="checkbox"
                            checked={kept}
                            onChange={(e) => toggleVolume(name, v.target ?? '', e.target.checked)}
                          />
                          <span>
                            Keep {v.type === 'bind' ? 'folder' : 'volume'} <code>{v.source}</code> →{' '}
                            <code>{v.target}</code>
                          </span>
                        </label>
                      )
                    })}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <label className="field narrow">
        Port the web service listens on, inside its container
        <input value={containerPort} onChange={(e) => setContainerPort(e.target.value.replace(/\D/g, ''))} inputMode="numeric" />
      </label>
      {violations.length > 0 && (
        <details className="note">
          <summary>As written in the repository, the safety check would refuse {violations.length} thing(s). webos's production settings fix the ports.</summary>
          <ul className="small">
            {violations.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

function DomainStep({
  domain,
  setDomain,
  withWww,
  setWithWww,
  serverIps,
  onBack,
  onNext,
}: {
  domain: string
  setDomain: (domain: string) => void
  withWww: boolean
  setWithWww: (value: boolean) => void
  serverIps: string[]
  onBack: () => void
  onNext: () => void
}) {
  const check = useCheckDomain()
  const valid = /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(domain)
  const apex = valid && domain.split('.').length === 2
  const ipv4 = serverIps.filter((ip) => !ip.includes(':'))

  return (
    <Section title="Domain">
      <label className="field wide">
        Address the site will answer on
        <input
          value={domain}
          onChange={(e) => {
            setDomain(e.target.value.trim().toLowerCase())
            check.reset()
          }}
          placeholder="app.example.com"
        />
      </label>
      {apex && (
        <label className="check">
          <input type="checkbox" checked={withWww} onChange={(e) => setWithWww(e.target.checked)} />
          <span>Also answer on www.{domain}</span>
        </label>
      )}
      <p className="muted small">
        A subdomain of a domain with wildcard DNS works right away. Your own domain needs an A
        record {apex ? <>for <code>@</code>{withWww && <> and <code>www</code></>}</> : null} pointing to{' '}
        <code>{ipv4.join(', ') || 'this server'}</code> at your DNS provider first.
      </p>
      <div className="row-actions start">
        <button type="button" className="btn" disabled={!valid || check.isPending} onClick={() => check.mutate(domain)}>
          Check DNS
        </button>
        {check.data && (
          <span className={check.data.ok ? 'good-text' : 'error-text'}>
            {check.data.ok
              ? `Points to this server (${check.data.resolves_to.join(', ')}).`
              : check.data.resolves_to.length
                ? `Points to ${check.data.resolves_to.join(', ')}, not this server.`
                : "Doesn't resolve yet."}
          </span>
        )}
        {check.error && <span className="error-text">{check.error.message}</span>}
      </div>
      <div className="wizard-actions">
        <button type="button" className="btn" onClick={onBack}>
          Back
        </button>
        <button type="button" className="btn primary" disabled={!valid} onClick={onNext}>
          Next: environment
        </button>
      </div>
    </Section>
  )
}

function EnvWarnings({ content }: { content: string }) {
  const keys = envKeys(content)
  const empty = keys.filter((k) => k.empty).map((k) => k.key)
  return (
    <p className="small muted">
      {keys.length} variable{keys.length === 1 ? '' : 's'}
      {empty.length > 0 && (
        <span className="warn-text"> · still empty: {empty.join(', ')}</span>
      )}
    </p>
  )
}

function ReviewStep({
  slug,
  config,
  domain,
  aliases,
  env,
  override,
  setOverride,
  autoDeploy,
  setAutoDeploy,
  onBack,
  onStarted,
}: {
  slug: string
  config: SiteConfig
  domain: string
  aliases: string[]
  env: string
  override: string
  setOverride: (text: string) => void
  autoDeploy: boolean
  setAutoDeploy: (value: boolean) => void
  onBack: () => void
  onStarted: (deploymentId: number) => void
}) {
  const preview = usePreview(slug)
  const deploy = useDeploySite(slug)
  const configKey = JSON.stringify(config)

  // Regenerate the production layer whenever the app choices change.
  useEffect(() => {
    preview.mutate(JSON.parse(configKey) as SiteConfig, { onSuccess: (p) => setOverride(p.override) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configKey])

  const data = preview.data
  const blocked = !data || data.violations.length > 0 || !override.trim()
  return (
    <Section title="Review">
      {preview.isPending && <p className="muted">Generating the production settings…</p>}
      {preview.error && <p className="error-text pre">{preview.error.message}</p>}
      {data && (
        <>
          <dl className="summary-list">
            <dt>Serves</dt>
            <dd>
              <code>{config.web_service}</code> (container port {config.container_port}) →{' '}
              <code>127.0.0.1:{data.port}</code> → https://{[domain, ...aliases].join(', https://')}
            </dd>
            <dt>Compose file</dt>
            <dd>
              <code>{config.compose_file}</code> plus webos's production layer below
            </dd>
            <dt>Environment</dt>
            <dd>{envKeys(env).length} variables, written to .env on the server</dd>
          </dl>
          {data.violations.length > 0 && (
            <div className="banner bad">
              <div>
                The safety check refuses this setup:
                <ul className="small">
                  {data.violations.map((v) => (
                    <li key={v}>{v}</li>
                  ))}
                </ul>
                Go back and adjust the choices (or the layer below).
              </div>
            </div>
          )}
          <details className="note">
            <summary>Production layer (docker-compose.webos.yml): edit if you need to</summary>
            <textarea
              className="mono override-editor"
              value={override}
              onChange={(e) => setOverride(e.target.value)}
              spellCheck={false}
              rows={Math.min(24, override.split('\n').length + 2)}
              aria-label="Production layer"
            />
            <p className="muted small">
              The safety check runs again on the final setup before anything starts.
            </p>
          </details>
          <label className="check">
            <input type="checkbox" checked={autoDeploy} onChange={(e) => setAutoDeploy(e.target.checked)} />
            <span>Auto-deploy: redeploy when a new commit lands on the branch (checked every minute)</span>
          </label>
        </>
      )}
      {deploy.error && <p className="error-text pre">{deploy.error.message}</p>}
      <div className="wizard-actions">
        <button type="button" className="btn" onClick={onBack}>
          Back
        </button>
        <button
          type="button"
          className="btn primary"
          disabled={blocked || deploy.isPending}
          onClick={() =>
            deploy.mutate(
              { ...config, domain, aliases, override, env, auto_deploy: autoDeploy },
              { onSuccess: (r) => onStarted(r.deployment_id) },
            )
          }
        >
          {deploy.isPending ? 'Starting…' : 'Deploy'}
        </button>
      </div>
    </Section>
  )
}
