import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api } from './client'
import type { Action, AuditPage, LoginResult, Me, Overview, ServerStats } from './types'

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
