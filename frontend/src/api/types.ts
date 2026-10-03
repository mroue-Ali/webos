// Mirrors backend/webos/schemas.py.

export interface Me {
  username: string
}

export interface Port {
  ip: string
  private_port: number
  public_port: number | null
  protocol: string
  public: boolean
}

export type Warning = 'public_port' | 'restarting' | 'unhealthy' | 'exited_error' | 'oom_killed'

export interface Container {
  id: string
  name: string
  service: string | null
  image: string
  state: string
  status: string
  health: string | null
  ports: Port[]
  restart_count: number
  exit_code: number | null
  oom_killed: boolean
  started_at: string | null
  warnings: Warning[]
  manageable: boolean
}

export interface Project {
  slug: string
  display_name: string
  compose_project: string
  working_dir: string | null
  domain: string | null
  port: number | null
  repo_url: string | null
  created_at: string
  is_self: boolean
  containers: Container[]
}

export interface UnmanagedGroup {
  compose_project: string | null
  working_dir: string | null
  is_self: boolean
  containers: Container[]
}

export interface Overview {
  docker: { version: string; running: number; total: number }
  projects: Project[]
  unmanaged: UnmanagedGroup[]
}

export interface AuditEvent {
  id: number
  ts: string
  request_id: string | null
  actor: string | null
  action: string
  target: string | null
  params: Record<string, unknown>
  outcome: 'started' | 'ok' | 'error'
  error: string | null
  ip: string | null
  user_agent: string | null
}

export interface AuditPage {
  items: AuditEvent[]
  next_before: number | null
}

export type Action = 'start' | 'stop' | 'restart'

export interface LogLine {
  ts: string
  stream: 'stdout' | 'stderr'
  text: string
}
