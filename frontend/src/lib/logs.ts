import { stripAnsi } from './ansi'

// Whole words only, so "/errors-page" in an access log doesn't count.
const ERROR_MARKERS =
  /(^|[^\w/-])(error|exception|traceback|fatal|panic|critical|segfault)([^\w/-]|$)/i

export function isErrorLine(text: string): boolean {
  return ERROR_MARKERS.test(stripAnsi(text))
}
