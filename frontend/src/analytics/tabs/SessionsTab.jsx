import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { pnlColor, fmt$, Loading, Empty, ErrorBox, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

const SESSION_COLORS = {
  'New York': '#38bdf8',
  'London':   '#f7c948',
  'Tokyo':    '#e06bff',
  'Off-hours':'#4e5166',
}

export default function SessionsTab({ tabKey, params, fetch, normalize }) {
  const { data: sessions = [], isLoading, isError } = useQuery({
    queryKey: [tabKey, params],
    queryFn: () => fetch(params),
    select: normalize,
  })

  if (isLoading) return <Loading />
  if (isError) return <ErrorBox />

  const active = sessions.filter(s => s.trade_count > 0)

  if (sessions.length === 0) return <Empty>No session data yet.</Empty>

  const onExport = () => downloadCsv(
    'sessions',
    ['Session', 'UTC Hours', 'Trades', 'Win %', 'Total P&L', 'Avg P&L', 'Best', 'Worst'],
    sessions.map((s) => [s.session, s.utc_hours ?? '', s.trade_count, s.win_rate, s.total_pnl, s.avg_pnl, s.best_trade, s.worst_trade]),
  )

  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <ExportButton onClick={onExport} disabled={!sessions.length} />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {sessions.map(s => {
          const color = SESSION_COLORS[s.session] || '#4e5166'
          const pnlPos = s.total_pnl >= 0
          return (
            <div key={s.session} className="card p-4 space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
                <span className="text-[13px] font-semibold text-white">{s.session}</span>
              </div>
              {s.utc_hours != null && (
                <p className="text-[10px] text-[#4e5166]">{s.utc_hours}</p>
              )}
              {s.trade_count === 0 ? (
                <p className="text-[12px] text-[#4e5166]">No trades</p>
              ) : (
                <div className="space-y-2">
                  <p className={`text-[20px] font-semibold font-mono ${pnlPos ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                    {fmt$(s.total_pnl)}
                  </p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                    <span className="text-[#4e5166]">Trades</span>
                    <span className="text-right text-[#e2e4ef] font-mono">{s.trade_count}</span>
                    <span className="text-[#4e5166]">Win %</span>
                    <span className="text-right text-[#e2e4ef] font-mono">{(s.win_rate ?? 0).toFixed(1)}%</span>
                    <span className="text-[#4e5166]">Avg</span>
                    <span className={`text-right font-mono ${s.avg_pnl >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                      {fmt$(s.avg_pnl)}
                    </span>
                    {s.best_trade != null && (
                      <>
                        <span className="text-[#4e5166]">Best</span>
                        <span className="text-right text-[#00d4aa] font-mono">{fmt$(s.best_trade)}</span>
                      </>
                    )}
                    {s.worst_trade != null && (
                      <>
                        <span className="text-[#4e5166]">Worst</span>
                        <span className="text-right text-[#de576f] font-mono">{fmt$(s.worst_trade)}</span>
                      </>
                    )}
                  </div>
                  {/* Win rate bar */}
                  <div className="h-1.5 bg-[#2a2c30] rounded-full overflow-hidden mt-1">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${s.win_rate ?? 0}%`, background: color }}
                    />
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {active.length > 0 && (
        <div className="card p-5">
          <h3 className="text-[13px] font-semibold text-[#8d91a6] mb-4">Session Comparison</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={active} margin={{ left: -10, right: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#242629" vertical={false} />
              <XAxis dataKey="session" tick={{ fill: '#4e5166', fontSize: 11 }} stroke="transparent" tickLine={false} />
              <YAxis tick={{ fill: '#4e5166', fontSize: 10 }} tickFormatter={v => `$${v}`}
                stroke="transparent" tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e2024', border: '1px solid #2a2c30', borderRadius: '10px', fontSize: '12px', padding: '8px 12px' }}
                cursor={{ fill: 'rgba(79,110,247,0.05)' }}
                formatter={v => [`$${(+v).toFixed(2)}`, 'P&L']}
              />
              <Bar dataKey="total_pnl" radius={[4, 4, 0, 0]} maxBarSize={60}>
                {active.map((s) => (
                  <Cell key={s.session} fill={SESSION_COLORS[s.session] || '#4e5166'} fillOpacity={0.8} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
