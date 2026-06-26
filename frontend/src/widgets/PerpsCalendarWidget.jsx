import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useDashboard } from '../dashboard/DashboardContext'
import { ChevronLeft, ChevronRight } from 'lucide-react'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function fmt(val, { sign = true, dollar = true } = {}) {
  const abs = Math.abs(val)
  const num = Math.round(abs).toLocaleString('de-DE')
  const prefix = sign ? (val >= 0 ? '+' : '-') : (val < 0 ? '-' : '')
  return `${prefix}${dollar ? '$' : ''}${num}`
}

function fmtCompact(val) {
  const abs = Math.abs(val)
  const sign = val >= 0 ? '+' : '-'
  if (abs >= 10000) return `${sign}$${(abs / 1000).toFixed(1).replace('.', ',')}k`
  return fmt(val)
}

export default function PerpsCalendarWidget() {
  const { queryParams, fetchers } = useDashboard()
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth())

  const { data: allPnl = [] } = useQuery({
    queryKey: ['perps-daily-pnl', queryParams],
    queryFn: () => fetchers.fetchDailyPnl(queryParams),
  })

  const prefix = `${year}-${String(month + 1).padStart(2, '0')}`
  const monthData = useMemo(() => allPnl.filter(d => d.date.startsWith(prefix)), [allPnl, prefix])

  const grid = useMemo(() => {
    const lookup = {}
    monthData.forEach(d => { lookup[d.date] = d })
    const first = new Date(year, month, 1)
    const last = new Date(year, month + 1, 0)
    const cells = []
    const startDow = (first.getDay() + 6) % 7
    for (let i = 0; i < startDow; i++) cells.push(null)
    for (let d = 1; d <= last.getDate(); d++) {
      const ds = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
      cells.push({ day: d, date: ds, ...(lookup[ds] || { pnl: 0, trade_count: 0 }) })
    }
    return cells
  }, [monthData, year, month])

  const maxAbs = useMemo(() => Math.max(...monthData.map(d => Math.abs(d.pnl)).filter(Boolean), 1), [monthData])

  const summary = useMemo(() => ({
    pnl: monthData.reduce((s, d) => s + d.pnl, 0),
    trades: monthData.reduce((s, d) => s + d.trade_count, 0),
    green: monthData.filter(d => d.pnl > 0).length,
    red: monthData.filter(d => d.pnl < 0).length,
  }), [monthData])

  function prev() { if (month === 0) { setYear(y => y - 1); setMonth(11) } else setMonth(m => m - 1) }
  function next() { if (month === 11) { setYear(y => y + 1); setMonth(0) } else setMonth(m => m + 1) }

  const monthName = new Date(year, month).toLocaleString('en', { month: 'long', year: 'numeric' })

  // Same visual language as the calendar page: bordered cells, capped tint —
  // readability comes from the colored P&L text, not the fill.
  function cellStyle(pnl) {
    if (!pnl) return { background: '#191b1e', border: '1px solid #232529' }
    const i = Math.min(Math.abs(pnl) / maxAbs, 1)
    const a = 0.06 + i * 0.22
    const c = pnl > 0 ? '0, 212, 170' : '222, 87, 111'
    return { background: `rgba(${c}, ${a})`, border: `1px solid rgba(${c}, ${Math.min(a + 0.18, 0.5)})` }
  }

  const tNow = new Date()
  const todayStr = `${tNow.getFullYear()}-${String(tNow.getMonth() + 1).padStart(2, '0')}-${String(tNow.getDate()).padStart(2, '0')}`

  return (
    <div className="h-full flex flex-col gap-1">
      {/* Header */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-1">
          <button onClick={prev} className="p-1 hover:bg-[#2a2c30] rounded-md transition-colors">
            <ChevronLeft className="w-3.5 h-3.5 text-[#4e5166]" />
          </button>
          <span className="text-[12px] font-semibold text-white w-32 text-center">{monthName}</span>
          <button onClick={next} className="p-1 hover:bg-[#2a2c30] rounded-md transition-colors">
            <ChevronRight className="w-3.5 h-3.5 text-[#4e5166]" />
          </button>
        </div>

        {/* Mini summary */}
        <div className="flex items-center gap-3 text-[10px]">
          <span className={`font-mono font-semibold tabular-nums ${summary.pnl >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
            {fmt(summary.pnl)}
          </span>
          <span className="text-[#4e5166]">{summary.trades} trades</span>
          <span className="text-[#00d4aa]">{summary.green}W</span>
          <span className="text-[#de576f]">{summary.red}L</span>
        </div>
      </div>

      {/* Day headers */}
      <div className="grid gap-1 px-1" style={{ gridTemplateColumns: 'repeat(7, 1fr) 3.5rem' }}>
        {DAYS.map(d => (
          <div key={d} className="text-center text-[9px] font-semibold text-[#3a3c42] uppercase">{d}</div>
        ))}
        <div />
      </div>

      {/* Calendar grid — rows of 7 + weekly summary */}
      <div className="flex flex-col gap-1 flex-1 px-1">
        {Array.from({ length: Math.ceil(grid.length / 7) }, (_, wi) => {
          const row = grid.slice(wi * 7, wi * 7 + 7)
          const tradingCells = row.filter(c => c && c.trade_count > 0)
          const weekPnl = tradingCells.reduce((s, c) => s + c.pnl, 0)
          const weekWins = tradingCells.reduce((s, c) => s + (c.wins || 0), 0)
          const weekLosses = tradingCells.reduce((s, c) => s + (c.losses || 0), 0)
          const hasData = tradingCells.length > 0
          return (
            <div key={wi} className="grid gap-1 flex-1" style={{ gridTemplateColumns: 'repeat(7, 1fr) 3.5rem' }}>
              {row.map((cell, ci) =>
                cell === null ? (
                  <div key={`e${wi}-${ci}`} className="rounded-md" />
                ) : (
                  <div
                    key={cell.date}
                    className={`relative rounded-md flex flex-col items-center justify-center
                               transition-all duration-100 hover:brightness-125 cursor-default min-h-0 overflow-hidden ${
                      cell.date === todayStr ? 'ring-1 ring-[#38bdf8]/50' : ''
                    }`}
                    style={cellStyle(cell.pnl)}
                    // native title instead of a floated tooltip — a custom popup
                    // rendered above top-row cells escaped the widget and bled
                    // into the pane above it on the dashboard grid
                    title={cell.trade_count > 0 ? `${cell.date} · ${cell.wins ?? 0}W ${cell.losses ?? 0}L` : undefined}
                  >
                    <span className={`absolute top-0.5 left-1 text-[8px] font-medium leading-none ${
                      cell.trade_count > 0 ? 'text-[#e2e4ef]' : 'text-[#4e5166]'
                    }`}>{cell.day}</span>
                    {cell.trade_count > 0 && (
                      <span className={`text-[9.5px] font-mono font-bold tabular-nums leading-none tracking-tight ${
                        cell.pnl > 0 ? 'text-[#00d4aa]' : cell.pnl < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]'
                      }`}>
                        {fmtCompact(cell.pnl)}
                      </span>
                    )}
                    {cell.trade_count > 0 && (
                      <span className="text-[7.5px] font-semibold leading-none tracking-tight mt-0.5">
                        {cell.wins != null
                          ? <><span className="text-[#00d4aa]">{cell.wins}W</span>{' '}<span className="text-[#de576f]">{cell.losses}L</span></>
                          : <span className="text-[#8d91a6]">{cell.trade_count}t</span>}
                      </span>
                    )}
                  </div>
                )
              )}
              {/* Weekly summary — mirrors the page's Week column */}
              <div className="flex flex-col items-center justify-center gap-0.5 rounded-md border border-[#232529] bg-[#191b1e] px-1.5 py-1 min-h-0 h-full">
                {hasData ? (
                  <>
                    <span className={`text-[9px] font-mono font-bold tabular-nums leading-none tracking-tight ${weekPnl >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                      {fmtCompact(weekPnl)}
                    </span>
                    <span className="text-[8px] font-semibold leading-none">
                      <span className="text-[#00d4aa]">{weekWins}W</span>
                      <span className="text-[#4e5166]"> · </span>
                      <span className="text-[#de576f]">{weekLosses}L</span>
                    </span>
                  </>
                ) : (
                  <span className="text-[9px] text-[#33353c]">—</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
