/** A filled bar for "used of total". Colour turns warning at 75% and critical at 90%. */
export function Meter({ used, total, label }: { used: number; total: number; label: string }) {
  const percent = total > 0 ? Math.min(100, (used / total) * 100) : 0
  const tone = percent >= 90 ? 'bad' : percent >= 75 ? 'warn' : 'ok'
  return (
    <div
      className={`meter ${tone}`}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(percent)}
      title={`${Math.round(percent)}% used`}
    >
      <div className="meter-fill" style={{ width: `${percent}%` }} />
    </div>
  )
}
