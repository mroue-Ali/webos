import { createContext, useContext } from 'react'
import type { StreamStatus } from '../lib/useEventSource'
import { APPS, isTarget, parsePath, targetKey, type AppId, type Target } from './apps'

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export interface Size {
  w: number
  h: number
}

/** Maximised, or tiled to one half. The floating `rect` is kept for when it's restored. */
export type Snap = 'full' | 'left' | 'right'

export interface Win {
  key: string
  target: Target
  rect: Rect
  snap: Snap | null
  minimized: boolean
  z: number
}

export interface DesktopState {
  windows: Win[]
  /** The highest z handed out so far. */
  z: number
}

export type DesktopAction =
  | { type: 'open'; target: Target; area: Size }
  | { type: 'close'; key: string }
  | { type: 'focus'; key: string }
  | { type: 'minimize'; key: string }
  | { type: 'toggleMax'; key: string }
  | { type: 'place'; key: string; rect: Rect; snap: Snap | null }

export const MIN_W = 360
export const MIN_H = 240
/** Gap kept around maximised and tiled windows. */
export const GAP = 8

/** The window in front, which is the one the URL and the dock highlight. */
export function topWindow(windows: Win[]): Win | null {
  let top: Win | null = null
  for (const w of windows) if (!w.minimized && (!top || w.z > top.z)) top = w
  return top
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), Math.max(min, max))

function placeWindow(app: AppId, windows: Win[], area: Size): Rect {
  const [prefW, prefH] = APPS[app].size
  const w = Math.min(prefW, Math.max(MIN_W, area.w - 2 * GAP))
  const h = Math.min(prefH, Math.max(MIN_H, area.h - 2 * GAP))
  // Centred, nudged left of the widgets, and cascaded so a new window never hides another.
  const step = (windows.filter((win) => !win.minimized).length % 6) * 28
  return {
    w,
    h,
    x: clamp(Math.round((area.w - w) / 2) - 60 + step, GAP, area.w - w - GAP),
    y: clamp(Math.round((area.h - h) / 2) - 30 + step, GAP, area.h - h - GAP),
  }
}

/** Where a window is drawn in an area of this size. Never off-screen past its title bar. */
export function frameRect(win: Pick<Win, 'rect' | 'snap'>, area: Size): Rect {
  const half = Math.round((area.w - 3 * GAP) / 2)
  const h = area.h - 2 * GAP
  if (win.snap === 'full') return { x: GAP, y: GAP, w: area.w - 2 * GAP, h }
  if (win.snap === 'left') return { x: GAP, y: GAP, w: half, h }
  if (win.snap === 'right') return { x: area.w - GAP - half, y: GAP, w: half, h }
  const w = Math.min(win.rect.w, area.w)
  const height = Math.min(win.rect.h, area.h)
  return {
    w,
    h: height,
    x: clamp(win.rect.x, 120 - w, area.w - 120),
    y: clamp(win.rect.y, 0, area.h - 44),
  }
}

function update(state: DesktopState, key: string, change: (w: Win) => Win): DesktopState {
  return { ...state, windows: state.windows.map((w) => (w.key === key ? change(w) : w)) }
}

export function reducer(state: DesktopState, action: DesktopAction): DesktopState {
  switch (action.type) {
    case 'open': {
      const key = targetKey(action.target)
      const z = state.z + 1
      if (state.windows.some((w) => w.key === key)) {
        return update({ ...state, z }, key, (w) => ({
          ...w,
          // Keep the same object when nothing changed, so the content doesn't re-render.
          target: JSON.stringify(w.target) === JSON.stringify(action.target) ? w.target : action.target,
          minimized: false,
          z,
        }))
      }
      const rect = placeWindow(action.target.app, state.windows, action.area)
      return { z, windows: [...state.windows, { key, target: action.target, rect, snap: null, minimized: false, z }] }
    }
    case 'close':
      return { ...state, windows: state.windows.filter((w) => w.key !== action.key) }
    case 'focus': {
      if (topWindow(state.windows)?.key === action.key) return state
      const z = state.z + 1
      return update({ ...state, z }, action.key, (w) => ({ ...w, minimized: false, z }))
    }
    case 'minimize':
      return update(state, action.key, (w) => ({ ...w, minimized: true }))
    case 'toggleMax':
      return update(state, action.key, (w) => ({ ...w, snap: w.snap ? null : 'full' }))
    case 'place':
      return update(state, action.key, (w) => ({ ...w, rect: action.rect, snap: action.snap }))
  }
}

