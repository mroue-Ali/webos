const pad = (n: number) => String(n).padStart(2, '0')

/** Local date and time, e.g. 2026-10-01 13:04:05. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${formatTime(iso)}`
}

/** Local time of day, e.g. 13:04:05. */
export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

/** 1,536 → "1.5 KB" (binary units, like `free -h` and `df -h`). */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—'
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit++
  }
  const shown = unit === 0 || value >= 100 ? Math.round(value) : value.toFixed(1)
  return `${shown} ${UNITS[unit]}`
}

export function formatRate(bytesPerSecond: number | null | undefined): string {
  return bytesPerSecond === null || bytesPerSecond === undefined
    ? '—'
    : `${formatBytes(bytesPerSecond)}/s`
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value < 10 ? `${value.toFixed(1)}%` : `${Math.round(value)}%`
}

/** 273,600 → "3d 4h". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days) return `${days}d ${hours}h`
  if (hours) return `${hours}h ${minutes}m`
  return `${minutes}m`
}
