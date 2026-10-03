import { describe, expect, it } from 'vitest'
import { parseAnsi, stripAnsi } from './ansi'
import { isErrorLine } from './logs'

describe('parseAnsi', () => {
  it('passes plain text through as one segment', () => {
    expect(parseAnsi('hello <b>world</b>')).toEqual([
      { text: 'hello <b>world</b>', fg: null, bold: false },
    ])
  })

  it('applies and resets colours', () => {
    expect(parseAnsi('\x1b[1;31mERROR\x1b[0m done')).toEqual([
      { text: 'ERROR', fg: 'red', bold: true },
      { text: ' done', fg: null, bold: false },
    ])
  })

  it('supports bright colours and default foreground', () => {
    expect(parseAnsi('\x1b[92mok\x1b[39m.')).toEqual([
      { text: 'ok', fg: 'bright-green', bold: false },
      { text: '.', fg: null, bold: false },
    ])
  })

  it('skips 256-colour and truecolour arguments', () => {
    expect(parseAnsi('\x1b[38;5;31mx\x1b[38;2;255;0;0my')).toEqual([
      { text: 'xy', fg: null, bold: false },
    ])
  })

  it('drops cursor movement, OSC titles and stray control characters', () => {
    expect(stripAnsi('\x1b[2K\x1b]0;title\x07a\rb\x08c\x1b')).toBe('abc')
  })

  it('keeps tabs', () => {
    expect(stripAnsi('a\tb')).toBe('a\tb')
  })
})

describe('isErrorLine', () => {
  it('matches common error markers, ignoring colour codes', () => {
    expect(isErrorLine('\x1b[31mERROR\x1b[0m: boom')).toBe(true)
    expect(isErrorLine('Traceback (most recent call last):')).toBe(true)
    expect(isErrorLine('panic: runtime error')).toBe(true)
    expect(isErrorLine('GET /errors-page 200')).toBe(false)
    expect(isErrorLine('INFO started')).toBe(false)
  })
})
