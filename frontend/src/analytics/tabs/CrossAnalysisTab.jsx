import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import {
  Lightbulb, TrendingUp, TrendingDown, ArrowUpDown,
} from 'lucide-react'
import { fmt$, pnlColor, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

export default function CrossAnalysisTab({ params, ns = 'cross', fetchDimensions, fetchCross, fetchInsights }) {
  const [primary, setPrimary] = useState('setup')
  const [secondary, setSecondary] = useState('')
  const [sortKey, setSortKey] = useState('total_pnl')
  const [sortDir, setSortDir] = useState('desc')

  const { data: dims = [] } = useQuery({ queryKey: [ns, 'dimensions'], queryFn: fetchDimensions })

  const { data: crossData, isLoading } = useQuery({
    queryKey: [ns, 'cross', primary, secondary, params],
    queryFn: () => fetchCross({ primary, ...(secondary && { secondary }), ...params }),
    enabled: !!primary,
  })

  const { data: insights = [] } = useQuery({
    queryKey: [ns, 'insights', params],
    queryFn: () => fetchInsights(params),
  })

  const sortedGroups = useMemo(() => {
    if (!crossData?.groups) return []
    return [...crossData.groups].sort((a, b) => {
      const av = a[sortKey] ?? 0
      const bv = b[sortKey] ?? 0
      return sortDir === 'desc' ? bv - av : av - bv
    })
  }, [crossData, sortKey, sortDir])

  const chartData = useMemo(() => {
    if (!crossData?.primary_totals) return []
    return Object.entries(crossData.primary_totals)
      .map(([key, metrics]) => ({ group: key, ...metrics }))
      .sort((a, b) => b.total_pnl - a.total_pnl)
  }, [crossData])

  function toggleSort(key) {
    if (sortKey === key) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortKey(key); setSortDir('desc') }
  }

  function exportCSV() {
    if (!sortedGroups.length) return
    const headers = secondary
      ? ['Primary', 'Secondary', 'Trades', 'Win %', 'Total P&L', 'Avg P&L', 'PF', 'Avg R', 'Best', 'Worst']
      : ['Group', 'Trades', 'Win %', 'Total P&L', 'Avg P&L', 'PF', 'Avg R', 'Best', 'Worst']
    const rows = sortedGroups.map((g) => secondary
      ? [g.primary, g.secondary, g.trade_count, g.win_rate, g.total_pnl, g.avg_pnl, g.profit_factor, g.avg_r ?? '', g.best_trade, g.worst_trade]
      : [g.primary, g.trade_count, g.win_rate, g.total_pnl, g.avg_pnl, g.profit_factor, g.avg_r ?? '', g.best_trade, g.worst_trade])
    downloadCsv(`${ns}_${primary}${secondary ? '_x_' + secondary : ''}`, headers, rows)
  }

  const colDefs = [
    ...(secondary ? [{ key: 'secondary', label: 'Secondary', align: 'left' }] : []),
    { key: 'trade_count', label: 'Trades', align: 'right' },
    { key: 'win_rate', label: 'Win %', align: 'right' },
    { key: 'total_pnl', label: 'Total P&L', align: 'right' },
    { key: 'avg_pnl', label: 'Avg P&L', align: 'right' },
    { key: 'profit_factor', label: 'PF', align: 'right' },
    { key: 'avg_r', label: 'Avg R', align: 'right' },
    { key: 'best_trade', label: 'Best', align: 'right' },
    { key: 'worst_trade', label: 'Worst', align: 'right' },
  ]

  return (
    <div className="space-y-5">
      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <div>
          <label className="block text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] mb-1">Group by</label>
          <select value={primary} onChange={(e) => setPrimary(e.target.value)} className="input">
            {dims.map(d => <option key={d.key} value={d.key}>{d.label}</option>)}
          </select>
        </div>
        <div className="text-[#4e5166] text-lg pt-4">×</div>
        <div>
          <label className="block text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] mb-1">Cross with (optional)</label>
          <select value={secondary} onChange={(e) => setSecondary(e.target.value)} className="input">
            <option value="">None</option>
            {dims.filter(d => d.key !== primary).map(d => (
              <option key={d.key} value={d.key}>{d.label}</option>
            ))}
          </select>
        </div>
        <div className="ml-auto pt-4">
          <ExportButton onClick={exportCSV} disabled={!sortedGroups.length} />
        </div>
      </div>

      {/* Insights */}
      {insights.length > 0 && (
        <div className="card p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Lightbulb className="w-4 h-4 text-amber-400" />
            <h3 className="text-[13px] font-semibold text-[#8d91a6]">Auto-detected insights</h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {insights.map((ins, i) => (
              <div key={i} className={`flex items-start gap-2.5 p-3 rounded-lg ${
                ins.type === 'positive' ? 'bg-[#00d4aa]/5 border border-[#00d4aa]/10' : 'bg-[#de576f]/5 border border-[#de576f]/10'
              }`}>
                {ins.type === 'positive'
                  ? <TrendingUp className="w-4 h-4 text-[#00d4aa] shrink-0 mt-0.5" />
                  : <TrendingDown className="w-4 h-4 text-[#de576f] shrink-0 mt-0.5" />}
                <div>
                  <p className={`text-[12px] font-medium ${ins.type === 'positive' ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                    {ins.message}
                  </p>
                  <p className="text-[10px] text-[#4e5166] mt-0.5">{ins.primary_dim} × {ins.secondary_dim}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Bar chart */}
      <div className="card p-5">
        <h3 className="text-[13px] font-semibold text-[#8d91a6] mb-4">
          P&L by {dims.find(d => d.key === primary)?.label || primary}
        </h3>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} margin={{ left: -10, right: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#242629" vertical={false} />
              <XAxis dataKey="group" tick={{ fill: '#4e5166', fontSize: 10 }} stroke="transparent" tickLine={false} />
              <YAxis tick={{ fill: '#4e5166', fontSize: 10 }} tickFormatter={v => `$${v}`}
                stroke="transparent" tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e2024', border: '1px solid #2a2c30', borderRadius: '10px', fontSize: '12px', padding: '8px 12px' }}
                cursor={{ fill: 'rgba(79, 110, 247, 0.05)' }}
                formatter={v => [`$${v.toFixed(2)}`, 'P&L']}
              />
              <Bar dataKey="total_pnl" radius={[4, 4, 0, 0]} maxBarSize={50}>
                {chartData.map((e, i) => <Cell key={i} fill={e.total_pnl >= 0 ? '#00d4aa' : '#de576f'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[280px] flex items-center justify-center text-[#4e5166] text-sm">
            {isLoading ? <div className="skeleton-shimmer w-full h-full" /> : 'No data'}
          </div>
        )}
      </div>

      {/* Table */}
      {sortedGroups.length > 0 && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2c30]">
                <th onClick={() => toggleSort('primary')}
                  className="px-4 py-3 text-left text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] cursor-pointer hover:text-[#8d91a6]">
                  <span className="inline-flex items-center gap-1">
                    {dims.find(d => d.key === primary)?.label || 'Group'}
                    {sortKey === 'primary' && <ArrowUpDown className="w-3 h-3 text-[var(--accent)]" />}
                  </span>
                </th>
                {colDefs.map(col => (
                  <th key={col.key} onClick={() => toggleSort(col.key)}
                    className={`px-3 py-3 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] cursor-pointer hover:text-[#8d91a6] ${col.align === 'right' ? 'text-right' : 'text-left'}`}>
                    <span className="inline-flex items-center gap-1">
                      {col.label}
                      {sortKey === col.key && <ArrowUpDown className="w-3 h-3 text-[var(--accent)]" />}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2c30]/50">
              {sortedGroups.map((g, i) => (
                <tr key={i} className="hover:bg-[#242629] transition-colors">
                  <td className="px-4 py-2.5 font-medium text-white text-[13px]">{g.primary}</td>
                  {secondary && <td className="px-3 py-2.5 text-[12px] text-[#8d91a6]">{g.secondary}</td>}
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-[#8d91a6]">{g.trade_count}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-[#8d91a6]">{g.win_rate?.toFixed(1)}%</td>
                  <td className={`px-3 py-2.5 text-right font-mono text-[13px] font-semibold ${g.total_pnl >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                    {g.total_pnl >= 0 ? '+' : ''}${g.total_pnl?.toFixed(2)}
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono text-[12px] ${g.avg_pnl >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                    ${g.avg_pnl?.toFixed(2)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-[#8d91a6]">
                    {g.profit_factor == null || g.profit_factor === Infinity ? '∞' : g.profit_factor.toFixed(2)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-[#8d91a6]">
                    {g.avg_r != null ? `${g.avg_r >= 0 ? '+' : ''}${g.avg_r.toFixed(2)}R` : '—'}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-[#00d4aa]">${g.best_trade?.toFixed(2)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-[#de576f]">${g.worst_trade?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}

      {/* Overall summary */}
      {crossData?.overall && crossData.overall.trade_count > 0 && (
        <div className="card p-4">
          <div className="flex items-center gap-6 text-[12px] text-[#4e5166]">
            <span>Overall: <strong className="text-white">{crossData.overall.trade_count}</strong> trades</span>
            <span>Win rate: <strong className="text-white">{crossData.overall.win_rate}%</strong></span>
            <span>P&L: <strong className={crossData.overall.total_pnl >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}>
              ${crossData.overall.total_pnl?.toFixed(2)}
            </strong></span>
            <span>PF: <strong className="text-white">{crossData.overall.profit_factor == null || crossData.overall.profit_factor === Infinity ? '∞' : crossData.overall.profit_factor.toFixed(2)}</strong></span>
          </div>
        </div>
      )}
    </div>
  )
}
