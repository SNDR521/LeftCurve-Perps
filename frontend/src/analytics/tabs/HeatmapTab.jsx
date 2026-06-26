import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fmt$, Loading, Empty, ErrorBox } from './_ui'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function HeatmapTab({ tabKey, params, fetch }) {
  const [metric, setMetric] = useState('total_pnl')

  const { data: cells = [], isLoading, isError } = useQuery({
    queryKey: [tabKey, params],
    queryFn: () => fetch(params),
    // no normalize — raw cells are identical for both venues
  })

  // Build a 7×24 matrix
  const matrix = useMemo(() => {
    const m = Array.from({ length: 7 }, () => Array(24).fill(null))
    cells.forEach(c => { m[c.weekday][c.hour] = c })
    return m
  }, [cells])

  // Compute min/max for colour scale
  const values = cells.map(c => metric === 'win_rate' ? c.win_rate : c.total_pnl)
  const maxAbs = Math.max(...values.map(Math.abs), 1)

  function cellBg(cell) {
    if (!cell || cell.trade_count === 0) return '#1e2024'
    const v = metric === 'win_rate' ? cell.win_rate : cell.total_pnl
    if (metric === 'win_rate') {
      const t = (cell.win_rate - 50) / 50  // -1 to 1 relative to 50%
      if (t > 0) return `rgba(0,212,170,${Math.min(t * 0.9 + 0.1, 0.9).toFixed(2)})`
      return `rgba(255,90,90,${Math.min(-t * 0.9 + 0.1, 0.9).toFixed(2)})`
    }
    const t = v / maxAbs
    if (t > 0) return `rgba(0,212,170,${Math.min(t * 0.9 + 0.1, 0.9).toFixed(2)})`
    return `rgba(255,90,90,${Math.min(-t * 0.9 + 0.1, 0.9).toFixed(2)})`
  }

  if (isLoading) return <Loading />
  if (isError) return <ErrorBox />

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="tab-bar">
          <button onClick={() => setMetric('total_pnl')} className={`tab-item ${metric === 'total_pnl' ? 'active' : ''}`}>P&amp;L</button>
          <button onClick={() => setMetric('win_rate')} className={`tab-item ${metric === 'win_rate' ? 'active' : ''}`}>Win Rate</button>
        </div>
        <p className="text-[11px] text-[#4e5166]">Hover a cell for details · hours in UTC</p>
      </div>

      <div className="card p-5 overflow-x-auto">
        <div className="min-w-[720px]">
          {/* Hour header */}
          <div className="flex mb-1 ml-10">
            {Array.from({ length: 24 }, (_, h) => (
              <div key={h} className="flex-1 text-center text-[9px] text-[#4e5166]">
                {h % 4 === 0 ? `${h}h` : ''}
              </div>
            ))}
          </div>

          {/* Rows */}
          {WEEKDAYS.map((day, wd) => (
            <div key={wd} className="flex items-center gap-0 mb-[3px]">
              <div className="w-10 text-[10px] text-[#4e5166] shrink-0">{day}</div>
              {matrix[wd].map((cell, hr) => {
                const bg = cellBg(cell)
                return (
                  <div key={hr} className="flex-1 mx-px">
                    <div
                      className="heatmap-cell relative rounded-sm cursor-default"
                      style={{ height: 22, background: bg }}
                      title={cell ? `${day} ${hr}:00 UTC\n${cell.trade_count} trade${cell.trade_count !== 1 ? 's' : ''}\nP&L: ${fmt$(cell.total_pnl)}\nWin: ${cell.win_rate.toFixed(0)}%` : ''}
                    />
                  </div>
                )
              })}
            </div>
          ))}

          {/* Legend */}
          <div className="flex items-center gap-3 mt-4 text-[10px] text-[#4e5166]">
            <span>Low</span>
            <div className="flex gap-px">
              {[0.1, 0.3, 0.5, 0.7, 0.9].map(o => (
                <div key={o} className="w-6 h-3 rounded-sm" style={{ background: `rgba(255,90,90,${o})` }} />
              ))}
              <div className="w-4 h-3 rounded-sm mx-1" style={{ background: '#1e2024', border: '1px solid #2a2c30' }} />
              {[0.1, 0.3, 0.5, 0.7, 0.9].map(o => (
                <div key={o} className="w-6 h-3 rounded-sm" style={{ background: `rgba(0,212,170,${o})` }} />
              ))}
            </div>
            <span>High</span>
          </div>
        </div>
      </div>

      {cells.length === 0 && (
        <Empty>No trade data yet</Empty>
      )}
    </div>
  )
}
