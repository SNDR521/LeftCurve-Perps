import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { fetchPerpsDailyPnl, fetchPlanCards } from '../lib/api'
import { useAccount } from '../components/Layout'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Plan-adherence dot for a calendar day. Grey = card but no trades,
// green = adherent with trades, red = breached.
function PlanDot({ card }) {
  if (!card) return null
  let color = '#4e5166'
  let title = 'plan: no trades'
  if (card.trades_count === 0) {
    color = '#4e5166'
    title = 'plan: no trades'
  } else if (card.adherent) {
    color = '#00d4aa'
    title = 'plan: adherent'
  } else {
    color = '#de576f'
    title = 'plan: breached'
  }
  return (
    <span
      className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full"
      style={{ background: color }}
      title={title}
    />
  )
}

export default function PerpsCalendar() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth())
  const { perpsAccountId } = useAccount()

  const { data: allPnl = [] } = useQuery({
    queryKey: ['perps-daily-pnl', perpsAccountId],
    queryFn: () => fetchPerpsDailyPnl({ ...(perpsAccountId && { account_id: perpsAccountId }) }),
  })

  const prefix = `${year}-${String(month + 1).padStart(2, '0')}`

  const from = `${prefix}-01`
  const to = `${prefix}-${String(new Date(year, month + 1, 0).getDate()).padStart(2, '0')}`

  const { data: planCards = [] } = useQuery({
    queryKey: ['plan-cards-range', from, to],
    queryFn: () => fetchPlanCards({ from, to }),
    retry: false,
  })

  const planMap = useMemo(() => {
    const m = {}
    planCards.forEach(c => { m[c.date] = c })
    return m
  }, [planCards])

  const monthData = useMemo(
    () => allPnl.filter(d => d.date.startsWith(prefix)),
    [allPnl, prefix],
  )

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

  const maxAbs = useMemo(
    () => Math.max(...monthData.map(d => Math.abs(d.pnl)).filter(Boolean), 1),
    [monthData],
  )

  const summary = useMemo(() => ({
    pnl: monthData.reduce((s, d) => s + (d.pnl ?? 0), 0),
    trades: monthData.reduce((s, d) => s + (d.trade_count ?? 0), 0),
    green: monthData.filter(d => d.pnl > 0).length,
    red: monthData.filter(d => d.pnl < 0).length,
  }), [monthData])

  function prev() {
    if (month === 0) { setYear(y => y - 1); setMonth(11) }
    else setMonth(m => m - 1)
  }
  function next() {
    if (month === 11) { setYear(y => y + 1); setMonth(0) }
    else setMonth(m => m + 1)
  }

  const monthName = new Date(year, month).toLocaleString('en', { month: 'long', year: 'numeric' })

  // Subtle tint scaled by day size; readability comes from the colored P&L
  // text, not from drowning the cell in color.
  function cellStyle(pnl) {
    if (!pnl) return { background: '#191b1e', border: '1px solid #232529' }
    const intensity = Math.min(Math.abs(pnl) / maxAbs, 1)
    const a = 0.06 + intensity * 0.22
    const c = pnl > 0 ? '0, 212, 170' : '222, 87, 111'
    return { background: `rgba(${c}, ${a})`, border: `1px solid rgba(${c}, ${Math.min(a + 0.18, 0.5)})` }
  }

  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const weeks = useMemo(() => {
    const rows = []
    for (let i = 0; i < grid.length; i += 7) rows.push(grid.slice(i, i + 7))
    return rows
  }, [grid])

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[22px] font-semibold text-white">Perps Calendar</h1>
        <p className="text-[13px] text-[#4e5166] mt-0.5">Monthly P&amp;L overview for your perps trades</p>
      </div>

      {/* Monthly summary */}
      <div className="grid grid-cols-4 gap-3">
        <div className="stat-card text-center">
          <p className="text-[10px] text-[#4e5166] font-semibold uppercase tracking-[0.08em] mb-1">Month P&amp;L</p>
          <p className={`text-[20px] font-mono font-semibold ${summary.pnl >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
            {summary.pnl >= 0 ? '+' : ''}${summary.pnl.toFixed(2)}
          </p>
        </div>
        <div className="stat-card text-center">
          <p className="text-[10px] text-[#4e5166] font-semibold uppercase tracking-[0.08em] mb-1">Trades</p>
          <p className="text-[20px] font-mono font-semibold text-white">{summary.trades}</p>
        </div>
        <div className="stat-card text-center">
          <p className="text-[10px] text-[#4e5166] font-semibold uppercase tracking-[0.08em] mb-1">Green Days</p>
          <p className="text-[20px] font-mono font-semibold text-[#00d4aa]">{summary.green}</p>
        </div>
        <div className="stat-card text-center">
          <p className="text-[10px] text-[#4e5166] font-semibold uppercase tracking-[0.08em] mb-1">Red Days</p>
          <p className="text-[20px] font-mono font-semibold text-[#de576f]">{summary.red}</p>
        </div>
      </div>

      {/* Calendar grid */}
      <div className="card p-5">
        {/* Month navigation */}
        <div className="flex items-center gap-3 mb-4">
          <button onClick={prev} className="btn-ghost p-2">
            <ChevronLeft className="w-5 h-5" />
          </button>
          <span className="text-[16px] font-semibold flex-1 text-center text-white">{monthName}</span>
          <button onClick={next} className="btn-ghost p-2">
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>

        {/* Day headers (7 days + weekly total column) */}
        <div className="grid gap-1.5 mb-1.5" style={{ gridTemplateColumns: 'repeat(7, 1fr) 6rem' }}>
          {DAYS.map(d => (
            <div key={d} className="text-center text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">{d}</div>
          ))}
          <div className="text-center text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">Week</div>
        </div>

        {/* Week rows */}
        <div className="flex flex-col gap-1.5">
          {weeks.map((row, wi) => {
            const traded = row.filter(c => c && c.trade_count > 0)
            const weekPnl = traded.reduce((s, c) => s + (c.pnl ?? 0), 0)
            const weekWins = traded.reduce((s, c) => s + (c.wins || 0), 0)
            const weekLosses = traded.reduce((s, c) => s + (c.losses || 0), 0)
            return (
              <div key={wi} className="grid gap-1.5" style={{ gridTemplateColumns: 'repeat(7, 1fr) 6rem' }}>
                {row.map((cell, ci) =>
                  cell === null ? (
                    <div key={`e${wi}-${ci}`} className="h-[84px] rounded-lg" />
                  ) : (
                    <div
                      key={cell.date}
                      className={`relative h-[84px] rounded-lg p-2 flex flex-col transition-all duration-100 hover:brightness-125 ${
                        cell.date === todayStr ? 'ring-1 ring-[rgb(var(--accent-rgb)/0.5)]' : ''
                      }`}
                      style={cellStyle(cell.pnl)}
                      title={cell.trade_count > 0
                        ? `${cell.date} · ${cell.trade_count} trade${cell.trade_count === 1 ? '' : 's'}${cell.wins != null ? ` · ${cell.wins}W ${cell.losses}L` : ''}`
                        : cell.date}
                    >
                      <div className="flex items-start justify-between">
                        <span className={`text-[11px] font-medium ${cell.trade_count > 0 ? 'text-[#e2e4ef]' : 'text-[#4e5166]'}`}>{cell.day}</span>
                        <PlanDot card={planMap[cell.date]} />
                      </div>
                      {cell.trade_count > 0 && (
                        <div className="flex-1 flex flex-col items-center justify-center -mt-1">
                          <span className={`text-[14px] font-mono font-bold tabular-nums leading-tight ${
                            cell.pnl > 0 ? 'text-[#00d4aa]' : cell.pnl < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]'
                          }`}>
                            {cell.pnl > 0 ? '+' : cell.pnl < 0 ? '-' : ''}${Math.abs(cell.pnl ?? 0).toFixed(0)}
                          </span>
                          <span className="text-[10px] text-[#8d91a6] mt-0.5">
                            {cell.trade_count} {cell.trade_count === 1 ? 'trade' : 'trades'}
                            {cell.wins != null && <> · <span className="text-[#00d4aa]">{cell.wins}W</span> <span className="text-[#de576f]">{cell.losses}L</span></>}
                          </span>
                        </div>
                      )}
                    </div>
                  )
                )}
                {/* Weekly total */}
                <div className="h-[84px] rounded-lg border border-[#232529] bg-[#191b1e] flex flex-col items-center justify-center gap-1">
                  {traded.length > 0 ? (
                    <>
                      <span className={`text-[13px] font-mono font-bold tabular-nums ${weekPnl >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                        {weekPnl >= 0 ? '+' : '-'}${Math.abs(weekPnl).toFixed(0)}
                      </span>
                      <span className="text-[10px]">
                        <span className="text-[#00d4aa]">{weekWins}W</span>
                        <span className="text-[#4e5166]"> · </span>
                        <span className="text-[#de576f]">{weekLosses}L</span>
                      </span>
                    </>
                  ) : (
                    <span className="text-[10px] text-[#33353c]">—</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
