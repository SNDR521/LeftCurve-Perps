import { TrendingUp, TrendingDown } from 'lucide-react'

export default function StatWidget({ label, value, format = 'text', icon: Icon, subtitle }) {
  const formatted = formatValue(value, format)
  const isPositive = (format === 'currency' || format === 'percent') && value > 0
  const isNegative = (format === 'currency' || format === 'percent') && value < 0

  return (
    <div className="stat-card group">
      <div className="flex items-start justify-between mb-2">
        <p className="text-[11px] font-medium text-[#8d91a6] uppercase tracking-[0.05em]">
          {label}
        </p>
        {Icon && (
          <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${
            isPositive ? 'bg-[#00d4aa]/10' : isNegative ? 'bg-[#de576f]/10' : 'bg-[rgb(var(--accent-rgb)/0.1)]'
          }`}>
            <Icon className={`w-3.5 h-3.5 ${
              isPositive ? 'text-[#00d4aa]' : isNegative ? 'text-[#de576f]' : 'text-[var(--accent)]'
            }`} />
          </div>
        )}
      </div>
      <p className={`text-xl font-semibold font-mono tracking-tight ${
        isPositive ? 'text-[#00d4aa]' : isNegative ? 'text-[#de576f]' : 'text-white'
      }`}>
        {formatted}
      </p>
      {subtitle && (
        <p className="text-[11px] text-[#4e5166] mt-1">{subtitle}</p>
      )}
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
    case 'percent':
      return `${value.toFixed(1)}%`
    case 'ratio':
      return value === Infinity ? '∞' : value.toFixed(2)
    case 'integer':
      return Math.round(value).toLocaleString()
    case 'r':
      return value != null ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}R` : '—'
    case 'duration': {
      if (!value) return '—'
      const h = Math.floor(value / 3600)
      const m = Math.floor((value % 3600) / 60)
      return h > 0 ? `${h}h ${m}m` : `${m}m`
    }
    default:
      return String(value)
  }
}
