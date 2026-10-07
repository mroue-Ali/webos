/** A circle as path data, so every icon is a single stroked path. */
const circle = (cx: number, cy: number, r: number) =>
  `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`

// 24×24 outline glyphs, drawn for webos.
const PATHS = {
  grid: 'M4.5 4.5h5.5V10H4.5zM14 4.5h5.5V10H14zM4.5 14H10v5.5H4.5zM14 14h5.5v5.5H14z',
  projects: 'M12 3.5 20.5 8 12 12.5 3.5 8zM3.5 12 12 16.5 20.5 12M3.5 16 12 20.5 20.5 16',
  server:
    'M7.5 4.5h9a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-9a3 3 0 0 1-3-3v-9a3 3 0 0 1 3-3zM9.5 9.5h5v5h-5zM9.5 2v2.5M14.5 2v2.5M9.5 19.5V22M14.5 19.5V22M2 9.5h2.5M2 14.5h2.5M19.5 9.5H22M19.5 14.5H22',
  rocket:
    'M12 2.5c3.2 2.2 4.8 5.6 4.8 9.8l-2.2 3.2H9.4l-2.2-3.2c0-4.2 1.6-7.6 4.8-9.8z' +
    circle(12, 9.3, 1.7) +
    'M7.6 13.4 4.8 16v3.2l4.3-2.4M16.4 13.4l2.8 2.6v3.2l-4.3-2.4M10.6 18.6V21M13.4 18.6V21',
  audit: 'M12 2.5 19.5 5.8v5.6c0 4.5-3.1 8.4-7.5 9.9-4.4-1.5-7.5-5.4-7.5-9.9V5.8zM8.8 12l2.3 2.3 4.2-4.6',
  globe:
    circle(12, 12, 8.5) +
    'M3.5 12h17M12 3.5c2.3 2.4 3.5 5.2 3.5 8.5s-1.2 6.1-3.5 8.5c-2.3-2.4-3.5-5.2-3.5-8.5s1.2-6.1 3.5-8.5z',
  logs: 'M6.5 3h7.5l4.5 4.5v12a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5.5 19.5v-15A1.5 1.5 0 0 1 7 3zM13.5 3v5h5M8.5 12.5h7M8.5 16h4.5',
  bell: 'M18 10a6 6 0 0 0-12 0c0 5.5-2.2 7-2.2 7h16.4S18 15.5 18 10zM10 20.2a2.3 2.3 0 0 0 4 0',
  search: circle(10.5, 10.5, 6.5) + 'M15.4 15.4 20.5 20.5',
  sun:
    circle(12, 12, 4) +
    'M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4',
  moon: 'M19.5 14.6A8 8 0 0 1 9.4 4.5a8 8 0 1 0 10.1 10.1z',
  expand: 'M4.5 9V5.5a1 1 0 0 1 1-1H9M15 4.5h3.5a1 1 0 0 1 1 1V9M19.5 15v3.5a1 1 0 0 1-1 1H15M9 19.5H5.5a1 1 0 0 1-1-1V15',
  shrink: 'M9 4.5V8a1 1 0 0 1-1 1H4.5M19.5 9H16a1 1 0 0 1-1-1V4.5M15 19.5V16a1 1 0 0 1 1-1h3.5M4.5 15H8a1 1 0 0 1 1 1v3.5',
  refresh: 'M4.5 12a7.5 7.5 0 0 1 13-5.1l2 2.1M19.5 4v5h-5M19.5 12a7.5 7.5 0 0 1-13 5.1l-2-2.1M4.5 20v-5h5',
  plus: 'M12 5v14M5 12h14',
  external: 'M14 4.5h5.5V10M19.5 4.5 11 13M17.5 14v4a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 18V8A1.5 1.5 0 0 1 6 6.5h4',
  logout: 'M10 4.5H6.5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2H10M15 8l4 4-4 4M19 12H9.5',
  play: 'M7.5 5v14l11-7z',
  stop: 'M6.5 6.5h11v11h-11z',
  restart: 'M4.5 12a7.5 7.5 0 1 0 2.2-5.3L4.5 9M4.5 4.5V9H9',
  alert: 'M12 3.5 2.8 19.5h18.4zM12 10v4.2M12 17v.01',
  check: circle(12, 12, 8.5) + 'M8.3 12.3l2.6 2.6 4.8-5.2',
  box: 'M12 3 20 7.3v9.4L12 21l-8-4.3V7.3zM4 7.3l8 4.4 8-4.4M12 11.7V21',
  disk: 'M3.5 13h17M6 5.5h12l2.5 7.5v5a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1v-5zM7.5 16h.01M10.5 16h.01',
  activity: 'M3 12h3.8l2.4-6.2 5.2 12.4 2.4-6.2H21',
  close: 'M7 7l10 10M17 7 7 17',
  minus: 'M6 12h12',
  maximize: 'M13.5 4.5h6v6M10.5 19.5h-6v-6M19.5 4.5 14 10M4.5 19.5 10 14',
  user: circle(12, 8.5, 3.8) + 'M4.8 20a7.2 7.2 0 0 1 14.4 0',
  arrowDown: 'M12 5v14M6.5 13.5 12 19l5.5-5.5',
  arrowUp: 'M12 19V5M6.5 10.5 12 5l5.5 5.5',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
