import { useLogout, useOverview } from '../api/queries'
import { Icon } from '../components/Icon'
import { projectHue, projectStatus } from '../lib/status'
import { APPS, LAUNCHABLE, type Target } from './apps'
import { Popover, type Anchor } from './Popover'
import { useDesktop } from './state'

/** The apps button's panel: every app, every project, and signing out. */
export function Launcher({
  anchor,
  username,
  onClose,
  onSearch,
}: {
  anchor: Anchor
  username: string
  onClose: () => void
  onSearch: () => void
}) {
  const desktop = useDesktop()
  const overview = useOverview()
  const logout = useLogout(false)
  const logoutAll = useLogout(true)
  const projects = overview.data?.projects ?? []

  const go = (target: Target) => {
    desktop.open(target)
    onClose()
  }

  return (
    <Popover anchor={anchor} width={380} label="Apps" className="launcher" onClose={onClose}>
      <div className="launcher-head">
        <span className="avatar" aria-hidden>
          {username.charAt(0).toUpperCase()}
        </span>
        <div className="launcher-who">
          <div className="strong">{username}</div>
          <div className="muted small">Signed in to webos</div>
        </div>
        <button type="button" className="launcher-search" onClick={onSearch}>
          <Icon name="search" size={15} />
          Search
          <kbd>Ctrl K</kbd>
        </button>
      </div>

      <div className="launcher-apps">
        {LAUNCHABLE.map((app) => (
          <button key={app} type="button" className="launcher-app" onClick={() => go({ app })}>
            <span className={`art hue-${APPS[app].hue}`}>
              <Icon name={APPS[app].icon} size={22} />
            </span>
            {APPS[app].title}
          </button>
        ))}
      </div>

      {projects.length > 0 && (
        <>
          <div className="launcher-section">Projects</div>
          <ul className="launcher-list">
            {projects.map((p) => {
              const status = projectStatus(p)
              return (
                <li key={p.slug}>
                  <button type="button" onClick={() => go({ app: 'project', slug: p.slug })}>
                    <span className={`art tiny hue-${projectHue(p.slug)}`}>
                      <Icon name="globe" size={14} />
                    </span>
                    <span className="launcher-name">{p.display_name}</span>
                    <span className="muted small launcher-domain">{p.domain ?? ''}</span>
                    <span className={`status-dot ${status.tone}`} title={status.label} />
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}

      <div className="launcher-foot">
        <button type="button" className="btn ghost small" onClick={() => logout.mutate()}>
          <Icon name="logout" size={15} />
          Log out
        </button>
        <button
          type="button"
          className="btn ghost small"
          onClick={() => logoutAll.mutate()}
          title="End every session, on every device"
        >
          Log out everywhere
        </button>
      </div>
    </Popover>
  )
}
