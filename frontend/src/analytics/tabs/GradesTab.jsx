import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { fmt$, Loading, Empty, ErrorBox, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

const GRADE_META = {
  A: { color: '#00d4aa', label: 'Perfect — followed plan exactly' },
  B: { color: '#38bdf8', label: 'Good — minor deviations' },
  C: { color: '#f59e0b', label: 'Average — notable mistakes' },
  D: { color: '#de576f', label: 'Poor — broke the rules' },
  Ungraded: { color: '#4e5166', label: 'No grade assigned' },
}

export default function GradesTab({ tabKey, params, fetch, normalize }) {
  const { data: grades = [], isLoading, isError } = useQuery({
    queryKey: [tabKey, params],
    queryFn: () => fetch(params),
    select: normalize,
  })

  if (isLoading) return <Loading />
  if (isError) return <ErrorBox />
  if (!grades.length) return <Empty>No graded trades yet — grade trades in the trade detail view.</Empty>

  const graded = grades.filter(g => g.grade !== 'Ungraded')

  const onExport = () => downloadCsv(
    'grades',
    ['Grade', 'Trades', 'Win %', 'Avg P&L', 'Total P&L', 'Profit Factor'],
    grades.map((g) => [g.grade, g.count, g.win_rate, g.avg_pnl, g.total_pnl, g.profit_factor]),
  )

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <ExportButton onClick={onExport} disabled={!grades.length} />
      </div>
      {/* Grade cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {graded.map(g => {
          const meta = GRADE_META[g.grade] || GRADE_META.Ungraded
          return (
            <div key={g.grade} className="card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[28px] font-bold" style={{ color: meta.color }}>{g.grade}</span>
                <span className="text-[11px] text-[#4e5166]">{g.count} trades</span>
              </div>
              <p className="text-[10px] text-[#4e5166]">{meta.label}</p>
              <div className="space-y-1.5 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-[#4e5166]">Win Rate</span>
                  <span className="font-mono text-[#e2e4ef]">{(g.win_rate ?? 0).toFixed(1)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#4e5166]">Avg P&amp;L</span>
                  <span className={`font-mono ${(g.avg_pnl ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>{fmt$(g.avg_pnl)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#4e5166]">Total P&amp;L</span>
                  <span className={`font-mono font-semibold ${(g.total_pnl ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>{fmt$(g.total_pnl)}</span>
                </div>
              </div>
              <div className="h-1.5 bg-[#2a2c30] rounded-full overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${g.win_rate ?? 0}%`, background: meta.color }} />
              </div>
            </div>
          )
        })}
      </div>

      {/* Bar chart */}
      {graded.length > 0 && (
        <div className="card p-5">
          <h3 className="text-[13px] font-semibold text-[#8d91a6] mb-4">Avg P&amp;L by Grade</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={graded} margin={{ left: -10, right: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#242629" vertical={false} />
              <XAxis dataKey="grade" tick={{ fill: '#4e5166', fontSize: 12 }} stroke="transparent" tickLine={false} />
              <YAxis tick={{ fill: '#4e5166', fontSize: 10 }} tickFormatter={v => `$${v}`} stroke="transparent" tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e2024', border: '1px solid #2a2c30', borderRadius: '10px', fontSize: '12px', padding: '8px 12px' }}
                cursor={{ fill: 'rgb(var(--accent-rgb)/0.05)' }}
                formatter={v => [fmt$(v), 'Avg P&L']}
              />
              <Bar dataKey="avg_pnl" radius={[4, 4, 0, 0]} maxBarSize={60}>
                {graded.map(g => <Cell key={g.grade} fill={GRADE_META[g.grade]?.color || '#4e5166'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2c30]">
                {['Grade', 'Trades', 'Win %', 'Avg P&L', 'Total P&L', 'Profit Factor'].map(h => (
                  <th key={h} className={`px-4 py-3 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] ${h === 'Grade' ? 'text-left' : 'text-right'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2c30]/50">
              {grades.map(g => {
                const color = GRADE_META[g.grade]?.color || '#4e5166'
                return (
                  <tr key={g.grade} className="hover:bg-[#242629] transition-colors">
                    <td className="px-4 py-3">
                      <span className="text-[14px] font-bold" style={{ color }}>{g.grade}</span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[12px] text-[#8d91a6]">{g.count}</td>
                    <td className="px-4 py-3 text-right font-mono text-[12px] text-[#8d91a6]">{(g.win_rate ?? 0).toFixed(1)}%</td>
                    <td className={`px-4 py-3 text-right font-mono text-[12px] ${(g.avg_pnl ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>{fmt$(g.avg_pnl)}</td>
                    <td className={`px-4 py-3 text-right font-mono text-[13px] font-semibold ${(g.total_pnl ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>{fmt$(g.total_pnl)}</td>
                    <td className="px-4 py-3 text-right font-mono text-[12px] text-[#8d91a6]">
                      {g.profit_factor != null ? g.profit_factor.toFixed(2) : g.count > 0 ? '∞' : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
