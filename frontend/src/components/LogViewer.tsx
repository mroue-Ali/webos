import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Container, LogLine } from '../api/types'
import { parseAnsi } from '../lib/ansi'
import { formatTime } from '../lib/format'
import { isErrorLine } from '../lib/logs'
import { useEventSource } from '../lib/useEventSource'

const MAX_LINES = 5000
const FLUSH_MS = 200

type Filter = 'all' | 'errors' | 'stderr'

interface Line extends LogLine {
  key: number
  error: boolean
}

function LogText({ text }: { text: string }) {
  // Rendered as text nodes only; colours map to fixed class names, never to markup.
  return (
    <>
      {parseAnsi(text).map((s, i) => (
        <span key={i} className={[s.fg && `ansi-${s.fg}`, s.bold && 'ansi-bold'].filter(Boolean).join(' ') || undefined}>
          {s.text}
        </span>
      ))}
    </>
  )
}

/** Live log tail for one container. Mount with key={container.id} to reset on switch. */
export function LogViewer({ container }: { container: Container }) {
  const [lines, setLines] = useState<Line[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [paused, setPaused] = useState(false)
  const [follow, setFollow] = useState(true)
  const pending = useRef<Line[]>([])
  const nextKey = useRef(0)
  const scroller = useRef<HTMLDivElement>(null)

  const status = useEventSource(
    `/api/containers/${container.id}/logs?tail=500`,
    ['line', 'error'],
    (name, data) => {
      if (name === 'error') {
        const message = (data as { message?: string }).message ?? 'stream error'
        data = { ts: '', stream: 'stderr', text: `[webos] ${message}` }
      }
      const line = data as LogLine
      pending.current.push({ ...line, key: nextKey.current++, error: isErrorLine(line.text) })
      if (pending.current.length > MAX_LINES) pending.current.splice(0, pending.current.length - MAX_LINES)
    },
  )

  useEffect(() => {
    if (paused) return
    const timer = setInterval(() => {
      if (pending.current.length === 0) return
      const batch = pending.current
      pending.current = []
      setLines((prev) => prev.concat(batch).slice(-MAX_LINES))
    }, FLUSH_MS)
    return () => clearInterval(timer)
  }, [paused])

  const visible = useMemo(() => {
    const needle = search.toLowerCase()
    return lines.filter(
      (l) =>
        (filter === 'all' || (filter === 'errors' ? l.error : l.stream === 'stderr')) &&
        (!needle || l.text.toLowerCase().includes(needle)),
    )
  }, [lines, filter, search])

  useLayoutEffect(() => {
    const el = scroller.current
    if (el && follow) el.scrollTop = el.scrollHeight
  }, [visible, follow])

  function onScroll() {
    const el = scroller.current
    if (el) setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40)
  }

  const errorCount = useMemo(() => lines.filter((l) => l.error).length, [lines])

  return (
    <div className="logs">
      <div className="logs-toolbar">
        <strong>{container.name}</strong>
        <span className={`stream-status ${status}`}>
          {status === 'live' ? 'live' : status === 'connecting' ? 'connecting…' : 'disconnected'}
        </span>
        <div className="spacer" />
        <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} aria-label="Filter">
          <option value="all">All lines</option>
          <option value="errors">Errors ({errorCount})</option>
          <option value="stderr">stderr only</option>
        </select>
        <input
          type="search"
          placeholder="Search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search logs"
        />
        <button type="button" className="btn small" onClick={() => setPaused((p) => !p)}>
          {paused ? 'Resume' : 'Pause'}
        </button>
        <button type="button" className="btn small" onClick={() => setLines([])}>
          Clear
        </button>
      </div>
      <div className="logs-body mono" ref={scroller} onScroll={onScroll}>
        {visible.length === 0 && <div className="muted pad">No log lines{lines.length ? ' match' : ' yet'}.</div>}
        {visible.map((l) => (
          <div key={l.key} className={`log-line${l.stream === 'stderr' ? ' stderr' : ''}${l.error ? ' error' : ''}`}>
            <span className="log-ts">{l.ts ? formatTime(l.ts) : ''}</span>
            <span className="log-text">
              <LogText text={l.text} />
            </span>
          </div>
        ))}
      </div>
      {!follow && (
        <button type="button" className="btn small jump" onClick={() => setFollow(true)}>
          Jump to latest
        </button>
      )}
    </div>
  )
}
