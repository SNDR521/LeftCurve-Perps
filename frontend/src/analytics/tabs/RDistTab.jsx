import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { pnlColor, fmt$, Loading, Empty, ErrorBox, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

export default function RDistTab({ tabKey, params, fetch, modes }) {
  // If the adapter passes `modes`, we support the Stored|Actual toggle.
  // Default to the first mode if present, otherwise undefined (prop adapter — no mode arg).
  const [mode, setMode] = useState(() => modes?.[0] ?? null)

  const queryKey = modes ? [tabKey, params, mode] : [tabKey, params]
  const queryFn = modes ? () => fetch(params, mode) : () => fetch(params)

  const { data = [], isLoading, isError } = useQuery({ queryKey, queryFn })

  if (isLoading) return <Loading />
  if (isError) return <ErrorBox />

  // Support both prop shape (label/count/pct) and perps shape (bucket/trade_count)
  const normalised = data.map(b => ({
    label: b.label ?? b.bucket ?? '—',
    count: b.count ?? b.trade_count ?? 0,
    total_pnl: b.total_pnl,
    pct: b.pct,
  }))

  const hasTrades = normalised.some(b => b.count > 0)

  if (!hasTrades) {
    return (
      <div className="card overflow-hidden">
        {modes && (
          <div className="px-5 py-4 border-b border-[#2a2c30]">
            <ModeToggle modes={modes} mode={mode} setMode={setMode} />
          </div>
        )}
        <Empty>No trades with R-multiples yet — set a risk amount on trades to enable this view.</Empty>
      </div>
    )
  }

  const maxCount = Math.max(...normalised.map(b => b.count), 1)

  const onExport = () => downloadCsv(
    'r-distribution',
    ['Bucket', 'Trades', 'Share %', 'Total P&L'],
    normalised.map((b) => [b.label, b.count, b.pct ?? '', b.total_pnl]),
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {modes && <ModeToggle modes={modes} mode={mode} setMode={setMode} />}
        <ExportButton onClick={onExport} disabled={!hasTrades} />
      </div>

      <div className="card p-5">
        <h3 className="text-[13px] font-semibold text-[#8d91a6] mb-1">Trade Outcome Distribution</h3>
        <p className="text-[11px] text-[#4e5166] mb-4">How often your trades land in each R-multiple bucket</p>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={normalised} margin={{ left: -10, right: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#242629" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: '#4e5166', fontSize: 10 }} stroke="transparent" tickLine={false} />
            <YAxis tick={{ fill: '#4e5166', fontSize: 10 }} stroke="transparent" tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e2024', border: '1px solid #2a2c30', borderRadius: '10px', fontSize: '12px', padding: '8px 12px' }}
              cursor={{ fill: 'rgb(var(--accent-rgb)/0.05)' }}
              formatter={(v, _name, props) => {
                const pct = props.payload.pct
                return [pct != null ? `${v} trades (${pct}%)` : `${v} trades`, 'Count']
              }}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={60}>
              {normalised.map((b, i) => (
                <Cell key={i} fill={(b.total_pnl ?? 0) >= 0 ? '#00d4aa' : '#de576f'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2c30]">
                {['Bucket', 'Trades', 'Share', 'Total P&L'].map(h => (
                  <th key={h} className={`px-4 py-3 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] ${h === 'Bucket' ? 'text-left' : 'text-right'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2c30]/50">
              {normalised.map(b => (
                <tr key={b.label} className="hover:bg-[#242629] transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <span className="text-[13px] font-semibold text-white w-20">{b.label}</span>
                      {b.count > 0 && (
                        <div className="flex-1 h-1.5 bg-[#2a2c30] rounded-full overflow-hidden max-w-[100px]">
                          <div className="h-full rounded-full" style={{ width: `${b.count / maxCount * 100}%`, background: (b.total_pnl ?? 0) >= 0 ? '#00d4aa' : '#de576f' }} />
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[12px] text-[#8d91a6]">{b.count || '—'}</td>
                  <td className="px-4 py-3 text-right font-mono text-[12px] text-[#4e5166]">
                    {b.count > 0 && b.pct != null ? `${b.pct}%` : '—'}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono text-[13px] font-semibold ${(b.total_pnl ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'}`}>
                    {b.count > 0 ? fmt$(b.total_pnl) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function ModeToggle({ modes, mode, setMode }) {
  const labels = { stored: 'Stored R', actual: 'Actual R' }
  return (
    <div className="tab-bar">
      {modes.map(m => (
        <button key={m} onClick={() => setMode(m)} className={`tab-item ${mode === m ? 'active' : ''}`}>
          {labels[m] ?? m}
        </button>
      ))}
    </div>
  )
}
