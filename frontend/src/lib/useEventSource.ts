import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { keys } from '../api/queries'

export type StreamStatus = 'connecting' | 'live' | 'closed'

export interface StreamOptions {
  /** Close for good when the server ends the stream (a finished deployment), instead of
   *  letting the browser reconnect (right for container logs, which resume). */
  closeOnEnd?: boolean
  /** Called on every (re)connect; the server replays from the start for some streams. */
  onOpen?: () => void
}

/**
 * Subscribes to a webos SSE endpoint. The browser reconnects by itself when a stream ends
 * (sending Last-Event-ID, so log streams resume where they stopped). A stream the server
 * ends because the session expired is closed for good, and the app falls back to login.
 */
export function useEventSource(
  url: string | null,
  events: string[],
  onEvent: (name: string, data: unknown) => void,
  options: StreamOptions = {},
): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const handler = useRef(onEvent)
  const opts = useRef(options)
  const client = useQueryClient()
  const eventKey = events.join(',')

  useEffect(() => {
    handler.current = onEvent
    opts.current = options
  })

  useEffect(() => {
    if (!url) return
    const source = new EventSource(url)
    const checkSession = () => void client.invalidateQueries({ queryKey: keys.me })

    source.onopen = () => {
      setStatus('live')
      opts.current.onOpen?.()
    }
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        setStatus('closed')
        checkSession() // a refused reconnect is often an expired session
      } else {
        setStatus('connecting')
      }
    }
    source.addEventListener('end', (event) => {
      const reason = JSON.parse(event.data).reason
      if (reason === 'session' || opts.current.closeOnEnd) {
        source.close()
        setStatus('closed')
        handler.current('end', { reason })
        if (reason === 'session') checkSession()
      }
    })
    for (const name of eventKey.split(',')) {
      source.addEventListener(name, (event) => handler.current(name, JSON.parse(event.data)))
    }
    return () => source.close()
  }, [url, eventKey, client])

  return status
}
