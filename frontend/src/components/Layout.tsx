import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router'
import { useLogout } from '../api/queries'

export function Layout({ username, children }: { username: string; children: ReactNode }) {
  const logout = useLogout(false)
  const logoutAll = useLogout(true)

  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          <img src="/favicon.svg" alt="" width={22} height={22} />
          webos
        </Link>
        <nav className="nav">
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/server">Server</NavLink>
          <NavLink to="/audit">Audit log</NavLink>
        </nav>
        <div className="spacer" />
        <span className="muted small">{username}</span>
        <button type="button" className="btn ghost small" onClick={() => logout.mutate()}>
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
      </header>
      <main className="content">{children}</main>
    </div>
  )
}
