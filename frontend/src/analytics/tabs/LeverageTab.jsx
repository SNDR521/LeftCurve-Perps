import { useQuery } from '@tanstack/react-query'
import { fetchPerpsLeverage } from '../../lib/api'
import { fmt$, pnlColor, TH, ErrorBox, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

function Insight({ children }) {
  return <p className="text-[15px] text-white leading-relaxed">{children}</p>
}

export default function LeverageTab({ params }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['perps-costs', 'leverage', params],
    queryFn: () => fetchPerpsLeverage(params),
  })

  if (isLoading) return <div className="skeleton-shimmer h-52 w-full rounded-lg" />
  if (isError) return <ErrorBox />

  const buckets = data?.buckets ?? []
  const populated = buckets.filter(b => b.trade_count > 0)

  if (populated.length === 0) {
    return <p className="px-5 py-8 text-center text-[#4e5166] text-[13px]">No leverage data yet.</p>
  }

  // buckets arrive ordered low→high (excluding/including unknown at the end);
  // pick lowest- and highest-leverage populated buckets, excluding "unknown"
  const realPopulated = populated.filter(b => b.bucket !== 'unknown')
  let insight = null
  if (realPopulated.length >= 2) {
    const low = realPopulated[0]
    const high = realPopulated[realPopulated.length - 1]
    insight = (
      <>Win rate {low.bucket}: {Number(low.win_rate).toFixed(0)}% (n={low.trade_count}) vs {high.bucket}: {Number(high.win_rate).toFixed(0)}% (n={high.trade_count}).</>
    )
  }

  return (
    <div className="space-y-4">
      {insight && <Insight>{insight}</Insight>}
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-[#2a2c30] flex items-center justify-between gap-3">
          <h2 className="text-[14px] font-semibold text-white">By Leverage</h2>
          <ExportButton
            onClick={() => downloadCsv('leverage', ['Bucket', 'Trades', 'Win rate', 'Total P&L', 'Avg P&L'],
              buckets.map((r) => [r.bucket, r.trade_count, r.win_rate, r.total_pnl, r.avg_pnl]))}
            disabled={!buckets.length} />
        </div>
        <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-[#4e5166] border-b border-[#2a2c30]">
              <TH>Bucket</TH>
              <TH right>Trades</TH>
              <TH right>Win rate</TH>
              <TH right>Total P&amp;L</TH>
              <TH right>Avg P&amp;L</TH>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#2a2c30]/50">
            {buckets.map(r => (
              <tr key={r.bucket} className="hover:bg-[#242629] transition-colors">
                <td className="px-4 py-3 font-medium text-white">{r.bucket}</td>
                <td className="px-4 py-3 text-right font-mono text-[#8d91a6]">{r.trade_count}</td>
                <td className="px-4 py-3 text-right font-mono text-[#8d91a6]">
                  {r.trade_count > 0 ? `${Number(r.win_rate).toFixed(1)}%` : '—'}
                </td>
                <td className={`px-4 py-3 text-right font-mono font-semibold ${pnlColor(r.total_pnl)}`}>
                  {r.trade_count > 0 ? fmt$(r.total_pnl) : '—'}
                </td>
                <td className={`px-4 py-3 text-right font-mono ${pnlColor(r.avg_pnl)}`}>
                  {r.trade_count > 0 && r.avg_pnl != null ? fmt$(r.avg_pnl) : '—'}
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
