import { Link, Route, Routes } from 'react-router'
import { ApiError } from './api/client'
import { useMe } from './api/queries'
import { Layout } from './components/Layout'
import { AuditPage } from './pages/AuditPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { ProjectPage } from './pages/ProjectPage'

export default function App() {
  const me = useMe()

  if (me.isPending) return null
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 401) return <LoginPage />
    return (
      <div className="login">
        <div className="card login-card">
          <p className="error-text">Can't reach webos: {me.error.message}</p>
          <button type="button" className="btn" onClick={() => me.refetch()}>
            Try again
          </button>
        </div>
      </div>
    )
  }

  return (
    <Layout username={me.data.username}>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/projects/:slug" element={<ProjectPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route
          path="*"
          element={
            <p>
              Not found. <Link to="/">Back to the dashboard</Link>
            </p>
          }
        />
      </Routes>
    </Layout>
  )
}
