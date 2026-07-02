import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts'
import { useDashboard } from '../dashboard/DashboardContext'

function fmt(n) {
  if (n == null) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function RealizedChart({ data, tickFmt }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
        <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#4e5166' }} />
        <YAxis tick={{ fontSize: 10, fill: '#4e5166' }} width={48} tickFormatter={tickFmt} />
        <Tooltip
          contentStyle={{ background: '#1e2024', border: '1px solid #2a2c30', fontSize: 12 }}
          formatter={(v) => [tickFmt(v), 'P&L']}
        />
        <Area type="monotone" dataKey="equity" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.15} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

export default function PerpsEquityWidget() {
  const { queryParams, fetchers, view, BALANCE, oneR, chartSuffix } = useDashboard()
  const [mode, setMode] = useState(() => localStorage.getItem('perps_equity_mode') || 'true')

  const setModePersist = (next) => {
    setMode(next)
    localStorage.setItem('perps_equity_mode', next)
  }

  const { data: realized = [] } = useQuery({
    queryKey: ['perps-drawdown', queryParams],
    queryFn: () => fetchers.fetchDrawdown(queryParams),
  })

  const { data: equity } = useQuery({
    queryKey: ['perps-equity', queryParams.account_id],
    queryFn: () => fetchers.fetchEquity(queryParams),
    enabled: mode === 'true',
  })

  const points = equity?.points ?? []
  const trueHasData = mode === 'true' && points.length > 0

  // Realized P&L follows the dashboard $/%/R selector. True equity is a wallet
  // balance, not a P&L number (transfers would make % returns lie), so it always
  // charts dollars — the title says so when a non-$ view is active.
  const denomMissing = (view === 'Percentage' && !BALANCE) || (view === 'R-Multiple' && !oneR)
  const realizedData = useMemo(() => {
    if (denomMissing) return []
    if (view === 'Percentage') return realized.map((d) => ({ ...d, equity: (d.equity / BALANCE) * 100 }))
    if (view === 'R-Multiple') return realized.map((d) => ({ ...d, equity: d.equity / oneR }))
    return realized
  }, [realized, view, BALANCE, oneR, denomMissing])

  const tickFmt = (v) => chartSuffix === '$'
    ? `$${Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`
    : chartSuffix === 'R' ? `${Number(v).toFixed(1)}R` : `${Number(v).toFixed(1)}%`

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-2 px-1">
        <span className="text-[12px] font-semibold text-[#8d91a6]">
          {trueHasData
            ? `True Equity — wallet balance${view !== 'Dollars' ? ' (always $)' : ''}`
            : 'Cumulative Realized P&L'}
        </span>
        <div className="tab-bar">
          <button onClick={() => setModePersist('true')} className={`tab-item ${mode === 'true' ? 'active' : ''}`}>True equity</button>
          <button onClick={() => setModePersist('realized')} className={`tab-item ${mode === 'realized' ? 'active' : ''}`}>Realized P&amp;L</button>
        </div>
      </div>

      <div className="flex-1 min-h-0">
        {trueHasData ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#4e5166' }} />
              <YAxis tick={{ fontSize: 10, fill: '#4e5166' }} width={48} />
              <Tooltip contentStyle={{ background: '#1e2024', border: '1px solid #2a2c30', fontSize: 12 }} />
              {(equity?.transfers ?? []).map((t, i) => (
                <ReferenceLine
                  key={i}
                  x={t.ts.slice(0, 10)}
                  stroke={t.kind === 'TRANSFER_IN' ? '#00d4aa' : '#de576f'}
                  strokeDasharray="3 3"
                />
              ))}
              <Area type="monotone" dataKey="balance" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.15} />
            </AreaChart>
          </ResponsiveContainer>
        ) : denomMissing ? (
          <div className="h-full flex items-center justify-center text-[#4e5166] text-sm">
            {view === 'Percentage'
              ? 'no period-start balance for % view — run a sync'
              : 'no risk data for R view'}
          </div>
        ) : (
          <RealizedChart data={realizedData} tickFmt={tickFmt} />
        )}
      </div>

      {trueHasData && equity?.stats && (
        <p className="text-[11px] text-[#4e5166] mt-1 px-1">
          Peak ${fmt(equity.stats.peak)} · DD {equity.stats.drawdown_from_peak_pct.toFixed(1)}% · {equity.stats.days_since_high}d since high
        </p>
      )}
      {mode === 'true' && points.length === 0 && (
        <p className="text-[11px] text-[#4e5166] mt-1 px-1">
          no balance history yet — run a sync
        </p>
      )}
    </div>
  )
}
