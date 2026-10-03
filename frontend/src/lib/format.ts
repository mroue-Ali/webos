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
