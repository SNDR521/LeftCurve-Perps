import { useQuery } from '@tanstack/react-query'
import { useDashboard } from '../dashboard/DashboardContext'
import {
  DollarSign, TrendingUp, Target, BarChart3, Clock, Zap,
  ArrowUpRight, ArrowDownRight, Activity,
} from 'lucide-react'

const ICONS = { DollarSign, TrendingUp, Target, BarChart3, Clock, Zap, ArrowUpRight, ArrowDownRight, Activity }

export default function StatCardWidget({ metricKey, label, format, icon }) {
  const { queryParams, convertVal, viewFmt, fetchers } = useDashboard()

  const { data: overview } = useQuery({
    queryKey: ['overview', queryParams],
    queryFn: () => fetchers.fetchOverview(queryParams),
  })

  const rawVal = overview?.[metricKey]
  const isCurrency = format === 'currency'
  const val = isCurrency ? convertVal(rawVal) : rawVal
  const fmt = isCurrency ? viewFmt() : format
  const formatted = formatValue(val, fmt)

  const isPositive = (fmt === 'currency' || fmt === 'percent') && val > 0
  const isNegative = (fmt === 'currency' || fmt === 'percent') && val < 0

  const Icon = ICONS[icon]

  return (
    <div className="h-full flex flex-col justify-center px-1">
      <div className="flex items-start justify-between mb-1">
        <p className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.05em] leading-tight">
          {label}
        </p>
        {Icon && (
          <div className={`w-6 h-6 rounded-md flex items-center justify-center shrink-0 ${
            isPositive ? 'bg-[#00d4aa]/10' : isNegative ? 'bg-[#de576f]/10' : 'bg-[#38bdf8]/10'
          }`}>
            <Icon className={`w-3 h-3 ${
              isPositive ? 'text-[#00d4aa]' : isNegative ? 'text-[#de576f]' : 'text-[#38bdf8]'
            }`} />
          </div>
        )}
      </div>
      <p className={`text-[18px] font-semibold font-mono tracking-tight ${
        isPositive ? 'text-[#00d4aa]' : isNegative ? 'text-[#de576f]' : 'text-white'
      }`}>
        {formatted}
      </p>
    </div>
  )
}

function formatValue(value, format) {
  if (value === null || value === undefined) return '—'
  switch (format) {
    case 'currency': {
      const abs = Math.abs(value)
      const str = abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      return value < 0 ? `-$${str}` : `$${str}`
    }
    case 'percent': return `${value.toFixed(1)}%`
    case 'ratio': return value === Infinity ? '∞' : value.toFixed(2)
    case 'integer': return Math.round(value).toLocaleString()
    case 'r': return value != null ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}R` : '—'
    default: return String(value)
  }
}
