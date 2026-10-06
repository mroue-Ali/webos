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
  // Sites deployed through webos (the new-site wizard).
  managed: boolean
  state: 'draft' | 'active'
  branch: string | null
  compose_file: string | null
  env_file: string | null
  web_service: string | null
  container_port: number | null
  aliases: string[]
  override: string | null
  auto_deploy: boolean
  deployed_commit: string | null
  deploying: boolean
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

export interface AgentStatus {
  available: boolean
  error: string | null
  version: string | null
  apps_root: string | null
  user: string | null
  host_ips: string[]
  compose_version: string | null
  nginx: boolean | null
  certbot: boolean | null
}

export interface ComposeService {
  image: string | null
  build: boolean
  command: string[] | string | null
  ports: { target: number | null; published: string | null; host_ip: string | null }[]
  volumes: { type: string | null; source: string | null; target: string | null }[]
  expose: (string | number)[]
  healthcheck: boolean
}

export interface ServiceChoice {
  keep_volumes: string[] | null
  use_image_command: boolean
}

export interface SiteCreated {
  slug: string
  commit: string
  subject: string
  compose_files: string[]
}

export interface SiteInspect {
  compose_file: string
  services: Record<string, ComposeService>
  violations: string[]
  env_example: string
  suggestion: {
    web_service: string | null
    container_port: number | null
    services: Record<string, ServiceChoice & { dev_mounts: string[] }>
  }
  port: number
  domain_suggestion: string | null
  server_ips: string[]
}

export interface SiteConfig {
  compose_file: string
  env_file: string
  web_service: string
  container_port: number
  services: Record<string, ServiceChoice>
}

export interface SitePreview {
  override: string
  port: number
  violations: string[]
  services: Record<string, ComposeService>
}

export interface DomainCheck {
  domain: string
  resolves_to: string[]
  server_ips: string[]
  ok: boolean
}

export interface Deployment {
  id: number
  trigger: 'create' | 'manual' | 'auto' | 'env'
  status: 'running' | 'ok' | 'failed'
  commit: string | null
  subject: string | null
  actor: string | null
  started_at: string
  finished_at: string | null
  error: string | null
}

export interface DeploymentDetail extends Deployment {
  project: string
  log: string
}

export interface EnvContent {
  content: string
  exists: boolean
}
