import { ApiError } from './api/client'
import { useMe } from './api/queries'
import { Desktop } from './desktop/Desktop'
import { LockClock, LoginPage } from './pages/LoginPage'

export default function App() {
  const me = useMe()

  if (me.isPending) return null
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 401) return <LoginPage />
    return (
      <div className="login">
        <LockClock />
        <div className="login-card">
          <p className="error-text">Can't reach webos: {me.error.message}</p>
          <button type="button" className="btn primary" onClick={() => me.refetch()}>
            Try again
          </button>
        </div>
      </div>
    )
  }

  return <Desktop username={me.data.username} />
}
