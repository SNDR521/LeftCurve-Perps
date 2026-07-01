import { useQuery } from '@tanstack/react-query'
import { useDashboard } from '../dashboard/DashboardContext'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { useMemo } from 'react'

const TITLES = {
  symbol: 'P&L by Symbol',
  weekday: 'P&L by Weekday',
  hour: 'P&L by Hour',
  direction: 'Long vs Short',
}

export default function PnlBarWidget({ groupBy = 'symbol' }) {
  const { queryParams, view, BALANCE, oneR, chartSuffix, fetchers } = useDashboard()

  const { data } = useQuery({
    queryKey: [`perf-${groupBy}`, queryParams],
    queryFn: () => fetchers.fetchPerformance(groupBy, queryParams),
  })

  const transformed = useMemo(() => {
    if (!data) return null
    if (view === 'Dollars') return data
    // Guard the denominator: a perps account with no balance history (Percentage)
    // or no journaled risk (R-Multiple) has no basis to convert against — render
    // no data rather than Infinity/NaN bars.
    const denom = view === 'Percentage' ? BALANCE : oneR
    if (!denom) return []
    return data.map(d => ({
      ...d,
      total_pnl: view === 'Percentage' ? (d.total_pnl / denom) * 100 : d.total_pnl / denom,
    }))
  }, [data, view, BALANCE, oneR])

  const tickFmt = (v) => chartSuffix === '$' ? `$${v}` : chartSuffix === 'R' ? `${v.toFixed(1)}R` : `${v.toFixed(1)}%`
  const tooltipFmt = (v) => [tickFmt(v), 'P&L']

  return (
    <div className="h-full flex flex-col">
      <span className="text-[12px] font-semibold text-[#8d91a6] mb-2 px-1">{TITLES[groupBy] || groupBy}</span>
      <div className="flex-1 min-h-0">
        {transformed?.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={transformed} margin={{ left: -10, right: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#242629" vertical={false} />
              <XAxis dataKey="group" tick={{ fill: '#4e5166', fontSize: 10 }} stroke="transparent" tickLine={false} />
              <YAxis tick={{ fill: '#4e5166', fontSize: 10 }} tickFormatter={tickFmt} stroke="transparent" tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ backgroundColor: '#1e2024', border: '1px solid #2a2c30', borderRadius: '10px', fontSize: '12px', padding: '8px 12px', color: '#e2e4ef' }}
                labelStyle={{ color: '#e2e4ef' }} itemStyle={{ color: '#e2e4ef' }}
                cursor={{ fill: 'rgba(79, 110, 247, 0.05)' }} formatter={tooltipFmt} />
              <Bar dataKey="total_pnl" radius={[4, 4, 0, 0]} maxBarSize={40}>
                {transformed.map((e, i) => <Cell key={i} fill={e.total_pnl >= 0 ? '#00d4aa' : '#de576f'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full flex items-center justify-center text-[#4e5166] text-sm">No data</div>
        )}
      </div>
    </div>
  )
}
