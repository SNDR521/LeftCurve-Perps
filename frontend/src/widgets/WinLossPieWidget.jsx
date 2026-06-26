import { useQuery } from '@tanstack/react-query'
import { useDashboard } from '../dashboard/DashboardContext'
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'

export default function WinLossPieWidget() {
  const { queryParams, fetchers } = useDashboard()

  const { data: m } = useQuery({
    queryKey: ['overview', queryParams],
    queryFn: () => fetchers.fetchOverview(queryParams),
  })

  if (!m?.total_trades) {
    return <div className="h-full flex items-center justify-center text-[#4e5166] text-sm">No data</div>
  }

  const pieData = [
    { name: 'Wins',   value: m.winning_trades || 0, color: '#00d4aa' },
    { name: 'Losses', value: m.losing_trades  || 0, color: '#de576f' },
    { name: 'BE',     value: m.total_trades - (m.winning_trades || 0) - (m.losing_trades || 0), color: '#4e5166' },
  ].filter(d => d.value > 0)

  return (
    <div className="h-full flex flex-col items-center justify-center gap-2">
      <div className="relative w-full flex-1 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={pieData} cx="50%" cy="50%" innerRadius="55%" outerRadius="80%"
              paddingAngle={3} dataKey="value" strokeWidth={0}>
              {pieData.map((e, i) => <Cell key={i} fill={e.color} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-[14px] font-bold text-white font-mono">{m.win_rate?.toFixed(0)}%</span>
          <span className="text-[8px] text-[#4e5166]">Win Rate</span>
        </div>
      </div>
      <div className="flex gap-4 pb-1">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-sm bg-[#00d4aa]" />
          <span className="text-[10px] text-[#8d91a6]">{m.winning_trades} W</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-sm bg-[#de576f]" />
          <span className="text-[10px] text-[#8d91a6]">{m.losing_trades} L</span>
        </div>
      </div>
    </div>
  )
}
