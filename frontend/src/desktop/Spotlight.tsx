import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useLogout, useOverview } from '../api/queries'
import { Icon, type IconName } from '../components/Icon'
import { projectHue, projectStatus } from '../lib/status'
import { toggleTheme, useTheme } from '../lib/theme'
import { APPS, LAUNCHABLE, type Target } from './apps'
import { useDesktop } from './state'

interface Command {
  id: string
  group: 'Apps' | 'Projects' | 'Actions'
  label: string
  hint?: string
  icon: IconName
  hue: string
  /** Extra words it should match. */
  terms?: string
  run: () => void
}

/** Ctrl+K: jump to any app, project, log or action by typing. */
export function Spotlight({ onClose }: { onClose: () => void }) {
  const desktop = useDesktop()
  const overview = useOverview()
  const theme = useTheme()
  const logout = useLogout(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const list = useRef<HTMLDivElement>(null)

  const commands = useMemo(() => {
    const open = (target: Target) => () => desktop.open(target)
    const out: Command[] = LAUNCHABLE.map((app) => ({
      id: app,
      group: 'Apps',
      label: APPS[app].title,
      icon: APPS[app].icon,
      hue: APPS[app].hue,
      terms: app === 'server' ? 'cpu memory disk network stats' : app === 'new' ? 'deploy create add' : '',
      run: open({ app }),
    }))
    for (const p of overview.data?.projects ?? []) {
      const hue = projectHue(p.slug)
      const terms = [p.slug, p.domain, ...p.containers.map((c) => c.name)].filter(Boolean).join(' ')
      out.push({
        id: `project:${p.slug}`,
        group: 'Projects',
        label: p.display_name,
        hint: `${projectStatus(p).label}${p.domain ? ` · ${p.domain}` : ''}`,
        icon: 'globe',
        hue,
        terms,
        run: open({ app: 'project', slug: p.slug }),
      })
      if (p.containers.length > 0) {
        out.push({
          id: `logs:${p.slug}`,
          group: 'Projects',
          label: `Logs: ${p.display_name}`,
          icon: 'logs',
          hue,
          terms,
          run: open({ app: 'logs', slug: p.slug }),
        })
      }
      if (p.managed && p.state === 'draft') {
        out.push({
          id: `new:${p.slug}`,
          group: 'Projects',
          label: `Continue setup: ${p.display_name}`,
          icon: 'rocket',
          hue: 'green',
          run: open({ app: 'new', site: p.slug }),
        })
      }
    }
    out.push(
      {
        id: 'theme',
        group: 'Actions',
        label: theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode',
        icon: theme === 'dark' ? 'sun' : 'moon',
        hue: 'slate',
        terms: 'theme appearance',
        run: toggleTheme,
      },
      {
        id: 'logout',
        group: 'Actions',
        label: 'Log out',
        icon: 'logout',
        hue: 'slate',
        terms: 'sign out',
        run: () => logout.mutate(),
      },
    )
    return out
  }, [desktop, overview.data, theme, logout])

  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const results = words.length
    ? commands.filter((c) => {
        const text = `${c.label} ${c.hint ?? ''} ${c.terms ?? ''}`.toLowerCase()
        return words.every((w) => text.includes(w))
      })
    : commands
  const selected = Math.min(active, results.length - 1)

  useEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  function run(command: Command | undefined) {
    if (!command) return
    onClose()
    command.run()
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === 'ArrowDown') setActive(Math.min(results.length - 1, selected + 1))
    else if (event.key === 'ArrowUp') setActive(Math.max(0, selected - 1))
    else if (event.key === 'Enter') run(results[selected])
    else if (event.key === 'Escape') onClose()
    else return
    event.preventDefault()
  }

  return (
    <div className="spotlight-scrim" onClick={onClose}>
      <div className="spotlight" role="dialog" aria-modal="true" aria-label="Search" onClick={(e) => e.stopPropagation()}>
        <div className="spotlight-input">
          <Icon name="search" size={20} />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            onKeyDown={onKeyDown}
            placeholder="Search projects, apps and actions"
            role="combobox"
            aria-expanded="true"
            aria-controls="spotlight-results"
            aria-activedescendant={results[selected] ? `spot-${results[selected].id}` : undefined}
            aria-label="Search"
          />
          <kbd>Esc</kbd>
        </div>
        <div className="spotlight-list" id="spotlight-results" role="listbox" ref={list}>
          {results.length === 0 && <p className="muted pad">Nothing matches “{query}”.</p>}
          {results.map((c, i) => {
            const heading = i === 0 || results[i - 1].group !== c.group ? c.group : null
            return (
              <div key={c.id}>
                {heading && (
                  <div className="spot-group" aria-hidden>
                    {heading}
                  </div>
                )}
                <div
                  id={`spot-${c.id}`}
                  role="option"
                  aria-selected={i === selected}
                  className="spot-item"
                  onPointerMove={() => i !== selected && setActive(i)}
                  onClick={() => run(c)}
                >
                  <span className={`art tiny hue-${c.hue}`}>
                    <Icon name={c.icon} size={14} />
                  </span>
                  <span className="spot-label">{c.label}</span>
                  {c.hint && <span className="muted small spot-hint">{c.hint}</span>}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
