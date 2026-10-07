import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

// The choice is a per-browser convenience; until one is made, the system setting wins.
const KEY = 'webos.theme'
const listeners = new Set<() => void>()
const media = window.matchMedia('(prefers-color-scheme: dark)')

function stored(): Theme | null {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme
  for (const listener of listeners) listener()
}

function current(): Theme {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

/** Sets the theme before the first render, and follows the system until one is chosen. */
export function initTheme() {
  apply(stored() ?? (media.matches ? 'dark' : 'light'))
  media.addEventListener('change', () => {
    if (!stored()) apply(media.matches ? 'dark' : 'light')
  })
}

export function toggleTheme() {
  const next: Theme = current() === 'dark' ? 'light' : 'dark'
  try {
    localStorage.setItem(KEY, next)
  } catch {
    // Storage blocked: the switch still applies until the page reloads.
  }
  apply(next)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, current)
}
