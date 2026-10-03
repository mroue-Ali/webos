/**
 * Turns ANSI-coloured log text into plain segments. Log lines are attacker-controlled
 * (anyone can put text into a public site's access log), so this never produces HTML:
 * callers render `text` as a React text node and map `fg` through fixed class names.
 */

export interface Segment {
  text: string
  fg: string | null
  bold: boolean
}

const COLORS = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']

// CSI (ESC [ ... final byte), OSC (ESC ] ... BEL or ESC \), and two-byte escapes.
// eslint-disable-next-line no-control-regex
const ESCAPES = /\x1b\[([0-9;?]*)([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]/g
// Remaining control characters (keeps tab).
// eslint-disable-next-line no-control-regex
const CONTROL = /[\x00-\x08\x0b-\x1f\x7f]/g

export function parseAnsi(input: string): Segment[] {
  const segments: Segment[] = []
  let fg: string | null = null
  let bold = false
  let last = 0

  const push = (raw: string) => {
    const text = raw.replace(CONTROL, '')
    if (!text) return
    const prev = segments.at(-1)
    if (prev && prev.fg === fg && prev.bold === bold) prev.text += text
    else segments.push({ text, fg, bold })
  }

  for (const match of input.matchAll(ESCAPES)) {
    push(input.slice(last, match.index))
    last = match.index + match[0].length
    if (match[2] !== 'm') continue // only colours; cursor movement etc. is dropped

    const codes = (match[1] || '0').split(';').map((c) => Number(c || 0))
    for (let i = 0; i < codes.length; i++) {
      const code = codes[i]
      if (code === 0) {
        fg = null
        bold = false
      } else if (code === 1) bold = true
      else if (code === 22) bold = false
      else if (code >= 30 && code <= 37) fg = COLORS[code - 30]
      else if (code >= 90 && code <= 97) fg = `bright-${COLORS[code - 90]}`
      else if (code === 39) fg = null
      else if (code === 38 || code === 48) {
        // 256-colour (5;n) and truecolour (2;r;g;b): skip their arguments.
        i += codes[i + 1] === 5 ? 2 : codes[i + 1] === 2 ? 4 : 0
      }
    }
  }
  push(input.slice(last))
  return segments
}

export function stripAnsi(input: string): string {
  return parseAnsi(input)
    .map((s) => s.text)
    .join('')
}
