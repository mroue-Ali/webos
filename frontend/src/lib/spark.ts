/**
 * SVG path data for a line through `values` in a `width`×`height` box, scaled so `max` is
 * the top. A null is a gap in the line, not a drop to zero.
 */
export function linePath(
  values: (number | null)[],
  max: number,
  width: number,
  height: number,
  pad = 3,
): string {
  const step = values.length > 1 ? width / (values.length - 1) : 0
  let d = ''
  let pen = false
  values.forEach((v, i) => {
    if (v === null) {
      pen = false
      return
    }
    const x = i * step
    const y = height - pad - (Math.min(v, max) / max) * (height - 2 * pad)
    d += `${pen ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
    pen = true
  })
  return d
}
