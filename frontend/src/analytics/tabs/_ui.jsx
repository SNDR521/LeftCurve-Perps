import { Download } from 'lucide-react'

export const pnlColor = (v) => (v > 0 ? 'text-[#00d4aa]' : v < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]')

export function fmt$(n) {
  if (n == null) return '—'
  const abs = Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n < 0 ? `-$${abs}` : `$${abs}`
}

export const fmtNum = (v, d = 2) => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }))

export const TH = ({ children, right }) => (
  <th className={`px-4 py-3 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] ${right ? 'text-right' : 'text-left'}`}>
    {children}
  </th>
)

export const Loading = () => <div className="skeleton-shimmer h-40 w-full rounded-lg" />
export const Empty = ({ children = 'No data yet' }) => (
  <p className="px-5 py-8 text-center text-[#4e5166] text-[13px]">{children}</p>
)
export const ErrorBox = ({ children = 'Failed to load — try again.' }) => (
  <p className="px-5 py-8 text-center text-[#de576f] text-[13px]">{children}</p>
)

export const ExportButton = ({ onClick, disabled }) => (
  <button onClick={onClick} disabled={disabled}
    className="btn-ghost text-[12px] border border-[#2a2c30] flex items-center gap-1.5 disabled:opacity-30">
    <Download className="w-3.5 h-3.5" /> Export CSV
  </button>
)
