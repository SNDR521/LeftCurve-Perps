import { useQuery } from '@tanstack/react-query'
import { useDashboard } from '../dashboard/DashboardContext'
import { Zap, TrendingDown } from 'lucide-react'

export default function StreaksWidget() {
  const { queryParams, fetchers } = useDashboard()

  const { data: m } = useQuery({
    queryKey: ['overview', queryParams],
    queryFn: () => fetchers.fetchOverview(queryParams),
  })

  return (
    <div className="h-full flex items-center justify-around px-2">
      <div className="text-center">
        <Zap className="w-4 h-4 text-[#00d4aa] mx-auto mb-1" />
        <p className="text-[20px] font-mono font-semibold text-white">{m?.max_consecutive_wins || 0}</p>
        <p className="text-[9px] text-[#4e5166] uppercase">Best streak</p>
      </div>
      <div className="w-px h-10 bg-[#2a2c30]" />
      <div className="text-center">
        <TrendingDown className="w-4 h-4 text-[#de576f] mx-auto mb-1" />
        <p className="text-[20px] font-mono font-semibold text-white">{m?.max_consecutive_losses || 0}</p>
        <p className="text-[9px] text-[#4e5166] uppercase">Worst streak</p>
      </div>
    </div>
  )
}
