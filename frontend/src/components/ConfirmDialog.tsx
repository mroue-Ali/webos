import { useEffect, useRef, useState, type ReactNode } from 'react'

export interface ConfirmRequest {
  title: string
  body: ReactNode
  confirmLabel: string
  danger?: boolean
  onConfirm: () => Promise<unknown>
}

/** A modal that runs `onConfirm` and stays open with the error if it fails. */
export function ConfirmDialog({
  request,
  onClose,
}: {
  request: ConfirmRequest | null
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (request && !dialog.open) dialog.showModal()
    if (!request && dialog.open) dialog.close()
  }, [request])

  async function confirm() {
    if (!request) return
    setPending(true)
    setError(null)
    try {
      await request.onConfirm()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setPending(false)
    }
  }

  function close() {
    setError(null)
    onClose()
  }

  return (
    <dialog ref={ref} className="dialog" onClose={close}>
      {request && (
        <>
          <h2>{request.title}</h2>
          <div className="dialog-body">{request.body}</div>
          {error && <p className="error-text">{error}</p>}
          <div className="dialog-actions">
            <button type="button" className="btn" onClick={close} disabled={pending}>
              Cancel
            </button>
            <button
              type="button"
              className={request.danger ? 'btn danger' : 'btn primary'}
              onClick={confirm}
              disabled={pending}
              autoFocus
            >
              {pending ? 'Working…' : request.confirmLabel}
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}
