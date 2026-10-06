import { parseAnsi } from '../lib/ansi'

/** One log line. Text nodes only: colours map to fixed class names, never to markup. */
export function LogText({ text }: { text: string }) {
  return (
    <>
      {parseAnsi(text).map((s, i) => (
        <span
          key={i}
          className={[s.fg && `ansi-${s.fg}`, s.bold && 'ansi-bold'].filter(Boolean).join(' ') || undefined}
        >
          {s.text}
        </span>
      ))}
    </>
  )
}