// The layout is remembered per browser, like any desktop. It holds window positions and
// which pages are open, nothing else.
const STORAGE_KEY = 'webos.desktop'

interface Saved {
  target: Target
  rect: Rect
  snap: Snap | null
  minimized: boolean
}

const isRect = (r: unknown): r is Rect =>
  typeof r === 'object' &&
  r !== null &&
  ['x', 'y', 'w', 'h'].every((k) => Number.isFinite((r as Record<string, unknown>)[k]))

export function saveDesktop(state: DesktopState) {
  const windows: Saved[] = [...state.windows]
    .sort((a, b) => a.z - b.z)
    .map(({ target, rect, snap, minimized }) => ({ target, rect, snap, minimized }))
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ windows }))
  } catch {
    // Storage blocked or full: the layout just isn't remembered.
  }
}

function loadSaved(): Saved[] | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    const list = (parsed as { windows?: unknown }).windows
    if (!Array.isArray(list)) return null
    return list.filter(
      (s): s is Saved =>
        isTarget(s?.target) &&
        isRect(s.rect) &&
        (s.snap === null || s.snap === 'full' || s.snap === 'left' || s.snap === 'right') &&
        typeof s.minimized === 'boolean',
    )
  } catch {
    return null
  }
}

/** The usable desktop before it has been measured: the viewport above the dock. */
export function estimateArea(): Size {
  const mobile = window.matchMedia('(max-width: 720px)').matches
  return { w: window.innerWidth, h: window.innerHeight - (mobile ? 60 : 84) }
}

/**
 * The saved layout, plus whatever the URL points at. A first visit opens Projects, so the
 * panel never starts on an empty screen.
 */
export function initialDesktop(): DesktopState {
  const saved = loadSaved()
  let state: DesktopState = { windows: [], z: 0 }
  const seen = new Set<string>()
  for (const s of saved ?? []) {
    const key = targetKey(s.target)
    if (seen.has(key)) continue
    seen.add(key)
    state = { z: state.z + 1, windows: [...state.windows, { ...s, key, z: state.z + 1 }] }
  }
  const fromUrl = parsePath(window.location.pathname, window.location.search)
  const first = fromUrl ?? (saved === null ? { app: 'projects' as const } : null)
  if (first) state = reducer(state, { type: 'open', target: first, area: estimateArea() })
  return state
}

export interface DesktopApi {
  open: (target: Target) => void
  close: (key: string) => void
  focus: (key: string) => void
  minimize: (key: string) => void
  toggleMaximize: (key: string) => void
  place: (key: string, rect: Rect, snap: Snap | null) => void
}

export const DesktopContext = createContext<DesktopApi | null>(null)

export function useDesktop(): DesktopApi {
  const api = useContext(DesktopContext)
  if (!api) throw new Error('useDesktop outside the desktop')
  return api
}

export interface WindowApi {
  key: string
  minimized: boolean
  close: () => void
}

export const WindowContext = createContext<WindowApi | null>(null)

/** The window this content is shown in. */
export function useWindow(): WindowApi | null {
  return useContext(WindowContext)
}

/** Whether Docker events are streaming, shared by the desktop with every window. */
export const LiveContext = createContext<StreamStatus>('connecting')

export function useLive(): StreamStatus {
  return useContext(LiveContext)
}
