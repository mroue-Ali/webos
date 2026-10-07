import { Icon } from '../components/Icon'
import type { Notice } from '../lib/status'
import type { StreamStatus } from '../lib/useEventSource'
import { Popover, type Anchor } from './Popover'
import { useDesktop } from './state'

/** The bell's panel: everything on the server that wants attention right now. */
export function Notifications({
  anchor,
  notices,
  live,
  onClose,
}: {
  anchor: Anchor
  notices: Notice[]
  live: StreamStatus
  onClose: () => void
}) {
  const desktop = useDesktop()

  function openNotice(n: Notice) {
    if (n.draft && n.slug) desktop.open({ app: 'new', site: n.slug })
    else if (n.slug) desktop.open({ app: 'project', slug: n.slug })
    else desktop.open({ app: 'projects' })
    onClose()
  }

  return (
    <Popover anchor={anchor} width={380} label="Notifications" className="notices" onClose={onClose}>
      <div className="notices-head">
        <span className="strong">Notifications</span>
        <span className={`live-state ${live}`}>
          <span className={`live-dot ${live}`} aria-hidden />
          {live === 'live' ? 'Live' : live === 'connecting' ? 'Connecting…' : 'Disconnected'}
        </span>
      </div>
      {notices.length === 0 ? (
        <div className="notices-empty">
          <Icon name="check" size={28} />
          <div className="strong">All clear</div>
          <div className="muted small">No container needs attention.</div>
        </div>
      ) : (
        <ul className="notices-list">
          {notices.map((n) => (
            <li key={n.id}>
              <button type="button" className={`notice ${n.tone}`} onClick={() => openNotice(n)} title={n.help}>
                <span className="notice-icon">
                  <Icon name={n.tone === 'info' ? 'rocket' : 'alert'} size={16} />
                </span>
                <span className="notice-text">
                  <span className="notice-title">{n.title}</span>
                  <span className="muted small">{n.detail}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Popover>
  )
}
