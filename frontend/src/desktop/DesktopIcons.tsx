import type { Project } from '../api/types'
import { Icon } from '../components/Icon'
import { projectHue, projectStatus } from '../lib/status'
import { APPS, LAUNCHABLE } from './apps'
import { useDesktop } from './state'

/** The apps, then one icon per project with its status as a dot. */
export function DesktopIcons({ projects }: { projects: Project[] }) {
  const desktop = useDesktop()
  return (
    <nav className="desk-icons" aria-label="Desktop">
      {LAUNCHABLE.map((app) => (
        <button key={app} type="button" className="desk-icon" onClick={() => desktop.open({ app })}>
          <span className={`art hue-${APPS[app].hue}`}>
            <Icon name={APPS[app].icon} size={24} />
          </span>
          <span className="desk-label">{APPS[app].title}</span>
        </button>
      ))}
      {projects.map((p) => {
        const status = projectStatus(p)
        return (
          <button
            key={p.slug}
            type="button"
            className="desk-icon"
            title={`${p.display_name}: ${status.label}`}
            onClick={() => desktop.open({ app: 'project', slug: p.slug })}
          >
            <span className={`art hue-${projectHue(p.slug)}`}>
              <Icon name="globe" size={24} />
              <span className={`status-dot ${status.tone}`} aria-hidden />
            </span>
            <span className="desk-label">{p.display_name}</span>
          </button>
        )
      })}
    </nav>
  )
}
