import { useQuery } from '@tanstack/react-query'
import { pnlColor, fmt$, TH, Loading, Empty, ErrorBox, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

export default function GroupTab({ tabKey, params, fetch, normalize, title, labelHeader = 'Group' }) {
  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: [tabKey, params], queryFn: () => fetch(params), select: normalize,
  })
  if (isLoading) return <Loading />
  if (isError) return <ErrorBox />
  const onExport = () => downloadCsv(
    `${labelHeader}`,
    [labelHeader, 'Trades', 'Win %', 'Total P&L', 'Avg P&L', 'Profit Factor'],
    rows.map((r) => [r.label ?? '—', r.trade_count, r.win_rate, r.total_pnl, r.avg_pnl, r.profit_factor]),
  )
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-4 border-b border-[#2a2c30] flex items-center justify-between gap-3">
        <h2 className="text-[14px] font-semibold text-white">{title || labelHeader}</h2>
        <ExportButton onClick={onExport} disabled={!rows.length} />
      </div>
      {rows.length === 0 ? <Empty /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead><tr className="text-[#4e5166] border-b border-[#2a2c30]">
              <TH>{labelHeader}</TH><TH right>Trades</TH><TH right>Win %</TH>
              <TH right>Total P&amp;L</TH><TH right>Avg P&amp;L</TH><TH right>Profit Factor</TH>
            </tr></thead>
            <tbody className="divide-y divide-[#2a2c30]/50">
              {rows.map((r, i) => (
                <tr key={i} className="hover:bg-[#242629] transition-colors">
                  <td className="px-4 py-3 font-medium text-white">{r.label ?? '—'}</td>
                  <td className="px-4 py-3 text-right font-mono text-[#8d91a6]">{r.trade_count}</td>
                  <td className="px-4 py-3 text-right font-mono text-[#8d91a6]">{r.trade_count > 0 ? `${Number(r.win_rate).toFixed(1)}%` : '—'}</td>
                  <td className={`px-4 py-3 text-right font-mono font-semibold ${pnlColor(r.total_pnl)}`}>{r.trade_count > 0 ? fmt$(r.total_pnl) : '—'}</td>
                  <td className={`px-4 py-3 text-right font-mono ${pnlColor(r.avg_pnl)}`}>{r.trade_count > 0 ? fmt$(r.avg_pnl) : '—'}</td>
                  <td className="px-4 py-3 text-right font-mono text-[#8d91a6]">{r.trade_count > 0 ? (r.profit_factor == null || r.profit_factor === Infinity ? '∞' : Number(r.profit_factor).toFixed(2)) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
