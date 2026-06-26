import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { fmt$, Loading, Empty, ErrorBox, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

export default function HoldTimeTab({ tabKey, params, fetch, normalize }) {
  const { data: buckets = [], isLoading, isError } = useQuery({
    queryKey: [tabKey, params],
    queryFn: () => fetch(params),
    select: normalize,
  })

  if (isLoading) return <Loading />
  if (isError) return <ErrorBox />

  if (buckets.length === 0) return <Empty>No hold-time data yet.</Empty>

  const maxPnl = Math.max(...buckets.map(b => Math.abs(b.total_pnl ?? 0)), 1)

  const onExport = () => downloadCsv(
    'hold-time',
    ['Hold Time', 'Trades', 'Win %', 'Total P&L', 'Avg P&L', 'Profit Factor'],
    buckets.map((b) => [b.label, b.trade_count, b.win_rate, b.total_pnl, b.avg_pnl, b.profit_factor]),
  )

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <ExportButton onClick={onExport} disabled={!buckets.length} />
      </div>
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2c30]">
                {['Hold Time', 'Trades', 'Win %', 'Total P&L', 'Avg P&L', 'Profit Factor'].map(h => (
                  <th key={h} className={`px-4 py-3 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] ${h === 'Hold Time' ? 'text-left' : 'text-right'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2c30]/50">
              {buckets.map(b => (
                <tr key={b.label} className="hover:bg-[#242629] transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <span className="text-[13px] font-semibold text-white w-16">{b.label}</span>
                      {b.trade_count > 0 && (
                        <div className="flex-1 h-1.5 bg-[#2a2c30] rounded-full overflow-hidden max-w-[120px]">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.abs(b.total_pnl ?? 0) / maxPnl * 100}%`,
                              background: (b.total_pnl ?? 0) >= 0 ? '#00d4aa' : '#de576f',
                            }}
                          />
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[12px] text-[#8d91a6]">{b.trade_count}</td>
                  <td className="px-4 py-3 text-right font-mono text-[12px] text-[#8d91a6]">
                    {b.trade_count > 0 ? `${(b.win_rate ?? 0).toFixed(1)}%` : '—'}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono text-[13px] font-semibold ${(b.total_pnl ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                    {b.trade_count > 0 ? fmt$(b.total_pnl) : '—'}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono text-[12px] ${(b.avg_pnl ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                    {b.trade_count > 0 ? fmt$(b.avg_pnl) : '—'}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[12px] text-[#8d91a6]">
                    {b.trade_count > 0
                      ? (b.profit_factor == null ? '—' : b.profit_factor === Infinity ? '∞' : b.profit_factor.toFixed(2))
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {buckets.some(b => b.trade_count > 0) && (
        <div className="card p-5">
          <h3 className="text-[13px] font-semibold text-[#8d91a6] mb-4">P&amp;L by Hold Time</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={buckets.filter(b => b.trade_count > 0)} margin={{ left: -10, right: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#242629" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#4e5166', fontSize: 11 }} stroke="transparent" tickLine={false} />
              <YAxis tick={{ fill: '#4e5166', fontSize: 10 }} tickFormatter={v => `$${v}`}
                stroke="transparent" tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e2024', border: '1px solid #2a2c30', borderRadius: '10px', fontSize: '12px', padding: '8px 12px' }}
                cursor={{ fill: 'rgba(79,110,247,0.05)' }}
                formatter={v => [fmt$(v), 'P&L']}
              />
              <Bar dataKey="total_pnl" radius={[4, 4, 0, 0]} maxBarSize={50}>
                {buckets.filter(b => b.trade_count > 0).map(b => (
                  <Cell key={b.label} fill={(b.total_pnl ?? 0) >= 0 ? '#00d4aa' : '#de576f'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
