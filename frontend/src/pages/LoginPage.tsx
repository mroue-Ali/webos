import { useState, type FormEvent } from 'react'
import { useLogin } from '../api/queries'

export function LoginPage() {
  const login = useLogin()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    login.mutate({ username, password, code }, { onError: () => setCode('') })
  }

  return (
    <div className="login">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand login-brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          webos
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
        <label>
          Authenticator code
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, ''))}
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[\d ]{6,7}"
            maxLength={7}
            required
          />
        </label>
        {login.error && <p className="error-text">{login.error.message}</p>}
        <button type="submit" className="btn primary" disabled={login.isPending}>
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
