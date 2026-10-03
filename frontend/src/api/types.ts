// Mirrors backend/webos/schemas.py.

export interface Me {
  username: string
}

/** Signed in, or (with 2FA on) the password was right and the code is needed next. */
export interface LoginResult {
  username: string | null
  code_required: boolean
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

export interface ContainerUsage {
  id: string
  name: string
  project: string | null
  cpu_percent: number // share of the whole machine
  memory_used: number
  memory_limit: number
  net_rx: number
  net_tx: number
}

export interface NetworkInterface {
  name: string
  rx_bytes: number
  tx_bytes: number
  rx_rate: number | null
  tx_rate: number | null
}

export interface ServerStats {
  host: {
    hostname: string | null
    os: string | null
    kernel: string | null
    cpus: number | null
    docker_version: string | null
    uptime_seconds: number | null
  }
  cpu: { percent: number | null; load: number[] | null }
  memory: {
    total: number
    used: number
    available: number
    swap_total: number | null
    swap_used: number | null
  } | null
  disk: { total: number; used: number; free: number } | null
  docker_disk: {
    images: number
    images_reclaimable: number
    containers: number
    volumes: number
    build_cache: number
    build_cache_reclaimable: number
  } | null
  network: NetworkInterface[] | null
  history: {
    interval_seconds: number
    ts: number[]
    cpu: (number | null)[]
    memory: (number | null)[]
    rx: (number | null)[]
    tx: (number | null)[]
  }
  containers: ContainerUsage[]
}
