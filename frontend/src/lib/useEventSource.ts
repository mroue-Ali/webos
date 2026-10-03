import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { keys } from '../api/queries'

export type StreamStatus = 'connecting' | 'live' | 'closed'

/**
 * Subscribes to a webos SSE endpoint. The browser reconnects by itself when a stream ends
 * (sending Last-Event-ID, so log streams resume where they stopped). A stream the server
 * ends because the session expired is closed for good, and the app falls back to login.
 */
export function useEventSource(
  url: string | null,
  events: string[],
  onEvent: (name: string, data: unknown) => void,
): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const handler = useRef(onEvent)
  const client = useQueryClient()
  const eventKey = events.join(',')

  useEffect(() => {
    handler.current = onEvent
  })

  useEffect(() => {
    if (!url) return
    const source = new EventSource(url)
    const checkSession = () => void client.invalidateQueries({ queryKey: keys.me })

    source.onopen = () => setStatus('live')
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        setStatus('closed')
        checkSession() // a refused reconnect is often an expired session
      } else {
        setStatus('connecting')
      }
    }
    source.addEventListener('end', (event) => {
      if (JSON.parse(event.data).reason === 'session') {
        source.close()
        setStatus('closed')
        checkSession()
      }
    })
    for (const name of eventKey.split(',')) {
      source.addEventListener(name, (event) => handler.current(name, JSON.parse(event.data)))
    }
    return () => source.close()
  }, [url, eventKey, client])

  return status
}
