import { useState, type ReactNode } from 'react'
import { useServer } from '../api/queries'
import type { ContainerUsage, ServerStats } from '../api/types'
import { Meter } from '../components/Meter'
import { Sparkline } from '../components/Sparkline'
import { formatBytes, formatDuration, formatPercent, formatRate } from '../lib/format'

function historyLabel(stats: ServerStats) {
  const minutes = Math.round((stats.history.ts.length * stats.history.interval_seconds) / 60)
  return minutes >= 29 ? 'Last 30 minutes' : `Since the panel started (${minutes} min)`
}

function Tile({ label, value, children }: { label: string; value: ReactNode; children?: ReactNode }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {children}
    </div>
  )
}

export function ServerPage() {
  const server = useServer()
  if (server.isPending) return <p className="muted">Loading…</p>
  if (server.isError) return <p className="error-text">{server.error.message}</p>

  const stats = server.data
  const { host, cpu, memory, disk, network, history } = stats
  const rxNow = network?.reduce((sum, i) => sum + (i.rx_rate ?? 0), 0) ?? null
  const txNow = network?.reduce((sum, i) => sum + (i.tx_rate ?? 0), 0) ?? null
  const span = historyLabel(stats)

  return (
    <>
      <div className="page-head">
        <div>
          {host.hostname && <div className="page-title strong">{host.hostname}</div>}
          <div className="meta muted small">
            {host.os && <span>{host.os}</span>}
            {host.kernel && <span>kernel {host.kernel}</span>}
            {host.cpus && <span>{host.cpus} CPUs</span>}
            <span>up {formatDuration(host.uptime_seconds)}</span>
            {host.docker_version && <span>Docker {host.docker_version}</span>}
          </div>
        </div>
        <span className="muted small">Updates every 5 seconds</span>
      </div>

      <div className="tiles">
        <Tile label="CPU" value={formatPercent(cpu.percent)}>
          <div className="tile-sub muted small">
            {cpu.load ? `Load ${cpu.load.map((l) => l.toFixed(2)).join(' · ')}` : 'Load —'}
          </div>
          <Sparkline
            ts={history.ts}
            series={[{ label: 'CPU', values: history.cpu, tone: 'series-1' }]}
            max={100}
            format={formatPercent}
            label={`CPU use, ${span.toLowerCase()}`}
          />
          <div className="tile-foot muted small">{span}</div>
        </Tile>

        <Tile
          label="Memory"
          value={memory ? `${formatBytes(memory.used)} of ${formatBytes(memory.total)}` : '—'}
        >
          {memory && <Meter used={memory.used} total={memory.total} label="Memory used" />}
          <div className="tile-sub muted small">
            {memory ? `${formatBytes(memory.available)} available` : ''}
            {memory?.swap_total ? ` · swap ${formatBytes(memory.swap_used)} of ${formatBytes(memory.swap_total)}` : ''}
          </div>
          <Sparkline
            ts={history.ts}
            series={[{ label: 'Memory', values: history.memory, tone: 'series-1' }]}
            max={100}
            format={formatPercent}
            label={`Memory used, ${span.toLowerCase()}`}
          />
          <div className="tile-foot muted small">{span}</div>
        </Tile>

        <Tile label="Disk" value={disk ? `${formatBytes(disk.used)} of ${formatBytes(disk.total)}` : '—'}>
          {disk && <Meter used={disk.used} total={disk.total} label="Disk used" />}
          <div className="tile-sub muted small">
            {disk ? `${formatBytes(disk.free)} free · ${formatPercent((disk.used / disk.total) * 100)} used` : ''}
          </div>
          <DockerDisk stats={stats} />
        </Tile>

        <Tile
          label="Network"
          value={
            network ? (
              <span className="net-now">
                <span><span className="swatch series-1" />↓ {formatRate(rxNow)}</span>
                <span><span className="swatch series-2" />↑ {formatRate(txNow)}</span>
              </span>
            ) : (
              '—'
            )
          }
        >
          {network ? (
            <>
              <div className="tile-sub muted small">
                <span className="legend"><span className="swatch series-1" />In</span>
                <span className="legend"><span className="swatch series-2" />Out</span>
              </div>
              <Sparkline
                ts={history.ts}
                series={[
                  { label: 'In', values: history.rx, tone: 'series-1' },
                  { label: 'Out', values: history.tx, tone: 'series-2' },
                ]}
                format={formatRate}
                label={`Network traffic in and out, ${span.toLowerCase()}`}
              />
              <div className="tile-foot muted small">{span}</div>
            </>
          ) : (
            <p className="muted small">Host network counters aren't mounted (see docker-compose.yml).</p>
          )}
        </Tile>
      </div>

      <ContainerUsageTable usage={stats.containers} memoryTotal={memory?.total ?? null} />

      {network && network.length > 0 && (
        <section className="card">
          <div className="card-head">
            <span className="card-title">Network interfaces</span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Interface</th>
                  <th className="num">In now</th>
                  <th className="num">Out now</th>
                  <th className="num">Received since boot</th>
                  <th className="num">Sent since boot</th>
                </tr>
              </thead>
              <tbody>
                {network.map((i) => (
                  <tr key={i.name}>
                    <td className="mono">{i.name}</td>
                    <td className="num">{formatRate(i.rx_rate)}</td>
                    <td className="num">{formatRate(i.tx_rate)}</td>
                    <td className="num">{formatBytes(i.rx_bytes)}</td>
                    <td className="num">{formatBytes(i.tx_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}

function DockerDisk({ stats }: { stats: ServerStats }) {
  const d = stats.docker_disk
  if (!d) return null
  const rows: [string, number, number | null][] = [
    ['Images', d.images, d.images_reclaimable],
    ['Build cache', d.build_cache, d.build_cache_reclaimable],
    ['Volumes', d.volumes, null],
    ['Containers', d.containers, null],
  ]
  return (
    <table className="mini-table small">
      <caption className="muted">Docker's share</caption>
      <tbody>
        {rows.map(([name, size, unused]) => (
          <tr key={name}>
            <td>{name}</td>
            <td className="num">{formatBytes(size)}</td>
            <td className="num muted">{unused ? `${formatBytes(unused)} unused` : ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

type SortKey = 'cpu' | 'memory'

function ContainerUsageTable({
  usage,
  memoryTotal,
}: {
  usage: ContainerUsage[]
  memoryTotal: number | null
}) {
  const [sort, setSort] = useState<SortKey>('memory')
  const rows = [...usage].sort((a, b) =>
    sort === 'cpu' ? b.cpu_percent - a.cpu_percent : b.memory_used - a.memory_used,
  )
  const sortButton = (key: SortKey, text: string) => (
    <button
      type="button"
      className={`sort ${sort === key ? 'active' : ''}`}
      onClick={() => setSort(key)}
      aria-pressed={sort === key}
    >
      {text}
      {sort === key ? ' ↓' : ''}
    </button>
  )

  return (
    <section className="card">
      <div className="card-head">
        <span className="card-title">Running containers by resource use</span>
        <span className="muted small">CPU is a share of the whole server; network is since the container started.</span>
      </div>
      {rows.length === 0 ? (
        <p className="muted pad">No running containers.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Container</th>
                <th className="num">{sortButton('cpu', 'CPU')}</th>
                <th className="num">{sortButton('memory', 'Memory')}</th>
                <th>Memory limit</th>
                <th className="num">Received</th>
                <th className="num">Sent</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const limited = memoryTotal !== null && c.memory_limit > 0 && c.memory_limit < memoryTotal * 0.98
                return (
                  <tr key={c.id}>
                    <td>
                      <div className="strong">{c.name}</div>
                      <div className="muted small">{c.project ?? 'no compose project'}</div>
                    </td>
                    <td className="num">{formatPercent(c.cpu_percent)}</td>
                    <td className="num">{formatBytes(c.memory_used)}</td>
                    <td className="small">
                      {limited ? (
                        <div className="limit">
                          <Meter used={c.memory_used} total={c.memory_limit} label={`${c.name} memory`} />
                          <span className="muted">{formatBytes(c.memory_limit)}</span>
                        </div>
                      ) : (
                        <span className="muted">none</span>
                      )}
                    </td>
                    <td className="num">{formatBytes(c.net_rx)}</td>
                    <td className="num">{formatBytes(c.net_tx)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
