import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api } from './client'
import type {
  Action,
  AgentStatus,
  AuditPage,
  Deployment,
  DeploymentDetail,
  DomainCheck,
  EnvContent,
  LoginResult,
  Me,
  Overview,
  ServerStats,
  SiteConfig,
  SiteCreated,
  SiteInspect,
  SitePreview,
} from './types'

export const keys = {
  me: ['me'] as const,
  overview: ['overview'] as const,
  audit: (action: string, target: string) => ['audit', action, target] as const,
}

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => api<Me>('/api/auth/me'),
    retry: false,
    // Refetching while signed out would briefly unmount the login form and wipe what was
    // typed into it, so only re-check on focus while signed in.
    refetchOnWindowFocus: (query) => query.state.status === 'success',
  })
}

export function useOverview() {
  return useQuery({
    queryKey: keys.overview,
    queryFn: () => api<Overview>('/api/overview'),
    refetchInterval: 30_000, // fallback; live events trigger refetches sooner
  })
}

/** Host resources and per-container usage, refreshed every 5 s while the tab is visible. */
export function useServer() {
  return useQuery({
    queryKey: ['server'],
    queryFn: () => api<ServerStats>('/api/server'),
    refetchInterval: 5_000,
  })
}

export function useAudit(action: string, target: string) {
  return useInfiniteQuery({
    queryKey: keys.audit(action, target),
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: '50' })
      if (action) params.set('action', action)
      if (target) params.set('target', target)
      if (pageParam) params.set('before', String(pageParam))
      return api<AuditPage>(`/api/audit?${params}`)
    },
    getNextPageParam: (last) => last.next_before,
  })
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { username: string; password: string; code?: string }) =>
      api<LoginResult>('/api/auth/login', { method: 'POST', body }),
    onSuccess: (result) => {
      if (result.username) client.setQueryData<Me>(keys.me, { username: result.username })
    },
  })
}

export function useLogout(everywhere: boolean) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api<void>(everywhere ? '/api/auth/logout-all' : '/api/auth/logout', { method: 'POST' }),
    onSettled: () => {
      client.clear()
      void client.invalidateQueries({ queryKey: keys.me })
    },
  })
}

/** Start/stop/restart one container, or a whole project. `confirm` names the target. */
export function useAction() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (v: { kind: 'container' | 'project'; id: string; action: Action; confirm: string }) =>
      api(`/api/${v.kind === 'container' ? 'containers' : 'projects'}/${v.id}/${v.action}`, {
        method: 'POST',
        body: { confirm: v.confirm },
      }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.overview }),
  })
}

export function useImportProject() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { compose_project: string; slug?: string; display_name?: string }) =>
      api('/api/projects', { method: 'POST', body }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.overview }),
  })
}

export function useUpdateProject(slug: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, string | number | null>) =>
      api(`/api/projects/${slug}`, { method: 'PATCH', body }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.overview }),
  })
}

export function useUnregisterProject() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      api(`/api/projects/${slug}`, { method: 'DELETE', body: { confirm: slug } }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.overview }),
  })
}

// --- sites and deployments ------------------------------------------------------------------

export function useAgent() {
  return useQuery({ queryKey: ['agent'], queryFn: () => api<AgentStatus>('/api/agent') })
}

export function useDeployKey() {
  return useMutation({
    mutationFn: (name: string) =>
      api<{ public_key: string }>('/api/sites/deploy-key', { method: 'POST', body: { name } }),
  })
}

export function useCreateSite() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; repo: string; branch: string }) =>
      api<SiteCreated>('/api/sites', { method: 'POST', body }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.overview }),
  })
}

export function useComposeFiles(slug: string | null) {
  return useQuery({
    queryKey: ['compose-files', slug],
    queryFn: () => api<string[]>(`/api/sites/${slug}/compose-files`),
    enabled: !!slug,
  })
}

export function useInspect(slug: string | null, composeFile: string | null) {
  return useQuery({
    queryKey: ['inspect', slug, composeFile],
    queryFn: () =>
      api<SiteInspect>(
        `/api/sites/${slug}/inspect?compose_file=${encodeURIComponent(composeFile ?? '')}`,
      ),
    enabled: !!slug && !!composeFile,
    staleTime: Infinity,
  })
}

export function usePreview(slug: string) {
  return useMutation({
    mutationFn: (config: SiteConfig) =>
      api<SitePreview>(`/api/sites/${slug}/preview`, { method: 'POST', body: config }),
  })
}

export function useCheckDomain() {
  return useMutation({
    mutationFn: (domain: string) =>
      api<DomainCheck>(`/api/sites/check-domain?domain=${encodeURIComponent(domain)}`),
  })
}

export interface DeploySiteBody extends SiteConfig {
  domain: string
  aliases: string[]
  override: string
  env: string
  auto_deploy: boolean
}

export function useDeploySite(slug: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: DeploySiteBody) =>
      api<{ deployment_id: number }>(`/api/sites/${slug}/deploy`, { method: 'POST', body }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.overview }),
  })
}

export function useDiscardDraft() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      api(`/api/sites/${slug}`, { method: 'DELETE', body: { confirm: slug } }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.overview }),
  })
}

export function useDeployments(slug: string, live: boolean) {
  return useQuery({
    queryKey: ['deployments', slug],
    queryFn: () => api<Deployment[]>(`/api/projects/${slug}/deployments`),
    refetchInterval: live ? 3_000 : 30_000,
  })
}

export function useDeployment(id: number | null) {
  return useQuery({
    queryKey: ['deployment', id],
    queryFn: () => api<DeploymentDetail>(`/api/deployments/${id}`),
    enabled: id !== null,
  })
}

export function useRedeploy() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      api<{ deployment_id: number }>(`/api/projects/${slug}/deploy`, {
        method: 'POST',
        body: { confirm: slug },
      }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.overview })
      void client.invalidateQueries({ queryKey: ['deployments'] })
    },
  })
}

export function useUpdateSite(slug: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { auto_deploy?: boolean; override?: string }) =>
      api(`/api/projects/${slug}/site`, { method: 'PATCH', body }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.overview }),
  })
}

/** Reading the .env is audited, so it's fetched on an explicit click, not on page load. */
export function useReadEnv(slug: string) {
  return useMutation({
    mutationFn: () => api<EnvContent>(`/api/projects/${slug}/env`),
  })
}

export function useUpdateEnv(slug: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (content: string) =>
      api<{ deployment_id: number }>(`/api/projects/${slug}/env`, {
        method: 'PUT',
        body: { content, confirm: slug },
      }),
    onSettled: () => client.invalidateQueries({ queryKey: ['deployments'] }),
  })
}

export function useRemoveSite(slug: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { delete_files: boolean; delete_volumes: boolean; code?: string }) =>
      api<{ log: string[] }>(`/api/projects/${slug}/remove`, {
        method: 'POST',
        body: { ...body, confirm: slug },
      }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.overview }),
  })
}
