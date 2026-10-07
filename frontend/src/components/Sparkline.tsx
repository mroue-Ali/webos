import { useState, type PointerEvent } from 'react'
import { formatTime } from '../lib/format'
import { linePath } from '../lib/spark'

export interface SparkSeries {
  label: string
  values: (number | null)[]
  /** CSS class that sets the series colour (series-1, series-2). */
  tone: 'series-1' | 'series-2'
}

const W = 300
const H = 56

const path = (values: (number | null)[], max: number) => linePath(values, max, W, H)

/**
 * A small trend line with a hover readout. One series: soft area fill. Two series: the
 * caller shows a legend. `max` fixes the scale (100 for percentages); otherwise it fits
 * the data.
 */
export function Sparkline({
  ts,
  series,
  max,
  format,
  label,
}: {
  ts: number[]
  series: SparkSeries[]
  max?: number
  format: (value: number | null) => string
  label: string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const n = ts.length
  const peak = Math.max(0, ...series.flatMap((s) => s.values.filter((v): v is number => v !== null)))
  const scaleMax = max ?? (peak > 0 ? peak * 1.15 : 1)

  function onMove(event: PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    const fraction = (event.clientX - rect.left) / rect.width
    setHover(n > 1 ? Math.max(0, Math.min(n - 1, Math.round(fraction * (n - 1)))) : null)
  }

  if (n < 2) {
    return <div className="spark spark-empty muted small">Collecting data…</div>
  }

  const left = hover === null ? 0 : (hover / (n - 1)) * 100
  return (
    <div
      className="spark"
      onPointerMove={onMove}
      onPointerLeave={() => setHover(null)}
      role="img"
      aria-label={label}
    >
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
        {series.length === 1 && (
          <path
            className={`spark-area ${series[0].tone}`}
            d={`${path(series[0].values, scaleMax)}L${W},${H}L0,${H}Z`}
          />
        )}
        {series.map((s) => (
          <path
            key={s.label}
            className={`spark-line ${s.tone}`}
            d={path(s.values, scaleMax)}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      {hover !== null && (
        <>
          <div className="spark-cursor" style={{ left: `${left}%` }} />
          <div className={`spark-tip ${left > 60 ? 'flip' : ''}`} style={{ left: `${left}%` }}>
            <div className="muted">{formatTime(new Date(ts[hover] * 1000).toISOString())}</div>
            {series.map((s) => (
              <div key={s.label}>
                {series.length > 1 && <span className={`swatch ${s.tone}`} />}
                {series.length > 1 && `${s.label} `}
                <strong>{format(s.values[hover])}</strong>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
