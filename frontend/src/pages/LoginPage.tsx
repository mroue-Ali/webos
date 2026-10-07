import { useState, type FormEvent } from 'react'
import { useLogin } from '../api/queries'
import { clockDate, clockTime, useNow } from '../lib/useNow'

/** The big clock over the sign-in card, like a lock screen. */
export function LockClock() {
  const now = useNow()
  return (
    <div className="lock-clock" aria-hidden>
      <div className="lock-time">{clockTime(now)}</div>
      <div className="lock-date">{clockDate(now)}</div>
    </div>
  )
}

export function LoginPage() {
  const login = useLogin()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  // Only shown when the account has 2FA turned on and the password was right.
  const [needsCode, setNeedsCode] = useState(false)
  const [code, setCode] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    login.mutate(
      { username, password, code: needsCode ? code : undefined },
      {
        onSuccess: (result) => setNeedsCode(result.code_required),
        onError: () => setCode(''),
      },
    )
  }

  return (
    <div className="login">
      <LockClock />
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <img src="/favicon.svg" alt="" width={44} height={44} />
          <span>webos</span>
        </div>
        <label>
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {needsCode && (
          <label>
            6-digit code from your authenticator app
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, ''))}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={7}
              autoFocus
              required
            />
          </label>
        )}
        {login.error && <p className="error-text">{login.error.message}</p>}
        <button type="submit" className="btn primary" disabled={login.isPending}>
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
