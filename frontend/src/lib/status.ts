import type { Container, Overview, Project, Warning } from '../api/types'

export type Tone = 'good' | 'warn' | 'bad' | 'info' | 'neutral'

export interface Status {
  label: string
  tone: Tone
}

export const WARNING_TEXT: Record<Warning, { label: string; help: string }> = {
  public_port: {
    label: 'public port',
    help: 'Published on every interface. Docker writes its own firewall rules, so ufw does not block this port. Bind it to 127.0.0.1 instead.',
  },
  restarting: { label: 'restarting', help: 'The container keeps crashing and being restarted.' },
  unhealthy: { label: 'unhealthy', help: 'Its health check is failing.' },
  exited_error: { label: 'crashed', help: 'It exited with a non-zero code.' },
  oom_killed: { label: 'out of memory', help: 'The kernel killed it for using too much memory.' },
}

export function containerStatus(container: Container): Status {
  const { state, health, exit_code } = container
  let tone: Tone = 'neutral'
  if (state === 'running') tone = health === 'unhealthy' ? 'bad' : 'good'
  else if (state === 'restarting') tone = 'warn'
  else if ((state === 'exited' || state === 'dead') && exit_code) tone = 'bad'
  const label = state === 'exited' && exit_code !== null ? `exited (${exit_code})` : state
  return { label, tone }
}

/** One word for a whole compose stack, from its containers. */
export function stackStatus(containers: Container[]): Status {
  if (containers.length === 0) return { label: 'No containers', tone: 'neutral' }
  const running = containers.filter((c) => c.state === 'running').length
  if (running === containers.length) {
    return containers.some((c) => c.warnings.length > 0)
      ? { label: 'Degraded', tone: 'warn' }
      : { label: 'Running', tone: 'good' }
  }
  if (running > 0) return { label: 'Partial', tone: 'warn' }
  if (containers.some((c) => containerStatus(c).tone === 'bad')) return { label: 'Failed', tone: 'bad' }
  return { label: 'Stopped', tone: 'neutral' }
}

export function projectStatus(project: Project): Status {
  if (project.deploying) return { label: 'Deploying', tone: 'info' }
  if (project.managed && project.state === 'draft') return { label: 'Setup', tone: 'neutral' }
  return stackStatus(project.containers)
}

const HUES = ['indigo', 'violet', 'cyan', 'teal', 'pink', 'blue'] as const

/** A stable colour per project, so its icon is recognisable across the desktop and dock. */
export function projectHue(slug: string): string {
  let hash = 0
  for (const ch of slug) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return HUES[hash % HUES.length]
}

/** The tone of a used/total ratio: warning at 75%, critical at 90% (as the meters). */
export function usageTone(percent: number | null | undefined): Tone {
  if (percent === null || percent === undefined) return 'neutral'
  return percent >= 90 ? 'bad' : percent >= 75 ? 'warn' : 'good'
}

export interface Notice {
  id: string
  tone: Tone
  title: string
  detail: string
  help?: string
  /** The project to open, or null for something not registered. */
  slug: string | null
  draft?: boolean
}

/** Everything that wants attention: container warnings, deploys in flight, unfinished setups. */
export function collectNotices(overview: Overview | undefined): Notice[] {
  if (!overview) return []
  const notices: Notice[] = []
  const add = (containers: Container[], owner: string, slug: string | null) => {
    for (const c of containers) {
      for (const w of c.warnings) {
        notices.push({
          id: `${c.id}:${w}`,
          tone: 'bad',
          title: `${c.service ?? c.name}: ${WARNING_TEXT[w].label}`,
          detail: owner,
          help: WARNING_TEXT[w].help,
          slug,
        })
      }
    }
  }
  for (const p of overview.projects) {
    add(p.containers, p.display_name, p.slug)
    if (p.deploying) {
      notices.push({
        id: `deploy:${p.slug}`,
        tone: 'info',
        title: `Deploying ${p.display_name}`,
        detail: 'A deployment is running.',
        slug: p.slug,
      })
    } else if (p.managed && p.state === 'draft') {
      notices.push({
        id: `draft:${p.slug}`,
        tone: 'warn',
        title: `${p.display_name}: setup not finished`,
        detail: 'Cloned but never deployed. Continue the setup or discard it.',
        slug: p.slug,
        draft: true,
      })
    }
  }
  for (const g of overview.unmanaged) add(g.containers, g.compose_project ?? 'Standalone container', null)
  return notices
}
