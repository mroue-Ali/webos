import type { IconName } from '../components/Icon'

/** What a window shows. Each maps to a URL, so links and reloads land on the same window. */
export type Target =
  | { app: 'projects' }
  | { app: 'server' }
  | { app: 'audit' }
  | { app: 'new'; site?: string }
  | { app: 'project'; slug: string }
  | { app: 'logs'; slug: string; container?: string }

export type AppId = Target['app']

export interface AppInfo {
  title: string
  icon: IconName
  hue: string
  /** Preferred size; windows shrink to fit small screens. */
  size: [number, number]
  /** The content fills the window instead of scrolling (the log viewer). */
  fill?: boolean
}

export const APPS: Record<AppId, AppInfo> = {
  projects: { title: 'Projects', icon: 'projects', hue: 'amber', size: [1000, 680] },
  server: { title: 'Server', icon: 'server', hue: 'cyan', size: [1060, 720] },
  new: { title: 'New site', icon: 'rocket', hue: 'green', size: [880, 740] },
  audit: { title: 'Audit log', icon: 'audit', hue: 'violet', size: [1040, 660] },
  project: { title: 'Project', icon: 'globe', hue: 'blue', size: [1080, 740] },
  logs: { title: 'Logs', icon: 'logs', hue: 'slate', size: [960, 600], fill: true },
}

/** The apps on the desktop and in the launcher, in order. */
export const LAUNCHABLE = ['projects', 'server', 'new', 'audit'] as const

/** One window per key: opening a target that is already open brings that window forward. */
export function targetKey(t: Target): string {
  switch (t.app) {
    case 'new':
      return t.site ? `new:${t.site}` : 'new'
    case 'project':
      return `project:${t.slug}`
    case 'logs':
      return `logs:${t.slug}`
    default:
      return t.app
  }
}

export function targetPath(t: Target): string {
  switch (t.app) {
    case 'projects':
      return '/projects'
    case 'server':
      return '/server'
    case 'audit':
      return '/audit'
    case 'new':
      return t.site ? `/new?site=${t.site}` : '/new'
    case 'project':
      return `/projects/${t.slug}`
    case 'logs':
      return `/projects/${t.slug}/logs`
  }
}

// The same rules the server applies; anything else in a URL or saved layout is ignored.
const SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/
const CONTAINER_NAME = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/

export function parsePath(pathname: string, search: string): Target | null {
  const parts = pathname.split('/').filter(Boolean)
  const [first, slug, rest] = parts
  if (parts.length === 1 && (first === 'projects' || first === 'server' || first === 'audit')) {
    return { app: first }
  }
  if (parts.length === 1 && first === 'new') {
    const site = new URLSearchParams(search).get('site')
    return site && SLUG.test(site) ? { app: 'new', site } : { app: 'new' }
  }
  if (first === 'projects' && slug && SLUG.test(slug)) {
    if (parts.length === 2) return { app: 'project', slug }
    if (parts.length === 3 && rest === 'logs') return { app: 'logs', slug }
  }
  return null
}

/** Checks a target read back from storage. */
export function isTarget(value: unknown): value is Target {
  if (typeof value !== 'object' || value === null) return false
  const t = value as Record<string, unknown>
  const slugOk = (v: unknown) => typeof v === 'string' && SLUG.test(v)
  switch (t.app) {
    case 'projects':
    case 'server':
    case 'audit':
      return true
    case 'new':
      return t.site === undefined || slugOk(t.site)
    case 'project':
      return slugOk(t.slug)
    case 'logs':
      return (
        slugOk(t.slug) &&
        (t.container === undefined || (typeof t.container === 'string' && CONTAINER_NAME.test(t.container)))
      )
    default:
      return false
  }
}
