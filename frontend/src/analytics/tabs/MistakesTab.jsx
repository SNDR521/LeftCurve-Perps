import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { fmt$, Loading, Empty, ErrorBox, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

export default function MistakesTab({ tabKey, params, fetch, normalize }) {
  const { data: mistakes = [], isLoading, isError } = useQuery({
    queryKey: [tabKey, params],
    queryFn: () => fetch(params),
    select: normalize,
  })

  if (isLoading) return <Loading />
  if (isError) return <ErrorBox />
  if (!mistakes.length) return <Empty>No mistake tags yet — tag mistakes in the trade journal.</Empty>

  const maxCount = Math.max(...mistakes.map(m => m.count), 1)
  const topMistake = mistakes.reduce((a, b) => (b.count > (a?.count ?? -1) ? b : a), null)?.mistake

  const onExport = () => downloadCsv(
    'mistakes',
    ['Mistake', 'Occurrences', 'Total P&L Impact', 'Avg per Trade', 'Max Streak'],
    mistakes.map((m) => [m.mistake, m.count, m.total_pnl, m.avg_pnl, m.max_streak ?? '']),
  )

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <ExportButton onClick={onExport} disabled={!mistakes.length} />
      </div>
      <div className="card p-5">
        <h3 className="text-[13px] font-semibold text-[#8d91a6] mb-4">P&amp;L Cost by Mistake</h3>
        <ResponsiveContainer width="100%" height={Math.max(200, mistakes.length * 40)}>
          <BarChart data={mistakes} layout="vertical" margin={{ left: 20, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#242629" horizontal={false} />
            <XAxis type="number" tick={{ fill: '#4e5166', fontSize: 10 }} tickFormatter={v => `$${v}`} stroke="transparent" tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="mistake" tick={{ fill: '#8d91a6', fontSize: 11 }} width={100} stroke="transparent" tickLine={false} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e2024', border: '1px solid #2a2c30', borderRadius: '10px', fontSize: '12px', padding: '8px 12px' }}
              cursor={{ fill: 'rgba(222,87,111,0.05)' }}
              formatter={v => [fmt$(v), 'Total P&L']}
            />
            <Bar dataKey="total_pnl" radius={[0, 4, 4, 0]} maxBarSize={20}>
              {mistakes.map(m => <Cell key={m.mistake} fill={(m.total_pnl ?? 0) >= 0 ? '#00d4aa' : '#de576f'} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2c30]">
                {['Mistake', 'Occurrences', 'Frequency', 'Total P&L Impact', 'Avg per Trade', 'Streak'].map(h => (
                  <th key={h} className={`px-4 py-3 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] ${h === 'Mistake' ? 'text-left' : 'text-right'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2c30]/50">
              {mistakes.map(m => {
                const isTop = m.mistake === topMistake
                return (
                <tr key={m.mistake} className={`hover:bg-[#242629] transition-colors ${isTop ? 'bg-[#de576f]/5' : ''}`}>
                  <td className="px-4 py-3">
                    {isTop && <span className="mr-1.5 text-[10px] font-bold text-[#de576f] align-middle">#1</span>}
                    <span className="text-[12px] font-medium text-white px-2 py-0.5 bg-[#de576f]/10 border border-[#de576f]/20 rounded-md">{m.mistake}</span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[12px] text-[#8d91a6]">{m.count}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <div className="w-16 h-1.5 bg-[#2a2c30] rounded-full overflow-hidden">
                        <div className="h-full bg-[#de576f] rounded-full" style={{ width: `${m.count / maxCount * 100}%` }} />
                      </div>
                      <span className="font-mono text-[11px] text-[#4e5166] w-8 text-right">{Math.round(m.count / maxCount * 100)}%</span>
                    </div>
                  </td>
                  <td className={`px-4 py-3 text-right font-mono text-[13px] font-semibold ${(m.total_pnl ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>{fmt$(m.total_pnl)}</td>
                  <td className={`px-4 py-3 text-right font-mono text-[12px] ${(m.avg_pnl ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>{fmt$(m.avg_pnl)}</td>
                  <td className="px-4 py-3 text-right">
                    {m.max_streak != null && m.max_streak >= 3 ? (
                      <span className={`badge text-[10px] ${m.max_streak >= 10
                        ? 'bg-[#de576f] text-white' : 'bg-[#f59e0b]/15 text-[#f59e0b]'}`}>
                        {m.max_streak >= 10 ? '🛑' : '⚠'} {m.max_streak}×
                      </span>
                    ) : (
                      <span className="font-mono text-[11px] text-[#4e5166]">{m.max_streak ?? '—'}{m.max_streak != null ? '×' : ''}</span>
                    )}
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
