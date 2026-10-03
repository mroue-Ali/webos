import { useState } from 'react'
import { useAction } from '../api/queries'
import type { Action, Container } from '../api/types'
import type { ConfirmRequest } from '../components/ConfirmDialog'
import { capitalize } from './format'

const CONSEQUENCES: Record<Exclude<Action, 'start'>, string> = {
  stop: 'It stays stopped until you start it again; whatever it serves goes offline.',
  restart: 'Expect a few seconds of downtime while it comes back up.',
}

/**
 * Start runs straight away; stop and restart ask first. Either way the server gets the
 * target's name as `confirm`, which it requires for disruptive actions.
 */
export function useContainerActions() {
  const action = useAction()
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)
  const [error, setError] = useState<string | null>(null)

  function run(kind: 'container' | 'project', id: string, name: string, act: Action) {
    const go = () => action.mutateAsync({ kind, id, action: act, confirm: name })
    setError(null)
    if (act === 'start') {
      go().catch((e: Error) => setError(e.message))
      return
    }
    const what = kind === 'project' ? `every container of ${name}` : name
    setConfirm({
      title: `${capitalize(act)} ${what}?`,
      body: <p>{CONSEQUENCES[act]}</p>,
      confirmLabel: capitalize(act),
      danger: true,
      onConfirm: go,
    })
  }

  return {
    confirm,
    clearConfirm: () => setConfirm(null),
    error,
    clearError: () => setError(null),
    container: (c: Container, act: Action) => run('container', c.id, c.name, act),
    project: (slug: string, act: Action) => run('project', slug, slug, act),
  }
}
