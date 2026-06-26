import { useMemo } from 'react'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function CalendarHeatmap({ data = [], year, month }) {
  const grid = useMemo(() => {
    const lookup = {}
    data.forEach((d) => { lookup[d.date] = d })

    const firstDay = new Date(year, month, 1)
    const lastDay = new Date(year, month + 1, 0)
    const days = []

    const startDow = (firstDay.getDay() + 6) % 7
    for (let i = 0; i < startDow; i++) days.push(null)

    for (let d = 1; d <= lastDay.getDate(); d++) {
      const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
      days.push({ day: d, date: dateStr, ...(lookup[dateStr] || { pnl: 0, trade_count: 0 }) })
    }
    return days
  }, [data, year, month])

  const maxAbs = useMemo(() => {
    const vals = data.map((d) => Math.abs(d.pnl)).filter(Boolean)
    return Math.max(...vals, 1)
  }, [data])

  function cellStyle(pnl) {
    if (!pnl || pnl === 0) return { backgroundColor: '#1e2024' }
    const intensity = Math.min(Math.abs(pnl) / maxAbs, 1)
    const alpha = 0.12 + intensity * 0.55
    return {
      backgroundColor: pnl > 0 ? `rgba(0, 212, 170, ${alpha})` : `rgba(255, 90, 90, ${alpha})`,
    }
  }

  return (
    <div>
      <div className="grid grid-cols-7 gap-1.5 mb-1.5">
        {WEEKDAYS.map((d) => (
          <div key={d} className="text-center text-[10px] font-medium text-[#4e5166] py-1">{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1.5">
        {grid.map((cell, i) =>
          cell === null ? (
            <div key={`e-${i}`} className="aspect-square" />
          ) : (
            <div
              key={cell.date}
              className="aspect-square rounded-lg flex flex-col items-center justify-center cursor-default
                         transition-transform duration-100 hover:scale-[1.08] relative group"
              style={cellStyle(cell.pnl)}
              title={`${cell.date}: $${cell.pnl?.toFixed(2) || '0'} (${cell.trade_count || 0} trades)`}
            >
              <span className="text-[10px] text-[#4e5166] font-medium">{cell.day}</span>
              {cell.trade_count > 0 && (
                <span className={`text-[9px] font-mono font-semibold ${
                  cell.pnl > 0 ? 'text-[#00d4aa]' : cell.pnl < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]'
                }`}>
                  {cell.pnl > 0 ? '+' : ''}{cell.pnl?.toFixed(0)}
                </span>
              )}
              {/* Tooltip on hover */}
              <div className="absolute bottom-full mb-1 hidden group-hover:block z-10">
                <div className="bg-[#1e2024] border border-[#2a2c30] rounded-lg px-2.5 py-1.5 text-[10px]
                                shadow-xl whitespace-nowrap">
                  <span className="text-[#8d91a6]">{cell.date}</span>
                  <span className="mx-1 text-[#2a2c30]">|</span>
                  <span className={cell.pnl > 0 ? 'text-[#00d4aa]' : cell.pnl < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]'}>
                    ${cell.pnl?.toFixed(2)}
                  </span>
                  <span className="mx-1 text-[#2a2c30]">|</span>
                  <span className="text-[#8d91a6]">{cell.trade_count} trades</span>
                </div>
              </div>
            </div>
          )
        )}
      </div>
    </div>
  )
}
